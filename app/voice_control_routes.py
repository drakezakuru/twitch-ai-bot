"""Authenticated API for scoped owner-voice enrollment and settings."""
from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, HTTPException

from app.security import auth_dependency
from app import voice_control


router = APIRouter(
    prefix="/api/voice-control", tags=["voice-control"],
    dependencies=[Depends(auth_dependency)],
)


def _http_error(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("")
async def get_settings(account_id: int, channel: str) -> dict:
    try:
        return await voice_control.get_config(account_id, channel)
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.put("")
async def put_settings(payload: dict, account_id: int, channel: str) -> dict:
    try:
        return await voice_control.save_config(account_id, channel, payload)
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.post("/enroll")
async def enroll(payload: dict) -> dict:
    try:
        raw = base64.b64decode(str(payload.get("audio_b64") or ""), validate=True)
        return await voice_control.enroll(
            int(payload.get("account_id") or 0), str(payload.get("channel") or ""), raw,
            str(payload.get("mime_type") or "audio/wav"),
        )
    except (ValueError, TypeError, base64.binascii.Error) as exc:
        raise HTTPException(status_code=400, detail=str(exc) or "invalid_audio") from exc


@router.delete("/enrollment")
async def delete_enrollment(account_id: int, channel: str) -> dict:
    try:
        return await voice_control.delete_enrollment(account_id, channel)
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.get("/capabilities")
async def capabilities(account_id: int, channel: str) -> dict:
    try:
        scope = await voice_control.verify_scope(account_id, channel)
    except ValueError as exc:
        raise _http_error(exc) from exc
    return {
        "account_id": scope[0], "channel": scope[1],
        "actions": voice_control.VOICE_ACTIONS,
        "prompt_block": voice_control.capability_block(*scope),
    }
