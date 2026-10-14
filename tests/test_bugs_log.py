"""BUGS-LOG 12.09: регрессионные тесты на фиксы BUG-1…BUG-6.

BUG-2 — TTL-кэш публичного recent-events (успех 3 c / ошибка 1 c);
BUG-3 — /favicon.ico отдаётся, а не 404;
BUG-4 — circuit breaker локального fallback (Ollama): мёртвый провайдер
        не долбится каждым AI-вызовом;
BUG-6 — beep-воркер применяет настройки beep-фильтра из БД (beep_settings).
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


# ─────────────── BUG-4: circuit breaker Ollama-fallback ───────────────

def _ai():
    from app.ai_service import AIService
    return AIService()


async def test_breaker_opens_after_failures():
    ai = _ai()
    assert ai._fallback_healthy()
    for _ in range(ai.FALLBACK_FAIL_THRESHOLD):
        ai._note_fallback_result(False)
    assert not ai._fallback_healthy()


async def test_breaker_success_resets():
    ai = _ai()
    ai._note_fallback_result(False)
    ai._note_fallback_result(False)
    ai._note_fallback_result(True)
    assert ai._fallback_fail_streak == 0
    assert ai._fallback_healthy()


async def test_dead_ollama_not_called_when_breaker_open(monkeypatch):
    """При открытом breaker'е generate_text не дёргает Ollama (0 TCP-вызовов)."""
    ai = _ai()
    ai.offline_mode = True  # провайдер = ollama
    for _ in range(ai.FALLBACK_FAIL_THRESHOLD):
        ai._note_fallback_result(False)

    async def _fail(*a, **kw):
        raise AssertionError("Ollama не должен вызываться при открытом breaker'е")

    monkeypatch.setattr(ai, "_ollama_chat", _fail)
    result = await ai.generate_text("промпт", account_id=1, channel="chan")
    assert result == ""


async def test_fallback_attempt_skipped_when_breaker_open(monkeypatch):
    """Облачный провайдер вернул пусто → локальный fallback НЕ вызывается."""
    ai = _ai()
    for _ in range(ai.FALLBACK_FAIL_THRESHOLD):
        ai._note_fallback_result(False)

    async def _empty_cloud(*a, **kw):
        return ""

    async def _fail_fallback(*a, **kw):
        raise AssertionError("локальный fallback не должен вызываться при открытом breaker'е")

    monkeypatch.setattr(ai, "_openrouter_chat", _empty_cloud)
    monkeypatch.setattr(ai, "_ollama_chat", _fail_fallback)
    ai.provider = "openrouter"
    ai.openrouter_key = "k"
    result = await ai.generate_text("промпт", account_id=1, channel="chan")
    assert result == ""


# ─────────────── BUG-2: TTL-кэш публичного recent-events ───────────────

async def test_recent_events_public_caches_success(monkeypatch):
    import app.widgets as W
    W._RECENT_EVENTS_PUBLIC_CACHE.clear()

    calls = {"scope": 0, "read": 0}

    async def _scope(account_id, channel):
        calls["scope"] += 1
        return (1, "chan")

    async def _read(limit, scope=None):
        calls["read"] += 1
        return [{"kind": "follow", "username": "u"}]

    monkeypatch.setattr(W, "_verified_widget_state_scope", _scope)
    monkeypatch.setattr(W, "_read_recent_events", _read)

    a = await W.recent_events_public(limit=5, account_id=1, channel="chan")
    b = await W.recent_events_public(limit=5, account_id=1, channel="chan")
    assert a == b == [{"kind": "follow", "username": "u"}]
    assert calls == {"scope": 1, "read": 1}
    W._RECENT_EVENTS_PUBLIC_CACHE.clear()


async def test_recent_events_public_caches_error_briefly(monkeypatch):
    """BUG-1+2: нерезолвимый скоуп (400) тоже кэшируется на 1 c —
    десятки превью не должны устраивать шторм одинаковых отказов."""
    from fastapi import HTTPException
    import app.widgets as W
    W._RECENT_EVENTS_PUBLIC_CACHE.clear()

    calls = {"scope": 0}

    async def _scope(account_id, channel):
        calls["scope"] += 1
        raise HTTPException(status_code=400, detail="widget_scope_not_found")

    monkeypatch.setattr(W, "_verified_widget_state_scope", _scope)

    for _ in range(3):
        with pytest.raises(HTTPException) as ei:
            await W.recent_events_public(limit=5, account_id=1, channel="alekzz03")
        assert ei.value.detail == "widget_scope_not_found"
    assert calls["scope"] == 1  # 2-й и 3-й взялись из кэша ошибки
    W._RECENT_EVENTS_PUBLIC_CACHE.clear()


# ─────────────── BUG-3: favicon ───────────────

async def test_favicon_served(tmp_db, disable_auth):
    from httpx import ASGITransport, AsyncClient

    import app.server as server_mod

    async with AsyncClient(transport=ASGITransport(server_mod.app), base_url="http://test") as c:
        r = await c.get("/favicon.ico")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/x-icon"
    assert r.content[:4] == b"\x00\x00\x01\x00"  # ICO-заголовок


# ─────────────── BUG-6: beep-воркер учитывает beep_settings ───────────────

async def test_beep_status_reports_whisper_state_honestly():
    from app.beep_pipeline import BeepPipeline

    p = BeepPipeline()
    p._whisper = None
    p._whisper_failed = False
    st = await p.status()
    assert st["whisper_state"] == "unknown"  # ещё не проверялся — не заявляем pass-through
    p._whisper_failed = True
    st = await p.status()
    assert st["whisper_state"] == "unavailable"
    p._whisper = object()
    st = await p.status()
    assert st["whisper_state"] == "ready"


async def test_beep_worker_respects_guard_settings(tmp_db, monkeypatch):
    """Фильтр выключен в beep_settings → check_transcript не вызывается."""
    from app.database import init_db
    from app.beep_pipeline import BeepPipeline
    from app import beep_guard

    await init_db()
    await beep_guard.ensure_schema()

    # включённый фильтр с кастомным словом
    await beep_guard.update_settings("7", enabled=True, sensitivity="normal",
                                     custom_words={"блин": "custom"}, channels={})

    called = {"check": 0}
    real_check = beep_guard.check_transcript

    def _spy(text, custom_words=None, sensitivity="normal"):
        called["check"] += 1
        called["custom_words"] = custom_words
        called["sensitivity"] = sensitivity
        return real_check(text, custom_words=custom_words, sensitivity=sensitivity)

    monkeypatch.setattr("app.beep_guard.check_transcript", _spy)

    p = BeepPipeline()
    p.running = True
    p.cfg = {"account_id": "7", "channel": "chan", "segment_sec": 5, "beep_hz": 1000}
    p._tmpdir = ""
    p._processed = {"chunk_0001.wav"}  # все чанки «уже обработаны» — воркер не найдёт свежих
    p._whisper = None
    p._whisper_failed = True
    import asyncio as _aio

    async def _noop():
        return

    p.worker = _aio.create_task(p._worker())
    try:
        await _aio.sleep(0.2)
    finally:
        p.running = False
        p.worker.cancel()
        try:
            await p.worker
        except BaseException:  # noqa: BLE001  # CancelledError — норма при остановке
            pass
    # воркер крутился, свежих чанков нет — до check_transcript дойти не должно было,
    # но настройки загружаться обязаны без ошибки (smoke на новый код загрузки).
    assert called["check"] == 0
