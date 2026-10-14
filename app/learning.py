"""§16 BRAIN_PLAN: Безопасное автообучение.

Система предложений, которые бот НЕ применяет сам — только владелец
через панель «Обучение». Каждое применённое изменение пишется в
action_log с revert_payload, чтобы можно было откатить.

Источники предложений (на будущее):
  - feedback 👍/👎 (см. submit_feedback в ai_quality_db)
  - engagement-метрики (bot_engagement)
  - повторяющиеся вопросы чата (background detector)

kind:
  - style_example : {"message": "...", "note": "..."}
  - kb_topic      : {"topic": "...", "content": "...", "tags": "..."}
  - persona_delta : {"key": "...", "value": "..."}  (например mood_shift)
  - banned_topic  : {"pattern": "...", "fallback": "...", "mode": "..."}

status: pending | applied | rejected | reverted
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from app.database import get_db

logger = logging.getLogger(__name__)

VALID_KINDS = ("style_example", "kb_topic", "persona_delta", "banned_topic")
VALID_STATUSES = ("pending", "applied", "rejected", "reverted")


async def ensure_table() -> None:
    """Создаёт таблицу learning_suggestions идемпотентно."""
    db = await get_db()
    try:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS learning_suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL DEFAULT '',
                kind TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                reason TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'auto',
                confidence REAL NOT NULL DEFAULT 0.5,
                status TEXT NOT NULL DEFAULT 'pending',
                applied_at TIMESTAMP,
                reverted_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            )
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_ls_scope ON learning_suggestions(account_id, channel, status)"
        )
        await db.commit()
    finally:
        await db.close()


def _normalize_channel(channel: str) -> str:
    return (channel or "").strip().lower().lstrip("#")


def _row_to_dict(row: Any) -> dict:
    d = dict(row)
    pj = d.get("payload_json")
    if pj:
        try:
            d["payload"] = json.loads(pj)
        except (ValueError, TypeError):
            d["payload"] = {}
    else:
        d["payload"] = {}
    for k in ("created_at", "applied_at", "reverted_at"):
        v = d.get(k)
        if v is not None and not isinstance(v, str):
            try:
                d[k] = str(v)
            except Exception:
                d[k] = None
    return d


async def add_suggestion(
    account_id: int,
    channel: str,
    kind: str,
    payload: dict,
    *,
    reason: str = "",
    source: str = "auto",
    confidence: float = 0.5,
) -> int:
    """Добавляет предложение. Возвращает id (0 при ошибке).

    Дубликаты (same kind+payload+pending) не создаём.
    """
    if kind not in VALID_KINDS:
        logger.warning("add_suggestion: invalid kind %r", kind)
        return 0
    await ensure_table()
    channel = _normalize_channel(channel)
    payload = payload or {}
    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        confidence = 0.5
    try:
        db = await get_db()
        try:
            payload_json = json.dumps(payload, ensure_ascii=False)
            # Простая защита от дублей
            cursor = await db.execute(
                """SELECT id FROM learning_suggestions
                   WHERE account_id = ? AND channel = ? AND kind = ?
                     AND payload_json = ? AND status = 'pending'
                   LIMIT 1""",
                (account_id, channel, kind, payload_json),
            )
            existing = await cursor.fetchone()
            if existing:
                return int(existing["id"])
            cursor = await db.execute(
                """INSERT INTO learning_suggestions
                   (account_id, channel, kind, payload_json, reason, source, confidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    account_id,
                    channel,
                    kind,
                    payload_json,
                    (reason or "")[:500],
                    (source or "auto")[:32],
                    confidence,
                ),
            )
            await db.commit()
            return int(cursor.lastrowid or 0)
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("add_suggestion error: %s", exc)
        return 0


async def list_suggestions(
    account_id: int,
    channel: str = "",
    *,
    status: Optional[str] = None,
    kind: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    await ensure_table()
    channel = _normalize_channel(channel)
    # channel='*' — все скоупы (глобальные + все каналы; PLAN_FEEDBACK_3008 §2.1)
    where = ["account_id = ?", *([] if channel == "*" else ["channel = ?"])]
    params: list[Any] = [account_id, *([] if channel == "*" else [channel])]
    if status:
        where.append("status = ?")
        params.append(status)
    if kind:
        where.append("kind = ?")
        params.append(kind)
    params.append(limit)
    try:
        db = await get_db()
        try:
            cursor = await db.execute(
                f"""SELECT * FROM learning_suggestions
                    WHERE {' AND '.join(where)}
                    ORDER BY created_at DESC LIMIT ?""",
                tuple(params),
            )
            rows = await cursor.fetchall()
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("list_suggestions error: %s", exc)
        return []
    return [_row_to_dict(r) for r in rows]


async def apply_suggestion(account_id: int, suggestion_id: int) -> bool:
    """Помечает предложение как применённое. Реальное действие — в routes."""
    await ensure_table()
    try:
        db = await get_db()
        try:
            cursor = await db.execute(
                """UPDATE learning_suggestions
                   SET status = 'applied', applied_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND account_id = ? AND status = 'pending'""",
                (suggestion_id, account_id),
            )
            await db.commit()
            return cursor.rowcount > 0
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("apply_suggestion error: %s", exc)
        return False


async def reject_suggestion(account_id: int, suggestion_id: int) -> bool:
    await ensure_table()
    try:
        db = await get_db()
        try:
            cursor = await db.execute(
                """UPDATE learning_suggestions
                   SET status = 'rejected'
                   WHERE id = ? AND account_id = ? AND status = 'pending'""",
                (suggestion_id, account_id),
            )
            await db.commit()
            return cursor.rowcount > 0
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("reject_suggestion error: %s", exc)
        return False


async def mark_reverted(account_id: int, suggestion_id: int) -> bool:
    await ensure_table()
    try:
        db = await get_db()
        try:
            cursor = await db.execute(
                """UPDATE learning_suggestions
                   SET status = 'reverted', reverted_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND account_id = ? AND status = 'applied'""",
                (suggestion_id, account_id),
            )
            await db.commit()
            return cursor.rowcount > 0
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("mark_reverted error: %s", exc)
        return False


async def get_suggestion(account_id: int, suggestion_id: int) -> dict | None:
    await ensure_table()
    try:
        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT * FROM learning_suggestions WHERE id = ? AND account_id = ?",
                (suggestion_id, account_id),
            )
            row = await cursor.fetchone()
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("get_suggestion error: %s", exc)
        return None
    return _row_to_dict(row) if row else None
