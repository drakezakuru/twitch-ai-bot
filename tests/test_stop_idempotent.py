"""D1/«Стоп» (bugfix 3e0cdd3, 12.09.2026): остановка не запущенного бота — валидный
no-op, а не «Ошибка: OK» (панель раньше показывала ошибку из-за {"ok": bot_manager.stop_bot()}
возвращавшего False для уже остановленного бота)."""
from __future__ import annotations

import sys
from types import ModuleType

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.database import get_db, init_db

pytestmark = pytest.mark.asyncio


def _app():
    from app.routes import router, actor_middleware
    app = FastAPI()
    app.middleware("http")(actor_middleware)
    app.include_router(router)
    return app


@pytest.fixture()
def stub_server(monkeypatch):
    saved = sys.modules.get("app.server")
    fake = ModuleType("app.server")

    class _BotManager:
        def __init__(self):
            self.running = set()
            self._bots = {}

        def set_desired(self, account_id, params):
            pass

        def is_running(self, account_id):
            return account_id in self.running or account_id in self._bots

        async def stop_bot(self, account_id):
            was_running = account_id in self.running or account_id in self._bots
            self.running.discard(account_id)
            self._bots.pop(account_id, None)
            return was_running

    class _EventSubManager:
        async def stop_for_account(self, account_id):
            pass

    fake.bot_manager = _BotManager()
    fake.eventsub_manager = _EventSubManager()
    fake.chat_analyzer = None
    sys.modules["app.server"] = fake
    try:
        yield fake
    finally:
        if saved is not None:
            sys.modules["app.server"] = saved
        else:
            sys.modules.pop("app.server", None)


@pytest_asyncio.fixture(autouse=True)
async def _seed(tmp_db):
    await init_db()
    db = await get_db()
    try:
        await db.execute("INSERT INTO accounts (id, nickname, token, enabled) VALUES (1, 'bot', 'tok', 1)")
        await db.commit()
    finally:
        await db.close()


async def test_stopping_an_already_stopped_bot_is_a_successful_no_op(tmp_db, disable_auth, stub_server):
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        r = await client.post("/api/accounts/1/stop")
        body = r.json()
        # Раньше здесь было {"ok": False}, панель рисовала тост «Ошибка: OK».
        assert body["ok"] is True
        assert body["was_running"] is False


async def test_stopping_a_running_bot_reports_it_was_running(tmp_db, disable_auth, stub_server):
    stub_server.bot_manager.running.add(1)
    stub_server.bot_manager._bots[1] = True
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        r = await client.post("/api/accounts/1/stop")
        body = r.json()
        assert body["ok"] is True
        assert body["was_running"] is True


async def test_stop_all_bots(tmp_db, disable_auth, stub_server):
    stub_server.bot_manager.running.add(1)
    stub_server.bot_manager._bots[1] = True
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        r = await client.post("/api/bots/stop-all")
        body = r.json()
        assert body["ok"] is True
        assert body["stopped"] == 1
        assert 1 not in stub_server.bot_manager.running
        assert 1 not in stub_server.bot_manager._bots


async def test_start_all_bots(tmp_db, disable_auth, stub_server, monkeypatch):
    import app.bootstrap
    async def fake_start(*args, **kwargs):
        return True
    monkeypatch.setattr(app.bootstrap, "start_account", fake_start)

    db = await get_db()
    try:
        await db.execute("INSERT INTO channels (account_id, channel_name, enabled) VALUES (1, 'streamer', 1)")
        await db.commit()
    finally:
        await db.close()

    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        r = await client.post("/api/bots/start-all")
        body = r.json()
        assert body["ok"] is True
        assert body["started"] == 1
        assert body["total"] == 1
