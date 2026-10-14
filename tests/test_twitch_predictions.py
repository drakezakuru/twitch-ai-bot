"""Native Twitch Prediction creation never calls Helix before authorization."""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.asyncio


class _Response:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


async def _seed_scope() -> None:
    from app.database import get_db, init_db

    await init_db()
    db = await get_db()
    try:
        await db.execute("INSERT INTO accounts (id, nickname, token, enabled) VALUES (1, 'owner', 'stored', 1)")
        await db.execute("INSERT INTO channels (account_id, channel_name, enabled) VALUES (1, 'owner', 1)")
        await db.commit()
    finally:
        await db.close()


def _authorize(monkeypatch, scopes: list[str], login: str = "owner") -> None:
    import app.twitch_helix as helix
    import app.twitch_polls as polls

    async def token(_account_id: int) -> str:
        return "oauth:token"

    async def validate(_token: str) -> dict:
        return {"login": login, "user_id": "42", "scopes": scopes}

    monkeypatch.setattr(polls, "_account_token", token)
    monkeypatch.setattr(helix, "validate_token", validate)
    monkeypatch.setattr(helix, "_client_id", lambda: "client-id")


def _fake_client(monkeypatch, response: _Response, calls: list[dict]) -> None:
    import httpx

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, **kwargs):
            calls.append({"url": url, **kwargs})
            return response

    monkeypatch.setattr(httpx, "AsyncClient", Client)


async def test_prediction_requires_enabled_exact_scope_before_helix(tmp_db, monkeypatch):
    import app.twitch_predictions as predictions

    await _seed_scope()
    _authorize(monkeypatch, ["channel:manage:predictions"])
    calls: list[dict] = []
    _fake_client(monkeypatch, _Response(200), calls)

    assert await predictions.create_prediction(1, "other", "Question", ["Yes", "No"]) == {
        "error": "account_channel_mismatch"
    }
    assert calls == []


async def test_prediction_route_rejects_malformed_scope_without_calling_helix(tmp_db, monkeypatch):
    import app.twitch_predictions as predictions

    calls: list[dict] = []
    _fake_client(monkeypatch, _Response(200), calls)

    assert await predictions.create_prediction_route({
        "account_id": "not-an-id", "channel": "owner", "title": "Question", "outcomes": ["Yes", "No"],
    }) == {"error": "account_and_channel_required"}
    assert calls == []


async def test_prediction_requires_broadcaster_identity_and_prediction_scope(tmp_db, monkeypatch):
    import app.twitch_predictions as predictions

    await _seed_scope()
    calls: list[dict] = []
    _fake_client(monkeypatch, _Response(200), calls)

    _authorize(monkeypatch, [])
    assert await predictions.create_prediction(1, "owner", "Question", ["Yes", "No"]) == {"error": "missing_scope"}
    assert calls == []

    _authorize(monkeypatch, ["channel:manage:predictions"], login="someone-else")
    assert await predictions.create_prediction(1, "owner", "Question", ["Yes", "No"]) == {
        "error": "broadcaster_token_required"
    }
    assert calls == []


async def test_prediction_creates_helix_payload_and_maps_response(tmp_db, monkeypatch):
    import app.twitch_predictions as predictions

    await _seed_scope()
    _authorize(monkeypatch, ["channel:manage:predictions"])
    calls: list[dict] = []
    _fake_client(monkeypatch, _Response(200, {"data": [{
        "id": "prediction-1", "title": "Question", "status": "ACTIVE", "winning_outcome_id": None, "prediction_window": 300,
        "created_at": "2026-09-05T00:00:00Z", "outcomes": [
            {"id": "yes", "title": "Yes", "color": "BLUE", "users": 2, "channel_points": 50},
        ],
    }]}), calls)

    result = await predictions.create_prediction(1, "#OWNER", "Question", ["Yes", "No"], 300)

    assert result == {"ok": True, "prediction": {
        "id": "prediction-1", "title": "Question", "status": "ACTIVE", "winning_outcome_id": None, "prediction_window": 300,
        "created_at": "2026-09-05T00:00:00Z", "outcomes": [
            {"id": "yes", "title": "Yes", "color": "BLUE", "users": 2, "channel_points": 50},
        ],
    }}
    assert calls == [{
        "url": "https://api.twitch.tv/helix/predictions",
        "headers": {"Authorization": "Bearer token", "Client-Id": "client-id"},
        "json": {
            "broadcaster_id": "42", "title": "Question", "outcomes": [{"title": "Yes"}, {"title": "No"}],
            "prediction_window": 300,
        },
    }]


