"""Scoped moderator grants and short-lived Twitch-verified console sessions."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.database import get_db
from app.security import auth_dependency
from app.tts_voice_policy import normalize_channel

PERMISSIONS = {"send_tts", "play_media", "play_sound", "upload_media"}
SESSION_MINUTES = 55  # forces Twitch re-validation within the documented hourly interval
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,99}$")
_CHAT_COMMAND_RE = re.compile(r"^![a-z0-9_-]{2,30}$")

async def _owner_auth_dependency(request: Request) -> None:
    await auth_dependency(request)


admin_router = APIRouter(
    prefix="/api/moderator-console/admin",
    tags=["moderator-console-admin"],
    dependencies=[Depends(_owner_auth_dependency)],
)
public_router = APIRouter(prefix="/api/moderator-console", tags=["moderator-console"])
page_router = APIRouter(tags=["moderator-console"])
templates = Jinja2Templates(directory="templates")
_device_logins: dict[str, dict[str, Any]] = {}


def _device_now() -> float:
    return time.monotonic()


def _gc_device_logins() -> None:
    from app import twitch_oauth

    now = _device_now()
    for code, pending in list(_device_logins.items()):
        if float(pending["expires_at"]) <= now:
            _device_logins.pop(code, None)
            twitch_oauth.forget_session(code)
    twitch_oauth.gc_expired_sessions()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def ensure_schema(db=None) -> None:
    own = db is None
    db = db or await get_db()
    try:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS moderator_console_grants (
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                twitch_user_id TEXT NOT NULL,
                twitch_login TEXT NOT NULL DEFAULT '',
                permissions_json TEXT NOT NULL DEFAULT '[]',
                enabled INTEGER NOT NULL DEFAULT 1,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
                UNIQUE(account_id, channel, twitch_user_id)
            );
            CREATE TABLE IF NOT EXISTS moderator_console_invites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                twitch_user_id TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL,
                used_at TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS moderator_console_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                twitch_user_id TEXT NOT NULL,
                twitch_login TEXT NOT NULL DEFAULT '',
                token_hash TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS moderator_console_tts_commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                twitch_user_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                text TEXT NOT NULL,
                voice_alias TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                reason TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
                UNIQUE(account_id, channel, twitch_user_id, idempotency_key)
            );
            CREATE TABLE IF NOT EXISTS moderator_console_chat_tts_config (
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                command_alias TEXT NOT NULL DEFAULT '!tts',
                enabled INTEGER NOT NULL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
                UNIQUE(account_id, channel)
            );
        """)
        await db.commit()
    finally:
        if own:
            await db.close()


async def _audit(action: str, detail: str) -> None:
    from app.routes import log_action
    await log_action(action, detail)


