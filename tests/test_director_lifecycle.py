"""DIR-LIVE-06: lifecycle table, offline grace, manual raid/end, worker safety."""
from __future__ import annotations

import asyncio
import json
import time
from uuid import uuid4

import pytest

from app import director
from app.database import get_db
from app.director_plan import DIRECTOR_PLAN_SCHEMA_VERSION


@pytest.fixture
def storage_root(tmp_path, monkeypatch):
    monkeypatch.setattr(director, "DATA_ROOT", tmp_path / "storage")
    return tmp_path / "storage"


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


def _plan(session_id, source_id, bot_id="1", channel="runtime"):
    group_id, message_id = str(uuid4()), str(uuid4())
    return json.dumps({
        "schema_version": DIRECTOR_PLAN_SCHEMA_VERSION, "plan_id": str(uuid4()),
        "channel_id": channel, "session_id": session_id, "source_snapshot_id": source_id,
        "explanation": "A visible moment", "reaction_level": "small", "reaction_percentage": 0,
        "reaction_count": 1, "assignment_mode": "ai_assigned",
        "groups": [{"group_id": group_id, "text": "Nice play", "percentage": 100, "delay_seconds": 1}],
        "individual_messages": [{"message_id": message_id, "group_id": group_id, "bot_id": bot_id, "text": "Nice play", "delay_seconds": 1}],
        "delay_window_seconds": {"min": 1, "max": 1}, "ttl_seconds": 45,
        "template_ids": [], "example_ids": [],
    })


def _healthy(channel="runtime", at=None, reset=True):
    clock = getattr(director.health, "_clock", time.monotonic)
    base = clock() if at is None else at
    for source in ("ai", "vision", "speech", "twitch"):
        if reset:
            director.health.report(channel, source, ok=False)  # drop inherited hub state
        director.health.report(channel, source, at=base - 100)  # stable for 15+ seconds
        director.health.report(channel, source, at=base)  # and fresh right now


async def _pause_reason(channel="runtime"):
    db = await director.get_db()
    try:
        row = await (await db.execute("SELECT state, pause_reason FROM director_sessions WHERE channel=?", (channel,))).fetchone()
        return (row[0], row[1]) if row else None
    finally:
        await db.close()


def _cleanup_global():
    scheduler = director.scheduler
    scheduler.clock = time.monotonic
    scheduler.configure(planner=None, worker_status=None, sender=None)
    scheduler._offline_at = {}
    scheduler._finalize_at = {}
    scheduler._manual_previews = {}
    scheduler._emergency_dry_runs = {}


@pytest.mark.asyncio
async def test_pause_reasons_drive_resume_rules(tmp_db):
    from app.database import init_db
    await init_db(); await _accounts(); _healthy()
    await director.save_config("runtime", {}, [1], 2)
    session_id = (await director.start("runtime"))["session"]["id"]
    db = await director.get_db()
    try:
        await db.execute("UPDATE director_sessions SET state='live' WHERE id=?", (session_id,))
        await db.commit()
    finally:
        await db.close()
    # Manual pause resumes on health alone.
    await director.transition("runtime", "pause")
    assert (await _pause_reason()) == ("paused", "manual")
    _healthy()
    await director.transition("runtime", "resume")
    # AI-error pause requires a valid dry-run (spec §4).
    db = await director.get_db()
    try:
        await db.execute("UPDATE director_sessions SET state='live', pause_reason=NULL WHERE id=?", (session_id,))
        await db.commit()
    finally:
        await db.close()
    await director.transition("runtime", "pause", reason="ai_errors")
    _healthy()
    with pytest.raises(ValueError, match="ai_pause_requires_dry_run"):
        await director.transition("runtime", "resume")
    async def fake_planner(request):
        return _plan(session_id, request["source_snapshot_id"])
    try:
        director.scheduler.configure(planner=fake_planner, worker_status=lambda _: {"connected": True})
        await director.scheduler.emergency_dry_run("runtime")
        await director.transition("runtime", "resume")
    finally:
        _cleanup_global()


