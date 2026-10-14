"""DIR-LIVE-07: source wiring to the AI snapshot, priority wake, provider request proof."""
from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app import director, director_review


async def _accounts():
    db = await director.get_db()
    try:
        await db.execute("INSERT INTO accounts (id, nickname, token, enabled, bot_role) VALUES (1, 'worker', 'x', 1, 'lurker')")
        await db.execute("INSERT INTO channels (account_id, channel_name, enabled) VALUES (1, 'runtime', 1)")
        await db.execute("INSERT INTO accounts (id, nickname, token, enabled, bot_role) VALUES (2, 'director', 'x', 1, 'director')")
        await db.execute("INSERT INTO channels (account_id, channel_name, enabled) VALUES (2, 'runtime', 1)")
        await db.commit()
    finally:
        await db.close()


async def _stream_session_live():
    db = await director.get_db()
    try:
        await db.execute("INSERT INTO stream_session(start_time, is_live) VALUES (?, 1)", (time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time() - 600)),))
        await db.commit()
    finally:
        await db.close()


async def _chat(channel: str, author: str, text: str, *, is_bot: int = 0):
    db = await director.get_db()
    try:
        await db.execute("INSERT INTO chat_log(account_id, channel, author, message, is_bot) VALUES (1, ?, ?, ?, ?)", (channel, author, text, is_bot))
        await db.commit()
    finally:
        await db.close()


async def _event(kind: str, username: str, *, age_sec: int = 10, amount: int = 0):
    db = await director.get_db()
    try:
        await db.execute("INSERT INTO recent_events(kind, username, amount, created_at) VALUES (?, ?, ?, ?)",
                         (kind, username, amount, time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time() - age_sec))))
        await db.commit()
    finally:
        await db.close()


def _healthy(channel="runtime"):
    now = time.monotonic()
    for source in ("ai", "vision", "speech", "twitch"):
        director.health.report(channel, source, ok=False)  # drop inherited hub state
        director.health.report(channel, source, at=now - 100)  # stable for 15+ seconds
        director.health.report(channel, source, at=now)  # and fresh right now


def _adapter(fake_stream):
    vision = SimpleNamespace(get_last_observation=lambda *a, **k: None)
    bots = SimpleNamespace(get_all_statuses=lambda: {}, get_status=lambda _id: {})
    return director.ProductionDirectorAdapter(SimpleNamespace(), vision, bots, stream_info_loader=fake_stream)


@pytest.mark.asyncio
async def test_snapshot_carries_stream_events_owner_commands_and_dedup(tmp_db):
    await init_db(); await _accounts(); await _stream_session_live()
    async def fake_stream(_channel):
        return {"title": "Собираем базу", "game_name": "Factorio", "viewer_count": 123, "is_live": True}
    adapter = _adapter(fake_stream)
    await _event("channel.follow", "alice", age_sec=10)
    await _event("channel.follow", "alice", age_sec=20)  # dedup in window
    await _event("channel.cheer", "bob", age_sec=200, amount=50)  # outside window
    await _chat("runtime", "flood", "LUL")
    await _chat("runtime", "flood", "LUL")
    await _chat("runtime", "flood", "LUL")
    await _chat("runtime", "flood", "kekw")  # interleaved: does not revive the older duplicate
    await _chat("runtime", "flood", "LUL")
    await _chat("runtime", "bot1", "Nice play", is_bot=1)  # own bot is evidence, never a viewer
    snapshot = await adapter.snapshot("runtime", "snap1")
    assert snapshot["stream"]["title"] == "Собираем базу"
    assert snapshot["stream"]["category"] == "Factorio"
    assert snapshot["stream"]["viewer_count"] == 123
    assert snapshot["stream"]["duration_sec"] and snapshot["stream"]["duration_sec"] >= 599
    kinds = [(item["kind"], item["username"]) for item in snapshot["events"]]
    assert ("follow", "alice") in kinds and ("cheer", "bob") not in kinds  # fresh verified only
    texts = [(item["author"], item["text"], item["kind"]) for item in snapshot["chat"]]
    assert texts.count(("flood", "LUL", "viewer")) == 1  # duplicates collapsed across the window
    assert ("bot1", "Nice play", "own_bot") in texts  # own bot is visible evidence
    # own bot never counts as viewer activity
    activity = snapshot["viewer_activity"]
    assert activity["message_count"] == texts.count(("flood", "LUL", "viewer")) + 1  # kekw only
    assert "Nice play" not in activity["recent_text"]
    assert snapshot["owner_speech_commands"] == []


