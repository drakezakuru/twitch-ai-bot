"""Focused coverage for panel provider configuration and secret handling."""
from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient


def _app():
    from fastapi import FastAPI
    from app.routes import router
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture()
def server_stub(monkeypatch):
    from app.ai_service import AIService
    service = AIService()
    fake = ModuleType("app.server")
    fake.ai_service = service
    fake.bot_manager = SimpleNamespace(get_all_statuses=lambda: {})
    monkeypatch.setitem(sys.modules, "app.server", fake)
    return service


@pytest.mark.asyncio
async def test_ai_config_is_persisted_redacted_and_partial_secret_safe(tmp_db, disable_auth, server_stub):
    from app import database
    await database.init_db()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        response = await client.put("/api/ai/config", json={
            "provider": "ollama",
            "ollama_host": "http://ollama:11434",
            "openai_key": "super-secret-openai-key",
        })
        assert response.status_code == 200
        body = response.json()
        assert "openai_key" not in body
        assert body["has_openai_key"] is True
        assert body["openai_key_masked"] == "supe...-key"

        # A panel save that omits the secret must not clear it.
        await client.put("/api/ai/config", json={"provider": "openai"})
        stored = await database.get_setting("ai_openai_key")
        assert stored == "super-secret-openai-key"
        response = await client.get("/api/ai/config")
        assert "super-secret-openai-key" not in response.text


@pytest.mark.asyncio
async def test_unified_provider_status_and_test_are_secret_safe(tmp_db, disable_auth, server_stub, monkeypatch):
    from app import database
    await database.init_db()
    monkeypatch.setenv("TWITCH_CLIENT_ID", "client-id")
    monkeypatch.setenv("TWITCH_CLIENT_SECRET", "secret-value")
    server_stub.ollama_status = AsyncMock(return_value={"state": "paused", "version": ""})
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        status = await client.get("/api/providers/status")
        assert status.status_code == 200
        data = status.json()
        assert data["ai"]["ollama"]["configured"] is True
        assert data["ai"]["ollama"]["state"] == "paused"
        assert data["twitch"]["helix_configured"] is True
        assert "secret-value" not in status.text

        tested = await client.post("/api/providers/test", json={"provider": "web_speech"})
        assert tested.json() == {"provider": "web_speech", "ok": True, "message": "Browser SpeechSynthesis is available"}


@pytest.mark.asyncio
async def test_panel_status_survives_unavailable_ollama_without_inference(tmp_db, disable_auth, server_stub):
    import httpx
    from app import database

    await database.init_db()
    server_stub.provider = "ollama"
    server_stub._client.get = AsyncMock(side_effect=httpx.ConnectError("offline"))
    server_stub._client.post = AsyncMock(side_effect=AssertionError("status must not run inference"))

    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        response = await client.get("/api/runtime/status")

    assert response.status_code == 200
    assert response.json()["ai_state"] == "paused"
    assert response.json()["ollama_state"] == "paused"
    server_stub._client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_test_does_not_switch_active_ai_provider(server_stub):
    server_stub.provider = "ollama"
    server_stub.test_connection = AsyncMock(
        return_value={"ok": True, "model": "gpt-test"}
    )
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        response = await client.post("/api/providers/test", json={"provider": "openai"})
    assert response.json()["provider"] == "openai"
    assert server_stub.provider == "ollama"


@pytest.mark.asyncio
async def test_offline_mode_is_persisted(tmp_db, disable_auth, server_stub):
    from app import database
    await database.init_db()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        response = await client.put("/api/offline/config", json={"enabled": True})
        assert response.json()["enabled"] is True
        assert server_stub.offline_mode is True
        assert (await client.get("/api/offline/config")).json()["provider"] == "ollama"
        assert await database.get_setting("offline_mode") == "1"
