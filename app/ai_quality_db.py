"""v8 AI Quality — БД-обвязка вокруг чистых функций из ai_quality.py.

Этот модуль делает реальные SQL-запросы и связывает все улучшения
с pipeline'ом chat_analyzer'а. Чистые алгоритмы — в ai_quality.py.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from app.ai_quality import (
    ChatMsg,
    ClassifierDecision,
    BannedTopicHit,
    HallucinationCheck,
    FilterReport,
    build_conversation_block,
    classify_message,
    extract_topic_tokens,
    topics_overlap,
    check_banned_topics,
    check_hallucination,
    filter_output_heuristic,
    retrieve_kb,
    format_kb_block,
    format_few_shot_block,
    pick_variant,
    variant_score,
)
from app.database import get_db

logger = logging.getLogger(__name__)


# ====== Conversation memory (DB-backed) ======


async def fetch_recent_channel_msgs(account_id: int, channel: str, *, limit: int = 10) -> list[ChatMsg]:
    """Последние N сообщений канала (включая bot-ответы) из chat_log."""
    if limit <= 0:
        return []
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT author, message, is_bot, timestamp FROM chat_log "
            "WHERE account_id = ? AND channel = ? "
            "ORDER BY id DESC LIMIT ?",
            (account_id, channel, limit),
        )
        rows = await cursor.fetchall()
    finally:
        await db.close()
    return [
        ChatMsg(
            author=r["author"],
            message=r["message"],
            is_bot=bool(r["is_bot"]),
            timestamp=str(r["timestamp"] or ""),
        )
        for r in reversed(rows)
    ]


async def fetch_user_bot_pairs(
    account_id: int,
    channel: str,
    author: str,
    *,
    limit_pairs: int = 3,
) -> list[tuple[ChatMsg, ChatMsg]]:
    """Последние пары (юзер X → бот) для конкретного юзера в канале.

    Алгоритм: берём последние ~30 сообщений, идём вперёд, копим пары
    «не-бот author == X» → «следующее bot-сообщение в этом же канале».
    """
    if limit_pairs <= 0 or not author:
        return []
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, author, message, is_bot, timestamp FROM chat_log "
            "WHERE account_id = ? AND channel = ? "
            "ORDER BY id DESC LIMIT 80",
            (account_id, channel),
        )
        rows = list(await cursor.fetchall())
    finally:
        await db.close()
    rows.reverse()
    pairs: list[tuple[ChatMsg, ChatMsg]] = []
    pending_user: Optional[ChatMsg] = None
    author_l = author.lower()
    for r in rows:
        msg = ChatMsg(
            author=r["author"],
            message=r["message"],
            is_bot=bool(r["is_bot"]),
            timestamp=str(r["timestamp"] or ""),
        )
        if not msg.is_bot and msg.author.lower() == author_l:
            pending_user = msg
        elif msg.is_bot and pending_user is not None:
            pairs.append((pending_user, msg))
            pending_user = None
    return pairs[-limit_pairs:]


async def build_full_conversation_context(
    account_id: int,
    channel: str,
    author: str = "",
    *,
    max_channel: int = 10,
    max_pairs: int = 3,
) -> str:
    """Полный блок разговорного контекста (channel + user-bot pairs)."""
    chan = await fetch_recent_channel_msgs(account_id, channel, limit=max_channel)
    pairs = []
    if author:
        pairs = await fetch_user_bot_pairs(account_id, channel, author, limit_pairs=max_pairs)
    return build_conversation_block(chan, pairs, max_channel=max_channel, max_pairs=max_pairs)


# ====== Pre-classifier ======


async def classify_message_db(
    account_id: int,
    channel: str,
    message: str,
    *,
    bot_nickname: str = "",
    require_mention: bool = False,
    min_confidence: float = 0.4,
    chat_gap_threshold: float = 30.0,
) -> ClassifierDecision:
    """Pre-classifier с подгрузкой триггеров и гэпа из БД."""
    # Подгружаем активные триггеры
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT keyword FROM triggers WHERE account_id = ? AND enabled = 1",
            (account_id,),
        )
        triggers = [r["keyword"] for r in await cursor.fetchall() if r["keyword"]]

        # Гэп с момента последнего сообщения в канале
        cursor = await db.execute(
            "SELECT MAX(timestamp) AS ts FROM chat_log "
            "WHERE account_id = ? AND channel = ? AND is_bot = 0",
            (account_id, channel),
        )
        gap_row = await cursor.fetchone()
    finally:
        await db.close()

    gap = 0.0
    if gap_row and gap_row["ts"]:
        try:
            from datetime import datetime, timezone
            ts = datetime.strptime(str(gap_row["ts"])[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            gap = max(0.0, (datetime.now(timezone.utc) - ts).total_seconds())
        except (ValueError, TypeError):
            gap = 0.0

    return classify_message(
        message,
        bot_nickname=bot_nickname,
        trigger_keywords=triggers,
        seconds_since_last_chat_msg=gap,
        chat_gap_threshold=chat_gap_threshold,
        min_confidence=min_confidence,
        require_mention=require_mention,
    )


# ====== Cooldown per-topic ======


async def check_topic_cooldown(
    account_id: int,
    channel: str,
    candidate_text: str,
    *,
    window_sec: int = 60,
    min_shared: int = 2,
) -> Optional[dict]:
    """Если тема candidate_text похожа на одну из недавних bot-тем → возвращает совпавшую запись.

    Иначе None (значит можно отправлять).
    """
    candidate_topic = extract_topic_tokens(candidate_text, top_n=4)
    if not candidate_topic:
        return None
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, topic, full_text, created_at FROM bot_topic_log "
            "WHERE account_id = ? AND channel = ? "
            "AND created_at > datetime('now', ?) "
            "ORDER BY id DESC LIMIT 20",
            (account_id, channel, f"-{int(window_sec)} seconds"),
        )
        rows = await cursor.fetchall()
    finally:
        await db.close()
    for r in rows:
        existing_topic = (r["topic"] or "").split(",")
        existing_topic = [t.strip() for t in existing_topic if t.strip()]
        if topics_overlap(candidate_topic, existing_topic, min_shared=min_shared):
            return {
                "id": r["id"],
                "topic": r["topic"],
                "full_text": r["full_text"],
                "created_at": r["created_at"],
            }
    return None


async def record_bot_topic(account_id: int, channel: str, full_text: str) -> None:
    """Записывает тему bot-ответа в bot_topic_log (для будущих cooldown-проверок)."""
    topic_tokens = extract_topic_tokens(full_text, top_n=5)
    if not topic_tokens:
        return
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO bot_topic_log (account_id, channel, topic, full_text) VALUES (?, ?, ?, ?)",
            (account_id, channel, ",".join(topic_tokens), full_text[:300]),
        )
        # Удаляем старые записи (>24ч)
        await db.execute(
            "DELETE FROM bot_topic_log WHERE created_at < datetime('now', '-1 day')"
        )
        await db.commit()
    finally:
        await db.close()


# ====== Banned topics ======


async def check_banned_topics_db(account_id: int, text: str) -> Optional[BannedTopicHit]:
    """Загружает enabled banned_topics для account и проверяет."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, pattern, fallback, mode, enabled FROM banned_topics "
            "WHERE account_id = ? AND enabled = 1",
            (account_id,),
        )
        rows = [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()
    return check_banned_topics(text, rows)


# ====== Streamer KB ======


async def list_kb(account_id: int, channel: str = "") -> list[dict]:
    """§5 PLAN_FEEDBACK_2908: channel='' — все знания (вкл. per-channel)."""
    db = await get_db()
    try:
        if channel:
            cursor = await db.execute(
                "SELECT id, topic, content, tags, priority, enabled, updated_at, channel "
                "FROM streamer_kb WHERE account_id = ? AND channel = ? "
                "ORDER BY priority DESC, id DESC",
                (account_id, (channel or "").lower()),
            )
        else:
            cursor = await db.execute(
                "SELECT id, topic, content, tags, priority, enabled, updated_at, channel "
                "FROM streamer_kb WHERE account_id = ? ORDER BY priority DESC, id DESC",
                (account_id,),
            )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


async def add_kb(account_id: int, topic: str, content: str, tags: str = "", priority: int = 5, channel: str = "") -> int:
    """§5: channel — привязка знания к каналу ('' = глобальное для бота)."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO streamer_kb (account_id, topic, content, tags, priority, channel) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (account_id, topic.strip(), content.strip(), tags.strip(), int(priority), (channel or "").lower()),
        )
        await db.commit()
        return cursor.lastrowid or 0
    finally:
        await db.close()


async def update_kb(account_id: int, kb_id: int, **fields) -> bool:
    if not fields:
        return False
    keys = []
    vals = []
    for k in ("topic", "content", "tags", "priority", "enabled"):
        if k in fields:
            keys.append(f"{k} = ?")
            vals.append(fields[k])
    if not keys:
        return False
    keys.append("updated_at = CURRENT_TIMESTAMP")
    vals.extend((kb_id, account_id))
    db = await get_db()
    try:
        cursor = await db.execute(
            f"UPDATE streamer_kb SET {', '.join(keys)} WHERE id = ? AND account_id = ?",
            vals,
        )
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


async def delete_kb(account_id: int, kb_id: int) -> bool:
    db = await get_db()
    try:
        cursor = await db.execute(
            "DELETE FROM streamer_kb WHERE id = ? AND account_id = ?",
            (kb_id, account_id),
        )
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


async def retrieve_kb_for_query(account_id: int, query: str, *, top_k: int = 3) -> list[dict]:
    entries = await list_kb(account_id)
    return retrieve_kb(query, entries, top_k=top_k)


# ====== Style examples (few-shot) ======


async def list_style_examples(account_id: int, *, channel: str = "", limit: int = 50) -> list[dict]:
    channel = channel.strip().lower().lstrip("#")
    db = await get_db()
    try:
        where = "account_id = ?"
        params: list[object] = [account_id]
        if channel:
            where += " AND (channel = ? OR channel = '')"
            params.append(channel)
        params.append(limit)
        cursor = await db.execute(
            "SELECT id, channel, message, note, created_at FROM style_examples "
            f"WHERE {where} ORDER BY CASE WHEN channel = ? THEN 0 ELSE 1 END, id DESC LIMIT ?",
            (*params[:-1], channel, params[-1]),
        )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


async def add_style_example(account_id: int, message: str, channel: str = "", note: str = "") -> int:
    channel = channel.strip().lower().lstrip("#")
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO style_examples (account_id, channel, message, note) "
            "VALUES (?, ?, ?, ?)",
            (account_id, channel.strip(), message.strip(), note.strip()),
        )
        await db.commit()
        return cursor.lastrowid or 0
    finally:
        await db.close()


async def delete_style_example(account_id: int, ex_id: int) -> bool:
    db = await get_db()
    try:
        cursor = await db.execute(
            "DELETE FROM style_examples WHERE id = ? AND account_id = ?",
            (ex_id, account_id),
        )
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


async def pick_style_examples(
    account_id: int, *, channel: str = "", count: int = 4, query: str = ""
) -> list[dict]:
    """Few-shot примеры стиля.

    query (BRAIN_PLAN §3): если задан — перебираем пул кандидатов (×4) и
    возвращаем top-K по косинусной близости темы (переиспользуем
    conversation_threads._tokenize/_tf/cosine). Без query — как раньше (RANDOM).
    """
    channel = channel.strip().lower().lstrip("#")
    db = await get_db()
    try:
        if channel:
            sql = (
                "SELECT id, message FROM style_examples "
                "WHERE account_id = ? AND (channel = ? OR channel = '') "
                "ORDER BY CASE WHEN channel = ? THEN 0 ELSE 1 END, RANDOM() LIMIT ?"
            )
            params: tuple = (account_id, channel, channel, count)
        else:
            sql = "SELECT id, message FROM style_examples WHERE account_id = ? ORDER BY RANDOM() LIMIT ?"
            params = (account_id, count)
        if (query or "").strip():
            # пул кандидатов больше, чтобы косинусному рейтингу был выбор
            params = (*params[:-1], max(int(params[-1]) * 4, 16))
        cursor = await db.execute(sql, params)
        rows = [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()

    q = (query or "").strip()
    if not q or not rows:
        return rows[:count]
    try:
        from app.conversation_threads import _tokenize, _tf, cosine as _cosine

        q_tf = _tf(_tokenize(q))
        if not q_tf:
            return rows[:count]
        scored = []
        for i, r in enumerate(rows):
            e_tf = _tf(_tokenize(r.get("message") or ""))
            score = _cosine(q_tf, e_tf) if e_tf else 0.0
            scored.append((-score, i, r))
        scored.sort(key=lambda x: (x[0], x[1]))
        return [r for _, _, r in scored[:count]]
    except Exception:  # cosine ranking не должен ломать few-shot
        return rows[:count]



# ====== Account-scoped A/B prompt variants ======


async def list_variants(account_id: int) -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, account_id, label, system_prompt, weight, count, likes, dislikes, enabled "
            "FROM prompt_variants WHERE account_id = ? ORDER BY id ASC",
            (account_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


async def add_variant(account_id: int, label: str, system_prompt: str, weight: int = 50) -> int:
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO prompt_variants (account_id, label, system_prompt, weight) "
            "VALUES (?, ?, ?, ?)",
            (account_id, label.strip()[:32], system_prompt, max(0, int(weight))),
        )
        await db.commit()
        return cursor.lastrowid or 0
    finally:
        await db.close()


async def update_variant(account_id: int, variant_id: int, **fields) -> bool:
    if not fields:
        return False
    keys = []
    vals = []
    for k in ("label", "system_prompt", "weight", "enabled"):
        if k in fields:
            keys.append(f"{k} = ?")
            vals.append(fields[k])
    if not keys:
        return False
    vals.extend((variant_id, account_id))
    db = await get_db()
    try:
        cursor = await db.execute(
            f"UPDATE prompt_variants SET {', '.join(keys)} WHERE id = ? AND account_id = ?",
            vals,
        )
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


async def delete_variant(account_id: int, variant_id: int) -> bool:
    db = await get_db()
    try:
        cursor = await db.execute(
            "DELETE FROM prompt_variants WHERE id = ? AND account_id = ?",
            (variant_id, account_id),
        )
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


async def pick_variant_for_account(account_id: int) -> Optional[dict]:
    """Load account prompt variants and choose one by weight."""
    variants = await list_variants(account_id)
    if not variants:
        return None
    return pick_variant(variants)


async def increment_variant_count(account_id: int, variant_id: int) -> bool:
    db = await get_db()
    try:
        cursor = await db.execute(
            "UPDATE prompt_variants SET count = count + 1 WHERE id = ? AND account_id = ?",
            (variant_id, account_id),
        )
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


# ====== Banned topics CRUD ======


async def list_banned_topics(account_id: int) -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, pattern, fallback, mode, enabled FROM banned_topics "
            "WHERE account_id = ? ORDER BY id ASC",
            (account_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


async def add_banned_topic(account_id: int, pattern: str, fallback: str = "", mode: str = "silent") -> int:
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO banned_topics (account_id, pattern, fallback, mode) VALUES (?, ?, ?, ?)",
            (account_id, pattern.strip(), fallback.strip(), mode),
        )
        await db.commit()
        return cursor.lastrowid or 0
    finally:
        await db.close()


async def update_banned_topic(account_id: int, topic_id: int, **fields) -> bool:
    if not fields:
        return False
    keys = []
    vals = []
    for k in ("pattern", "fallback", "mode", "enabled"):
        if k in fields:
            keys.append(f"{k} = ?")
            vals.append(fields[k])
    if not keys:
        return False
    vals.extend((topic_id, account_id))
    db = await get_db()
    try:
        cursor = await db.execute(
            f"UPDATE banned_topics SET {', '.join(keys)} WHERE id = ? AND account_id = ?",
            vals,
        )
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


async def delete_banned_topic(account_id: int, topic_id: int) -> bool:
    db = await get_db()
    try:
        cursor = await db.execute(
            "DELETE FROM banned_topics WHERE id = ? AND account_id = ?",
            (topic_id, account_id),
        )
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


# ====== Feedback ======


async def submit_feedback(
    account_id: int,
    chat_log_id: int,
    feedback: int,
    *,
    source: str = "panel",
    note: str = "",
    prompt_variant_id: Optional[int] = None,
) -> int:
    """feedback: 1 (like) or -1 (dislike)."""
    feedback = 1 if feedback > 0 else -1
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT 1 FROM chat_log WHERE id = ? AND account_id = ?",
            (chat_log_id, account_id),
        )
        if await cursor.fetchone() is None:
            return 0
        if prompt_variant_id is not None:
            cursor = await db.execute(
                "SELECT 1 FROM prompt_variants WHERE id = ? AND account_id = ?",
                (prompt_variant_id, account_id),
            )
            if await cursor.fetchone() is None:
                return 0
        cursor = await db.execute(
            "INSERT INTO bot_response_feedback (chat_log_id, prompt_variant_id, feedback, source, note) "
            "VALUES (?, ?, ?, ?, ?)",
            (int(chat_log_id), prompt_variant_id, feedback, source, note),
        )
        # Bump variant stats если знаем variant
        if prompt_variant_id:
            col = "likes" if feedback > 0 else "dislikes"
            await db.execute(
                f"UPDATE prompt_variants SET {col} = {col} + 1 WHERE id = ? AND account_id = ?",
                (prompt_variant_id, account_id),
            )
        await db.commit()
        return cursor.lastrowid or 0
    finally:
        await db.close()


async def get_feedback_for_log(account_id: int, chat_log_id: int) -> Optional[dict]:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT 1 FROM chat_log WHERE id = ? AND account_id = ?",
            (chat_log_id, account_id),
        )
        if await cursor.fetchone() is None:
            return None
        cursor = await db.execute(
            "SELECT feedback, COUNT(*) AS cnt FROM bot_response_feedback "
            "WHERE chat_log_id = ? GROUP BY feedback",
            (chat_log_id,),
        )
        rows = await cursor.fetchall()
    finally:
        await db.close()
    likes = 0
    dislikes = 0
    for r in rows:
        if int(r["feedback"]) > 0:
            likes = int(r["cnt"])
        else:
            dislikes = int(r["cnt"])
    return {"likes": likes, "dislikes": dislikes}


async def feedback_summary(account_id: int, days: int = 30) -> dict:
    """Агрегаты feedback'a для аналитики."""
    where_clauses = ["f.created_at > datetime('now', ?)"]
    params: list[Any] = [f"-{int(days)} days"]
    where_clauses.append("c.account_id = ?")
    params.append(account_id)
    where_sql = " AND ".join(where_clauses)
    db = await get_db()
    try:
        cursor = await db.execute(
            f"""SELECT f.feedback AS fb, COUNT(*) AS cnt
                FROM bot_response_feedback f
                LEFT JOIN chat_log c ON c.id = f.chat_log_id
                WHERE {where_sql}
                GROUP BY f.feedback""",
            params,
        )
        rows = await cursor.fetchall()
    finally:
        await db.close()
    likes = 0
    dislikes = 0
    for r in rows:
        if int(r["fb"]) > 0:
            likes = int(r["cnt"])
        else:
            dislikes = int(r["cnt"])
    return {"likes": likes, "dislikes": dislikes, "total": likes + dislikes, "days": days}
