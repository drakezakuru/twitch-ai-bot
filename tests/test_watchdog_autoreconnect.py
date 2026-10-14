"""Тест автовосстановления ботов при обрыве связи (Watchdog autoreconnect)."""
from __future__ import annotations

import asyncio
import time
import pytest

pytestmark = pytest.mark.asyncio


async def test_watchdog_autorecovers_stuck_error(tmp_db, monkeypatch):
    from app.bot_manager import TwitchBotManager, BotInstance

    manager = TwitchBotManager()
    started_reconnect = []

    async def fake_start_bot(aid, nickname, token, channels, proxy=""):
        started_reconnect.append((aid, nickname))
        return True

    monkeypatch.setattr(manager, "start_bot", fake_start_bot)

    # Задаём желаемое состояние
    manager.set_desired(10, {"nickname": "dropper", "token": "t", "channels": ["ch"], "proxy": ""})

    # Создаём зависший инстанс бота (connected=False, state="error", last_error_at 150s ago)
    inst = BotInstance(
        account_id=10,
        nickname="dropper",
        token="t",
        channels=["ch"],
        connected=False,
        state="error",
        last_error="Connection reset by peer",
        last_error_at=time.time() - 150.0,
    )
    manager._bots[10] = inst

    # Запускаем watchdog
    wd = asyncio.create_task(manager.watchdog_loop(interval=0.05))
    await asyncio.sleep(0.2)
    wd.cancel()
    await asyncio.gather(wd, return_exceptions=True)

    assert len(started_reconnect) >= 1
    assert started_reconnect[0] == (10, "dropper")
