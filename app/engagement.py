"""v10.3 4B: Engagement-tracking — реакции на ответы бота.

После каждого bot-сообщения смотрим в окне ``window_sec`` (default 30s) реакции
зрителей в том же канале и считаем:

- ``support`` — кол-во **уникальных** не-бот пользователей, написавших что угодно;
- ``mentions`` — кол-во не-бот сообщений, упоминающих ник бота;
- ``replies`` — общее кол-во не-бот сообщений в окне;
- ``breakthrough`` — флаг "прорыв чата" (support ≥ ``breakthrough_min``).

Метрики хранятся в таблице ``bot_engagement`` (по ``chat_log_id`` bot-сообщения).

Считает фоновая корутина ``engagement_loop``: периодически берёт bot-сообщения,
у которых окно уже закрылось и метрика ещё не посчитана.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.database import get_db, get_setting

logger = logging.getLogger(__name__)


DEFAULT_WINDOW_SEC = 30
DEFAULT_BREAKTHROUGH_MIN = 3


async def get_window_sec() -> int:
    """Текущее окно в секундах (clamp 5..600)."""
    raw = await get_setting("engagement_window_sec", str(DEFAULT_WINDOW_SEC))
    try:
        return max(5, min(600, int(raw)))
    except (TypeError, ValueError):
        return DEFAULT_WINDOW_SEC


async def get_breakthrough_min() -> int:
    raw = await get_setting("engagement_breakthrough_min", str(DEFAULT_BREAKTHROUGH_MIN))
    try:
        return max(1, min(100, int(raw)))
    except (TypeError, ValueError):
        return DEFAULT_BREAKTHROUGH_MIN


async def compute_for_chat_log(
    chat_log_id: int,
    *,
    window_sec: int | None = None,
    breakthrough_min: int | None = None,
) -> dict[str, Any] | None:
    """Посчитать engagement-метрики для конкретного bot-сообщения.

    Записывает результат в ``bot_engagement``. Возвращает посчитанный dict
    или ``None`` если сообщение не найдено / не bot.
    """
    if window_sec is None:
        window_sec = await get_window_sec()
    if breakthrough_min is None:
        breakthrough_min = await get_breakthrough_min()

    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT id, account_id, channel, author, timestamp, is_bot "
            "FROM chat_log WHERE id = ?",
            (chat_log_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        if not row["is_bot"]:
            return None

        bot_nick = (row["author"] or "").lower()
        cur = await db.execute(
            "SELECT author, message FROM chat_log "
            "WHERE COALESCE(account_id, 0) = ? "
            "AND channel = ? "
            "AND is_bot = 0 "
            "AND timestamp > ? "
            "AND timestamp <= datetime(?, ?)",
            (
                row["account_id"] or 0,
                row["channel"],
                row["timestamp"],
                row["timestamp"],
                f"+{int(window_sec)} seconds",
            ),
        )
        replies = await cur.fetchall()

        unique_authors: set[str] = set()
        mention_count = 0
        for r in replies:
            author = (r["author"] or "").lower()
            if author:
                unique_authors.add(author)
            msg = (r["message"] or "").lower()
            if bot_nick and bot_nick in msg:
                mention_count += 1

        support = len(unique_authors)
        replies_total = len(replies)
        breakthrough = 1 if support >= breakthrough_min else 0

        await db.execute(
            "INSERT OR REPLACE INTO bot_engagement "
            "(chat_log_id, account_id, channel, support, mentions, replies, breakthrough) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                row["id"],
                row["account_id"] or 0,
                row["channel"],
                support,
                mention_count,
                replies_total,
                breakthrough,
            ),
        )
        await db.commit()
        return {
            "chat_log_id": row["id"],
            "account_id": row["account_id"] or 0,
            "channel": row["channel"],
            "support": support,
            "mentions": mention_count,
            "replies": replies_total,
            "breakthrough": bool(breakthrough),
        }
    finally:
        await db.close()


async def compute_pending(
    *,
    window_sec: int | None = None,
    breakthrough_min: int | None = None,
    limit: int = 200,
) -> int:
    """Посчитать engagement для всех bot-сообщений с закрывшимся окном."""
    if window_sec is None:
        window_sec = await get_window_sec()
    if breakthrough_min is None:
        breakthrough_min = await get_breakthrough_min()

    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT cl.id FROM chat_log cl "
            "LEFT JOIN bot_engagement be ON be.chat_log_id = cl.id "
            "WHERE cl.is_bot = 1 "
            "AND be.id IS NULL "
            "AND cl.timestamp <= datetime('now', ?) "
            "ORDER BY cl.id ASC LIMIT ?",
            (f"-{int(window_sec)} seconds", int(limit)),
        )
        rows = await cur.fetchall()
        ids = [r["id"] for r in rows]
    finally:
        await db.close()

    count = 0
    for chat_id in ids:
        try:
            res = await compute_for_chat_log(
                chat_id,
                window_sec=window_sec,
                breakthrough_min=breakthrough_min,
            )
            if res is not None:
                count += 1
        except Exception as exc:
            logger.warning("engagement compute failed for chat_log_id=%s: %s", chat_id, exc)
    return count


async def engagement_loop(interval_sec: float = 30.0) -> None:
    """Фоновая корутина: каждые ``interval_sec`` секунд считает накопившиеся метрики."""
    logger.info("engagement_loop started, interval=%ss", interval_sec)
    while True:
        try:
            await asyncio.sleep(interval_sec)
            await compute_pending()
        except asyncio.CancelledError:
            logger.info("engagement_loop cancelled")
            break
        except Exception as exc:
            logger.warning("engagement_loop tick error: %s", exc)
            await asyncio.sleep(interval_sec)


async def stats_summary(*, account_id: int = 0, days: int = 7) -> dict[str, Any]:
    """Агрегаты engagement за период.

    Возвращает: total ответов бота, % с support, % breakthrough, mentions/reply rate,
    топ-3 канала по среднему support.
    """
    days = max(1, min(365, int(days)))
    where = ["be.computed_at > datetime('now', ?)"]
    params: list[Any] = [f"-{days} days"]
    if account_id:
        where.append("be.account_id = ?")
        params.append(int(account_id))
    where_sql = "WHERE " + " AND ".join(where)

    db = await get_db()
    try:
        cur = await db.execute(
            f"SELECT COUNT(*) AS total, "
            f"SUM(CASE WHEN support > 0 THEN 1 ELSE 0 END) AS with_support, "
            f"SUM(breakthrough) AS breakthroughs, "
            f"SUM(mentions) AS total_mentions, "
            f"SUM(replies) AS total_replies, "
            f"AVG(support) AS avg_support "
            f"FROM bot_engagement be {where_sql}",
            tuple(params),
        )
        row = await cur.fetchone()
        total = (row["total"] if row else 0) or 0
        with_support = (row["with_support"] if row else 0) or 0
        breakthroughs = (row["breakthroughs"] if row else 0) or 0
        total_mentions = (row["total_mentions"] if row else 0) or 0
        total_replies = (row["total_replies"] if row else 0) or 0
        avg_support = float(row["avg_support"] or 0.0) if row else 0.0

        cur = await db.execute(
            f"SELECT be.channel AS channel, COUNT(*) AS cnt, "
            f"AVG(be.support) AS avg_support, SUM(be.breakthrough) AS breakthroughs "
            f"FROM bot_engagement be {where_sql} "
            f"GROUP BY be.channel ORDER BY avg_support DESC, cnt DESC LIMIT 5",
            tuple(params),
        )
        top_channels = [
            {
                "channel": r["channel"],
                "count": r["cnt"],
                "avg_support": round(float(r["avg_support"] or 0.0), 2),
                "breakthroughs": r["breakthroughs"] or 0,
            }
            for r in await cur.fetchall()
        ]
    finally:
        await db.close()

    def _pct(num: int, den: int) -> float:
        return round(100.0 * num / den, 1) if den else 0.0

    return {
        "days": days,
        "account_id": account_id,
        "total": total,
        "with_support": with_support,
        "support_rate": _pct(with_support, total),
        "breakthroughs": breakthroughs,
        "breakthrough_rate": _pct(breakthroughs, total),
        "total_mentions": total_mentions,
        "total_replies": total_replies,
        "mentions_per_reply": round(total_mentions / total, 2) if total else 0.0,
        "replies_per_reply": round(total_replies / total, 2) if total else 0.0,
        "avg_support": round(avg_support, 2),
        "top_channels": top_channels,
    }


async def list_recent(
    *,
    account_id: int = 0,
    channel: str = "",
    days: int = 7,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Список последних bot-сообщений с engagement-метрикой."""
    days = max(1, min(365, int(days)))
    limit = max(1, min(500, int(limit)))
    offset = max(0, int(offset))
    channel = (channel or "").strip().lstrip("#")

    where = ["cl.is_bot = 1", "cl.timestamp > datetime('now', ?)"]
    params: list[Any] = [f"-{days} days"]
    if account_id:
        where.append("cl.account_id = ?")
        params.append(int(account_id))
    if channel:
        where.append("cl.channel = ?")
        params.append(channel)
    where_sql = "WHERE " + " AND ".join(where)

    db = await get_db()
    try:
        cur = await db.execute(
            f"SELECT COUNT(*) AS c FROM chat_log cl {where_sql}",
            tuple(params),
        )
        total = (await cur.fetchone())["c"]
        cur = await db.execute(
            f"SELECT cl.id, cl.account_id, cl.channel, cl.author, cl.message, cl.timestamp, "
            f"be.support, be.mentions, be.replies, be.breakthrough "
            f"FROM chat_log cl LEFT JOIN bot_engagement be ON be.chat_log_id = cl.id "
            f"{where_sql} "
            f"ORDER BY cl.id DESC LIMIT ? OFFSET ?",
            tuple(params + [limit, offset]),
        )
        items = []
        for r in await cur.fetchall():
            items.append(
                {
                    "chat_log_id": r["id"],
                    "account_id": r["account_id"] or 0,
                    "channel": r["channel"],
                    "author": r["author"],
                    "message": r["message"],
                    "timestamp": r["timestamp"],
                    "support": r["support"] if r["support"] is not None else None,
                    "mentions": r["mentions"] if r["mentions"] is not None else None,
                    "replies": r["replies"] if r["replies"] is not None else None,
                    "breakthrough": bool(r["breakthrough"]) if r["breakthrough"] is not None else None,
                    "pending": r["support"] is None,
                }
            )
    finally:
        await db.close()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items,
    }