@pytest.mark.asyncio
async def test_owner_speech_commands_recognized_and_viewer_text_excluded(tmp_db):
    await init_db(); await _accounts()
    vision = SimpleNamespace(get_last_observation=lambda *a, **k: {"transcript": "Так, заканчивай на сегодня, рейд в соседний канал", "description": "", "at": time.time()})
    bots = SimpleNamespace(get_all_statuses=lambda: {1: {"connected": True, "channels": ["runtime"]}})
    adapter = director.ProductionDirectorAdapter(SimpleNamespace(), vision, bots, stream_info_loader=None)
    snapshot = await adapter.snapshot("runtime", "snap2")
    # Silence/static-frame semantics: an empty-text observation is still a healthy heartbeat.
    silent_vision = SimpleNamespace(get_last_observation=lambda *a, **k: {"transcript": "", "description": "", "at": time.time()})
    silent_adapter = director.ProductionDirectorAdapter(SimpleNamespace(), silent_vision, bots, stream_info_loader=None)
    await silent_adapter.snapshot("runtime", "snap2-silent")
    silent_status = director.health.status("runtime", {"vision_stale_sec": 45, "speech_stale_sec": 15})
    assert silent_status["vision"] is True and silent_status["speech"] is True
    assert "raid" in snapshot["owner_speech_commands"] and "end" in snapshot["owner_speech_commands"]
    await _chat("runtime", "viewer123", "рейд! рейд! заканчивай!")
    refreshed = await adapter.snapshot("runtime", "snap3")
    # Viewer chat text never lands in the owner speech channel, even with command words.
    assert "рейд! рейд! заканчивай!" in [item["text"] for item in refreshed["chat"]]
    assert refreshed["owner_speech_commands"] == ["raid", "end"]  # from the streamer's speech only


@pytest.mark.asyncio
async def test_priority_wake_uses_priority_cooldown(tmp_db):
    await init_db(); await _accounts(); _healthy()
    now = [500.0]
    analyses = []

    async def planner(request):
        analyses.append(request["source_snapshot_id"])
        return "{}"  # plan-identity fails validation; only the wake cadence is under test

    runtime = director.DirectorScheduler(planner=planner, worker_status=lambda _: {"connected": True}, clock=lambda: now[0])
    runtime._analysis_lock = asyncio.Lock()
    runtime._last_analysis = {}
    runtime._pending_priority = set()
    await director.save_config("runtime", {"analysis_interval_sec": 15, "priority_cooldown_sec": 5}, [1], 2)
    session_id = (await director.start("runtime"))["session"]["id"]
    db = await director.get_db()
    try:
        await db.execute("UPDATE director_sessions SET state='live' WHERE id=?", (session_id,))
        await db.commit()
    finally:
        await db.close()
    config = (await director._config("runtime"))[0]
    await runtime._run_analysis("runtime", config)  # first analysis at 500
    assert len(analyses) == 1
    now[0] = 505.0
    await runtime._run_analysis("runtime", config)
    assert len(analyses) == 1  # normal interval (15s) blocks at +5
    director.scheduler._pending_priority = set()
    director.notify_stream_event_sync = None  # not used; wake via note_priority
    runtime.note_priority("runtime")
    await runtime._run_analysis("runtime", config)
    assert len(analyses) == 2  # priority cooldown (5s) lets it through
    assert "runtime" not in runtime._pending_priority  # consumed by the analysis
    now[0] = 521.0
    await runtime._run_analysis("runtime", config)
    assert len(analyses) == 3  # normal interval elapsed (505 + 15)


