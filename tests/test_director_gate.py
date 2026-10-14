"""DIR-LIVE-09 engineering gate: transport failure matrix, restart recovery, two-channel isolation."""
from __future__ import annotations

import asyncio
import json
import time
from uuid import uuid4

import pytest

from app import director
from app.director_plan import DIRECTOR_PLAN_SCHEMA_VERSION


def _healthy(channel="runtime"):
    now = time.monotonic()
    for source in ("ai", "vision", "speech", "twitch"):
        director.health.report(channel, source, ok=False)
        director.health.report(channel, source, at=now - 100)
        director.health.report(channel, source, at=now)


async def _accounts():
    db = await director.get_db()
    try:
        for account_id, role in ((1, 'lurker'), (2, 'director')):
            await db.execute("INSERT INTO accounts (id, nickname, token, enabled, bot_role) VALUES (?, ?, 'x', 1, ?)", (account_id, f'acc{account_id}', role))
            await db.execute("INSERT INTO channels (account_id, channel_name, enabled) VALUES (?, 'runtime', 1)", (account_id,))
        await db.commit()
    finally:
        await db.close()


def _plan(session_id, source_id):
    group_id, message_id = str(uuid4()), str(uuid4())
    return json.dumps({
        "schema_version": DIRECTOR_PLAN_SCHEMA_VERSION, "plan_id": str(uuid4()),
        "channel_id": "runtime", "session_id": session_id, "source_snapshot_id": source_id,
        "explanation": "x", "reaction_level": "small", "reaction_percentage": 0,
        "reaction_count": 1, "assignment_mode": "ai_assigned",
        "groups": [{"group_id": group_id, "text": "Hi", "percentage": 100, "delay_seconds": 1}],
        "individual_messages": [{"message_id": message_id, "group_id": group_id, "bot_id": "1", "text": "Hi", "delay_seconds": 1}],
        "delay_window_seconds": {"min": 1, "max": 1}, "ttl_seconds": 45,
        "template_ids": [], "example_ids": [],
    })


@pytest.mark.asyncio
async def test_provider_timeout_cancel_never_submits(tmp_db):
    from app.database import init_db
    await init_db(); await _accounts(); _healthy()
    now = [100.0]

    async def planner(_request):
        await asyncio.sleep(999)  # simulated provider hang

    runtime = director.DirectorScheduler(planner=planner, worker_status=lambda _: {"connected": True}, clock=lambda: now[0])
    runtime._analysis_lock = asyncio.Lock()
    runtime._last_analysis = {}
    runtime._pending_priority = set()
    await director.save_config("runtime", {}, [1], 2)
    session_id = (await director.start("runtime"))["session"]["id"]
    db = await director.get_db()
    try:
        await db.execute("UPDATE director_sessions SET state='live' WHERE id=?", (session_id,))
        await db.commit()
    finally:
        await db.close()
    task = asyncio.create_task(runtime._run_analysis("runtime", (await director._config("runtime"))[0]))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    db = await director.get_db()
    try:
        plans = await (await db.execute("SELECT count(*) FROM director_plans")).fetchone()
        messages = await (await db.execute("SELECT count(*) FROM director_messages")).fetchone()
        assert plans[0] == 0 and messages[0] == 0  # cancelled transport never submits
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_restart_keeps_paused_session_without_auto_live(tmp_db):
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
    await director.transition("runtime", "pause", reason="ai_errors")
    await director.recover_after_restart()
    db = await director.get_db()
    try:
        row = await (await db.execute("SELECT state, pause_reason, emergency_fence FROM director_sessions WHERE id=?", (session_id,))).fetchone()
        assert tuple(row) == ("paused", "ai_errors", 0)  # no auto-live, reason survives restart
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_two_channel_recovery_is_isolated(tmp_db):
    from app.database import init_db
    await init_db(); await _accounts()
    _healthy()
    async def extra_channel():
        db = await director.get_db()
        try:
            await db.execute("INSERT INTO channels (account_id, channel_name, enabled) VALUES (1, 'other', 1)")
            await db.execute("INSERT INTO channels (account_id, channel_name, enabled) VALUES (2, 'other', 1)")
            await db.commit()
        finally:
            await db.close()
    await extra_channel()
    _healthy("other")
    await director.save_config("runtime", {}, [1], 2)
    await director.save_config("other", {}, [1], 2)
    first = (await director.start("runtime"))["session"]["id"]
    second = (await director.start("other"))["session"]["id"]
    await director.transition("runtime", "pause", reason="offline")
    await director.recover_after_restart()
    db = await director.get_db()
    try:
        rows = await (await db.execute("SELECT channel, state, pause_reason FROM director_sessions")).fetchall()
        by_channel = {row[0]: (row[1], row[2]) for row in rows}
        # No auto-live after restart; the paused session keeps its reason, the other just parks.
        assert by_channel["runtime"] == ("paused", "offline")
        assert by_channel["other"][0] == "paused"
    finally:
        await db.close()