@pytest.mark.parametrize(("status", "expected"), [(401, "invalid_token"), (403, "helix_forbidden"), (429, "rate_limited")])
async def test_prediction_maps_helix_access_errors(tmp_db, monkeypatch, status, expected):
    import app.twitch_predictions as predictions

    await _seed_scope()
    _authorize(monkeypatch, ["channel:manage:predictions"])
    calls: list[dict] = []
    _fake_client(monkeypatch, _Response(status), calls)

    assert await predictions.create_prediction(1, "owner", "Question", ["Yes", "No"]) == {"error": expected}
    assert len(calls) == 1


def _lifecycle_client(monkeypatch, prediction: dict, calls: list[dict]) -> None:
    import httpx

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, **kwargs):
            calls.append({"method": "get", "url": url, **kwargs})
            return _Response(200, {"data": [prediction]})

        async def patch(self, url, **kwargs):
            calls.append({"method": "patch", "url": url, **kwargs})
            prediction["status"] = kwargs["json"]["status"]
            if "winning_outcome_id" in kwargs["json"]:
                prediction["winning_outcome_id"] = kwargs["json"]["winning_outcome_id"]
            return _Response(200, {"data": [prediction]})

    monkeypatch.setattr(httpx, "AsyncClient", Client)


async def test_prediction_lifecycle_locks_resolves_and_cancels_exact_scope(tmp_db, monkeypatch):
    import app.twitch_predictions as predictions

    await _seed_scope()
    _authorize(monkeypatch, ["channel:manage:predictions"])
    calls: list[dict] = []
    prediction = {
        "id": "prediction-1", "title": "Question", "status": "ACTIVE", "outcomes": [
            {"id": "yes", "title": "Yes", "channel_points": 50},
            {"id": "no", "title": "No", "channel_points": 25},
        ],
    }
    _lifecycle_client(monkeypatch, prediction, calls)

    active = await predictions.get_active_prediction(1, "#OWNER")
    assert active["prediction"]["status"] == "ACTIVE"
    locked = await predictions.end_prediction(1, "owner", "prediction-1", "LOCKED")
    assert locked["prediction"]["status"] == "LOCKED"
    resolved = await predictions.end_prediction(
        1, "owner", "prediction-1", "RESOLVED", winning_outcome_id="yes",
    )
    assert resolved["prediction"]["status"] == "RESOLVED"
    assert resolved["prediction"]["winning_outcome_id"] == "yes"
    assert [call["json"]["status"] for call in calls if call["method"] == "patch"] == ["LOCKED", "RESOLVED"]

    prediction["status"] = "ACTIVE"
    canceled = await predictions.end_prediction(1, "owner", "prediction-1", "CANCELED", confirmed=True)
    assert canceled["prediction"]["status"] == "CANCELED"


async def test_prediction_lifecycle_rejects_wrong_winner_and_duplicate_action(tmp_db, monkeypatch):
    import app.twitch_predictions as predictions

    await _seed_scope()
    _authorize(monkeypatch, ["channel:manage:predictions"])
    calls: list[dict] = []
    prediction = {
        "id": "prediction-1", "status": "LOCKED", "outcomes": [{"id": "yes", "title": "Yes"}],
    }
    _lifecycle_client(monkeypatch, prediction, calls)

    assert await predictions.end_prediction(1, "owner", "prediction-1", "RESOLVED") == {
        "error": "winning_outcome_required"
    }
    assert await predictions.end_prediction(1, "owner", "prediction-1", "RESOLVED", winning_outcome_id="no") == {
        "error": "winning_outcome_invalid"
    }
    assert await predictions.end_prediction(1, "owner", "prediction-1", "CANCELED") == {
        "error": "confirmation_required"
    }
    assert await predictions.end_prediction(1, "owner", "prediction-1", "RESOLVED", winning_outcome_id="yes") == {
        "ok": True,
        "prediction": {
            "id": "prediction-1", "title": "", "status": "RESOLVED", "winning_outcome_id": "yes",
            "prediction_window": 0, "created_at": "", "outcomes": [
                {"id": "yes", "title": "Yes", "color": "", "users": 0, "channel_points": 0},
            ],
        },
    }
    assert await predictions.end_prediction(1, "owner", "prediction-1", "RESOLVED", winning_outcome_id="yes") == {
        "error": "no_matching_active_prediction"
    }
    assert len([call for call in calls if call["method"] == "patch"]) == 1
