from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from app import database
from app import routes_token_refresh as token_routes
from app import twitch_helix


@pytest.mark.asyncio
async def test_existing_validate_token_still_returns_provider_payload(monkeypatch):
    payload = {
        "login": "bot",
        "user_id": "123",
        "expires_in": 3600,
        "scopes": ["chat:read"],
    }
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=payload)
    )
    original = httpx.AsyncClient

    class Client:
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            self.client = original(*args, **kwargs)

        async def __aenter__(self):
            return await self.client.__aenter__()

        async def __aexit__(self, *args):
            return await self.client.__aexit__(*args)

    monkeypatch.setattr(twitch_helix.httpx, "AsyncClient", Client)

    assert await twitch_helix.validate_token("oauth:test") == payload


@pytest.mark.asyncio
async def test_auto_refresh_defaults_on_with_seven_day_warning():
    await database.init_db()

    assert await token_routes.get_auto_refresh() == {
        "auto_refresh": True,
        "warning_days": 7,
    }


@pytest.mark.asyncio
async def test_auto_refresh_settings_are_independent_and_clamped():
    await database.init_db()

    await token_routes.set_auto_refresh({"auto_refresh": False, "warning_days": 120})
    assert await token_routes.get_auto_refresh() == {
        "auto_refresh": False,
        "warning_days": 90,
    }

    await token_routes.set_auto_refresh({"warning_days": "invalid"})
    assert await token_routes.get_auto_refresh() == {
        "auto_refresh": False,
        "warning_days": 7,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "payload", "expected"),
    [
        (200, {"expires_in": 3600}, {"status": "valid", "expires_in": 3600}),
        (401, {}, {"status": "expired"}),
        (503, {}, {"status": "unknown"}),
    ],
)
async def test_validate_oauth_token_status_distinguishes_expiry(
    monkeypatch, status_code, payload, expected
):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status_code, json=payload)
    )
    original = httpx.AsyncClient

    class Client:
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            self.client = original(*args, **kwargs)

        async def __aenter__(self):
            return await self.client.__aenter__()

        async def __aexit__(self, *args):
            return await self.client.__aexit__(*args)

    monkeypatch.setattr(twitch_helix.httpx, "AsyncClient", Client)

    assert await twitch_helix.validate_oauth_token_status("oauth:test") == expected


@pytest.mark.asyncio
async def test_token_status_uses_expiry_without_provider_call(monkeypatch):
    now = 2_000_000_000

    async def fail_validate(token):
        raise AssertionError("known expiry must not call Twitch")

    monkeypatch.setattr(token_routes, "validate_oauth_token_status", fail_validate)
    base = {"id": 1, "token": "oauth:test", "has_refresh_token": True}

    assert await token_routes._token_status(
        {**base, "token_expires_at": now + 8 * 86400}, 7, now
    ) == "valid"
    assert await token_routes._token_status(
        {**base, "token_expires_at": now + 7 * 86400}, 7, now
    ) == "valid"
    assert await token_routes._token_status(
        {**base, "token_expires_at": now + 6 * 86400}, 7, now
    ) == "expiring"
    assert await token_routes._token_status(
        {**base, "token_expires_at": now - 1}, 7, now
    ) == "expired"


@pytest.mark.asyncio
async def test_manual_token_without_expiry_is_not_refreshable(monkeypatch):
    async def fail_validate(token):
        raise AssertionError("non-refreshable status is known locally")

    monkeypatch.setattr(token_routes, "validate_oauth_token_status", fail_validate)

    status = await token_routes._token_status(
        {
            "id": 1,
            "token": "oauth:manual",
            "token_expires_at": 0,
            "has_refresh_token": False,
        },
        7,
        int(time.time()),
    )

    assert status == "not_refreshable"


@pytest.mark.asyncio
async def test_missing_access_token_status_is_unknown():
    status = await token_routes._token_status(
        {
            "id": 1,
            "token": "",
            "token_expires_at": 0,
            "has_refresh_token": False,
        },
        7,
        int(time.time()),
    )

    assert status == "unknown"


