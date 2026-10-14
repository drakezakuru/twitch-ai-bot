"""§9.3 WIDGETS_PLAN: subathon-timer, emoji-leaderboard,
hype-meter (клиентский — проверяем только файл/роут).

poll-overlay выведен из эксплуатации (owner survey Q28): оверлей и свой
!vote-опрос удалены, остались нативные Twitch Polls — их тесты живут в
test_widget_owner_decisions.py.
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


async def test_subathon_flow_and_donation_extension(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        # not running
        pub = (await c.get("/api/widgets/public/subathon")).json()
        assert pub["running"] is False
        # start 30 min
        assert (await c.post("/api/widgets/subathon/start", json={"minutes": 30})).json()["ok"]
        pub = (await c.get("/api/widgets/public/subathon")).json()
        assert pub["running"] is True and 25*60 < pub["remaining"] <= 30*60
        # donation продлевает
        from app.widgets import on_donation_event
        await on_donation_event("Alice", 100, "RUB", "го")
        pub2 = (await c.get("/api/widgets/public/subathon")).json()
        assert pub2["remaining"] > pub["remaining"]
        # sub продлевает на seconds_per_sub (60 default) — через прямой хук
        from app.widgets import on_subscribe_event
        await on_subscribe_event()
        pub3 = (await c.get("/api/widgets/public/subathon")).json()
        assert pub3["remaining"] >= pub2["remaining"] + 55
        # stop
        assert (await c.post("/api/widgets/subathon/stop")).json()["ok"]
        pub4 = (await c.get("/api/widgets/public/subathon")).json()
        assert pub4["running"] is False
        # настройки
        put = (await c.put("/api/widgets/subathon", json={"seconds_per_sub": 90, "title": "САБАТОН"})).json()
        assert put["ok"] is True


async def test_retired_poll_overlay_keeps_url_without_vote_api(tmp_db, disable_auth):
    """Q28: оверлей и !vote-API удалены, URL отвечает тёмной заглушкой."""
    import app.widgets as W
    assert not hasattr(W, "handle_poll_vote"), "!vote-обработчик вернулся"
    async with await _client(tmp_db) as c:
        assert (await c.get("/api/widgets/public/poll")).status_code == 404
        assert (await c.post("/api/widgets/poll", json={
            "question": "x", "choices": ["a", "b"]})).status_code == 404
        r = await c.get("/widget/poll-overlay")
        assert r.status_code == 200 and "#0f0f1a" in r.text


async def test_emoji_leaderboard_counts(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        from app.widgets import on_chat_emoji, _count_emojis
        assert _count_emojis("привет 😀🔥🔥") == 3
        assert _count_emojis("просто текст") == 0
        await on_chat_emoji("alice", "😀🔥🔥")
        await on_chat_emoji("alice", "😀")
        await on_chat_emoji("bob", "😂")
        pub = (await c.get("/api/widgets/public/emoji-leaderboard")).json()
        items = pub["items"]
        assert items[0]["username"] == "alice" and items[0]["count"] == 4
        assert items[1]["username"] == "bob"


async def test_extra_widget_routes_serve_files():
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport
    from app.widgets import public_router
    app = FastAPI()
    app.include_router(public_router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        for path, marker in (
            ("/widget/hype-meter", "HYPE"),
            ("/widget/subathon-timer", "SUBATHON"),
            ("/widget/emoji-leaderboard", "LEADERBOARD"),
        ):
            r = await c.get(path)
            assert r.status_code == 200 and marker in r.text
