"""§15 BRAIN_PLAN: Lore стримера — одобряемая память.

Идея: бот и summarizer предлагают «факты о стримере» (lore). Владелец
просматривает в панели, подтверждает/отклоняет. В prompt подмешиваются
только approved (с учётом expires_at). Никогда не меняет поведение
автоматически — только через подтверждение.

Изоляция: всё per (account_id, channel). channel='' = глобальный факт
по стримеру (применяется ко всем каналам этого аккаунта).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.database import get_db

logger = logging.getLogger(__name__)


async def ensure_table() -> None:
    """Создаёт таблицу streamer_lore идемпотентно."""
    db = await get_db()
    try:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS streamer_lore (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL DEFAULT '',
                fact TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'summary'
                    CHECK(source IN ('summary', 'chat', 'manual', 'auto')),
                evidence TEXT NOT NULL DEFAULT '',
                confidence REAL NOT NULL DEFAULT 0.5,
                importance INTEGER NOT NULL DEFAULT 50,
                status TEXT NOT NULL DEFAULT 'suggested'
                    CHECK(status IN ('suggested', 'approved', 'rejected')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                approved_at TIMESTAMP,
                expires_at TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            )
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_lore_scope ON streamer_lore(account_id, channel, status)"
        )
        await db.commit()
    finally:
        await db.close()


def _normalize_channel(channel: str) -> str:
    return (channel or "").strip().lower().lstrip("#")


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        s = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _row_to_dict(row: Any) -> dict:
    d = dict(row)
    for k in ("created_at", "updated_at", "approved_at", "expires_at"):
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
    fact: str,
    *,
    source: str = "summary",
    evidence: str = "",
    confidence: float = 0.5,
    importance: int = 50,
    expires_at: Optional[str] = None,
) -> int:
    """Добавляет предложение факта. Возвращает id."""
    if not fact or not fact.strip():
        return 0
    await ensure_table()
    channel = _normalize_channel(channel)
    source = (source or "summary").strip().lower()
    if source not in ("summary", "chat", "manual", "auto"):
        source = "summary"
    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        confidence = 0.5
    try:
        importance = max(0, min(100, int(importance)))
    except (TypeError, ValueError):
        importance = 50
    try:
        db = await get_db()
        try:
            cursor = await db.execute(
                """INSERT INTO streamer_lore
                   (account_id, channel, fact, source, evidence,
                    confidence, importance, status, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'suggested', ?)""",
                (
                    account_id,
                    channel,
                    fact.strip(),
                    source,
                    evidence[:500],
                    confidence,
                    importance,
                    expires_at,
                ),
            )
            await db.commit()
            return int(cursor.lastrowid or 0)
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("add_suggestion error: %s", exc)
        return 0


async def approve(lore_id: int) -> bool:
    await ensure_table()
    try:
        db = await get_db()
        try:
            await db.execute(
                """UPDATE streamer_lore
                   SET status = 'approved', approved_at = CURRENT_TIMESTAMP,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (lore_id,),
            )
            await db.commit()
            return True
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("approve error: %s", exc)
        return False


async def reject(lore_id: int) -> bool:
    await ensure_table()
    try:
        db = await get_db()
        try:
            await db.execute(
                """UPDATE streamer_lore
                   SET status = 'rejected', updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (lore_id,),
            )
            await db.commit()
            return True
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("reject error: %s", exc)
        return False


async def update_fact(
    lore_id: int, *, fact: Optional[str] = None, importance: Optional[int] = None,
    expires_at: Optional[str] = None,
) -> bool:
    await ensure_table()
    sets: list[str] = []
    params: list[Any] = []
    if fact is not None:
        fact = fact.strip()
        if not fact:
            return False
        sets.append("fact = ?")
        params.append(fact)
    if importance is not None:
        try:
            importance = max(0, min(100, int(importance)))
        except (TypeError, ValueError):
            return False
        sets.append("importance = ?")
        params.append(importance)
    if expires_at is not None:
        sets.append("expires_at = ?")
        params.append(expires_at if expires_at else None)
    if not sets:
        return False
    sets.append("updated_at = CURRENT_TIMESTAMP")
    params.append(lore_id)
    try:
        db = await get_db()
        try:
            await db.execute(
                f"UPDATE streamer_lore SET {', '.join(sets)} WHERE id = ?",
                tuple(params),
            )
            await db.commit()
            return True
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("update_fact error: %s", exc)
        return False


async def delete_lore(lore_id: int) -> bool:
    await ensure_table()
    try:
        db = await get_db()
        try:
            await db.execute("DELETE FROM streamer_lore WHERE id = ?", (lore_id,))
            await db.commit()
            return True
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("delete_lore error: %s", exc)
        return False


async def list_lore(
    account_id: int,
    channel: str = "",
    *,
    status: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    """Список фактов; если status не задан — все (s+a+r).

    channel='' — только глобальные факты; channel='*' — все скоупы
    (глобальные + все каналы; PLAN_FEEDBACK_3008 §2.1 «🌐 все каналы»).
    """
    await ensure_table()
    channel = _normalize_channel(channel)
    all_scopes = channel == "*"
    try:
        db = await get_db()
        try:
            ch_cond = "" if all_scopes else "AND channel = ?"
            if status:
                cursor = await db.execute(
                    f"""SELECT * FROM streamer_lore
                       WHERE account_id = ? {ch_cond} AND status = ?
                       ORDER BY importance DESC, created_at DESC LIMIT ?""",
                    (account_id, *([] if all_scopes else [channel]), status, limit),
                )
            else:
                cursor = await db.execute(
                    f"""SELECT * FROM streamer_lore
                       WHERE account_id = ? {ch_cond}
                       ORDER BY status ASC, importance DESC, created_at DESC LIMIT ?""",
                    (account_id, *([] if all_scopes else [channel]), limit),
                )
            rows = await cursor.fetchall()
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("list_lore error: %s", exc)
        return []
    return [_row_to_dict(r) for r in rows]


async def list_approved(account_id: int, channel: str = "", *, limit: int = 50) -> list[dict]:
    """Только approved + не просроченные."""
    return await list_lore(account_id, channel, status="approved", limit=limit)


def _is_expired(row: dict) -> bool:
    expires = _parse_iso(row.get("expires_at"))
    if not expires:
        return False
    now = datetime.now(timezone.utc)
    return expires <= now


def format_lore_for_prompt(rows: list[dict], *, max_chars: int = 800, max_items: int = 8) -> str:
    """Собирает блок для system_prompt только из approved+непросроченных.

    Сортировка: importance DESC, approved_at DESC.
    """
    now = datetime.now(timezone.utc)
    items: list[tuple[int, str, str]] = []
    for r in rows or []:
        if (r.get("status") or "") != "approved":
            continue
        expires = _parse_iso(r.get("expires_at"))
        if expires and expires <= now:
            continue
        fact = (r.get("fact") or "").strip()
        if not fact:
            continue
        try:
            importance = max(0, min(100, int(r.get("importance") or 50)))
        except (TypeError, ValueError):
            importance = 50
        items.append((importance, str(r.get("approved_at") or ""), fact))
    items.sort(key=lambda x: (x[0], x[1]), reverse=True)
    if not items:
        return ""
    parts = ["Что я знаю о стримере (только проверенные факты):"]
    used = 0
    for _, _, fact in items[:max_items]:
        if used + len(fact) + 2 > max_chars:
            break
        parts.append(f"  • {fact}")
        used += len(fact) + 2
    return "\n".join(parts)
