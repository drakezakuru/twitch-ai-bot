"""MOD-18 admin routes (owner panel surface): kill switch and grant revocation.

Owner-only endpoints behind the same owner auth as the moderator console admin.
The kill switch state is shared with `moderator_site_controls`; revocation
reuses the MOD-07 grant semantics (version bump, sessions killed).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.moderator_console_routes import _owner_auth_dependency
from app.database import get_db

admin_router = APIRouter(prefix="/api/moderator-site/admin", tags=["moderator-site-admin"],
                         dependencies=[Depends(_owner_auth_dependency)])


async def _prepare() -> Any:
    from app import moderator_site_controls as controls
    from app import moderator_site_permissions as perms
    from app import moderator_site_schema as ms
    db = await get_db()
    await controls.ensure_schema(db)
    await perms.ensure_schema(db)
    await ms.ensure_schema(db)
    return db, controls, perms


@admin_router.get("/kill")
async def kill_status() -> dict[str, Any]:
    db, controls, _perms = await _prepare()
    try:
        return {"active": await controls.kill_active(db)}
    finally:
        await db.close()


@admin_router.post("/kill")
async def kill_set(data: dict[str, Any]) -> dict[str, Any]:
    db, controls, _perms = await _prepare()
    try:
        if data.get("active"):
            result = await controls.activate_kill(db, by="owner", reason=str(data.get("reason") or "manual"))
        else:
            await controls.deactivate_kill(db)
            result = {"active": False}
        return {"ok": True, **result}
    finally:
        await db.close()


@admin_router.get("/grants")
async def grants(account_id: int, channel: str) -> dict[str, Any]:
    db, _controls, perms = await _prepare()
    try:
        return {"items": await perms.list_grants(db, account_id, channel)}
    finally:
        await db.close()


@admin_router.post("/grants/{grant_id}/revoke")
async def revoke(grant_id: str) -> dict[str, Any]:
    db, _controls, perms = await _prepare()
    try:
        return await perms.revoke_grant(db, grant_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": str(exc)}) from exc
    finally:
        await db.close()
