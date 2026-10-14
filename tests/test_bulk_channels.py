from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app import bulk_channels_routes
from app.database import get_db, init_db


@pytest_asyncio.fixture
async def seeded_db(tmp_db):
    await init_db()
    db = await get_db()
    try:
        await db.executemany(
            "INSERT INTO accounts (id, nickname, token) VALUES (?, ?, ?)",
            [(1, "alpha", "token-a"), (2, "beta", "token-b")],
        )
        await db.commit()
    finally:
        await db.close()


async def _successful_checks(accounts, channel, _message, **_kwargs):
    return [
        {
            "account_id": account["id"], "nickname": account["nickname"], "channel": channel,
            "token_status": "valid", "join_status": "online", "read_status": "confirmed",
            "send_status": "sent", "result": "success", "reason": "ok",
        }
        for account in accounts
    ]


@pytest.mark.asyncio
async def test_two_account_channel_matrix_is_idempotent_and_checked(seeded_db, monkeypatch):
    monkeypatch.setattr(bulk_channels_routes, "run_bot_check", _successful_checks)
    first = await bulk_channels_routes.run_bulk_add_and_check(
        [1, 2], ["one", "two"], "ping [ник]", read_timeout=0, send_interval=0,
    )
    second = await bulk_channels_routes.run_bulk_add_and_check(
        [1, 2], ["one", "two"], "ping [ник]", read_timeout=0, send_interval=0,
    )

    assert {(item["account_id"], item["channel"]) for item in first} == {
        (1, "one"), (2, "one"), (1, "two"), (2, "two"),
    }
    assert {item["add_result"] for item in first} == {"added"}
    assert {item["add_result"] for item in second} == {"skipped"}
    assert {item["check_result"] for item in second} == {"success"}

    db = await get_db()
    try:
        count = (await (await db.execute("SELECT COUNT(*) FROM channels")).fetchone())[0]
    finally:
        await db.close()
    assert count == 4


@pytest.mark.asyncio
async def test_missing_bot_is_per_item_error_without_stopping_valid_pair(seeded_db, monkeypatch):
    monkeypatch.setattr(bulk_channels_routes, "run_bot_check", _successful_checks)
    results = await bulk_channels_routes.run_bulk_add_and_check(
        [1, 99], ["one"], "ping", read_timeout=0, send_interval=0,
    )
    assert results[0]["add_result"] == "added"
    assert results[0]["check_result"] == "success"
    assert results[1]["add_result"] == "error"
    assert results[1]["add_reason"] == "bot_not_found"
    assert results[1]["check_result"] == "error"


@pytest.mark.asyncio
async def test_channel_overview_reports_exact_runtime_membership(seeded_db, monkeypatch):
    db = await get_db()
    try:
        await db.executemany(
            "INSERT INTO channels (account_id, channel_name, enabled) VALUES (?, ?, 1)",
            [(1, "shared"), (2, "shared"), (2, "other")],
        )
        await db.commit()
    finally:
        await db.close()

    class Manager:
        def get_all_statuses(self):
            return {
                1: {"connected": True, "channels": ["shared"]},
                2: {"connected": True, "channels": ["other"]},
            }

    monkeypatch.setattr(bulk_channels_routes, "_runtime_manager", lambda: Manager())
    payload = await bulk_channels_routes.channel_overview()
    channels = {item["channel"]: item for item in payload["channels"]}
    assert channels["shared"]["bot_count"] == 2
    assert channels["shared"]["connected_count"] == 1
    assert {bot["nickname"]: bot["connected"] for bot in channels["shared"]["bots"]} == {
        "alpha": True, "beta": False,
    }
    assert channels["other"]["connected_count"] == 1


