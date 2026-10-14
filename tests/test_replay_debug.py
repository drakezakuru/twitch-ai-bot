"""Tests for v10.4.7 Wave 4.7 — replay debug mode."""

import asyncio
import time

import pytest


def _setup_db(tmp_path, monkeypatch):
    import app.database as db_mod

    db_path = tmp_path / "replay.db"
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)
    monkeypatch.setattr(db_mod, "_shared_db", None)
    db_path.parent.mkdir(parents=True, exist_ok=True)


@pytest.mark.asyncio
async def test_start_end_session(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    from app.replay_debug import start_session, end_session, get_session

    sid = await start_session("test_run", account_id=1, channel="ch", notes="hello")
    assert sid > 0
    s = await get_session(sid)
    assert s["name"] == "test_run"
    assert s["channel"] == "ch"
    assert s["ended_at"] is None
    await end_session(sid)
    s2 = await get_session(sid)
    assert s2["ended_at"] is not None


@pytest.mark.asyncio
async def test_add_event_and_count(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    from app.replay_debug import start_session, add_event, get_session, get_events

    sid = await start_session("t", 1, "ch")
    await add_event(sid, "chat_in", {"user": "a", "text": "hi"}, ts=1000.0)
    await add_event(sid, "bot_out", {"text": "hello"}, ts=1001.0)
    await add_event(sid, "vision_frame", {"text": "elden ring"}, ts=1005.0)

    sess = await get_session(sid)
    assert sess["n_events"] == 3

    events = await get_events(sid)
    assert len(events) == 3
    assert events[0]["kind"] == "chat_in"
    assert events[0]["payload"]["text"] == "hi"


@pytest.mark.asyncio
async def test_filter_kinds(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    from app.replay_debug import start_session, add_event, get_events

    sid = await start_session("t", 1, "ch")
    await add_event(sid, "chat_in", {"x": 1}, ts=1.0)
    await add_event(sid, "bot_out", {"x": 2}, ts=2.0)
    await add_event(sid, "vision_frame", {"x": 3}, ts=3.0)

    only_chat = await get_events(sid, kinds=["chat_in"])
    assert len(only_chat) == 1
    assert only_chat[0]["payload"]["x"] == 1


@pytest.mark.asyncio
async def test_list_sessions_order(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    from app.replay_debug import start_session, list_sessions

    s1 = await start_session("a", 1, "c")
    s2 = await start_session("b", 1, "c")
    sessions = await list_sessions()
    # DESC order: новейший первый
    assert sessions[0]["id"] == s2
    assert sessions[1]["id"] == s1


@pytest.mark.asyncio
async def test_delete_session_removes_events(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    from app.replay_debug import start_session, add_event, delete_session, get_events

    sid = await start_session("t", 1, "c")
    await add_event(sid, "chat_in", {"x": 1})
    await delete_session(sid)
    events = await get_events(sid)
    assert events == []


@pytest.mark.asyncio
async def test_replay_session_yields_events_max_speed(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    from app.replay_debug import start_session, add_event, replay_session

    sid = await start_session("t", 1, "c")
    base = time.time()
    await add_event(sid, "chat_in", {"x": 1}, ts=base)
    await add_event(sid, "bot_out", {"x": 2}, ts=base + 0.1)
    await add_event(sid, "chat_in", {"x": 3}, ts=base + 0.2)

    out = []
    async for ev in replay_session(sid, speed=0):
        out.append(ev)
    assert len(out) == 3
    assert [e["payload"]["x"] for e in out] == [1, 2, 3]


@pytest.mark.asyncio
async def test_replay_session_respects_kinds(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    from app.replay_debug import start_session, add_event, replay_session

    sid = await start_session("t", 1, "c")
    await add_event(sid, "chat_in", {"x": 1}, ts=1.0)
    await add_event(sid, "bot_out", {"x": 2}, ts=2.0)

    out = []
    async for ev in replay_session(sid, speed=0, kinds=["chat_in"]):
        out.append(ev)
    assert len(out) == 1
    assert out[0]["kind"] == "chat_in"
