import pytest
import httpx
from app.server import app, ai_service

pytestmark = pytest.mark.asyncio


async def test_ai_test_connection_unsupported():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/api/ai/test", json={"provider": "unknown_dummy_provider"})
        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is False
        assert "Unsupported provider" in data["error"]


async def test_ai_test_connection_ollama_not_running():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/api/ai/test", json={"provider": "ollama"})
        assert res.status_code == 200
        data = res.json()
        # Если Ollama не запущен локально — получаем внятную ошибку с подсказкой "ollama serve"
        if not data["ok"]:
            assert "ollama" in data["error"].lower()
        else:
            assert "latency_ms" in data


async def test_ai_test_connection_mock_success(monkeypatch):
    async def mock_openai_chat(*args, **kwargs):
        return "OK from mock"

    monkeypatch.setattr(ai_service, "_openai_chat", mock_openai_chat)
    monkeypatch.setattr(ai_service, "custom_api_key", "test_key")
    monkeypatch.setattr(ai_service, "custom_base_url", "http://mock-ai")

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/api/ai/test", json={"provider": "custom"})
        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is True
        assert data["response"] == "OK from mock"
        assert "latency_ms" in data
        assert data["latency_ms"] >= 0
