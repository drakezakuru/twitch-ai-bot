"""Тесты для Smart Anti-Dead-Air (детектор затишья эфира per-bot).

Проверяем:
1. По умолчанию anti_dead_air_enabled выключен, check_dead_air возвращает False.
2. При включении, если время тишины < порога, возвращает False.
3. При наступлении тишины >= anti_dead_air_minutes вызывается генерация реплики для оживления.
4. После срабатывания действует кулдаун anti_dead_air_cooldown_min.
5. Любое новое сообщение в чате сбрасывает счетчик затишья.
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock
import pytest
import pytest_asyncio

from app import database
from app.chat_analyzer import ChatAnalyzer

pytestmark = pytest.mark.asyncio


class _FakeAI:
    async def get_response(self, *a, **kw):
        return "Как дела на стриме?"

    async def generate_text(self, *a, **kw):
        return "Как дела на стриме?"


class _FakeAuthor:
    def __init__(self, name):
        self.name = name


class _FakeChannel:
    def __init__(self, name):
        self.name = name


class _FakeMessage:
    def __init__(self, channel, author, content):
        self.channel = _FakeChannel(channel)
        self.author = _FakeAuthor(author)
        self.content = content


class _FakeInstance:
    def __init__(self, account_id, nickname="chat_bot"):
        self.account_id = account_id
        self.nickname = nickname
        self.token = "oauth:test"


@pytest_asyncio.fixture(autouse=True)
async def _reset_db(tmp_db, disable_auth):
    await database.init_db()
    yield


async def test_anti_dead_air_defaults_disabled():
    analyzer = ChatAnalyzer(ai=_FakeAI(), send_fn=AsyncMock())
    settings = analyzer.get_settings(1)
    assert settings["anti_dead_air_enabled"] is False
    assert settings["anti_dead_air_minutes"] == 3
    assert settings["anti_dead_air_cooldown_min"] == 10

    # Без включения не срабатывает
    res = await analyzer.check_dead_air(1, "main_channel", "bot1")
    assert res is False


async def test_anti_dead_air_triggers_after_silence():
    sent = []

    async def capture_send(account_id, channel, text, **kw):
        sent.append(text)
        return True

    analyzer = ChatAnalyzer(ai=_FakeAI(), send_fn=capture_send)
    aid = 42
    channel = "streamer_chan"

    analyzer.update_settings(aid, {
        "enabled": True,
        "anti_dead_air_enabled": True,
        "anti_dead_air_minutes": 2,          # 2 минуты порог
        "anti_dead_air_cooldown_min": 5,     # 5 минут кулдаун
    })

    # Первый вызов регистрирует активность канала и возвращает False
    res = await analyzer.check_dead_air(aid, channel, "bot_nick")
    assert res is False

    # Эмулируем, что прошло 60 секунд (меньше порога 2 мин)
    ch_key = (aid, channel)
    analyzer._channel_last_activity[ch_key] = time.time() - 60
    res = await analyzer.check_dead_air(aid, channel, "bot_nick")
    assert res is False

    # Эмулируем, что прошло 130 секунд (больше порога 2 мин = 120 сек)
    analyzer._channel_last_activity[ch_key] = time.time() - 130
    res = await analyzer.check_dead_air(aid, channel, "bot_nick")
    assert res is True
    assert len(sent) == 1

    # Повторный вызов сразу после срабатывания должен быть заблокирован кулдауном
    analyzer._channel_last_activity[ch_key] = time.time() - 150
    res2 = await analyzer.check_dead_air(aid, channel, "bot_nick")
    assert res2 is False


async def test_anti_dead_air_chat_activity_resets_silence():
    sent = []

    async def capture_send(account_id, channel, text, **kw):
        sent.append(text)
        return True

    analyzer = ChatAnalyzer(ai=_FakeAI(), send_fn=capture_send)
    aid = 99
    channel = "game_channel"

    analyzer.update_settings(aid, {
        "enabled": True,
        "anti_dead_air_enabled": True,
        "anti_dead_air_minutes": 1,
    })

    # Устанавливаем время активности в прошлом (90 сек назад)
    ch_key = (aid, channel)
    analyzer._channel_last_activity[ch_key] = time.time() - 90

    # Входящее сообщение в чат сбрасывает таймер затишья
    inst = _FakeInstance(aid, "my_bot")
    msg = _FakeMessage(channel, "random_viewer", "Всем привет!")
    await analyzer.on_message(inst, msg)

    # Проверяем, что таймер обновился на свежий timestamp
    assert time.time() - analyzer._channel_last_activity[ch_key] < 5

    # check_dead_air теперь должен вернуть False
    res = await analyzer.check_dead_air(aid, channel, "my_bot")
    assert res is False


async def test_anti_dead_air_channel_cooldown_prevents_multi_bot_storm():
    sent = []

    async def capture_send(account_id, channel, text, **kw):
        sent.append((account_id, text))
        return True

    analyzer = ChatAnalyzer(ai=_FakeAI(), send_fn=capture_send)
    channel = "shared_channel"
    aid1 = 101
    aid2 = 102

    analyzer.update_settings(aid1, {
        "enabled": True,
        "anti_dead_air_enabled": True,
        "anti_dead_air_minutes": 2,
        "anti_dead_air_cooldown_min": 5,
    })
    analyzer.update_settings(aid2, {
        "enabled": True,
        "anti_dead_air_enabled": True,
        "anti_dead_air_minutes": 2,
        "anti_dead_air_cooldown_min": 5,
    })

    # Устанавливаем затишье для обоих ботов
    now = time.time()
    analyzer._channel_last_activity[(aid1, channel)] = now - 200
    analyzer._channel_last_activity[(aid2, channel)] = now - 200

    # Первый бот срабатывает
    res1 = await analyzer.check_dead_air(aid1, channel, "bot1")
    assert res1 is True
    assert len(sent) == 1
    assert sent[0][0] == aid1

    # Второй бот на том же канале в ту же секунду блокируется канальным кулдауном
    res2 = await analyzer.check_dead_air(aid2, channel, "bot2")
    assert res2 is False
    assert len(sent) == 1
