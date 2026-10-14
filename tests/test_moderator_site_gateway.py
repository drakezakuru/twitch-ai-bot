"""MOD-03 gate: gateway and bridge are separate, default-deny, credential-checked."""
from __future__ import annotations

import pytest

from app.moderator_site_bridge import BRIDGE_ENDPOINTS, bridge_app
from gateway.main import gateway_app
from gateway.routes import GATEWAY_ROUTES, resolve, validate_registry


@pytest.fixture
def service_env(monkeypatch):
    monkeypatch.setenv("MODERATOR_BRIDGE_TOKEN", "bridge-secret")
    monkeypatch.setenv("MODERATOR_SITE_TOKEN", "site-secret")
    monkeypatch.setenv("MODERATOR_BRIDGE_BASE_URL", "http://bridge.test")


def _client(app):
    import httpx
    from httpx import ASGITransport
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_bridge_fails_closed_without_token(monkeypatch):
    monkeypatch.delenv("MODERATOR_BRIDGE_TOKEN", raising=False)
    async with _client(bridge_app) as client:
        response = await client.get("/bridge/health")
        assert response.status_code == 403
        any_path = await client.get("/bridge/api/accounts")
        assert any_path.status_code == 403


@pytest.mark.asyncio
async def test_bridge_serves_only_enumerated_endpoints(monkeypatch):
    monkeypatch.setenv("MODERATOR_BRIDGE_TOKEN", "bridge-secret")
    async with _client(bridge_app) as client:
        ok = await client.get("/bridge/health", headers={"X-Moderator-Bridge-Token": "bridge-secret"})
        assert ok.status_code == 200 and ok.json()["ok"] is True
        # no wildcard forwarding: any other path (including owner API prefixes) is 404
        for path in ("/bridge/api/accounts", "/bridge/api/director/status", "/bridge/", "/bridge/health/extra"):
            denied = await client.get(path, headers={"X-Moderator-Bridge-Token": "bridge-secret"})
            assert denied.status_code == 404, path


class _StubBridge:
    """Stands in for the real panel bridge; only proves the gateway hop contract."""

    def __init__(self, *args, **kwargs): pass

    async def request(self, method: str, bridge_path: str):
        assert bridge_path == "/bridge/health"
        import httpx
        return httpx.Response(200, json={"ok": True, "bridge": "moderator-site"})


@pytest.mark.asyncio
async def test_gateway_denies_unknown_browser_and_paths(monkeypatch, service_env):
    monkeypatch.setattr("gateway.main.BridgeClient", _StubBridge)
    async with _client(gateway_app) as client:
        assert (await client.get("/moderator-site/health")).status_code == 403  # no browser credential
        assert (await client.get("/moderator-site/health", headers={"X-Moderator-Site-Auth": "wrong"})).status_code == 403
        ok = await client.get("/moderator-site/health", headers={"X-Moderator-Site-Auth": "site-secret"})
        assert ok.status_code == 200 and ok.json()["bridge"] == "moderator-site"
        # default-deny: mapped path with wrong method and ANY unmapped path
        post = await client.post("/moderator-site/health", headers={"X-Moderator-Site-Auth": "site-secret"})
        assert post.status_code == 404
        for path in ("/api/accounts", "/api/director/status", "/moderator-site/api/accounts", "/"):
            denied = await client.get(path, headers={"X-Moderator-Site-Auth": "site-secret"})
            assert denied.status_code == 404, path


def test_registry_contract():
    assert validate_registry() == []
    assert all(route.gateway_path.startswith("/moderator-site/") for route in GATEWAY_ROUTES)
    assert resolve("/moderator-site/health") is not None
    assert resolve("/moderator-site/api/accounts") is None
    # bridge surface stays explicitly enumerated
    assert ("GET", "/bridge/health") in BRIDGE_ENDPOINTS


@pytest.mark.asyncio
async def test_exchange_sets_httponly_cookie(monkeypatch, service_env):
    class _ExchangeStub:
        def __init__(self, *args, **kwargs): pass

        async def request(self, method: str, bridge_path: str):
            import httpx
            assert bridge_path == "/bridge/identity/exchange"
            return httpx.Response(200, json={"cookie_token": "opaque-cookie", "expires_in": 43200})

    monkeypatch.setattr("gateway.main.BridgeClient", _ExchangeStub)
    async with _client(gateway_app) as client:
        response = await client.post(
            "/moderator-site/identity/exchange",
            headers={"X-Moderator-Site-Auth": "site-secret"},
            json={"nonce": "n", "browser_fingerprint": FINGERPRINT},
        )
    assert response.status_code == 200
    set_cookie = response.headers["set-cookie"]
    assert "ms_session=opaque-cookie" in set_cookie
    assert "HttpOnly" in set_cookie and "SameSite=Strict" in set_cookie
    assert "Path=/moderator-site" in set_cookie
    body = response.json()
    assert body["expires_in"] == 43200
    assert "csrf_token" in body  # server-bound CSRF for later mutations (MOD-06)
    assert "cookie_token" not in body  # consumed into the HttpOnly header

FINGERPRINT = "fp-browser-1"
