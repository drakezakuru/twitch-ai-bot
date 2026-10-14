"""Moderator identity: login transactions and cookie sessions (MOD-05).

Login attempts are single-use, bound to one Twitch user and one browser
fingerprint, expire, can be cancelled and are rate-limited. The Twitch access
token never leaves the server side: it is stored only inside the attempt/session
row and is never included in any response payload.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Any, Callable

MAX_ACTIVE_ATTEMPTS_PER_USER = 3
SESSION_TTL_SEC = 12 * 3600
LOGIN_TTL_SEC = 600


async def ensure_schema(db: Any) -> None:
    await db.executescript("""
    CREATE TABLE IF NOT EXISTS ms_login_attempts (
      id TEXT PRIMARY KEY, twitch_user_id TEXT NOT NULL, twitch_login TEXT NOT NULL,
      nonce_hash TEXT NOT NULL, browser_fingerprint TEXT NOT NULL,
      grant_version INTEGER NOT NULL DEFAULT 1,
      status TEXT NOT NULL DEFAULT 'pending',
      twitch_access_token TEXT,
      created_at REAL NOT NULL, expires_at REAL NOT NULL,
      exchanged_at REAL, session_id TEXT);
    CREATE INDEX IF NOT EXISTS ms_login_attempts_user
      ON ms_login_attempts(twitch_user_id, status);

    CREATE TABLE IF NOT EXISTS ms_sessions (
      id TEXT PRIMARY KEY, twitch_user_id TEXT NOT NULL, twitch_login TEXT NOT NULL DEFAULT '',
      cookie_token_hash TEXT NOT NULL, browser_fingerprint TEXT NOT NULL,
      grant_version INTEGER NOT NULL DEFAULT 1,
      created_at REAL NOT NULL, expires_at REAL NOT NULL,
      revoked_at TEXT);
    CREATE INDEX IF NOT EXISTS ms_sessions_cookie ON ms_sessions(cookie_token_hash);
    """)


async def create_login_attempt(
    db: Any, twitch_user_id: str, twitch_login: str, browser_fingerprint: str,
    *, grant_version: int = 1, now: float | None = None,
) -> dict[str, Any]:
    now = time.time() if now is None else now
    active = await (await db.execute(
        "SELECT count(*) FROM ms_login_attempts WHERE twitch_user_id=? AND status='pending' AND expires_at>?",
        (twitch_user_id, now),
    )).fetchone()
    if active[0] >= MAX_ACTIVE_ATTEMPTS_PER_USER:
        raise ValueError("login_rate_limited")
    attempt_id = secrets.token_hex(16)
    nonce = secrets.token_urlsafe(24)
    nonce_hash = hashlib.sha256(nonce.encode()).hexdigest()
    await db.execute(
        "INSERT INTO ms_login_attempts(id, twitch_user_id, twitch_login, nonce_hash, browser_fingerprint,"
        " grant_version, status, created_at, expires_at) VALUES (?,?,?,?,?,?,'pending',?,?)",
        (attempt_id, twitch_user_id, twitch_login, nonce_hash, browser_fingerprint,
         grant_version, now, now + LOGIN_TTL_SEC),
    )
    await db.commit()
    # The raw nonce exists only here, once: it travels to the owner-approved channel.
    return {"attempt_id": attempt_id, "nonce": nonce, "expires_in": LOGIN_TTL_SEC}


async def cancel_login_attempt(db: Any, attempt_id: str, twitch_user_id: str) -> None:
    cursor = await db.execute(
        "UPDATE ms_login_attempts SET status='cancelled' WHERE id=? AND twitch_user_id=? AND status='pending'",
        (attempt_id, twitch_user_id),
    )
    await db.commit()
    if not cursor.rowcount:
        raise ValueError("attempt_missing")


async def exchange_login(
    db: Any, nonce: str, browser_fingerprint: str, *, now: float | None = None,
    twitch_token: str | None = None,
) -> dict[str, Any]:
    """Single-use exchange: wrong browser/duplicate/expired attempts all fail closed."""
    now = time.time() if now is None else now
    nonce_hash = hashlib.sha256(nonce.encode()).hexdigest()
    await db.execute("BEGIN IMMEDIATE")
    try:
        row = await (await db.execute(
            "SELECT id, twitch_user_id, twitch_login, browser_fingerprint, grant_version, status,"
            " expires_at, twitch_access_token FROM ms_login_attempts WHERE nonce_hash=?",
            (nonce_hash,),
        )).fetchone()
        if row is None:
            raise ValueError("attempt_missing")
        (attempt_id, twitch_user_id, twitch_login, attempt_browser, grant_version, status,
         expires_at, stored_token) = row
        if status == "exchanged":
            raise ValueError("duplicate_exchange")
        if status in {"cancelled", "expired"}:
            raise ValueError("attempt_missing")
        if now > float(expires_at):
            await db.execute("UPDATE ms_login_attempts SET status='expired' WHERE id=?", (attempt_id,))
            raise ValueError("attempt_expired")
        if not hmac.compare_digest(attempt_browser, browser_fingerprint):
            raise ValueError("wrong_browser")
        token = twitch_token or stored_token
        if twitch_token:  # device-flow result lands server-side only
            await db.execute("UPDATE ms_login_attempts SET twitch_access_token=? WHERE id=?", (twitch_token, attempt_id))
        session_id = secrets.token_hex(16)
        cookie_token = secrets.token_urlsafe(32)
        await db.execute(
            "INSERT INTO ms_sessions(id, twitch_user_id, twitch_login, cookie_token_hash, browser_fingerprint,"
            " grant_version, created_at, expires_at) VALUES (?,?,?,?,?,?,?,?)",
            (session_id, twitch_user_id, twitch_login, hashlib.sha256(cookie_token.encode()).hexdigest(),
             browser_fingerprint, grant_version, now, now + SESSION_TTL_SEC),
        )
        await db.execute(
            "UPDATE ms_login_attempts SET status='exchanged', exchanged_at=?, session_id=? WHERE id=?",
            (now, session_id, attempt_id),
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return {
        "session_id": session_id,
        "cookie_token": cookie_token,  # HttpOnly cookie value; never a Twitch token
        "twitch_login": twitch_login,
        "grant_version": grant_version,
        "expires_in": SESSION_TTL_SEC,
    }


async def validate_session(db: Any, cookie_token: str, browser_fingerprint: str, *, now: float | None = None) -> dict[str, Any] | None:
    now = time.time() if now is None else now
    row = await (await db.execute(
        "SELECT id, twitch_login, grant_version, browser_fingerprint, expires_at"
        " FROM ms_sessions WHERE cookie_token_hash=? AND revoked_at IS NULL",
        (hashlib.sha256(cookie_token.encode()).hexdigest(),),
    )).fetchone()
    if row is None or now > float(row[4]):
        return None
    if not hmac.compare_digest(row[3], browser_fingerprint):
        return None  # wrong browser: session is bound to its first browser
    return {"session_id": row[0], "twitch_login": row[1], "grant_version": row[2]}


async def logout_session(db: Any, cookie_token: str) -> bool:
    cursor = await db.execute(
        "UPDATE ms_sessions SET revoked_at=CURRENT_TIMESTAMP WHERE cookie_token_hash=? AND revoked_at IS NULL",
        (hashlib.sha256(cookie_token.encode()).hexdigest(),),
    )
    await db.commit()
    return bool(cursor.rowcount)
