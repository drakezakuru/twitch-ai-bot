"""Q26 (DEC-OWNER-014): журнал наказаний — владельческий реестр per-канал.

Что сюда пишется:
  - применённые наказания (таймаут любой длительности, бан навсегда) — движок
    (app/moderation.py) зовёт journal_applied после успешного Helix-вызова;
  - отложенные случаи «бана навсегда» на защищённого зрителя (и ask/learn-рекомендации) —
    journal_pending, статус pending, решение владельца переводит их в applied/cancelled.

Статусы журнала: applied / pending / cancelled / expired. Нерешённые случаи закрываются
автоматически через 30 дней (expire_stale_pending — лениво, при чтении журнала).

Схема создаётся moderation_journal.ensure_schema() — одной строкой из init_db.
Модуль НЕ импортирует app.moderation (только database), чтобы не было цикла.
"""
from __future__ import annotations

import logging

from app import database

logger = logging.getLogger(__name__)

JOURNAL_STATUSES = ("applied", "pending", "cancelled", "expired")
EXPIRE_AFTER_DAYS = 30


async def ensure_schema() -> None:
    """Таблица журнала наказаний. Идемпотентно; legacy-данные не трогает."""
    db = await database.get_db()
    try:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS moderation_journal ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " account_id INTEGER NOT NULL,"
            " channel TEXT NOT NULL DEFAULT '',"
            " username TEXT NOT NULL DEFAULT '',"
            " category TEXT NOT NULL DEFAULT '',"
            " severity INTEGER NOT NULL DEFAULT 0,"
            " rule_name TEXT NOT NULL DEFAULT '',"
            " message_excerpt TEXT NOT NULL DEFAULT '',"
            " action TEXT NOT NULL DEFAULT '',"           # timeout | ban | ''
            " duration_sec INTEGER,"                       # NULL = бан навсегда
            " status TEXT NOT NULL DEFAULT 'applied'"
            "  CHECK(status IN ('applied','pending','cancelled','expired')),"
            " detail TEXT NOT NULL DEFAULT '',"
            " pending_id INTEGER,"                         # строка очереди moderation_pending
            " created_at TEXT DEFAULT (datetime('now')),"
            " decided_at TEXT)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_mod_journal_acc_chan "
            "ON moderation_journal(account_id, channel, created_at)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_mod_journal_status ON moderation_journal(status)"
        )
        await db.commit()
    finally:
        await db.close()


def _norm_channel(channel: str) -> str:
    return (channel or "").lower().lstrip("#")