@pytest.mark.asyncio
async def test_bulk_job_returns_combined_report_and_summary_only_audit(seeded_db, disable_auth, monkeypatch):
    async def fake_bulk(account_ids, channels, message_template, **_kwargs):
        return [{
            "account_id": account_ids[0], "nickname": "alpha", "channel": channels[0],
            "add_result": "skipped", "add_reason": "already_exists",
            "token_status": "valid", "join_status": "online", "read_status": "no_messages",
            "send_status": "sent", "check_result": "not_confirmed", "check_reason": "no_messages",
        }]

    monkeypatch.setattr(bulk_channels_routes, "run_bulk_add_and_check", fake_bulk)
    bulk_channels_routes._jobs.clear()
    app = FastAPI()
    app.include_router(bulk_channels_routes.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        job = (await client.post("/api/bulk/channels", json={
            "direction": "bots_to_channels", "account_ids": [1], "channels": ["shared"],
        })).json()
        for _ in range(20):
            status = (await client.get(f"/api/bulk/channels/{job['job_id']}")).json()
            if status["status"] != "running":
                break
            await asyncio.sleep(0)
    assert status["status"] == "completed"
    assert status["counts"]["skipped"] == 1
    assert status["counts"]["not_confirmed"] == 1

    db = await get_db()
    try:
        row = await (await db.execute(
            "SELECT detail FROM action_log WHERE action = 'bulk_channels' ORDER BY id DESC LIMIT 1"
        )).fetchone()
    finally:
        await db.close()
    assert "direction=bots_to_channels" in row["detail"]
    assert "no_messages" not in row["detail"]


@pytest.mark.asyncio
async def test_bulk_request_validation(seeded_db, disable_auth):
    app = FastAPI()
    app.include_router(bulk_channels_routes.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        bad_direction = await client.post("/api/bulk/channels", json={
            "direction": "bad", "account_ids": [1], "channels": ["ok"],
        })
        bad_channel = await client.post("/api/bulk/channels", json={
            "direction": "channel_to_bots", "account_ids": [1], "channels": ["bad channel"],
        })
    assert bad_direction.json()["code"] == "invalid_direction"
    assert bad_channel.json()["code"] == "invalid_channels"



# ── Q08(в): массовая смена канала ──

class _QuietManager:
    """Боты не подключены — join не нужен."""
    def get_status(self, _account_id):
        return {"connected": False, "channels": []}


class _JoinRecordingManager:
    def __init__(self):
        self.joins = []

    def get_status(self, account_id):
        return {"connected": True, "channels": self.joins_for.get(account_id, [])}

    def __init__(self):
        self.joins = []
        self.joins_for = {}

    async def join_channel(self, account_id, channel):
        self.joins.append((account_id, channel))
        self.joins_for.setdefault(account_id, []).append(channel)


async def _seed_binding(account_id: int, channel: str, enabled: int = 1) -> None:
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO channels (account_id, channel_name, enabled) VALUES (?, ?, ?)",
            (account_id, channel, enabled),
        )
        await db.commit()
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_change_channel_replace_detaches_old_and_joins_connected(seeded_db, monkeypatch):
    manager = _JoinRecordingManager()
    monkeypatch.setattr(bulk_channels_routes, "_runtime_manager", lambda: manager)
    await _seed_binding(1, "oldone")
    await _seed_binding(1, "oldtwo")

    items = await bulk_channels_routes._change_channel_pairs(
        [1], "newchan", True, {1: {"id": 1, "nickname": "alpha", "token": "t"}},
    )
    assert items == [{
        "account_id": 1, "nickname": "alpha", "channel": "newchan",
        "result": "changed", "reason": "ok", "detached": 2,
    }]
    assert manager.joins == [(1, "newchan")]

    db = await get_db()
    try:
        rows = await (await db.execute(
            "SELECT channel_name FROM channels WHERE account_id = 1 ORDER BY channel_name"
        )).fetchall()
    finally:
        await db.close()
    assert [row["channel_name"] for row in rows] == ["newchan"]


@pytest.mark.asyncio
async def test_change_channel_without_replace_keeps_old_bindings(seeded_db, monkeypatch):
    monkeypatch.setattr(bulk_channels_routes, "_runtime_manager", lambda: _QuietManager())
    await _seed_binding(1, "oldone")

    items = await bulk_channels_routes._change_channel_pairs(
        [1], "newchan", False, {1: {"id": 1, "nickname": "alpha", "token": "t"}},
    )
    assert items[0]["result"] == "added"
    assert items[0]["detached"] == 0

    db = await get_db()
    try:
        rows = await (await db.execute(
            "SELECT channel_name FROM channels WHERE account_id = 1 ORDER BY channel_name"
        )).fetchall()
    finally:
        await db.close()
    assert [row["channel_name"] for row in rows] == ["newchan", "oldone"]


@pytest.mark.asyncio
async def test_change_channel_existing_and_disabled_bindings_are_skipped(seeded_db, monkeypatch):
    monkeypatch.setattr(bulk_channels_routes, "_runtime_manager", lambda: _QuietManager())
    await _seed_binding(1, "live")
    await _seed_binding(2, "live", enabled=0)

    items = await bulk_channels_routes._change_channel_pairs(
        [1, 2], "live", False, {1: {"id": 1, "nickname": "alpha", "token": "t"},
                                2: {"id": 2, "nickname": "beta", "token": "t"}},
    )
    assert items[0]["result"] == "skipped"
    assert items[0]["reason"] == "already_exists"
    assert items[1]["result"] == "skipped"
    assert items[1]["reason"] == "binding_disabled"


@pytest.mark.asyncio
async def test_change_channel_missing_bot_is_per_item_error(seeded_db, monkeypatch):
    monkeypatch.setattr(bulk_channels_routes, "_runtime_manager", lambda: _QuietManager())
    items = await bulk_channels_routes._change_channel_pairs(
        [99], "newchan", False, {},
    )
    assert items[0]["result"] == "error"
    assert items[0]["reason"] == "bot_not_found"


@pytest.mark.asyncio
async def test_change_channel_job_runs_and_logs_summary_only(seeded_db, disable_auth, monkeypatch):
    monkeypatch.setattr(bulk_channels_routes, "_runtime_manager", lambda: _QuietManager())
    await _seed_binding(1, "oldone")
    await _seed_binding(2, "oldone")
    bulk_channels_routes._jobs.clear()
    app = FastAPI()
    app.include_router(bulk_channels_routes.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        bad = await client.post("/api/bulk/change-channel", json={
            "account_ids": [1], "channel": "bad channel",
        })
        assert bad.json()["code"] == "invalid_channels"
        job = (await client.post("/api/bulk/change-channel", json={
            "account_ids": [1, 2], "channel": "newchan", "replace": True,
        })).json()
        for _ in range(200):
            status = (await client.get(f"/api/bulk/channels/{job['job_id']}")).json()
            if status["status"] != "running":
                break
            await asyncio.sleep(0.01)
    assert status["status"] == "completed"
    assert status["counts"] == {"changed": 2, "added": 0, "skipped": 0, "errors": 0}

    db = await get_db()
    try:
        row = await (await db.execute(
            "SELECT detail FROM action_log WHERE action = 'bulk_channels' ORDER BY id DESC LIMIT 1"
        )).fetchone()
    finally:
        await db.close()
    assert "direction=change_channel" in row["detail"]
    assert "alpha" not in row["detail"]