def _permissions(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({str(item) for item in value if str(item) in PERMISSIONS})


def _load_permissions(value: str) -> list[str]:
    try:
        return _permissions(json.loads(value or "[]"))
    except (TypeError, ValueError):
        return []


async def save_grant(account_id: int, channel: str, data: dict[str, Any]) -> dict[str, Any]:
    channel = normalize_channel(channel)
    user_id = str(data.get("twitch_user_id") or "").strip()
    login = str(data.get("twitch_login") or "").strip().lower()[:100]
    raw_permissions = data.get("permissions")
    permissions = _permissions(raw_permissions)
    enabled = data.get("enabled", True) is True
    if not channel or not user_id.isdigit() or len(user_id) > 32:
        return {"ok": False, "error": "invalid_grant"}
    if not isinstance(raw_permissions, list) or any(str(item) not in PERMISSIONS for item in raw_permissions):
        return {"ok": False, "error": "invalid_permissions"}
    db = await get_db()
    try:
        await ensure_schema(db)
        scope = await (await db.execute(
            "SELECT 1 FROM channels WHERE account_id = ? AND lower(ltrim(channel_name, '#')) = ? AND enabled = 1",
            (account_id, channel),
        )).fetchone()
        if not scope:
            return {"ok": False, "error": "scope_not_found"}
        await db.execute(
            "INSERT INTO moderator_console_grants "
            "(account_id, channel, twitch_user_id, twitch_login, permissions_json, enabled) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(account_id, channel, twitch_user_id) DO UPDATE SET "
            "twitch_login=excluded.twitch_login, permissions_json=excluded.permissions_json, "
            "enabled=excluded.enabled, updated_at=CURRENT_TIMESTAMP",
            (account_id, channel, user_id, login, json.dumps(permissions), int(enabled)),
        )
        if not enabled:
            await db.execute(
                "UPDATE moderator_console_sessions SET revoked = 1 "
                "WHERE account_id = ? AND channel = ? AND twitch_user_id = ?",
                (account_id, channel, user_id),
            )
        await db.commit()
    finally:
        await db.close()
    await _audit("moderator_console_grant", f"account={account_id} channel={channel} user_id={user_id} enabled={int(enabled)} permissions={','.join(permissions)}")
    return {"ok": True, "account_id": account_id, "channel": channel,
            "twitch_user_id": user_id, "permissions": permissions, "enabled": enabled}


async def list_grants(account_id: int, channel: str) -> dict[str, Any]:
    channel = normalize_channel(channel)
    db = await get_db()
    try:
        rows = await (await db.execute(
            "SELECT g.twitch_user_id, g.twitch_login, g.permissions_json, g.enabled, g.updated_at, "
            "COUNT(s.id) AS active_sessions FROM moderator_console_grants g "
            "LEFT JOIN moderator_console_sessions s ON s.account_id=g.account_id AND s.channel=g.channel "
            "AND s.twitch_user_id=g.twitch_user_id AND s.revoked=0 AND s.expires_at > ? "
            "WHERE g.account_id = ? AND g.channel = ? GROUP BY g.account_id, g.channel, g.twitch_user_id "
            "ORDER BY g.twitch_login, g.twitch_user_id",
            (_iso(_now()), account_id, channel),
        )).fetchall()
    finally:
        await db.close()
    return {
        "ok": True,
        "account_id": account_id,
        "channel": channel,
        "grants": [
            {
                "twitch_user_id": row["twitch_user_id"],
                "twitch_login": row["twitch_login"],
                "permissions": _load_permissions(row["permissions_json"]),
                "enabled": bool(row["enabled"]),
                "active_sessions": int(row["active_sessions"]),
                "updated_at": row["updated_at"],
            }
            for row in rows
        ],
    }


async def save_chat_tts_config(account_id: int, channel: str, data: dict[str, Any]) -> dict[str, Any]:
    channel = normalize_channel(channel)
    alias = str(data.get("command_alias") or "!tts").strip().lower()
    enabled = data.get("enabled") is True
    if not channel or not _CHAT_COMMAND_RE.fullmatch(alias):
        return {"ok": False, "error": "invalid_command_alias"}
    db = await get_db()
    try:
        scope = await (await db.execute(
            "SELECT 1 FROM channels WHERE account_id = ? AND lower(ltrim(channel_name, '#')) = ? AND enabled = 1",
            (account_id, channel),
        )).fetchone()
        if not scope:
            return {"ok": False, "error": "scope_not_found"}
        await db.execute(
            "INSERT INTO moderator_console_chat_tts_config (account_id, channel, command_alias, enabled) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(account_id, channel) DO UPDATE SET "
            "command_alias=excluded.command_alias, enabled=excluded.enabled, updated_at=CURRENT_TIMESTAMP",
            (account_id, channel, alias, int(enabled)),
        )
        await db.commit()
    finally:
        await db.close()
    await _audit("moderator_chat_tts_config", f"account={account_id} channel={channel} alias={alias} enabled={int(enabled)}")
    return {"ok": True, "account_id": account_id, "channel": channel,
            "command_alias": alias, "enabled": enabled}


async def get_chat_tts_config(account_id: int, channel: str) -> dict[str, Any]:
    channel = normalize_channel(channel)
    db = await get_db()
    try:
        row = await (await db.execute(
            "SELECT command_alias, enabled FROM moderator_console_chat_tts_config "
            "WHERE account_id = ? AND channel = ?",
            (account_id, channel),
        )).fetchone()
    finally:
        await db.close()
    return {"ok": True, "account_id": account_id, "channel": channel,
            "command_alias": str(row["command_alias"]) if row else "!tts",
            "enabled": bool(row["enabled"]) if row else False}


async def handle_chat_tts_command(
    account_id: int,
    channel: str,
    *,
    twitch_user_id: str,
    twitch_login: str,
    message_id: str,
    message: str,
) -> dict[str, Any]:
    if not str(message or "").lstrip().startswith("!"):
        return {"handled": False}
    config = await get_chat_tts_config(account_id, channel)
    if not config["enabled"]:
        return {"handled": False}
    match = re.fullmatch(rf"{re.escape(config['command_alias'])}\s+(.+)", str(message or "").strip(), re.IGNORECASE | re.DOTALL)
    if not match:
        return {"handled": False}
    user_id = str(twitch_user_id or "").strip()
    msg_id = str(message_id or "").strip()
    if not user_id.isdigit():
        await _audit("moderator_chat_tts", f"account={account_id} channel={normalize_channel(channel)} result=stable_user_id_required")
        return {"handled": True, "ok": False, "error": "stable_user_id_required"}
    if not msg_id or len(msg_id) > 80:
        await _audit("moderator_chat_tts", f"account={account_id} channel={normalize_channel(channel)} user_id={user_id} result=message_id_required")
        return {"handled": True, "ok": False, "error": "message_id_required"}
    db = await get_db()
    try:
        grant = await (await db.execute(
            "SELECT permissions_json FROM moderator_console_grants WHERE account_id = ? AND channel = ? "
            "AND twitch_user_id = ? AND enabled = 1",
            (account_id, normalize_channel(channel), user_id),
        )).fetchone()
    finally:
        await db.close()
    permissions = _load_permissions(grant["permissions_json"]) if grant else []
    if "send_tts" not in permissions:
        await _audit("moderator_chat_tts", f"account={account_id} channel={normalize_channel(channel)} user_id={user_id} result=permission_denied")
        return {"handled": True, "ok": False, "error": "permission_denied"}
    result = await send_moderator_tts(
        {"account_id": account_id, "channel": normalize_channel(channel),
         "twitch_user_id": user_id, "twitch_login": str(twitch_login or "")[:100],
         "permissions": permissions},
        {"text": match.group(1).strip(), "idempotency_key": f"chat:{msg_id}"},
    )
    return {"handled": True, **result}


async def create_invite(account_id: int, channel: str, twitch_user_id: str, ttl_minutes: int = 15) -> dict[str, Any]:
    channel = normalize_channel(channel)
    user_id = str(twitch_user_id or "").strip()
    ttl = max(1, min(60, int(ttl_minutes)))
    if not channel or not user_id.isdigit() or len(user_id) > 32:
        return {"ok": False, "error": "invalid_grant"}
    db = await get_db()
    try:
        await ensure_schema(db)
        grant = await (await db.execute(
            "SELECT 1 FROM moderator_console_grants WHERE account_id = ? AND channel = ? "
            "AND twitch_user_id = ? AND enabled = 1",
            (account_id, channel, user_id),
        )).fetchone()
        if not grant:
            return {"ok": False, "error": "grant_not_found"}
        token = secrets.token_urlsafe(32)
        expires_at = _iso(_now() + timedelta(minutes=ttl))
        await db.execute(
            "INSERT INTO moderator_console_invites "
            "(account_id, channel, twitch_user_id, token_hash, expires_at) VALUES (?, ?, ?, ?, ?)",
            (account_id, channel, user_id, _hash(token), expires_at),
        )
        await db.commit()
    finally:
        await db.close()
    await _audit("moderator_console_invite", f"account={account_id} channel={channel} user_id={user_id} ttl_min={ttl}")
    return {"ok": True, "invite_token": token, "expires_at": expires_at}


async def validate_invite(invite_token: str) -> dict[str, Any]:
    """Validate a pending invite without consuming it or exposing its scope."""
    db = await get_db()
    try:
        await ensure_schema(db)
        row = await (await db.execute(
            "SELECT i.expires_at, i.used_at, g.enabled FROM moderator_console_invites i "
            "JOIN moderator_console_grants g ON g.account_id=i.account_id AND g.channel=i.channel "
            "AND g.twitch_user_id=i.twitch_user_id WHERE i.token_hash = ?",
            (_hash(str(invite_token or "")),),
        )).fetchone()
    finally:
        await db.close()
    if not row or row["used_at"] or row["expires_at"] <= _iso(_now()) or not row["enabled"]:
        return {"ok": False, "error": "invalid_or_expired_invite"}
    return {"ok": True}


async def exchange_invite(invite_token: str, twitch_access_token: str) -> dict[str, Any]:
    from app.twitch_helix import validate_token

    identity = await validate_token(str(twitch_access_token or "").removeprefix("oauth:"))
    if not identity or not identity.get("user_id"):
        return {"ok": False, "error": "invalid_twitch_identity"}
    db = await get_db()
    try:
        await ensure_schema(db)
        await db.execute("BEGIN IMMEDIATE")
        invite = await (await db.execute(
            "SELECT * FROM moderator_console_invites WHERE token_hash = ?",
            (_hash(str(invite_token or "")),),
        )).fetchone()
        if not invite or invite["used_at"] or datetime.fromisoformat(invite["expires_at"]) <= _now():
            return {"ok": False, "error": "invalid_or_expired_invite"}
        user_id = str(identity["user_id"])
        if user_id != str(invite["twitch_user_id"]):
            return {"ok": False, "error": "identity_mismatch"}
        grant = await (await db.execute(
            "SELECT permissions_json FROM moderator_console_grants WHERE account_id = ? AND channel = ? "
            "AND twitch_user_id = ? AND enabled = 1",
            (invite["account_id"], invite["channel"], user_id),
        )).fetchone()
        if not grant:
            return {"ok": False, "error": "access_revoked"}
        session_token = secrets.token_urlsafe(32)
        expires_at = _iso(_now() + timedelta(minutes=SESSION_MINUTES))
        await db.execute(
            "UPDATE moderator_console_invites SET used_at = ? WHERE id = ? AND used_at = ''",
            (_iso(_now()), invite["id"]),
        )
        await db.execute(
            "INSERT INTO moderator_console_sessions "
            "(account_id, channel, twitch_user_id, twitch_login, token_hash, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (invite["account_id"], invite["channel"], user_id,
             str(identity.get("login") or "")[:100], _hash(session_token), expires_at),
        )
        await db.commit()
        permissions = _load_permissions(grant["permissions_json"])
    finally:
        await db.close()
    await _audit("moderator_console_login", f"account={invite['account_id']} channel={invite['channel']} user_id={user_id}")
    return {"ok": True, "session_token": session_token, "expires_at": expires_at,
            "account_id": invite["account_id"], "channel": invite["channel"],
            "twitch_user_id": user_id, "permissions": permissions}


