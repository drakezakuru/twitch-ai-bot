"""v8 API endpoint tests."""
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
    await db.execute(
        "INSERT INTO accounts (id, nickname, token) VALUES (2, 'acc2', 'tok')"
    )
    await db.commit()
    from fastapi import FastAPI
    from app.routes import router, ws_router
    app = FastAPI()
    app.include_router(router)
    app.include_router(ws_router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ====== KB ======


async def test_kb_post_get_put_delete(tmp_db, disable_auth):
    client = await _client(tmp_db)
    async with client:
        # Add
        r = await client.post("/api/accounts/1/kb", json={
            "topic": "стрим",
            "content": "стрим вечером в 19",
            "tags": "расписание",
            "priority": 7,
        })
        assert r.status_code == 200
        kb_id = r.json()["id"]
        assert kb_id > 0

        # List
        r = await client.get("/api/accounts/1/kb")
        items = r.json()["items"]
        assert len(items) == 1
        assert items[0]["topic"] == "стрим"

        # Update
        r = await client.put(f"/api/accounts/1/kb/{kb_id}", json={"priority": 9})
        assert r.status_code == 200
        r = await client.get("/api/accounts/1/kb")
        assert r.json()["items"][0]["priority"] == 9

        # Search
        r = await client.get("/api/accounts/1/kb/search", params={"q": "когда стрим", "top_k": 3})
        assert r.status_code == 200
        assert "results" in r.json()

        # Delete
        r = await client.delete(f"/api/accounts/1/kb/{kb_id}")
        assert r.status_code == 200
        r = await client.get("/api/accounts/1/kb")
        assert r.json()["items"] == []


async def test_kb_validates_required_fields(tmp_db, disable_auth):
    client = await _client(tmp_db)
    async with client:
        r = await client.post("/api/accounts/1/kb", json={"topic": "", "content": ""})
        assert r.status_code == 200
        assert r.json().get("error") == "topic_and_content_required"


# ====== Style examples ======


async def test_style_examples_endpoints(tmp_db, disable_auth):
    client = await _client(tmp_db)
    async with client:
        r = await client.post("/api/accounts/1/style-examples", json={
            "message": "ну да, харош",
            "channel": "streamer1",
            "note": "мой стиль",
        })
        ex_id = r.json()["id"]
        assert ex_id > 0

        r = await client.get("/api/accounts/1/style-examples")
        items = r.json()["items"]
        assert len(items) == 1
        assert items[0]["message"] == "ну да, харош"

        r = await client.delete(f"/api/accounts/1/style-examples/{ex_id}")
        assert r.status_code == 200
        assert (await client.get("/api/accounts/1/style-examples")).json()["items"] == []


async def test_style_examples_validates_message(tmp_db, disable_auth):
    client = await _client(tmp_db)
    async with client:
        r = await client.post("/api/accounts/1/style-examples", json={"message": ""})
        assert r.json().get("error") == "message_required"


# ====== Banned topics ======


async def test_banned_topics_endpoints(tmp_db, disable_auth):
    client = await _client(tmp_db)
    async with client:
        r = await client.post("/api/accounts/1/banned-topics", json={
            "pattern": "политика",
            "fallback": "о игре",
            "mode": "fallback",
        })
        topic_id = r.json()["id"]
        assert topic_id > 0

        r = await client.get("/api/accounts/1/banned-topics")
        assert len(r.json()["items"]) == 1

        r = await client.put(f"/api/accounts/1/banned-topics/{topic_id}", json={"mode": "silent"})
        assert r.status_code == 200

        r = await client.get("/api/accounts/1/banned-topics")
        assert r.json()["items"][0]["mode"] == "silent"

        r = await client.delete(f"/api/accounts/1/banned-topics/{topic_id}")
        assert r.status_code == 200


async def test_banned_topics_default_mode(tmp_db, disable_auth):
    client = await _client(tmp_db)
    async with client:
        r = await client.post("/api/accounts/1/banned-topics", json={
            "pattern": "spam",
            "mode": "invalid_mode",
        })
        topic_id = r.json()["id"]
        r = await client.get("/api/accounts/1/banned-topics")
        # invalid_mode → silent (default)
        assert r.json()["items"][0]["mode"] == "silent"


async def test_check_banned_endpoint(tmp_db, disable_auth):
    client = await _client(tmp_db)
    async with client:
        await client.post("/api/accounts/1/banned-topics", json={
            "pattern": "spam",
            "fallback": "no",
            "mode": "fallback",
        })
        r = await client.post("/api/ai/check-banned", json={
            "text": "this is spam content",
            "account_id": 1,
        })
        assert r.json()["hit"] is not None

        r = await client.post("/api/ai/check-banned", json={
            "text": "harmless text",
            "account_id": 1,
        })
        assert r.json()["hit"] is None


# ====== Account-scoped A/B prompt variants ======


async def test_variants_endpoints(tmp_db, disable_auth):
    client = await _client(tmp_db)
    async with client:
        r = await client.post("/api/accounts/1/prompt-variants", json={
            "label": "A", "system_prompt": "промпт A", "weight": 70,
        })
        vid = r.json()["id"]
        r = await client.get("/api/accounts/1/prompt-variants")
        assert len(r.json()["items"]) == 1
        assert (await client.put(f"/api/accounts/1/prompt-variants/{vid}", json={"weight": 30})).status_code == 200
        assert (await client.delete(f"/api/accounts/1/prompt-variants/{vid}")).status_code == 200


# ====== Feedback ======


async def test_feedback_endpoints(tmp_db, disable_auth):
    client = await _client(tmp_db)
    async with client:
        # Создаём chat_log запись
        from app import database
        db = await database.get_db()
        try:
            await db.execute(
                "INSERT INTO chat_log (account_id, channel, author, message, is_bot) "
                "VALUES (1, 'c', 'bot', 'msg', 1)"
            )
            await db.commit()
            cursor = await db.execute("SELECT id FROM chat_log LIMIT 1")
            log_id = (await cursor.fetchone())["id"]
        finally:
            await db.close()

        # Submit feedback
        r = await client.post("/api/accounts/1/feedback", json={
            "chat_log_id": log_id,
            "feedback": 1,
            "note": "хорошо",
        })
        assert r.status_code == 200

        r = await client.post("/api/accounts/1/feedback", json={
            "chat_log_id": log_id,
            "feedback": -1,
        })
        assert r.status_code == 200

        # Get feedback for log
        r = await client.get(f"/api/accounts/1/feedback/log/{log_id}")
        data = r.json()
        assert data["likes"] == 1
        assert data["dislikes"] == 1

        # Summary
        r = await client.get("/api/accounts/1/feedback/summary", params={"days": 30})
        assert r.status_code == 200


async def test_feedback_validates_required(tmp_db, disable_auth):
    client = await _client(tmp_db)
    async with client:
        r = await client.post("/api/accounts/1/feedback", json={"feedback": 1})
        assert r.json().get("error") == "chat_log_id_required"

        r = await client.post("/api/accounts/1/feedback", json={"chat_log_id": 1, "feedback": 0})
        assert r.json().get("error") == "feedback_required"


async def test_ai_quality_mutations_reject_foreign_account(tmp_db, disable_auth):
    client = await _client(tmp_db)
    async with client:
        kb_id = (await client.post("/api/accounts/1/kb", json={"topic": "owned", "content": "content"})).json()["id"]
        style_id = (await client.post("/api/accounts/1/style-examples", json={"message": "owned"})).json()["id"]
        topic_id = (await client.post("/api/accounts/1/banned-topics", json={"pattern": "owned"})).json()["id"]
        variant_id = (await client.post("/api/accounts/1/prompt-variants", json={"label": "A"})).json()["id"]

        assert (await client.put(f"/api/accounts/2/kb/{kb_id}", json={"content": "stolen"})).status_code == 404
        assert (await client.delete(f"/api/accounts/2/kb/{kb_id}")).status_code == 404
        assert (await client.delete(f"/api/accounts/2/style-examples/{style_id}")).status_code == 404
        assert (await client.put(f"/api/accounts/2/banned-topics/{topic_id}", json={"pattern": "stolen"})).status_code == 404
        assert (await client.delete(f"/api/accounts/2/banned-topics/{topic_id}")).status_code == 404
        assert (await client.put(f"/api/accounts/2/prompt-variants/{variant_id}", json={"weight": 1})).status_code == 404
        assert (await client.delete(f"/api/accounts/2/prompt-variants/{variant_id}")).status_code == 404

        assert (await client.get("/api/accounts/1/kb")).json()["items"][0]["content"] == "content"
        assert (await client.get("/api/accounts/1/style-examples")).json()["items"][0]["message"] == "owned"
        assert (await client.get("/api/accounts/1/banned-topics")).json()["items"][0]["pattern"] == "owned"
        assert (await client.get("/api/accounts/1/prompt-variants")).json()["items"][0]["weight"] == 50


async def test_feedback_routes_reject_foreign_account(tmp_db, disable_auth):
    client = await _client(tmp_db)
    async with client:
        from app import database
        db = await database.get_db()
        try:
            cursor = await db.execute(
                "INSERT INTO chat_log (account_id, channel, author, message, is_bot) "
                "VALUES (1, 'c', 'bot', 'owned', 1)"
            )
            await db.commit()
            log_id = cursor.lastrowid
        finally:
            await db.close()

        assert (await client.post("/api/accounts/2/feedback", json={"chat_log_id": log_id, "feedback": 1})).status_code == 404
        assert (await client.get(f"/api/accounts/2/feedback/log/{log_id}")).status_code == 404
        assert (await client.get("/api/accounts/2/feedback/summary")).json()["total"] == 0
        assert (await client.get(f"/api/accounts/1/feedback/log/{log_id}")).json() == {"likes": 0, "dislikes": 0}


# ====== Pre-classifier ======


async def test_classify_endpoint(tmp_db, disable_auth):
    client = await _client(tmp_db)
    async with client:
        r = await client.post("/api/ai/classify", json={
            "message": "Эй botName, как дела?",
            "account_id": 1,
            "channel": "c",
            "bot_nickname": "botName",
            "min_confidence": 0.4,
        })
        data = r.json()
        assert data["should_reply"] is True
        assert data["confidence"] >= 0.4


async def test_classify_endpoint_validates_message(tmp_db, disable_auth):
    client = await _client(tmp_db)
    async with client:
        r = await client.post("/api/ai/classify", json={"message": ""})
        assert r.json().get("error") == "message_required"
