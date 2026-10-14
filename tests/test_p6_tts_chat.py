"""P6 PLAN.md: TTS-чат (озвучки) — speaker в WS-событии + карточка/виджет."""
from __future__ import annotations

import pytest
from tests import _panel_js

pytestmark = pytest.mark.asyncio


async def test_broadcast_tts_event_includes_speaker_fields(tmp_db, disable_auth):
    """broadcast_tts_event добавляет speaker/speaker_kind/speaker_emoji."""
    from app.database import init_db, get_db
    await init_db()
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO accounts (id, nickname, token) VALUES (1, 'BotName', 't')")
        await db.execute(
            "INSERT OR IGNORE INTO tts_bot_config (account_id, widget_emoji) "
            "VALUES (1, '🤖')")
        await db.commit()
    finally:
        await db.close()

    from app import tts_engine
    sent: list[dict] = []

    async def fake_broadcast(msg):
        sent.append(msg)

    import app.server as server
    orig = server.broadcast_log
    server.broadcast_log = fake_broadcast
    try:
        # 1) Бот без явного speaker → nickname из accounts + эмодзи из конфига.
        await tts_engine.broadcast_tts_event(
            channel="ch1", account_id=1, text="привет", emotion="neutral",
            audio_b64="", mime="audio/wav", provider="web_speech")
        # 2) Зритель (TTS за баллы) → ник редиктора + 📣.
        await tts_engine.broadcast_tts_event(
            channel="ch1", account_id=1, text="Говорит ivan: тест", emotion="neutral",
            audio_b64="", mime="audio/wav", provider="web_speech",
            speaker="ivan", speaker_kind="viewer", display_text="тест")
    finally:
        server.broadcast_log = orig

    bot_ev = sent[0]
    assert bot_ev["type"] == "tts"
    assert bot_ev["speaker"] == "BotName"
    assert bot_ev["speaker_kind"] == "bot"
    assert bot_ev["speaker_emoji"] == "🤖"
    viewer_ev = sent[1]
    assert viewer_ev["speaker"] == "ivan"
    assert viewer_ev["speaker_kind"] == "viewer"
    assert viewer_ev["speaker_emoji"] == "📣"
    assert viewer_ev["display_text"] == "тест"


async def test_redemption_enqueues_speaker(tmp_db, disable_auth):
    """handle_redemption передаёт ник редиктора в audio_queue."""
    from app.database import init_db, get_db
    await init_db()
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO accounts (id, nickname, token) VALUES (9, 'bot9', 't')")
        await db.commit()
    finally:
        await db.close()

    from app.channel_points_tts import save_config, handle_redemption, _reset_rate_state
    await save_config(9, {"enabled": 1})
    _reset_rate_state()

    from app import audio_queue
    q = audio_queue.get_audio_queue()
    q._reset_for_tests()
    items: list[dict] = []

    class FakeEngine:
        async def speak(self, *a, **k):
            items.append({"args": a, "kwargs": k})

    orig_get = None
    from app import tts_engine as tts_engine_mod
    orig_get = tts_engine_mod.get_tts_engine
    tts_engine_mod.get_tts_engine = lambda: FakeEngine()
    try:
        ok = await handle_redemption(9, "ch1", {
            "user_login": "redactor",
            "user_input": "привет из чата",
            "reward": {"title": "Озвучить сообщение"},
        })
    finally:
        tts_engine_mod.get_tts_engine = orig_get

    assert ok is True
    assert len(items) == 1
    kw = items[0]["kwargs"]
    assert kw["speaker"] == "redactor"
    assert kw["speaker_kind"] == "viewer"
    assert kw["display_text"] == "привет из чата"


async def test_tts_chat_overlay_default_30s(tmp_db, disable_auth):
    """Дефолт скрытия 30000 мс (30с), а не 12000."""
    from httpx import AsyncClient, ASGITransport
    from app.database import init_db
    from app.widgets import public_router, ensure_widgets_schema
    from app import database as db_mod
    if db_mod._shared_db is not None:
        try:
            await db_mod._shared_db.close()
        except Exception:
            pass
        db_mod._shared_db = None
    await init_db()
    await ensure_widgets_schema()
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(public_router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/widget/tts-chat-overlay")
        assert r.status_code == 200
        assert "30000" in r.text


async def test_widget_page_contains_tts_chat_card():
    """Карточка «TTS-чат (озвучки)» есть в widgets.html + i18n ru/en/ua в app.js."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    tpl = (root / "templates" / "partials" / "widgets.html").read_text()
    assert 'data-i18n="tts_chat.title"' in tpl
    assert "ttsChatCard" in tpl
    js = _panel_js.panel_js()
    for key in ("tts_chat.title", "tts_chat.hide"):
        assert js.count(f"'{key}'") >= 3
    # Кнопка копирования переиспользует существующий ключ (запрет дублей §3.2)
    assert 'data-i18n="brainx.copy"' in tpl
    assert "loadTtsChatCard" in js


async def test_speak_signature_accepts_speaker_kwargs(tmp_db, disable_auth, monkeypatch):
    """TTSEngine.speak прокидывает speaker-поля в broadcast_tts_event."""
    from app.database import init_db, get_db
    await init_db()
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO accounts (id, nickname, token) VALUES (3, 'bot3', 't')")
        await db.execute(
            "INSERT INTO tts_bot_config (account_id, enabled, provider) VALUES (3, 1, 'web_speech')")
        await db.commit()
    finally:
        await db.close()

    from app import tts_engine, widget_bus
    widget_bus._reset_for_tests()

    async def _noop(**k):
        return None

    monkeypatch.setattr(widget_bus, "request_pause_media", _noop)
    monkeypatch.setattr(widget_bus, "request_resume_media", _noop)

    class CaptureProvider:
        async def synthesize(self, text, voice, emotion, speed):
            return b"x"

    engine = tts_engine.get_tts_engine()
    monkeypatch.setitem(engine._providers, "web_speech", CaptureProvider())

    events: list[dict] = []

    async def fake_bcast(**kw):
        events.append(kw)

    monkeypatch.setattr(tts_engine, "broadcast_tts_event", fake_bcast)
    await engine.speak(3, "ch1", "текст", speaker="viewer1",
                       speaker_kind="viewer", display_text="текст")
    assert events and events[0]["speaker"] == "viewer1"
    assert events[0]["speaker_kind"] == "viewer"
    assert events[0]["display_text"] == "текст"
