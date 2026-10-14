"""attention — вынесено из app/routes.py (P5-сплит, PLAN.md). Декорирует ОБЩИЙ
router из app.routes; импортируется ВНИЗУ routes.py (после создания router).
"""
from fastapi import Request
from app.routes import router, get_db, router  # noqa: E402


# ===================== v11: ATTENTION CONFIG + CHAT USERS =====================

@router.get("/api/accounts/{account_id}/attention-config")
async def get_attention_config(account_id: int):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM bot_attention_config WHERE account_id = ?", (account_id,)
        )
        row = await cur.fetchone()
        return {"ok": True, "config": dict(row) if row else {
            "attention_mode": "everyone",
            "batch_window_sec": 5.0,
            "batch_max_size": 5,
            "min_messages_to_respond": 2,
            "ignore_noise": 1,
            "cooldown_after_reply_sec": 30.0,
            "max_replies_per_minute": 3,
            "dont_interrupt_streamer_sec": 0,
            "tts_reply_percent": 100,
            "reply_to_mentions": 1,
            "reply_to_keywords": 0,
            "reply_keywords": "",
        }}
    finally:
        await db.close()


@router.put("/api/accounts/{account_id}/attention-config")
async def update_attention_config(account_id: int, request: Request):
    body = await request.json()
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO bot_attention_config "
            "(account_id, attention_mode, batch_window_sec, batch_max_size, "
            "min_messages_to_respond, ignore_noise, cooldown_after_reply_sec, max_replies_per_minute, "
            "dont_interrupt_streamer_sec, tts_reply_percent, reply_to_mentions, "
            "reply_to_keywords, reply_keywords) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(account_id) DO UPDATE SET "
            "attention_mode=excluded.attention_mode, batch_window_sec=excluded.batch_window_sec, "
            "batch_max_size=excluded.batch_max_size, min_messages_to_respond=excluded.min_messages_to_respond, "
            "ignore_noise=excluded.ignore_noise, cooldown_after_reply_sec=excluded.cooldown_after_reply_sec, "
            "max_replies_per_minute=excluded.max_replies_per_minute, "
            "dont_interrupt_streamer_sec=excluded.dont_interrupt_streamer_sec, "
            "tts_reply_percent=excluded.tts_reply_percent, "
            "reply_to_mentions=excluded.reply_to_mentions, "
            "reply_to_keywords=excluded.reply_to_keywords, "
            "reply_keywords=excluded.reply_keywords",
            (
                account_id,
                body.get("attention_mode", "everyone"),
                body.get("batch_window_sec", 5.0),
                body.get("batch_max_size", 5),
                body.get("min_messages_to_respond", 2),
                body.get("ignore_noise", 1),
                body.get("cooldown_after_reply_sec", 30.0),
                body.get("max_replies_per_minute", 3),
                max(0, min(3600, int(body.get("dont_interrupt_streamer_sec", 0) or 0))),
                max(0, min(100, int(body.get("tts_reply_percent", 100) if body.get("tts_reply_percent") is not None else 100))),
                1 if body.get("reply_to_mentions", 1) else 0,
                1 if body.get("reply_to_keywords", 0) else 0,
                str(body.get("reply_keywords", "") or ""),
            ),
        )
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()
