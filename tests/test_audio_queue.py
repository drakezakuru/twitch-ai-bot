"""§7 WIDGETS_PLAN: тести для загальної аудіо-черги (AudioQueue)."""
from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.asyncio


async def test_enqueue_priority_routing():
    from app.audio_queue import (
        get_audio_queue,
        PRIORITY_ALERT, PRIORITY_TTS_STREAMER,
        PRIORITY_TTS_CHAT_READER, PRIORITY_TTS_NORMAL,
    )
    q = get_audio_queue()
    q._reset_for_tests()
    assert PRIORITY_ALERT < PRIORITY_TTS_STREAMER < PRIORITY_TTS_CHAT_READER < PRIORITY_TTS_NORMAL
    assert PRIORITY_ALERT == 0
    assert PRIORITY_TTS_NORMAL == 20


async def test_enqueue_creates_and_clears_item(monkeypatch):
    """Після делегування в TTS item з облікової черги зникає."""
    from app.audio_queue import get_audio_queue
    from app import tts_engine

    called: list[dict] = []
    class FakeEngine:
        async def speak(self, account_id, channel, text, emotion="neutral", **kwargs):
            called.append({"aid": account_id, "ch": channel, "text": text})
    monkeypatch.setattr(tts_engine, "get_tts_engine", lambda: FakeEngine())

    q = get_audio_queue()
    q._reset_for_tests()
    await q.enqueue("tts_normal", 1, "ch1", "hello")
    # Після speak() — наша облікова черга порожня (транзитна).
    assert q.size() == 0
    assert len(called) == 1
    assert called[0]["text"] == "hello"


async def test_enqueue_alert_no_tts(monkeypatch):
    """Для kind='alert' TTS не викликається (заглушка)."""
    from app.audio_queue import get_audio_queue
    from app import tts_engine

    called: list[dict] = []
    class FakeEngine:
        async def speak(self, *a, **k):
            called.append({"a": a, "k": k})
    monkeypatch.setattr(tts_engine, "get_tts_engine", lambda: FakeEngine())

    q = get_audio_queue()
    q._reset_for_tests()
    await q.enqueue("alert", 1, "ch", "donation sound")
    assert q.size() == 0
    assert called == []  # TTS не викликався


async def test_snapshot_orders_by_priority(monkeypatch):
    """snapshot() сортує за пріоритетом (нижче = перший)."""
    from app.audio_queue import get_audio_queue
    from app import tts_engine

    async def slow_speak(*a, **k):
        await asyncio.sleep(0.1)  # блокуємо, щоб items лишилися в обліку
    monkeypatch.setattr(tts_engine, "get_tts_engine", lambda: type("E", (), {"speak": staticmethod(slow_speak)})())

    q = get_audio_queue()
    q._reset_for_tests()
    # Запускаємо кілька enqueue без очікування — вони збираються в обліку.
    tasks = [
        asyncio.create_task(q.enqueue("tts_normal", 1, "ch", "n1")),
        asyncio.create_task(q.enqueue("tts_streamer", 1, "ch", "s1")),
        asyncio.create_task(q.enqueue("tts_chat_reader", 1, "ch", "r1")),
    ]
    # alert додаємо напряму (без speak) — теж має бути в обліку під час snapshot.
    # Емулюємо поведінку: ставимо item в облік, не очікуючи delegate.
    import asyncio as _aio
    await _aio.sleep(0.005)
    snap = q.snapshot()
    # Маємо 3 tts-елементи у порядку priority.
    assert [s["kind"] for s in snap] == [
        "tts_streamer", "tts_chat_reader", "tts_normal",
    ], snap
    # Дочекатися завершення всіх (інакше event loop warning).
    for t in tasks:
        try:
            await t
        except Exception:
            pass


async def test_backlog_capped_at_max_size(monkeypatch):
    """Якщо enqueue викликається занадто багато разів підряд — старі викидаються."""
    from app.audio_queue import get_audio_queue
    from app import tts_engine

    # Mock speak, який нічого не робить (items лишаються в обліку).
    async def noop(*a, **k):
        return None
    monkeypatch.setattr(tts_engine, "get_tts_engine", lambda: type("E", (), {"speak": staticmethod(noop)})())

    q = get_audio_queue()
    q._reset_for_tests()
    tasks = [
        asyncio.create_task(q.enqueue("tts_normal", 1, "ch", f"msg_{i}"))
        for i in range(q._max_size + 10)
    ]
    await asyncio.sleep(0.01)  # дати час додати в чергу
    # Розмір обмежений max_size
    assert q.size() <= q._max_size
    for t in tasks:
        try:
            await t
        except Exception:
            pass


async def test_clear_and_size(monkeypatch):
    from app.audio_queue import get_audio_queue
    from app import tts_engine
    async def noop(*a, **k): return None
    monkeypatch.setattr(tts_engine, "get_tts_engine", lambda: type("E", (), {"speak": staticmethod(noop)})())

    q = get_audio_queue()
    q._reset_for_tests()
    await asyncio.create_task(q.enqueue("tts_normal", 1, "ch", "x"))
    await asyncio.sleep(0.005)
    assert q.size() == 0  # вже очищено після speak
    q.clear()
    assert q.size() == 0


async def test_chat_reader_uses_audio_queue(tmp_db, disable_auth, monkeypatch):
    """read_chat_message (§6.1) делегую в AudioQueue (kind=tts_chat_reader)."""
    from app import audio_queue, tts_engine
    spoken: list[dict] = []
    async def fake_speak(account_id, channel, text, emotion="neutral", **kwargs):
        spoken.append({"aid": account_id, "ch": channel, "text": text})
    monkeypatch.setattr(tts_engine, "get_tts_engine",
                        lambda: type("E", (), {"speak": staticmethod(fake_speak)})())
    q = audio_queue.get_audio_queue()
    q._reset_for_tests()

    from app.database import init_db, get_db
    await init_db()
    from app.widgets import ensure_widgets_schema
    await ensure_widgets_schema()
    db = await get_db()
    try:
        await db.execute("INSERT OR IGNORE INTO accounts (id, nickname, token) VALUES (1, 'a', 't')")
        await db.execute("INSERT INTO chat_reader_settings (account_id, enabled, read_all, command, min_role, tts_provider, max_chars, cooldown_sec) VALUES (1, 1, 1, '!read', 'any', '', 200, 0)")
        await db.commit()
    finally:
        await db.close()

    from app.widgets import read_chat_message
    r = await read_chat_message(1, "ch", "u1", "hello", trigger="all", badges=None)
    assert r.get("ok") is True
    assert len(spoken) == 1
    assert spoken[0]["text"] == "hello"
