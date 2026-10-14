"""P1 §6/§9g/§9h: карточки на главной странице бота (Обзор).

Проверяем:
1. §6 quick-настройки: разметка (quickAutoChat/quickSilent/quickObservation/quickCooldown),
   i18n-ключ behavior.cooldown, PUT /api/accounts/{id}/analyzer принимает cooldown.
2. §9g Clip Detector: config roundtrip (GET/PUT), check при всплеске пишет момент
   в clip_moments, моменты читаются через /moments.
3. §9h Replay: события сессии читаются через API, сессия удаляется через API,
   автозапись при старте/остановке бота (bot_manager).
4. §3 плюрализация: PLURAL_FORMS содержит replies/events/errors для ru/ua/en.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport
from tests import _panel_js

pytestmark = pytest.mark.asyncio

ROOT = Path(__file__).resolve().parent.parent


async def _client():
    from fastapi import FastAPI
    from app.routes import router
    app = FastAPI()
    app.include_router(router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_bot_cards_fall_back_to_persisted_channels_for_disabled_accounts(tmp_db, disable_auth):
    """A disabled bot has no runtime instance, but its configured channels remain visible."""
    from app import database
    await database.init_db()
    db = await database.get_db()
    try:
        await db.execute("INSERT INTO accounts (id, nickname, token, enabled) VALUES (1, 'qa', 'fake', 0)")
        await db.execute(
            "INSERT INTO channels (account_id, channel_name, enabled) VALUES (1, 'qa_channel', 1)"
        )
        await db.commit()
    finally:
        await db.close()

    async with await _client() as client:
        accounts = (await client.get("/api/accounts")).json()
    assert len(accounts) == 1
    assert accounts[0]["enabled"] == 0
    assert accounts[0]["persisted_channels"] == ["qa_channel"]

    dashboard_js = (ROOT / "static" / "app" / "02_dashboard.js").read_text(encoding="utf-8")
    bots_js = (ROOT / "static" / "app" / "03_bots.js").read_text(encoding="utf-8")
    assert "function botDisplayChannels(b, st)" in dashboard_js
    assert "return runtimeChannels.length ? runtimeChannels : persistedChannels;" in dashboard_js
    assert dashboard_js.count("botDisplayChannels(b, st)") == 2
    assert "const displayChannels = botDisplayChannels(b, st);" in bots_js


# ---------- §6: quick-настройки ----------

def test_quick_settings_markup():
    html = (ROOT / "templates" / "partials" / "bots.html").read_text(encoding="utf-8")
    for frag in (
        'id="quickAutoChat"',
        'id="quickSilent"',
        'id="quickObservation"',
        'id="quickCooldown"',
        'data-i18n="behavior.cooldown"',
        'data-i18n="bot.quick_title"',
    ):
        assert frag in html, f"quick-settings markup missing: {frag}"


def test_custom_provider_models_are_dropdowns_for_named_providers():
    # Q15b (E3): у custom:*-провайдера чат- и vision-модели — дропдауны из списков
    # провайдера; для встроенных провайдеров остаётся свободный ввод.
    html = (ROOT / "templates" / "partials" / "bots.html").read_text(encoding="utf-8")
    js = _panel_js.panel_js()
    assert '<input type="text" id="botAIModel"' in html
    assert '<select id="botAIModelSelect"' in html
    assert '<input type="text" id="botAIVisionModel"' in html
    assert '<select id="botAIVisionModelSelect"' in html
    assert 'list="botAIVisionModels"' not in html, "ручной ввод через datalist убран (Q15b)"
    assert "function _botNamedProvider(" in js
    assert "function refreshBotAIModels(" in js
    assert "refreshBotAIVisionModels" not in js
    # Q15a-контракт сохранён: «своя» с пустым полем = общая (пустая строка)
    assert "data.ai_vision_model_override = mode === 'own' ? vm : ''" in js


async def test_analyzer_put_cooldown_roundtrip(tmp_db, disable_auth):
    from app import database
    await database.init_db()
    async with await _client() as c:
        put = (await c.put("/api/accounts/1/analyzer", json={"cooldown": 15})).json()
        assert put["cooldown"] == 15
        got = (await c.get("/api/accounts/1/analyzer")).json()
        assert got["cooldown"] == 15


# ---------- §9g: Clip Detector ----------

async def test_clip_config_roundtrip(tmp_db, disable_auth):
    from app import database
    await database.init_db()
    async with await _client() as c:
        cfg = (await c.get("/api/bot/clip-detector/config")).json()
        assert {"threshold_multiplier", "window_sec", "cooldown_sec"} <= set(cfg)

        put = (await c.put("/api/bot/clip-detector/config", json={
            "threshold_multiplier": 2.0, "window_sec": 45, "cooldown_sec": 10,
        })).json()
        assert put["ok"] is True
        cfg = (await c.get("/api/bot/clip-detector/config")).json()
        assert cfg["threshold_multiplier"] == 2.0
        assert cfg["window_sec"] == 45
        assert cfg["cooldown_sec"] == 10


async def test_clip_check_records_moment_on_spike(tmp_db, disable_auth):
    from app import database
    from app.routes import _chat_rate_tracker, _clip_cooldowns
    await database.init_db()
    async with await _client() as c:
        await c.put("/api/bot/clip-detector/config", json={
            "threshold_multiplier": 1.2, "window_sec": 60, "cooldown_sec": 5,
        })
        # Наполняем трекер: 6 сообщений за последние 30 сек
        import time as _time
        key = (7, "testchan")
        _chat_rate_tracker[key] = [_time.time() - i * 4 for i in range(6)]
        _clip_cooldowns.pop(key, None)

        check = (await c.get("/api/bot/clip-detector/check/7/testchan")).json()
        assert check["spike"] is True

        moments = (await c.get("/api/bot/clip-detector/moments/7")).json()["items"]
        assert len(moments) == 1
        assert moments[0]["channel"] == "testchan"
        assert moments[0]["clip_url"] in (None, "")


# ---------- §9h: Replay ----------

async def test_replay_events_and_delete_api(tmp_db, disable_auth):
    from app import database
    await database.init_db()
    async with await _client() as c:
        started = (await c.post("/api/replay/sessions/start", json={
            "account_id": 3, "channel": "demo", "name": "ui_test",
        })).json()
        assert started["ok"] is True and started["session_id"] > 0
        sid = started["session_id"]

        events = (await c.get(f"/api/replay/sessions/{sid}/events")).json()
        assert "events" in events

        deleted = (await c.delete(f"/api/replay/sessions/{sid}")).json()
        assert deleted["ok"] is True
        sessions = (await c.get("/api/replay/sessions?limit=50")).json()["sessions"]
        assert all(s["id"] != sid for s in sessions)


async def test_replay_auto_record_start_stop(tmp_db, disable_auth):
    from app import database
    from app.bot_manager import BotInstance, TwitchBotManager
    await database.init_db()

    # По умолчанию автозапись включена
    manager = TwitchBotManager()
    inst = BotInstance(account_id=9, nickname="replaybot", token="oauth:x", channels=["#demo"])
    try:
        await manager._replay_auto_start(inst)
        assert inst.replay_session_id and inst.replay_session_id > 0
        sid = inst.replay_session_id
        sessions = (await manager._replay_list()).get("sessions", [])
        mine = [s for s in sessions if s["id"] == sid]
        assert mine and mine[0]["ended_at"] is None and mine[0]["account_id"] == 9

        await manager._replay_auto_end(inst)
        sessions = (await manager._replay_list()).get("sessions", [])
        mine = [s for s in sessions if s["id"] == sid]
        assert mine and mine[0]["ended_at"] is not None
        assert inst.replay_session_id is None

        # Настройка выключена → сессия не открывается
        from app.database import set_setting
        await set_setting("replay_auto_record", "0")
        inst2 = BotInstance(account_id=10, nickname="noreplay", token="oauth:x", channels=["#demo"])
        await manager._replay_auto_start(inst2)
        assert inst2.replay_session_id is None
    finally:
        if inst.replay_session_id:
            await manager._replay_auto_end(inst)


# ---------- §3: плюрализация ----------

def test_plural_forms_has_replies_events_errors():
    js = _panel_js.panel_js()
    marker = "const PLURAL_FORMS = {"
    start = js.index(marker)
    end = js.index("};", start)
    block = js[start:end]
    for key in ("replies", "events", "errors"):
        assert f"{key}: {{" in block, f"PLURAL_FORMS missing: {key}"
        # каждая форма должна присутствовать в 3 локалях (ru/ua/en)
        assert block.count(f"{key}: {{") == 1
        for lang in ("ru:", "ua:", "en:"):
            seg_start = block.index(f"{key}: {{")
            seg_end = block.index("}", seg_start)
            assert lang in block[seg_start:seg_end], f"{key} missing locale {lang}"


# ---------- Persona toggles: рендер не должен затенять функцию перевода t() ----------

def test_persona_toggles_render_does_not_shadow_translator():
    """Баг: PERSONA_TOGGLES.map(t => ... t(tg.label)) — параметр t затенял t(),
    внутри использовался несуществующий tg → ReferenceError, тумблеры персоны
    не рендерились вообще."""
    js = (Path(__file__).parent.parent / "static" / "app" / "03_bots.js").read_text(encoding="utf-8")
    start = js.index("$('personaToggles').innerHTML")
    block = js[start:js.index("`).join('');", start)]
    assert "PERSONA_TOGGLES.map(t =>" not in block, "параметр map снова затеняет t()"
    assert "t(tg.label)" in block, "перевод label должен идти через функцию t()"
    assert "tg.key" in block, "значение тумблера должно читаться по tg.key"
