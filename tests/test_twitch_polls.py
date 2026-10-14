"""Track 6.10: native Twitch Poll lifecycle never calls Helix unverified."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


class _Response:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


async def _seed_scope(account_id: int = 1, channel: str = "owner") -> None:
    from app.database import get_db, init_db

    await init_db()
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO accounts (id, nickname, token, enabled) VALUES (?, ?, 'stored', 1)",
            (account_id, f"bot-{account_id}"),
        )
        await db.execute(
            "INSERT INTO channels (account_id, channel_name, enabled) VALUES (?, ?, 1)",
            (account_id, channel),
        )
        await db.commit()
    finally:
        await db.close()


def _authorize(monkeypatch, scopes: list[str], login: str = "owner") -> None:
    import app.twitch_polls as polls
    import app.twitch_helix as helix

    polls._POLL_CACHE.clear()

    async def token(_account_id: int) -> str:
        return "oauth:token"

    async def validate(_token: str) -> dict:
        return {"login": login, "user_id": "42", "scopes": scopes}

    monkeypatch.setattr(polls, "_account_token", token)
    monkeypatch.setattr(helix, "validate_token", validate)
    monkeypatch.setattr(helix, "_client_id", lambda: "client-id")


def _fake_client(monkeypatch, response: _Response, calls: list[tuple[str, str]]) -> None:
    import httpx

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, **kwargs):
            calls.append(("GET", url))
            return response

        async def post(self, url, **kwargs):
            calls.append(("POST", url))
            return response

        async def patch(self, url, **kwargs):
            calls.append(("PATCH", url))
            return response

    monkeypatch.setattr(httpx, "AsyncClient", Client)


async def test_poll_requires_enabled_exact_account_channel_before_helix(tmp_db, monkeypatch):
    import app.twitch_polls as polls

    await _seed_scope()
    _authorize(monkeypatch, ["channel:manage:polls"])
    calls: list[tuple[str, str]] = []
    _fake_client(monkeypatch, _Response(200), calls)

    result = await polls.create_poll(1, "other", "Question", ["One", "Two"])
    assert result == {"error": "account_channel_mismatch"}
    assert calls == []


async def test_poll_requires_broadcaster_identity_and_scope_before_helix(tmp_db, monkeypatch):
    import app.twitch_polls as polls

    await _seed_scope()
    calls: list[tuple[str, str]] = []
    _fake_client(monkeypatch, _Response(200), calls)

    _authorize(monkeypatch, [], login="owner")
    assert await polls.create_poll(1, "owner", "Question", ["One", "Two"]) == {"error": "missing_scope"}
    assert calls == []

    _authorize(monkeypatch, ["channel:manage:polls"], login="someone-else")
    assert await polls.create_poll(1, "owner", "Question", ["One", "Two"]) == {
        "error": "broadcaster_token_required"
    }
    assert calls == []


@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, "invalid_token"), (403, "helix_forbidden"), (429, "rate_limited")],
)
async def test_poll_create_maps_helix_auth_and_rate_errors(tmp_db, monkeypatch, status, expected):
    import app.twitch_polls as polls

    await _seed_scope()
    _authorize(monkeypatch, ["channel:manage:polls"])
    calls: list[tuple[str, str]] = []
    _fake_client(monkeypatch, _Response(status), calls)

    assert await polls.create_poll(1, "owner", "Question", ["One", "Two"]) == {"error": expected}
    assert calls and calls[0][0] == "POST"


async def test_poll_active_status_and_safe_early_termination(tmp_db, monkeypatch):
    import app.twitch_polls as polls

    await _seed_scope()
    _authorize(monkeypatch, ["channel:read:polls", "channel:manage:polls"])
    active = {
        "data": [{
            "id": "poll-1", "title": "Question", "status": "ACTIVE", "duration_seconds": 120,
            "choices": [{"title": "One", "votes": 7}, {"title": "Two", "votes": 4}],
        }],
    }
    calls: list[tuple[str, str]] = []

    class LifecycleClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, **kwargs):
            calls.append(("GET", url))
            return _Response(200, active)

        async def patch(self, url, **kwargs):
            calls.append(("PATCH", url))
            return _Response(200, {"data": [{**active["data"][0], "status": "TERMINATED"}]})

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", LifecycleClient)

    status = await polls.get_active_poll(1, "#OWNER")
    assert status == {
        "id": "poll-1", "title": "Question", "status": "ACTIVE", "duration": 120,
        "started_at": "", "choices": [{"title": "One", "votes": 7}, {"title": "Two", "votes": 4}],
    }
    ended = await polls.end_poll(1, "owner")
    assert ended["ok"] is True and ended["poll"]["status"] == "TERMINATED"
    assert [method for method, _ in calls] == ["GET", "GET", "PATCH"]
