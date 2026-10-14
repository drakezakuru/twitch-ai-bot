"""Тесты Feature T: глобальный поиск /api/search."""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


async def _populate(tmp_db):
    """Создаёт временную БД и заполняет её тестовыми данными."""
    from app import database

    await database.init_db()
    db = await database.get_db()
    await db.execute(
        "INSERT INTO accounts (id, nickname, token) VALUES (1, 'streamer_one', 'tok')"
    )
    await db.execute(
        "INSERT INTO accounts (id, nickname, token) VALUES (2, 'helper_bot', 'tok')"
    )
    await db.execute(
        "INSERT INTO channels (account_id, channel_name) VALUES (1, 'pokimane')"
    )
    await db.execute(
        "INSERT INTO triggers (account_id, keyword, response) VALUES "
        "(1, 'kappa', 'Kappa right back')"
    )
    await db.execute(
        "INSERT INTO user_memory (account_id, username, facts, msg_count) VALUES "
        "(1, 'viewer42', '[\"играет в Доту\", \"живёт в Москве\"]', 100)"
    )
    await db.execute(
        "INSERT INTO chat_log (account_id, channel, author, message, is_bot) VALUES "
        "(1, 'pokimane', 'viewer42', 'omg KEKW что это было', 0)"
    )
    await db.commit()
    # Минимальное FastAPI-приложение из router без зависимости app.server (twitchio).
    from fastapi import FastAPI
    from app.routes import router, ws_router
    app = FastAPI()
    app.include_router(router)
    app.include_router(ws_router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_search_finds_account(tmp_db, disable_auth):
    async with await _populate(tmp_db) as client:
        r = await client.get("/api/search", params={"q": "streamer"})
        assert r.status_code == 200
        data = r.json()
        kinds = [x["kind"] for x in data["results"]]
        assert "account" in kinds
        titles = [x["title"] for x in data["results"]]
        assert "streamer_one" in titles


async def test_search_finds_channel(tmp_db, disable_auth):
    async with await _populate(tmp_db) as client:
        r = await client.get("/api/search", params={"q": "pokimane"})
        data = r.json()
        kinds = [x["kind"] for x in data["results"]]
        assert "channel" in kinds


async def test_search_finds_trigger(tmp_db, disable_auth):
    async with await _populate(tmp_db) as client:

        r = await client.get("/api/search", params={"q": "kappa"})
        data = r.json()
        assert "trigger" in [x["kind"] for x in data["results"]]


async def test_search_finds_memory_facts(tmp_db, disable_auth):
    async with await _populate(tmp_db) as client:
        r = await client.get("/api/search", params={"q": "Доту"})
        data = r.json()
        memory_results = [x for x in data["results"] if x["kind"] == "memory"]
        assert memory_results, f"Ожидали найти факт про Доту, получили {data['results']}"
        assert "Дот" in memory_results[0]["subtitle"]


async def test_search_finds_chat_log(tmp_db, disable_auth):
    async with await _populate(tmp_db) as client:
        r = await client.get("/api/search", params={"q": "KEKW"})
        data = r.json()
        chat_results = [x for x in data["results"] if x["kind"] == "chat"]
        assert chat_results
        assert "viewer42" in chat_results[0]["title"]


async def test_search_finds_tabs(tmp_db, disable_auth):
    async with await _populate(tmp_db) as client:
        r = await client.get("/api/search", params={"q": "аналитика"})
        data = r.json()
        tab_results = [x for x in data["results"] if x["kind"] == "tab"]
        assert tab_results
        assert any(t["tab"] == "graphs" for t in tab_results)


async def test_search_empty_query(tmp_db, disable_auth):
    async with await _populate(tmp_db) as client:
        r = await client.get("/api/search", params={"q": ""})
        data = r.json()
        assert data["total"] == 0
        assert data["results"] == []


async def test_search_short_query_returns_empty(tmp_db, disable_auth):
    """Запрос < 2 символов не делает ничего (защита от перегрузки)."""
    async with await _populate(tmp_db) as client:
        r = await client.get("/api/search", params={"q": "k"})
        assert r.json()["total"] == 0
