"""Focused backend coverage for v13 fact metadata and observer preset."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient


def test_fact_metadata_normalizes_and_prompt_is_prioritized():
    from app.ai_quality import format_facts_for_prompt, normalize_fact_entry

    normalized = normalize_fact_entry({"fact": "important", "priority": 999, "expires_at": None})
    assert normalized["priority"] == 100
    assert normalized["expires_at"] is None
    text = format_facts_for_prompt([
        {"fact": "low", "priority": 1, "confidence": 1},
        {"fact": "high", "priority": 90, "confidence": 1},
    ])
    assert text == "high; low"


def test_expired_facts_are_filtered():
    from app.ai_quality import format_facts_for_prompt

    expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    assert format_facts_for_prompt([{"fact": "gone", "expires_at": expired}]) == ""


@pytest.mark.asyncio
async def test_memory_route_accepts_priority_and_ttl(tmp_db, disable_auth):
    from app import database
    from fastapi import FastAPI
    from app.routes import router

    await database.init_db()
    db = await database.get_db()
    await db.execute("INSERT INTO accounts (id, nickname, token) VALUES (1, 'bot', 'tok')")
    await db.commit()
    await db.close()

    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/accounts/1/memory/alice", json={
            "fact": "likes tea", "priority": 85, "ttl": 3600,
        })
        assert response.json()["ok"] is True
        memory = (await client.get("/api/accounts/1/memory/alice")).json()
        fact = memory["facts_structured"][0]
        assert fact["priority"] == 85
        assert fact["expires_at"] is not None

        updated = await client.put("/api/accounts/1/memory/alice/fact", json={
            "fact": "likes tea", "priority": 100, "expires_at": None,
        })
        assert updated.json()["ok"] is True
        fact = (await client.get("/api/accounts/1/memory/alice")).json()["facts_structured"][0]
        assert fact["priority"] == 100
        assert fact["expires_at"] is None


@pytest.mark.asyncio
async def test_affinity_isolated_by_channel_and_user_with_lock_history(tmp_db, disable_auth):
    from app import database
    from fastapi import FastAPI
    from app.routes import router

    await database.init_db()
    db = await database.get_db()
    await db.execute("INSERT INTO accounts (id, nickname, token) VALUES (1, 'bot', 'tok')")
    await db.commit()
    await db.close()

    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.put("/api/accounts/1/affinity", json={
            "channel": "#alpha", "username": "Alice", "contact_level": 150,
            "chat_affinity": -10, "auto_adjust": True, "manual_lock": True,
        })
        assert first.json()["contact_level"] == 100
        assert first.json()["chat_affinity"] == 0
        assert first.json()["manual_lock"] == 1

        second = await client.put("/api/accounts/1/affinity", json={
            "channel": "beta", "username": "alice", "contact_level": 20,
            "chat_affinity": 30,
        })
        assert second.json()["channel"] == "beta"
        alpha = (await client.get("/api/accounts/1/affinity?channel=alpha&username=ALICE")).json()
        beta = (await client.get("/api/accounts/1/affinity?channel=%23beta&username=alice")).json()
        assert (alpha["contact_level"], alpha["chat_affinity"], alpha["manual_lock"]) == (100, 0, 1)
        assert (beta["contact_level"], beta["chat_affinity"]) == (20, 30)

        history = (await client.get("/api/accounts/1/affinity/history?channel=alpha&username=alice")).json()
        assert len(history["history"]) == 1
        assert history["history"][0]["source"] == "manual"


@pytest.mark.asyncio
async def test_legacy_affinity_is_copied_to_global_scope(tmp_db):
    from app import database

    await database.init_db()
    db = await database.get_db()
    try:
        await db.execute("INSERT INTO accounts (id, nickname, token) VALUES (1, 'bot', 'tok')")
        await db.execute(
            "INSERT INTO bot_streamer_affinity (account_id, contact_level, chat_affinity, auto_adjust) VALUES (1, 77, 66, 1)"
        )
        await db.commit()
    finally:
        await db.close()

    # init_db is idempotent and performs the compatibility copy for an
    # existing database after the new table has been created.
    await database.init_db()
    db = await database.get_db()
    try:
        cursor = await db.execute(
            "SELECT contact_level, chat_affinity, auto_adjust FROM bot_affinity "
            "WHERE account_id = 1 AND channel = '' AND username = ''"
        )
        row = await cursor.fetchone()
        assert tuple(row) == (77, 66, 1)
    finally:
        await db.close()


def test_observer_is_in_backend_preset_registry():
    from app.bot_presets import BEHAVIOR_PRESETS

    assert BEHAVIOR_PRESETS["observer"]["observation_only"] is True
    assert "ai" not in BEHAVIOR_PRESETS["observer"]["description"].lower()