@pytest.mark.asyncio
async def test_offline_grace_reconnect_and_finalization(tmp_db, monkeypatch):
    from app.database import init_db
    from app.database import get_db as _get_db  # noqa: F401  (same proxy)
    await init_db(); await _accounts()
    now = [1000.0]
    monkeypatch.setattr(director, "health", director.SourceHealthHub(clock=lambda: now[0]))
    _healthy(at=1000)
    director.scheduler.clock = lambda: now[0]
    director.scheduler._offline_at = {}
    director.scheduler._finalize_at = {}
    try:
        await director.save_config("runtime", {"ttl_sec": 45}, [1], 2)
        session_id = (await director.start("runtime"))["session"]["id"]
        db = await director.get_db()
        try:
            await db.execute("UPDATE director_sessions SET state='live' WHERE id=?", (session_id,))
            await db.commit()
        finally:
            await db.close()
        await director.transcript_append("runtime", session_id, [{"at": 1.0, "source_id": "7", "text": "до оффлайна"}])
        await director.handle_stream_lifecycle("runtime", online=False)
        assert (await _pause_reason()) == ("paused", "offline")
        # Pending joins revoked, plans fenced immediately, transcript still open.
        db = await director.get_db()
        try:
            join_state = await (await db.execute("SELECT state FROM director_worker_state WHERE session_id=?", (session_id,))).fetchone()
            assert join_state[0] == "revoked"
        finally:
            await db.close()
        status = await director.transcript_status("runtime", session_id)
        assert status["state"] == "recording"
        # Reconnect within grace: twitch freshness restarts, so auto-resume waits for 15s stable.
        now[0] = 1050.0
        await director.handle_stream_lifecycle("runtime", online=True)
        _healthy(at=1060, reset=False)  # fresh heartbeats; reconnect stability window is kept
        await director.scheduler._offline_lifecycle(now[0])
        assert (await _pause_reason()) == ("paused", "offline")
        now[0] = 1066.0
        await director.scheduler._offline_lifecycle(now[0])
        assert (await _pause_reason())[0] == "warming"
        # Fresh session; grace expiry without reconnect finalizes honestly.
        db = await director.get_db()
        try:
            await db.execute("UPDATE director_sessions SET state='live', pause_reason=NULL WHERE id=?", (session_id,))
            await db.commit()
        finally:
            await db.close()
        await director.handle_stream_lifecycle("runtime", online=False)
        now[0] = 1066.0 + 61  # the repeated offline at 1066 restarted the grace window
        await director.scheduler._offline_lifecycle(now[0])
        assert (await _pause_reason())[0] == "stopped"
        assert (await director.transcript_status("runtime", session_id))["state"] == "closed"
        # Finalization stamps closed_at on the session row (§05: sessions close).
        db = await director.get_db()
        try:
            closed_at = await (await db.execute("SELECT closed_at FROM director_sessions WHERE id=?", (session_id,))).fetchone()
        finally:
            await db.close()
        assert closed_at[0] is not None
        # A late reconnect event cannot resurrect the finalized session.
        db = await director.get_db()
        try:
            await db.execute("INSERT INTO director_audit(channel, session_id, action, result, details_json) VALUES ('runtime', NULL, 'marker', 'ok', '{}')")
            await db.commit()
        finally:
            await db.close()
        before = len((await director.list_audit("runtime"))["entries"])
        await director.handle_stream_lifecycle("runtime", online=True)
        assert len((await director.list_audit("runtime"))["entries"]) == before
    finally:
        _cleanup_global()


