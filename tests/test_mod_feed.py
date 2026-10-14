"""PLAN_SESSION_ROLES §R2: mod-feed — publish/poll, дедуп, интенты, фильтры."""

from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app import database
from app.mod_feed_routes import (
    _BUFFER,
    _DEDUP,
    _INTENTS,
    publish_event,
    admin_router,
    public_router,
)


@pytest_asyncio.fixture(autouse=True)
async def _schema(tmp_db, disable_auth):
    await database.init_db()
    _BUFFER.clear()
    _DEDUP.clear()
    _INTENTS.clear()


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(public_router)
    return app


@pytest.mark.asyncio
async def test_publish_poll_roundtrip(tmp_db):
    ev = publish_event(1, "#Alekzz", "violation", user="badguy", text="мат (словарь)")
    assert ev is not None and ev["channel"] == "alekzz03" or ev["channel"] == "alekzz"
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        r = await client.get("/api/mod-feed/public/poll")
        body = r.json()
        assert body["ok"] is True and body["events"], "событие не дошло до виджета"
        assert body["events"][-1]["user"] == "badguy"
        # курсор: повторный поллинг — пусто
        cur = body["cursor"]
        r2 = await client.get(f"/api/mod-feed/public/poll?since={cur}")
        assert r2.json()["events"] == []


@pytest.mark.asyncio
async def test_dedup_same_violation(tmp_db):
    """§9: 10 одинаковых нарушений подряд не заваливают оверлей."""
    published = [publish_event(1, "ch", "violation", user="u1", text="мат") for _ in range(10)]
    assert published[0] is not None
    assert all(e is None for e in published[1:]), "дедуп не сработал"
    # другой юзер проходит
    assert publish_event(1, "ch", "violation", user="u2", text="мат") is not None
    # окно дедупа можно обойти явно
    assert publish_event(1, "ch", "violation", user="u1", text="мат", dedup=False) is not None


@pytest.mark.asyncio
async def test_intent_approve_reject(tmp_db):
    executed: list[dict] = []
    ev = publish_event(1, "ch", "intent", user="u1", text="предлагаю таймаут 1м",
                       intent={"_executor": lambda: executed.append({"ok": True}) or True})
    assert ev and ev["status"] == "pending"
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        r = await client.post(f"/api/mod-feed/intents/{ev['id']}/reject")
        assert r.json()["ok"] is True and r.json()["event"]["status"] == "rejected"
        assert executed == []  # reject не исполняет
        ev2 = publish_event(1, "ch", "intent", user="u2", text="предлагаю таймаут 10м",
                            intent={"_executor": lambda: executed.append({"ok": True}) or True})
        r = await client.post(f"/api/mod-feed/intents/{ev2['id']}/approve")
        assert r.json()["event"]["status"] == "approved"
        assert executed == [{"ok": True}]
        # повторное решение — не найдено
        r = await client.post(f"/api/mod-feed/intents/{ev2['id']}/approve")
        assert r.json()["ok"] is False


@pytest.mark.asyncio
async def test_kinds_filter(tmp_db):
    publish_event(1, "ch", "violation", user="u1", text="мат")
    publish_event(1, "ch", "action", user="u1", text="таймаут выдан")
    publish_event(1, "ch", "lurker", user="", text="наблюдение")
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        r = await client.get("/api/mod-feed/public/poll?kinds=violation,action")
        kinds = {e["kind"] for e in r.json()["events"]}
        assert kinds == {"violation", "action"}, "фильтр не сработал"


@pytest.mark.asyncio
async def test_bad_kind_rejected(tmp_db):
    assert publish_event(1, "ch", "hack_kind") is None


@pytest.mark.asyncio
async def test_widget_html_served(tmp_db):
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        r = await client.get("/widget/mod-feed")
        assert r.status_code == 200
        assert "mod-feed" in r.text and "/api/mod-feed/public/poll" in r.text
        assert "/widget/_shared/theme.css?v=" in r.text
        assert "/widget/_shared/appearance.js?v=" in r.text
