"""PLAN_FEEDBACK_2908 §3: единый хук on_donation_received.

Донат из ЛЮБОЙ платформы (DonatePay polling, DonateX polling,
DonationAlerts WS, универсальный webhook) двигает: топ донатеров
(таблица donations), активные челленджи (дельта), recent-events.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


async def _seed_challenge() -> int:
    from app.database import get_db

    db = await get_db()
    try:
        cur = await db.execute(
            "INSERT INTO donation_challenges (title, target_amount, current_amount, active) "
            "VALUES ('Тест-челлендж', 100, 0, 1)"
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


async def _challenge_row(cid: int) -> dict:
    from app.database import get_db

    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT current_amount, completed FROM donation_challenges WHERE id = ?", (cid,)
        )
        row = await cur.fetchone()
        return dict(row) if row else {}
    finally:
        await db.close()


async def _donations_count() -> int:
    from app.database import get_db

    db = await get_db()
    try:
        cur = await db.execute("SELECT COUNT(*) AS n FROM donations")
        return (await cur.fetchone())["n"]
    finally:
        await db.close()


async def test_hook_from_three_platforms_moves_challenge(tmp_db):
    from app.database import init_db
    from app.widgets import on_donation_received

    await init_db()
    cid = await _seed_challenge()

    for platform, user, amount in (
        ("donatepay", "nick", 30.0),
        ("donatex", "alex", 20.0),
        ("donationalerts", "maria", 10.0),
    ):
        res = await on_donation_received(platform, user, amount, "RUB", "го челлендж")
        assert res["ok"] is True
        assert res["platform"] == platform

    row = await _challenge_row(cid)
    assert row["current_amount"] == 60.0
    assert row["completed"] == 0
    assert await _donations_count() == 3


async def test_webhook_moves_challenge_and_top(tmp_db, disable_auth, monkeypatch):
    from app.database import init_db
    from app.widgets import admin_router, public_router
    from app.routes import router as api_router
    from fastapi import FastAPI

    await init_db()
    cid = await _seed_challenge()
    monkeypatch.setenv("DONATION_WEBHOOK_SECRET", "hook-secret")

    app = FastAPI()
    app.include_router(api_router)
    app.include_router(admin_router)
    app.include_router(public_router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/widgets/public/donation-webhook",
            json={
                "event_id": "s3-hook-event", "username": "webhook_user",
                "amount": 10, "currency": "RUB", "secret": "hook-secret",
            },
        )
        assert resp.status_code == 200
        assert resp.json().get("ok") is True

        row = await _challenge_row(cid)
        assert row["current_amount"] == 10.0
        assert await _donations_count() == 1

        # топ донатеров видит донат из webhook
        resp = await client.get("/api/widgets/public/top-donator/alltime")
        assert resp.status_code == 200
