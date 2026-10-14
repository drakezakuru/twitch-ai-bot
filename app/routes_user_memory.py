"""user_memory — вынесено из app/routes.py (P5-сплит, PLAN.md). Декорирует ОБЩИЙ
router из app.routes; импортируется ВНИЗУ routes.py (после создания router).
"""
from typing import Any

from app.database import get_db
from app.routes import user_memory
from app.routes import router  # noqa: E402


# ===================== FEATURE 5: USER MEMORY =====================

@router.get("/api/accounts/{account_id}/memory")
async def list_memory(account_id: int, limit: int = 100) -> list[dict]:
    return await user_memory.list_user_memory(account_id, limit=limit)


@router.get("/api/accounts/{account_id}/memory/{username}")
async def get_memory(account_id: int, username: str) -> dict:
    mem = await user_memory.get_user_memory(account_id, username)
    return mem or {"username": username, "facts": [], "msg_count": 0, "last_seen": None}


@router.post("/api/accounts/{account_id}/memory/{username}")
async def add_memory_fact(account_id: int, username: str, data: dict[str, Any]) -> dict:
    fact = data.get("fact", "").strip()
    if not fact:
        return {"ok": False, "error": "Пустой факт"}
    ok = await user_memory.add_fact(
        account_id, username, fact, priority=data.get("priority", 50),
        expires_at=data.get("expires_at"), ttl=data.get("ttl", data.get("ttl_seconds")),
    )
    return {"ok": ok}


@router.put("/api/accounts/{account_id}/memory/{username}/fact")
async def update_memory_fact(account_id: int, username: str, data: dict[str, Any]) -> dict:
    """Update metadata by re-merging the selected fact without changing its API shape."""
    fact = str(data.get("fact") or "").strip()
    if not fact:
        return {"ok": False, "error": "Пустой факт"}
    ok = await user_memory.update_fact(
        account_id, username, fact, priority=data.get("priority", 50),
        expires_at=data.get("expires_at"), ttl=data.get("ttl", data.get("ttl_seconds")),
    )
    return {"ok": ok}


@router.delete("/api/accounts/{account_id}/memory/{username}")
async def delete_memory_user(account_id: int, username: str) -> dict:
    ok = await user_memory.delete_user(account_id, username)
    return {"ok": ok}


@router.delete("/api/accounts/{account_id}/memory/{username}/fact")
async def delete_memory_fact(account_id: int, username: str, data: dict[str, Any]) -> dict:
    fact = data.get("fact", "")
    ok = await user_memory.remove_fact(account_id, username, fact)
    return {"ok": ok}


def _affinity_scope(channel: str = "", username: str = "") -> tuple[str, str]:
    return channel.lower().strip().lstrip("#"), username.lower().strip()


@router.get("/api/accounts/{account_id}/affinity")
async def get_affinity(account_id: int, channel: str = "", username: str = "") -> dict:
    channel, username = _affinity_scope(channel, username)
    db = await get_db()
    try:
        if channel or username:
            cur = await db.execute(
                "SELECT contact_level, chat_affinity, auto_adjust, manual_lock, channel, username "
                "FROM bot_affinity WHERE account_id = ? AND channel = ? AND username = ?",
                (account_id, channel, username),
            )
            row = await cur.fetchone()
            return dict(row) if row else {
                "contact_level": 50, "chat_affinity": 50, "auto_adjust": 0,
                "manual_lock": 0, "channel": channel, "username": username,
            }
        cur = await db.execute("SELECT contact_level, chat_affinity, auto_adjust FROM bot_streamer_affinity WHERE account_id = ?", (account_id,))
        row = await cur.fetchone()
        return dict(row) if row else {"contact_level": 50, "chat_affinity": 50, "auto_adjust": 0}
    finally:
        await db.close()


@router.put("/api/accounts/{account_id}/affinity")
async def update_affinity(account_id: int, data: dict[str, Any]) -> dict:
    def clamp(value: Any, default: int = 50) -> int:
        try:
            return max(0, min(100, int(value)))
        except (TypeError, ValueError):
            return default
    contact = clamp(data.get("contact_level"))
    chat = clamp(data.get("chat_affinity"))
    auto = 1 if data.get("auto_adjust") else 0
    locked = 1 if data.get("manual_lock") else 0
    channel, username = _affinity_scope(str(data.get("channel") or ""), str(data.get("username") or ""))
    db = await get_db()
    try:
        if channel or username:
            await db.execute(
                "INSERT INTO bot_affinity (account_id, channel, username, contact_level, chat_affinity, auto_adjust, manual_lock) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(account_id, channel, username) DO UPDATE SET "
                "contact_level=excluded.contact_level, chat_affinity=excluded.chat_affinity, auto_adjust=excluded.auto_adjust, "
                "manual_lock=excluded.manual_lock, updated_at=CURRENT_TIMESTAMP",
                (account_id, channel, username, contact, chat, auto, locked),
            )
            await db.execute(
                "INSERT INTO bot_affinity_history (account_id, channel, username, contact_level, chat_affinity, auto_adjust, manual_lock, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (account_id, channel, username, contact, chat, auto, locked, "manual"),
            )
            await db.commit()
            return {"ok": True, "channel": channel, "username": username, "contact_level": contact,
                    "chat_affinity": chat, "auto_adjust": auto, "manual_lock": locked}
        await db.execute(
            "INSERT INTO bot_streamer_affinity (account_id, contact_level, chat_affinity, auto_adjust) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(account_id) DO UPDATE SET contact_level=excluded.contact_level, chat_affinity=excluded.chat_affinity, auto_adjust=excluded.auto_adjust, updated_at=CURRENT_TIMESTAMP",
            (account_id, contact, chat, auto),
        )
        await db.commit()
        return {"ok": True, "contact_level": contact, "chat_affinity": chat, "auto_adjust": auto}
    finally:
        await db.close()


@router.get("/api/accounts/{account_id}/affinity/history")
async def affinity_history(account_id: int, channel: str = "", username: str = "", limit: int = 50) -> dict:
    channel, username = _affinity_scope(channel, username)
    limit = max(1, min(200, int(limit)))
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM bot_affinity_history WHERE account_id = ? AND channel = ? AND username = ? "
            "ORDER BY id DESC LIMIT ?", (account_id, channel, username, limit),
        )
        return {"ok": True, "history": [dict(row) for row in await cur.fetchall()]}
    finally:
        await db.close()