async def authenticate_session(token: str, permission: str = "") -> dict[str, Any] | None:
    if permission and permission not in PERMISSIONS:
        return None
    db = await get_db()
    try:
        row = await (await db.execute(
            "SELECT s.*, g.permissions_json, g.enabled FROM moderator_console_sessions s "
            "JOIN moderator_console_grants g ON g.account_id=s.account_id AND g.channel=s.channel "
            "AND g.twitch_user_id=s.twitch_user_id WHERE s.token_hash = ? AND s.revoked = 0",
            (_hash(str(token or "")),),
        )).fetchone()
        if not row or not row["enabled"] or datetime.fromisoformat(row["expires_at"]) <= _now():
            return None
        permissions = _load_permissions(row["permissions_json"])
        if permission and permission not in permissions:
            return None
        return {"account_id": row["account_id"], "channel": row["channel"],
                "twitch_user_id": row["twitch_user_id"], "twitch_login": row["twitch_login"],
                "permissions": permissions, "expires_at": row["expires_at"]}
    finally:
        await db.close()


async def get_moderator_context(session: dict[str, Any]) -> dict[str, Any]:
    can_send_tts = "send_tts" in session["permissions"]
    db = await get_db()
    try:
        aliases = await (await db.execute(
            "SELECT alias, label FROM tts_voice_aliases WHERE account_id = ? AND channel = ? "
            "AND enabled = 1 AND ? = 1 ORDER BY alias",
            (session["account_id"], session["channel"], int(can_send_tts)),
        )).fetchall()
        policy = await (await db.execute(
            "SELECT enabled, allowed_role, default_alias, allow_voice_choice, cooldown_sec, max_per_minute, max_length "
            "FROM tts_source_voice_policy WHERE account_id = ? AND channel = ? "
            "AND source = 'twitch_moderator_message' AND ? = 1",
            (session["account_id"], session["channel"], int(can_send_tts)),
        )).fetchone()
        preference = await (await db.execute(
            "SELECT default_alias, favorite_aliases_json FROM tts_moderator_voice_preferences "
            "WHERE account_id = ? AND channel = ? AND twitch_user_id = ? AND ? = 1",
            (session["account_id"], session["channel"], session["twitch_user_id"], int(can_send_tts)),
        )).fetchone()
    finally:
        await db.close()
    favorites: list[str] = []
    if preference:
        try:
            favorites = [str(value) for value in json.loads(preference["favorite_aliases_json"] or "[]")]
        except (TypeError, ValueError):
            favorites = []
    approved = {str(row["alias"]) for row in aliases}
    favorites = [alias for alias in favorites if alias in approved]
    default_alias = str(preference["default_alias"] or "") if preference else ""
    if default_alias not in approved:
        default_alias = ""
    return {
        "ok": True,
        "account_id": session["account_id"],
        "channel": session["channel"],
        "twitch_user_id": session["twitch_user_id"],
        "expires_at": session.get("expires_at", ""),
        "permissions": session["permissions"],
        # Raw provider IDs and voice IDs intentionally never enter the moderator response.
        "voices": [dict(row) for row in aliases],
        "policy": dict(policy) if policy else None,
        "preferences": {
            "default_alias": default_alias,
            "favorites": favorites,
        },
    }


