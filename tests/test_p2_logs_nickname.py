"""Фидбек 29.08: в глобальных логах видно, какому боту принадлежит строка.

get_bot_logs() присоединяет accounts.nickname к каждой записи — панель
рендерит бейдж ника вместо обезличенного «Бот ...».
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _seed_account(aid: int, nick: str) -> None:
    from app import database
    db = await database.get_db()
    try:
        await db.execute(
            "INSERT INTO accounts (id, nickname, token, enabled) VALUES (?, ?, 'oauth:x', 1) "
            "ON CONFLICT(id) DO NOTHING",
            (aid, nick),
        )
        await db.commit()
    finally:
        await db.close()


async def test_bot_logs_include_nickname(tmp_db, disable_auth):
    from app import database
    from app.bot_logs import get_bot_logs, log_per_bot
    await database.init_db()
    await _seed_account(77, "NickBot")
    await _seed_account(78, "SecondBot")

    await log_per_bot(account_id=77, channel="chan", category="chat", message="читает чат")
    await log_per_bot(account_id=78, channel="chan", category="ai", message="генерирует ответ")

    logs, _ = await get_bot_logs(limit=10)
    by_msg = {l["message"]: l for l in logs}
    assert by_msg["читает чат"]["nickname"] == "NickBot"
    assert by_msg["генерирует ответ"]["nickname"] == "SecondBot"


async def test_bot_logs_route_returns_nickname(tmp_db, disable_auth):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app import database
    from app.bot_logs import log_per_bot
    from app.routes import router
    await database.init_db()
    await _seed_account(77, "NickBot")
    await log_per_bot(account_id=77, channel="chan", category="system", message="проверка маршрута")

    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        data = (await c.get("/api/bot-logs?limit=5")).json()
    assert data["ok"] is True
    mine = [l for l in data["logs"] if l["message"] == "проверка маршрута"]
    assert mine and mine[0]["nickname"] == "NickBot"
