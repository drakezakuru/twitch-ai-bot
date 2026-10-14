"""DIR-LIVE-10 offline provider transport matrix: timeout/auth/429/malformed fail closed.

Covers the offline half of the matrix (fake transports through the production
planner->submit path); the real-transport sweep stays in DIR-LIVE-10 acceptance.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from app import director


def _healthy(channel="runtime"):
    now = time.monotonic()
    for source in ("ai", "vision", "speech", "twitch"):
        director.health.report(channel, source, ok=False)
        director.health.report(channel, source, at=now - 100)
        director.health.report(channel, source, at=now)


async def _accounts():
    db = await director.get_db()
    try:
        for account_id, role in ((1, "lurker"), (2, "director")):
            await db.execute("INSERT INTO accounts (id, nickname, token, enabled, bot_role) VALUES (?, ?, 'x', 1, ?)", (account_id, f"acc{account_id}", role))
            await db.execute("INSERT INTO channels (account_id, channel_name, enabled) VALUES (?, 'runtime', 1)", (account_id,))
        await db.commit()
    finally:
        await db.close()


def _failure(kind: str):
    if kind == "timeout":
        async def planner(_request):
            raise asyncio.TimeoutError("provider timeout")
    elif kind == "auth":
        async def planner(_request):
            raise RuntimeError("401 unauthorized")
    elif kind == "rate":
        async def planner(_request):
            raise RuntimeError("429 rate limited")
    else:  # malformed
        async def planner(_request):
            return "definitely not a plan json {{{"
    return planner


async def _setup_live():
    await director.save_config("runtime", {}, [1], 2)
    session_id = (await director.start("runtime"))["session"]["id"]
    db = await director.get_db()
    try:
        await db.execute("UPDATE director_sessions SET state='live' WHERE id=?", (session_id,))
        await db.commit()
    finally:
        await db.close()
    return session_id


async def _state_and_counts():
    db = await director.get_db()
    try:
        state = await (await db.execute("SELECT state, pause_reason FROM director_sessions WHERE channel='runtime'")).fetchone()
        plans = await (await db.execute("SELECT count(*) FROM director_plans")).fetchone()
        messages = await (await db.execute("SELECT count(*) FROM director_messages")).fetchone()
        return tuple(state), plans[0], messages[0]
    finally:
        await db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["timeout", "auth", "rate", "malformed"])
async def test_transport_failures_count_and_fail_closed(tmp_db, kind):
    from app.database import init_db
    await init_db()
    await _accounts()
    _healthy()
    session_id = await _setup_live()
    runtime = director.DirectorScheduler(planner=_failure(kind), worker_status=lambda _: {"connected": True}, clock=lambda: 100.0)
    runtime._analysis_lock = asyncio.Lock()
    runtime._last_analysis = {}
    runtime._pending_priority = set()
    runtime._ai_errors = {}
    config = (await director._config("runtime"))[0]
    await runtime._run_analysis("runtime", config)  # must not raise: production path reports instead
    assert runtime._ai_errors["runtime"] == 1
    state, plans, messages = await _state_and_counts()
    assert state[0] == "live"  # one failure is below the default limit
    assert plans == 0 and messages == 0  # nothing was submitted
    assert session_id  # session still alive


@pytest.mark.asyncio
async def test_consecutive_failures_pause_and_cancel(tmp_db):
    from app.database import init_db
    await init_db()
    await _accounts()
    _healthy()
    session_id = await _setup_live()
    now = [100.0]
    runtime = director.DirectorScheduler(planner=_failure("auth"), worker_status=lambda _: {"connected": True}, clock=lambda: now[0])
    runtime._analysis_lock = asyncio.Lock()
    runtime._last_analysis = {}
    runtime._pending_priority = set()
    runtime._ai_errors = {}
    config = (await director._config("runtime"))[0]
    limit = config["ai_error_limit"]
    for _ in range(limit):
        now[0] += 10_000.0  # cooldown gate: каждый вызов обязан выполниться
        await runtime._run_analysis("runtime", config)
    state, plans, messages = await _state_and_counts()
    assert state == ("paused", "ai_errors")  # N consecutive failures pause the session
    assert plans == 0 and messages == 0  # pending messages cancelled, nothing submitted
    assert session_id
