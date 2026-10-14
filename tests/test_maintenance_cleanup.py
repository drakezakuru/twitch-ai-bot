"""Тесты авто-ротации и очистки старых логов (Task 8)."""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from app import database
from app import maintenance as M

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def _fresh_db(tmp_db, disable_auth):
    await database.init_db()
    yield


def _client() -> AsyncClient:
    from app.routes import router
    import app.routes_maintenance  # noqa: F401
    app = FastAPI()
    app.include_router(router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_cleanup_database_logs_retention():
    db = await database.get_db()
    try:
        cur = await db.execute("INSERT INTO accounts (nickname, token) VALUES ('bot1', 'oauth:fake')")
        aid = cur.lastrowid

        # Вставляем старые записи (>30 дней)
        await db.execute(
            "INSERT INTO chat_log (account_id, channel, author, message, timestamp) "
            "VALUES (?, 'chan', 'user1', 'old msg', datetime('now', '-40 days'))",
            (aid,),
        )
        await db.execute(
            "INSERT INTO ai_feedback (account_id, channel, message, rating, created_at) "
            "VALUES (?, 'chan', 'old feedback', 1, datetime('now', '-40 days'))",
            (aid,),
        )
        await db.execute(
            "INSERT INTO moderation_events (account_id, channel, username, action_taken, created_at) "
            "VALUES (?, 'chan', 'user1', 'block', datetime('now', '-40 days'))",
            (aid,),
        )
        await db.execute(
            "INSERT INTO action_log (action, detail, timestamp) "
            "VALUES ('login', 'old login', datetime('now', '-40 days'))"
        )

        # Вставляем свежие записи (<30 дней)
        await db.execute(
            "INSERT INTO chat_log (account_id, channel, author, message, timestamp) "
            "VALUES (?, 'chan', 'user2', 'new msg', datetime('now', '-5 days'))",
            (aid,),
        )
        await db.execute(
            "INSERT INTO ai_feedback (account_id, channel, message, rating, created_at) "
            "VALUES (?, 'chan', 'new feedback', 1, datetime('now', '-5 days'))",
            (aid,),
        )
        await db.execute(
            "INSERT INTO moderation_events (account_id, channel, username, action_taken, created_at) "
            "VALUES (?, 'chan', 'user2', 'block', datetime('now', '-5 days'))",
            (aid,),
        )
        await db.execute(
            "INSERT INTO action_log (action, detail, timestamp) "
            "VALUES ('login', 'new login', datetime('now', '-5 days'))"
        )
        await db.commit()
    finally:
        await db.close()

    # Очищаем логи старше 30 дней
    res = await M.cleanup_database_logs(days=30)
    assert res["chat_log"] == 1
    assert res["ai_feedback"] == 1
    assert res["moderation_events"] == 1
    assert res["action_log"] == 1

    # Проверяем, что свежие записи остались
    db = await database.get_db()
    try:
        cur = await db.execute("SELECT COUNT(*) FROM chat_log")
        assert (await cur.fetchone())[0] == 1

        cur = await db.execute("SELECT COUNT(*) FROM ai_feedback")
        assert (await cur.fetchone())[0] == 1

        cur = await db.execute("SELECT COUNT(*) FROM moderation_events")
        assert (await cur.fetchone())[0] == 1

        cur = await db.execute("SELECT COUNT(*) FROM action_log")
        assert (await cur.fetchone())[0] == 1
    finally:
        await db.close()


async def test_api_maintenance_cleanup():
    async with _client() as client:
        resp = await client.post("/api/maintenance/cleanup", json={"days": 15})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["days"] == 15
        assert "deleted" in data
        assert "total_deleted" in data


async def test_run_log_retention():
    # Запуск без ошибок
    total = await M.run_log_retention()
    assert isinstance(total, int)
