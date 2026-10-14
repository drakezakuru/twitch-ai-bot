"""Q34a/Q34b / DEC-OWNER-019: bot pack CRUD and apply/collapse."""
from __future__ import annotations

import sys
from types import ModuleType
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app import bot_packs
from app.database import get_db, init_db

pytestmark = pytest.mark.asyncio


async def seed_bots():
    await init_db()
    db = await get_db()
    try:
        await db.executemany(
            "INSERT INTO accounts(id, nickname, token, enabled, bot_role) VALUES (?, ?, 'x', 1, 'lurker')",
            ((1, "bot_a"), (2, "bot_b"), (3, "bot_c")),
        )
        await db.executemany(
            "INSERT INTO channels(account_id, channel_name, enabled) VALUES (?, ?, 1)",
            ((1, "streamer1"), (2, "streamer2")),
        )
        await db.commit()
    finally:
        await db.close()


def members(*pairs):
    return [{"account_id": a, "channel_name": c} for a, c in pairs]


async def test_pack_crud_roundtrip_and_normalization():
    await seed_bots()
    created = await bot_packs.create_pack(
        {"name": "  Ночной стрим  ", "join_window_min": "7", "members": members((1, "#Streamer1"), (2, ""), (1, "streamer1"))}
    )
    assert created["ok"] and created["members"] == 2  # duplicate (1, streamer1) deduped
    packs = (await bot_packs.list_packs())["packs"]
    assert len(packs) == 1
    pack = packs[0]
    assert pack["name"] == "Ночной стрим" and pack["join_window_min"] == 7
    assert [m["account_id"] for m in pack["members"]] == [1, 2]
    assert pack["members"][0]["channel_name"] == "streamer1"  # '#' stripped, lowercased
    assert pack["members"][0]["nickname"] == "bot_a"
    assert pack["members"][1]["channel_name"] == ""

    updated = await bot_packs.update_pack(
        pack["id"], {"name": "Дневной", "join_window_min": 0, "members": members((3, "streamer2"))}
    )
    assert updated["members"] == 1
    packs = (await bot_packs.list_packs())["packs"]
    assert packs[0]["name"] == "Дневной" and packs[0]["join_window_min"] == 0
    assert [m["account_id"] for m in packs[0]["members"]] == [3]

    assert (await bot_packs.delete_pack(pack["id"]))["ok"] is True
    assert (await bot_packs.list_packs())["packs"] == []
    with pytest.raises(Exception, match="pack_missing"):
        await bot_packs.delete_pack(pack["id"])


async def test_pack_validation_rejects_bad_input():
    await seed_bots()
    await bot_packs.create_pack({"name": "base", "join_window_min": 5, "members": members((1, "s"))})
    for bad in (
        {"name": "", "members": []},
        {"name": "x" * 65, "members": []},
        {"name": "ok", "join_window_min": -1, "members": []},
        {"name": "ok", "join_window_min": 181, "members": []},
        {"name": "ok", "join_window_min": "abc", "members": []},
        {"name": "ok", "members": "nope"},
        {"name": "ok", "members": members((999, "s"))},
        {"name": "ok", "members": members((True, "s"))},
        {"name": "ok", "members": [{"account_id": 1, "channel_name": 5}]},
    ):
        with pytest.raises(Exception):
            await bot_packs.create_pack(bad)
    packs = (await bot_packs.list_packs())["packs"]
    assert len(packs) == 1  # nothing partial was created
    # Name must stay unique.
    with pytest.raises(Exception, match="pack_name_taken"):
        await bot_packs.create_pack({"name": "base", "join_window_min": 5, "members": []})
    # A rename onto ANOTHER pack's name is rejected.
    await bot_packs.create_pack({"name": "second", "join_window_min": 1, "members": []})
    with pytest.raises(Exception, match="pack_name_taken"):
        await bot_packs.update_pack(packs[0]["id"], {"name": "second", "join_window_min": 5, "members": []})


