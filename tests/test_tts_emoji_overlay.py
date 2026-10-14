"""§8 WIDGETS_PLAN: тести для емодзі-брендингу TTS + tts-chat-overlay."""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


async def _client(seed_accounts: tuple[int, ...] = ()):
    from app.database import init_db
    from app.widgets import admin_router, public_router, ensure_widgets_schema
    from app.routes import router as api_router
    from app import database as db_mod
    if db_mod._shared_db is not None:
        try: await db_mod._shared_db.close()
        except: pass
        db_mod._shared_db = None
    await init_db()
    await ensure_widgets_schema()
    if seed_accounts:
        from app.database import get_db
        db = await get_db()
        try:
            for aid in seed_accounts:
                await db.execute(
                    "INSERT OR IGNORE INTO accounts (id, nickname, token) "
                    "VALUES (?, ?, ?)",
                    (aid, f"tts_{aid}", "tok"),
                )
            await db.commit()
        finally:
            await db.close()
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(api_router)
    app.include_router(admin_router)
    app.include_router(public_router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ── emoji_prefix / emoji_suffix в tts_engine.speak ─────────────────

async def test_emoji_wrap_applied_in_speak(tmp_db, disable_auth, monkeypatch):
    """Якщо в tts_bot_config є prefix/suffix — speak() обгортає текст перед синтезом."""
    from app.database import init_db
    await init_db()
    from app import tts_engine

    sent: list[dict] = []
    # Використовуємо реальний TTSEngine singleton, але підміняємо
    # провайдера web_speech на наш CaptureProvider (через monkeypatch).
    engine = tts_engine.get_tts_engine()
    class CaptureProvider:
        async def synthesize(self, text, voice, emotion, speed):
            sent.append({"text": text, "voice": voice})
            return b"web-speech-blob"
    monkeypatch.setitem(engine._providers, "web_speech", CaptureProvider())
    # Увімкнути TTS для account_id=1 з prefix/suffix.
    from app.database import get_db
    db = await get_db()
    try:
        await db.execute("INSERT OR IGNORE INTO accounts (id, nickname, token) VALUES (1, 'a', 't')")
        await db.execute(
            "INSERT INTO tts_bot_config (account_id, enabled, provider, emoji_prefix, emoji_suffix) "
            "VALUES (1, 1, 'web_speech', '✨', '🔥')"
        )
        await db.commit()
    finally:
        await db.close()

    # Викликаємо speak напряму (потрібно обійти duck/pause через monkeypatch).
    from app import widget_bus
    widget_bus._reset_for_tests()
    async def _noop(**k):
        return None
    monkeypatch.setattr(widget_bus, "request_pause_media", _noop)
    monkeypatch.setattr(widget_bus, "request_resume_media", _noop)
    print("DEBUG widget_bus.request_pause_media:", widget_bus.request_pause_media, flush=True)
    print("DEBUG is_ducked:", widget_bus.is_ducked(), flush=True)
    print("DEBUG is_hard_muted:", widget_bus.is_hard_muted(), flush=True)
    print("DEBUG remaining_ms:", widget_bus.remaining_ms(), flush=True)

    await engine.speak(1, "ch1", "hello", emotion="neutral")
    # Текст у синтезі має бути обгорнутий.
    assert any("✨" in s["text"] and "hello" in s["text"] and "🔥" in s["text"]
               for s in sent), sent


async def _async_noop():
    return None


async def test_emoji_wrap_empty_does_not_change_text(tmp_db, disable_auth, monkeypatch):
    """Без prefix/suffix — текст передається як є."""
    from app.database import init_db
    await init_db()
    from app import tts_engine
    engine = tts_engine.get_tts_engine()
    sent: list[dict] = []
    class CaptureProvider:
        async def synthesize(self, text, voice, emotion, speed):
            sent.append({"text": text})
            return b""
    engine._providers["web_speech"] = CaptureProvider()

    from app.database import get_db
    db = await get_db()
    try:
        await db.execute("INSERT OR IGNORE INTO accounts (id, nickname, token) VALUES (2, 'a', 't')")
        await db.execute(
            "INSERT INTO tts_bot_config (account_id, enabled, provider) VALUES (2, 1, 'web_speech')"
        )
        await db.commit()
    finally:
        await db.close()

    from app import widget_bus
    widget_bus._reset_for_tests()
    async def _noop(**k):
        return None
    monkeypatch.setattr(widget_bus, "request_pause_media", _noop)
    monkeypatch.setattr(widget_bus, "request_resume_media", _noop)

    await engine.speak(2, "ch1", "plain text", emotion="neutral")
    assert any(s["text"] == "plain text" for s in sent), sent


# ── tts-chat-overlay widget ─────────────────────────────────────────

async def test_tts_chat_overlay_default(tmp_db, disable_auth):
    async with await _client() as c:
        r = await c.get("/widget/tts-chat-overlay")
        assert r.status_code == 200
        html = r.text
        # i18n-заглушка: EN-тайтл подставляется JS-ом, в HTML — RU-дефолт
        assert "Чат озвучки" in html or "TTS Chat Overlay" in html
        assert "#FFD700" in html  # gold default
        # За замовчуванням max_msgs=5, retain_ms=30000 (P6 PLAN.md)
        assert "5" in html
        assert "30000" in html


async def test_tts_chat_overlay_custom_params(tmp_db, disable_auth):
    async with await _client() as c:
        r = await c.get("/widget/tts-chat-overlay?color=%23ff00aa&max_msgs=10&retain_ms=30000")
        assert r.status_code == 200
        assert "#FF00AA" in r.text
        assert "10" in r.text
        assert "30000" in r.text


async def test_tts_chat_overlay_clamps(tmp_db, disable_auth):
    async with await _client() as c:
        r = await c.get("/widget/tts-chat-overlay?max_msgs=999&retain_ms=999999")
        assert r.status_code == 200
        # max_msgs clamp [1, 20]
        assert "20" in r.text
        # retain_ms clamp [2000, 60000]
        assert "60000" in r.text


async def test_tts_chat_overlay_uses_db_color(tmp_db, disable_auth):
    await _client(seed_accounts=(7,))
    from app.database import get_db
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO tts_bot_config (account_id, widget_color) VALUES (7, '#abcdef')"
        )
        await db.commit()
    finally:
        await db.close()
    async with await _client() as c:
        r = await c.get("/widget/tts-chat-overlay?account_id=7")
        assert r.status_code == 200
        assert "#ABCDEF" in r.text