async def save_moderator_preferences(session: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    if "send_tts" not in session["permissions"]:
        await _audit("moderator_console_preferences", f"user_id={session['twitch_user_id']} result=permission_denied")
        return {"ok": False, "error": "permission_denied"}
    from app.tts_voice_policy import set_moderator_preferences
    result = await set_moderator_preferences(
        session["account_id"], session["channel"], session["twitch_user_id"],
        default_alias=str(data.get("default_alias") or "").strip().lower(),
        favorites=[str(value).strip().lower() for value in data.get("favorites", [])]
        if isinstance(data.get("favorites"), list) else [],
    )
    if not result["ok"]:
        await _audit(
            "moderator_console_preferences",
            f"account={session['account_id']} channel={session['channel']} "
            f"user_id={session['twitch_user_id']} result={result['error']}",
        )
    return result


async def _reserve_tts_command(
    session: dict[str, Any], idempotency_key: str, text: str, alias: str
) -> tuple[int, dict[str, Any] | None]:
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT OR IGNORE INTO moderator_console_tts_commands "
            "(account_id, channel, twitch_user_id, idempotency_key, text, voice_alias) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (session["account_id"], session["channel"], session["twitch_user_id"],
             idempotency_key, text, alias),
        )
        await db.commit()
        if cursor.rowcount:
            return int(cursor.lastrowid), None
        row = await (await db.execute(
            "SELECT id, status, reason, voice_alias FROM moderator_console_tts_commands "
            "WHERE account_id = ? AND channel = ? AND twitch_user_id = ? AND idempotency_key = ?",
            (session["account_id"], session["channel"], session["twitch_user_id"], idempotency_key),
        )).fetchone()
        return 0, dict(row) if row else {"status": "rejected", "reason": "duplicate_unknown"}
    finally:
        await db.close()