@pytest.mark.asyncio
async def test_manual_raid_and_end_without_twitch_raid_api(tmp_db, storage_root):
    from app.database import init_db
    await init_db(); await _accounts(); _healthy()
    now = [2000.0]
    sent = []

    async def sender(account_id, channel, text):
        sent.append((account_id, channel, text))
        return {"ok": True}

    director.scheduler.clock = lambda: now[0]
    director.scheduler._offline_at = {}
    director.scheduler._finalize_at = {}
    director.scheduler._manual_previews = {}
    try:
        await director.save_config("runtime", {"ttl_sec": 2, "send_delay_min_sec": 1, "send_delay_max_sec": 1}, [1], 2)
        session_id = (await director.start("runtime"))["session"]["id"]
        await director.transcript_append("runtime", session_id, [{"at": 1.0, "source_id": "7", "text": "момент для реакции"}])
        db = await director.get_db()
        try:
            await db.execute("UPDATE director_sessions SET state='live' WHERE id=?", (session_id,))
            await db.commit()
        finally:
            await db.close()

        async def fake_planner(request):
            return _plan(session_id, request["source_snapshot_id"])

        director.scheduler.configure(planner=fake_planner, worker_status=lambda _: {"connected": True}, sender=sender)
        preview = await director.scheduler.manual_plan_preview("runtime", "raid")
        assert preview["messages"] and preview["messages"][0]["text"] == "Nice play"
        db = await get_db()
        try:
            plans_before = (await (await db.execute("SELECT count(*) FROM director_plans")).fetchone())[0]
            assert plans_before == 0  # preview never persists
        finally:
            await db.close()
        confirmed = await director.scheduler.manual_plan_confirm("runtime", "raid")
        assert confirmed["plan_id"]
        assert (await _pause_reason())[0] == "live"  # raid does not stop the session
        await director.scheduler._dispatch_due(now[0] + 2)
        assert sent and sent[0] == (1, "runtime", "Nice play")  # chat send only, no Twitch raid API
        # Manual End: preview → confirm → final reaction, then stop after the valid tail.
        end_preview = await director.scheduler.manual_plan_preview("runtime", "end")
        assert end_preview["messages"]
        await director.scheduler.manual_plan_confirm("runtime", "end")
        assert (await _pause_reason())[0] == "live"  # the final tail is still dispatching
        now[0] = 2000.0 + 3
        await director.scheduler._tick()
        assert (await _pause_reason())[0] == "stopped"
        assert (await director.transcript_status("runtime", session_id))["state"] == "closed"
        with pytest.raises(ValueError, match="manual_preview_expired"):
            await director.scheduler.manual_plan_confirm("runtime", "raid")
    finally:
        _cleanup_global()


@pytest.mark.asyncio
async def test_worker_conflicts_and_ttl_expiry(tmp_db):
    from app.database import init_db
    await init_db(); await _accounts(); _healthy()
    now = [3000.0]
    sent = []

    async def sender(account_id, channel, text):
        sent.append((account_id, channel, text))
        return {"ok": True}

    runtime = director.DirectorScheduler(sender=sender, worker_status=lambda _: {"connected": True}, clock=lambda: now[0])
    await director.save_config("runtime", {"ttl_sec": 5, "send_delay_min_sec": 1, "send_delay_max_sec": 2}, [1], 2)
    session_id = (await director.start("runtime"))["session"]["id"]
    db = await director.get_db()
    try:
        await db.execute("UPDATE director_sessions SET state='live' WHERE id=?", (session_id,))
        await db.commit()
    finally:
        await db.close()
    source1 = str(uuid4())
    await runtime.submit_response("runtime", _plan(session_id, source1), source_snapshot_id=source1)
    # The worker is now busy in plan 1; plan 2 must not reuse it (spec §9).
    source2 = str(uuid4())
    plan2_id = await runtime.submit_response("runtime", _plan(session_id, source2), source_snapshot_id=source2)
    db = await director.get_db()
    try:
        row = await (await db.execute("SELECT status, payload_json FROM director_plans WHERE id=?", (plan2_id,))).fetchone()
        assert row is not None and row[0] in {"partial", "rejected"}  # no worker to execute it
        payload = json.loads(row[1])
        assert payload["messages"] == []
        rejected_reasons = [part["reason"] for part in payload["rejected"]]
        assert "worker_not_available_in_snapshot" in rejected_reasons, rejected_reasons
        pending = await (await db.execute("SELECT state FROM director_messages WHERE state='pending'")).fetchall()
        assert len(pending) == 1  # only plan 1 has a live message
    finally:
        await db.close()
    # Expired tail is cancelled by TTL, never sent; plan 2 produced no messages (busy worker).
    now[0] = 3000.0 + 6
    await runtime._dispatch_due(now[0])
    db = await director.get_db()
    try:
        states = await (await db.execute("SELECT state, count(*) FROM director_messages GROUP BY state")).fetchall()
        assert dict(states) == {"cancelled": 1}
        assert sent == []
    finally:
        await db.close()

