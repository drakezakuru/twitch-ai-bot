"""Track 6.7: validation, duplicate protection, and durable audit."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio


async def _client() -> AsyncClient:
    from app.database import get_db, init_db
    from app.song_request_routes import router as audit_router
    from app.widgets import admin_router

    await init_db()
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO accounts (id, nickname, token) VALUES (1, 'songs', 'fake')"
        )
        await db.executemany(
            "INSERT OR IGNORE INTO channels (account_id, channel_name, enabled) VALUES (1, ?, 1)",
            (("chan",), ("other",)),
        )
        await db.commit()
    finally:
        await db.close()
    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(audit_router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_chat_rejects_unsafe_empty_and_duplicate_with_exact_scope_audit(
    tmp_db, disable_auth,
):
    from app.widgets import add_song_request

    async with await _client() as client:
        await client.put(
            "/api/widgets/song-request?account_id=1&channel=chan",
            json={"cooldown_sec": 0, "max_per_user": 0},
        )
        assert (await add_song_request("", "viewer", "chan", account_id=1))["error"] == "empty_request"
        assert (await add_song_request(
            "javascript:alert(1)", "viewer", "chan", account_id=1,
        ))["error"] == "unsafe_url"
        assert (await add_song_request("  My   Song  ", "viewer", "chan", account_id=1))["ok"] is True
        assert (await add_song_request("my song", "other", "chan", account_id=1))["error"] == "duplicate_request"
        assert (await add_song_request("my song", "other", "other", account_id=1))["ok"] is True

        audit = (await client.get(
            "/api/widgets/song-request/audit?account_id=1&channel=%23CHAN"
        )).json()["items"]
        other = (await client.get(
            "/api/widgets/song-request/audit?account_id=1&channel=other"
        )).json()["items"]

    assert [item["reason"] for item in audit] == [
        "duplicate_request", "accepted", "unsafe_url", "empty_request",
    ]
    assert all(item["source"] == "chat" for item in audit)
    assert [item["reason"] for item in other] == ["accepted"]


async def test_owner_add_uses_same_validation_and_journal(tmp_db, disable_auth):
    async with await _client() as client:
        endpoint = "/api/widgets/song-request/add?account_id=1&channel=chan"
        first = (await client.post(endpoint, json={
            "title": "https://youtube.com/watch?v=abcdefghijk",
            "requested_by": "owner",
        })).json()
        duplicate = (await client.post(endpoint, json={
            "title": "https://youtube.com/watch?v=abcdefghijk",
            "requested_by": "owner",
        })).json()
        unsafe = (await client.post(endpoint, json={
            "title": "https://user:secret@example.com/watch?v=abcdefghijk",
            "requested_by": "owner",
        })).json()
        audit = (await client.get(
            "/api/widgets/song-request/audit?account_id=1&channel=chan"
        )).json()["items"]

    assert first["ok"] is True
    assert duplicate["error"] == "duplicate_request"
    assert unsafe["error"] == "unsafe_url"
    assert [item["reason"] for item in audit] == [
        "unsafe_url", "duplicate_request", "accepted",
    ]
    assert all(item["source"] == "owner" for item in audit)
