"""§S5: тесты stream_tools_routes — Twitch Helix stream tools endpoints."""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from app import stream_tools_routes


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def app(disable_auth, tmp_db):
    application = FastAPI()
    application.include_router(stream_tools_routes.router)
    return application


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_connection_not_configured(client, monkeypatch):
    """When Twitch is not configured, endpoint returns error + help_url."""
    monkeypatch.setattr(stream_tools_routes, "is_helix_configured", lambda: False)
    resp = await client.get(
        "/api/stream-tools/check-connection",
        params={"account_id": "1"},
    )
    data = resp.json()
    assert data.get("ok") is False
    assert "help_url" in data or "detail" in str(data)


@pytest.mark.asyncio
async def test_check_connection_configured(client, monkeypatch):
    """When Twitch is configured, endpoint tries Helix."""
    monkeypatch.setattr(stream_tools_routes, "is_helix_configured", lambda: True)

    async def fake_helix(method, path, account_id, **kw):
        return {"status": 200, "data": {"data": [{"id": "123", "login": "testuser", "display_name": "TestUser"}]}}

    monkeypatch.setattr(stream_tools_routes, "_helix_request", fake_helix)
    resp = await client.get(
        "/api/stream-tools/check-connection",
        params={"account_id": "1"},
    )
    data = resp.json()
    assert data.get("ok") is True
    assert data.get("login") == "testuser"


@pytest.mark.asyncio
async def test_channel_info(client, monkeypatch):
    """Channel info returns category/title from Helix."""
    monkeypatch.setattr(stream_tools_routes, "is_helix_configured", lambda: True)

    async def fake_resolve(aid):
        return {"ok": True, "user": {"id": "123", "login": "testuser"}}

    async def fake_helix(method, path, account_id, **kw):
        return {"status": 200, "data": {"data": [{"game_name": "Just Chatting", "title": "Test Stream"}]}}

    monkeypatch.setattr(stream_tools_routes, "_resolve_broadcaster", fake_resolve)
    monkeypatch.setattr(stream_tools_routes, "_helix_request", fake_helix)
    resp = await client.get(
        "/api/stream-tools/channel-info",
        params={"account_id": "1"},
    )
    data = resp.json()
    assert data.get("ok") is True or "game_name" in data


@pytest.mark.asyncio
async def test_check_connection_helix_error(client, monkeypatch):
    """When Helix returns 401, endpoint returns error."""
    monkeypatch.setattr(stream_tools_routes, "is_helix_configured", lambda: True)

    async def fake_helix(method, path, account_id, **kw):
        return {"status": 401, "data": {}}

    monkeypatch.setattr(stream_tools_routes, "_helix_request", fake_helix)
    resp = await client.get(
        "/api/stream-tools/check-connection",
        params={"account_id": "1"},
    )
    data = resp.json()
    assert data.get("ok") is False or data.get("error") is not None
