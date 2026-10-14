"""Тесты изолированного запуска и остановки ботов по конкретному каналу.

POST /api/channels/{channel}/start
POST /api/channels/{channel}/stop
POST /api/accounts/{account_id}/start?channel=...
"""
from __future__ import annotations

import sys
from types import ModuleType

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


def _build_app():
    from fastapi import FastAPI
    from app.routes import router, actor_middleware
    from app.bulk_channels_routes import router as bulk_channels_router

    app = FastAPI()
    app.middleware("http")(actor_middleware)
    app.include_router(router)
    app.include_router(bulk_channels_router)
    return app


@pytest.fixture(autouse=True)
def clean_instance_locks(monkeypatch, tmp_path):
    from app import instance_lock
    for aid in list(instance_lock._flocked.keys()):
        instance_lock.release_account_lock(aid)
    instance_lock._flocked.clear()
    monkeypatch.setattr(instance_lock, "LOCKS_DIR", tmp_path / "locks")
    yield
    for aid in list(instance_lock._flocked.keys()):
        instance_lock.release_account_lock(aid)
    instance_lock._flocked.clear()


@pytest.fixture()
def fake_bot_manager(monkeypatch):
    """Мок менеджера ботов для изоляции тестов."""
    class FakeBotInstance:
        def __init__(self, account_id, nickname, token, channels, proxy=""):
            self.account_id = account_id
            self.nickname = nickname
            self.token = token
            self.channels = list(channels)
            self.proxy = proxy
            self.connected = True
            self.state = "connected"

    class FakeBotManager:
        def __init__(self):
            self._bots = {}
            self._desired = {}

        def is_running(self, account_id: int) -> bool:
            return account_id in self._bots

        def get_status(self, account_id: int) -> dict:
            bot = self._bots.get(account_id)
            if not bot:
                return {"connected": False, "channels": []}
            return {
                "connected": bot.connected,
                "state": bot.state,
                "channels": list(bot.channels),
            }

        def get_all_statuses(self) -> dict:
            return {aid: self.get_status(aid) for aid in self._bots}

        def get_desired(self, account_id: int) -> dict | None:
            return self._desired.get(account_id)

        def set_desired(self, account_id: int, params: dict | None) -> None:
            if params is None:
                self._desired.pop(account_id, None)
            else:
                self._desired[account_id] = params

        async def start_bot(self, account_id: int, nickname: str, token: str, channels: list[str], proxy: str = "") -> bool:
            if account_id in self._bots:
                return False
            self._bots[account_id] = FakeBotInstance(account_id, nickname, token, channels, proxy)
            return True

        async def stop_bot(self, account_id: int) -> bool:
            if account_id not in self._bots:
                return False
            del self._bots[account_id]
            return True

        async def join_channel(self, account_id: int, channel: str) -> bool:
            bot = self._bots.get(account_id)
            if not bot:
                return False
            if channel not in bot.channels:
                bot.channels.append(channel)
            return True

        async def leave_channel(self, account_id: int, channel: str) -> bool:
            bot = self._bots.get(account_id)
            if not bot:
                return False
            if channel in bot.channels:
                bot.channels.remove(channel)
            return True

    manager = FakeBotManager()

    # Патчим bot_manager в app.server
    saved = sys.modules.get("app.server")
    fake_server = ModuleType("app.server")
    fake_server.bot_manager = manager
    fake_server.eventsub_manager = None
    fake_server.chat_analyzer = None
    sys.modules["app.server"] = fake_server

    try:
        yield manager
    finally:
        if saved is not None:
            sys.modules["app.server"] = saved
        else:
            sys.modules.pop("app.server", None)


