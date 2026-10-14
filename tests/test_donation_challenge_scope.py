"""Donation Challenge state is isolated by account and normalized channel."""
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
            ((1, "donation_one"), (2, "donation_two")),
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


async def test_scoped_crud_and_public_read_do_not_leak(tmp_db, disable_auth):
    async with await _client() as client:
        scoped = (await client.post("/api/widgets/donation-challenges", json={
            "account_id": 1, "channel": " #ChAn ", "title": "Scoped", "target_amount": 100,
        })).json()
        legacy = (await client.post("/api/widgets/donation-challenges", json={
            "title": "Legacy", "target_amount": 50,
        })).json()

        own = (await client.get(
            "/api/widgets/public/donation-challenge/active?account_id=1&channel=CHAN"
        )).json()
        other_channel = (await client.get(
            "/api/widgets/public/donation-challenge/active?account_id=1&channel=other"
        )).json()
        other_account = (await client.get(
            "/api/widgets/public/donation-challenge/active?account_id=2&channel=chan"
        )).json()
        legacy_state = (await client.get(
            "/api/widgets/public/donation-challenge/active"
        )).json()

        assert own["id"] == scoped["id"] and own["title"] == "Scoped"
        assert other_channel == {"active": False}
        assert other_account == {"active": False}
        assert legacy_state["id"] == legacy["id"] and legacy_state["title"] == "Legacy"

        scoped_list = (await client.get(
            "/api/widgets/donation-challenges?account_id=1&channel=chan"
        )).json()
        legacy_list = (await client.get("/api/widgets/donation-challenges")).json()
        assert [item["id"] for item in scoped_list["challenges"]] == [scoped["id"]]
        assert [item["id"] for item in legacy_list["challenges"]] == [legacy["id"]]

        blocked = (await client.post(
            f"/api/widgets/donation-challenges/{scoped['id']}/add-funds",
            json={"amount": 10},
        )).json()
        assert blocked == {"ok": False, "error": "not_found"}
        added = (await client.post(
            f"/api/widgets/donation-challenges/{scoped['id']}/add-funds"
            "?account_id=1&channel=chan",
            json={"amount": 10},
        )).json()
        assert added["ok"] is True and added["current_amount"] == 10
        own_after = (await client.get(
            "/api/widgets/public/donation-challenge/active?account_id=1&channel=chan"
        )).json()
        assert own_after["current_amount"] == 10


@pytest.mark.parametrize("query", ("account_id=1", "channel=chan", "account_id=9&channel=chan"))
async def test_scope_is_complete_and_configured(tmp_db, disable_auth, query):
    async with await _client() as client:
        response = await client.get(
            f"/api/widgets/public/donation-challenge/active?{query}"
        )
    assert response.status_code == 400


async def test_owner_panel_uses_selected_scope_and_scoped_obs_url():
    panel = (ROOT / "templates/partials/widgets.html").read_text(encoding="utf-8")
    widgets_js = (ROOT / "static/app/07_widgets.js").read_text(encoding="utf-8")
    session_js = (ROOT / "static/app/13_widgets_session.js").read_text(encoding="utf-8")

    assert 'id="waDonationChallengesList"' in panel
    assert "waCopyWidgetUrl('/widget/donation-challenge')" in panel
    assert "'/widget/donation-challenge'" in widgets_js
    assert "...scope, title:" in session_js
    assert "wstateapi('/api/widgets/donation-challenges')" in session_js
    assert "wstateapi('/api/widgets/donation-integration')" in session_js
    assert "wstateapi('/api/widgets/donation-goal-sync')" in session_js
    assert "'/widget/subathon-timer'" in widgets_js


