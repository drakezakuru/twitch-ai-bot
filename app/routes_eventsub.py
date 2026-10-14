"""eventsub — вынесено из app/routes.py (P5-сплит, PLAN.md). Декорирует ОБЩИЙ
router из app.routes; импортируется ВНИЗУ routes.py (после создания router).
"""
from typing import Any

from app.database import get_db
from app.routes import decrypt_token, is_helix_configured
from app.routes import router  # noqa: E402


# ===================== FEATURE 3: EVENTSUB =====================

@router.get("/api/eventsub/status")
async def eventsub_status() -> dict:
    """Какие аккаунты сейчас в EventSub."""
    from app.server import eventsub_manager
    db = await get_db()
    try:
        cursor = await db.execute("SELECT id, nickname, eventsub_enabled FROM accounts")
        rows = await cursor.fetchall()
    finally:
        await db.close()
    return {
        "configured": is_helix_configured(),
        "accounts": [
            {
                "id": r["id"],
                "nickname": r["nickname"],
                "eventsub_enabled": bool(r["eventsub_enabled"]) if "eventsub_enabled" in r.keys() else False,
                "running": eventsub_manager.is_running(r["id"]),
            }
            for r in rows
        ],
    }


@router.post("/api/accounts/{account_id}/eventsub/toggle")
async def eventsub_toggle(account_id: int, data: dict[str, Any]) -> dict:
    """Вкл/выкл EventSub для аккаунта. Если бот запущен — стартуем/останавливаем сразу."""
    enabled = bool(data.get("enabled"))
    db = await get_db()
    try:
        await db.execute(
            "UPDATE accounts SET eventsub_enabled = ? WHERE id = ?",
            (1 if enabled else 0, account_id),
        )
        await db.commit()
        cursor = await db.execute("SELECT * FROM accounts WHERE id = ?", (account_id,))
        acc = await cursor.fetchone()
    finally:
        await db.close()
    if not acc:
        return {"ok": False, "error": "Аккаунт не найден"}

    from app.server import bot_manager, eventsub_manager
    status = bot_manager.get_status(account_id)
    if enabled and status.get("connected"):
        # запускаем для запущенного бота
        cursor_db = await get_db()
        try:
            cursor = await cursor_db.execute(
                "SELECT channel_name FROM channels WHERE account_id = ? AND enabled = 1", (account_id,)
            )
            channels = [r["channel_name"] for r in await cursor.fetchall()]
        finally:
            await cursor_db.close()
        await eventsub_manager.start_for_account(
            account_id, acc["nickname"], decrypt_token(acc["token"]), channels,
        )
    elif not enabled:
        await eventsub_manager.stop_for_account(account_id)
    return {"ok": True, "enabled": enabled}
