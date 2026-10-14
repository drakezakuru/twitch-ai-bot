"""Bot logs — персистентні логи per-bot з рівнями, категоріями та WebSocket-трансляцією.

Функції:
- ``log_per_bot`` — запис логу + broadcast через WebSocket
- ``get_bot_logs`` — отримання логів з фільтрами
- ``cleanup_old_logs`` — видалення старих логів (> retention днів)
- ``export_logs`` — експорт у CSV/JSON
"""

from __future__ import annotations

import csv
import io
import json
import logging
from typing import Any

from app.database import get_db

logger = logging.getLogger(__name__)

# Default retention: 30 днів
DEFAULT_RETENTION_DAYS = 30
DEFAULT_MAX_LOGS_PER_BOT = 10000


async def log_per_bot(
    account_id: int,
    channel: str,
    category: str,
    message: str,
    level: str = "info",
    details: dict[str, Any] | None = None,
) -> None:
    """Записує лог для конкретного бота + broadcast через WebSocket."""
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO bot_logs (account_id, channel, level, category, message, details) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                account_id,
                channel,
                level,
                category,
                message,
                json.dumps(details or {}, ensure_ascii=False),
            ),
        )
        await db.commit()
    except Exception as exc:
        logger.warning("log_per_bot failed: %s", exc)
        return
    finally:
        await db.close()

    # WebSocket broadcast
    try:
        from app.server import broadcast_log
        await broadcast_log({
            "type": "bot_log",
            "account_id": account_id,
            "channel": channel,
            "level": level,
            "category": category,
            "message": message,
        })
    except Exception:
        pass  # WebSocket не критичний


async def get_bot_logs(
    account_id: int | None = None,
    level: str | None = None,
    category: str | None = None,
    channel: str | None = None,
    q: str | None = None,
    from_time: str | None = None,
    to_time: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Отримує логи з фільтрами. Повертає (logs, total)."""
    db = await get_db()
    try:
        conditions: list[str] = []
        params: list[Any] = []

        if account_id is not None:
            conditions.append("l.account_id = ?")
            params.append(account_id)
        if level:
            conditions.append("l.level = ?")
            params.append(level)
        if category:
            conditions.append("l.category = ?")
            params.append(category)
        if channel:
            conditions.append("l.channel = ?")
            params.append(channel)
        if q:
            conditions.append("l.message LIKE ?")
            params.append(f"%{q}%")
        if from_time:
            conditions.append("l.created_at >= ?")
            params.append(from_time)
        if to_time:
            conditions.append("l.created_at <= ?")
            params.append(to_time)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # Total count
        cur = await db.execute(f"SELECT COUNT(*) as cnt FROM bot_logs l {where}", params)
        row = await cur.fetchone()
        total = row["cnt"] if row else 0

        # Fetch logs; nickname бота — чтобы в панели отличать, чей это лог
        # (нет account_id → событие самой панели, не бота).
        cur = await db.execute(
            f"SELECT l.*, a.nickname FROM bot_logs l "
            f"LEFT JOIN accounts a ON l.account_id = a.id "
            f"{where} ORDER BY l.created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        )
        logs = [dict(r) for r in await cur.fetchall()]

        return logs, total
    finally:
        await db.close()


async def cleanup_old_logs(
    retention_days: int = DEFAULT_RETENTION_DAYS,
    account_id: int | None = None,
) -> int:
    """Видаляє старі логи глобально або лише для одного акаунта."""
    db = await get_db()
    try:
        where = "created_at < datetime('now', ?)"
        params: list[Any] = [f"-{retention_days} days"]
        if account_id is not None:
            where += " AND account_id = ?"
            params.append(account_id)
        cur = await db.execute(
            f"DELETE FROM bot_logs WHERE {where}",
            params,
        )
        deleted = cur.rowcount
        await db.commit()
        if deleted > 0:
            logger.info("Cleaned up %d old bot logs (retention=%d days)", deleted, retention_days)
        return deleted
    finally:
        await db.close()


async def export_logs(
    account_id: int,
    fmt: str = "json",
    level: str | None = None,
    category: str | None = None,
) -> str | bytes:
    """Експорт логів бота у CSV або JSON."""
    logs, _ = await get_bot_logs(
        account_id=account_id, level=level, category=category, limit=10000
    )

    if fmt == "csv":
        output = io.StringIO()
        if logs:
            writer = csv.DictWriter(output, fieldnames=logs[0].keys())
            writer.writeheader()
            writer.writerows(logs)
        return output.getvalue()
    else:
        return json.dumps(logs, ensure_ascii=False, default=str, indent=2)


async def get_log_stats(account_id: int) -> dict[str, Any]:
    """Статистика логів per-bot: counts by level, by category."""
    db = await get_db()
    try:
        result: dict[str, Any] = {}

        # By level
        cur = await db.execute(
            "SELECT level, COUNT(*) as cnt FROM bot_logs WHERE account_id = ? GROUP BY level",
            (account_id,),
        )
        result["by_level"] = {r["level"]: r["cnt"] for r in await cur.fetchall()}

        # By category
        cur = await db.execute(
            "SELECT category, COUNT(*) as cnt FROM bot_logs WHERE account_id = ? GROUP BY category",
            (account_id,),
        )
        result["by_category"] = {r["category"]: r["cnt"] for r in await cur.fetchall()}

        # Total
        cur = await db.execute(
            "SELECT COUNT(*) as cnt FROM bot_logs WHERE account_id = ?", (account_id,)
        )
        row = await cur.fetchone()
        result["total"] = row["cnt"] if row else 0

        return result
    finally:
        await db.close()


__all__ = [
    "log_per_bot",
    "get_bot_logs",
    "cleanup_old_logs",
    "export_logs",
    "get_log_stats",
]