@pytest.mark.asyncio
async def test_valid_status_is_short_cached_but_unknown_is_not(monkeypatch):
    token_routes._token_status_cache.clear()
    calls = 0
    results = [
        {"status": "valid", "expires_in": 10 * 86400},
        {"status": "unknown"},
        {"status": "unknown"},
    ]

    async def validate(token):
        nonlocal calls
        result = results[calls]
        calls += 1
        return result

    monkeypatch.setattr(token_routes, "validate_oauth_token_status", validate)
    account = {
        "id": 5,
        "token": "oauth:cached",
        "token_expires_at": 0,
        "has_refresh_token": True,
    }

    assert await token_routes._token_status(account, 7, 1) == "valid"
    assert await token_routes._token_status(account, 7, 1) == "valid"
    assert calls == 1

    account["token"] = "oauth:changed"
    assert await token_routes._token_status(account, 7, 1) == "unknown"
    assert await token_routes._token_status(account, 7, 1) == "unknown"
    assert calls == 3


@pytest.mark.asyncio
async def test_account_status_endpoint_returns_only_statuses(monkeypatch):
    await database.init_db()
    now = int(time.time())
    db = await database.get_db()
    try:
        await db.executemany(
            "INSERT INTO accounts (nickname, token, refresh_token, token_expires_at) "
            "VALUES (?, ?, ?, ?)",
            [
                ("manual", "manual-access", "", 0),
                ("known", "known-access", "known-refresh", now + 86400),
                ("provider", "provider-access", "provider-refresh", 0),
            ],
        )
        await db.commit()
        rows = await (await db.execute("SELECT id, nickname FROM accounts")).fetchall()
        ids = {row["nickname"]: str(row["id"]) for row in rows}
    finally:
        await db.close()

    async def validate(token):
        assert token == "provider-access"
        return {"status": "valid", "expires_in": 30 * 86400}

    token_routes._token_status_cache.clear()
    monkeypatch.setattr(token_routes, "validate_oauth_token_status", validate)

    result = await token_routes.account_token_statuses()

    assert result == {
        "statuses": {
            ids["manual"]: "not_refreshable",
            ids["known"]: "expiring",
            ids["provider"]: "valid",
        }
    }
    assert "manual-access" not in repr(result)
    assert "provider-refresh" not in repr(result)




def _disable_token_encryption(monkeypatch) -> None:
    """Полный прогон: ранее тесты включают Fernet (глобальный кэш _FERNET),
    после чего refresh сохраняет enc::… вместо открытого токена."""
    from app import security as security_mod
    monkeypatch.setattr(security_mod, "_FERNET", None)
    monkeypatch.setattr(security_mod, "_FERNET_TRIED", True)


@pytest.mark.asyncio
async def test_manual_refresh_updates_token_and_invalidates_status_cache(monkeypatch):
    _disable_token_encryption(monkeypatch)  # тест ждёт plaintext-токен в БД
    await database.init_db()
    db = await database.get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO accounts (nickname, token, refresh_token, token_expires_at, enabled) "
            "VALUES (?, ?, ?, ?, ?)",
            ("refreshable", "old-access", "old-refresh", 0, 1),
        )
        account_id = cursor.lastrowid
        await db.commit()
    finally:
        await db.close()

    token_routes._token_status_cache[account_id] = (
        time.monotonic() + 600,
        "fingerprint",
        {"status": "valid"},
    )
    monkeypatch.setattr(token_routes, "is_helix_configured", lambda: True)

    async def refresh(refresh_token):
        assert refresh_token == "old-refresh"
        return {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        }

    async def log_action(*args, **kwargs):
        return None

    monkeypatch.setattr(token_routes, "refresh_oauth_token", refresh)
    monkeypatch.setattr(token_routes, "log_action", log_action)

    result = await token_routes.manual_refresh_token(account_id)

    assert result == {"ok": True, "expires_in": 3600}
    assert account_id not in token_routes._token_status_cache
    db = await database.get_db()
    try:
        row = await (
            await db.execute(
                "SELECT token, refresh_token, enabled FROM accounts WHERE id = ?",
                (account_id,),
            )
        ).fetchone()
    finally:
        await db.close()
    assert row["token"] == "new-access"
    assert row["refresh_token"] == "new-refresh"
    assert row["enabled"] == 1


@pytest.mark.asyncio
async def test_manual_refresh_does_not_erase_token_on_incomplete_provider_response(monkeypatch):
    await database.init_db()
    db = await database.get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO accounts (nickname, token, refresh_token, enabled) VALUES (?, ?, ?, ?)",
            ("refreshable", "old-access", "old-refresh", 1),
        )
        account_id = cursor.lastrowid
        await db.commit()
    finally:
        await db.close()

    monkeypatch.setattr(token_routes, "is_helix_configured", lambda: True)

    async def refresh(refresh_token):
        return {"refresh_token": "rotated", "expires_in": 3600}

    monkeypatch.setattr(token_routes, "refresh_oauth_token", refresh)

    result = await token_routes.manual_refresh_token(account_id)

    assert result["ok"] is False
    db = await database.get_db()
    try:
        row = await (
            await db.execute(
                "SELECT token, refresh_token, enabled FROM accounts WHERE id = ?",
                (account_id,),
            )
        ).fetchone()
    finally:
        await db.close()
    assert dict(row) == {
        "token": "old-access",
        "refresh_token": "old-refresh",
        "enabled": 1,
    }


