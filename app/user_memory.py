"""Feature 5: Долговременная память per-user.

v8: расширено до структурированных фактов с confidence+decay.
Format (новый, backward-compat со старым):
  facts = [
    {fact: str, confidence: float 0..1, last_seen: iso, source_msg_id: int|None},
    ...
  ]
Старые строковые факты автоконвертятся при чтении.

Хранит факты о зрителях в таблице `user_memory`:
  - username
  - account_id (под каким ботом)
  - facts (JSON)
  - msg_count
  - last_seen
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.ai_quality import (
    decay_facts,
    format_facts_for_prompt,
    merge_fact,
    normalize_fact_entry,
)
from app.database import get_db

logger = logging.getLogger(__name__)


def _parse_facts(raw_json: Any, *, apply_decay: bool = True) -> list[dict]:
    """Парсит JSON фактов и нормализует к новому формату с decay."""
    try:
        loaded = json.loads(raw_json) if raw_json else []
    except Exception:
        return []
    if not isinstance(loaded, list):
        return []
    normalized = [normalize_fact_entry(f) for f in loaded]
    normalized = [f for f in normalized if f["fact"]]
    if apply_decay:
        normalized = decay_facts(normalized)
    return normalized


async def get_user_memory(account_id: int, username: str, *, structured: bool = False) -> dict | None:
    """Возвращает {username, facts: [...], msg_count, last_seen} или None.
    
    By default facts — list[str] (legacy-compat).
    structured=True — list[dict {fact, confidence, last_seen, source_msg_id}].
    """
    if not username:
        return None
    username = username.lower().strip()
    try:
        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT username, facts, msg_count, last_seen FROM user_memory "
                "WHERE account_id = ? AND username = ?",
                (account_id, username),
            )
            row = await cursor.fetchone()
            if not row:
                return None
            structured_facts = _parse_facts(row["facts"])
            if structured:
                facts: Any = structured_facts
            else:
                facts = [f["fact"] for f in structured_facts]
            return {
                "username": row["username"],
                "facts": facts,
                "facts_structured": structured_facts,
                "msg_count": row["msg_count"],
                "last_seen": row["last_seen"],
            }
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("get_user_memory error: %s", exc)
        return None


async def list_user_memory(account_id: int, limit: int = 100, *, structured: bool = False) -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT username, facts, msg_count, last_seen FROM user_memory "
            "WHERE account_id = ? ORDER BY msg_count DESC LIMIT ?",
            (account_id, limit),
        )
        rows = await cursor.fetchall()
        result = []
        for row in rows:
            structured_facts = _parse_facts(row["facts"])
            if structured:
                facts: Any = structured_facts
            else:
                facts = [f["fact"] for f in structured_facts]
            result.append({
                "username": row["username"],
                "facts": facts,
                "facts_structured": structured_facts,
                "msg_count": row["msg_count"],
                "last_seen": row["last_seen"],
            })
        return result
    finally:
        await db.close()


async def increment_msg_count(account_id: int, username: str) -> None:
    """Каждое сообщение от юзера → +1 к счётчику + обновление last_seen."""
    if not username:
        return
    username = username.lower().strip()
    try:
        db = await get_db()
        try:
            await db.execute(
                """INSERT INTO user_memory (account_id, username, facts, msg_count, last_seen)
                   VALUES (?, ?, '[]', 1, CURRENT_TIMESTAMP)
                   ON CONFLICT(account_id, username) DO UPDATE SET
                       msg_count = msg_count + 1,
                       last_seen = CURRENT_TIMESTAMP""",
                (account_id, username),
            )
            await db.commit()
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("increment_msg_count error: %s", exc)


async def add_fact(
    account_id: int, username: str, fact: str, *, source_msg_id: int | None = None,
    priority: int = 50, expires_at: str | None = None, ttl: int | float | None = None,
    source: str = "manual", confirmed: bool = False,
) -> bool:
    """Добавляет факт. Возвращает True если факт реально новый.

    Если такой же факт (case-insensitive) уже есть — bump'аем confidence
    и возвращаем False (дубликат).
    """
    if not username or not fact:
        return False
    username = username.lower().strip()
    fact = fact.strip()
    if not fact:
        return False
    fact_l = fact.lower()
    try:
        priority = max(0, min(100, int(priority)))
    except (TypeError, ValueError):
        priority = 50
    if ttl is not None and expires_at is None:
        try:
            expires_at = (datetime.now(timezone.utc) + timedelta(seconds=max(0, float(ttl)))).isoformat()
        except (TypeError, ValueError):
            expires_at = None
    source = (source or "manual")[:32]
    try:
        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT facts FROM user_memory WHERE account_id = ? AND username = ?",
                (account_id, username),
            )
            row = await cursor.fetchone()
            if row:
                facts = _parse_facts(row["facts"], apply_decay=False)
                # Точное совпадение (case-insensitive) — это дубликат
                exact_dup = any(f["fact"].lower() == fact_l for f in facts)
                facts = merge_fact(facts, fact, source_msg_id=source_msg_id)
                for item in facts:
                    if item["fact"].lower() == fact_l or fact_l in item["fact"].lower() or item["fact"].lower() in fact_l:
                        item["priority"] = priority
                        if expires_at is not None:
                            item["expires_at"] = expires_at
                        item["source"] = source
                        if confirmed:
                            item["confirmed"] = True
                        break
                await db.execute(
                    "UPDATE user_memory SET facts = ? WHERE account_id = ? AND username = ?",
                    (json.dumps(facts, ensure_ascii=False), account_id, username),
                )
                await db.commit()
                return not exact_dup
            else:
                facts = merge_fact([], fact, source_msg_id=source_msg_id)
                facts[0]["priority"] = priority
                facts[0]["expires_at"] = expires_at
                facts[0]["source"] = source
                if confirmed:
                    facts[0]["confirmed"] = True
                await db.execute(
                    """INSERT INTO user_memory (account_id, username, facts, msg_count)
                       VALUES (?, ?, ?, 0)""",
                    (account_id, username, json.dumps(facts, ensure_ascii=False)),
                )
                await db.commit()
                return True
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("add_fact error: %s", exc)
        return False


async def update_fact(
    account_id: int, username: str, fact: str, *, priority: int = 50,
    expires_at: str | None = None, ttl: int | float | None = None,
) -> bool:
    """Updates metadata for an existing fact without changing its text."""
    if not username or not fact:
        return False
    username = username.lower().strip()
    fact_l = fact.strip().lower()
    if not fact_l:
        return False
    try:
        priority = max(0, min(100, int(priority)))
    except (TypeError, ValueError):
        priority = 50
    if ttl is not None and expires_at is None:
        try:
            expires_at = (datetime.now(timezone.utc) + timedelta(seconds=max(0, float(ttl)))).isoformat()
        except (TypeError, ValueError):
            expires_at = None
    try:
        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT facts FROM user_memory WHERE account_id = ? AND username = ?",
                (account_id, username),
            )
            row = await cursor.fetchone()
            if not row:
                return False
            facts = _parse_facts(row["facts"], apply_decay=False)
            target = next((item for item in facts if item["fact"].lower() == fact_l), None)
            if target is None:
                return False
            target["priority"] = priority
            target["expires_at"] = expires_at
            await db.execute(
                "UPDATE user_memory SET facts = ? WHERE account_id = ? AND username = ?",
                (json.dumps(facts, ensure_ascii=False), account_id, username),
            )
            await db.commit()
            return True
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("update_fact error: %s", exc)
        return False


async def remove_fact(account_id: int, username: str, fact: str) -> bool:
    """Удаляет факт по совпадению строки (case-insensitive)."""
    if not username:
        return False
    username = username.lower().strip()
    fact_l = (fact or "").strip().lower()
    if not fact_l:
        return False
    try:
        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT facts FROM user_memory WHERE account_id = ? AND username = ?",
                (account_id, username),
            )
            row = await cursor.fetchone()
            if not row:
                return False
            facts = _parse_facts(row["facts"], apply_decay=False)
            new_facts = [f for f in facts if f["fact"].lower() != fact_l]
            if len(new_facts) == len(facts):
                return False
            await db.execute(
                "UPDATE user_memory SET facts = ? WHERE account_id = ? AND username = ?",
                (json.dumps(new_facts, ensure_ascii=False), account_id, username),
            )
            await db.commit()
            return True
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("remove_fact error: %s", exc)
        return False


async def delete_user(account_id: int, username: str) -> bool:
    username = (username or "").lower().strip()
    if not username:
        return False
    try:
        db = await get_db()
        try:
            await db.execute(
                "DELETE FROM user_memory WHERE account_id = ? AND username = ?",
                (account_id, username),
            )
            await db.commit()
            return True
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("delete_user error: %s", exc)
        return False


async def set_fact_confirmed(
    account_id: int, username: str, fact: str, confirmed: bool = True
) -> bool:
    """Помечает факт как подтверждённый (или снимает подтверждение).

    Подтверждённые факты:
      - идут в prompt первыми (priority=100 effective)
      - decay сильно замедлен (half-life ×4)
    """
    if not username or not fact:
        return False
    username = username.lower().strip()
    fact_l = fact.strip().lower()
    if not fact_l:
        return False
    try:
        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT facts FROM user_memory WHERE account_id = ? AND username = ?",
                (account_id, username),
            )
            row = await cursor.fetchone()
            if not row:
                return False
            facts = _parse_facts(row["facts"], apply_decay=False)
            target = next(
                (it for it in facts if it["fact"].lower() == fact_l), None
            )
            if target is None:
                return False
            target["confirmed"] = bool(confirmed)
            await db.execute(
                "UPDATE user_memory SET facts = ? WHERE account_id = ? AND username = ?",
                (json.dumps(facts, ensure_ascii=False), account_id, username),
            )
            await db.commit()
            return True
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("set_fact_confirmed error: %s", exc)
        return False


async def gc_expired_facts(account_id: int | None = None) -> int:
    """Чистит просроченные факты (expires_at < now). Возвращает число удалённых.

    Если account_id=None — проходим по всем аккаунтам.
    """
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        db = await get_db()
        try:
            if account_id is None:
                cursor = await db.execute("SELECT account_id, username, facts FROM user_memory")
            else:
                cursor = await db.execute(
                    "SELECT account_id, username, facts FROM user_memory WHERE account_id = ?",
                    (account_id,),
                )
            rows = await cursor.fetchall()
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("gc_expired_facts select: %s", exc)
        return 0
    removed = 0
    for row in rows:
        facts = _parse_facts(row["facts"], apply_decay=False)
        keep = [f for f in facts if not _is_expired(f, now_iso)]
        if len(keep) != len(facts):
            try:
                db = await get_db()
                try:
                    await db.execute(
                        "UPDATE user_memory SET facts = ? WHERE account_id = ? AND username = ?",
                        (json.dumps(keep, ensure_ascii=False),
                         row["account_id"], row["username"]),
                    )
                    await db.commit()
                finally:
                    await db.close()
                removed += len(facts) - len(keep)
            except Exception as exc:
                logger.warning("gc_expired_facts update: %s", exc)
    return removed


def _is_expired(f: dict, now_iso: str) -> bool:
    from datetime import datetime, timezone
    exp = f.get("expires_at")
    if not exp:
        return False
    try:
        exp_dt = datetime.fromisoformat(str(exp).replace("Z", "+00:00"))
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
        now_dt = datetime.fromisoformat(now_iso)
        return exp_dt <= now_dt
    except (ValueError, TypeError):
        return False


async def auto_extract_facts_for(
    account_id: int,
    username: str,
    *,
    min_message_count: int = 5,
    max_facts: int = 3,
    confidence_threshold: float = 0.6,
    ai_service: Any = None,
    channel: str = "",
) -> list[dict]:
    """Извлекает факты из последних N сообщений пользователя (LLM-extract).

    Возвращает список найденных facts [{fact, confidence, source}].
    Ничего не пишет в БД — только candidates. Владелец подтверждает через UI.

    Если ai_service не передан или LLM недоступен — функция тихо возвращает [].
    """
    if not username or ai_service is None:
        return []
    username_l = username.lower().strip()
    try:
        history = await get_message_history(
            account_id, channel, username_l, limit=10
        )
    except Exception:
        return []
    if not history or len(history) < min_message_count:
        return []
    msgs = [h.get("message", "") for h in history if h.get("message")]
    if not msgs:
        return []
    joined = "\n".join(f"- {m[:200]}" for m in msgs[:10])
    prompt = (
        "Ты аналитик. Извлеки из сообщений пользователя 1-3 коротких факта "
        "(хобби, привычки, локация, профессия, что угодно конкретное).\n"
        "Верни СТРОГО JSON-массив объектов: [{\"fact\": \"...\", \"confidence\": 0.0..1.0}]\n"
        "Если фактов нет — верни [].\n\n"
        f"Сообщения:\n{joined}"
    )
    try:
        raw = await ai_service.generate_text(
            prompt=prompt,
            system="Отвечай только JSON.",
            account_id=account_id,
            channel=channel,
            temperature=0.1,
        )
    except Exception as exc:
        logger.debug("auto_extract ai error: %s", exc)
        return []
    return _parse_extracted_facts(raw, confidence_threshold=confidence_threshold,
                                  max_facts=max_facts)


def _parse_extracted_facts(raw: str, *, confidence_threshold: float, max_facts: int) -> list[dict]:
    if not raw:
        return []
    txt = raw.strip()
    # Вытащим JSON из ```...``` если есть
    if "```" in txt:
        try:
            txt = txt.split("```", 2)[1]
            if txt.startswith("json"):
                txt = txt[4:]
            txt = txt.strip()
        except Exception:
            pass
    try:
        data = json.loads(txt)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    for item in data[:max_facts]:
        if not isinstance(item, dict):
            continue
        fact = str(item.get("fact") or "").strip()
        if not fact or len(fact) < 3:
            continue
        try:
            conf = float(item.get("confidence") or 0.5)
        except (TypeError, ValueError):
            conf = 0.5
        if conf < confidence_threshold:
            continue
        out.append({"fact": fact[:500], "confidence": round(max(0.0, min(1.0, conf)), 2),
                    "source": "auto"})
    return out


async def add_message_history(account_id: int, channel: str, username: str, message: str, is_bot: bool = False, max_history: int = 5) -> None:
    """v12: зберігає повідомлення в історію per-user (останні max_history повідомлень)."""
    if not username or not message:
        return
    username = username.lower().strip()
    channel = channel.lower().strip().lstrip("#")
    max_history = max(1, min(50, int(max_history)))
    try:
        db = await get_db()
        try:
            await db.execute(
                "INSERT INTO user_message_history (account_id, channel, username, message, is_bot) "
                "VALUES (?, ?, ?, ?, ?)",
                (account_id, channel, username, message[:500], 1 if is_bot else 0),
            )
            # Обрізаємо старі — залишаємо лише останні max_history
            await db.execute(
                """DELETE FROM user_message_history
                   WHERE account_id = ? AND channel = ? AND username = ?
                     AND id NOT IN (
                    SELECT id FROM user_message_history
                    WHERE account_id = ? AND channel = ? AND username = ?
                    ORDER BY created_at DESC LIMIT ?
                )""",
                (account_id, channel, username, account_id, channel, username, max_history),
            )
            await db.commit()
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("add_message_history error: %s", exc)


async def get_message_history(account_id: int, channel: str, username: str, limit: int = 5) -> list[dict]:
    """v12: повертає останні N повідомлень користувача в контексті каналу."""
    if not username:
        return []
    username = username.lower().strip()
    channel = channel.lower().strip().lstrip("#")
    limit = max(1, min(50, int(limit)))
    try:
        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT message, is_bot, created_at FROM user_message_history "
                "WHERE account_id = ? AND channel = ? AND username = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (account_id, channel, username, limit),
            )
            rows = await cursor.fetchall()
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("get_message_history error: %s", exc)
        return []
    return [
        {"message": r["message"], "is_bot": bool(r["is_bot"]), "at": r["created_at"]}
        for r in reversed(rows)
    ]


def format_history_for_prompt(history: list[dict], username: str) -> str:
    """v12: форматує історію повідомлень для AI-промпту."""
    if not history or not username:
        return ""
    lines = []
    for h in history:
        prefix = "[бот]" if h.get("is_bot") else "[юзер]"
        lines.append(f"{prefix} {h['message']}")
    return f"Останні повідомлення від {username} (контекст розмови):\n" + "\n".join(lines)


def format_memory_for_prompt(memory: dict | None) -> str:
    """Превращает запись памяти в текст для system-prompt.
    
    Поддерживает оба формата: legacy (list[str]) и v8 (list[dict]).
    Если в memory есть facts_structured — используем его (фильтр по confidence).
    """
    if not memory:
        return ""
    facts_struct = memory.get("facts_structured")
    facts_raw = memory.get("facts") or []
    msg_count = memory.get("msg_count", 0)
    if not facts_raw and not facts_struct and msg_count < 5:
        return ""
    parts = []
    if msg_count:
        parts.append(f"написал {msg_count} сообщений")
    facts_text = ""
    if facts_struct:
        facts_text = format_facts_for_prompt(facts_struct, min_confidence=0.3)
    elif facts_raw:
        if isinstance(facts_raw[0], dict):
            facts_text = format_facts_for_prompt(facts_raw, min_confidence=0.3)
        else:
            facts_text = "; ".join(str(f) for f in facts_raw)
    if facts_text:
        parts.append("факты: " + facts_text)
    if not parts:
        return ""
    return f"Что я знаю о пользователе {memory['username']}: " + ", ".join(parts) + "."
