import json
import time
from uuid import uuid4

import pytest

from app import director
from app.director_plan import DIRECTOR_PLAN_SCHEMA_VERSION


async def _lurker():
    db = await director.get_db()
    try:
        await db.execute("INSERT INTO accounts (id, nickname, token, enabled, bot_role) VALUES (1, 'worker', 'x', 1, 'lurker')")
        await db.execute("INSERT INTO channels (account_id, channel_name, enabled) VALUES (1, 'runtime', 1)")
        await db.execute("INSERT INTO accounts (id, nickname, token, enabled, bot_role) VALUES (2, 'director', 'x', 1, 'director')")
        await db.execute("INSERT INTO channels (account_id, channel_name, enabled) VALUES (2, 'runtime', 1)")
        await db.commit()
    finally:
        await db.close()


def _plan(session_id, source_id):
    group_id, message_id = str(uuid4()), str(uuid4())
    return json.dumps({
        "schema_version": DIRECTOR_PLAN_SCHEMA_VERSION, "plan_id": str(uuid4()),
        "channel_id": "runtime", "session_id": session_id, "source_snapshot_id": source_id,
        "explanation": "A visible moment", "reaction_level": "small", "reaction_percentage": 0,
        "reaction_count": 1, "assignment_mode": "ai_assigned",
        "groups": [{"group_id": group_id, "text": "Nice play", "percentage": 100, "delay_seconds": 1}],
        "individual_messages": [{"message_id": message_id, "group_id": group_id, "bot_id": "1", "text": "Nice play", "delay_seconds": 1}],
        "delay_window_seconds": {"min": 1, "max": 1}, "ttl_seconds": 2,
        "template_ids": [], "example_ids": [],
    })


@pytest.mark.asyncio
async def test_live_plan_is_immutable_idempotent_and_emergency_fenced(tmp_db):
    from app.database import init_db
    await init_db(); await _lurker()
    now = [100.0]
    sent = []

    async def sender(account_id, channel, text):
        sent.append((account_id, channel, text))
        return {"ok": True}

    runtime = director.DirectorScheduler(sender=sender, worker_status=lambda _: {"connected": True}, clock=lambda: now[0])
    await director.save_config("runtime", {"mode": "live", "send_delay_min_sec": 1, "send_delay_max_sec": 1, "ttl_sec": 2}, [1], 2)
    for source in ("ai", "vision", "speech", "twitch"):
        director.health.report("runtime", source, at=time.monotonic())
    session_id = (await director.start("runtime"))["session"]["id"]
    db = await director.get_db()
    try:
        await db.execute("UPDATE director_sessions SET state='live' WHERE id=?", (session_id,))
        await db.commit()
    finally:
        await db.close()
    source_id = str(uuid4())
    response = _plan(session_id, source_id)
    plan_id = await runtime.submit_response("runtime", response, source_snapshot_id=source_id)
    assert plan_id
    assert await runtime.submit_response("runtime", response, source_snapshot_id=source_id) is None  # duplicate plan identity cannot be persisted
    now[0] = 101.0
    await runtime._dispatch_due(now[0])
    await runtime._dispatch_due(now[0])
    assert sent == [(1, "runtime", "Nice play")]

    # A pending message cannot cross an emergency fence even if it was already due.
    source_id = str(uuid4())
    second = json.loads(_plan(session_id, source_id)); second["plan_id"] = str(uuid4())
    second["individual_messages"][0]["message_id"] = str(uuid4())
    await runtime.submit_response("runtime", json.dumps(second), source_snapshot_id=source_id)
    await director.transition("runtime", "emergency")
    await runtime._dispatch_due(now[0] + 1)
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_worker_role_revocation_cancels_unsent_message(tmp_db):
    from app.database import init_db
    await init_db(); await _lurker()
    db = await director.get_db()
    try:
        await director.ensure_schema(db)
    finally:
        await db.close()
    db = await director.get_db()
    try:
        await db.execute("INSERT INTO director_messages(id, plan_id, session_id, account_id, text, due_at, expires_at) VALUES ('m', 'p', 's', 1, 'x', 0, 99)")
        await db.commit()
    finally:
        await db.close()
    assert await director.revoke_worker(1) == 1
    db = await director.get_db()
    try:
        assert (await (await db.execute("SELECT state FROM director_messages WHERE id='m'")).fetchone())[0] == "cancelled"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_warming_survives_ai_heartbeat_expiry_until_first_analysis(tmp_db):
    """DIR-LIVE-10 regression: the 30s warm window exceeds the 15s ai freshness, but no
    plan has been attempted during warm-up — a stale ai mark must not pause the session
    before its first analysis; the heartbeat is reseeded at the warming→suggest move."""
    from app.database import init_db
    await init_db(); await _lurker()
    now = [300.0]
    runtime = director.DirectorScheduler(
        sender=None,
        worker_status=lambda _: {"connected": True},
        clock=lambda: now[0],
    )

    async def refresher(request):
        for source in ("vision", "speech", "twitch"):
            director.health.report(request["channel"], source, at=time.monotonic())

    runtime.source_refresher = refresher
    await director.save_config("runtime", {"mode": "suggest"}, [1], 2)
    for source in ("ai", "vision", "speech", "twitch"):
        director.health.report("runtime", source, at=time.monotonic())
    session_id = (await director.start("runtime"))["session"]["id"]

    async def _state():
        db = await director.get_db()
        try:
            row = await (await db.execute("SELECT state FROM director_sessions WHERE id=?", (session_id,))).fetchone()
            return row[0]
        finally:
            await db.close()

    now[0] += 16  # ai mark (15s) is already stale here; warm window (30s) is still running
    await runtime._tick()
    assert await _state() == "warming"  # must NOT be paused before the first analysis

    now[0] += 16  # anchor age 16s: still warming, ai still exempt
    await runtime._tick()
    assert await _state() == "warming"
    now[0] += 16  # anchor age 32s: warming → suggest, ai heartbeat reseeded
    await runtime._tick()
    state = await _state()
    assert state == "suggest"

    await runtime._tick()  # next tick must run, not pause: ai was reseeded at the move
    assert await _state() == "suggest"