@pytest.mark.asyncio
async def test_pause_freezes_tail_until_original_ttl(tmp_db):
    """Spec §pause: pending messages survive a pause longer than the remaining TTL."""
    from app.database import init_db
    await init_db(); await _accounts(); _healthy()
    now = [5000.0]
    sent = []

    async def sender(account_id, channel, text):
        sent.append((account_id, channel, text))
        return {"ok": True}

    director.scheduler.clock = lambda: now[0]
    director.scheduler.configure(sender=sender, worker_status=lambda _: {"connected": True})
    runtime = director.scheduler
    await director.save_config("runtime", {"ttl_sec": 10, "send_delay_min_sec": 1, "send_delay_max_sec": 2}, [1], 2)
    session_id = (await director.start("runtime"))["session"]["id"]
    db = await director.get_db()
    try:
        await db.execute("UPDATE director_sessions SET state='live' WHERE id=?", (session_id,))
        await db.commit()
    finally:
        await db.close()
    source1 = str(uuid4())
    await runtime.submit_response("runtime", _plan(session_id, source1), source_snapshot_id=source1)
    # Pause, then let more than the whole TTL pass while paused.
    await director.transition("runtime", "pause", reason="manual")
    now[0] = 5000.0 + 30  # > ttl_sec: without freezing the tail would be expired here
    await runtime._dispatch_due(now[0])
    await director.transition("runtime", "resume")
    db = await director.get_db()
    try:
        await db.execute("UPDATE director_sessions SET state='live' WHERE id=?", (session_id,))
        await db.commit()
    finally:
        await db.close()
    now[0] = 5000.0 + 30 + 1  # due again after resume; tail must still be pending
    db = await director.get_db()
    try:
        dbg = await (await db.execute("SELECT state, due_at, expires_at FROM director_messages")).fetchall()
        print("DBG:", [dict(r) for r in dbg])
    finally:
        await db.close()
    await runtime._dispatch_due(now[0])
    assert sent, "frozen tail must send after resume"
    db = await director.get_db()
    try:
        rows = await (await db.execute("SELECT state FROM director_messages")).fetchall()
        assert all(row[0] == "sent" for row in rows)
    finally:
        await db.close()
    # But the shifted expiry still cancels a tail that is never delivered in time.
    source2 = str(uuid4())
    await runtime.submit_response("runtime", _plan(session_id, source2), source_snapshot_id=source2)
    now[0] = 5000.0 + 30 + 1 + 30  # beyond the shifted TTL headroom
    await runtime._dispatch_due(now[0])
    db = await director.get_db()
    try:
        rows = await (await db.execute("SELECT state, count(*) FROM director_messages WHERE state='cancelled'")).fetchall()
        assert rows and rows[0][1] >= 1
    finally:
        await db.close()
    _cleanup_global()

@pytest.mark.asyncio
async def test_plan_audit_details_carry_level_and_sources(tmp_db):
    """Spec §13: audit for a plan includes sources/level/delays/TTL, not only the payload."""
    from app.database import init_db
    await init_db(); await _accounts(); _healthy()
    now = [7000.0]
    director.scheduler.clock = lambda: now[0]
    director.scheduler.configure(worker_status=lambda _: {"connected": True})
    try:
        await director.save_config("runtime", {"ttl_sec": 45}, [1], 2)
        session_id = (await director.start("runtime"))["session"]["id"]
        db = await director.get_db()
        try:
            await db.execute("UPDATE director_sessions SET state='live' WHERE id=?", (session_id,))
            await db.commit()
        finally:
            await db.close()
        source1 = str(uuid4())
        await director.scheduler.submit_response("runtime", _plan(session_id, source1), source_snapshot_id=source1)
        entries = (await director.list_audit("runtime"))["entries"]
        plan_entry = next(item for item in entries if item["action"] == "plan")
        details = plan_entry["details"]
        assert details["ttl_sec"] == 45 and details["reaction_level"] == "small"
        assert details["sources"] == {"ai": True, "vision": True, "speech": True, "twitch": True}
        assert details["source_snapshot_id"] == source1
    finally:
        _cleanup_global()


