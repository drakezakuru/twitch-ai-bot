"""DELETE bot logs must not remove another account's history."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _seed_logs() -> None:
    from app import database

    db = await database.get_db()
    try:
        await db.execute(
            "INSERT INTO accounts (id, nickname, token) VALUES "
            "(1, 'first', 'oauth:first'), (2, 'second', 'oauth:second')"
        )
        await db.execute(
            "INSERT INTO bot_logs (account_id, channel, level, category, message, created_at) VALUES "
            "(1, '', 'info', 'system', 'first-old', datetime('now', '-31 days')), "
            "(1, '', 'info', 'system', 'first-fresh', datetime('now', '-1 day')), "
            "(2, '', 'info', 'system', 'second-old', datetime('now', '-31 days'))"
        )
        await db.commit()
    finally:
        await db.close()


async def _messages() -> set[str]:
    from app import database

    db = await database.get_db()
    try:
        cursor = await db.execute("SELECT message FROM bot_logs")
        return {row["message"] for row in await cursor.fetchall()}
    finally:
        await db.close()


async def test_account_log_cleanup_is_scoped(tmp_db, disable_auth):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app import database
    from app.routes import router

    await database.init_db()
    await _seed_logs()
    app = FastAPI()
    app.include_router(router)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete("/api/accounts/1/bot-logs?older_than=30d")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "deleted": 1}
    assert await _messages() == {"first-fresh", "second-old"}


@pytest.mark.parametrize("older_than", ["-1d", "+1d", "30", "days", "3651d", "1.5d"])
async def test_account_log_cleanup_rejects_unsafe_retention(tmp_db, disable_auth, older_than):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app import database
    from app.routes import router

    await database.init_db()
    app = FastAPI()
    app.include_router(router)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete(f"/api/accounts/1/bot-logs?older_than={older_than}")

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_older_than"


async def test_global_log_cleanup_remains_available(tmp_db):
    from app import database
    from app.bot_logs import cleanup_old_logs

    await database.init_db()
    await _seed_logs()

    assert await cleanup_old_logs(30) == 2
    assert await _messages() == {"first-fresh"}
