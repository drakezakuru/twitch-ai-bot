"""Q15d (E5): smart-routing чат-моделей per-бот.

Проверяем:
1. ``_apply_smart_routing`` с per-бот конфигом (cfg) — включение без
   глобального флага, порог и провайдеры из cfg, custom:<имя> разрешён.
2. ``generate_text`` использует per-бот routing, когда глобальный выключен.
3. Бот без своего конфига наследует глобальное поведение (legacy).
4. API: PUT ``ai-override`` валидирует и сохраняет routing; выключенный
   routing не сохраняется (наследование); GET возвращает конфиг.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


async def _client():
    from fastapi import FastAPI
    from app.routes import router
    app = FastAPI()
    app.include_router(router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _service(monkeypatch):
    import os
    from app.ai_service import AIService
    for name in [k for k in os.environ if k.startswith(("OPENROUTER", "GEMINI", "OPENAI", "ANTHROPIC", "OLLAMA", "LOCAL_FALLBACK", "OFFLINE"))]:
        monkeypatch.delenv(name, raising=False)
    return AIService()


def test_apply_smart_routing_per_bot_cfg(monkeypatch):
    svc = _service(monkeypatch)
    assert svc.smart_routing_enabled is False, "глобальный routing по умолчанию выключен"
    cfg = {
        "enabled": True, "threshold": 50,
        "simple_provider": "ollama", "simple_model": "llama3:8b",
        "complex_provider": "anthropic", "complex_model": "claude-3-5-sonnet-latest",
    }
    p, m, k = svc._apply_smart_routing("openrouter", "gpt-x", "key", "simple", cfg=cfg)
    assert (p, m, k) == ("ollama", "llama3:8b", "")
    p, m, k = svc._apply_smart_routing("ollama", "llama3", "", "complex", cfg=cfg)
    assert (p, m, k) == ("anthropic", "claude-3-5-sonnet-latest", "")
    # выключенный cfg = passthrough, даже если глобальный включён
    svc.smart_routing_enabled = True
    p, m, k = svc._apply_smart_routing("openrouter", "gpt-x", "key", "simple", cfg={})
    assert (p, m, k) == ("openrouter", "gpt-x", "key")


def test_apply_smart_routing_per_bot_custom_named_provider(monkeypatch):
    svc = _service(monkeypatch)
    svc.set_custom_providers([
        {"name": "myproxy", "base_url": "https://api.example.com/v1",
         "api_key": "sk-abc", "models": ["model-a"], "enabled": 1},
    ])
    cfg = {"enabled": True, "simple_provider": "custom:myproxy", "simple_model": "model-a"}
    p, m, k = svc._apply_smart_routing("openrouter", "gpt-x", "", "simple", cfg=cfg)
    assert p == "custom:myproxy"
    assert m == "model-a"
    assert k == "sk-abc"


async def test_generate_text_uses_per_bot_routing(monkeypatch):
    from app.ai_service import AIService, AccountAIOverride
    svc = _service(monkeypatch)
    svc.provider = "openrouter"
    svc.set_account_override(1, AccountAIOverride(smart_routing={
        "enabled": True, "threshold": 50,
        "simple_provider": "ollama", "simple_model": "llama3:8b",
        "complex_provider": "", "complex_model": "",
    }))
    captured = {}

    async def fake_ollama_chat(prompt, system="", temperature=None, model=""):
        captured["model"] = model
        return "ok"

    monkeypatch.setattr(svc, "_ollama_chat", fake_ollama_chat)
    result = await svc.generate_text("привет", account_id=1)
    assert result == "ok"
    assert captured["model"] == "llama3:8b", "короткий промпт уходит на per-бот простую модель"


async def test_generate_text_without_cfg_inherits_global_off(monkeypatch):
    from app.ai_service import AIService
    svc = _service(monkeypatch)
    svc.provider = "openrouter"
    captured = {}

    async def fake_openrouter_chat(prompt, system="", temperature=None, model="", api_key=""):
        captured["model"] = model
        return "ok"

    monkeypatch.setattr(svc, "_openrouter_chat", fake_openrouter_chat)
    await svc.generate_text("привет", account_id=2)
    assert captured["model"] == svc.openrouter_chat, "без cfg бот не переключается"


async def test_ai_override_smart_routing_roundtrip(tmp_db, disable_auth):
    from app import database
    await database.init_db()
    db = await database.get_db()
    await db.execute("INSERT INTO accounts (nickname, token) VALUES ('bot1', 'tok')")
    await db.commit()
    await db.close()

    async with await _client() as c:
        put = (await c.put("/api/accounts/1/ai-override", json={
            "ai_smart_routing": {
                "enabled": True, "threshold": 40,
                "simple_provider": "OLLAMA", "simple_model": "llama3",
                "complex_provider": "totally-fake", "complex_model": "x",
            },
        })).json()
        assert put["ok"] is True
        assert put["ai_smart_routing"]["enabled"] is True
        assert put["ai_smart_routing"]["threshold"] == 50, "порог clamp до минимума 50"
        assert put["ai_smart_routing"]["simple_provider"] == "ollama"
        assert put["ai_smart_routing"]["complex_provider"] == "", "невалидный провайдер отброшен"

        got = (await c.get("/api/accounts/1/ai-override")).json()
        assert got["ai_smart_routing"]["simple_model"] == "llama3"

        off = (await c.put("/api/accounts/1/ai-override", json={
            "ai_smart_routing": {"enabled": False},
        })).json()
        assert off["ai_smart_routing"] is None, "выключенный routing = наследовать глобальный"
