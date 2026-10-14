"""Тесты Device Code Flow (twitch_oauth.py)."""
from __future__ import annotations

import time

import httpx
import pytest


def _mock_transport(handler):
    return httpx.MockTransport(handler)


def test_is_configured_no_env(monkeypatch):
    monkeypatch.delenv("TWITCH_CLIENT_ID", raising=False)
    from app import twitch_oauth
    assert twitch_oauth.is_configured() is False


def test_is_configured_with_env(monkeypatch):
    monkeypatch.setenv("TWITCH_CLIENT_ID", "fakeclient123")
    from app import twitch_oauth
    assert twitch_oauth.is_configured() is True


@pytest.mark.asyncio
async def test_start_device_flow_no_client_id(monkeypatch):
    monkeypatch.delenv("TWITCH_CLIENT_ID", raising=False)
    from app import twitch_oauth
    r = await twitch_oauth.start_device_flow()
    assert r["ok"] is False
    assert "TWITCH_CLIENT_ID" in r["error"]


@pytest.mark.asyncio
async def test_start_device_flow_success(monkeypatch):
    monkeypatch.setenv("TWITCH_CLIENT_ID", "fakeclient123")
    from app import twitch_oauth

    def handler(request: httpx.Request) -> httpx.Response:
        assert "device" in str(request.url)
        return httpx.Response(200, json={
            "device_code": "DEV_ABC",
            "user_code": "ABCDEF",
            "verification_uri": "https://www.twitch.tv/activate",
            "expires_in": 1800,
            "interval": 5,
        })

    transport = httpx.MockTransport(handler)
    orig = httpx.AsyncClient

    class _Patched:
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            self._c = orig(*a, **kw)
        async def __aenter__(self):
            return await self._c.__aenter__()
        async def __aexit__(self, *a):
            return await self._c.__aexit__(*a)

    monkeypatch.setattr(twitch_oauth.httpx, "AsyncClient", _Patched)
    r = await twitch_oauth.start_device_flow()
    assert r["ok"] is True
    assert r["device_code"] == "DEV_ABC"
    assert r["user_code"] == "ABCDEF"


@pytest.mark.asyncio
async def test_poll_device_token_pending(monkeypatch):
    monkeypatch.setenv("TWITCH_CLIENT_ID", "fakeclient123")
    from app import twitch_oauth

    def handler(request):
        return httpx.Response(400, json={"message": "authorization_pending"})

    transport = httpx.MockTransport(handler)
    orig = httpx.AsyncClient

    class _P:
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            self._c = orig(*a, **kw)
        async def __aenter__(self):
            return await self._c.__aenter__()
        async def __aexit__(self, *a):
            return await self._c.__aexit__(*a)

    monkeypatch.setattr(twitch_oauth.httpx, "AsyncClient", _P)
    r = await twitch_oauth.poll_device_token("DEV_ABC")
    assert r["ok"] is False
    assert r.get("pending") is True


@pytest.mark.asyncio
async def test_poll_device_token_success(monkeypatch):
    monkeypatch.setenv("TWITCH_CLIENT_ID", "fakeclient123")
    from app import twitch_oauth

    def handler(request):
        return httpx.Response(200, json={
            "access_token": "tok_xyz",
            "refresh_token": "rtok_abc",
            "expires_in": 14400,
            "scope": ["chat:read", "chat:edit"],
            "token_type": "bearer",
        })

    transport = httpx.MockTransport(handler)
    orig = httpx.AsyncClient

    class _P:
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            self._c = orig(*a, **kw)
        async def __aenter__(self):
            return await self._c.__aenter__()
        async def __aexit__(self, *a):
            return await self._c.__aexit__(*a)

    monkeypatch.setattr(twitch_oauth.httpx, "AsyncClient", _P)
    r = await twitch_oauth.poll_device_token("DEV_ABC")
    assert r["ok"] is True
    assert r["access_token"] == "tok_xyz"
    assert r["refresh_token"] == "rtok_abc"


