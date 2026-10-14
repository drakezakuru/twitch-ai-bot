"""MOD-06 gate: origin/CSRF/host/proxy/size bounds — spoofed inputs fail closed."""
from __future__ import annotations

import pytest

from gateway import security
from gateway.main import gateway_app

FINGERPRINT = "fp-browser-1"


@pytest.fixture(autouse=True)
def strict_deployment(monkeypatch):
    monkeypatch.setenv("MODERATOR_SITE_TOKEN", "site-secret")
    monkeypatch.setenv("MODERATOR_BRIDGE_TOKEN", "bridge-secret")
    monkeypatch.setenv("MODERATOR_SITE_ALLOWED_HOSTS", "mod.example.com")
    monkeypatch.setenv("MODERATOR_SITE_ALLOWED_ORIGINS", "https://mod.example.com")
    monkeypatch.setattr("gateway.main.BridgeClient", _AnyBridge)
    yield


class _AnyBridge:
    def __init__(self, *args, **kwargs): pass

    async def request(self, method: str, bridge_path: str):
        import httpx
        return httpx.Response(200, json={"ok": True})


def _client():
    import httpx
    from httpx import ASGITransport
    return httpx.AsyncClient(transport=ASGITransport(app=gateway_app), base_url="https://mod.example.com")


def _auth(**extra):
    headers = {"X-Moderator-Site-Auth": "site-secret"}
    headers.update(extra)
    return headers


@pytest.mark.asyncio
async def test_host_allowlist_exact():
    async with _client() as client:
        ok = await client.get("/moderator-site/health", headers=_auth(Host="mod.example.com"))
        assert ok.status_code == 200
        spoofed = await client.get("/moderator-site/health", headers=_auth(Host="evil.example.com"))
        assert spoofed.status_code == 403
        encoded = await client.get("/moderator-site/health", headers=_auth(Host="mod.example.com%2F.evil"))
        assert encoded.status_code == 403


@pytest.mark.asyncio
async def test_origin_validation_exact_and_null():
    async with _client() as client:
        ok = await client.post(
            "/moderator-site/identity/login-attempt",
            headers=_auth(Origin="https://mod.example.com"), json={})
        assert ok.status_code in {200, 400}  # origin accepted; payload errors are fine
        for bad_origin in ("https://evil.example.com", "null"):
            denied = await client.post(
                "/moderator-site/identity/login-attempt", headers=_auth(Origin=bad_origin), json={})
            assert denied.status_code == 403, bad_origin
        missing = await client.post("/moderator-site/identity/login-attempt", headers=_auth(), json={})
        assert missing.status_code == 403


@pytest.mark.asyncio
async def test_csrf_missing_or_wrong_header_fails(monkeypatch):
    class _ExchangeStub:
        def __init__(self, *args, **kwargs): pass

        async def request(self, method: str, bridge_path: str):
            import httpx
            return httpx.Response(200, json={"cookie_token": "opaque", "expires_in": 43200})

    monkeypatch.setattr("gateway.main.BridgeClient", _ExchangeStub)
    async with _client() as client:
        exchange = await client.post(
            "/moderator-site/identity/exchange",
            headers={**_auth(), "Origin": "https://mod.example.com"},
            cookies={}, json={"nonce": "n", "browser_fingerprint": FINGERPRINT})
        assert exchange.status_code == 200
        csrf = exchange.json()["csrf_token"]
        origin = {"Origin": "https://mod.example.com"}
        session_cookie = {"ms_session": "opaque", "ms_csrf": csrf}
        # Missing CSRF header on a session mutation: 403.
        missing = await client.post("/moderator-site/identity/logout", headers={**_auth(), **origin}, cookies=session_cookie)
        assert missing.status_code == 403
        # Wrong value: 403.
        wrong = await client.post(
            "/moderator-site/identity/logout",
            headers={**_auth(), **origin, security.CSRF_HEADER: "spoofed"}, cookies=session_cookie)
        assert wrong.status_code == 403
        # Correct server-bound value passes to the bridge.
        good = await client.post(
            "/moderator-site/identity/logout",
            headers={**_auth(), **origin, security.CSRF_HEADER: csrf}, cookies=session_cookie)

        assert good.status_code == 200


@pytest.mark.asyncio
async def test_request_size_bound():
    async with _client() as client:
        huge = await client.post(
            "/moderator-site/identity/login-attempt", headers={**_auth(), "content-length": str(10 * 1024 * 1024)})
        assert huge.status_code == 413


@pytest.mark.asyncio
async def test_encoded_paths_and_wrong_methods_fail_closed():
    async with _client() as client:
        for path in (
            "/moderator-site/%2e%2e/api/accounts",
            "/moderator-site/..%2Fapi%2Faccounts",
            "/moderator-site/health/",
        ):
            denied = await client.get(path, headers=_auth())
            assert denied.status_code == 404, path
        wrong_method = await client.delete("/moderator-site/health", headers=_auth())
        assert wrong_method.status_code == 404


def test_client_ip_ignores_spoofed_xff_without_trusted_proxies():
    # No trusted proxies configured: the forwarded header is attacker-controlled.
    assert security.client_ip_from("1.2.3.4", [], peer="127.0.0.1") == "127.0.0.1"
    # With a trusted proxy chain: the first untrusted hop wins.
    assert security.client_ip_from("9.9.9.9, 10.0.0.2", ["10.0.0.2"], peer="10.0.0.2") == "9.9.9.9"
    # Peer itself is not trusted: forwarded header ignored.
    assert security.client_ip_from("9.9.9.9", ["10.0.0.2"], peer="6.6.6.6") == "6.6.6.6"
