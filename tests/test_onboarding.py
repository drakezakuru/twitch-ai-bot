from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_onboarding_state_is_persisted(tmp_db, disable_auth):
    from app import database
    from app.routes import router

    await database.init_db()
    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        initial = await client.get("/api/onboarding")
        assert initial.json() == {"completed": False, "dismissed": False}
        updated = await client.put("/api/onboarding", json={"completed": True})
        assert updated.json()["completed"] is True
        assert (await client.get("/api/onboarding")).json()["completed"] is True