@pytest.mark.asyncio
async def test_send_failure_retries_same_account_until_ttl(tmp_db):
    """Spec §9: a failed send retries the same account until TTL, then errors."""
    from app.database import init_db
    await init_db(); await _accounts(); _healthy()
    now = [6000.0]
    calls = []
    sent = []

    async def flaky_sender(account_id, channel, text):
        calls.append(account_id)
        if len(calls) == 1:
            return {"ok": False, "error": "timeout"}
        sent.append((account_id, text))
        return {"ok": True}

    director.scheduler.clock = lambda: now[0]
    director.scheduler.configure(sender=flaky_sender, worker_status=lambda _: {"connected": True})
    try:
        await director.save_config("runtime", {"ttl_sec": 10, "send_delay_min_sec": 1, "send_delay_max_sec": 2}, [1], 2)
        session_id = (await director.start("runtime"))["session"]["id"]
        db = await director.get_db()
        try:
            await db.execute("UPDATE director_sessions SET state='live' WHERE id=?", (session_id,))
            await db.commit()
        finally:
            await db.close()
        source1 = str(uuid4())
        await director.scheduler.submit_response("runtime", _plan(session_id, source1), source_snapshot_id=source1)
        await director.scheduler._dispatch_due(now[0] + 2)  # first attempt fails, stays pending
        db = await director.get_db()
        try:
            state = await (await db.execute("SELECT state FROM director_messages")).fetchall()
            assert all(row[0] == "pending" for row in state)  # retriable before TTL
        finally:
            await db.close()
        now[0] = 6000.0 + 4
        await director.scheduler._dispatch_due(now[0])  # retry succeeds on the same account
        assert sent and sent[0][0] == 1  # same account, no reassignment
        db = await director.get_db()
        try:
            row = await (await db.execute("SELECT state FROM director_messages")).fetchone()
            assert row[0] == "sent"
        finally:
            await db.close()
        # Expired message never retries: TTL wins.
        source2 = str(uuid4())
        await director.scheduler.submit_response("runtime", _plan(session_id, source2), source_snapshot_id=source2)
        now[0] = 6000.0 + 2 + 40
        await director.scheduler._dispatch_due(now[0])
        db = await director.get_db()
        try:
            rows = await (await db.execute("SELECT state, count(*) FROM director_messages GROUP BY state")).fetchall()
            states = {row[0]: row[1] for row in rows}
            assert states.get("cancelled", 0) == 1 and states.get("sent", 0) == 1
        finally:
            await db.close()
    finally:
        _cleanup_global()

@pytest.mark.asyncio
async def test_chant_dictionary_session_vs_permanent(tmp_db):
    """Spec §8: owner chants are permanent; AI chants die with the session until approved."""
    from app.database import init_db
    await init_db(); await _accounts()
    added = await director.chant_add("runtime", "LETS GOOO", source="owner")
    assert added["source"] == "owner" and added["session_id"] is None
    ai = await director.chant_add("runtime", "POGCHAMP", source="ai", session_id="sess-1")
    assert ai["session_id"] == "sess-1"
    # Session AI chant exempts duplicates for that session only.
    texts = await director._chant_texts("runtime", "sess-1")
    assert {"lets gooo", "pogchamp"} <= texts
    assert "pogchamp" not in await director._chant_texts("runtime", "sess-OTHER")
    # Owner approval makes it permanent (session-independent).
    await director.chant_approve("runtime", ai["id"])
    texts = await director._chant_texts("runtime", "sess-OTHER")
    assert "pogchamp" in texts
    listing = await director.chant_list("runtime")
    assert {item["source"] for item in listing["chants"]} == {"owner"}
    await director.chant_delete("runtime", added["id"])
    assert await director._chant_texts("runtime", "sess-1") == frozenset({"pogchamp"})
    # Unsafe chant text is refused.
    with pytest.raises(ValueError):
        await director.chant_add("runtime", "SELECT * FROM users", source="owner")
    with pytest.raises(ValueError):
        await director.chant_add("runtime", "email me at bot@example.com", source="owner")

