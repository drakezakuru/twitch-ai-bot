"""v10.3 4C — tests for side-by-side model comparison."""
from __future__ import annotations

import sys
from types import ModuleType

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


def _build_app():
    from fastapi import FastAPI
    from app.routes import router
    app = FastAPI()
    app.include_router(router)
    return app


class _StubAi:
    """ai_service stub with controllable responses per (provider, model)."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.results: dict[tuple[str, str], dict] = {}

    def set(self, provider: str, model: str, *, ok: bool, response: str = "", error: str = ""):
        self.results[(provider, model)] = {"ok": ok, "response": response, "error": error}

    async def generate_text_with(self, provider, model, prompt, system="", temperature=None):
        self.calls.append((provider, model))
        return self.results.get((provider, model), {"ok": False, "response": "", "error": "no stub"})


@pytest.fixture()
def stub_ai():
    """Подменяет app.server модулем-заглушкой, чтобы routes.py мог импортировать ai_service."""
    stub = _StubAi()
    saved = sys.modules.get("app.server")
    fake = ModuleType("app.server")
    fake.ai_service = stub
    sys.modules["app.server"] = fake
    try:
        yield stub
    finally:
        if saved is not None:
            sys.modules["app.server"] = saved
        else:
            sys.modules.pop("app.server", None)


async def test_compare_requires_prompt(tmp_db, disable_auth, stub_ai):
    from app import database
    await database.init_db()
    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        r = await client.post("/api/ai/compare", json={"models": [{"provider": "openrouter", "model": "x/y"}]})
        assert r.status_code == 200
        d = r.json()
        assert d["ok"] is False
        assert "prompt" in (d.get("error") or "")


async def test_compare_requires_models(tmp_db, disable_auth, stub_ai):
    from app import database
    await database.init_db()
    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        r = await client.post("/api/ai/compare", json={"prompt": "hi"})
        d = r.json()
        assert d["ok"] is False


async def test_compare_runs_in_parallel_and_returns_results(tmp_db, disable_auth, stub_ai):
    from app import database
    await database.init_db()

    stub_ai.set("openrouter", "a/m1", ok=True, response="ответ A")
    stub_ai.set("ollama", "llama3", ok=True, response="ответ B")
    stub_ai.set("openrouter", "broken", ok=False, error="boom")

    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        r = await client.post("/api/ai/compare", json={
            "prompt": "Привет",
            "system": "Ты бот",
            "temperature": 0.5,
            "models": [
                {"provider": "openrouter", "model": "a/m1"},
                {"provider": "ollama", "model": "llama3"},
                {"provider": "openrouter", "model": "broken"},
            ],
        })
        assert r.status_code == 200
        d = r.json()
        assert d["ok"] is True
        assert len(d["results"]) == 3
        # Все 3 модели вызваны
        called = sorted(stub_ai.calls)
        assert called == sorted([("openrouter", "a/m1"), ("ollama", "llama3"), ("openrouter", "broken")])
        # Маппинг по provider+model
        by_key = {(r["provider"], r["model"]): r for r in d["results"]}
        assert by_key[("openrouter", "a/m1")]["ok"] is True
        assert by_key[("openrouter", "a/m1")]["response"] == "ответ A"
        assert by_key[("ollama", "llama3")]["response"] == "ответ B"
        assert by_key[("openrouter", "broken")]["ok"] is False
        assert by_key[("openrouter", "broken")]["error"] == "boom"
        # ms — int >= 0, length — int
        for it in d["results"]:
            assert isinstance(it.get("ms"), int)
            assert it["ms"] >= 0
            assert isinstance(it.get("length", 0), int)


async def test_compare_unknown_provider_falls_back_to_openrouter(tmp_db, disable_auth, stub_ai):
    from app import database
    await database.init_db()
    stub_ai.set("openrouter", "x/y", ok=True, response="ok")

    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        r = await client.post("/api/ai/compare", json={
            "prompt": "p",
            "models": [{"provider": "magic-cloud", "model": "x/y"}],
        })
        d = r.json()
        assert d["ok"] is True
        assert d["results"][0]["provider"] == "openrouter"


async def test_compare_logs_action(tmp_db, disable_auth, stub_ai):
    from app import database
    await database.init_db()
    stub_ai.set("openrouter", "a/m1", ok=True, response="hi")

    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        await client.post("/api/ai/compare", json={
            "prompt": "test",
            "models": [{"provider": "openrouter", "model": "a/m1"}],
        })
        r = await client.get("/api/action-log?action=compare_run")
        d = r.json()
        assert d["total"] >= 1
        assert d["items"][0]["action"] == "compare_run"


async def test_generate_text_with_validation():
    """Прямой вызов public-метода без сети: пустая модель / неизвестный провайдер."""
    from app.ai_service import AIService
    svc = AIService()
    try:
        r = await svc.generate_text_with("openrouter", "", "p")
        assert r["ok"] is False and "model" in r["error"]
        r = await svc.generate_text_with("magic", "x/y", "p")
        assert r["ok"] is False and "provider" in r["error"]
    finally:
        await svc.close()