async def test_scoped_donation_mutates_only_matching_challenge_and_subathon(
    tmp_db, disable_auth,
):
    async with await _client() as client:
        challenge_ids = {}
        for account_id, channel in ((1, "chan"), (1, "other"), (2, "chan")):
            created = (await client.post("/api/widgets/donation-challenges", json={
                "account_id": account_id, "channel": channel,
                "title": f"{account_id}:{channel}", "target_amount": 100,
            })).json()
            challenge_ids[(account_id, channel)] = created["id"]
            await client.put(
                f"/api/widgets/subathon?account_id={account_id}&channel={channel}",
                json={"seconds_per_donation": 30, "seconds_per_currency": 1},
            )
            await client.post(
                f"/api/widgets/subathon/start?account_id={account_id}&channel={channel}",
                json={"minutes": 10},
            )

        before = {}
        for scope in challenge_ids:
            response = await client.get(
                f"/api/widgets/public/subathon?account_id={scope[0]}&channel={scope[1]}"
            )
            before[scope] = response.json()["remaining"]

        from app.widgets import on_donation_received
        await on_donation_received(
            "donatex", "ScopedDonor", 25, "RUB", "",
            account_id=1, channel="#CHAN",
        )

        from app.database import get_db
        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT id, current_amount FROM donation_challenges ORDER BY id"
            )
            amounts = {row["id"]: row["current_amount"] for row in await cursor.fetchall()}
        finally:
            await db.close()
        assert amounts[challenge_ids[(1, "chan")]] == 25
        assert amounts[challenge_ids[(1, "other")]] == 0
        assert amounts[challenge_ids[(2, "chan")]] == 0

        after = {}
        for scope in challenge_ids:
            response = await client.get(
                f"/api/widgets/public/subathon?account_id={scope[0]}&channel={scope[1]}"
            )
            after[scope] = response.json()["remaining"]
        assert after[(1, "chan")] >= before[(1, "chan")] + 23
        assert after[(1, "other")] <= before[(1, "other")]
        assert after[(2, "chan")] <= before[(2, "chan")]


async def test_scoped_integration_crud_masks_and_isolates_tokens(tmp_db, disable_auth):
    async with await _client() as client:
        for account_id, channel, token in (
            (1, "chan", "secret-one"), (1, "other", "secret-other"),
            (2, "chan", "secret-two"),
        ):
            response = await client.put(
                f"/api/widgets/donation-integration?account_id={account_id}&channel={channel}",
                json={
                    "platform": "donatex", "enabled": True, "token": token,
                    "webhook_token": f"webhook-{account_id}-{channel}",
                },
            )
            assert response.json() == {"ok": True, "platform": "donatex", "enabled": True}

        own = (await client.get(
            "/api/widgets/donation-integration?account_id=1&channel=chan"
        )).json()["items"]
        other = (await client.get(
            "/api/widgets/donation-integration?account_id=2&channel=chan"
        )).json()["items"]
        assert own[0]["token_hint"] == "…-one"
        assert other[0]["token_hint"] == "…-two"
        assert own[0]["webhook_token_set"] is True
        assert "secret-one" not in str(own) and "secret-two" not in str(other)
        assert "webhook-1-chan" not in str(own)


async def test_scoped_webhook_requires_secret_and_routes_exact_scope(
    tmp_db, disable_auth, monkeypatch,
):
    monkeypatch.setenv("DONATION_WEBHOOK_SECRET", "legacy-global-secret")
    async with await _client() as client:
        created = (await client.post("/api/widgets/donation-challenges", json={
            "account_id": 1, "channel": "chan", "title": "Scoped", "target_amount": 100,
        })).json()
        payload = {
            "account_id": 1, "channel": "chan", "username": "Webhook",
            "event_id": "scope-event", "amount": 12, "currency": "RUB",
        }
        denied = (await client.post(
            "/api/widgets/public/donation-webhook", json=payload,
        )).json()
        assert denied == {"error": "webhook_not_configured"}
        bridge_token = (await client.post(
            "/api/widgets/donation-bridge/rotate?account_id=1&channel=chan", json={},
        )).json()["token"]
        accepted = (await client.post(
            "/api/widgets/public/donation-webhook",
            json={**payload, "secret": bridge_token},
        )).json()
        assert accepted == {"ok": True}
        state = (await client.get(
            "/api/widgets/public/donation-challenge/active?account_id=1&channel=chan"
        )).json()
        assert state["id"] == created["id"] and state["current_amount"] == 12


async def test_scoped_webhook_token_cannot_mutate_another_scope(tmp_db, disable_auth):
    async with await _client() as client:
        for channel in ("chan", "other"):
            await client.post("/api/widgets/donation-challenges", json={
                "account_id": 1, "channel": channel, "title": channel, "target_amount": 100,
            })
            await client.put(
                f"/api/widgets/donation-integration?account_id=1&channel={channel}",
                json={
                    "platform": "donatex", "enabled": False,
                    "webhook_token": f"token-{channel}",
                },
            )
        wrong = (await client.post("/api/widgets/public/donation-webhook", json={
            "account_id": 1, "channel": "other", "secret": "token-chan",
            "username": "X", "amount": 9,
        })).json()
        assert wrong == {"error": "bad_secret"}
        accepted = (await client.post("/api/widgets/public/donation-webhook", json={
            "account_id": 1, "channel": "chan", "secret": "token-chan",
            "event_id": "token-event", "username": "X", "amount": 9,
        })).json()
        assert accepted == {"ok": True}