@pytest.mark.asyncio
async def test_cross_plan_busy_worker_is_global(tmp_db):
    """Spec §9: a worker busy in one session is excluded from plans of other sessions too."""
    from app.database import init_db
    await init_db(); await _accounts()
    db = await director.get_db()
    try:
        # Worker 1 is shared between two channels: runtime (existing) and other.
        await db.execute("INSERT INTO channels (account_id, channel_name, enabled) VALUES (1, 'other', 1)")
        await db.execute("INSERT INTO accounts (id, nickname, token, enabled, bot_role) VALUES (3, 'director2', 'x', 1, 'director')")
        await db.execute("INSERT INTO channels (account_id, channel_name, enabled) VALUES (3, 'other', 1)")
        await db.commit()
    finally:
        await db.close()
    now = [4000.0]
    runtime = director.DirectorScheduler(worker_status=lambda _: {"connected": True}, clock=lambda: now[0])
    _healthy()
    _healthy(channel="other")
    await director.save_config("runtime", {"ttl_sec": 45}, [1], 2)
    await director.save_config("other", {"ttl_sec": 45}, [1], 3)
    sid1 = (await director.start("runtime"))["session"]["id"]
    sid2 = (await director.start("other"))["session"]["id"]
    db = await director.get_db()
    try:
        await db.execute("UPDATE director_sessions SET state='live' WHERE id IN (?, ?)", (sid1, sid2))
        await db.commit()
    finally:
        await db.close()
    source1 = str(uuid4())
    await runtime.submit_response("runtime", _plan(sid1, source1), source_snapshot_id=source1)
    # Same worker, different session/channel: plan must get no usable worker.
    source2 = str(uuid4())
    plan2_id = await runtime.submit_response("other", _plan(sid2, source2, channel="other"), source_snapshot_id=source2)
    db = await director.get_db()
    try:
        row = await (await db.execute("SELECT status, payload_json FROM director_plans WHERE id=?", (plan2_id,))).fetchone()
        assert row is not None and row[0] in {"partial", "rejected"}
        payload = json.loads(row[1])
        assert payload["messages"] == []
        assert "worker_not_available_in_snapshot" in [part["reason"] for part in payload["rejected"]]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_join_now_idempotent_and_reconnect_keeps_delay(tmp_db):
    from app.database import init_db
    await init_db(); await _accounts(); _healthy()
    connects = []

    async def connector(account_id, channel):
        connects.append(account_id)
        return True

    runtime = director.DirectorScheduler(worker_status=lambda _: {"connected": False}, worker_connector=connector, clock=lambda: 500.0)
    await director.save_config("runtime", {}, [1], 2)
    session_id = (await director.start("runtime"))["session"]["id"]
    db = await director.get_db()
    try:
        row = await (await db.execute("SELECT state, join_at FROM director_worker_state WHERE session_id=?", (session_id,))).fetchone()
        assert row[0] == "scheduled" and row[1] > 500.0  # random 0–30 min delay
        original_join_at = row[1]
        await runtime.join_now("runtime", 1)
        await runtime.join_now("runtime", 1)
        assert connects.count(1) == 1  # second request is a no-op
        row = await (await db.execute("SELECT state, join_at FROM director_worker_state WHERE session_id=?", (session_id,))).fetchone()
        assert tuple(row) == ("connecting", original_join_at)
        # Connection drops: reconcile returns to connecting, no new join delay.
        db2 = await director.get_db()
        try:
            await db2.execute("UPDATE director_worker_state SET state='online' WHERE session_id=?", (session_id,))
            await db2.commit()
        finally:
            await db2.close()
        await runtime._reconcile_workers()
        row = await (await db.execute("SELECT state, join_at FROM director_worker_state WHERE session_id=?", (session_id,))).fetchone()
        assert row[0] == "connecting" and row[1] == original_join_at
    finally:
        await db.close()