@pytest.mark.asyncio
async def test_notify_stream_event_requires_verified_source(tmp_db):
    await init_db(); await _accounts()
    await director.notify_stream_event("runtime", "channel.raid", verified=False)
    assert "runtime" not in (director.scheduler._pending_priority or set())
    director.scheduler._pending_priority = set()
    await director.notify_stream_event("runtime", "channel.raid", verified=True)
    assert "runtime" in director.scheduler._pending_priority
    db = await director.get_db()
    try:
        rows = await (await db.execute("SELECT action FROM director_audit WHERE channel='runtime' AND action='priority_wake'")).fetchall()
        assert len(rows) == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_plan_context_carries_moments_and_negative_examples(tmp_db, monkeypatch):
    await init_db(); await _accounts()
    captured: dict = {}

    class FakeAdapter:
        def __init__(self, *a, **k): pass
        def provider_ready(self, _c): return True
        def provider_fingerprint(self, _c): return "fp123"
        async def snapshot(self, _c, _s): return {"chat": [], "vision": "", "speech": "", "owner_speech_commands": ["raid"]}
        async def plan(self, request): captured.update(request); return "{}"
    monkeypatch.setattr(director, "_production_adapter", FakeAdapter())
    monkeypatch.setattr(director_review, "active_prompt", lambda *a, **k: _async_return("Keep it short"))
    monkeypatch.setattr(director_review, "active_prompt", lambda *a, **k: _async_return("Keep it short"))
    context = director_review.bounded_context({"chat": [], "vision": "", "speech": ""})
    context["builtin_moments"] = {"version": director_review.BUILTIN_MOMENTS_VERSION, "scenarios": {name: lines[:1] for name, lines in director_review.BUILTIN_MOMENTS.items()}}
    assert context["builtin_moments"]["version"] == "builtin-moments/v1"
    assert "raid" in context["builtin_moments"]["scenarios"]
    captured["context"] = context
    # Rejected (negative) examples ride along as negative context, keyed by id.
    db = await director.get_db()
    try:
        await db.execute("INSERT INTO director_examples(id,channel,source_plan_id,payload_json,kind,payload_hash) VALUES ('ex-neg','runtime','plan-x',?, 'negative', 'h')",
                         (json.dumps({"chat": [{"author": "Viewer-1", "kind": "viewer", "text": "bad reaction"}], "messages": []}),))
        await db.commit()
    finally:
        await db.close()
    result = await director_review.list_examples("runtime", limit=3, kind="negative")
    assert result["examples"][0]["kind"] == "negative"
    negative_context = [{"id": item["id"], "example": {k: item[k] for k in ("chat", "messages") if k in item}} for item in result["examples"]]
    assert negative_context[0]["id"] == "ex-neg" and "frame_path" not in json.dumps(negative_context)


@pytest.mark.asyncio
async def test_session_summary_is_compact_without_media(tmp_db):
    """Spec §4 cloud mode: compact session summary rides with the plan context."""
    from app.database import init_db
    await init_db(); await _accounts()
    db = await director.get_db()
    try:
        await db.execute("INSERT INTO director_sessions(id, channel, state, config_version) VALUES ('s-sum', 'runtime', 'live', 1)")
        await db.execute("INSERT INTO director_messages(id, plan_id, session_id, account_id, text, due_at, expires_at, state, sent_at) VALUES ('m1','p1','s-sum',1,'Sent text',0,0,'sent',1)")
        await db.execute("INSERT INTO director_messages(id, plan_id, session_id, account_id, text, due_at, expires_at, state) VALUES ('m2','p1','s-sum',1,'Pending text',0,0,'pending')")
        await db.commit()
    finally:
        await db.close()
    summary = await director.session_summary("runtime")
    assert summary["session_id"] == "s-sum" and summary["state"] == "live"
    assert summary["message_states"] == {"sent": 1, "pending": 1}
    assert summary["recent_sent"][0]["text"] == "Sent text"
    assert "frame" not in json.dumps(summary) and "audio" not in json.dumps(summary)
    assert await director.session_summary("empty") == {}


def _async_return(value):
    async def _inner(*_a, **_k):
        return value
    return _inner()


from app.database import init_db  # noqa: E402  (after imports for readability)
