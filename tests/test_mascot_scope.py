"""Mascot config and reactions are isolated by account and channel."""
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
            ((1, "mascot_one"), (2, "mascot_two")),
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


async def test_mascot_config_is_exact_scope_and_legacy_is_preserved(tmp_db, disable_auth):
    async with await _client() as client:
        await client.put("/api/widgets/mascot", json={"preset": "ghost", "idle_timeout_sec": 90})
        await client.put(
            "/api/widgets/mascot?account_id=1&channel=%23ChAn",
            json={"preset": "owl", "idle_timeout_sec": 120},
        )

        own = (await client.get(
            "/api/widgets/public/mascot?account_id=1&channel=CHAN"
        )).json()
        other_channel = (await client.get(
            "/api/widgets/public/mascot?account_id=1&channel=other"
        )).json()
        other_account = (await client.get(
            "/api/widgets/public/mascot?account_id=2&channel=chan"
        )).json()
        legacy = (await client.get("/api/widgets/public/mascot")).json()

    assert own == {"preset": "owl", "custom_url": "", "idle_timeout_sec": 120}
    assert other_channel["preset"] == "blob"
    assert other_account["preset"] == "blob"
    assert legacy["preset"] == "ghost" and legacy["idle_timeout_sec"] == 90


async def test_mascot_reacts_only_to_events_from_its_scope(tmp_db, disable_auth):
    from app.widgets import on_stream_event

    async with await _client() as client:
        await on_stream_event("follow", "Own", account_id=1, channel="chan")
        await on_stream_event("raid", "OtherChannel", account_id=1, channel="other")
        await on_stream_event("cheer", "OtherAccount", 50, account_id=2, channel="chan")
        await on_stream_event("manual", "Legacy")

        own = (await client.get(
            "/api/widgets/public/recent-events?account_id=1&channel=chan"
        )).json()
        other_channel = (await client.get(
            "/api/widgets/public/recent-events?account_id=1&channel=other"
        )).json()
        legacy = (await client.get("/api/widgets/public/recent-events")).json()

    assert [event["username"] for event in own] == ["Own"]
    assert [event["username"] for event in other_channel] == ["OtherChannel"]
    assert [event["username"] for event in legacy] == ["Legacy"]


@pytest.mark.parametrize("query", ("account_id=1", "channel=chan", "account_id=9&channel=chan"))
async def test_mascot_scope_must_be_complete_and_configured(tmp_db, disable_auth, query):
    async with await _client() as client:
        config = await client.get(f"/api/widgets/public/mascot?{query}")
        events = await client.get(f"/api/widgets/public/recent-events?{query}")
    assert config.status_code == 400
    assert events.status_code == 400


async def test_panel_and_runtime_forward_selected_scope():
    panel_js = (ROOT / "static/app/15_feedback_2908.js").read_text(encoding="utf-8")
    widgets_js = (ROOT / "static/app/07_widgets.js").read_text(encoding="utf-8")
    runtime = (ROOT / "widgets/mascot/index.html").read_text(encoding="utf-8")

    assert "wstateapi('/api/widgets/mascot')" in panel_js
    assert "'/widget/mascot'" in widgets_js
    assert "configUrl:'/api/widgets/public/mascot'+scopeSuffix" in runtime
    assert "public/recent-events" not in runtime