async def _finish_tts_command(command_id: int, status: str, reason: str = "", alias: str = "") -> None:
    db = await get_db()
    try:
        await db.execute(
            "UPDATE moderator_console_tts_commands SET status = ?, reason = ?, voice_alias = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, reason, alias, command_id),
        )
        await db.commit()
    finally:
        await db.close()


async def list_moderator_tts_commands(session: dict[str, Any]) -> dict[str, Any]:
    if "send_tts" not in session["permissions"]:
        return {"ok": False, "error": "permission_denied"}
    db = await get_db()
    try:
        rows = await (await db.execute(
            "SELECT id, text, voice_alias, status, reason, created_at, updated_at "
            "FROM moderator_console_tts_commands WHERE account_id = ? AND channel = ? "
            "AND twitch_user_id = ? ORDER BY id DESC LIMIT 50",
            (session["account_id"], session["channel"], session["twitch_user_id"]),
        )).fetchall()
    finally:
        await db.close()
    return {"ok": True, "commands": [dict(row) for row in rows]}


async def send_moderator_tts(session: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    if "send_tts" not in session["permissions"]:
        await _audit("moderator_console_tts", f"user_id={session['twitch_user_id']} result=permission_denied")
        return {"ok": False, "error": "permission_denied"}
    text = str(data.get("text") or "").strip()
    alias = str(data.get("voice_alias") or "").strip().lower()
    idempotency_key = str(data.get("idempotency_key") or "").strip()
    if not _IDEMPOTENCY_RE.fullmatch(idempotency_key):
        await _audit(
            "moderator_console_tts",
            f"account={session['account_id']} channel={session['channel']} "
            f"user_id={session['twitch_user_id']} result=idempotency_required",
        )
        return {"ok": False, "error": "idempotency_required"}
    command_id, duplicate = await _reserve_tts_command(session, idempotency_key, text, alias)
    if duplicate is not None:
        accepted = duplicate.get("status") == "accepted"
        duplicate_status = str(duplicate.get("status") or "rejected")
        await _audit(
            "moderator_console_tts",
            f"account={session['account_id']} channel={session['channel']} "
            f"user_id={session['twitch_user_id']} result=duplicate status={duplicate_status}",
        )
        result = {"ok": accepted, "status": duplicate.get("status", "rejected"),
                  "duplicate": True, "command_id": duplicate.get("id", 0),
                  "voice_alias": duplicate.get("voice_alias", "")}
        if not accepted:
            result["error"] = "in_progress" if duplicate_status == "pending" else duplicate.get("reason") or "rejected"
        return result
    from app.tts_voice_policy import authorize_tts
    decision = await authorize_tts(
        session["account_id"], session["channel"], "twitch_moderator_message",
        actor_role="moderator", actor_id=session["twitch_user_id"], text=text,
        requested_alias=alias,
    )
    # A protected console never inherits permissive legacy behavior.
    if decision.get("legacy"):
        await _audit(
            "moderator_console_tts",
            f"account={session['account_id']} channel={session['channel']} "
            f"user_id={session['twitch_user_id']} result=policy_missing",
        )
        await _finish_tts_command(command_id, "rejected", "policy_missing", alias)
        return {"ok": False, "error": "policy_missing", "command_id": command_id}
    if not decision["ok"]:
        reason = str(decision.get("reason") or "rejected")
        await _finish_tts_command(command_id, "rejected", reason, alias)
        return {"ok": False, "error": reason, "command_id": command_id}
    if not decision.get("alias") or not decision.get("provider_override") or not decision.get("voice_override"):
        await _finish_tts_command(command_id, "rejected", "approved_voice_required", alias)
        await _audit(
            "moderator_console_tts",
            f"account={session['account_id']} channel={session['channel']} "
            f"user_id={session['twitch_user_id']} result=approved_voice_required",
        )
        return {"ok": False, "error": "approved_voice_required", "command_id": command_id}
    from app.audio_queue import get_audio_queue
    await get_audio_queue().enqueue(
        "tts_moderator", session["account_id"], session["channel"], text,
        speaker=session.get("twitch_login") or session["twitch_user_id"],
        speaker_kind="viewer", display_text=text,
        provider_override=str(decision.get("provider_override") or ""),
        voice_override=str(decision.get("voice_override") or ""),
    )
    resolved_alias = str(decision.get("alias") or "")
    await _finish_tts_command(command_id, "accepted", "", resolved_alias)
    return {"ok": True, "status": "accepted", "command_id": command_id,
            "voice_alias": resolved_alias}


async def _request_session(request: Request) -> dict[str, Any]:
    header = request.headers.get("Authorization", "")
    token = header[7:] if header.lower().startswith("bearer ") else ""
    session = await authenticate_session(token)
    if not session:
        raise HTTPException(status_code=401, detail="unauthorized")
    return session


@admin_router.put("/accounts/{account_id}/channels/{channel}/grants/{twitch_user_id}")
async def api_save_grant(account_id: int, channel: str, twitch_user_id: str, data: dict) -> dict[str, Any]:
    return await save_grant(account_id, channel, {**data, "twitch_user_id": twitch_user_id})


@admin_router.get("/accounts/{account_id}/channels/{channel}/grants")
async def api_list_grants(account_id: int, channel: str) -> dict[str, Any]:
    return await list_grants(account_id, channel)


@admin_router.get("/accounts/{account_id}/channels/{channel}/chat-tts")
async def api_get_chat_tts_config(account_id: int, channel: str) -> dict[str, Any]:
    return await get_chat_tts_config(account_id, channel)


@admin_router.put("/accounts/{account_id}/channels/{channel}/chat-tts")
async def api_save_chat_tts_config(account_id: int, channel: str, data: dict) -> dict[str, Any]:
    return await save_chat_tts_config(account_id, channel, data)


@admin_router.post("/accounts/{account_id}/channels/{channel}/grants/{twitch_user_id}/invite")
async def api_create_invite(account_id: int, channel: str, twitch_user_id: str, data: dict | None = None) -> dict[str, Any]:
    return await create_invite(account_id, channel, twitch_user_id, int((data or {}).get("ttl_minutes", 15)))


@public_router.post("/session")
async def api_exchange_invite(data: dict) -> dict[str, Any]:
    result = await exchange_invite(str(data.get("invite_token") or ""), str(data.get("twitch_access_token") or ""))
    if not result["ok"]:
        raise HTTPException(status_code=401, detail=result["error"])
    return result


@public_router.post("/twitch-device")
async def api_start_twitch_device(data: dict) -> dict[str, Any]:
    from app import twitch_oauth

    invite_token = str(data.get("invite_token") or "")
    invite = await validate_invite(invite_token)
    if not invite["ok"]:
        raise HTTPException(status_code=401, detail=invite["error"])
    _gc_device_logins()
    invite_hash = _hash(invite_token)
    for pending in _device_logins.values():
        if pending["invite_hash"] == invite_hash:
            return dict(pending["response"])
    result = await twitch_oauth.start_device_flow(scopes=[])
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("error", "twitch_unavailable"))
    twitch_oauth.remember_session(
        result["device_code"], result["user_code"], int(result.get("expires_in", 600))
    )
    interval = max(1, int(result.get("interval", 5)))
    _device_logins[result["device_code"]] = {
        "invite_hash": invite_hash,
        "expires_at": _device_now() + max(1, int(result.get("expires_in", 600))),
        "next_poll_at": _device_now() + interval,
        "interval": interval,
        "response": dict(result),
    }
    return result


