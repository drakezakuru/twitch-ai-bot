"""Exact-scoped selection of the single OBS source allowed to play TTS audio."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.database import get_db
from app.moderator_console_routes import _owner_auth_dependency
from app.tts_voice_policy import normalize_channel

SOURCES = {"tts-bot", "chat-reader", "tts-raw"}
router = APIRouter(prefix="/api/tts-audio-output", tags=["tts-audio-output"])


async def ensure_schema(db=None) -> None:
    own = db is None
    db = db or await get_db()
    try:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tts_audio_output (
                account_id INTEGER NOT NULL, channel TEXT NOT NULL, source TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(account_id, channel),
                FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
            )
        """)
        await db.commit()
    finally:
        if own:
            await db.close()


async def get_output(account_id: int, channel: str) -> dict:
    channel = normalize_channel(channel)
    db = await get_db()
    try:
        await ensure_schema(db)
        row = await (await db.execute(
            "SELECT source FROM tts_audio_output WHERE account_id=? AND channel=?", (account_id, channel)
        )).fetchone()
    finally:
        await db.close()
    return {"ok": True, "account_id": account_id, "channel": channel, "source": row["source"] if row else "", "configured": bool(row), "telemetry": "unverified"}


@router.get("/public")
async def public_output(account_id: int, channel: str) -> dict:
    return await get_output(account_id, channel)


@router.get("/{account_id}/{channel}", dependencies=[Depends(_owner_auth_dependency)])
async def owner_get_output(account_id: int, channel: str) -> dict:
    return await get_output(account_id, channel)


@router.put("/{account_id}/{channel}", dependencies=[Depends(_owner_auth_dependency)])
async def owner_set_output(account_id: int, channel: str, data: dict) -> dict:
    channel = normalize_channel(channel)
    source = str(data.get("source") or "")
    if source not in SOURCES:
        raise HTTPException(400, "invalid_audio_output")
    db = await get_db()
    try:
        exists = await (await db.execute(
            "SELECT 1 FROM channels WHERE account_id=? AND lower(ltrim(channel_name,'#'))=? AND enabled=1", (account_id, channel)
        )).fetchone()
        if not exists:
            raise HTTPException(404, "scope_not_found")
        await ensure_schema(db)
        await db.execute(
            "INSERT INTO tts_audio_output(account_id,channel,source) VALUES(?,?,?) ON CONFLICT(account_id,channel) DO UPDATE SET source=excluded.source,updated_at=CURRENT_TIMESTAMP",
            (account_id, channel, source),
        )
        await db.commit()
    finally:
        await db.close()
    return await get_output(account_id, channel)


@router.post("/{account_id}/{channel}/test", dependencies=[Depends(_owner_auth_dependency)])
async def owner_test_output(account_id: int, channel: str, data: dict) -> dict:
    state = await get_output(account_id, channel)
    if not state["configured"]:
        raise HTTPException(409, "audio_output_not_configured")
    text = str(data.get("text") or "TTS output test").strip()[:120]
    from app.audio_queue import get_audio_queue
    await get_audio_queue().enqueue(
        "tts_output_test", account_id, state["channel"], text,
        speaker="test", speaker_kind="owner", display_text=text,
    )
    return {"ok": True, "source": state["source"], "status": "accepted", "telemetry": "unverified"}