@pytest_asyncio.fixture
async def client(disable_auth):
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(bot_packs.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as value:
        yield value


async def test_pack_routes_list_create_update_delete(client):
    await seed_bots()
    listed = await client.get("/api/packs")
    assert listed.status_code == 200 and listed.json()["packs"] == []
    created = await client.post(
        "/api/packs",
        json={"name": "pack", "join_window_min": 3, "members": members((1, "streamer1"), (2, "streamer2"))},
    )
    assert created.status_code == 200 and created.json()["members"] == 2
    bad = await client.post("/api/packs", json={"name": "", "members": []})
    assert bad.status_code == 400 and bad.json()["detail"] == "pack_name_invalid"
    updated = await client.put(
        "/api/packs/1", json={"name": "renamed", "join_window_min": 10, "members": members((3, ""))}
    )
    assert updated.status_code == 200 and updated.json()["members"] == 1
    missing = await client.put("/api/packs/999", json={"name": "x", "join_window_min": 1, "members": []})
    assert missing.status_code == 400 and missing.json()["detail"] == "pack_missing"
    assert (await client.delete("/api/packs/1")).json()["ok"] is True
    assert (await client.get("/api/packs")).json()["packs"] == []


# ── Q34b: apply («Начать стрим») и collapse («Свернуть») ──


class _FakeManager:
    def __init__(self):
        self.started: list[int] = []
        self.stopped: list[int] = []
        self.connected: set[int] = set()

    def get_status(self, account_id):
        return {"connected": account_id in self.connected}

    async def start_bot(self, account_id, *_a, **_kw):
        self.started.append(account_id)
        self.connected.add(account_id)
        return True

    async def stop_bot(self, account_id, *_a, **_kw):
        self.stopped.append(account_id)
        self.connected.discard(account_id)
        return True


@pytest.fixture
def stub_server():
    saved = sys.modules.get("app.server")
    fake = ModuleType("app.server")
    manager = _FakeManager()
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


async def _enabled_flags() -> dict[int, int]:
    db = await get_db()
    try:
        return {row[0]: row[1] for row in await (await db.execute("SELECT id, enabled FROM accounts")).fetchall()}
    finally:
        await db.close()


async def _channel_rows() -> list[tuple[int, str, int]]:
    db = await get_db()
    try:
        return [
            (row[0], row[1], row[2])
            for row in await (
                await db.execute("SELECT account_id, channel_name, enabled FROM channels ORDER BY account_id, channel_name")
            ).fetchall()
        ]
    finally:
        await db.close()


async def test_apply_enables_binds_and_collapses_to_snapshot(stub_server):
    await seed_bots()
    # Pre-pack world: bot 1 enabled with chan1 (same name, disabled), bot 2 disabled.
    db = await get_db()
    try:
        await db.execute("UPDATE channels SET enabled=0 WHERE account_id=1 AND channel_name='streamer1'")
        await db.execute("UPDATE accounts SET enabled=0 WHERE id=2")
        await db.commit()
    finally:
        await db.close()
    await bot_packs.create_pack(
        {"name": "ночь", "join_window_min": 0, "members": members((1, "streamer1"), (2, "streamer2"))}
    )
    applied = await bot_packs.apply_pack(1)
    assert applied["enabled"] == 2 and applied["connected"] == [1, 2]
    assert stub_server.started == [1, 2]
    flags = await _enabled_flags()
    assert flags == {1: 1, 2: 1, 3: 1}  # bot 3 (не в пачке) не тронут: был enabled=1
    channels = dict(((a, c), e) for a, c, e in await _channel_rows())
    assert channels[(1, "streamer1")] == 1  # заново включена
    assert channels[(2, "streamer2")] == 1  # создана и включена

    # Collapse возвращает мир к снимку: bot 2 снова выключен, chan1 снова выключена.
    collapsed = await bot_packs.collapse_pack(1)
    assert collapsed["disabled"] == 1 and collapsed["kept"] == 1
    assert stub_server.stopped == [2] and 2 not in stub_server.connected
    flags = await _enabled_flags()
    assert flags == {1: 1, 2: 0, 3: 1}
    channels = dict(((a, c), e) for a, c, e in await _channel_rows())
    assert channels[(1, "streamer1")] == 0 and channels[(2, "streamer2")] == 1

    # Повторный collapse без снимка просто выключает всех членов пачки.
    again = await bot_packs.collapse_pack(1)
    assert again["disabled"] == 2 and again["kept"] == 0
    assert (await _enabled_flags()) == {1: 0, 2: 0, 3: 1}


async def test_collapse_disable_channels_option_and_empty_pack(stub_server):
    await seed_bots()
    await bot_packs.create_pack(
        {"name": "p", "join_window_min": 0, "members": members((1, "streamer1"), (2, "streamer2"))}
    )
    await bot_packs.apply_pack(1)
    collapsed = await bot_packs.collapse_pack(1, disable_channels=True)
    assert collapsed["channels_disabled"] is True
    assert all(enabled == 0 for _a, _c, enabled in await _channel_rows())

    await bot_packs.create_pack({"name": "empty", "join_window_min": 1, "members": []})
    with pytest.raises(Exception, match="pack_empty"):
        await bot_packs.apply_pack((await bot_packs.list_packs())["packs"][-1]["id"])
    with pytest.raises(Exception, match="pack_missing"):
        await bot_packs.apply_pack(999)


async def test_apply_routes_wire_to_handlers(client, stub_server):
    await seed_bots()
    await bot_packs.create_pack({"name": "pack", "join_window_min": 5, "members": members((1, "s"))})
    applied = await client.post("/api/packs/1/apply", json={"connect": False})
    assert applied.status_code == 200 and applied.json()["enabled"] == 1
    assert stub_server.started == []  # connect=False: только флаги, без захода
    collapsed = await client.post("/api/packs/1/collapse", json={"disable_channels": False})
    assert collapsed.status_code == 200 and collapsed.json()["ok"] is True
    joins = await client.get("/api/packs/1/joins")
    assert joins.status_code == 200 and joins.json()["counts"]["pending"] == 0
    cancelled = await client.post("/api/packs/1/joins/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["cancelled"] == 0
    missing = await client.post("/api/packs/999/apply", json={})
    assert missing.status_code == 400 and missing.json()["detail"] == "pack_missing"
    missing_joins = await client.get("/api/packs/999/joins")
    assert missing_joins.status_code == 400 and missing_joins.json()["detail"] == "pack_missing"
