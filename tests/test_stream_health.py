"""Дашборд «здоровье эфира» (владелец, 27.09.2026 вечером): одна таблица
«кто подключён / отвечает / молчит и почему», см. app/stream_health.py.

Live-снимок: причина молчания читается из ChatAnalyzer._role_reply_gate
(тот же гейт, что использует реальный чат-пайплайн), без изменений в самом
пайплайне и без нового журнала.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.database import get_db, init_db

pytestmark = pytest.mark.asyncio


async def _client():
    from app.server import app
    await init_db()
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


async def _make_bot(nickname: str, bot_role: str = "chatter", enabled: int = 1,
                     channel: str = "streamer1", binding_enabled: int = 1) -> int:
    await init_db()
    db = await get_db()
    try:
        cur = await db.execute(
            "INSERT INTO accounts(nickname, token, enabled, bot_role) VALUES (?, 'x', ?, ?)",
            (nickname, enabled, bot_role),
        )
        await db.commit()
        account_id = cur.lastrowid
        await db.execute(
            "INSERT INTO channels(account_id, channel_name, enabled) VALUES (?, ?, ?)",
            (account_id, channel, binding_enabled),
        )
        await db.commit()
        return account_id
    finally:
        await db.close()


async def test_disabled_bot_reports_silent_with_reason():
    await _make_bot("offbot", enabled=0)
    async with await _client() as client:
        resp = await client.get("/api/stream-health")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        bot = data["channels"][0]["bots"][0]
        assert bot["silent"] is True
        assert bot["reason"] == "бот выключен"
        assert bot["connected"] is False


async def test_disabled_binding_reports_silent_with_reason():
    await _make_bot("boundoff", binding_enabled=0)
    async with await _client() as client:
        data = (await client.get("/api/stream-health")).json()
        bot = data["channels"][0]["bots"][0]
        assert bot["silent"] is True
        assert bot["reason"] == "канал отключён у этого бота"


async def test_not_connected_enabled_bot_is_silent_not_connected():
    await _make_bot("neverjoined")
    async with await _client() as client:
        data = (await client.get("/api/stream-health")).json()
        bot = data["channels"][0]["bots"][0]
        assert bot["connected"] is False
        assert bot["silent"] is True
        assert bot["reason"] == "не подключён"


async def test_channel_filter_only_returns_that_channel():
    await _make_bot("a", channel="chan_a")
    await _make_bot("b", channel="chan_b")
    async with await _client() as client:
        data = (await client.get("/api/stream-health?channel=chan_a")).json()
        assert [c["channel"] for c in data["channels"]] == ["chan_a"]


async def test_connected_lurker_without_mention_is_silent_by_role_gate(monkeypatch):
    account_id = await _make_bot("lurky", bot_role="lurker")
    from app.server import bot_manager
    monkeypatch.setattr(bot_manager, "get_status", lambda aid: (
        {"connected": True, "channels": ["streamer1"], "last_error": ""}
        if aid == account_id else {"connected": False, "channels": []}
    ))
    async with await _client() as client:
        data = (await client.get("/api/stream-health")).json()
        bot = data["channels"][0]["bots"][0]
        assert bot["connected"] is True
        assert bot["silent"] is True
        assert "mention_reply" in bot["reason"]


async def test_connected_chatter_is_not_silent(monkeypatch):
    account_id = await _make_bot("chatty", bot_role="chatter")
    from app.server import bot_manager
    monkeypatch.setattr(bot_manager, "get_status", lambda aid: (
        {"connected": True, "channels": ["streamer1"], "last_error": ""}
        if aid == account_id else {"connected": False, "channels": []}
    ))
    async with await _client() as client:
        data = (await client.get("/api/stream-health")).json()
        bot = data["channels"][0]["bots"][0]
        assert bot["connected"] is True
        assert bot["silent"] is False
        assert bot["reason"] == ""


async def test_director_is_always_silent_with_friendly_reason(monkeypatch):
    account_id = await _make_bot("boss", bot_role="director")
    from app.server import bot_manager
    monkeypatch.setattr(bot_manager, "get_status", lambda aid: (
        {"connected": True, "channels": ["streamer1"], "last_error": ""}
        if aid == account_id else {"connected": False, "channels": []}
    ))
    async with await _client() as client:
        data = (await client.get("/api/stream-health")).json()
        bot = data["channels"][0]["bots"][0]
        assert bot["silent"] is True
        assert bot["reason"] == "Режиссёр не пишет в чат — только наблюдает и планирует"


async def test_stream_health_channel_live_state(monkeypatch):
    await _make_bot("testbot", channel="livechan")
    import app.routes
    monkeypatch.setattr(app.routes, "is_helix_configured", lambda: True)
    async def fake_get_channel_info(channel, token):
        return {"channel": channel, "is_live": True, "viewer_count": 123, "game_name": "Just Chatting", "title": "Chill Stream"}
    monkeypatch.setattr(app.routes, "get_channel_info", fake_get_channel_info)

    async with await _client() as client:
        data = (await client.get("/api/stream-health?channel=livechan")).json()
        ch = data["channels"][0]
        assert ch["channel"] == "livechan"
        assert ch["is_live"] is True
        assert ch["viewer_count"] == 123
        assert ch["game_name"] == "Just Chatting"
        assert ch["title"] == "Chill Stream"