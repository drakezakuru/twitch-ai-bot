"""Regression coverage for the v13 UI/backend additions."""

from __future__ import annotations

import re

import pytest
from httpx import ASGITransport, AsyncClient
from pathlib import Path
from tests import _panel_js


def test_dynamic_ui_localization_has_runtime_keys_for_all_languages():
    app_js = (Path(__file__).resolve().parents[1] / "static" / "app.js").read_text()
    for key in (
        "label.connecting", "label.error", "toast.not_sent_by_bots",
        "toast.trigger_updated", "toast.event_added", "status.runtime",
        "status.ai_paused", "status.ai_paused_short", "status.fallback_enabled", "status.runtime_error",
    ):
        assert app_js.count(f"'{key}'") >= 3


def test_all_active_template_and_javascript_i18n_keys_exist_in_each_locale():
    root = Path(__file__).resolve().parents[1]
    js = _panel_js.panel_js()
    template_text = "\n".join(path.read_text() for path in [
        root / "templates" / "base.html",
        *sorted((root / "templates" / "partials").glob("*.html")),
    ])
    template_keys = set(re.findall(r'data-i18n(?:-placeholder|-title|-aria-label)?="([^"]+)"', template_text))
    template_keys = {key for key in template_keys if "{{" not in key}
    javascript_keys = set(re.findall(r"\bt\(['\"]([^'\"]+)['\"]", js))
    referenced = template_keys | javascript_keys
    # ключи-префиксы (t('donation.provider.' + mode)) переводятся по суффиксу —
    # литерала-перевода для них не существует; то же для хвостов на '_' вроде
    # t('channels.mod_status_' + status) и t('panel.mod.ext_' + action_ext)
    referenced = {key for key in referenced if not key.endswith('.') and not key.endswith('_')}
    missing = [key for key in sorted(referenced) if js.count(f"'{key}'") + js.count(f'"{key}"') < 3]
    assert not missing, f"Missing RU/EN/UA translations: {missing}"


@pytest.mark.asyncio
async def test_send_route_returns_actionable_failure(tmp_db, disable_auth):
    from app import database
    from fastapi import FastAPI
    from app.routes import router

    await database.init_db()
    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/send", json={"account_id": 1, "channel": "", "text": "hello"})
        assert response.status_code == 200
        assert response.json() == {
            "ok": False,
            "reason": "invalid_target",
            "error": "Укажите бота и канал",
        }


@pytest.mark.asyncio
async def test_trigger_validation_and_update(tmp_db, disable_auth):
    from app import database
    from fastapi import FastAPI
    from app.routes import router

    await database.init_db()
    db = await database.get_db()
    try:
        await db.execute("INSERT INTO accounts (id, nickname, token) VALUES (1, 'bot', 'tok')")
        await db.commit()
    finally:
        await db.close()

    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        invalid = await client.post("/api/accounts/1/triggers", json={"keyword": "  "})
        assert invalid.json()["ok"] is False

        created = await client.post("/api/accounts/1/triggers", json={
            "keyword": "hello", "response": "hi", "use_ai": False,
        })
        trigger_id = created.json()["trigger_id"]
        updated = await client.put(f"/api/triggers/{trigger_id}", json={
            "keyword": "welcome", "enabled": False,
        })
        assert updated.json()["ok"] is True
        trigger = (await client.get("/api/accounts/1/triggers")).json()[0]
        assert trigger["keyword"] == "welcome"
        assert trigger["enabled"] == 0


@pytest.mark.asyncio
async def test_event_response_validation_and_clamps_chance(tmp_db, disable_auth):
    from app import database
    from fastapi import FastAPI
    from app.routes import router

    await database.init_db()
    db = await database.get_db()
    try:
        await db.execute("INSERT INTO accounts (id, nickname, token) VALUES (1, 'bot', 'tok')")
        await db.commit()
    finally:
        await db.close()

    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        invalid = await client.post("/api/accounts/1/events", json={"event_type": ""})
        assert invalid.json()["ok"] is False

        created = await client.post("/api/accounts/1/events", json={
            "event_type": "follow", "chance": 999, "use_ai": False,
        })
        assert created.json()["ok"] is True
        event = (await client.get("/api/accounts/1/events")).json()[0]
        assert event["event_type"] == "follow"
        assert event["chance"] == 100


