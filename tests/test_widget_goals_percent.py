"""§11.1 WIDGETS_PLAN: цели в процентах вместо галочки.

1. Миграция percent-колонки создаётся идемпотентно.
2. POST goals принимает percent; PUT goals/{id} принимает percent (0-100 clamp).
3. percent=100 автоматически выставляет done=1 (визуальная совместимость).
4. Публичный read отдаёт percent; старый done=1 читается как percent=100.
5. POST goals/{id}/step — шаг +1/-1 с clamp'ом 0..100 (для ?admin=1 и биндингов).
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


async def _client(tmp_db):
    from app.database import init_db
    from app.widgets import admin_router, public_router, ensure_widgets_schema
    await init_db()
    await ensure_widgets_schema()

    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(public_router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_goal_percent_add_update(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        add = (await c.post("/api/widgets/goals", json={"text": "50 subs", "percent": 30})).json()
        gid = add["id"]
        items = (await c.get("/api/widgets/goals")).json()["items"]
        assert items[0]["percent"] == 30
        assert items[0]["done"] in (0, False)

        # PUT percent + clamp
        await c.put(f"/api/widgets/goals/{gid}", json={"percent": 150})
        items = (await c.get("/api/widgets/goals")).json()["items"]
        assert items[0]["percent"] == 100
        # 100% = done (галочка — только визуал выполнено)
        assert items[0]["done"] in (1, True)


async def test_goal_public_percent_and_done_compat(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        add = (await c.post("/api/widgets/goals", json={"text": "g1"})).json()
        gid = add["id"]
        # Старый флоу: галочка done=True без percent -> public отдаёт percent=100
        await c.put(f"/api/widgets/goals/{gid}", json={"done": True})
        pub = (await c.get("/api/widgets/public/goals")).json()["items"]
        assert pub[0]["percent"] == 100


async def test_goal_step_route(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        add = (await c.post("/api/widgets/goals", json={"text": "step", "percent": 98})).json()
        gid = add["id"]
        row = (await c.post(f"/api/widgets/goals/{gid}/step", json={"delta": 1})).json()
        assert row["percent"] == 99
        row = (await c.post(f"/api/widgets/goals/{gid}/step", json={"delta": 5})).json()
        assert row["percent"] == 100
        assert row["done"] in (1, True)
        # clamp сверху
        row = (await c.post(f"/api/widgets/goals/{gid}/step", json={"delta": 10})).json()
        assert row["percent"] == 100
        # clamp снизу
        row = (await c.post(f"/api/widgets/goals/{gid}/step", json={"delta": -500})).json()
        assert row["percent"] == 0


async def test_goals_widget_html_has_percent_markers(tmp_db):
    from app.database import init_db
    from app.widgets import ensure_widgets_schema, widget_goals
    await init_db()
    await ensure_widgets_schema()
    html = await widget_goals()
    assert "gbar-fill" in html and "percent" in html and "admin" in html
