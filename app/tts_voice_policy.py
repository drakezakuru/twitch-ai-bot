"""Exact-scoped approved voice aliases and per-source TTS policy."""

from __future__ import annotations

import json
import re
import time
from collections import defaultdict, deque
from typing import Any

from fastapi import APIRouter, Depends

from app.database import get_db
from app.security import auth_dependency

router = APIRouter(
    prefix="/api/accounts/{account_id}/channels/{channel}/tts-voice-policy",
    tags=["tts-voice-policy"],
    dependencies=[Depends(auth_dependency)],
)

SOURCES = {
    "bot_reply",
    "voice_companion_reply",
    "moderation_announcement",
    "twitch_moderator_message",
    "ordinary_chat",
    "channel_points_reward",
}
ROLES = {"owner", "moderator", "viewer", "bot"}
_ALIAS_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
_runtime_last: dict[tuple[int, str, str, str], float] = {}
_runtime_window: dict[tuple[int, str, str, str], deque[float]] = defaultdict(deque)


def normalize_channel(channel: str) -> str:
    return str(channel or "").strip().lower().lstrip("#")


async def ensure_schema(db=None) -> None:
    own = db is None
    db = db or await get_db()
    try:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS tts_voice_aliases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                alias TEXT NOT NULL,
                provider TEXT NOT NULL,
                voice_id TEXT NOT NULL,
                label TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
                UNIQUE(account_id, channel, alias)
            );
            CREATE TABLE IF NOT EXISTS tts_source_voice_policy (
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                source TEXT NOT NULL,
                allowed_role TEXT NOT NULL DEFAULT 'owner',
                default_alias TEXT NOT NULL DEFAULT '',
                allow_voice_choice INTEGER NOT NULL DEFAULT 0,
                cooldown_sec INTEGER NOT NULL DEFAULT 5,
                max_per_minute INTEGER NOT NULL DEFAULT 5,
                max_length INTEGER NOT NULL DEFAULT 300,
                blacklist TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
                UNIQUE(account_id, channel, source)
            );
            CREATE TABLE IF NOT EXISTS tts_moderator_voice_preferences (
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                twitch_user_id TEXT NOT NULL,
                default_alias TEXT NOT NULL DEFAULT '',
                favorite_aliases_json TEXT NOT NULL DEFAULT '[]',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
                UNIQUE(account_id, channel, twitch_user_id)
            );
        """)
        await db.commit()
    finally:
        if own:
            await db.close()


async def _scope_exists(db, account_id: int, channel: str) -> bool:
    row = await (await db.execute(
        "SELECT 1 FROM channels WHERE account_id = ? AND lower(ltrim(channel_name, '#')) = ? AND enabled = 1",
        (account_id, channel),
    )).fetchone()
    return row is not None


async def _registered_voice(db, provider: str, voice_id: str) -> str | None:
    row = await (await db.execute(
        "SELECT label FROM tts_voice_presets WHERE provider = ? AND voice_id = ?",
        (provider, voice_id),
    )).fetchone()
    if row:
        return str(row["label"])
    row = await (await db.execute(
        "SELECT name FROM voice_clones WHERE provider = ? AND voice_id = ?",
        (provider, voice_id),
    )).fetchone()
    return str(row["name"]) if row else None


async def get_scope_policy(account_id: int, channel: str) -> dict[str, Any]:
    channel = normalize_channel(channel)
    db = await get_db()
    try:
        await ensure_schema(db)
        aliases = await (await db.execute(
            "SELECT alias, provider, voice_id, label, enabled FROM tts_voice_aliases "
            "WHERE account_id = ? AND channel = ? ORDER BY alias",
            (account_id, channel),
        )).fetchall()
        policies = await (await db.execute(
            "SELECT source, allowed_role, default_alias, allow_voice_choice, cooldown_sec, "
            "max_per_minute, max_length, blacklist, enabled FROM tts_source_voice_policy "
            "WHERE account_id = ? AND channel = ? ORDER BY source",
            (account_id, channel),
        )).fetchall()
        return {"ok": True, "account_id": account_id, "channel": channel,
                "aliases": [dict(row) for row in aliases], "policies": [dict(row) for row in policies]}
    finally:
        await db.close()


async def set_moderator_preferences(
    account_id: int, channel: str, twitch_user_id: str, *, default_alias: str, favorites: list[str]
) -> dict[str, Any]:
    """Trusted console helper; public HTTP exposure belongs to the access-controlled console."""
    channel = normalize_channel(channel)
    user_id = str(twitch_user_id or "").strip()
    requested = list(dict.fromkeys([default_alias, *favorites]))
    requested = [alias for alias in requested if alias]
    db = await get_db()
    try:
        await ensure_schema(db)
        rows = await (await db.execute(
            "SELECT alias FROM tts_voice_aliases WHERE account_id = ? AND channel = ? AND enabled = 1",
            (account_id, channel),
        )).fetchall()
        approved = {str(row["alias"]) for row in rows}
        if not user_id or any(alias not in approved for alias in requested):
            return {"ok": False, "error": "unapproved_alias"}
        clean_favorites = list(dict.fromkeys(alias for alias in favorites if alias in approved))[:20]
        await db.execute(
            "INSERT INTO tts_moderator_voice_preferences "
            "(account_id, channel, twitch_user_id, default_alias, favorite_aliases_json) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(account_id, channel, twitch_user_id) DO UPDATE SET "
            "default_alias=excluded.default_alias, favorite_aliases_json=excluded.favorite_aliases_json, "
            "updated_at=CURRENT_TIMESTAMP",
            (account_id, channel, user_id, default_alias, json.dumps(clean_favorites)),
        )
        await db.commit()
        await _audit(
            "tts_moderator_voice_preferences",
            f"account={account_id} channel={channel} twitch_user_id={user_id}",
        )
        return {"ok": True, "default_alias": default_alias, "favorites": clean_favorites}
    finally:
        await db.close()


async def _audit(action: str, detail: str) -> None:
    from app.routes import log_action
    await log_action(action, detail)


async def authorize_tts(
    account_id: int,
    channel: str,
    source: str,
    *,
    actor_role: str,
    actor_id: str,
    text: str,
    requested_alias: str = "",
) -> dict[str, Any]:
    """Apply an explicit source policy; absent policy preserves legacy behavior."""
    channel = normalize_channel(channel)
    from app.tts_mute_state import is_tts_muted
    if is_tts_muted(channel)[0]:
        return {"ok": False, "legacy": False, "reason": "tts_temporary_muted", "provider_override": "", "voice_override": ""}
    source = str(source or "").strip().lower()
    actor_role = str(actor_role or "").strip().lower()
    actor_id = str(actor_id or "").strip().lower()
    db = await get_db()
    try:
        row = await (await db.execute(
            "SELECT * FROM tts_source_voice_policy WHERE account_id = ? AND channel = ? AND source = ?",
            (account_id, channel, source),
        )).fetchone()
        if not row:
            return {"ok": True, "legacy": True, "provider_override": "", "voice_override": ""}
        policy = dict(row)
        reason = ""
        if not policy["enabled"]:
            reason = "policy_disabled"
        elif actor_role != policy["allowed_role"]:
            reason = "role_denied"
        elif not str(text or "").strip():
            reason = "empty"
        elif len(str(text)) > int(policy["max_length"]):
            reason = "too_long"
        else:
            lowered = str(text).lower()
            words = [word.strip().lower() for word in str(policy["blacklist"] or "").split(",") if word.strip()]
            if any(word in lowered for word in words):
                reason = "blacklist"

        alias = str(requested_alias or "").strip().lower()
        if not alias and actor_role == "moderator":
            pref = await (await db.execute(
                "SELECT default_alias FROM tts_moderator_voice_preferences "
                "WHERE account_id = ? AND channel = ? AND twitch_user_id = ?",
                (account_id, channel, actor_id),
            )).fetchone()
            alias = str(pref["default_alias"] or "") if pref else ""
        alias = alias or str(policy["default_alias"] or "")
        if requested_alias and not policy["allow_voice_choice"]:
            reason = reason or "voice_choice_denied"
        provider = ""
        voice_id = ""
        if alias:
            voice = await (await db.execute(
                "SELECT provider, voice_id FROM tts_voice_aliases WHERE account_id = ? AND channel = ? "
                "AND alias = ? AND enabled = 1",
                (account_id, channel, alias),
            )).fetchone()
            if not voice:
                reason = reason or "unapproved_alias"
            else:
                provider = str(voice["provider"])
                voice_id = str(voice["voice_id"])
    finally:
        await db.close()

    key = (account_id, channel, source, actor_id)
    now = time.monotonic()
    if not reason and now - _runtime_last.get(key, 0.0) < int(policy["cooldown_sec"]):
        reason = "cooldown"
    window = _runtime_window[key]
    while window and now - window[0] >= 60:
        window.popleft()
    if not reason and len(window) >= int(policy["max_per_minute"]):
        reason = "rate_limit"
    if not reason:
        _runtime_last[key] = now
        window.append(now)
    await _audit(
        "tts_policy_command",
        f"account={account_id} channel={channel} source={source} actor_role={actor_role} "
        f"actor_id={actor_id} result={reason or 'accepted'} alias={alias}",
    )
    return {"ok": not reason, "legacy": False, "reason": reason,
            "provider_override": provider, "voice_override": voice_id, "alias": alias}


def reset_runtime_state() -> None:
    _runtime_last.clear()
    _runtime_window.clear()


@router.get("")
async def api_get_policy(account_id: int, channel: str) -> dict[str, Any]:
    return await get_scope_policy(account_id, channel)


@router.put("/aliases/{alias}")
async def api_put_alias(account_id: int, channel: str, alias: str, data: dict) -> dict[str, Any]:
    channel = normalize_channel(channel)
    alias = str(alias or "").strip().lower()
    provider = str(data.get("provider") or "").strip().lower()
    voice_id = str(data.get("voice_id") or "").strip()
    if not channel or not _ALIAS_RE.fullmatch(alias) or not provider or not voice_id:
        return {"ok": False, "error": "invalid_alias"}
    db = await get_db()
    try:
        await ensure_schema(db)
        if not await _scope_exists(db, account_id, channel):
            return {"ok": False, "error": "scope_not_found"}
        label = await _registered_voice(db, provider, voice_id)
        if not label:
            return {"ok": False, "error": "voice_not_registered"}
        await db.execute(
            "INSERT INTO tts_voice_aliases (account_id, channel, alias, provider, voice_id, label, enabled) "
            "VALUES (?, ?, ?, ?, ?, ?, 1) ON CONFLICT(account_id, channel, alias) DO UPDATE SET "
            "provider=excluded.provider, voice_id=excluded.voice_id, label=excluded.label, enabled=1",
            (account_id, channel, alias, provider, voice_id, label),
        )
        await db.commit()
    finally:
        await db.close()
    await _audit("tts_voice_alias_upsert", f"account={account_id} channel={channel} alias={alias}")
    return {"ok": True, "alias": alias, "label": label}


@router.put("/sources/{source}")
async def api_put_source_policy(account_id: int, channel: str, source: str, data: dict) -> dict[str, Any]:
    channel = normalize_channel(channel)
    source = str(source or "").strip().lower()
    role = str(data.get("allowed_role") or "owner").strip().lower()
    default_alias = str(data.get("default_alias") or "").strip().lower()
    if source not in SOURCES or role not in ROLES or not channel:
        return {"ok": False, "error": "invalid_policy"}
    db = await get_db()
    try:
        await ensure_schema(db)
        if not await _scope_exists(db, account_id, channel):
            return {"ok": False, "error": "scope_not_found"}
        if default_alias:
            alias_row = await (await db.execute(
                "SELECT 1 FROM tts_voice_aliases WHERE account_id = ? AND channel = ? AND alias = ? AND enabled = 1",
                (account_id, channel, default_alias),
            )).fetchone()
            if not alias_row:
                return {"ok": False, "error": "unapproved_default_alias"}
        try:
            cooldown = max(0, min(600, int(data.get("cooldown_sec", 5))))
            rate = max(1, min(60, int(data.get("max_per_minute", 5))))
            max_length = max(1, min(500, int(data.get("max_length", 300))))
        except (TypeError, ValueError):
            return {"ok": False, "error": "invalid_limits"}
        blacklist = str(data.get("blacklist") or "")[:2000]
        enabled = 1 if data.get("enabled") is True else 0
        choose = 1 if data.get("allow_voice_choice") is True else 0
        await db.execute(
            "INSERT INTO tts_source_voice_policy (account_id, channel, source, allowed_role, default_alias, "
            "allow_voice_choice, cooldown_sec, max_per_minute, max_length, blacklist, enabled) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(account_id, channel, source) DO UPDATE SET "
            "allowed_role=excluded.allowed_role, default_alias=excluded.default_alias, "
            "allow_voice_choice=excluded.allow_voice_choice, cooldown_sec=excluded.cooldown_sec, "
            "max_per_minute=excluded.max_per_minute, max_length=excluded.max_length, "
            "blacklist=excluded.blacklist, enabled=excluded.enabled, updated_at=CURRENT_TIMESTAMP",
            (account_id, channel, source, role, default_alias, choose, cooldown, rate, max_length, blacklist, enabled),
        )
        await db.commit()
    finally:
        await db.close()
    await _audit("tts_source_policy_update", f"account={account_id} channel={channel} source={source}")
    return {"ok": True, "source": source}
