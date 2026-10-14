"""Song Request and Media Share queues are isolated by account and channel."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio
ROOT = Path(__file__).resolve().parents[1]


async def _client() -> AsyncClient:
    from app.database import get_db, init_db
    from app.widgets import admin_router, public_router

    await init_db()
    db = await get_db()
    try:
        await db.executemany(
            "INSERT OR IGNORE INTO accounts (id, nickname, token) VALUES (?, ?, 'fake')",
            ((1, "songs_one"), (2, "songs_two")),
        )
        await db.executemany(
            "INSERT OR IGNORE INTO channels (account_id, channel_name, enabled) VALUES (?, ?, 1)",
            ((1, "chan"), (1, "other"), (2, "chan")),
        )
        await db.commit()
    finally:
        await db.close()
    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(public_router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_settings_and_queue_are_exact_scope_with_legacy_preserved(tmp_db, disable_auth):
    async with await _client() as client:
        await client.put("/api/widgets/song-request", json={"theme": "minimal"})
        await client.put(
            "/api/widgets/song-request?account_id=1&channel=%23CHAN",
            json={"theme": "fire", "max_queue": 7},
        )
        own_add = (await client.post(
            "/api/widgets/song-request/add?account_id=1&channel=chan",
            json={"title": "Own", "requested_by": "viewer"},
        )).json()
        await client.post(
            "/api/widgets/song-request/add?account_id=1&channel=other",
            json={"title": "Other channel", "requested_by": "viewer"},
        )
        await client.post(
            "/api/widgets/song-request/add?account_id=2&channel=chan",
            json={"title": "Other account", "requested_by": "viewer"},
        )
        await client.post(
            "/api/widgets/song-request/add", json={"title": "Legacy", "requested_by": "viewer"},
        )

        own = (await client.get(
            "/api/widgets/public/song-request?account_id=1&channel=chan"
        )).json()
        other_channel = (await client.get(
            "/api/widgets/public/song-request?account_id=1&channel=other"
        )).json()
        other_account = (await client.get(
            "/api/widgets/public/song-request?account_id=2&channel=chan"
        )).json()
        legacy = (await client.get("/api/widgets/public/song-request")).json()

        def titles(state):
            return [item["title"] for item in (
                ([state["now_playing"]] if state["now_playing"] else []) + state["queue"]
            )]

        own_titles = titles(own)
        assert own_titles == ["Own"]
        assert titles(other_channel) == ["Other channel"]
        assert titles(other_account) == ["Other account"]
        assert titles(legacy) == ["Legacy"]
        assert own["theme"] == "fire"
        assert legacy["theme"] == "minimal"

        await client.delete(
            f"/api/widgets/song-request/{own_add['id']}?account_id=1&channel=other"
        )
        still_own = (await client.get(
            "/api/widgets/public/song-request?account_id=1&channel=chan"
        )).json()
        assert titles(still_own) == ["Own"]


async def test_chat_ingress_and_public_next_use_only_matching_scope(tmp_db, disable_auth):
    from app.widgets import add_song_request

    async with await _client() as client:
        for account_id, channel in ((1, "chan"), (1, "other")):
            await client.put(
                f"/api/widgets/song-request?account_id={account_id}&channel={channel}",
                json={"cooldown_sec": 0, "max_per_user": 0},
            )
        await add_song_request("First", "u1", "chan", account_id=1)
        await add_song_request("Second", "u2", "chan", account_id=1)
        await add_song_request("Other", "u3", "other", account_id=1)

        await client.post(
            "/api/widgets/public/song-request/next?account_id=1&channel=chan"
        )
        own = (await client.get(
            "/api/widgets/public/song-request?account_id=1&channel=chan"
        )).json()
        other = (await client.get(
            "/api/widgets/public/song-request?account_id=1&channel=other"
        )).json()

    assert own["now_playing"]["title"] == "Second"
    assert other["now_playing"]["title"] == "Other"


async def test_legacy_priority_grant_does_not_leak_into_scoped_queue(tmp_db, disable_auth):
    from app.widgets import add_song_request

    async with await _client() as client:
        await client.post(
            "/api/widgets/song-request/priority/grant", json={"username": "priority_viewer"},
        )
        await client.put(
            "/api/widgets/song-request?account_id=1&channel=chan",
            json={"cooldown_sec": 0, "max_per_user": 0},
        )
        await add_song_request("Scoped", "priority_viewer", "chan", account_id=1)
        state = (await client.get(
            "/api/widgets/song-request?account_id=1&channel=chan"
        )).json()

    item = state["now_playing"] or state["queue"][0]
    assert item["priority"] == 0


async def test_runtime_and_panel_forward_scope():
    panel = (ROOT / "static/app/07_widgets.js").read_text(encoding="utf-8")
    song = (ROOT / "widgets/song-request/index.html").read_text(encoding="utf-8")
    media = (ROOT / "widgets/media-share/index.html").read_text(encoding="utf-8")

    assert "wstateapi('/api/widgets/song-request')" in panel
    assert "'/widget/song-request', '/widget/media-share'" in panel
    assert "scope.set('account_id'" in song and "scope.set('channel'" in song
    assert "'/api/widgets/public/song-request/next' + scopeQuery" in media