@pytest.mark.asyncio
async def test_filter_routes_accept_panel_payloads(tmp_db, disable_auth):
    from app import database
    from fastapi import FastAPI
    from app.routes import router

    await database.init_db()
    db = await database.get_db()
    try:
        await db.execute("INSERT INTO accounts (id, nickname, token) VALUES (1, 'bot', 'tok')")
        await db.commit()
    finally:
        await db.close()

    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        banned = await client.post("/api/accounts/1/banlist", json={"username": "Alice"})
        assert banned.json()["ok"] is True
        assert (await client.get("/api/accounts/1/banlist")).json()[0]["username"] == "alice"

        word = await client.post("/api/accounts/1/wordfilter", json={"word": "Spoiler", "action": "replace"})
        assert word.json()["ok"] is True
        assert (await client.get("/api/accounts/1/wordfilter")).json()[0]["action"] == "replace"


@pytest.mark.asyncio
async def test_join_and_leave_keep_channel_enabled_state_in_sync(tmp_db, disable_auth, monkeypatch):
    import sys
    from types import SimpleNamespace

    from app import database
    from fastapi import FastAPI
    from app.routes import router

    await database.init_db()
    db = await database.get_db()
    try:
        await db.execute("INSERT INTO accounts (id, nickname, token) VALUES (1, 'bot', 'tok')")
        await db.commit()
    finally:
        await db.close()

    fake_manager = SimpleNamespace(
        join_channel=lambda *_args: _completed(True),
        leave_channel=lambda *_args: _completed(True),
    )
    monkeypatch.setitem(sys.modules, "app.server", SimpleNamespace(bot_manager=fake_manager))
    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        joined = await client.post("/api/accounts/1/join", json={"channel": "#Alpha"})
        assert joined.json()["ok"] is True
        assert (await client.get("/api/accounts/1/channels")).json()[0]["enabled"] == 1
        left = await client.post("/api/accounts/1/leave", json={"channel": "alpha"})
        assert left.json()["ok"] is True
        assert (await client.get("/api/accounts/1/channels")).json()[0]["enabled"] == 0


async def _completed(value):
    return value


@pytest.mark.asyncio
async def test_custom_behavior_preset_crud(tmp_db, disable_auth):
    from app import database
    from fastapi import FastAPI
    from app.routes import router

    await database.init_db()
    db = await database.get_db()
    try:
        await db.execute("INSERT INTO accounts (id, nickname, token) VALUES (1, 'bot', 'tok')")
        await db.commit()
    finally:
        await db.close()

    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/api/accounts/1/behavior-presets", json={
            "name": "Calm custom", "values": {"humor_level": 12, "observation_only": True},
        })
        assert created.status_code == 200
        assert created.json()["ok"] is True
        listed = await client.get("/api/accounts/1/behavior-presets")
        assert listed.json()["presets"][0]["values"]["humor_level"] == 12
        deleted = await client.delete(f"/api/behavior-presets/{created.json()['id']}")
        assert deleted.json()["ok"] is True


@pytest.mark.asyncio
async def test_runtime_status_route(tmp_db, disable_auth):
    from app import database
    from fastapi import FastAPI
    from app.routes import router

    await database.init_db()
    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/runtime/status")
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert "ai_provider" in payload
        assert "fallback_enabled" in payload


@pytest.mark.asyncio
async def test_voice_clone_registration_with_sample(tmp_db, disable_auth, monkeypatch, tmp_path):
    from app import database
    from app import voice_clone
    from fastapi import FastAPI
    from app.routes import router

    await database.init_db()
    monkeypatch.setattr(voice_clone, "VOICE_CLONES_DIR", tmp_path)
    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/voice-clones", json={
            "name": "streamer voice", "provider": "xtts", "sample_b64": "dGVzdA==",
        })
        payload = response.json()
        assert response.status_code == 200
        assert payload["ok"] is True
        assert payload["clone"]["provider"] == "xtts"
        assert payload["clone"]["sample_path"]


def test_global_vision_override_is_used_for_accounts(monkeypatch):
    from app.ai_service import AIService

    service = AIService()
    service.provider = "ollama"
    service.ollama_vision = "llava"
    service.update_config({"global_vision_override": "qwen2-vl"})
    assert service._resolve(0)[2] == "qwen2-vl"
