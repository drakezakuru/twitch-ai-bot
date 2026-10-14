"""Решения владельца 28.08.2026: Twitch Polls, emote-картинки, media-share.

Внешние API (Helix, BTTV, 7TV) мокаются — сети нет.
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
    for r in (admin_router, public_router):
        app.include_router(r)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
    def json(self):
        return self._payload


async def test_twitch_poll_normalize_and_get(tmp_db, monkeypatch):
    async with await _client(tmp_db) as c:
        import app.twitch_polls as tp
        from app.twitch_helix import HELIX_BASE

        async def fake_get_active(account_id, channel, force=False):
            return {
                "id": "p1", "title": "Кто?", "status": "ACTIVE",
                "choices": [{"title": "Катя", "votes": 5}, {"title": "Маша", "votes": 3}],
            }
        monkeypatch.setattr(tp, "get_active_poll", fake_get_active)

        r = (await c.get("/api/widgets/public/twitch-poll",
                         params={"account_id": 1, "channel": "chan"})).json()
        assert r["poll"]["title"] == "Кто?" and r["poll"]["choices"][0]["votes"] == 5
        # без параметров — пусто
        r2 = (await c.get("/api/widgets/public/twitch-poll")).json()
        assert r2["poll"] is None


async def test_twitch_poll_create_validation_and_helix(tmp_db, monkeypatch):
    async with await _client(tmp_db) as c:
        import app.twitch_polls as tp
        from app.twitch_helix import HELIX_BASE

        # валидация: <2 вариантов
        r = (await c.post("/api/widgets/twitch-poll", json={
            "account_id": 1, "channel": "chan", "title": "x",
            "choices": ["only one"]})).json()
        assert r["error"] == "title_and_2_choices_required"

        # мок авторизации broadcaster + httpx.post
        async def fake_bc(account_id, channel, required_scopes):
            return "12345", {"Authorization": "Bearer x", "Client-Id": "cid"}, "tok", ""
        monkeypatch.setattr(tp, "_broadcaster_and_headers", fake_bc)
        captured = {}
        class FakeClient:
            def __init__(self, *a, **k): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, url, headers=None, json=None):
                captured["url"] = url; captured["json"] = json
                return _FakeResp({"data": [{
                    "id": "p9", "title": json["title"], "status": "ACTIVE",
                    "duration_seconds": json["duration_seconds"],
                    "choices": [{"title": ch["title"], "votes": 0} for ch in json["choices"]],
                }]})
        import httpx as _httpx
        monkeypatch.setattr(_httpx, "AsyncClient", FakeClient)
        r = (await c.post("/api/widgets/twitch-poll", json={
            "account_id": 1, "channel": "chan", "title": "Кто победит?",
            "choices": ["Катя", "Маша", "Третий", "4", "5", "6"]})).json()
        assert r["ok"] is True and len(r["poll"]["choices"]) == 5  # clamp до 5
        assert captured["url"].endswith("/polls")


async def test_emotes_public_mocked(tmp_db, monkeypatch):
    async with await _client(tmp_db) as c:
        import app.widgets as W
        async def fake_fetch(url):
            if "betterttv.net/3/cached/emotes/global" in url:
                return [{"code": "Kappa", "id": "bttv1"},
                        {"code": "KEKW", "id": "bttv2"}]
            if "7tv.io" in url:
                return {"emotes": [{"name": "peepoHappy",
                                    "data": {"host": {"url": "//cdn.7tv.app/emote/abc",
                                                      "files": [{"name": "1x.webp"}, {"name": "2x.webp"}]}}}]}
            return None
        monkeypatch.setattr(W, "_fetch_json", fake_fetch)
        # токенов нет — Twitch-эмоции пропускаются
        r = (await c.get("/api/widgets/public/emotes")).json()
        em = r["emotes"]
        assert em["Kappa"] == "https://cdn.betterttv.net/emote/bttv1/2x"
        assert em["peepoHappy"].startswith("https://cdn.7tv.app/emote/abc/2x.webp")
        # кэш: второй вызов из кэша
        r2 = (await c.get("/api/widgets/public/emotes")).json()
        assert r2["emotes"]["KEKW"].endswith("/2x")


async def test_media_share_route_and_public_next(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        r = await c.get("/widget/media-share")
        assert r.status_code == 200
        assert "onYouTubeIframeAPIReady" in r.text
        assert "pause_media" in r.text  # автопауза при TTS через widget_bus
        # публичный next (пустая очередь — не падает)
        r2 = (await c.post("/api/widgets/public/song-request/next")).json()
        assert r2.get("ok") is True


async def test_retired_poll_overlay_keeps_url_and_emoji_chat_works():
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport
    from app.widgets import public_router
    app = FastAPI()
    app.include_router(public_router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # Q28: оверлей выведен, URL живёт заглушкой (нативные Twitch Polls остались).
        r = await c.get("/widget/poll-overlay")
        assert r.status_code == 200
        assert "#0f0f1a" in r.text and "loadCustom" not in r.text
        r2 = await c.get("/widget/emoji-chat")
        assert "renderMessage" in r2.text and "public/emotes" in r2.text
