"""§1 WIDGETS_PLAN: тесты для Widget Audio Bus.

Проверяем:
1. in-memory state (start/end/TTL/purge/hard_mute).
2. ``is_ducked()`` отдаёт самый «длинный» активный источник.
3. ``_resolve_duck_duration()`` для известного/неизвестного event_kind.
4. ``on_eventsub_event("channel.subscribe", ...)`` взводит ``duck_start``
   через ``widget_bus`` (интеграция §1+§3).
"""
from __future__ import annotations

import asyncio
import time

import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _no_broadcast(monkeypatch):
    """Глушимо розсилку widget_bus, щоб тести не зачіпали реальний broadcast_log."""
    from app import widget_bus
    async def fake_broadcast(kind, **kw):
        return None
    monkeypatch.setattr(widget_bus, "_broadcast_bus", fake_broadcast)


async def test_duck_basic_start_end():
    from app import widget_bus
    widget_bus._reset_for_tests()
    assert widget_bus.is_ducked() is None

    await widget_bus.duck_start("donation", channel="alpha", reason="donation", duration_ms=500)
    st = widget_bus.is_ducked("alpha")
    assert st is not None
    assert st.source == "donation"
    assert st.hard_mute is False
    assert 0 < widget_bus.remaining_ms() <= 500

    await widget_bus.duck_end("donation", channel="alpha")
    assert widget_bus.is_ducked("alpha") is None


async def test_duck_extends_window_on_repeat():
    """Повторный duck_start для того же source продлевает окно."""
    from app import widget_bus
    widget_bus._reset_for_tests()
    await widget_bus.duck_start("subscribe", channel="alpha", duration_ms=100)
    await asyncio.sleep(0.05)
    await widget_bus.duck_start("subscribe", channel="alpha", duration_ms=500)
    st = widget_bus.is_ducked("alpha")
    assert st is not None
    # Должно быть существенно больше исходных 100мс
    assert widget_bus.remaining_ms() > 200


async def test_duck_hard_mute_flag():
    from app import widget_bus
    widget_bus._reset_for_tests()
    await widget_bus.duck_start("alert", channel="alpha", hard_mute=True, duration_ms=1000)
    assert widget_bus.is_hard_muted("alpha") is True
    widget_bus._reset_for_tests()
    await widget_bus.duck_start("alert", channel="alpha", hard_mute=False, duration_ms=1000)
    assert widget_bus.is_hard_muted("alpha") is False


async def test_duck_ttl_expires_lazily():
    from app import widget_bus
    widget_bus._reset_for_tests()
    await widget_bus.duck_start("cheer", channel="alpha", duration_ms=50)
    assert widget_bus.is_ducked() is not None
    await asyncio.sleep(0.08)
    # После истечения окна is_ducked() возвращает None
    assert widget_bus.is_ducked() is None


async def test_purge_expired_removes_stale():
    from app import widget_bus
    widget_bus._reset_for_tests()
    await widget_bus.duck_start("a", channel="alpha", duration_ms=30)
    await widget_bus.duck_start("b", channel="beta", duration_ms=10000)
    await asyncio.sleep(0.05)
    removed = widget_bus.purge_expired()
    assert removed == 1
    snap = widget_bus.get_active_ducks_snapshot()
    assert len(snap) == 1
    assert snap[0]["source"] == "b"


async def test_snapshot_includes_remaining_ms():
    from app import widget_bus
    widget_bus._reset_for_tests()
    await widget_bus.duck_start("raid", channel="alpha", reason="raid_event", duration_ms=2000)
    snap = widget_bus.get_active_ducks_snapshot()
    assert len(snap) == 1
    assert snap[0]["source"] == "raid"
    assert snap[0]["channel"] == "alpha"
    assert snap[0]["reason"] == "raid_event"
    assert 0 < snap[0]["remaining_ms"] <= 2000


async def test_resolve_duck_duration_known(tmp_db, disable_auth):
    """Известный event_kind даёт duration из таблицы (или дефолт 8000)."""
    from app.database import init_db
    await init_db()
    from app.server import _resolve_duck_duration
    # После первого вызова таблица создастся с дефолтами.
    ms = await _resolve_duck_duration("subscribe")
    assert ms == 8000
    ms_raid = await _resolve_duck_duration("raid")
    assert ms_raid == 10000


async def test_resolve_duck_duration_unknown_uses_default(tmp_db, disable_auth):
    from app.database import init_db
    await init_db()
    from app.server import _resolve_duck_duration
    # follow заведено с duration=0 (не глушит), но неизвестный ключ — 8000
    ms = await _resolve_duck_duration("some_new_kind")
    assert ms == 8000


async def test_resolve_duck_duration_follow_disabled(tmp_db, disable_auth):
    from app.database import init_db
    await init_db()
    from app.server import _resolve_duck_duration
    ms = await _resolve_duck_duration("follow")
    assert ms == 0


async def test_eventsub_subscribe_triggers_duck(tmp_db, disable_auth, monkeypatch):
    """§1+§3: channel.subscribe → on_eventsub_event → widget_bus.duck_start.

    Проверяем по фактическому состоянию ``_active_ducks`` в widget_bus.
    """
    from app.database import init_db
    await init_db()

    from app import server as srv
    from app import widget_bus
    widget_bus._reset_for_tests()

    # Минимально нужные поля payload, чтобы on_eventsub_event дошёл до нашего хука.
    await srv.on_eventsub_event(
        account_id=1,
        event_type="channel.subscribe",
        channel="streamer",
        payload={"user_login": "viewer1"},
    )

    # После on_eventsub_event в _active_ducks должна появиться запись "subscribe"
    # с duration ~8000мс (дефолт из таблицы).
    st = widget_bus.is_ducked("streamer")
    assert st is not None
    assert st.source == "subscribe"
    assert 7000 < widget_bus.remaining_ms() <= 8000


async def test_broadcast_bus_emits_widget_bus(monkeypatch, _no_broadcast):
    """_broadcast_bus шлёт корректное WS-событие через broadcast_log."""
    from app import widget_bus
    captured: list[dict] = []

    async def fake_broadcast_log(payload):
        captured.append(payload)

    # Подменяем _broadcast_bus на свой, который сразу зовёт broadcast_log
    # (вместо ленивого import app.server). Это позволяет тесту работать без
    # поднятого FastAPI-приложения.
    async def patched_broadcast(kind, **kw):
        from app.server import broadcast_log
        await broadcast_log({
            "type": "widget_bus",
            "kind": kind,
            **kw,
        })
    monkeypatch.setattr(widget_bus, "_broadcast_bus", patched_broadcast)
    import app.server as srv
    monkeypatch.setattr(srv, "broadcast_log", fake_broadcast_log)

    widget_bus._reset_for_tests()
    await widget_bus.duck_start("donation", channel="alpha", reason="donation",
                                duration_ms=500, hard_mute=True)
    assert any(p.get("type") == "widget_bus"
               and p.get("kind") == "duck_start"
               and p.get("source") == "donation"
               and p.get("channel") == "alpha"
               and p.get("hard_mute") is True
               for p in captured), captured