@public_router.post("/twitch-device/poll")
async def api_poll_twitch_device(data: dict) -> dict[str, Any]:
    from app import twitch_oauth

    device_code = str(data.get("device_code") or "")
    invite_token = str(data.get("invite_token") or "")
    _gc_device_logins()
    pending = _device_logins.get(device_code)
    if (not pending or pending["invite_hash"] != _hash(invite_token)
            or not twitch_oauth.is_known_session(device_code)
            or not (await validate_invite(invite_token))["ok"]):
        raise HTTPException(status_code=401, detail="invalid_login_session")
    if _device_now() < float(pending["next_poll_at"]):
        return {"ok": False, "slow_down": True}
    pending["next_poll_at"] = _device_now() + int(pending["interval"])
    result = await twitch_oauth.poll_device_token(device_code)
    if not result.get("ok"):
        return result
    twitch_oauth.forget_session(device_code)
    _device_logins.pop(device_code, None)
    exchanged = await exchange_invite(invite_token, result["access_token"])
    if not exchanged["ok"]:
        raise HTTPException(status_code=401, detail=exchanged["error"])
    return exchanged


@public_router.get("/me")
async def api_session_me(session: dict[str, Any] = Depends(_request_session)) -> dict[str, Any]:
    return {"ok": True, "session": session}


