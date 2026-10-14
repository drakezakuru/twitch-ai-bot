"""Тесты Feature U: AI-резюме чата за последние N минут."""
from __future__ import annotations

import sys
from datetime import datetime
from types import ModuleType, SimpleNamespace

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


class _StubAI:
    """Заглушка ai_service, которая запоминает prompt и возвращает фиксированный ответ."""

    def __init__(self):
        self.last_prompt: str | None = None
        self.last_system: str | None = None
        self.next_response: str = "- AI сказал что-то осмысленное\n- Чат смеялся"

    async def generate_text(self, prompt, system="", account_id=0, channel=""):
        self.last_prompt = prompt
        self.last_system = system
        return self.next_response


def _install_stub_server(stub_ai):
    """Подменяет модуль app.server, чтобы routes.py мог импортировать ai_service."""
    fake_server = ModuleType("app.server")
    fake_server.ai_service = stub_ai
    sys.modules["app.server"] = fake_server


async def _setup(tmp_db, *, stub_ai, n_messages=5, with_events=True):
    from app import database
    await database.init_db()
    db = await database.get_db()
    await db.execute("INSERT INTO accounts (id, nickname, token) VALUES (1, 'main', 'tok')")
    # Сообщения за последние ~5 минут (datetime('now', '-X minutes') возьмёт)
    for i in range(n_messages):
        await db.execute(
            "INSERT INTO chat_log (account_id, channel, author, message, is_bot) "
            "VALUES (1, 'mychannel', ?, ?, 0)",
            (f"viewer{i}", f"какое-то сообщение #{i} kekw"),
        )
    if with_events:
        await db.execute(
            "INSERT INTO action_log (action, detail) VALUES ('eventsub_sub', 'viewer1 подписался')"
        )
        await db.execute(
            "INSERT INTO action_log (action, detail) VALUES ('eventsub_raid', 'streamerX рейдил с 50 viewers')"
        )
    await db.commit()
    _install_stub_server(stub_ai)

    from fastapi import FastAPI
    from app.routes import router, ws_router
    app = FastAPI()
    app.include_router(router)
    app.include_router(ws_router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_summary_returns_empty_when_no_messages(tmp_db, disable_auth):
    stub = _StubAI()
    async with await _setup(tmp_db, stub_ai=stub, n_messages=0, with_events=False) as client:
        r = await client.post("/api/ai/summary", json={"minutes": 10})
        assert r.status_code == 200
        data = r.json()
        assert data["msg_count"] == 0
        assert data["minutes"] == 10
        assert "сообщений не было" in data["summary"].lower()
        # AI не должен был вызываться, если нет сообщений
        assert stub.last_prompt is None


async def test_summary_calls_ai_with_chat_log(tmp_db, disable_auth):
    stub = _StubAI()
    async with await _setup(tmp_db, stub_ai=stub, n_messages=5) as client:
        r = await client.post("/api/ai/summary", json={"minutes": 10})
        assert r.status_code == 200
        data = r.json()
        assert data["msg_count"] == 5
        assert data["summary"] == "- AI сказал что-то осмысленное\n- Чат смеялся"
        assert stub.last_prompt is not None
        # В prompt'е должны быть все сообщения и hint про события
        for i in range(5):
            assert f"viewer{i}" in stub.last_prompt
        assert "ЧАТ" in stub.last_prompt


async def test_summary_includes_eventsub_section(tmp_db, disable_auth):
    """Если есть EventSub-события — они должны попасть в prompt."""
    stub = _StubAI()
    async with await _setup(tmp_db, stub_ai=stub, n_messages=3, with_events=True) as client:
        r = await client.post("/api/ai/summary", json={"minutes": 10})
        data = r.json()
        assert "events" in data
        assert len(data["events"]) == 2
        assert "СОБЫТИЯ" in stub.last_prompt
        assert "eventsub_sub" in stub.last_prompt or "viewer1" in stub.last_prompt


async def test_summary_clamps_minutes(tmp_db, disable_auth):
    """minutes ограничен диапазоном [1, 360]."""
    stub = _StubAI()
    async with await _setup(tmp_db, stub_ai=stub, n_messages=2) as client:
        r = await client.post("/api/ai/summary", json={"minutes": 99999})
        assert r.json()["minutes"] == 360
        r = await client.post("/api/ai/summary", json={"minutes": -5})
        assert r.json()["minutes"] == 1


async def test_summary_filters_by_channel(tmp_db, disable_auth):
    stub = _StubAI()
    async with await _setup(tmp_db, stub_ai=stub, n_messages=3) as client:
        r = await client.post("/api/ai/summary", json={"minutes": 10, "channel": "nonexistent"})
        data = r.json()
        assert data["msg_count"] == 0


async def test_summary_returns_error_message_on_ai_failure(tmp_db, disable_auth):
    """Если AI бросает — endpoint всё равно возвращает 200 с ошибкой в ответе."""
    stub = _StubAI()

    async def boom(*args, **kwargs):
        raise RuntimeError("API quota exceeded")

    stub.generate_text = boom  # type: ignore
    async with await _setup(tmp_db, stub_ai=stub, n_messages=2) as client:
        r = await client.post("/api/ai/summary", json={"minutes": 10})
        assert r.status_code == 200
        data = r.json()
        assert "error" in data
        assert "quota" in data["summary"].lower()
