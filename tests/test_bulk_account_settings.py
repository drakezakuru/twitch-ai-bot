"""Q39: массовое применение одной настройки сразу к большому числу ботов/аккаунтов."""
from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app import bulk_account_settings_routes, role_routes
from app.database import get_db, init_db

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def seeded(tmp_db):
    await init_db()
    db = await get_db()
    try:
        await db.executemany(
            "INSERT INTO accounts (id, nickname, token, bot_role, observation_only, eventsub_enabled, enabled) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (1, "alpha", "t1", "lurker", 0, 1, 1),
                (2, "beta", "t2", "lurker", 0, 1, 1),
                (3, "gamma", "t3", "chatter", 0, 1, 1),
            ],
        )
        await db.commit()
    finally:
        await db.close()


async def test_bulk_boolean_field_is_applied_to_every_selected_account(seeded, disable_auth):
    app = FastAPI()
    app.include_router(bulk_account_settings_routes.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/bulk/account-settings", json={
            "ids": [1, 2, 3], "field": "observation_only", "value": True,
        })
        body = resp.json()
        assert body["ok"] is True
        assert body["updated"] == 3
        assert {(item["account_id"], item["ok"]) for item in body["results"]} == {(1, True), (2, True), (3, True)}
    db = await get_db()
    try:
        rows = await (await db.execute("SELECT id, observation_only FROM accounts ORDER BY id")).fetchall()
    finally:
        await db.close()
    assert [tuple(row) for row in rows] == [(1, 1), (2, 1), (3, 1)]


async def test_bulk_bot_role_reuses_single_account_logic_and_clears_observation_only_leaving_lurker(seeded, disable_auth):
    db = await get_db()
    try:
        await db.execute("UPDATE accounts SET observation_only=1 WHERE id IN (1,2)")
        await db.commit()
    finally:
        await db.close()
    app = FastAPI()
    app.include_router(bulk_account_settings_routes.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/bulk/account-settings", json={
            "ids": [1, 2, 3], "field": "bot_role", "value": "chatter",
        })
        body = resp.json()
        assert body["ok"] is True and body["updated"] == 3
    db = await get_db()
    try:
        rows = {row[0]: (row[1], row[2]) for row in await (await db.execute(
            "SELECT id, bot_role, observation_only FROM accounts ORDER BY id",
        )).fetchall()}
    finally:
        await db.close()
    # Уходя с lurker, observation_only снимается (правило role_routes.put_role_config); тот, кто уже
    # не был lurker (gamma), не должен внезапно получить смену этого поля.
    assert rows[1] == ("chatter", 0)
    assert rows[2] == ("chatter", 0)
    assert rows[3] == ("chatter", 0)


async def test_bulk_settings_reports_not_found_and_invalid_value_without_touching_others(seeded, disable_auth):
    app = FastAPI()
    app.include_router(bulk_account_settings_routes.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        missing = await client.post("/api/bulk/account-settings", json={
            "ids": [1, 999], "field": "eventsub_enabled", "value": False,
        })
        body = missing.json()
        assert body["ok"] is True and body["updated"] == 1
        by_id = {item["account_id"]: item for item in body["results"]}
        assert by_id[999]["ok"] is False and by_id[999]["reason"] == "not_found"
        assert by_id[1]["ok"] is True

        bad_value = await client.post("/api/bulk/account-settings", json={
            "ids": [1], "field": "enabled", "value": "yes",
        })
        assert bad_value.json() == {"ok": False, "error": "invalid_value"}

        bad_field = await client.post("/api/bulk/account-settings", json={
            "ids": [1], "field": "token", "value": "x",
        })
        assert bad_field.json() == {"ok": False, "error": "unknown_field"}

        bad_role = await client.post("/api/bulk/account-settings", json={
            "ids": [1], "field": "bot_role", "value": "wizard",
        })
        assert bad_role.json() == {"ok": False, "error": "invalid_value"}

        empty_ids = await client.post("/api/bulk/account-settings", json={
            "ids": [], "field": "enabled", "value": True,
        })
        assert empty_ids.json() == {"ok": False, "error": "ids_required"}