async def test_channel_start_connects_only_to_target_channel(tmp_db, disable_auth, fake_bot_manager):
    from app import database
    await database.init_db()

    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        # Создаем бота
        r = await client.post("/api/accounts", json={"nickname": "multi_bot", "token": "oauth:token123"})
        assert r.status_code == 200
        bot_id = r.json()["id"]

        # Привязываем бота к ДВУМ каналам: chan_a и chan_b
        await client.post(f"/api/accounts/{bot_id}/channels", json={"channel_name": "chan_a"})
        await client.post(f"/api/accounts/{bot_id}/channels", json={"channel_name": "chan_b"})

        # Запускаем канал chan_a
        start_res = await client.post("/api/channels/chan_a/start")
        assert start_res.status_code == 200
        data = start_res.json()
        assert data["ok"] is True
        assert len(data["started"]) == 1
        assert data["started"][0]["id"] == bot_id

        # Проверяем, что бот запущен ИСКЛЮЧИТЕЛЬНО на chan_a!
        status = fake_bot_manager.get_status(bot_id)
        assert status["connected"] is True
        assert status["channels"] == ["chan_a"]
        # chan_b НЕ должен быть подключен!
        assert "chan_b" not in status["channels"]


async def test_channel_start_skips_bots_busy_on_other_channel(tmp_db, disable_auth, fake_bot_manager):
    from app import database
    await database.init_db()

    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        r = await client.post("/api/accounts", json={"nickname": "busy_bot", "token": "oauth:token456"})
        bot_id = r.json()["id"]
        await client.post(f"/api/accounts/{bot_id}/channels", json={"channel_name": "stream_one"})
        await client.post(f"/api/accounts/{bot_id}/channels", json={"channel_name": "stream_two"})

        # Запускаем канал stream_one
        await client.post("/api/channels/stream_one/start")
        assert fake_bot_manager.get_status(bot_id)["channels"] == ["stream_one"]

        # Теперь пробуем запустить канал stream_two
        res2 = await client.post("/api/channels/stream_two/start")
        assert res2.status_code == 200
        d2 = res2.json()
        assert d2["ok"] is True
        assert len(d2["started"]) == 0
        assert len(d2["skipped"]) == 1
        assert d2["skipped"][0]["reason"] == "busy_on_other_channel"

        # Бот по-прежнему остался ТОЛЬКО на stream_one!
        assert fake_bot_manager.get_status(bot_id)["channels"] == ["stream_one"]


async def test_channel_stop_shuts_down_single_channel_bot(tmp_db, disable_auth, fake_bot_manager):
    from app import database
    await database.init_db()

    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        r = await client.post("/api/accounts", json={"nickname": "solo_bot", "token": "oauth:token789"})
        bot_id = r.json()["id"]
        await client.post(f"/api/accounts/{bot_id}/channels", json={"channel_name": "live_chan"})

        # Запускаем канал
        await client.post("/api/channels/live_chan/start")
        assert fake_bot_manager.is_running(bot_id) is True

        # Останавливаем канал
        stop_res = await client.post("/api/channels/live_chan/stop")
        assert stop_res.status_code == 200
        assert stop_res.json()["ok"] is True
        assert len(stop_res.json()["stopped"]) == 1

        # Бот полностью остановлен
        assert fake_bot_manager.is_running(bot_id) is False


async def test_account_start_with_explicit_channel(tmp_db, disable_auth, fake_bot_manager):
    from app import database
    await database.init_db()

    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        r = await client.post("/api/accounts", json={"nickname": "target_bot", "token": "oauth:token999"})
        bot_id = r.json()["id"]
        await client.post(f"/api/accounts/{bot_id}/channels", json={"channel_name": "ch1"})
        await client.post(f"/api/accounts/{bot_id}/channels", json={"channel_name": "ch2"})

        # Запускаем бота с указанием канала ch2
        start_res = await client.post(f"/api/accounts/{bot_id}/start?channel=ch2")
        assert start_res.status_code == 200
        assert start_res.json()["ok"] is True

        # Бот должен быть запущен только на ch2
        status = fake_bot_manager.get_status(bot_id)
        assert status["channels"] == ["ch2"]
