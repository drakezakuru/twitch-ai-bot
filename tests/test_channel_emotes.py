"""Тесты для сбора и синхронизации смайлов канала (7TV, BTTV, FFZ)."""
import pytest
from httpx import ASGITransport, AsyncClient

from app import channel_emotes
from app.server import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.asyncio
async def test_channel_emotes_mocked_fetch(monkeypatch):
    """Проверка сборщиков смайлов из 7TV, BTTV и FFZ."""
    async def fake_get(client, url):
        if "7tv.io/v3/emote-sets/global" in url:
            return {"emotes": [{"name": "peepoHappy"}, {"name": "KEKW"}]}
        if "7tv.io/v3/users/twitch" in url:
            return {"emote_set": {"emotes": [{"name": "streamerClap"}]}}
        if "betterttv.net/3/cached/emotes/global" in url:
            return [{"code": "monkaS"}, {"code": "LULW"}]
        if "betterttv.net/3/cached/users/twitch" in url:
            return {"channelEmotes": [{"code": "customBTTV"}], "sharedEmotes": [{"code": "sharedBTTV"}]}
        if "frankerfacez.com/v1/room" in url:
            return {"sets": {"1": {"emoticons": [{"name": "PogChampFFZ"}]}}}
        if "frankerfacez.com/v1/set/global" in url:
            return {"sets": {"0": {"emoticons": [{"name": "CatBag"}]}}}
        return None

    monkeypatch.setattr(channel_emotes, "_safe_fetch_json", fake_get)
    monkeypatch.setattr(channel_emotes, "_resolve_twitch_user_id", lambda ch: "123456")

    summary = await channel_emotes.sync_channel_emotes("mycoolchannel")
    assert summary["ok"] is True
    assert summary["channel"] == "mycoolchannel"
    assert summary["total_count"] > 0
    assert summary["sources"]["7tv"] >= 3
    assert summary["sources"]["bttv"] >= 4
    assert summary["sources"]["ffz"] >= 2

    cached = channel_emotes.get_cached_channel_emotes("mycoolchannel")
    assert "peepoHappy" in cached
    assert "streamerClap" in cached
    assert "customBTTV" in cached
    assert "PogChampFFZ" in cached
    assert "CatBag" in cached

    # Summary
    sum_data = channel_emotes.get_channel_emotes_summary("mycoolchannel")
    assert sum_data["ok"] is True
    assert sum_data["total_count"] == summary["total_count"]


@pytest.mark.asyncio
async def test_channel_emotes_api_endpoints(monkeypatch):
    """Проверка REST эндпоинтов GET и POST для смайлов."""
    channel_emotes._EMOTE_CACHE.clear()
    channel_emotes._EMOTE_DETAILS_CACHE.clear()

    async def fake_get(client, url):
        if "7tv.io" in url:
            return {"emotes": [{"name": "EZ"}]}
        return None

    monkeypatch.setattr(channel_emotes, "_safe_fetch_json", fake_get)
    monkeypatch.setattr(channel_emotes, "_resolve_twitch_user_id", lambda ch: "")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # GET summary
        res = await ac.get("/api/channels/coolstreamer/emotes")
        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is True
        assert data["channel"] == "coolstreamer"

        # POST sync
        res_sync = await ac.post("/api/channels/coolstreamer/emotes/sync")
        assert res_sync.status_code == 200
        data_sync = res_sync.json()
        assert data_sync["ok"] is True
        assert data_sync["channel"] == "coolstreamer"
        assert "EZ" in data_sync["sample"]

        # GET full
        res_full = await ac.get("/api/channels/coolstreamer/emotes?full=1")
        assert res_full.status_code == 200
        assert "all_emotes" in res_full.json()
        assert "EZ" in res_full.json()["all_emotes"]


@pytest.mark.asyncio
async def test_emote_humanizer_uses_channel_emotes(monkeypatch):
    """Проверка, что chat_analyzer._try_emote_humanizer распознает смайлы канала."""
    from unittest.mock import AsyncMock
    from app.chat_analyzer import ChatAnalyzer

    analyzer = ChatAnalyzer(ai=AsyncMock(), send_fn=AsyncMock())
    monkeypatch.setattr(analyzer, "is_paused", lambda: (False, ""))
    monkeypatch.setattr(
        analyzer,
        "get_settings",
        lambda aid: {
            "emote_humanizer_enabled": True,
            "emote_humanizer_chance": 100,
            "emote_humanizer_cooldown": 0,
        },
    )

    # Канал с уникальным смайлом
    channel_emotes._EMOTE_CACHE["memechannel"] = (
        9999999999.0,
        ["POGGERS_SUPER_CUSTOM", "HYPER_CLAP"],
    )

    # Заполняем буфер чата сообщениями со смайлом канала
    buf_key = analyzer._buffer_key(1, "memechannel")
    analyzer._chat_buffer[buf_key] = [
        {"author": "viewer1", "text": "хаха POGGERS_SUPER_CUSTOM"},
        {"author": "viewer2", "text": "да POGGERS_SUPER_CUSTOM"},
        {"author": "viewer3", "text": "POGGERS_SUPER_CUSTOM POGGERS_SUPER_CUSTOM"},
    ]

    sent_messages = []

    async def fake_send_chat(aid, ch, text):
        sent_messages.append((aid, ch, text))
        return True

    analyzer.send_fn = fake_send_chat

    res = await analyzer._try_emote_humanizer(1, "memechannel", "botnick")
    assert res is True
    assert len(sent_messages) == 1
    assert "POGGERS_SUPER_CUSTOM" in sent_messages[0][2]