@pytest.mark.asyncio
async def test_poll_device_token_expired(monkeypatch):
    monkeypatch.setenv("TWITCH_CLIENT_ID", "fakeclient123")
    from app import twitch_oauth

    def handler(request):
        return httpx.Response(400, json={"message": "expired_token"})

    transport = httpx.MockTransport(handler)
    orig = httpx.AsyncClient

    class _P:
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            self._c = orig(*a, **kw)
        async def __aenter__(self):
            return await self._c.__aenter__()
        async def __aexit__(self, *a):
            return await self._c.__aexit__(*a)

    monkeypatch.setattr(twitch_oauth.httpx, "AsyncClient", _P)
    r = await twitch_oauth.poll_device_token("DEV_OLD")
    assert r.get("expired") is True


def test_session_management():
    """In-memory сессии: запомнить, проверить, забыть, gc."""
    from app import twitch_oauth
    twitch_oauth._pending.clear()
    twitch_oauth.remember_session("dev_x", "USER1", 1800)
    assert twitch_oauth.is_known_session("dev_x") is True
    twitch_oauth.forget_session("dev_x")
    assert twitch_oauth.is_known_session("dev_x") is False

    # GC expired
    twitch_oauth.remember_session("dev_y", "USER2", 1800)
    twitch_oauth._pending["dev_y"]["expires_at"] = time.time() - 1
    twitch_oauth.gc_expired_sessions()
    assert twitch_oauth.is_known_session("dev_y") is False


@pytest.mark.asyncio
async def test_route_rejects_unknown_device_code_without_provider_call(monkeypatch):
    from app import twitch_oauth
    from app.routes_device_code import twitch_oauth_poll

    twitch_oauth._pending.clear()
    provider_called = False

    async def poll_provider(device_code):
        nonlocal provider_called
        provider_called = True
        return {"ok": False, "pending": True}

    monkeypatch.setattr(twitch_oauth, "poll_device_token", poll_provider)

    result = await twitch_oauth_poll({"device_code": "untrusted-code"})

    assert result == {"ok": False, "error": "unknown_device_session"}
    assert provider_called is False


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["expired", "denied"])
async def test_route_forgets_terminal_device_session(monkeypatch, terminal):
    from app import twitch_oauth
    from app.routes_device_code import twitch_oauth_poll

    twitch_oauth._pending.clear()
    twitch_oauth.remember_session("known-code", "ABCD", 600)

    async def poll_provider(device_code):
        assert device_code == "known-code"
        return {"ok": False, terminal: True}

    monkeypatch.setattr(twitch_oauth, "poll_device_token", poll_provider)

    result = await twitch_oauth_poll({"device_code": "known-code"})

    assert result[terminal] is True
    assert not twitch_oauth.is_known_session("known-code")


@pytest.mark.asyncio
@pytest.mark.parametrize("transient", ["pending", "slow_down"])
async def test_route_retains_session_for_transient_poll_state(monkeypatch, transient):
    from app import twitch_oauth
    from app.routes_device_code import twitch_oauth_poll

    twitch_oauth._pending.clear()
    twitch_oauth.remember_session("known-code", "ABCD", 600)

    async def poll_provider(device_code):
        return {"ok": False, transient: True}

    monkeypatch.setattr(twitch_oauth, "poll_device_token", poll_provider)

    result = await twitch_oauth_poll({"device_code": "known-code"})

    assert result[transient] is True
    assert twitch_oauth.is_known_session("known-code")
    twitch_oauth.forget_session("known-code")


@pytest.mark.asyncio
async def test_route_consumes_session_when_token_exchange_succeeds(monkeypatch):
    from app import twitch_oauth
    from app.routes_device_code import twitch_oauth_poll

    twitch_oauth._pending.clear()
    twitch_oauth.remember_session("known-code", "ABCD", 600)

    async def poll_provider(device_code):
        return {"ok": True, "access_token": "fake-access", "expires_in": 60}

    async def fail_validation(access_token):
        assert access_token == "fake-access"
        assert not twitch_oauth.is_known_session("known-code")
        return {"ok": False, "error": "fake validation failure"}

    monkeypatch.setattr(twitch_oauth, "poll_device_token", poll_provider)
    monkeypatch.setattr(twitch_oauth, "fetch_user_info", fail_validation)

    result = await twitch_oauth_poll({"device_code": "known-code"})

    assert result["ok"] is False
    assert "валидация" in result["error"]
    assert not twitch_oauth.is_known_session("known-code")
