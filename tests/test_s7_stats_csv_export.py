"""§7.1 (из PLAN_ALL_IN_ONE «Stats»): CSV-экспорт chat_log — фильтры работают.

GET /api/chat-log/export.csv?hours=&account_id=&channel=&sentiment=
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


async def test_csv_export_smoke_with_filters(tmp_db, disable_auth):
    from app.database import init_db, get_db
    from app.routes import router
    from fastapi import FastAPI

    await init_db()
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO accounts (id, nickname, token) VALUES (1, 'csvbot', 'tok')"
        )
        await db.execute(
            "INSERT INTO chat_log (account_id, channel, author, message, is_bot, sentiment) "
            "VALUES (1, 'racing', 'viewer1', 'гоу гоу', 0, 1)"
        )
        await db.commit()
    finally:
        await db.close()

    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/chat-log/export.csv?hours=24&account_id=1&channel=%23racing&sentiment=pos"
        )
        assert resp.status_code == 200
        body = resp.text
        assert "viewer1" in body
        # фильтр по sentiment=neu не должен вернуть pos-строку
        resp2 = await client.get(
            "/api/chat-log/export.csv?hours=24&account_id=1&sentiment=neu"
        )
        assert resp2.status_code == 200
        assert "viewer1" not in resp2.text
