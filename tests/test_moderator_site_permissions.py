"""MOD-07 gate: permission scopes, live enabled checks, revocation, account/channel/user matrix."""
from __future__ import annotations

import pytest
import pytest_asyncio

from app import moderator_site_identity as ident
from app import moderator_site_permissions as perms


@pytest_asyncio.fixture
async def db(tmp_path):
    import aiosqlite
    conn = await aiosqlite.connect(tmp_path / "perm.db")
    await perms.ensure_schema(conn)
    await ident.ensure_schema(conn)
    yield conn
    await conn.close()


async def _session_for(db, twitch_user_id: str, fingerprint: str = "fp") -> dict:
    attempt = await ident.create_login_attempt(db, twitch_user_id, f"login-{twitch_user_id}", fingerprint)
    session = await ident.exchange_login(db, attempt["nonce"], fingerprint)
    # validate_session returns the server-side row fields used by authenticate_session.
    validated = await ident.validate_session(db, session["cookie_token"], fingerprint)
    assert validated is not None
    return {**validated, "twitch_user_id": twitch_user_id}


@pytest.mark.asyncio
async def test_matrix_two_accounts_two_channels_two_users(db):
    await perms.save_grant(db, 1, "chan_a", "userA", "modA", ["play_media"])
    await perms.save_grant(db, 2, "chan_b", "userB", "modB", ["upload_media"])
    session_a = await _session_for(db, "userA")
    # A's grant works only in its own account+channel scope.
    ok = await perms.authenticate_session(db, session_a, "play_media", account_id=1, channel="chan_a")
    assert ok["permissions"] == ["play_media"]
    with pytest.raises(ValueError, match="grant_missing"):
        await perms.authenticate_session(db, session_a, "play_media", account_id=2, channel="chan_b")
    with pytest.raises(ValueError, match="grant_missing"):
        await perms.authenticate_session(db, session_a, "play_media", account_id=1, channel="chan_b")
    # B (upload-only actor) has no play permissions at all.
    session_b = await _session_for(db, "userB")
    with pytest.raises(ValueError, match="permission_denied"):
        await perms.authenticate_session(db, session_b, "play_media", account_id=2, channel="chan_b")
    granted = await perms.authenticate_session(db, session_b, "upload_media", account_id=2, channel="chan_b")
    assert "upload_media" in granted["permissions"]


@pytest.mark.asyncio
async def test_revoke_during_open_page_kills_access(db):
    await perms.save_grant(db, 1, "chan", "userX", "modX", ["play_sound"])
    session = await _session_for(db, "userX")
    ok = await perms.authenticate_session(db, session, "play_sound", account_id=1, channel="chan")
    assert ok["permissions"] == ["play_sound"]
    grants = await perms.list_grants(db, 1, "chan")
    await perms.revoke_grant(db, grants[0]["id"])  # owner revokes while the page is open
    with pytest.raises(ValueError, match="grant_disabled"):
        await perms.authenticate_session(db, session, "play_sound", account_id=1, channel="chan")


@pytest.mark.asyncio
async def test_regrant_bumps_version_and_stale_cookie_stale_check(db):
    await perms.save_grant(db, 1, "chan", "userX", "modX", ["play_sound"])
    session = await _session_for(db, "userX")  # cookie carries grant_version=1
    await perms.save_grant(db, 1, "chan", "userX", "modX", ["play_media"])  # owner changes the scope
    with pytest.raises(ValueError, match="grant_version_stale"):
        await perms.authenticate_session(db, session, "play_media", account_id=1, channel="chan")


@pytest.mark.asyncio
async def test_invalid_permission_rejected(db):
    await perms.save_grant(db, 1, "chan", "userX", "modX", ["play_sound"])
    session = await _session_for(db, "userX")
    with pytest.raises(ValueError, match="invalid_permission"):
        await perms.authenticate_session(db, session, "become_admin", account_id=1, channel="chan")
