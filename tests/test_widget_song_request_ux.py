"""§11.5 WIDGETS_PLAN: Song Request UX — cooldown и лимит на юзера.

1. PUT song-request принимает cooldown_sec / max_per_user.
2. add_song_request: user_limit (сколько pending-треков на юзера),
   cooldown (retry_after), обе ошибки различимы для чат-ответов.
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


async def test_sr_settings_accept_ux_fields(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        put = (await c.put("/api/widgets/song-request", json={
            "cooldown_sec": 45, "max_per_user": 3})).json()
        assert put["ok"] is True
        s = (await c.get("/api/widgets/song-request")).json()
        assert s["cooldown_sec"] == 45 and s["max_per_user"] == 3


async def test_sr_user_limit(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        await c.put("/api/widgets/song-request", json={"max_per_user": 1, "cooldown_sec": 0})
        from app.widgets import add_song_request
        r1 = await add_song_request("Track A", "user1", "chan")
        assert r1.get("ok") is True
        # Track A сразу получает status='playing' (очередь пуста) —
        # поэтому первый pending у user1 ещё свободен.
        r2 = await add_song_request("Track B", "user1", "chan")
        assert r2.get("ok") is True
        r3 = await add_song_request("Track D", "user1", "chan")
        assert r3.get("error") == "user_limit"
        # другой юзер не ограничен
        r4 = await add_song_request("Track C", "user2", "chan")
        assert r4.get("ok") is True


async def test_sr_cooldown(tmp_db, disable_auth, monkeypatch):
    async with await _client(tmp_db) as c:
        await c.put("/api/widgets/song-request", json={"cooldown_sec": 60, "max_per_user": 0})
        import app.widgets as W
        W._sr_user_last.clear()
        from app.widgets import add_song_request
        r1 = await add_song_request("Track A", "user1", "chan")
        assert r1.get("ok") is True
        r2 = await add_song_request("Track B", "user1", "chan")
        assert r2.get("error") == "cooldown"
        assert 0 < r2.get("retry_after", 0) <= 60
        # другой юзер не в cooldown
        r3 = await add_song_request("Track C", "user2", "chan")
        assert r3.get("ok") is True
