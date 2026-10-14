"""user_history — вынесено из app/routes.py (P5-сплит, PLAN.md). Декорирует ОБЩИЙ
router из app.routes; импортируется ВНИЗУ routes.py (после создания router).
"""
from typing import Any

from app.database import get_db, get_setting, set_setting
from app.routes import user_memory
from app.routes import router  # noqa: E402


# ===================== v12: USER MESSAGE HISTORY (контекст per-user) =====================

@router.get("/api/accounts/{account_id}/memory/{username}/history")
async def get_user_message_history(
    account_id: int, username: str, channel: str = "", limit: int = 5
) -> list[dict]:
    """Возвращает последние N сообщений пользователя в контексте канала."""
    if not channel:
        # Берём первый активный канал
        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT channel_name FROM channels WHERE account_id = ? AND enabled = 1 LIMIT 1",
                (account_id,),
            )
            row = await cursor.fetchone()
            channel = row["channel_name"] if row else ""
        finally:
            await db.close()


    return await user_memory.get_message_history(
        account_id, channel, username, limit=min(int(limit), 20)
    )


@router.get("/api/onboarding")
async def get_onboarding_state() -> dict:
    """Return first-run state shared by browsers using this panel."""
    return {"completed": await get_setting("onboarding_completed", "0") == "1",
            "dismissed": await get_setting("onboarding_dismissed", "0") == "1"}


@router.put("/api/onboarding")
async def update_onboarding_state(data: dict[str, Any]) -> dict:
    if "completed" in data:
        await set_setting("onboarding_completed", "1" if data["completed"] else "0")
    if "dismissed" in data:
        await set_setting("onboarding_dismissed", "1" if data["dismissed"] else "0")
    return await get_onboarding_state()


@router.delete("/api/accounts/{account_id}/memory/{username}/history")
async def clear_user_message_history(account_id: int, username: str) -> dict:
    """Очищает историю сообщений пользователя."""
    db = await get_db()
    try:
        await db.execute(
            "DELETE FROM user_message_history WHERE account_id = ? AND username = ?",
            (account_id, username.lower().strip()),
        )
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()
