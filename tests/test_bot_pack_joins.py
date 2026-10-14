"""Q34c / DEC-OWNER-019: durable staggered joins, progress and cancellation."""
from __future__ import annotations

import sys
from types import ModuleType

import pytest

from app import bot_packs
from app.database import get_db, init_db

pytestmark = pytest.mark.asyncio


class FakeManager:
    def __init__(self):
        self.started: list[int] = []
        self.connected: set[int] = set()

    def get_status(self, account_id):
        return {"connected": account_id in self.connected}

    async def start_bot(self, account_id, *_a, **_kw):
        self.started.append(account_id)
        self.connected.add(account_id)
        return True

    async def stop_bot(self, account_id, *_a, **_kw):
        self.connected.discard(account_id)
        return True


@pytest.fixture
def server_stub():
    saved = sys.modules.get("app.server")
    fake = ModuleType("app.server")
    manager = FakeManager()
    fake.bot_manager = manager
    fake.eventsub_manager = None
    fake.chat_analyzer = None
    sys.modules["app.server"] = fake
    try:
        yield manager
    finally:
        if saved is not None:
            sys.modules["app.server"] = saved
        else:
            sys.modules.pop("app.server", None)


async def seed():
    await init_db()
    db = await get_db()
    try:
        await db.executemany(
            "INSERT INTO accounts(id,nickname,token,enabled,bot_role) VALUES (?,?,'x',0,'lurker')",
            ((1, "one"), (2, "two"), (3, "three")),
        )
        await db.commit()
    finally:
        await db.close()
    await bot_packs.create_pack(
        {
            "name": "spread",
            "join_window_min": 2,
            "members": [
                {"account_id": 1, "channel_name": "stream"},
                {"account_id": 2, "channel_name": "stream"},
                {"account_id": 3, "channel_name": "stream"},
            ],
        }
    )


async def join_rows():
    db = await get_db()
    try:
        return [
            tuple(row)
            for row in await (
                await db.execute("SELECT id,account_id,due_at,state FROM bot_pack_joins ORDER BY due_at,id")
            ).fetchall()
        ]
    finally:
        await db.close()


async def test_apply_schedules_spread_without_connecting_immediately(server_stub, monkeypatch):
    await seed()
    # No immortal background worker in the unit test; due rows are pumped explicitly below.
    async def no_worker():
        return None

    monkeypatch.setattr(bot_packs, "ensure_join_worker", no_worker)
    before = bot_packs.time.time()
    applied = await bot_packs.apply_pack(1)
    assert applied["scheduled"] == 3 and applied["window_min"] == 2
    assert server_stub.started == []
    rows = await join_rows()
    assert len(rows) == 3
    assert all(before <= due <= before + 120.1 and state == "pending" for _id, _account, due, state in rows)
    # Rows do not all share one timestamp: their slots are distributed over the window.
    assert len({round(row[2], 3) for row in rows}) == 3
    status = await bot_packs.pack_join_status(1)
    assert status["counts"]["pending"] == 3 and status["counts"]["joined"] == 0

    # Advance time beyond the full window: each queued bot connects once and is marked joined.
    joined = await bot_packs.process_due_joins(before + 121)
    assert joined == 3 and sorted(server_stub.started) == [1, 2, 3]
    status = await bot_packs.pack_join_status(1)
    assert status["counts"]["pending"] == 0 and status["counts"]["joined"] == 3


async def test_cancel_stops_pending_and_collapse_cancels_running_queue(server_stub, monkeypatch):
    await seed()
    async def no_worker():
        return None

    monkeypatch.setattr(bot_packs, "ensure_join_worker", no_worker)
    await bot_packs.apply_pack(1)
    cancelled = await bot_packs.cancel_pack_joins(1)
    assert cancelled["cancelled"] == 3
    assert (await bot_packs.pack_join_status(1))["counts"]["cancelled"] == 3
    assert await bot_packs.process_due_joins(bot_packs.time.time() + 999) == 0
    assert server_stub.started == []

    # A newly scheduled queue is cancelled by «Свернуть», too.
    await bot_packs.apply_pack(1)
    collapsed = await bot_packs.collapse_pack(1)
    assert collapsed["ok"] is True
    status = await bot_packs.pack_join_status(1)
    assert status["counts"]["pending"] == 0
    assert status["counts"]["cancelled"] == 3  # новый запуск очистил историю предыдущего


async def test_zero_window_stays_immediate(server_stub):
    await init_db()
    db = await get_db()
    try:
        await db.execute("INSERT INTO accounts(id,nickname,token,enabled,bot_role) VALUES (1,'one','x',0,'lurker')")
        await db.commit()
    finally:
        await db.close()
    await bot_packs.create_pack(
        {"name": "now", "join_window_min": 0, "members": [{"account_id": 1, "channel_name": "stream"}]}
    )
    applied = await bot_packs.apply_pack(1)
    assert applied["connected"] == [1] and server_stub.started == [1]
    assert await join_rows() == []
