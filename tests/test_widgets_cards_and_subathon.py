"""Решения владельца 31.08: карточки новых виджетов + тариф субатона за валюту."""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


async def _client():
    from app.database import init_db
    from app.widgets import admin_router, public_router, ensure_widgets_schema
    from app import database as db_mod
    if db_mod._shared_db is not None:
        try:
            await db_mod._shared_db.close()
        except Exception:
            pass
        db_mod._shared_db = None
    await init_db()
    await ensure_widgets_schema()
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(public_router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_new_grid_cards_exist():
    """4 новых grid-карточки (follower-ticker, donation-challenge, emoji-chat, hype-meter)."""
    from app.widget_inventory import WIDGET_INVENTORY
    registered = {item.slug for item in WIDGET_INVENTORY}
    for slug in ("follower-ticker", "donation-challenge", "emoji-chat", "hype-meter"):
        assert slug in registered, slug


async def test_subathon_card_and_currency_rate_roundtrip(tmp_db, disable_auth):
    """Карточка субатона: тарифы сохраняются, seconds_per_currency в GET."""
    from pathlib import Path
    tpl = (Path(__file__).resolve().parents[1] / "templates" / "partials" / "widgets.html").read_text()
    assert 'id="subathonPerCurrency"' in tpl
    async with await _client() as c:
        put = await c.put("/api/widgets/subathon", json={
            "seconds_per_sub": 90,
            "seconds_per_donation": 45,
            "seconds_per_currency": 2.5,
        })
        assert put.json()["ok"] is True
        got = (await c.get("/api/widgets/subathon")).json()
        assert got["seconds_per_sub"] == 90
        assert got["seconds_per_donation"] == 45
        assert abs(float(got["seconds_per_currency"]) - 2.5) < 1e-6
        assert "remaining" in got


async def test_subathon_donation_uses_currency_rate(tmp_db, disable_auth):
    """Донат 10 ед. при тарифе 2.5 с/ед. продлевает таймер на 25 сек."""
    async with await _client() as c:
        # Запускаем таймер
        start = await c.post("/api/widgets/subathon/start", json={})
        assert start.json().get("ok") is True
        await c.put("/api/widgets/subathon", json={"seconds_per_currency": 2.5, "seconds_per_donation": 0})

        from app.database import get_db
        db = await get_db()
        try:
            cur = await db.execute("SELECT end_at FROM subathon_timer WHERE id = 1")
            end_before = (await cur.fetchone())["end_at"]
        finally:
            await db.close()

        from app.widgets import on_donation_received
        await on_donation_received("donatex", "user1", 10.0, "UAH", "го")

        db = await get_db()
        try:
            cur = await db.execute("SELECT end_at FROM subathon_timer WHERE id = 1")
            end_after = (await cur.fetchone())["end_at"]
        finally:
            await db.close()
        assert end_after > end_before  # таймер продлён


async def test_donation_reaches_top_and_recent_events(tmp_db, disable_auth):
    """§10.4: донат из интеграции → топ донатеров + recent-events."""
    async with await _client() as c:
        from app.widgets import on_donation_received
        await on_donation_received("donatex", "viewerX", 100.0, "UAH", "держи")
        recent = (await c.get("/api/widgets/recent-events?limit=50")).json()
        assert any(e["username"] == "viewerX" and e["kind"] == "donation" for e in recent), recent[:3]
        top = (await c.get("/api/widgets/top-donators")).json()
        assert any(d["username"] == "viewerX" for d in (top.get("recent_donations") or []))
        assert any(d["username"] == "viewerX" for d in (top.get("top_alltime") or []))
