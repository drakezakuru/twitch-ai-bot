"""PLAN_FEEDBACK_2908 §9k: расширенные категории AI-feedback.

POST /api/ai-feedback принимает category (too_long/toxic/off_style/off_topic/
other); stats возвращает разбивку categories.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


async def _seed_bot() -> None:
    from app.database import get_db

    db = await get_db()
    try:
        await db.execute("INSERT OR IGNORE INTO accounts (id, nickname, token) VALUES (1, 'fb', 't')")
        await db.commit()
    finally:
        await db.close()


async def test_feedback_with_category(tmp_db, disable_auth):
    from app.database import init_db
    from app.routes import router
    from fastapi import FastAPI

    await init_db()
    await _seed_bot()
    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for cat in ("too_long", "toxic", "toxic", "off_style"):
            resp = await client.post("/api/ai-feedback", json={
                "account_id": 1, "channel": "wow", "event_type": "send",
                "message": "тест", "rating": -1, "category": cat,
            })
            assert resp.status_code == 200 and resp.json()["ok"] is True

        # неизвестная категория → сохранена как ''
        resp = await client.post("/api/ai-feedback", json={
            "account_id": 1, "rating": -1, "category": "bogus",
        })
        assert resp.json()["ok"] is True

        stats = (await client.get("/api/ai-feedback/stats")).json()
        assert stats["negative"] == 5
        assert stats["categories"]["toxic"] == 2
        assert stats["categories"]["too_long"] == 1
        assert stats["categories"]["off_style"] == 1
        assert "bogus" not in stats["categories"]
