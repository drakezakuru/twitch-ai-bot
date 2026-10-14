"""Owner-facing Song Request journal endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.security import auth_dependency

router = APIRouter(dependencies=[Depends(auth_dependency)], tags=["song-request"])


@router.get("/api/widgets/song-request/audit")
async def song_request_audit(
    account_id: int | None = None, channel: str | None = None, limit: int = 100,
) -> dict:
    from app.song_request_service import list_audit
    from app.widgets import _verified_widget_state_scope

    scope = await _verified_widget_state_scope(account_id, channel)
    return {"ok": True, "items": await list_audit(scope, limit)}


@router.get("/api/widgets/song-request/entitlements")
async def song_request_entitlements_get(account_id: int, channel: str) -> dict:
    from app.song_request_service import get_entitlement_settings
    from app.widgets import _verified_widget_state_scope

    scope = await _verified_widget_state_scope(account_id, channel)
    if scope is None:
        raise HTTPException(status_code=400, detail="exact_scope_required")
    return {"ok": True, "settings": await get_entitlement_settings(scope)}


@router.put("/api/widgets/song-request/entitlements")
async def song_request_entitlements_put(payload: dict, account_id: int, channel: str) -> dict:
    from app.song_request_service import save_entitlement_settings
    from app.widgets import _verified_widget_state_scope

    scope = await _verified_widget_state_scope(account_id, channel)
    if scope is None:
        raise HTTPException(status_code=400, detail="exact_scope_required")
    try:
        settings = await save_entitlement_settings(scope, payload)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "settings": settings}
