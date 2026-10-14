"""v10.2: тесты ai_feedback API + DB."""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


async def _client(tmp_db):
    from app import database
    await database.init_db()
    db = await database.get_db()
    await db.execute(
        "INSERT INTO accounts (id, nickname, token) VALUES (1, 'acc1', 'tok')"
    )
    await db.commit()
    from fastapi import FastAPI
    from app.routes import router
    app = FastAPI()
    app.include_router(router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_ai_feedback_table_created(tmp_db, disable_auth):
    """В схеме v10.2 должна появиться таблица ai_feedback."""
    from app import database
    await database.init_db()
    db = await database.get_db()
    cur = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='ai_feedback'"
    )
    row = await cur.fetchone()
    assert row is not None


async def test_post_ai_feedback_stores_row(tmp_db, disable_auth):
    client = await _client(tmp_db)
    async with client:
        r = await client.post("/api/ai-feedback", json={
            "account_id": 1,
            "channel": "test",
            "event_type": "send",
            "message": "hi chat",
            "rating": 1,
        })
        assert r.status_code == 200
        assert r.json()["ok"] is True

        r = await client.get("/api/ai-feedback/stats")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["positive"] == 1
        assert body["negative"] == 0


async def test_post_ai_feedback_negative(tmp_db, disable_auth):
    client = await _client(tmp_db)
    async with client:
        for _ in range(3):
            r = await client.post("/api/ai-feedback", json={
                "account_id": 1,
                "channel": "test",
                "event_type": "stream_vision_chat",
                "message": "bad bot reply",
                "rating": -1,
            })
            assert r.status_code == 200

        await client.post("/api/ai-feedback", json={
            "account_id": 1,
            "channel": "test",
            "event_type": "send",
            "message": "good",
            "rating": 1,
        })

        r = await client.get("/api/ai-feedback/stats")
        body = r.json()
        assert body["total"] == 4
        assert body["positive"] == 1
        assert body["negative"] == 3


async def test_post_ai_feedback_rejects_invalid_rating(tmp_db, disable_auth):
    client = await _client(tmp_db)
    async with client:
        r = await client.post("/api/ai-feedback", json={
            "account_id": 1,
            "channel": "test",
            "event_type": "send",
            "message": "hello",
            "rating": 5,
        })
        body = r.json()
        assert body["ok"] is False
        assert "rating" in body["error"].lower()


async def test_get_stats_empty(tmp_db, disable_auth):
    client = await _client(tmp_db)
    async with client:
        r = await client.get("/api/ai-feedback/stats")
        body = r.json()
        # §9k: stats дополнен разбивкой categories
        assert body == {"total": 0, "positive": 0, "negative": 0, "categories": {}}
