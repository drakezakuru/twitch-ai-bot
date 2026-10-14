"""Chat Roulette state and participant selection stay in their exact scope."""
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
            ((1, "roulette_one"), (2, "roulette_two")),
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


async def test_state_is_exact_scope_and_legacy_is_preserved(tmp_db, disable_auth):
    async with await _client() as client:
        await client.put(
            "/api/widgets/chat-roulette",
            json={"participants": ["Legacy"], "winner": "Legacy", "theme": "legacy"},
        )
        await client.put(
            "/api/widgets/chat-roulette?account_id=1&channel=%23CHAN",
            json={"participants": ["Own", "Viewer"], "winner": "Own", "theme": "neon"},
        )

        own = (await client.get(
            "/api/widgets/public/chat-roulette?account_id=1&channel=chan"
        )).json()
        other_channel = (await client.get(
            "/api/widgets/public/chat-roulette?account_id=1&channel=other"
        )).json()
        other_account = (await client.get(
            "/api/widgets/public/chat-roulette?account_id=2&channel=chan"
        )).json()
        legacy = (await client.get("/api/widgets/public/chat-roulette")).json()

    assert own["participants"] == ["Own", "Viewer"]
    assert own["winner"] == "Own" and own["theme"] == "neon"
    assert other_channel["participants"] == [] and other_account["participants"] == []
    assert legacy["participants"] == ["Legacy"] and legacy["theme"] == "legacy"


async def test_spin_reads_only_matching_account_and_normalized_channel(tmp_db, disable_auth):
    from app.database import get_db

    async with await _client() as client:
        db = await get_db()
        try:
            await db.executemany(
                "INSERT INTO chat_log (account_id, channel, author, message) VALUES (?, ?, ?, 'hi')",
                (
                    (1, "#CHAN", "OwnA"),
                    (1, "chan", "OwnB"),
                    (1, "other", "WrongChannel"),
                    (2, "chan", "WrongAccount"),
                ),
            )
            await db.commit()
        finally:
            await db.close()

        spun = (await client.post(
            "/api/widgets/chat-roulette/spin?account_id=1&channel=CHAN",
            json={"channel": "other", "minutes": 10},
        )).json()
        own = (await client.get(
            "/api/widgets/public/chat-roulette?account_id=1&channel=chan"
        )).json()
        other = (await client.get(
            "/api/widgets/public/chat-roulette?account_id=1&channel=other"
        )).json()

    assert spun["participants"] == ["OwnA", "OwnB"]
    assert spun["winner"] in {"OwnA", "OwnB"}
    assert own["participants"] == ["OwnA", "OwnB"] and own["winner"] == spun["winner"]
    assert other["participants"] == [] and other["winner"] == ""


async def test_legacy_spin_contract_remains_global(tmp_db, disable_auth):
    from app.database import get_db

    async with await _client() as client:
        db = await get_db()
        try:
            await db.executemany(
                "INSERT INTO chat_log (account_id, channel, author, message) VALUES (?, ?, ?, 'hi')",
                ((1, "chan", "LegacyA"), (2, "other", "LegacyB")),
            )
            await db.commit()
        finally:
            await db.close()
        state = (await client.post(
            "/api/widgets/chat-roulette/spin", json={"minutes": 10},
        )).json()

    assert state["participants"] == ["LegacyA", "LegacyB"]


async def test_scope_must_be_complete_and_configured(tmp_db, disable_auth):
    async with await _client() as client:
        for query in ("account_id=1", "channel=chan", "account_id=9&channel=chan"):
            response = await client.get(f"/api/widgets/public/chat-roulette?{query}")
            assert response.status_code == 400


async def test_runtime_and_panel_forward_scope():
    panel_state = (ROOT / "static/app/07_widgets.js").read_text(encoding="utf-8")
    panel_actions = (ROOT / "static/app/15_feedback_2908.js").read_text(encoding="utf-8")
    runtime = (ROOT / "widgets/chat-roulette/index.html").read_text(encoding="utf-8")

    assert "'/widget/chat-roulette'" in panel_state
    assert "wstateapi('/api/widgets/chat-roulette'" in panel_actions
    assert "wstateapi('/api/widgets/chat-roulette/spin'" in panel_actions
    assert "scope.set('account_id'" in runtime and "scope.set('channel'" in runtime
