"""Wave 4 (owner survey Q25/Q29: М): общая event-модель.

`recent-events` (лента) и `latest-event-card` (одна карточка) — две проекции
одного набора данных `recent_events`, читаемого через `_read_recent_events()`.
Карточки и публичные URL у обоих сохранены — так решил владелец.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


async def _client():
    from app.database import init_db
    from app.widgets import admin_router, public_router, ensure_widgets_schema
    await init_db()
    await ensure_widgets_schema()
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(public_router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _add(c, kind: str, username: str, amount: int = 0):
    r = await c.post("/api/widgets/recent-events",
                     json={"kind": kind, "username": username, "amount": amount})
    assert r.json()["ok"] is True


async def test_both_projections_read_the_same_event(tmp_db, disable_auth):
    async with await _client() as c:
        await _add(c, "follow", "alice")
        await _add(c, "subscribe", "bob")
        feed = (await c.get("/api/widgets/public/recent-events")).json()
        card = (await c.get("/api/widgets/public/latest-event")).json()["event"]
        assert feed[0]["username"] == "bob"
        assert card == feed[0], "карточка и лента разошлись — модель не общая"


async def test_card_filter_narrows_only_the_card(tmp_db, disable_auth):
    """filter_kind — настройка карточки; лента остаётся полной."""
    async with await _client() as c:
        await _add(c, "follow", "alice")
        await _add(c, "subscribe", "bob")
        await c.put("/api/widgets/latest-event-card", json={"filter_kind": "follow"})
        card = (await c.get("/api/widgets/public/latest-event")).json()["event"]
        feed = (await c.get("/api/widgets/public/recent-events")).json()
        assert card["kind"] == "follow" and card["username"] == "alice"
        assert [e["username"] for e in feed] == ["bob", "alice"]


async def test_empty_state_is_honest(tmp_db, disable_auth):
    async with await _client() as c:
        await c.delete("/api/widgets/recent-events")
        assert (await c.get("/api/widgets/public/latest-event")).json()["event"] is None
        assert (await c.get("/api/widgets/public/recent-events")).json() == []


async def test_projections_expose_identical_fields(tmp_db, disable_auth):
    async with await _client() as c:
        await _add(c, "cheer", "carol", 100)
        feed_item = (await c.get("/api/widgets/public/recent-events")).json()[0]
        card = (await c.get("/api/widgets/public/latest-event")).json()["event"]
        assert set(feed_item) == set(card) == {"id", "kind", "username", "amount", "created_at"}


async def test_feed_limit_is_clamped(tmp_db, disable_auth):
    async with await _client() as c:
        for i in range(5):
            await _add(c, "follow", f"user{i}")
        assert len((await c.get("/api/widgets/public/recent-events?limit=2")).json()) == 2
        # верхняя граница публичной ленты — 30, запрос больше не должен падать
        assert len((await c.get("/api/widgets/public/recent-events?limit=999")).json()) == 5


async def test_both_widgets_keep_their_own_cards_and_urls():
    """Объединение модели не должно схлопнуть два виджета в один."""
    from app.widget_inventory import WIDGET_INVENTORY
    slugs = {item.slug for item in WIDGET_INVENTORY}
    assert {"latest-event-card", "recent-events"} <= slugs
    routes = {item.route for item in WIDGET_INVENTORY}
    assert {"/widget/latest-event-card", "/widget/recent-events"} <= routes
