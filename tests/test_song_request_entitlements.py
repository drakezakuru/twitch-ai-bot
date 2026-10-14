"""Track 6.7: idempotent scoped Channel Points and donation entitlements."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio


async def _client() -> AsyncClient:
    from app.database import get_db, init_db
    from app.song_request_routes import router

    await init_db()
    db = await get_db()
    try:
        await db.executemany(
            "INSERT OR IGNORE INTO accounts (id, nickname, token) VALUES (?, ?, 'fake')",
            ((1, "one"), (2, "two")),
        )
        await db.executemany(
            "INSERT OR IGNORE INTO channels (account_id, channel_name, enabled) VALUES (?, ?, 1)",
            ((1, "chan"), (1, "other"), (2, "chan")),
        )
        await db.commit()
    finally:
        await db.close()
    app = FastAPI()
    app.include_router(router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _configure_queue(account_id: int, channel: str) -> None:
    from app.database import get_db

    db = await get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO widget_song_request_settings_scoped "
            "(account_id, channel, cooldown_sec, max_per_user) VALUES (?, ?, 0, 0)",
            (account_id, channel),
        )
        await db.execute(
            "UPDATE widget_song_request_settings_scoped SET cooldown_sec = 0, max_per_user = 0 "
            "WHERE account_id = ? AND channel = ?",
            (account_id, channel),
        )
        await db.commit()
    finally:
        await db.close()


async def test_entitlement_config_is_exact_scope_and_donation_is_fail_closed(
    tmp_db, disable_auth,
):
    async with await _client() as client:
        incomplete = await client.put(
            "/api/widgets/song-request/entitlements?account_id=1&channel=chan",
            json={"donation_enabled": True},
        )
        assert incomplete.status_code == 400
        saved = (await client.put(
            "/api/widgets/song-request/entitlements?account_id=1&channel=%23CHAN",
            json={
                "donation_enabled": True,
                "donation_threshold": 25,
                "donation_currency": "usd",
                "donation_action": "create",
            },
        )).json()["settings"]
        other = (await client.get(
            "/api/widgets/song-request/entitlements?account_id=1&channel=other"
        )).json()["settings"]

    assert saved["donation_threshold"] == 25
    assert saved["donation_currency"] == "USD"
    assert other["donation_enabled"] == 0


async def test_channel_points_uses_stable_reward_id_and_is_idempotent(
    tmp_db, disable_auth,
):
    from app.song_request_service import handle_channel_points, save_entitlement_settings
    from app.widgets import _get_sr_now_playing, _get_sr_queue

    await _client()
    await _configure_queue(1, "chan")
    await save_entitlement_settings((1, "chan"), {
        "points_create_reward_id": "reward-create",
        "points_create_reward_title": "old title fallback must not match",
    })
    payload = {
        "id": "redemption-1",
        "reward": {"id": "reward-create", "title": "Renamed reward"},
        "user_input": "Requested Track",
        "user_id": "viewer-42",
    }
    first = await handle_channel_points(1, "CHAN", payload)
    duplicate = await handle_channel_points(1, "chan", payload)
    wrong_id = await handle_channel_points(1, "chan", {
        **payload, "id": "redemption-2",
        "reward": {"id": "other", "title": "old title fallback must not match"},
    })

    now = await _get_sr_now_playing((1, "chan"))
    queued = await _get_sr_queue(50, (1, "chan"))
    assert first["ok"] is True
    assert duplicate["error"] == "duplicate_event"
    assert wrong_id == {"handled": False}
    assert now["title"] == "Requested Track"
    assert queued == []


async def test_points_priority_boosts_existing_item_without_duplication(
    tmp_db, disable_auth,
):
    from app.database import get_db, init_db
    from app.song_request_service import handle_channel_points, save_entitlement_settings
    from app.widgets import add_song_request

    await init_db()
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO accounts (id, nickname, token) VALUES (1, 'one', 'fake')"
        )
        await db.execute(
            "INSERT OR IGNORE INTO channels (account_id, channel_name, enabled) VALUES (1, 'chan', 1)"
        )
        await db.commit()
    finally:
        await db.close()
    await _configure_queue(1, "chan")
    created = await add_song_request("Boost Me", "viewer", "chan", account_id=1)
    await save_entitlement_settings((1, "chan"), {"points_priority_reward_id": "boost"})
    result = await handle_channel_points(1, "chan", {
        "id": "boost-event", "reward": {"id": "boost", "title": "Boost"},
        "user_input": "boost me", "user_id": "viewer",
    })
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, priority FROM widget_song_request_queue_scoped "
            "WHERE account_id = 1 AND channel = 'chan'"
        )
        rows = await cursor.fetchall()
    finally:
        await db.close()

    assert result["reason"] == "priority_boosted"
    assert len(rows) == 1
    assert rows[0]["id"] == created["id"] and rows[0]["priority"] == 10


async def test_donation_threshold_rejection_and_acceptance_are_idempotent_and_audited(
    tmp_db, disable_auth,
):
    from app.song_request_service import (
        handle_donation, list_audit, save_entitlement_settings,
    )

    await _client()
    await _configure_queue(1, "chan")
    await save_entitlement_settings((1, "chan"), {
        "donation_enabled": True,
        "donation_threshold": 10,
        "donation_currency": "EUR",
        "donation_action": "create",
    })
    low = await handle_donation(
        1, "chan", platform="donatex", event_id="donation-low", username="alice",
        amount=5, currency="EUR", message="Low Track",
    )
    accepted = await handle_donation(
        1, "chan", platform="donatex", event_id="donation-ok", username="alice",
        amount=15, currency="EUR", message="Paid Track",
    )
    duplicate = await handle_donation(
        1, "chan", platform="donatex", event_id="donation-ok", username="alice",
        amount=15, currency="EUR", message="Different Track",
    )
    audit = await list_audit((1, "chan"))

    assert low["error"] == "below_threshold"
    assert accepted["ok"] is True
    assert duplicate["error"] == "duplicate_event"
    assert [item["reason"] for item in audit] == ["accepted", "below_threshold"]


async def test_donation_missing_id_currency_rejection_and_event_claim_are_exact_scope(
    tmp_db, disable_auth,
):
    from app.song_request_service import (
        handle_donation, list_audit, save_entitlement_settings,
    )
    from app.widgets import _get_sr_now_playing

    await _client()
    await _configure_queue(1, "chan")
    await _configure_queue(1, "other")
    policy = {
        "donation_enabled": True,
        "donation_threshold": 10,
        "donation_currency": "EUR",
        "donation_action": "create",
    }
    await save_entitlement_settings((1, "chan"), policy)
    await save_entitlement_settings((1, "other"), policy)

    missing_id = await handle_donation(
        1, "chan", platform="donatex", event_id="", username="alice",
        amount=15, currency="EUR", message="No ID Track",
    )
    wrong_currency = await handle_donation(
        1, "chan", platform="donatex", event_id="shared-event", username="alice",
        amount=15, currency="USD", message="Wrong Currency Track",
    )
    other_scope = await handle_donation(
        1, "other", platform="donatex", event_id="shared-event", username="alice",
        amount=15, currency="EUR", message="Other Scope Track",
    )

    assert missing_id["error"] == "missing_event_id"
    assert wrong_currency["error"] == "currency_mismatch"
    assert other_scope["ok"] is True
    assert await _get_sr_now_playing((1, "chan")) is None
    assert (await _get_sr_now_playing((1, "other")))["title"] == "Other Scope Track"
    assert [item["reason"] for item in await list_audit((1, "chan"))] == [
        "currency_mismatch", "missing_event_id",
    ]
    assert [item["reason"] for item in await list_audit((1, "other"))] == ["accepted"]
