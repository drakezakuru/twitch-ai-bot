"""P8-A1: GET /api/accounts/{id} существовал только как PUT/DELETE —
вкладка «Общие» бота ловила «Ошибка загрузки: Method Not Allowed», поля
бота не заполнялись, _currentBot перезаписывался ошибкой 405.

Фикс: GET-роут в routes.py (token не отдаём наружу — только token_masked).
Регресс ловится и Ф1-тестом (метод-уровень), здесь — поведенческая проверка.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


async def _client():
    from app.database import init_db
    from app.routes import router
    await init_db()
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed(account_id: int, nickname: str):
    from app.database import init_db, get_db
    await init_db()
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO accounts (id, nickname, token, proxy) VALUES (?, ?, 't', 'p1')",
            (account_id, nickname))
        await db.commit()
    finally:
        await db.close()


async def test_get_account_returns_fields_without_token(tmp_db, disable_auth):
    await _seed(1, "b1")
    async with await _client() as c:
        r = await c.get("/api/accounts/1")
    assert r.status_code == 200
    data = r.json()
    assert data.get("nickname") == "b1"
    assert data.get("proxy") == "p1"
    assert data.get("enabled") == 1
    # Токен наружу не уходит — только маска
    assert data.get("token", None) == ""
    assert isinstance(data.get("token_masked"), str)
    assert "t" not in data.get("token_masked", "") or data["token_masked"] == ""


async def test_get_account_missing_is_error_dict_not_405(tmp_db, disable_auth):
    async with await _client() as c:
        r = await c.get("/api/accounts/9999")
    assert r.status_code == 200
    assert r.json() == {"error": "not found"}
