"""MOD-14: media dispatcher and placement adapter.

Per-cue placement rides on the command itself and never writes the scope-wide
legacy config (the old URL keeps working unchanged). Output follows an explicit
current-command lifecycle: at most one `current` command per channel, claim ->
ACK -> done, with expiry and replacement as first-class transitions.
"""
from __future__ import annotations

import json
import secrets
import time
from typing import Any

COMMAND_TTL_SEC = 300


async def ensure_schema(db: Any) -> None:
    await db.executescript("""
    CREATE TABLE IF NOT EXISTS ms_media_commands (
      id TEXT PRIMARY KEY, cue_id TEXT NOT NULL, account_id INTEGER NOT NULL,
      channel TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
      placement_json TEXT NOT NULL DEFAULT '{}',
      generation INTEGER NOT NULL DEFAULT 1,
      created_at REAL NOT NULL, claimed_at REAL, ack_at REAL, done_at REAL);
    CREATE INDEX IF NOT EXISTS ms_media_channel ON ms_media_commands(channel, status);
    """)


async def enqueue(db: Any, *, cue_id: str, account_id: int, channel: str,
                  placement: dict[str, Any], now: float | None = None) -> dict[str, Any]:
    """New commands never mutate the legacy scope config; they carry placement inline."""
    now = time.time() if now is None else now
    await db.execute("BEGIN IMMEDIATE")
    try:
        # Replace whatever is currently playing: explicit lifecycle, no silent overlap.
        await db.execute(
            "UPDATE ms_media_commands SET status='replaced', done_at=?"
            " WHERE channel=? AND status='current'", (now, channel))
        command_id = secrets.token_hex(16)
        await db.execute(
            "INSERT INTO ms_media_commands(id, cue_id, account_id, channel, status, placement_json,"
            " created_at) VALUES (?,?,?,?, 'queued', ?, ?)",
            (command_id, cue_id, account_id, channel, json.dumps(placement, ensure_ascii=False), now))
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return {"command_id": command_id, "status": "queued"}


async def claim_next(db: Any, channel: str, *, now: float | None = None) -> dict[str, Any] | None:
    """Renderer claims the next queued command and makes it the single current one."""
    now = time.time() if now is None else now
    await db.execute("BEGIN IMMEDIATE")
    try:
        await db.execute(
            "UPDATE ms_media_commands SET status='expired', done_at=?"
            " WHERE channel=? AND status='queued' AND created_at<?", (now, channel, now - COMMAND_TTL_SEC))
        await db.execute(
            "UPDATE ms_media_commands SET status='expired', done_at=?"
            " WHERE channel=? AND status='current' AND claimed_at<?", (now, channel, now - COMMAND_TTL_SEC))
        # Explicit current-command lifecycle: a live current command blocks the claim.
        busy = await (await db.execute(
            "SELECT count(*) FROM ms_media_commands WHERE channel=? AND status='current'", (channel,)
        )).fetchone()
        row = None
        if not busy[0]:
            row = await (await db.execute(
                "SELECT id, cue_id, placement_json FROM ms_media_commands"
                " WHERE channel=? AND status='queued' ORDER BY created_at LIMIT 1", (channel,)
            )).fetchone()
        if row is None:
            await db.commit()
            return None
        await db.execute(
            "UPDATE ms_media_commands SET status='current', claimed_at=? WHERE id=?", (now, row[0]))
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return {"command_id": row[0], "cue_id": row[1], "placement": json.loads(row[2]), "status": "current"}


async def ack(db: Any, command_id: str, *, generation: int, now: float | None = None) -> dict[str, Any]:
    """Renderer ACK: only the current generation of a live command may finish it."""
    now = time.time() if now is None else now
    row = await (await db.execute(
        "SELECT status, generation FROM ms_media_commands WHERE id=?", (command_id,)
    )).fetchone()
    if row is None:
        raise ValueError("command_missing")
    if row[0] != "current":
        raise ValueError("command_not_current")
    if int(row[1]) != int(generation):
        raise ValueError("generation_mismatch")
    await db.execute(
        "UPDATE ms_media_commands SET status='done', ack_at=?, done_at=? WHERE id=?",
        (now, now, command_id))
    await db.commit()
    return {"command_id": command_id, "status": "done"}


async def replace(db: Any, command_id: str, *, now: float | None = None) -> dict[str, Any]:
    now = time.time() if now is None else now
    cursor = await db.execute(
        "UPDATE ms_media_commands SET status='replaced', done_at=? WHERE id=? AND status='current'",
        (now, command_id))
    await db.commit()
    if not cursor.rowcount:
        raise ValueError("command_not_current")
    return {"command_id": command_id, "status": "replaced"}


def build_media_url(base_url: str, command_id: str) -> str:
    """Compatibility contract: the legacy scope URL is never rewritten here."""
    return f"{base_url.rstrip('/')}/ms/media/{command_id}"
