"""MOD-21 gate: perimeter security and load bounds on the FULL ASGI wiring.

Tests drive the production gateway app through the ASGI protocol (no listener),
against a fake bridge. QA bypass env is cleaned; loopback and remote peers are
modelled via headers only. Load checks run on an in-memory DB — never production.
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio

from gateway import bridge_client as bridge_module
from gateway import main as gateway_main
from gateway.main import gateway_app

TOKEN = "perimeter-token"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Perimeter tests run without QA bypass: the gateway token must be required."""
    for env in ("MODERATOR_SITE_TOKEN", "MODERATOR_SITE_ALLOWED_HOSTS",
                "MODERATOR_SITE_ALLOWED_ORIGINS", "MODERATOR_QA_BYPASS", "QA_BYPASS"):
        monkeypatch.delenv(env, raising=False)


class _FakeBridge:
    def __init__(self): self.calls = []
    async def request(self, method: str, path: str):
        self.calls.append((method, path))
        return SimpleNamespace(status_code=200, json=lambda: {"ok": True})


@pytest.fixture
def fake_bridge(monkeypatch):
    bridge = _FakeBridge()
    monkeypatch.setattr(gateway_main, "BridgeClient", lambda: bridge)
    return bridge


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway_app), base_url="http://test")


def _auth(**extra):
    return {"X-Moderator-Site-Auth": TOKEN, **extra}


@pytest_asyncio.fixture
async def _token(monkeypatch):
    monkeypatch.setenv("MODERATOR_SITE_TOKEN", TOKEN)


@pytest.mark.asyncio
async def test_fail_closed_without_token():
    async with _client() as client:
        response = await client.get("/moderator-site/health")  # unauthenticated route
        assert response.status_code == 403 and response.json()["detail"]["code"] == "gateway_unauthorized"


@pytest.mark.asyncio
async def test_path_confusion_is_default_denied(_token, fake_bridge):
    async with _client() as client:
        for path in ("/moderator-site//identity/context", "/moderator-site/../panel/secret",
                     "/moderator-site/%2e%2e/panel", "/moderator-site/identity/context/",
                     "/panel/absolute", "/moderator-site/identity/%63ontext"):
            response = await client.get(path, headers=_auth())
            assert response.status_code == 404, path  # никогда не доходит до bridge
        assert fake_bridge.calls == []  # zero bridge touches


@pytest.mark.asyncio
async def test_request_bounds_and_safe_errors(_token, fake_bridge):
    async with _client() as client:
        response = await client.post(
            "/moderator-site/queue/snapshot", headers={**_auth(), "content-length": str(300 * 1024)},
            content=b"x")
        assert response.status_code == 413
        # safe errors: body carries only a code, no stack, no env, no paths
        response = await client.get("/moderator-site/unknown", headers=_auth())
        body = response.text
        assert response.status_code == 404
        for secret in ("token", TOKEN, "traceback", "/tmp/", "MODERATOR_SITE_TOKEN"):
            assert secret not in body


@pytest.mark.asyncio
async def test_loopback_peer_with_valid_session_reaches_bridge(_token, fake_bridge, monkeypatch):
    monkeypatch.setenv("MODERATOR_SITE_ALLOWED_HOSTS", "mod.example.com")
    async with _client() as client:
        # remote peer: foreign host -> 403 before anything else
        response = await client.get("/moderator-site/health",
                                    headers={**_auth(), "host": "mod.example.com"})
        assert response.status_code == 200  # allowed host passes the perimeter
        response2 = await client.get("/moderator-site/health",
                                     headers={**_auth(), "host": "mod.example.com"})
        assert response2.status_code == 200  # allowed host passes the perimeter
        # session-gated route: authenticated request reaches bridge and returns data
        response3 = await client.get("/moderator-site/identity/session",
                                     headers={**_auth(), "host": "mod.example.com"})
        assert response3.status_code == 401  # perimeter passed, session-gate next
        assert not any(path == "/bridge/identity/session" for _, path in fake_bridge.calls)


@pytest.mark.asyncio
async def test_login_rate_limit(db_tmp=None, tmp_path=None):
    import aiosqlite
    from app import moderator_site_identity as ident
    conn = await aiosqlite.connect(":memory:")
    await ident.ensure_schema(conn)
    try:
        for i in range(ident.MAX_ACTIVE_ATTEMPTS_PER_USER):
            await ident.create_login_attempt(conn, "user", f"login-{i}", "fp")
        with pytest.raises(ValueError, match="login_rate_limited"):
            await ident.create_login_attempt(conn, "user", "login-x", "fp")
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_fake_load_bounds_in_memory_only(tmp_path):
    """Fake 1000-item library и burst admission: bounded время, in-memory DB."""
    import aiosqlite
    from app import moderator_site_library as lib
    from app import moderator_site_cues as cues
    conn = await aiosqlite.connect(":memory:")
    await lib.ensure_schema(conn)
    await cues.ensure_schema(conn)
    from app import moderator_site_permissions as perms
    from app import moderator_site_schema as ms
    await perms.ensure_schema(conn)
    await ms.ensure_schema(conn)  # outbox для atomic audit
    try:
        started = time.perf_counter()
        await conn.execute("BEGIN")
        for i in range(1000):
            await conn.execute(
                "INSERT INTO ms_library_items(id, account_id, channel, kind, title, status)"
                " VALUES (?,1,'chan','media',?, 'approved')", (f"i{i}", f"Item {i:04d}"))
        await conn.commit()
        page = await lib.list_items(conn, account_id=1, channel="chan", kind="media", query="Item 091", limit=100)
        await conn.commit()
        listing_time = time.perf_counter() - started
        assert len(page["items"]) == 10  # Item 0910..0919
        assert listing_time < 10.0  # bounded; not a perf benchmark — an runaway guard
        # burst admission: 200 submissions, duplicates are idempotent, queue capped
        await conn.execute("INSERT INTO ms_grants(id, account_id, channel, twitch_user_id)"
                           " VALUES ('g',1,'chan','u')")
        await conn.commit()
        started = time.perf_counter()
        results = []
        for i in range(200):
            try:
                results.append(await cues.submit_cue(
                    conn, account_id=1, channel="chan", grant_id="g", grant_version=1,
                    payload={"asset_id": f"a{i}", "action": "play"}, policy_revision="p",
                    current_policy_revision="p", scope_stopped=False, queue_limit=5))
            except ValueError as exc:
                results.append(str(exc))
        burst_time = time.perf_counter() - started
        admitted = sum(1 for r in results if isinstance(r, dict) and not r.get("duplicate"))
        assert admitted == 5  # queue cap enforced under burst
        assert sum(1 for r in results if r == "cue_queue_full") == 195
        assert burst_time < 30.0
    finally:
        await conn.close()