@pytest.mark.asyncio
async def test_resume_seeds_ai_from_provider_proof_not_runtime_heartbeat(tmp_db, monkeypatch):
    """DIR-LIVE-10 regression: while paused no plan runs, so a runtime ai heartbeat
    cannot exist; resume must judge ai by the verified provider proof instead of
    deadlocking on sources_not_stable forever."""
    from app.database import init_db
    from app import director_review
    await init_db(); await _lurker()
    now = [400.0]
    runtime = director.DirectorScheduler(sender=None, worker_status=lambda _: {"connected": True}, clock=lambda: now[0])

    async def refresher(request):
        for source in ("vision", "speech", "twitch"):
            director.health.report(request["channel"], source, at=time.monotonic())

    runtime.source_refresher = refresher
    await director.save_config("runtime", {"mode": "suggest"}, [1], 2)
    for source in ("ai", "vision", "speech", "twitch"):
        director.health.report("runtime", source, at=time.monotonic())
    await director.start("runtime")
    await director.transition("runtime", "pause", reason="sources")
    now[0] += 60  # long pause: any runtime ai mark would be stale by now
    await runtime._tick()

    class _Adapter:
        def provider_ready(self, config):
            return True

    async def _proof_ok(channel, config, version):
        return {"ok": True}

    monkeypatch.setattr(director, "_production_adapter", _Adapter())
    monkeypatch.setattr(director_review, "active_prompt", _proof_ok)
    # Continuous production ticks keep vision/speech/twitch healthy since long ago;
    # emulate that 15s stability window without sleeping.
    for source in ("vision", "speech", "twitch"):
        director.health._healthy_since[("runtime", source)] = time.monotonic() - 20

    await director.transition("runtime", "resume")
    assert (await director.get_status("runtime"))["session"]["state"] == "warming"