@public_router.get("/context")
async def api_moderator_context(session: dict[str, Any] = Depends(_request_session)) -> dict[str, Any]:
    return await get_moderator_context(session)


@public_router.put("/preferences")
async def api_moderator_preferences(data: dict, session: dict[str, Any] = Depends(_request_session)) -> dict[str, Any]:
    result = await save_moderator_preferences(session, data)
    if not result["ok"]:
        raise HTTPException(status_code=403, detail=result["error"])
    return result


@public_router.post("/tts")
async def api_moderator_tts(data: dict, session: dict[str, Any] = Depends(_request_session)) -> dict[str, Any]:
    result = await send_moderator_tts(session, data)
    if not result["ok"]:
        error = result["error"]
        status = 400 if error == "idempotency_required" else 409 if error == "in_progress" else 429 if error in {"cooldown", "rate_limit"} else 403
        raise HTTPException(status_code=status, detail=error)
    return result


@public_router.get("/tts/commands")
async def api_moderator_tts_commands(session: dict[str, Any] = Depends(_request_session)) -> dict[str, Any]:
    result = await list_moderator_tts_commands(session)
    if not result["ok"]:
        raise HTTPException(status_code=403, detail=result["error"])
    return result


@page_router.get("/moderator-console", response_class=HTMLResponse)
async def moderator_console_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="moderator_console.html", context={})
