"""Owner report 27.09.2026: «Бот выключен» в чате + «Ошибка» при первом старте.

Корень: кнопка «Старт» слала `toggle` (он сам поднимал бота) и следом `/start`.
Второй `/start` получал «Уже запущен» → `{"ok": false}` без reason → тост «Ошибка»,
а флаг `accounts.enabled` рассинхронизировался с живым ботом, и `/api/send`
отвечал «Бот выключен».

Контракт, который здесь закрепляется:
1. `/start` на уже запущенного бота — успешный no-op (`ok: true, already: true`).
2. `/start` и `/stop` владеют флагом `accounts.enabled`.
3. `/toggle` — только флаг, бот не трогает.
4. `/api/send` доверяет фактическому подключению, а не только флагу.
"""
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


class _BotManager:
    """Заглушка bot_manager: считает старты/стопы и хранит «живые» инстансы."""

    def __init__(self):
        self.running: set[int] = set()
        self.connected: set[int] = set()
        self.channels: dict[int, list[str]] = {}
        self.start_calls: list[int] = []
        self.stop_calls: list[int] = []
        self.desired: dict[int, dict | None] = {}

    # ── API, который использует роутер ──
    def is_running(self, account_id: int) -> bool:
        return account_id in self.running

    def get_status(self, account_id: int) -> dict:
        return {
            "connected": account_id in self.connected,
            "channels": self.channels.get(account_id, []),
            "state": "online" if account_id in self.connected else "offline",
        }

    def set_desired(self, account_id: int, params) -> None:
        self.desired[account_id] = params

    async def start_bot(self, account_id, nickname, token, channels, proxy="") -> bool:
        if account_id in self.running:
            return False
        self.start_calls.append(account_id)
        self.running.add(account_id)
        self.channels[account_id] = list(channels)
        return True

    async def stop_bot(self, account_id) -> bool:
        self.stop_calls.append(account_id)
        was = account_id in self.running
        self.running.discard(account_id)
        self.connected.discard(account_id)
        self.channels.pop(account_id, None)
        return was

    async def send_message_detailed(self, account_id, channel, text) -> dict:
        if account_id not in self.connected:
            return {"ok": False, "reason": "bot_not_connected", "error": "Бот не подключён"}
        return {"ok": True, "confirmed": False}


class _EventSubManager:
    def __init__(self):
        self.started: list[int] = []
        self.stopped: list[int] = []

    async def start_for_account(self, account_id, nickname, token, channels):
        self.started.append(account_id)

    async def stop_for_account(self, account_id):
        self.stopped.append(account_id)


class _ChatAnalyzer:
    def __init__(self):
        self.tokens: dict[int, str] = {}

    def set_account_token(self, account_id, token):
        self.tokens[account_id] = token

    async def load_persisted_settings(self, account_id):
        return None

    def update_settings(self, account_id, data):
        return None


@pytest.fixture()
def stub_server(monkeypatch):
    saved = sys.modules.get("app.server")
    fake = ModuleType("app.server")
    fake.bot_manager = _BotManager()
    fake.eventsub_manager = _EventSubManager()
    fake.chat_analyzer = _ChatAnalyzer()
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
        await db.execute("INSERT INTO accounts (id, nickname, token, enabled) VALUES (1, 'bot', 'oauth:t', 0)")
        await db.execute("INSERT INTO channels (account_id, channel_name, enabled) VALUES (1, 'test_channel', 1)")
        await db.commit()
    finally:
        await db.close()


async def _enabled() -> int:
    db = await get_db()
    try:
        cur = await db.execute("SELECT enabled FROM accounts WHERE id = 1")
        return (await cur.fetchone())["enabled"]
    finally:
        await db.close()


async def test_start_turns_the_flag_on(tmp_db, disable_auth, stub_server):
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as c:
        r = await c.post("/api/accounts/1/start")
    assert r.json()["ok"] is True
    assert await _enabled() == 1
    assert stub_server.bot_manager.start_calls == [1]


async def test_start_of_a_running_bot_is_a_successful_no_op(tmp_db, disable_auth, stub_server):
    """Раньше второй /start давал ok:false → тост «Ошибка»."""
    stub_server.bot_manager.running.add(1)
    stub_server.bot_manager.connected.add(1)
    stub_server.bot_manager.channels[1] = ["test_channel"]
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as c:
        r = await c.post("/api/accounts/1/start")
    body = r.json()
    assert body["ok"] is True
    assert body["already"] is True
    assert body["connected"] is True
    # Второго подключения к Twitch не было.
    assert stub_server.bot_manager.start_calls == []
    # Флаг выровнен по факту.
    assert await _enabled() == 1


async def test_stop_turns_the_flag_off(tmp_db, disable_auth, stub_server):
    stub_server.bot_manager.running.add(1)
    stub_server.bot_manager.connected.add(1)
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as c:
        r = await c.post("/api/accounts/1/stop")
    assert r.json()["ok"] is True
    assert await _enabled() == 0


async def test_toggle_only_flips_the_flag(tmp_db, disable_auth, stub_server):
    """Toggle больше не поднимает/останавливает бота (иначе панель ловила
    двойной старт и рассинхрон флага)."""
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as c:
        r = await c.post("/api/accounts/1/toggle")
    assert r.json()["enabled"] == 1
    assert stub_server.bot_manager.start_calls == []
    assert stub_server.bot_manager.stop_calls == []


async def test_send_works_when_flag_is_off_but_bot_is_connected(tmp_db, disable_auth, stub_server):
    """Синхронный кейс владельца: бот в канале, флаг 0 → отправка проходит."""
    stub_server.bot_manager.running.add(1)
    stub_server.bot_manager.connected.add(1)
    stub_server.bot_manager.channels[1] = ["test_channel"]
    assert await _enabled() == 0
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as c:
        r = await c.post("/api/send", json={"account_id": 1, "channel": "test_channel", "text": "hi"})
    assert r.json()["ok"] is True


async def test_send_still_refuses_a_disconnected_bot(tmp_db, disable_auth, stub_server):
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as c:
        r = await c.post("/api/send", json={"account_id": 1, "channel": "test_channel", "text": "hi"})
    body = r.json()
    assert body["ok"] is False
    assert body["reason"] == "bot_disabled"
