"""Owner-only Soundboard library lifecycle endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.security import auth_dependency
from app import soundboard_library

router = APIRouter(
    prefix="/api/widgets/soundboard",
    tags=["soundboard-library"],
    dependencies=[Depends(auth_dependency)],
)


def _bad_request(exc: ValueError) -> HTTPException:
    status = 404 if str(exc) == "track_not_found" else 400
    return HTTPException(status, str(exc))


@router.patch("/tracks/{track_id}")
async def update_track(track_id: int, payload: dict) -> dict:
    try:
        return await soundboard_library.update_track(track_id, payload)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.delete("/tracks/{track_id}")
async def delete_track(track_id: int) -> dict:
    try:
        return await soundboard_library.delete_track(track_id)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/stop")
async def stop_playback(account_id: int = 0, channel: str = "") -> dict:
    if account_id <= 0 or not str(channel or "").strip().lstrip("#"):
        raise HTTPException(400, "widget_scope_required")
    from app.widgets import _verified_widget_state_scope
    scope = await _verified_widget_state_scope(account_id, channel)
    return await soundboard_library.stop_playback(account_id=scope[0], channel=scope[1])


@router.post("/trigger-hotkey")
async def trigger_hotkey(payload: dict) -> dict:
    combo = str(payload.get("combo") or "").strip().lower()
    account_id = int(payload.get("account_id") or 0)
    channel = str(payload.get("channel") or "").strip().lower().lstrip("#")
    if not combo:
        raise HTTPException(400, "hotkey_combo_required")
    if account_id <= 0 or not channel:
        from app.widgets import _verified_widget_state_scope
        scope = await _verified_widget_state_scope(account_id, channel)
        account_id, channel = scope[0], scope[1]
    track = await soundboard_library.get_track_by_hotkey(combo)
    if not track:
        raise HTTPException(404, "track_not_found_for_hotkey")
    try:
        res = await soundboard_library.play_track(
            track["id"], account_id=account_id, channel=channel, source="hotkey"
        )
        res["name"] = track["name"]
        res["hotkey"] = track["hotkey"]
        return res
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/ended")
async def finish_playback_route(account_id: int = 0, channel: str = "") -> dict:
    if account_id <= 0 or not str(channel or "").strip().lstrip("#"):
        raise HTTPException(400, "widget_scope_required")
    from app.widgets import _verified_widget_state_scope
    scope = await _verified_widget_state_scope(account_id, channel)
    return await soundboard_library.finish_playback(account_id=scope[0], channel=scope[1])