async def journal_applied(account_id: int, channel: str, username: str, *,
                          category: str, severity: int, rule_name: str,
                          action: str, duration_sec: int | None,
                          message_excerpt: str = "", detail: str = "") -> int:
    """Наказание реально применено (Helix ответил успехом)."""
    await ensure_schema()
    db = await database.get_db()
    try:
        cur = await db.execute(
            "INSERT INTO moderation_journal "
            "(account_id, channel, username, category, severity, rule_name, message_excerpt, "
            " action, duration_sec, status, detail) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'applied', ?)",
            (account_id, _norm_channel(channel), username or "", category or "", severity or 0,
             rule_name or "", (message_excerpt or "")[:200], action,
             int(duration_sec) if duration_sec is not None else None, detail or ""),
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


async def journal_shadow(account_id: int, channel: str, username: str, *,
                         category: str, severity: int, rule_name: str,
                         action: str, duration_sec: int | None = None,
                         message_excerpt: str = "",
                         detail: str = "[SHADOW] Теневой вердикт — реальное наказание не отправлялось") -> int:
    """Записывает теневой вердикт в журнал с пометкой [SHADOW] (наказание на Twitch НЕ отправлялось)."""
    await ensure_schema()
    db = await database.get_db()
    try:
        cur = await db.execute(
            "INSERT INTO moderation_journal "
            "(account_id, channel, username, category, severity, rule_name, message_excerpt, "
            " action, duration_sec, status, detail, decided_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'cancelled', ?, datetime('now'))",
            (account_id, _norm_channel(channel), username or "", category or "", severity or 0,
             rule_name or "", (message_excerpt or "")[:200], action,
             int(duration_sec) if duration_sec is not None else None, detail or "[SHADOW] Теневой вердикт"),
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


async def journal_pending(account_id: int, channel: str, username: str, *,
                          category: str, severity: int, rule_name: str,
                          action: str, duration_sec: int | None,
                          message_excerpt: str = "", detail: str = "",
                          pending_id: int | None = None) -> int:
    """Случай ждёт решения владельца: наказание НЕ применено (DEC-OWNER-014)."""
    await ensure_schema()
    db = await database.get_db()
    try:
        cur = await db.execute(
            "INSERT INTO moderation_journal "
            "(account_id, channel, username, category, severity, rule_name, message_excerpt, "
            " action, duration_sec, status, detail, pending_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
            (account_id, _norm_channel(channel), username or "", category or "", severity or 0,
             rule_name or "", (message_excerpt or "")[:200], action,
             int(duration_sec) if duration_sec is not None else None, detail or "", pending_id),
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


async def journal_resolve_by_pending(pending_id: int, *, approved: bool, executed: bool) -> None:
    """Решение владельца по очереди: executed → applied, отклонено → cancelled."""
    await ensure_schema()
    db = await database.get_db()
    try:
        if approved and executed:
            await db.execute(
                "UPDATE moderation_journal SET status = 'applied', decided_at = datetime('now'), "
                "detail = detail || ' · подтверждено владельцем' WHERE pending_id = ? AND status = 'pending'",
                (pending_id,),
            )
        else:
            await db.execute(
                "UPDATE moderation_journal SET status = 'cancelled', decided_at = datetime('now'), "
                "detail = detail || ' · отклонено владельцем' WHERE pending_id = ? AND status = 'pending'",
                (pending_id,),
            )
        await db.commit()
    finally:
        await db.close()


async def expire_stale_pending(max_age_days: int = EXPIRE_AFTER_DAYS) -> int:
    """Нерешённые случаи старше 30 дней → expired «не подтверждено, закрыт по сроку».

    Вызывается лениво при чтении журнала/очереди (отдельного планировщика нет)."""
    await ensure_schema()
    db = await database.get_db()
    try:
        cur = await db.execute(
            "UPDATE moderation_journal SET status = 'expired', decided_at = datetime('now'), "
            "detail = detail || ' · не подтверждено, закрыт по сроку' "
            "WHERE status = 'pending' AND created_at <= datetime('now', ?)",
            (f"-{int(max_age_days)} days",),
        )
        await db.commit()
        return cur.rowcount or 0
    finally:
        await db.close()


async def list_journal(account_id: int | None = None, channel: str | None = None,
                       limit: int = 100) -> list[dict]:
    """Журнал наказаний канала (или бота), свежее сверху. Сначала гасим просрочку."""
    await expire_stale_pending()
    await ensure_schema()
    q = ("SELECT j.*, a.nickname AS bot_nickname FROM moderation_journal j "
         "LEFT JOIN accounts a ON a.id = j.account_id WHERE 1=1")
    params: list = []
    if account_id is not None:
        q += " AND j.account_id = ?"
        params.append(account_id)
    if channel:
        q += " AND j.channel = ?"
        params.append(_norm_channel(channel))
    q += " ORDER BY j.id DESC LIMIT ?"
    params.append(max(1, min(500, limit)))
    db = await database.get_db()
    try:
        cur = await db.execute(q, params)
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


async def list_pending_cases(account_id: int | None = None,
                             channel: str | None = None) -> list[dict]:
    """Очередь подтверждения: наказание не применено и ждёт владельца."""
    await expire_stale_pending()
    await ensure_schema()
    q = ("SELECT j.*, a.nickname AS bot_nickname FROM moderation_journal j "
         "LEFT JOIN accounts a ON a.id = j.account_id WHERE j.status = 'pending'")
    params: list = []
    if account_id is not None:
        q += " AND j.account_id = ?"
        params.append(account_id)
    if channel:
        q += " AND j.channel = ?"
        params.append(_norm_channel(channel))
    q += " ORDER BY j.id ASC"
    db = await database.get_db()
    try:
        cur = await db.execute(q, params)
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()
