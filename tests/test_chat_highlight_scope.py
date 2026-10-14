"""Chat Highlight state and automatic bot replies stay in their exact scope."""
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
            ((1, "highlight_one"), (2, "highlight_two")),
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


async def test_manual_state_is_scoped_and_legacy_is_preserved(tmp_db, disable_auth):
    async with await _client() as client:
        await client.put("/api/widgets/chat-highlight", json={"text": "Legacy", "author": "L"})
        await client.put(
            "/api/widgets/chat-highlight?account_id=1&channel=%23ChAn",
            json={"text": "Scoped", "author": "S", "theme": "neon"},
        )

        own = (await client.get(
            "/api/widgets/public/chat-highlight?account_id=1&channel=CHAN"
        )).json()
        other_channel = (await client.get(
            "/api/widgets/public/chat-highlight?account_id=1&channel=other"
        )).json()
        other_account = (await client.get(
            "/api/widgets/public/chat-highlight?account_id=2&channel=chan"
        )).json()
        legacy = (await client.get("/api/widgets/public/chat-highlight")).json()

    assert own["text"] == "Scoped" and own["author"] == "S" and own["theme"] == "neon"
    assert other_channel["text"] == "" and other_account["text"] == ""
    assert legacy["text"] == "Legacy" and legacy["author"] == "L"


async def test_automatic_reply_mutates_only_matching_scope(tmp_db, disable_auth):
    from app.widgets import push_chat_highlight

    async with await _client() as client:
        for account_id, channel in ((1, "chan"), (1, "other"), (2, "chan")):
            await client.put(
                f"/api/widgets/chat-highlight?account_id={account_id}&channel={channel}",
                json={"auto_mode": True},
            )
        await push_chat_highlight(
            "Bot reply", author="ScopedBot", account_id=1, channel="#CHAN",
        )

        own = (await client.get(
            "/api/widgets/public/chat-highlight?account_id=1&channel=chan"
        )).json()
        other_channel = (await client.get(
            "/api/widgets/public/chat-highlight?account_id=1&channel=other"
        )).json()
        other_account = (await client.get(
            "/api/widgets/public/chat-highlight?account_id=2&channel=chan"
        )).json()

    assert own["text"] == "Bot reply" and own["author"] == "ScopedBot"
    assert other_channel["text"] == "" and other_account["text"] == ""


async def test_scope_must_be_complete_and_configured(tmp_db, disable_auth):
    async with await _client() as client:
        for query in ("account_id=1", "channel=chan", "account_id=9&channel=chan"):
            response = await client.get(f"/api/widgets/public/chat-highlight?{query}")
            assert response.status_code == 400


async def test_obs_runtime_and_panel_url_forward_scope():
    runtime = (ROOT / "widgets/chat-highlight/index.html").read_text(encoding="utf-8")
    panel = (ROOT / "static/app/07_widgets.js").read_text(encoding="utf-8")
    analyzer = (ROOT / "app/chat_analyzer.py").read_text(encoding="utf-8")

    assert "stateUrl='/api/widgets/public/chat-highlight'" in runtime
    assert "'/widget/chat-highlight'" in panel
    assert "account_id=account_id, channel=channel" in analyzer
