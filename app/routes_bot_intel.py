"""bot_intel — вынесено из app/routes.py (P5-сплит, PLAN.md). Декорирует ОБЩИЙ
router из app.routes; импортируется ВНИЗУ routes.py (после создания router).
"""
from fastapi import Request
from app.routes import router, get_db, user_memory  # noqa: E402


# ===================== BOT INTELLIGENCE: CONVERSATION THREADING =====================
import time as _time

_stream_conversations: dict[tuple[int, str], list[dict]] = {}


def get_conversation_context(account_id: int, channel: str, username: str, max_messages: int = 10) -> str:
    """Returns formatted context string for AI prompts."""
    key = (account_id, channel.lower())
    messages = _stream_conversations.get(key, [])
    relevant = [m for m in messages if m["username"].lower() == username.lower() or m["role"] == "bot"]
    recent = relevant[-max_messages:]
    if not recent:
        return ""
    lines = []
    for m in recent:
        prefix = f"[{m['role']}] {m['username']}"
        lines.append(f"{prefix}: {m['text']}")
    return "\n".join(lines)


@router.post("/api/bot/conversation/push")
async def bot_conversation_push(req: Request) -> dict:
    data = await req.json()
    account_id = data.get("account_id")
    channel = data.get("channel")
    username = data.get("username")
    text = data.get("text")
    if account_id is None or channel is None or username is None or text is None:
        return {"ok": False, "error": "Missing required fields: account_id, channel, username, text"}
    account_id = int(account_id)
    channel = channel.lower()
    role = data.get("role", "user")
    key = (account_id, channel)
    if key not in _stream_conversations:
        _stream_conversations[key] = []
    _stream_conversations[key].append({
        "role": role,
        "username": username,
        "text": text,
        "timestamp": _time.time(),
    })
    # Cap at 50 messages
    if len(_stream_conversations[key]) > 50:
        _stream_conversations[key] = _stream_conversations[key][-50:]
    return {"ok": True}


@router.get("/api/bot/conversation/context/{account_id}/{channel}/{username}")
async def bot_conversation_context(account_id: int, channel: str, username: str) -> dict:
    context = get_conversation_context(account_id, channel, username)
    key = (account_id, channel.lower())
    messages = _stream_conversations.get(key, [])
    relevant = [m for m in messages if m["username"].lower() == username.lower() or m["role"] == "bot"]
    return {"context": context, "message_count": len(relevant[-10:])}


@router.post("/api/bot/conversation/reset")
async def bot_conversation_reset(req: Request) -> dict:
    data = await req.json()
    account_id = int(data["account_id"])
    channel = data["channel"].lower()
    key = (account_id, channel)
    _stream_conversations.pop(key, None)
    return {"ok": True}


@router.get("/api/bot/conversation/sessions")
async def bot_conversation_sessions() -> list:
    sessions = []
    for (account_id, channel), msgs in _stream_conversations.items():
        sessions.append({"account_id": account_id, "channel": channel, "message_count": len(msgs)})
    return sessions


# ===================== BOT INTELLIGENCE: LEARNING FROM CORRECTIONS =====================

_session_corrections: dict[tuple[int, str], list[dict]] = {}


@router.post("/api/bot/corrections/learn")
async def bot_corrections_learn(req: Request) -> dict:
    data = await req.json()
    account_id = data.get("account_id")
    username = data.get("username")
    correction_text = data.get("correction_text")
    if account_id is None or username is None or correction_text is None:
        return {"ok": False, "error": "Missing required fields: account_id, username, correction_text"}
    account_id = int(account_id)
    channel = data.get("channel", "").lower()
    original_context = data.get("original_context", "")
    key = (account_id, channel)
    # Store in session memory
    if key not in _session_corrections:
        _session_corrections[key] = []
    _session_corrections[key].append({
        "username": username,
        "correction": correction_text,
        "original_context": original_context,
        "timestamp": _time.time(),
    })
    # Cap at 100 corrections per session (trim oldest)
    if len(_session_corrections[key]) > 100:
        _session_corrections[key] = _session_corrections[key][-100:]
    # Store in DB
    db = await get_db()
    try:
        cur = await db.execute(
            "INSERT INTO bot_corrections (account_id, channel, username, original_context, correction) VALUES (?, ?, ?, ?, ?)",
            (account_id, channel, username, original_context, correction_text),
        )
        await db.commit()
        return {"ok": True, "id": cur.lastrowid}
    finally:
        await db.close()


def get_corrections_context(account_id: int, channel: str) -> str:
    """Format recent channel-scoped corrections for prompt injection."""
    corrections = _session_corrections.get((int(account_id), channel.lower()), [])
    if not corrections:
        return ""
    lines = ["Учитывай исправления владельца для этого канала:"]
    for c in corrections[-20:]:
        line = f"- [{c['username']}] {c['correction']}"
        if c.get("original_context"):
            line += f" (исправляет: {c['original_context']})"
        lines.append(line)
    return "\n".join(lines)


@router.get("/api/bot/corrections/context/{account_id}/{channel}")
async def bot_corrections_context(account_id: int, channel: str) -> dict:
    context = get_corrections_context(account_id, channel)
    return {"context": context, "count": max(0, len(context.splitlines()) - 1) if context else 0}


@router.put("/api/bot/corrections/{correction_id}/permanent")
async def bot_corrections_toggle_permanent(correction_id: int) -> dict:
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT account_id, username, correction, permanent FROM bot_corrections WHERE id = ?",
            (correction_id,),
        )
        row = await cur.fetchone()
        if not row:
            return {"ok": False, "error": "Not found"}
        account_id = row[0]
        username = row[1]
        correction_text = row[2]
        current_perm = row[3]
        new_perm = 0 if current_perm else 1
        await db.execute(
            "UPDATE bot_corrections SET permanent = ? WHERE id = ?",
            (new_perm, correction_id),
        )
        await db.commit()
        # If setting permanent, store to user memory
        if new_perm == 1:
            await user_memory.add_fact(account_id, username, correction_text)
        return {"ok": True, "permanent": new_perm}
    finally:
        await db.close()


@router.get("/api/bot/corrections/list/{account_id}")
async def bot_corrections_list(account_id: int) -> dict:
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT id, channel, username, original_context, correction, permanent, created_at FROM bot_corrections WHERE account_id = ? ORDER BY id DESC LIMIT 50",
            (account_id,),
        )
        rows = await cur.fetchall()
        items = []
        for r in rows:
            items.append({
                "id": r[0], "channel": r[1], "username": r[2],
                "original_context": r[3], "correction": r[4],
                "permanent": r[5], "created_at": r[6],
            })
        return {"items": items}
    finally:
        await db.close()


@router.post("/api/bot/corrections/clear-session")
async def bot_corrections_clear_session(req: Request) -> dict:
    data = await req.json()
    account_id = int(data["account_id"])
    channel = data.get("channel", "").lower()
    key = (account_id, channel)
    _session_corrections.pop(key, None)
    return {"ok": True}
