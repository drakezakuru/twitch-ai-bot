"""P1 §24: админ-флоу виджетов — наполнение контентом через формы панели.

Проверяем по HTTP ровно те вызовы, которые делают новые формы в widgets.html:
1. Goals: add → toggle done → clear-done.
2. Sub-goal: PUT target/current → increment(+1) → reset.
3. Schedule: add → список содержит блок → delete.
4. Counters: PUT создаёт новый ключ → increment → reset.
5. Countdown: PUT duration/mode → start → stop → reset.
6. Top donators: add → появился в recent → delete.
7. Song request: add → очередь → skip → clear.
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


async def test_goals_flow(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        add = (await c.post("/api/widgets/goals", json={"text": "100 подписчиков"})).json()
        assert add.get("id", 0) > 0
        gid = add["id"]

        items = (await c.get("/api/widgets/goals")).json()["items"]
        assert items[0]["text"] == "100 подписчиков"

        assert (await c.put(f"/api/widgets/goals/{gid}", json={"done": True})).json()["ok"] is True
        items = (await c.get("/api/widgets/goals")).json()["items"]
        assert items[0]["done"] in (1, True)

        cleared = (await c.post("/api/widgets/goals/clear-done")).json()
        assert cleared["ok"] is True and cleared["deleted"] == 1


async def test_sub_goal_flow(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        r = (await c.put("/api/widgets/sub-goal", json={"target": 10, "current": 3, "title": "Саб-цель"})).json()
        assert r["ok"] is True

        inc = (await c.post("/api/widgets/sub-goal/increment", json={"delta": 2})).json()
        assert inc["ok"] is True and inc["current"] == 5

        reset = (await c.post("/api/widgets/sub-goal/reset")).json()
        assert reset["ok"] is True and reset["current"] == 0


async def test_schedule_flow(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        add = (await c.post("/api/widgets/schedule", json={"start_time": "Пт 20:00", "title": "Dota", "emoji": "🎮"})).json()
        assert add.get("ok") is True
        bid = add["id"]

        blocks = await c.get("/api/widgets/schedule")
        data = blocks.json()
        assert any(b["id"] == bid and b["title"] == "Dota" for b in data)

        assert (await c.delete(f"/api/widgets/schedule/{bid}")).json()["ok"] is True
        assert all(b["id"] != bid for b in (await c.get("/api/widgets/schedule")).json())


async def test_counter_flow(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        r = (await c.put("/api/widgets/counters/death", json={"label": "Смерти", "value": 2})).json()
        assert r["ok"] is True

        counters = (await c.get("/api/widgets/counters")).json()
        assert any(c["key"] == "death" and c["value"] == 2 for c in counters)

        assert (await c.post("/api/widgets/counters/death/increment", json={"delta": 3})).json()["ok"] is True
        counters = (await c.get("/api/widgets/counters")).json()
        assert next(c for c in counters if c["key"] == "death")["value"] == 5

        assert (await c.post("/api/widgets/counters/death/reset")).json()["ok"] is True
        counters = (await c.get("/api/widgets/counters")).json()
        assert next(c for c in counters if c["key"] == "death")["value"] == 0


async def test_countdown_flow(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        r = (await c.put("/api/widgets/countdown", json={"mode": "countdown", "duration_sec": 300, "title": "Subathon"})).json()
        assert r["ok"] is True

        started = (await c.post("/api/widgets/countdown/start")).json()
        assert started["ok"] is True and started["state"] == "running"

        stopped = (await c.post("/api/widgets/countdown/stop")).json()
        assert stopped["ok"] is True and stopped["state"] != "running"

        reset = (await c.post("/api/widgets/countdown/reset")).json()
        assert reset["ok"] is True


async def test_top_donators_flow(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        r = (await c.post("/api/widgets/top-donators/add",
                          json={"username": "viewer1", "amount": 25.5, "currency": "USD", "message": "го контент"})).json()
        assert r.get("ok") is True, r

        data = (await c.get("/api/widgets/top-donators")).json()
        assert data["recent_donations"], "donation should be listed"
        did = data["recent_donations"][0]["id"]
        assert data["recent_donations"][0]["username"] == "viewer1"

        assert (await c.delete(f"/api/widgets/top-donators/{did}")).json()["ok"] is True
        data = (await c.get("/api/widgets/top-donators")).json()
        assert not data["recent_donations"]


async def test_song_request_flow(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        r = (await c.put("/api/widgets/song-request", json={"enabled": True, "visible": True})).json()
        assert r["ok"] is True

        add = (await c.post("/api/widgets/song-request/add",
                            json={"title": "Synthwave mix", "requested_by": "viewer1"})).json()
        assert add.get("ok") is True, add

        data = (await c.get("/api/widgets/song-request")).json()
        assert any(q["title"] == "Synthwave mix" for q in data["queue"])

        assert (await c.post("/api/widgets/song-request/skip")).json()["ok"] is True

        assert (await c.post("/api/widgets/song-request/clear")).json()["ok"] is True
        data = (await c.get("/api/widgets/song-request")).json()
        assert not data["queue"]
