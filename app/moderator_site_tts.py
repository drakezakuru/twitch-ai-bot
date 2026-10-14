"""MOD-16: TTS adapter — voice policy, audio queue, cancellable late results.

This layer adds ONLY policy and correlation on top of cue admission: quota and
scope checks live in the admission layer (MOD-13) and are deliberately NOT
repeated here. Provider calls are injectable (no ML/cloud in tests); a late
synthesis result for a cancelled correlation is dropped, never played.
"""
from __future__ import annotations

import secrets
import time
from typing import Any, Awaitable, Callable

ALLOWED_VOICES = frozenset({"alena", "dmitri", "tanya", "standard"})
MAX_TEXT_CHARS = 500  # unicode code points, not bytes

SynthFn = Callable[[str, str], Awaitable[str]]  # (text, voice) -> audio token


async def ensure_schema(db: Any) -> None:
    await db.executescript("""
    CREATE TABLE IF NOT EXISTS ms_tts_commands (
      id TEXT PRIMARY KEY, correlation_id TEXT NOT NULL UNIQUE,
      channel TEXT NOT NULL, voice TEXT NOT NULL, text TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'queued',
      created_at REAL NOT NULL, finished_at REAL, audio_token TEXT NOT NULL DEFAULT '');
    """)


async def submit(db: Any, synth: SynthFn, *, channel: str, text: str, voice: str,
                 correlation_id: str | None = None) -> dict[str, Any]:
    """Policy-checked TTS submit; synthesis starts immediately (fake or real provider)."""
    if voice not in ALLOWED_VOICES:
        raise ValueError("voice_not_allowed")
    if len(text) > MAX_TEXT_CHARS:
        raise ValueError("tts_text_too_long")
    if not text.strip():
        raise ValueError("tts_text_empty")
    if correlation_id is not None:
        existing = await (await db.execute(
            "SELECT correlation_id, status FROM ms_tts_commands WHERE correlation_id=?", (correlation_id,)
        )).fetchone()
        if existing is not None:
            return {"correlation_id": existing[0], "status": existing[1], "deduplicated": True}
    correlation = correlation_id or secrets.token_hex(16)
    command_id = secrets.token_hex(16)
    await db.execute(
        "INSERT INTO ms_tts_commands(id, correlation_id, channel, voice, text, status, created_at)"
        " VALUES (?,?,?,?,?,'synthesizing',?)",
        (command_id, correlation, channel, voice, text, time.time()))
    await db.commit()
    try:
        audio_token = await synth(text, voice)
    except Exception:
        await db.execute("UPDATE ms_tts_commands SET status='failed', finished_at=? WHERE id=?",
                         (time.time(), command_id))
        await db.commit()
        return {"correlation_id": correlation, "status": "failed"}
    # Late-result guard: the command may have been cancelled while synthesizing.
    state = await (await db.execute("SELECT status FROM ms_tts_commands WHERE id=?", (command_id,))).fetchone()
    if state[0] == "cancelled":
        return {"correlation_id": correlation, "status": "cancelled", "dropped": True}
    await db.execute("UPDATE ms_tts_commands SET status='done', finished_at=?, audio_token=? WHERE id=?",
                     (time.time(), audio_token, command_id))
    await db.commit()
    return {"correlation_id": correlation, "status": "done", "dropped": False}


async def cancel(db: Any, correlation_id: str) -> bool:
    """Stop-during-synthesis: mark cancelled; a late result will be dropped."""
    cursor = await db.execute(
        "UPDATE ms_tts_commands SET status='cancelled', finished_at=?"
        " WHERE correlation_id=? AND status IN ('queued','synthesizing')", (time.time(), correlation_id))
    await db.commit()
    return bool(cursor.rowcount)


async def status(db: Any, correlation_id: str) -> dict[str, Any] | None:
    row = await (await db.execute(
        "SELECT correlation_id, channel, voice, status FROM ms_tts_commands WHERE correlation_id=?",
        (correlation_id,))).fetchone()
    if row is None:
        return None
    return {"correlation_id": row[0], "channel": row[1], "voice": row[2], "status": row[3]}
