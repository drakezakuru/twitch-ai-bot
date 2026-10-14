"""MODERATION_PLAN: политика «кто таймаутит» (auto/ask/learn) + очередь вопросов.

Решение владельца 28.08.2026: бот может спрашивать владельца (всплывашка Да/Нет
в панели) и учиться на ответах — после порога одобрений по категории таймаутит сам.

Эндпоинты живут в отдельном роутере (правило FILE_ZONES «Общие файлы»):
подключается одной строкой include_router в app/server.py.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app import moderation as _mod
from app.security import auth_dependency
from app.routes import log_action

router = APIRouter(dependencies=[Depends(auth_dependency)])


@router.get("/api/accounts/{account_id}/moderation/timeout-policy")
async def get_timeout_policy(account_id: int) -> dict:
    settings = await _mod.get_settings(account_id)
    return {
        "ok": True,
        "policy": settings.get("timeout_policy", "auto"),
        "can_timeout": bool(settings.get("moderation_can_timeout")),
        "learn_stats": await _mod.get_learn_stats(account_id),
        "pending": await _mod.list_pending_timeouts(account_id, limit=50),
    }


@router.put("/api/accounts/{account_id}/moderation/timeout-policy")
async def put_timeout_policy(account_id: int, data: dict[str, Any]) -> dict:
    policy = str(data.get("policy") or "").strip()
    if policy not in _mod.POLICIES:
        return {"ok": False, "error": "bad_policy", "allowed": list(_mod.POLICIES)}
    db = await _mod.database.get_db()
    try:
        await db.execute("UPDATE accounts SET timeout_policy = ? WHERE id = ?", (policy, account_id))
        await db.commit()
    finally:
        await db.close()
    _mod.invalidate_cache(account_id)
    await log_action("moderation_timeout_policy", f"{account_id}: {policy}")
    return {"ok": True, "policy": policy}


@router.get("/api/moderation/pending")
async def get_pending_global() -> dict:
    """Все нерешённые вопросы по всем ботам — для всплывашки на Dashboard."""
    events = await _mod.list_pending_timeouts(None, limit=20)
    return {"ok": True, "events": events, "total": len(events)}


@router.post("/api/moderation/pending/{rec_id}/decision")
async def decide_pending(rec_id: int, data: dict[str, Any]) -> dict:
    approved = bool(data.get("approved"))
    # Токен/ник берём из аккаунта в БД — панель не должна их передавать.
    token, bot_nickname = "", ""
    db = await _mod.database.get_db()
    try:
        cur = await db.execute(
            "SELECT a.nickname, a.token FROM accounts a "
            "JOIN moderation_pending p ON p.account_id = a.id WHERE p.id = ?",
            (rec_id,),
        )
        row = await cur.fetchone()
        if row:
            bot_nickname = row["nickname"] or ""
            token = row["token"] or ""
    finally:
        await db.close()
    result = await _mod.record_timeout_decision(rec_id, approved, token=token, bot_nickname=bot_nickname)
    if result.get("ok"):
        await log_action("moderation_pending_decision", f"#{rec_id}: {'да' if approved else 'нет'}")
    return result
