"""MOD-05 gate: login transactions, cookie sessions, token never reaches JS."""
from __future__ import annotations

import pytest
import pytest_asyncio

from app import moderator_site_identity as ident

FINGERPRINT = "fp-browser-1"
OTHER_FINGERPRINT = "fp-browser-2"


@pytest_asyncio.fixture
async def db(tmp_path):
    import aiosqlite
    conn = await aiosqlite.connect(tmp_path / "identity.db")
    await conn.execute("PRAGMA foreign_keys=ON")
    await ident.ensure_schema(conn)
    yield conn
    await conn.close()


@pytest.mark.asyncio
async def test_login_attempt_rate_limit(db):
    for _ in range(ident.MAX_ACTIVE_ATTEMPTS_PER_USER):
        await ident.create_login_attempt(db, "u1", "mod1", FINGERPRINT)
    with pytest.raises(ValueError, match="login_rate_limited"):
        await ident.create_login_attempt(db, "u1", "mod1", FINGERPRINT)
    # Another user is unaffected.
    await ident.create_login_attempt(db, "u2", "mod2", FINGERPRINT)


@pytest.mark.asyncio
async def test_exchange_single_use_and_binding(db):
    attempt = await ident.create_login_attempt(db, "u1", "mod1", FINGERPRINT)
    session = await ident.exchange_login(db, attempt["nonce"], FINGERPRINT)
    assert session["twitch_login"] == "mod1"
    # duplicate exchange is refused even with the correct browser
    with pytest.raises(ValueError, match="duplicate_exchange"):
        await ident.exchange_login(db, attempt["nonce"], FINGERPRINT)
    # a fresh nonce is browser-bound: wrong browser cannot exchange
    attempt2 = await ident.create_login_attempt(db, "u1", "mod1", FINGERPRINT)
    with pytest.raises(ValueError, match="wrong_browser"):
        await ident.exchange_login(db, attempt2["nonce"], OTHER_FINGERPRINT)
    # same browser still works (binding is to the initiating browser)
    session2 = await ident.exchange_login(db, attempt2["nonce"], FINGERPRINT)
    assert session2["session_id"] != session["session_id"]


@pytest.mark.asyncio
async def test_expired_invite_fails_closed(db):
    attempt = await ident.create_login_attempt(db, "u1", "mod1", FINGERPRINT)
    with pytest.raises(ValueError, match="attempt_expired"):
        await ident.exchange_login(db, attempt["nonce"], FINGERPRINT, now=ident.time.time() + ident.LOGIN_TTL_SEC + 5)


@pytest.mark.asyncio
async def test_cancellation_blocks_exchange(db):
    attempt = await ident.create_login_attempt(db, "u1", "mod1", FINGERPRINT)
    await ident.cancel_login_attempt(db, attempt["attempt_id"], "u1")
    with pytest.raises(ValueError, match="attempt_missing"):
        await ident.exchange_login(db, attempt["nonce"], FINGERPRINT)


@pytest.mark.asyncio
async def test_session_binding_logout_and_expiry(db):
    attempt = await ident.create_login_attempt(db, "u1", "mod1", FINGERPRINT)
    session = await ident.exchange_login(db, attempt["nonce"], FINGERPRINT)
    cookie = session["cookie_token"]
    valid = await ident.validate_session(db, cookie, FINGERPRINT)
    assert valid is not None and valid["grant_version"] == 1
    # wrong browser: session does not validate
    assert await ident.validate_session(db, cookie, OTHER_FINGERPRINT) is None
    assert await ident.logout_session(db, cookie) is True
    assert await ident.validate_session(db, cookie, FINGERPRINT) is None


@pytest.mark.asyncio
async def test_twitch_token_never_in_payloads(db):
    attempt = await ident.create_login_attempt(db, "u1", "mod1", FINGERPRINT)
    session = await ident.exchange_login(db, attempt["nonce"], FINGERPRINT, twitch_token="oauth:secret123")
    payload = repr(session)
    assert "secret123" not in payload  # access token stays server-side only
    import json
    row = await (await db.execute("SELECT twitch_access_token FROM ms_login_attempts WHERE id=?", (attempt["attempt_id"],))).fetchone()
    assert row[0] == "oauth:secret123"  # stored for the adapter, never returned
