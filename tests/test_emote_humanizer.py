"""Тесты для Emote Humanizer (быстрая реакция смайликами на хайп без вызова LLM).

Проверяем:
1. По умолчанию выключен.
2. При включении и наличии смайликов в буфере подхватывает доминирующий смайл (KEKW, Pog и т.д.)
   и отправляет его без обращения к AI.
3. Соблюдает кулдаун между реакциями.
4. При отсутствии смайликов/шума возвращает False.
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock
import pytest
import pytest_asyncio

from app import database
from app.chat_analyzer import ChatAnalyzer

pytestmark = pytest.mark.asyncio


class _MockAI:
    def __init__(self):
        self.call_count = 0

    async def get_response(self, *a, **kw):
        self.call_count += 1
        return "AI ответ"

    async def generate_text(self, *a, **kw):
        self.call_count += 1
        return "AI ответ"


@pytest_asyncio.fixture(autouse=True)
async def _reset_db(tmp_db, disable_auth):
    await database.init_db()
    yield


async def test_emote_humanizer_defaults_disabled():
    mock_ai = _MockAI()
    analyzer = ChatAnalyzer(ai=mock_ai, send_fn=AsyncMock())
    settings = analyzer.get_settings(1)
    assert settings["emote_humanizer_enabled"] is False

    res = await analyzer._try_emote_humanizer(1, "main", "bot1")
    assert res is False
    assert mock_ai.call_count == 0


async def test_emote_humanizer_reacts_to_hype_emotes():
    sent = []

    async def capture_send(account_id, channel, text, **kw):
        sent.append(text)
        return True

    mock_ai = _MockAI()
    analyzer = ChatAnalyzer(ai=mock_ai, send_fn=capture_send)
    aid = 10
    channel = "chan1"

    analyzer.update_settings(aid, {
        "enabled": True,
        "emote_humanizer_enabled": True,
        "emote_humanizer_chance": 100,  # 100% шанс в тесте
        "emote_humanizer_cooldown": 20,
    })

    # Наполняем буфер спамом KEKW
    buf_key = analyzer._buffer_key(aid, channel)
    analyzer._chat_buffer[buf_key] = [
        {"author": "user1", "text": "KEKW", "time": time.time()},
        {"author": "user2", "text": "KEKW KEKW", "time": time.time()},
        {"author": "user3", "text": "kekw ахаха", "time": time.time()},
    ]

    res = await analyzer._try_emote_humanizer(aid, channel, "my_bot")
    assert res is True
    assert len(sent) == 1
    assert "KEKW" in sent[0].upper()
    # LLM НЕ должна была вызываться
    assert mock_ai.call_count == 0

    # Повторный вызов блокируется кулдауном
    res2 = await analyzer._try_emote_humanizer(aid, channel, "my_bot")
    assert res2 is False
    assert len(sent) == 1


async def test_emote_humanizer_ignores_normal_chat():
    sent = []

    async def capture_send(account_id, channel, text, **kw):
        sent.append(text)
        return True

    mock_ai = _MockAI()
    analyzer = ChatAnalyzer(ai=mock_ai, send_fn=capture_send)
    aid = 11
    channel = "serious_chan"

    analyzer.update_settings(aid, {
        "enabled": True,
        "emote_humanizer_enabled": True,
        "emote_humanizer_chance": 100,
    })

    # Обычный разговорный чат без эмоутов хайпа
    buf_key = analyzer._buffer_key(aid, channel)
    analyzer._chat_buffer[buf_key] = [
        {"author": "user1", "text": "Какая погода сегодня на улице?", "time": time.time()},
        {"author": "user2", "text": "Кажется собирается дождь, нужно зонт взять", "time": time.time()},
    ]

    res = await analyzer._try_emote_humanizer(aid, channel, "my_bot")
    assert res is False
    assert len(sent) == 0
