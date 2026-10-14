"""Тесты ручного наказания через API /api/moderation/punish (Task 5)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from app import database
from app import moderation_journal as J

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def _fresh_db(tmp_db, disable_auth):
    await database.init_db()
    yield


async def _make_bot(nickname: str = "modbot") -> int:
    db = await database.get_db()
    try:
        cur = await db.execute(
            "INSERT INTO accounts (nickname, token) VALUES (?, ?)",
            (nickname, "oauth:fake"),
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


def _client() -> AsyncClient:
    from app.moderation_journal_routes import router as journal_router
    app = FastAPI()
    app.include_router(journal_router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_manual_punish_validation():
    async with _client() as client:
        # Без параметров
        resp = await client.post("/api/moderation/punish", json={})
        assert resp.status_code == 200
        assert resp.json()["ok"] is False


async def test_manual_punish_timeout():
    aid = await _make_bot("bot1")
    async with _client() as client:
        with patch("app.twitch_helix.timeout_user", new=AsyncMock(return_value=(True, None))) as mock_timeout:
            resp = await client.post("/api/moderation/punish", json={
                "account_id": aid,
                "channel": "mychan",
                "username": "spammer",
                "duration_sec": 600,
                "reason": "Спам / флуд",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            assert data["action"] == "timeout"
            assert data["duration_sec"] == 600

            mock_timeout.assert_called_once()
            _, kwargs = mock_timeout.call_args
            assert kwargs["channel"] == "mychan"
            assert kwargs["username"] == "spammer"
            assert kwargs["duration_sec"] == 600
            assert kwargs["reason"] == "Спам / флуд"

        # Проверяем запись в журнале
        journal = await J.list_journal(account_id=aid, channel="mychan")
        assert len(journal) == 1
        assert journal[0]["username"] == "spammer"
        assert journal[0]["action"] == "timeout"
        assert "Спам / флуд" in journal[0]["rule_name"]


async def test_manual_punish_ban():
    aid = await _make_bot("bot2")
    async with _client() as client:
        with patch("app.twitch_helix.ban_user", new=AsyncMock(return_value=(True, None))) as mock_ban:
            resp = await client.post("/api/moderation/punish", json={
                "account_id": aid,
                "channel": "mychan",
                "username": "raider",
                "duration_sec": 0,
                "reason": "Токсичность",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            assert data["action"] == "ban"

            mock_ban.assert_called_once()
            _, kwargs = mock_ban.call_args
            assert kwargs["username"] == "raider"
            assert kwargs["reason"] == "Токсичность"