async def test_webhook_receipts_are_independent_between_scopes(
    tmp_db, disable_auth, monkeypatch,
):
    monkeypatch.setenv("DONATION_WEBHOOK_SECRET", "legacy-global-secret")
    async with await _client() as client:
        ids = {}
        for account_id in (1, 2):
            ids[account_id] = (await client.post(
                "/api/widgets/donation-challenges", json={
                    "account_id": account_id, "channel": "chan",
                    "title": f"Scoped {account_id}", "target_amount": 100,
                },
            )).json()["id"]
            bridge_token = (await client.post(
                "/api/widgets/donation-bridge/rotate"
                f"?account_id={account_id}&channel=chan", json={},
            )).json()["token"]
            response = (await client.post(
                "/api/widgets/public/donation-webhook", json={
                    "account_id": account_id, "channel": "#CHAN",
                    "event_id": "shared-provider-id", "secret": bridge_token,
                    "username": "Webhook", "amount": 11,
                },
            )).json()
            assert response == {"ok": True}

        account_one_token = (await client.get(
            "/api/widgets/donation-bridge/reveal?account_id=1&channel=chan"
        )).json()["token"]
        duplicate = (await client.post(
            "/api/widgets/public/donation-webhook", json={
                "account_id": 1, "channel": "chan", "event_id": "shared-provider-id",
                "secret": account_one_token, "username": "Webhook", "amount": 11,
            },
        )).json()
        assert duplicate == {"ok": True, "duplicate": True}

        from app.database import get_db
        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT id, current_amount FROM donation_challenges WHERE id IN (?, ?)",
                (ids[1], ids[2]),
            )
            amounts = {row["id"]: row["current_amount"] for row in await cursor.fetchall()}
        finally:
            await db.close()
        assert amounts == {ids[1]: 11, ids[2]: 11}


async def test_scoped_goal_sync_updates_only_its_challenge(
    tmp_db, disable_auth, monkeypatch,
):
    async with await _client() as client:
        ids = {}
        for channel in ("chan", "other"):
            ids[channel] = (await client.post("/api/widgets/donation-challenges", json={
                "account_id": 1, "channel": channel, "title": channel, "target_amount": 1000,
            })).json()["id"]
        configured = (await client.put(
            "/api/widgets/donation-goal-sync?account_id=1&channel=chan",
            json={"external_goal_id": "goal-scoped", "enabled": True},
        )).json()
        assert configured == {"ok": True}
        conflict = (await client.put(
            "/api/widgets/donation-goal-sync?account_id=1&channel=other",
            json={"external_goal_id": "goal-scoped", "enabled": True},
        )).json()
        assert conflict == {"ok": False, "error": "goal_scope_conflict"}

        state = {"current": 100.0}
        async def fake_goal(_goal_id):
            return {"name": "Scoped", "current": state["current"], "target": 1000, "currency": "RUB"}

        monkeypatch.setattr("app.donation_integrations.fetch_donatex_goal", fake_goal)
        from app.donation_integrations import _sync_donatex_goal_once
        assert await _sync_donatex_goal_once((1, "chan")) is True
        state["current"] = 140.0
        assert await _sync_donatex_goal_once((1, "chan")) is True

        from app.database import get_db
        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT id, current_amount FROM donation_challenges WHERE id IN (?, ?)",
                (ids["chan"], ids["other"]),
            )
            amounts = {row["id"]: row["current_amount"] for row in await cursor.fetchall()}
        finally:
            await db.close()
        assert amounts[ids["chan"]] == 40
        assert amounts[ids["other"]] == 0


async def test_subscribe_extends_only_matching_scoped_subathon(tmp_db, disable_auth):
    async with await _client() as client:
        for channel in ("chan", "other"):
            await client.put(
                f"/api/widgets/subathon?account_id=1&channel={channel}",
                json={"seconds_per_sub": 45},
            )
            await client.post(
                f"/api/widgets/subathon/start?account_id=1&channel={channel}",
                json={"minutes": 10},
            )
        before = {}
        for channel in ("chan", "other"):
            before[channel] = (await client.get(
                f"/api/widgets/public/subathon?account_id=1&channel={channel}"
            )).json()["remaining"]

        from app.widgets import on_subscribe_event
        await on_subscribe_event(account_id=1, channel="#CHAN")

        after = {}
        for channel in ("chan", "other"):
            after[channel] = (await client.get(
                f"/api/widgets/public/subathon?account_id=1&channel={channel}"
            )).json()["remaining"]
        assert after["chan"] >= before["chan"] + 43
        assert after["other"] <= before["other"]


