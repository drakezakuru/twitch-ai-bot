"""channel_info — вынесено из app/routes.py (P5-сплит, PLAN.md). Декорирует ОБЩИЙ
router из app.routes; импортируется ВНИЗУ routes.py (после создания router).
"""
from app.database import get_db
from app.routes import decrypt_token, get_channel_info, is_helix_configured
from app.routes import router  # noqa: E402


# ===================== FEATURE 4: CHANNEL INFO (HELIX) =====================

@router.get("/api/accounts/{account_id}/channels/{channel}/stats")
async def channel_stats(account_id: int, channel: str) -> dict:
    """Статистика канала для карточки (§9.1): сообщений всего и время последнего."""
    ch = channel.lower().strip().lstrip("#")
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT COUNT(*) AS cnt, MAX(timestamp) AS last_at FROM chat_log "
            "WHERE account_id = ? AND channel = ?",
            (account_id, ch),
        )
        row = await cursor.fetchone()
        return {"ok": True, "channel": ch, "messages": row["cnt"] or 0, "last_message_at": row["last_at"]}
    finally:
        await db.close()


@router.get("/api/channels/{channel}/info")
async def channel_info(channel: str, account_id: int = 0) -> dict:
    """Получает текущую игру/название/количество зрителей канала через Helix."""
    if not is_helix_configured():
        return {"ok": False, "error": "TWITCH_CLIENT_ID/SECRET не заданы"}
    db = await get_db()
    try:
        # Берём токен любого включённого аккаунта (если account_id=0)
        if account_id:
            cursor = await db.execute("SELECT token FROM accounts WHERE id = ?", (account_id,))
        else:
            cursor = await db.execute("SELECT token FROM accounts WHERE enabled = 1 LIMIT 1")
        row = await cursor.fetchone()
        if not row:
            return {"ok": False, "error": "Нет активных аккаунтов"}
        token = decrypt_token(row["token"])
    finally:
        await db.close()
    info = await get_channel_info(channel, token)
    if not info:
        return {"ok": False, "error": "Канал не найден или Twitch недоступен"}
    return {"ok": True, **info}
