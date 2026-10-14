"""MOD-15: soundboard adapter — correlation, dedup, safe status, stop scope.

Reuses the read-only library projection (approved items only) and a single
dispatch path. Every play carries a correlation id; the same id is never
dispatched twice, so retries and restart ambiguity cannot double-play a sound.
"""
from __future__ import annotations

import json
import secrets
import time
from typing import Any, Awaitable, Callable

DispatchFn = Callable[[str, str, dict[str, Any]], Awaitable[None]]  # (channel, path, meta)


async def ensure_schema(db: Any) -> None:
    await db.executescript("""
    CREATE TABLE IF NOT EXISTS ms_sound_commands (
      id TEXT PRIMARY KEY, correlation_id TEXT NOT NULL UNIQUE,
      account_id INTEGER NOT NULL, channel TEXT NOT NULL,
      sound_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'dispatched',
      dispatched_at REAL NOT NULL, stopped_at REAL);
    """)


async def play(db: Any, dispatch: DispatchFn, *, account_id: int, channel: str,
               sound_id: str, correlation_id: str | None = None,
               from_library: Any = None) -> dict[str, Any]:
    """Dispatch once per correlation id; the sound must be an approved library item."""
    if correlation_id is not None:
        existing = await (await db.execute(
            "SELECT status, correlation_id FROM ms_sound_commands WHERE correlation_id=?",
            (correlation_id,),
        )).fetchone()
        if existing is not None:
            # Restart ambiguity: an already-dispatched correlation never replays.
            return {"correlation_id": existing[1], "status": existing[0], "deduplicated": True}
    if from_library is not None:
        items = await from_library.list_items(
            db, account_id=account_id, channel=channel, kind="sound", limit=100)
        if not any(item["id"] == sound_id for item in items["items"]):
            raise ValueError("sound_not_in_scope")  # чужой канал / unapproved звук
    correlation = correlation_id or secrets.token_hex(16)
    command_id = secrets.token_hex(16)
    # Safe status metadata only: no paths, no tokens.
    await db.execute(
        "INSERT INTO ms_sound_commands(id, correlation_id, account_id, channel, sound_id, dispatched_at)"
        " VALUES (?,?,?,?,?,?)",
        (command_id, correlation, account_id, channel, sound_id, time.time()))
    await db.commit()
    await dispatch(channel, "sound", {"correlation_id": correlation, "sound_id": sound_id})
    return {"correlation_id": correlation, "status": "dispatched", "deduplicated": False}


async def stop_scope(db: Any, dispatch: DispatchFn, channel: str) -> int:
    """Stop every live sound command in the scope; returns the count stopped."""
    rows = await (await db.execute(
        "SELECT id, correlation_id FROM ms_sound_commands WHERE channel=? AND status='dispatched'",
        (channel,),
    )).fetchall()
    now = time.time()
    for row_id, correlation in rows:
        await db.execute(
            "UPDATE ms_sound_commands SET status='stopped', stopped_at=? WHERE id=?", (now, row_id))
        await dispatch(channel, "sound_stop", {"correlation_id": correlation})
    await db.commit()
    return len(rows)


async def safe_status(db: Any, correlation_id: str) -> dict[str, Any] | None:
    row = await (await db.execute(
        "SELECT correlation_id, channel, sound_id, status FROM ms_sound_commands WHERE correlation_id=?",
        (correlation_id,),
    )).fetchone()
    if row is None:
        return None
    return {"correlation_id": row[0], "channel": row[1], "sound_id": row[2], "status": row[3]}
