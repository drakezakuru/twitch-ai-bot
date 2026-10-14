import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from httpx import AsyncClient, ASGITransport

from app.chat_analyzer import ChatAnalyzer
from app.server import app, chat_analyzer, bot_manager


@pytest.fixture(autouse=True)
def reset_pause_state():
    chat_analyzer.resume_all()
    yield
    chat_analyzer.resume_all()


def test_chat_analyzer_pause_controls():
    # Изначально паузы нет
    paused, rem = chat_analyzer.is_paused()
    assert not paused
    assert rem == 0

    # Ставим паузу на 120 секунд
    chat_analyzer.pause_all(120.0)
    paused, rem = chat_analyzer.is_paused()
    assert paused
    assert 115 <= rem <= 120

    # Снимаем паузу
    chat_analyzer.resume_all()
    paused, rem = chat_analyzer.is_paused()
    assert not paused
    assert rem == 0


@pytest.mark.asyncio
async def test_quick_action_api_pause_resume():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Проверяем статус
        resp = await client.get("/api/director/quick-action?action=status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["paused"] is False

        # 2. Ставим паузу через GET (как из Stream Deck)
        resp = await client.get("/api/director/quick-action?action=pause_2m")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["paused"] is True
        assert data["remaining_sec"] == 120

        # 3. Проверяем обновленный статус
        resp = await client.get("/api/director/quick-action?action=status")
        assert resp.status_code == 200
        assert resp.json()["paused"] is True

        # 4. Возобновляем через POST
        resp = await client.post("/api/director/quick-action", json={"action": "resume"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["paused"] is False

        # 5. Проверяем, что пауза снята
        paused, _ = chat_analyzer.is_paused()
        assert not paused


@pytest.mark.asyncio
async def test_quick_action_hype_emotes():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch.object(bot_manager, "get_all_statuses", return_value={
            1: {"connected": True, "channels": ["#testchan"], "nickname": "hype_bot_1"},
            2: {"connected": True, "channels": ["#testchan"], "nickname": "hype_bot_2"},
        }), patch.object(bot_manager, "send_message", new_callable=AsyncMock) as mock_send:
            resp = await client.post("/api/director/quick-action", json={
                "action": "hype_emotes",
                "channel": "testchan",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            assert data["action"] == "hype_emotes"
            assert data["sent_count"] == 2
            assert "emote" in data


@pytest.mark.asyncio
async def test_quick_action_break_silence():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch.object(bot_manager, "get_all_statuses", return_value={
            1: {"connected": True, "channels": ["#testchan"], "nickname": "quiet_bot"},
        }), patch.object(chat_analyzer, "check_dead_air", new_callable=AsyncMock, return_value=True) as mock_dead_air:
            resp = await client.post("/api/director/quick-action", json={
                "action": "break_silence",
                "channel": "testchan",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            assert data["action"] == "break_silence"
            assert data["bot"] == "quiet_bot"
            assert data["dispatched"] is True
            mock_dead_air.assert_awaited_once_with(1, "testchan", "quiet_bot", force=True)


@pytest.mark.asyncio
async def test_pause_suppresses_emotes_and_normal_generation():
    chat_analyzer.pause_all(60.0)

    # 1. _try_emote_humanizer должен вернуть False сразу
    with patch.object(chat_analyzer, "get_settings", return_value={"emote_humanizer_enabled": True}):
        res = await chat_analyzer._try_emote_humanizer(1, "testchan", "bot1")
        assert res is False

    # 2. _generate_and_send без force должен заблокироваться
    with patch.object(chat_analyzer, "_role_reply_gate", new_callable=AsyncMock, return_value=(True, "")) as mock_role:
        await chat_analyzer._generate_and_send(
            1, "testchan", "bot1", "author", "text", is_mention=False, force=False
        )
        # До role gate даже не доходит, так как pause срабатывает раньше
        mock_role.assert_not_called()


@pytest.mark.asyncio
async def test_quick_action_break_silence_filters_out_lurkers():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Бот 1 - lurker (не может писать), Бот 2 - chatter (может писать)
        with patch.object(bot_manager, "get_all_statuses", return_value={
            1: {"connected": True, "channels": ["#testchan"], "nickname": "lurker_bot"},
            2: {"connected": True, "channels": ["#testchan"], "nickname": "active_chatter"},
        }), patch.object(chat_analyzer, "_role_reply_gate", side_effect=[
            (False, "lurker молчит"),
            (True, ""),
        ]), patch.object(chat_analyzer, "check_dead_air", new_callable=AsyncMock, return_value=True) as mock_dead_air:
            resp = await client.post("/api/director/quick-action", json={
                "action": "break_silence",
                "channel": "testchan",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            # Должен быть выбран именно active_chatter (aid=2), а не lurker (aid=1)
            assert data["bot"] == "active_chatter"
            mock_dead_air.assert_awaited_once_with(2, "testchan", "active_chatter", force=True)