@pytest.mark.asyncio
async def test_refresh_loop_rechecks_helix_instead_of_exiting(monkeypatch):
    from app import server

    sleeps = []

    async def get_setting(key, default):
        assert (key, default) == ("auto_refresh_tokens", "1")
        return "1"

    async def sleep(delay):
        sleeps.append(delay)
        if len(sleeps) == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(server, "get_setting", get_setting)
    monkeypatch.setattr(server, "is_helix_configured", lambda: False)
    monkeypatch.setattr(server.asyncio, "sleep", sleep)

    await server.token_refresh_loop()

    assert sleeps == [60, 60]


@pytest.mark.asyncio
async def test_refresh_loop_updates_only_tokens_near_expiry(monkeypatch):
    _disable_token_encryption(monkeypatch)  # тест ждёт plaintext-токен в БД
    from app import server

    await database.init_db()
    now = int(time.time())
    db = await database.get_db()
    try:
        await db.executemany(
            "INSERT INTO accounts (nickname, token, refresh_token, token_expires_at, enabled) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                ("due", "due-access", "due-refresh", now + 300, 1),
                ("later", "later-access", "later-refresh", now + 7200, 1),
            ],
        )
        await db.commit()
    finally:
        await db.close()

    calls = []

    async def refresh(refresh_token):
        calls.append(refresh_token)
        return {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        }

    async def sleep(delay):
        assert delay == 600
        raise asyncio.CancelledError

    async def get_setting(key, default):
        return "1"

    async def ai_log(*args, **kwargs):
        return None

    monkeypatch.setattr(server, "get_setting", get_setting)
    monkeypatch.setattr(server, "is_helix_configured", lambda: True)
    monkeypatch.setattr(server, "refresh_oauth_token", refresh)
    monkeypatch.setattr(server, "ai_log", ai_log)
    monkeypatch.setattr(server.asyncio, "sleep", sleep)

    await server.token_refresh_loop()

    assert calls == ["due-refresh"]
    db = await database.get_db()
    try:
        rows = await (
            await db.execute(
                "SELECT nickname, token, refresh_token, enabled FROM accounts ORDER BY nickname"
            )
        ).fetchall()
    finally:
        await db.close()
    accounts = {row["nickname"]: dict(row) for row in rows}
    assert accounts["due"]["token"] == "new-access"
    assert accounts["due"]["refresh_token"] == "new-refresh"
    assert accounts["due"]["enabled"] == 1
    assert accounts["later"]["token"] == "later-access"


@pytest.mark.asyncio
async def test_failed_refresh_retries_without_disabling_bot(monkeypatch):
    from app import server

    await database.init_db()
    db = await database.get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO accounts (nickname, token, refresh_token, token_expires_at, enabled) "
            "VALUES (?, ?, ?, ?, ?)",
            ("still-running", "old-access", "old-refresh", 1, 1),
        )
        account_id = cursor.lastrowid
        await db.commit()
    finally:
        await db.close()

    attempts = 0
    cycle_sleeps = 0

    async def refresh(refresh_token):
        nonlocal attempts
        attempts += 1
        assert refresh_token == "old-refresh"
        return None

    async def sleep(delay):
        nonlocal cycle_sleeps
        assert delay == 600
        cycle_sleeps += 1
        if cycle_sleeps == 2:
            raise asyncio.CancelledError

    async def get_setting(key, default):
        return "1"

    monkeypatch.setattr(server, "get_setting", get_setting)
    monkeypatch.setattr(server, "is_helix_configured", lambda: True)
    monkeypatch.setattr(server, "refresh_oauth_token", refresh)
    monkeypatch.setattr(server.asyncio, "sleep", sleep)

    await server.token_refresh_loop()

    assert attempts == 2
    db = await database.get_db()
    try:
        row = await (
            await db.execute(
                "SELECT token, enabled FROM accounts WHERE id = ?", (account_id,)
            )
        ).fetchone()
    finally:
        await db.close()
    assert row["token"] == "old-access"
    assert row["enabled"] == 1
