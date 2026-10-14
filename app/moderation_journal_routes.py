"""Q26 (DEC-OWNER-014): API журнала наказаний, очереди подтверждения, защищённых и разбана.

Только панель и только владелец (auth_dependency): ни модераторского сайта, ни всплывашек,
ни автоматической отмены наказаний — см. «Не делать» в PLAN_TODO Q26.

Подключается одной строкой include_router в app/server.py.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app import database
from app import moderation as _mod
from app import moderation_journal as _journal
from app.security import auth_dependency
from app.routes import log_action

router = APIRouter(dependencies=[Depends(auth_dependency)])


@router.get("/api/moderation/journal")
async def get_journal(channel: str = "", account_id: int | None = None,
                      limit: int = 100) -> dict:
    """Журнал наказаний канала/бота: кто, когда, за что, действие, статус."""
    rows = await _journal.list_journal(account_id=account_id, channel=channel, limit=limit)
    return {"ok": True, "entries": rows, "total": len(rows)}


@router.get("/api/moderation/journal/pending")
async def get_pending_cases(channel: str = "", account_id: int | None = None) -> dict:
    """Очередь подтверждения: наказание не применено и ждёт решения владельца."""
    rows = await _journal.list_pending_cases(account_id=account_id, channel=channel)
    return {"ok": True, "entries": rows, "total": len(rows)}


@router.post("/api/moderation/journal/{entry_id}/resolve")
async def resolve_pending_case(entry_id: int, data: dict[str, Any]) -> dict:
    """Решение по случаю из очереди ЖУРНАЛА: approve=True → исполнить запрошенное наказание.

    Исполнение идёт через существующую очередь moderation_pending (строим вторую очередь? нет —
    план прямо запрещает): у журнальной строки есть pending_id на строку moderation_pending."""
    approve = bool(data.get("approve"))
    db = await database.get_db()
    try:
        cur = await db.execute(
            "SELECT id, pending_id, status, account_id FROM moderation_journal WHERE id = ?",
            (entry_id,),
        )
        row = await cur.fetchone()
    finally:
        await db.close()
    if not row:
        return {"ok": False, "error": "not_found"}
    if row["status"] != "pending":
        return {"ok": False, "error": "already_decided"}
    pending_id = row["pending_id"]
    if not pending_id:
        return {"ok": False, "error": "no_pending_ref"}
    # Токен/ник — из аккаунта в БД, панель их не передаёт.
    token, bot_nickname = "", ""
    db = await database.get_db()
    try:
        cur = await db.execute("SELECT nickname, token FROM accounts WHERE id = ?", (row["account_id"],))
        acc = await cur.fetchone()
        if acc:
            bot_nickname = acc["nickname"] or ""
            token = acc["token"] or ""
    finally:
        await db.close()
    result = await _mod.record_timeout_decision(pending_id, approve, token=token, bot_nickname=bot_nickname)
    if result.get("ok"):
        await log_action("moderation_journal_resolve", f"#{entry_id}: {'да' if approve else 'нет'}")
    return result


@router.post("/api/moderation/journal/unban")
async def unban_viewer(data: dict[str, Any]) -> dict:
    """Кнопка «Разбанить»: официальный Unban User (DELETE /moderation/bans).

    400 «user is not banned» возвращается как already_unbanned — UI показывает
    «уже не забанен», а не ошибку."""
    from app import twitch_helix
    account_id = int(data.get("account_id") or 0)
    channel = str(data.get("channel") or "")
    username = str(data.get("username") or "").strip()
    if not account_id or not channel or not username:
        return {"ok": False, "error": "Нужны account_id, channel и username"}
    db = await database.get_db()
    try:
        cur = await db.execute("SELECT nickname, token FROM accounts WHERE id = ?", (account_id,))
        acc = await cur.fetchone()
    finally:
        await db.close()
    if not acc:
        return {"ok": False, "error": "Аккаунт не найден"}
    ok, err = await twitch_helix.unban_user(
        token=acc["token"] or "",
        channel=channel,
        moderator_login=acc["nickname"] or "",
        username=username,
    )
    if ok:
        await log_action("moderation_unban", f"{channel}: {username}")
        return {"ok": True}
    if err == "user_not_banned":
        return {"ok": True, "already_unbanned": True}
    return {"ok": False, "error": err}


@router.post("/api/moderation/punish")
async def manual_punish(data: dict[str, Any]) -> dict:
    """Ручное наказание зрителя из панели (таймаут или бан) с указанием причины."""
    from app import twitch_helix
    account_id = int(data.get("account_id") or 0)
    channel = str(data.get("channel") or "")
    username = str(data.get("username") or "").strip()
    duration_sec = int(data.get("duration_sec") or 0)
    reason = str(data.get("reason") or "manual moderation").strip()
    if not account_id or not channel or not username:
        return {"ok": False, "error": "Нужны account_id, channel и username"}
    db = await database.get_db()
    try:
        cur = await db.execute("SELECT nickname, token FROM accounts WHERE id = ?", (account_id,))
        acc = await cur.fetchone()
    finally:
        await db.close()
    if not acc:
        return {"ok": False, "error": "Аккаунт не найден"}

    token = acc["token"] or ""
    bot_nickname = acc["nickname"] or ""
    action = "ban" if duration_sec <= 0 else "timeout"
    if action == "ban":
        ok, err = await twitch_helix.ban_user(
            token=token, channel=channel, moderator_login=bot_nickname,
            username=username, reason=reason,
        )
    else:
        ok, err = await twitch_helix.timeout_user(
            token=token, channel=channel, moderator_login=bot_nickname,
            username=username, duration_sec=duration_sec, reason=reason,
        )
    if ok:
        await _journal.journal_applied(
            account_id, channel, username,
            category="manual", severity=5 if action == "ban" else 3,
            rule_name=f"manual:{reason}", action=action,
            duration_sec=None if action == "ban" else duration_sec,
            message_excerpt=f"{action} {duration_sec}s ({reason})",
        )
        await log_action("moderation_manual_punish", f"{channel}: {action} {username} ({reason})")
        return {"ok": True, "action": action, "duration_sec": duration_sec}
    return {"ok": False, "error": err}


# ─── список защищённых (per-бот × per-канал; защита модераторов автоматическая) ───

@router.get("/api/moderation/protected")
async def get_protected(account_id: int, channel: str) -> dict:
    rows = await _mod.list_protected(account_id, channel)
    auto = sorted(_mod.PROTECTED_ROLES)
    return {"ok": True, "entries": rows, "auto_roles": auto}


@router.post("/api/moderation/protected")
async def add_protected(data: dict[str, Any]) -> dict:
    account_id = int(data.get("account_id") or 0)
    channel = str(data.get("channel") or "")
    username = str(data.get("username") or "").strip()
    note = str(data.get("note") or "")[:200]
    if not account_id or not channel or not username:
        return {"ok": False, "error": "Нужны account_id, channel и username"}
    row_id = await _mod.add_protected(account_id, channel, username, note=note)
    await log_action("moderation_protected_add", f"{channel}: {username}")
    return {"ok": True, "id": row_id}


@router.delete("/api/moderation/protected/{username}")
async def remove_protected(username: str, account_id: int, channel: str) -> dict:
    removed = await _mod.remove_protected(account_id, channel, username)
    if removed:
        await log_action("moderation_protected_remove", f"{channel}: {username}")
    return {"ok": True, "removed": removed}