async def test_scoped_donation_history_and_public_top_do_not_leak(tmp_db, disable_auth):
    async with await _client() as client:
        from app.widgets import on_donation_received

        await on_donation_received(
            "donatepay", "One", 10, "RUB", "", account_id=1, channel="chan",
        )
        await on_donation_received(
            "donatex", "Other", 20, "RUB", "", account_id=1, channel="other",
        )
        await on_donation_received(
            "donationalerts", "Two", 30, "RUB", "", account_id=2, channel="chan",
        )

        one = (await client.get(
            "/api/widgets/public/top-donator/alltime?account_id=1&channel=chan"
        )).json()["donors"]
        other = (await client.get(
            "/api/widgets/public/top-donator/alltime?account_id=1&channel=other"
        )).json()["donors"]
        two = (await client.get(
            "/api/widgets/public/top-donator/alltime?account_id=2&channel=chan"
        )).json()["donors"]
        assert [item["username"] for item in one] == ["One"]
        assert [item["username"] for item in other] == ["Other"]
        assert [item["username"] for item in two] == ["Two"]


async def test_local_bridge_rotation_revokes_old_token_and_remote_is_rejected(
    tmp_db, disable_auth, monkeypatch,
):
    monkeypatch.delenv("DONATION_WEBHOOK_SECRET", raising=False)
    async with await _client() as client:
        await client.put(
            "/api/widgets/donation-integration?account_id=1&channel=chan",
            json={
                "platform": "donatepay", "enabled": False,
                "webhook_token": "legacy-bridge-token",
            },
        )
        legacy = (await client.post("/api/widgets/public/donation-webhook", json={
            "account_id": 1, "channel": "chan", "event_id": "legacy-event",
            "secret": "legacy-bridge-token", "username": "Legacy", "amount": 1,
        })).json()
        assert legacy == {"ok": True}

        rotated = (await client.post(
            "/api/widgets/donation-bridge/rotate?account_id=1&channel=chan", json={},
        )).json()
        assert rotated["ok"] is True and rotated["hide_after_seconds"] == 30
        new_token = rotated["token"]
        status = (await client.get(
            "/api/widgets/donation-bridge?account_id=1&channel=chan"
        )).json()
        assert status["enabled"] is True and status["token_set"] is True
        assert new_token not in str(status)
        reveal = (await client.get(
            "/api/widgets/donation-bridge/reveal?account_id=1&channel=chan"
        )).json()
        assert reveal == {"token": new_token, "hide_after_seconds": 30}

        old = (await client.post("/api/widgets/public/donation-webhook", json={
            "account_id": 1, "channel": "chan", "event_id": "old-event",
            "secret": "legacy-bridge-token", "username": "Old", "amount": 1,
        })).json()
        assert old == {"error": "bad_secret"}
        fresh = (await client.post("/api/widgets/public/donation-webhook", json={
            "account_id": 1, "channel": "chan", "event_id": "new-event",
            "secret": new_token, "username": "Fresh", "amount": 1,
        })).json()
        assert fresh == {"ok": True}
        monkeypatch.setenv("DONATION_WEBHOOK_SECRET", "global-legacy-secret")
        scoped_global = (await client.post("/api/widgets/public/donation-webhook", json={
            "account_id": 1, "channel": "chan", "event_id": "global-event",
            "secret": "global-legacy-secret", "username": "Global", "amount": 1,
        })).json()
        assert scoped_global == {"error": "bad_secret"}
        cross_origin = await client.put(
            "/api/widgets/donation-bridge?account_id=1&channel=chan",
            json={"enabled": False}, headers={"origin": "https://attacker.example"},
        )
        assert cross_origin.status_code == 403

    from app.widgets import admin_router, public_router
    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(public_router)
    transport = ASGITransport(app=app, client=("198.51.100.8", 4321))
    async with AsyncClient(transport=transport, base_url="http://test") as remote:
        response = await remote.post("/api/widgets/public/donation-webhook", json={
            "account_id": 1, "channel": "chan", "event_id": "remote-event",
            "secret": new_token, "username": "Remote", "amount": 1,
        })
        remote_toggle = await remote.put(
            "/api/widgets/donation-bridge?account_id=1&channel=chan",
            json={"enabled": False},
        )
    assert response.status_code == 403
    assert remote_toggle.status_code == 403
