"""Moderator-site permissions (MOD-07): scoped grants, live enabled checks, revocation.

Permissions are independent flags (`send_tts`, `play_media`, `play_sound`,
`upload_media`) bound to one account + channel + Twitch user. Disabling a grant
bumps its grant_version, cancels unused invites and revokes live sessions — an
open page loses access on its next request without ever gaining admin rights.
"""
from __future__ import annotations

import secrets
from typing import Any

PERMISSIONS = frozenset({"send_tts", "play_media", "play_sound", "upload_media"})


async def ensure_schema(db: Any) -> None:
    await db.executescript("""
    CREATE TABLE IF NOT EXISTS ms_grants (
      id TEXT PRIMARY KEY, account_id INTEGER NOT NULL, channel TEXT NOT NULL,
      twitch_user_id TEXT NOT NULL, twitch_login TEXT NOT NULL DEFAULT '',
      grant_version INTEGER NOT NULL DEFAULT 1,
      permissions TEXT NOT NULL DEFAULT '[]',
      enabled INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE UNIQUE INDEX IF NOT EXISTS ms_grants_unique
      ON ms_grants(account_id, channel, twitch_user_id);
    CREATE TABLE IF NOT EXISTS ms_invites (
      id TEXT PRIMARY KEY, grant_id TEXT NOT NULL,
      invite_hash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
      expires_at REAL NOT NULL, created_at REAL NOT NULL);
    """)


def _validate_permissions(permissions: list[str]) -> list[str]:
    unique = sorted(set(permissions or []))
    if not unique or any(p not in PERMISSIONS for p in unique):
        raise ValueError("invalid_permissions")
    return unique


async def save_grant(db: Any, account_id: int, channel: str, twitch_user_id: str,
                     twitch_login: str, permissions: list[str]) -> str:
    perms = _validate_permissions(permissions)
    grant_id = secrets.token_hex(16)
    await db.execute(
        "INSERT INTO ms_grants(id, account_id, channel, twitch_user_id, twitch_login, permissions)"
        " VALUES (?,?,?,?,?,?)"
        " ON CONFLICT(account_id, channel, twitch_user_id) DO UPDATE SET"
        " permissions=excluded.permissions, grant_version=grant_version+1, enabled=1",
        (grant_id, account_id, channel, twitch_user_id, twitch_login, ",".join(perms)),
    )
    await db.commit()
    row = await (await db.execute(
        "SELECT id FROM ms_grants WHERE account_id=? AND channel=? AND twitch_user_id=?",
        (account_id, channel, twitch_user_id),
    )).fetchone()
    return str(row[0])


async def revoke_grant(db: Any, grant_id: str) -> dict[str, Any]:
    """Owner-only disable: version bump revokes sessions; unused invites die for good."""
    row = await (await db.execute(
        "SELECT account_id, channel, twitch_user_id, grant_version FROM ms_grants WHERE id=?",
        (grant_id,),
    )).fetchone()
    if row is None:
        raise ValueError("grant_missing")
    await db.execute(
        "UPDATE ms_grants SET enabled=0, grant_version=grant_version+1 WHERE id=?", (grant_id,))
    await db.execute(
        "UPDATE ms_invites SET status='cancelled' WHERE grant_id=? AND status='pending'", (grant_id,))
    # Sessions lose their live access immediately: validate_session re-reads the grant.
    await db.execute(
        "UPDATE ms_sessions SET revoked_at=CURRENT_TIMESTAMP WHERE twitch_user_id=? AND revoked_at IS NULL",
        (row[2],))
    await db.commit()
    return {"grant_id": grant_id, "enabled": 0, "grant_version": row[3] + 1}


async def list_grants(db: Any, account_id: int, channel: str) -> list[dict[str, Any]]:
    rows = await (await db.execute(
        "SELECT id, twitch_user_id, twitch_login, grant_version, permissions, enabled"
        " FROM ms_grants WHERE account_id=? AND channel=? ORDER BY twitch_login",
        (account_id, channel),
    )).fetchall()
    return [{"id": r[0], "twitch_user_id": r[1], "twitch_login": r[2], "grant_version": r[3],
             "permissions": [p for p in str(r[4]).split(",") if p], "enabled": bool(r[5])} for r in rows]


async def authenticate_session(db: Any, session_row: dict[str, Any],
                               permission: str, *, account_id: int, channel: str) -> dict[str, Any]:
    """Live scope check: grant must exist, be enabled, and hold the permission.

    Runs on EVERY authenticated request (permissions are re-read, never cached in
    the cookie). `account_id`/`channel` come from the runtime context the moderator
    works in — a grant for another account/channel does not authorise here.
    """
    if permission not in PERMISSIONS:
        raise ValueError("invalid_permission")
    row = await (await db.execute(
        "SELECT enabled, grant_version, permissions FROM ms_grants"
        " WHERE account_id=? AND channel=? AND twitch_user_id=?",
        (account_id, channel, session_row["twitch_user_id"]),
    )).fetchone()
    if row is None:
        raise ValueError("grant_missing")
    enabled, grant_version, permissions = row
    if not enabled:
        raise ValueError("grant_disabled")
    if int(session_row.get("grant_version", 0)) != int(grant_version):
        # The cookie predates the latest grant change (e.g. revoke-then-recreate).
        raise ValueError("grant_version_stale")
    if permission not in [p for p in str(permissions).split(",") if p]:
        raise ValueError("permission_denied")
    return {"grant_version": int(grant_version), "permissions": [p for p in str(permissions).split(",") if p]}
