from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


pytestmark = pytest.mark.asyncio


async def _app(tmp_db) -> FastAPI:
    from app.database import get_db, init_db
    from app.routes import router

    await init_db()
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO accounts (id, nickname, token) VALUES (1, 'clipbot', 'oauth')"
        )
        await db.executemany(
            "INSERT INTO channels (account_id, channel_name, enabled) VALUES (1, ?, ?)",
            (("Chan", 1), ("disabled", 0)),
        )
        await db.commit()
    finally:
        await db.close()
    app = FastAPI()
    app.include_router(router)
    return app


class _HelixResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


async def test_manual_clip_is_exact_scope_and_normalizes_channel(
    tmp_db, disable_auth, monkeypatch
):
    app = await _app(tmp_db)
    calls: list[dict] = []

    class _HelixClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, **kwargs):
            calls.append({"url": url, **kwargs})
            return _HelixResponse(202, {
                "data": [{"id": "clip-1", "edit_url": "https://clips.test/edit"}],
            })

    async def _user_id(_channel, _token):
        return "broadcaster-1"

    monkeypatch.setattr("app.twitch_helix._client_id", lambda: "client-1")
    monkeypatch.setattr("app.twitch_helix.get_user_id", _user_id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        rejected = await client.post(
            "/api/bot/clip-detector/create-clip",
            json={"account_id": 1, "channel": "other"},
        )
        assert rejected.json() == {
            "ok": False, "error": "Channel is not enabled for this account",
        }
        assert calls == []

        monkeypatch.setattr(httpx, "AsyncClient", _HelixClient)
        created = await client.post(
            "/api/bot/clip-detector/create-clip",
            json={"account_id": 1, "channel": " #CHAN "},
        )
        assert created.json() == {
            "ok": True, "clip_url": "clip-1", "edit_url": "https://clips.test/edit",
        }

    assert len(calls) == 1
    from app.database import get_db
    db = await get_db()
    try:
        rows = await (await db.execute(
            "SELECT account_id, channel, clip_url FROM clip_moments"
        )).fetchall()
    finally:
        await db.close()
    assert [tuple(row) for row in rows] == [(1, "chan", "clip-1")]


async def test_manual_clip_helix_failure_does_not_create_moment(
    tmp_db, disable_auth, monkeypatch
):
    app = await _app(tmp_db)

    class _DeniedClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return _HelixResponse(403)

    async def _user_id(_channel, _token):
        return "broadcaster-1"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        monkeypatch.setattr("app.twitch_helix._client_id", lambda: "client-1")
        monkeypatch.setattr("app.twitch_helix.get_user_id", _user_id)
        monkeypatch.setattr(httpx, "AsyncClient", _DeniedClient)
        response = await client.post(
            "/api/bot/clip-detector/create-clip",
            json={"account_id": 1, "channel": "chan"},
        )
    assert response.json()["ok"] is False
    assert "permissions" in response.json()["error"]

    from app.database import get_db
    db = await get_db()
    try:
        count = (await (await db.execute("SELECT COUNT(*) FROM clip_moments")).fetchone())[0]
    finally:
        await db.close()
    assert count == 0


async def test_clip_detector_never_auto_calls_manual_clip_action():
    root = Path(__file__).resolve().parents[1]
    script = (root / "static/app/11_brain_v16.js").read_text(encoding="utf-8")
    check = script.split("async function checkClipSpike()", 1)[1].split(
        "async function createClipManually()", 1
    )[0]
    manual = script.split("async function createClipManually()", 1)[1].split(
        "async function loadClipMoments()", 1
    )[0]
    assert "create-clip" not in check
    assert "/api/bot/clip-detector/create-clip" in manual
