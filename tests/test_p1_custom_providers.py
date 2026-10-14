"""P1 §25.4: именованные кастомные AI-провайдеры + §25.5 тест vision-эндпоинта.

Проверяем:
1. CRUD /api/custom-providers: создание, маскировка ключа в списке,
   PUT с пустым ключом не затирает старый, удаление.
2. ai_service: кэш set_custom_providers, _provider_defaults('custom:<name>') →
   первая модель + ключ, резолвинг per-account override.
3. generate_text dispatch: named custom → _openai_chat получает base_url/ключ/модель
   провайдера (monkeypatch на _openai_chat).
4. providers/status включает custom:<name> с configured по base_url.
5. update_config принимает provider='custom:<name>'.
"""
from __future__ import annotations

import json

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


async def _client():
    from fastapi import FastAPI
    from app.routes import router
    app = FastAPI()
    app.include_router(router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _create(c, name="myproxy", models=None, vision_models=None, key="sk-test-12345678"):
    return (await c.post("/api/custom-providers", json={
        "name": name,
        "base_url": "https://api.example.com/v1",
        "api_key": key,
        "models": models or ["model-a", "model-b"],
        "vision_models": vision_models or ["vision-a", "vision-b"],
    })).json()


async def test_crud_and_key_masking(tmp_db, disable_auth):
    from app import database
    await database.init_db()
    async with await _client() as c:
        created = await _create(c)
        assert created["ok"] is True

        items = (await c.get("/api/custom-providers")).json()["items"]
        assert len(items) == 1
        assert items[0]["name"] == "myproxy"
        assert items[0]["base_url"] == "https://api.example.com/v1"
        assert items[0]["models"] == ["model-a", "model-b"]
        assert items[0]["vision_models"] == ["vision-a", "vision-b"]
        assert "api_key" not in items[0]
        assert items[0]["has_api_key"] is True

        # Дубликат имени
        dup = await _create(c)
        assert dup["ok"] is False and "уже существует" in dup["error"]

        # PUT с пустым ключом — ключ сохраняется
        r = (await c.put(f"/api/custom-providers/{created['id']}", json={
            "name": "renamed", "base_url": "https://new.example.com/v1", "api_key": "",
            "models": ["model-x"], "vision_models": ["vision-x"],
        })).json()
        assert r["ok"] is True
        updated = (await c.get("/api/custom-providers")).json()["items"][0]
        assert updated["models"] == ["model-x"]
        assert updated["vision_models"] == ["vision-x"]
        # Проверяем ключ напрямую в БД
        from app import database
        db = await database.get_db()
        cur = await db.execute("SELECT api_key, vision_models FROM custom_providers WHERE id = ?", (created["id"],))
        row = await cur.fetchone()
        await db.close()
        assert row["api_key"] == "sk-test-12345678"
        assert row["api_key"]  # не затёрт пустой строкой
        assert json.loads(row["vision_models"]) == ["vision-x"]

        # Удаление
        assert (await c.delete(f"/api/custom-providers/{created['id']}")).json()["ok"] is True
        assert (await c.get("/api/custom-providers")).json()["items"] == []


async def test_ai_service_resolve_named_provider():
    from app.ai_service import AIService, AccountAIOverride as _Ov
    ai = AIService()
    ai.set_custom_providers([
        {"name": "myproxy", "base_url": "https://api.example.com/v1",
         "api_key": "sk-abc", "models": '["model-a", "model-b"]',
         "vision_models": '["vision-a", "vision-b"]', "enabled": 1},
    ])
    chat, vision, key = ai._provider_defaults("custom:myproxy")
    assert chat == "model-a"
    assert vision == "vision-a"
    assert key == "sk-abc"

    ai.set_custom_providers([
        {"name": "text-only", "models": ["chat-only"], "vision_models": [], "enabled": 1},
    ])
    assert ai._provider_defaults("custom:text-only")[:2] == ("chat-only", "")

    # Неизвестное имя → пустые дефолты
    chat2, _v, key2 = ai._provider_defaults("custom:ghost")
    assert chat2 == "" and key2 == ""

    # per-account override: provider custom:name + своя модель → модель из override
    ai.set_account_override(7, _Ov(provider="custom:myproxy", chat_model="model-b"))
    provider, chat_model, _vision, _key = ai._resolve(7)
    assert provider == "custom:myproxy"
    assert chat_model == "model-b"


async def test_generate_text_dispatch_named_custom(tmp_db, disable_auth, monkeypatch):
    from app.ai_service import AIService
    ai = AIService()
    ai.set_custom_providers([
        {"name": "myproxy", "base_url": "https://api.example.com/v1",
         "api_key": "sk-abc", "models": ["model-a"], "enabled": 1},
    ])
    captured = {}

    async def fake_openai_chat(prompt, system="", temperature=None, model="", api_key="", base_url=""):
        captured.update({"model": model, "api_key": api_key, "base_url": base_url})
        return "ответ"

    monkeypatch.setattr(ai, "_openai_chat", fake_openai_chat)
    # Подменяем _resolve, чтобы провайдер был custom:myproxy (без БД-оверрайда)
    monkeypatch.setattr(ai, "_resolve", lambda account_id: ("custom:myproxy", "model-a", "model-a", ""))

    result = await ai.generate_text("привет", account_id=1)
    assert result == "ответ"
    assert captured["model"] == "model-a"
    assert captured["api_key"] == "sk-abc"
    assert captured["base_url"] == "https://api.example.com/v1"


async def test_named_custom_vision_dispatch(monkeypatch):
    from app.ai_service import AIService
    from PIL import Image

    ai = AIService()
    ai.local_fallback_enabled = False
    ai.set_custom_providers([{
        "name": "VisionProxy", "base_url": "https://vision.example.com/v1",
        "api_key": "sk-vision", "models": ["chat-a"],
        "vision_models": ["vision-a"], "enabled": 1,
    }])
    ai.provider = "custom:visionproxy"
    captured = {}

    async def fake_vision(img_b64, prompt, model=None, api_key=None, base_url=None):
        captured.update({"model": model, "api_key": api_key, "base_url": base_url})
        return "seen"

    monkeypatch.setattr(ai, "_openai_vision", fake_vision)
    result = await ai.analyze_image(Image.new("RGB", (2, 2)), "look")
    assert result == "seen"
    assert captured == {
        "model": "vision-a", "api_key": "sk-vision",
        "base_url": "https://vision.example.com/v1",
    }


async def test_generate_text_with_named_custom(tmp_db, disable_auth, monkeypatch):
    from app.ai_service import AIService
    ai = AIService()
    ai.set_custom_providers([
        {"name": "myproxy", "base_url": "https://api.example.com/v1",
         "api_key": "sk-abc", "models": ["model-a"], "enabled": 1},
    ])

    async def fake_openai_chat(prompt, system="", temperature=None, model="", api_key="", base_url=""):
        return "OK"

    monkeypatch.setattr(ai, "_openai_chat", fake_openai_chat)
    res = await ai.generate_text_with("custom:myproxy", "model-a", "Say OK")
    assert res["ok"] is True and res["response"] == "OK"

    res_missing = await ai.generate_text_with("custom:ghost", "", "Say OK")
    assert res_missing["ok"] is False and "not found" in res_missing["error"]


async def test_providers_status_includes_named(tmp_db, disable_auth):
    from app import database
    await database.init_db()
    # Роут импортирует ai_service из app.server — кладём провайдера прямо в БД
    # и в кэш через тот же путь, что использует CRUD-роут (_refresh).
    db = await database.get_db()
    await db.execute(
        "INSERT INTO custom_providers (name, base_url, api_key, models, enabled) VALUES (?, ?, ?, ?, 1)",
        ("myproxy", "https://api.example.com/v1", "sk-abc", json.dumps(["model-a"])),
    )
    await db.commit()
    await db.close()

    from app.routes import _refresh_custom_providers_cache
    await _refresh_custom_providers_cache()
    async with await _client() as c:
        status = (await c.get("/api/providers/status")).json()
    named = status["ai"].get("custom:myproxy")
    assert named is not None
    assert named["configured"] is True
    assert named["model"] == "model-a"


async def test_update_config_accepts_named_provider():
    from app.ai_service import AIService
    ai = AIService()
    ai.update_config({"provider": "custom:myproxy"})
    assert ai.provider == "custom:myproxy"
    ai.update_config({"provider": "not-a-provider"})
    assert ai.provider == "custom:myproxy"  # неверное имя не применяется


def test_custom_provider_ui_vision_wiring_and_locales():
    from pathlib import Path
    from tests import _panel_js

    root = Path(__file__).resolve().parents[1]
    settings = (root / "templates" / "partials" / "settings.html").read_text(encoding="utf-8")
    js = _panel_js.panel_js()
    # Q15b (E2): один редактор списка моделей вместо двух textarea
    assert 'id="cpModelsEditor"' in settings
    assert 'onclick="cpAddModelRow()"' in settings
    assert 'data-i18n="cp.models_types_hint"' in settings
    assert 'id="cpVisionModels"' not in settings
    assert "function _cpListsFromRows(" in js
    assert "const vision_models = lists.vision_models" in js
    assert "const lists = _cpListsFromRows()" in js
    assert "$('cpVisionModels')" not in js and "$('cpModels')" not in js
    for lang in ("ru", "en", "ua"):
        assert f"Object.assign(LANGS.{lang}" in js
        for key in ("cp.add_model", "cp.models_types_hint", "cp.type_both"):
            assert js.count(f"'{key}'") >= 3


def test_custom_provider_option_refresh_preserves_selection_and_manual_vision_value():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    js = (root / "static" / "app" / "08_providers_moderation.js").read_text(encoding="utf-8")
    start = js.index("function refreshCustomProviderOptions()")
    end = js.index("function renderCustomProviders()", start)
    block = js[start:end]
    assert "const selectedValue = sel.value" in block
    assert "sel.value = selectedValue" in block
    assert "stale.value = selectedValue" in block
    # Q15b: рефрешер AI-полей бота переименован в refreshBotAIModels
    assert "refreshBotAIModels()" in block
    assert "botAIVisionModel').value" not in block


def test_one_off_custom_provider_option_is_gone():
    """Решение владельца 15.09: одноразовый «Custom API» убран из селектов —
    именованные провайдеры (custom:<имя>) единственный способ подключить свой
    OpenAI-совместимый endpoint. Рантайм legacy (ai_provider=custom в БД) читается как раньше."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    settings_html = (root / "templates" / "partials" / "settings.html").read_text(encoding="utf-8")
    bots_html = (root / "templates" / "partials" / "bots.html").read_text(encoding="utf-8")
    assert 'value="custom"' not in settings_html.split("globalAIProvider")[1].split("</select>")[0]
    assert 'value="custom"' not in bots_html.split("botAIProvider")[1].split("</select>")[0]
    js = (root / "static" / "app" / "04_chat_settings.js").read_text(encoding="utf-8")
    assert "custom_ai_base_url" not in js
    labels = (root / "static" / "app" / "15_feedback_2908.js").read_text(encoding="utf-8")
    assert "'provider.custom':" not in labels  # лейбл удалён, custom_hint остался
    assert labels.count("'provider.custom_hint':") == 3


async def test_named_provider_override_validation_and_vision_clear(tmp_db, disable_auth):
    from app import database

    await database.init_db()
    db = await database.get_db()
    await db.execute("INSERT INTO accounts (nickname, token) VALUES ('bot1', 'tok')")
    await db.execute(
        "INSERT INTO custom_providers (name, base_url, models, vision_models, enabled) "
        "VALUES ('VisionProxy', 'https://example.com/v1', '[\"chat\"]', '[\"vision\"]', 1)"
    )
    await db.commit()
    await db.close()

    async with await _client() as c:
        valid = (await c.put("/api/accounts/1/ai-override", json={
            "ai_provider_override": "custom:visionproxy",
            "ai_vision_model_override": "manual-vision",
        })).json()
        assert valid["ai_provider_override"] == "custom:VisionProxy"
        assert valid["ai_vision_model_override"] == "manual-vision"

        invalid = (await c.put("/api/accounts/1/ai-override", json={
            "ai_provider_override": "custom:missing",
        })).json()
        assert invalid["ai_provider_override"] == "custom:VisionProxy"

        cleared = (await c.put("/api/accounts/1/ai-override", json={
            "ai_vision_model_override": "",
        })).json()
        assert cleared["ai_vision_model_override"] == ""


async def test_vision_test_endpoint(tmp_db, disable_auth, monkeypatch):
    """§25.5: /api/ai/test-vision — ok при ответе модели, ошибка при пустом ответе.

    Патчим метод на КЛАССЕ: роут может держать другой экземпляр AIService
    (module reload в тестах), важно влиять на все инстансы.
    """
    from app import database
    await database.init_db()
    from app.ai_service import AIService

    async def fake_ok(self, image, prompt, account_id=0, channel=""):
        return "красное"

    async def fake_empty(self, image, prompt, account_id=0, channel=""):
        return ""

    monkeypatch.setattr(AIService, "analyze_image", fake_ok)
    async with await _client() as c:
        r = (await c.post("/api/ai/test-vision", json={})).json()
    assert r["ok"] is True and "красное" in r["response"]

    monkeypatch.setattr(AIService, "analyze_image", fake_empty)
    async with await _client() as c:
        r = (await c.post("/api/ai/test-vision", json={})).json()
    assert r["ok"] is False
    assert "пуст" in r["error"]



async def test_mood_replay_clip_routes(tmp_db, disable_auth):
    """§9g/§9h: маршруты, которые дергают новые карточки на Overview бота.

    Проверка `/api/streamer-mood/{id}` убрана: бэкенд настроения намеренно
    вырезан коммитом adec202, роут больше не существует (404), и ждать от
    него ok-обёртку нечего.
    """
    from app import database
    await database.init_db()
    db = await database.get_db()
    await db.execute("INSERT INTO accounts (nickname, token) VALUES ('bot1', 'tok')")
    await db.commit()
    await db.close()

    async with await _client() as c:
        # §9g: проверка всплеска — счётчики в ответе
        check = (await c.get("/api/bot/clip-detector/check/1/chan")).json()
        assert "spike" in check and "rate" in check and "avg_rate" in check

        # §9g: моменты — items-массив (пустой)
        moments = (await c.get("/api/bot/clip-detector/moments/1")).json()
        assert moments.get("items") == []

        # §9h: старт записи → сессия в списке → конец записи
        started = (await c.post("/api/replay/sessions/start", json={
            "account_id": 1, "channel": "chan", "name": "test_stream",
        })).json()
        assert started["ok"] is True and started["session_id"] > 0

        sessions = (await c.get("/api/replay/sessions?limit=5")).json()
        mine = [s for s in sessions["sessions"] if s["id"] == started["session_id"]]
        assert mine and mine[0]["channel"] == "chan" and not mine[0]["ended_at"]

        ended = (await c.post(f"/api/replay/sessions/{started['session_id']}/end")).json()
        assert ended["ok"] is True

        sessions2 = (await c.get("/api/replay/sessions?limit=5")).json()
        after = [s for s in sessions2["sessions"] if s["id"] == started["session_id"]]
        assert after and after[0]["ended_at"]
