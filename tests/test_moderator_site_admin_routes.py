"""MOD-18 gate: owner admin surface — kill switch endpoints and grant revocation."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _seed():
    from app.database import get_db, init_db
    from app import moderator_site_controls as controls
    from app import moderator_site_permissions as perms
    from app import moderator_site_schema as ms
    await init_db()
    db = await get_db()
    await controls.ensure_schema(db)
    await perms.ensure_schema(db)
    await ms.ensure_schema(db)
    await perms.save_grant(db, 1, "chan", "userA", "modA", ["play_media"])
    await db.commit()
    await db.close()


def _client():
    from fastapi import FastAPI
    from app.moderator_site_admin_routes import admin_router
    app = FastAPI()
    app.include_router(admin_router)
    from httpx import ASGITransport, AsyncClient
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def no_owner_auth(monkeypatch):
    # Endpoint auth is _owner_auth_dependency; the dependency-level gate is the
    # panel's own contract — here we verify the moderator-site logic behind it.
    import app.moderator_console_routes as console
    async def allow():
        return {"role": "owner"}
    monkeypatch.setattr(console, "_owner_auth_dependency", lambda: allow)


async def test_kill_status_and_activate_deactivate():
    await _seed()
    async with _client() as client:
        status = (await client.get("/api/moderator-site/admin/kill")).json()
        assert status == {"active": False}
        activated = (await client.post("/api/moderator-site/admin/kill", json={"active": True, "reason": "ops"})).json()
        assert activated["ok"] is True and activated["active"] is True
        # admission blocked while active
        from app.database import get_db
        from app import moderator_site_controls as controls
        db = await get_db()
        try:
            import pytest as _pytest
            with _pytest.raises(ValueError, match="kill_switch_active"):
                await controls.check_admission(db)
        finally:
            await db.close()
        deactivated = (await client.post("/api/moderator-site/admin/kill", json={"active": False})).json()
        assert deactivated["ok"] is True


async def test_grants_list_and_revoke():
    await _seed()
    async with _client() as client:
        grants = (await client.get("/api/moderator-site/admin/grants", params={"account_id": 1, "channel": "chan"})).json()
        assert len(grants["items"]) == 1
        grant_id = grants["items"][0]["id"]
        revoked = (await client.post(f"/api/moderator-site/admin/grants/{grant_id}/revoke")).json()
        assert revoked["enabled"] == 0 and revoked["grant_version"] == 2
        # second revoke: grant still exists (disabled) -> version bumps again
        again = (await client.post(f"/api/moderator-site/admin/grants/{grant_id}/revoke")).json()
        assert again["grant_version"] == 3


async def test_unknown_grant_is_404():
    await _seed()
    async with _client() as client:
        response = await client.post("/api/moderator-site/admin/grants/missing/revoke")
        assert response.status_code == 404 and response.json()["detail"]["code"] == "grant_missing"
