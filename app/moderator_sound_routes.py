"""Exact-scoped moderator sound commands for the existing OBS soundboard."""

from __future__ import annotations

import hashlib
import re
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse

from app.database import get_db
from app.moderator_console_routes import _owner_auth_dependency, authenticate_session
from app.tts_voice_policy import normalize_channel

admin_router = APIRouter(prefix="/api/moderator-console/admin/sounds", tags=["moderator-console-sounds-admin"], dependencies=[Depends(_owner_auth_dependency)])
public_router = APIRouter(prefix="/api/moderator-console/sounds", tags=["moderator-console-sounds"])
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,99}$")
_runtime_last: dict[tuple[int, str, str], float] = {}
_runtime_window: dict[tuple[int, str, str], deque[float]] = defaultdict(deque)


async def ensure_schema(db=None) -> None:
    own = db is None
    db = db or await get_db()
    try:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS moderator_console_sound_approvals (
                account_id INTEGER NOT NULL, channel TEXT NOT NULL, track_id INTEGER NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
                FOREIGN KEY (track_id) REFERENCES soundboard_tracks(id) ON DELETE CASCADE,
                UNIQUE(account_id, channel, track_id)
            );
            CREATE TABLE IF NOT EXISTS moderator_console_sound_policy (
                account_id INTEGER NOT NULL, channel TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                cooldown_sec INTEGER NOT NULL DEFAULT 5, max_per_minute INTEGER NOT NULL DEFAULT 5,
                obs_token_hash TEXT NOT NULL DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
                UNIQUE(account_id, channel)
            );
            CREATE TABLE IF NOT EXISTS moderator_console_sound_commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER NOT NULL, channel TEXT NOT NULL,
                twitch_user_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, track_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', reason TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
                UNIQUE(account_id, channel, twitch_user_id, idempotency_key)
            );
            CREATE TABLE IF NOT EXISTS moderator_console_sound_favorites (
                account_id INTEGER NOT NULL, channel TEXT NOT NULL, twitch_user_id TEXT NOT NULL,
                track_id INTEGER NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(account_id, channel, twitch_user_id, track_id),
                FOREIGN KEY(track_id) REFERENCES soundboard_tracks(id) ON DELETE CASCADE
            );
        """)
        columns = {
            row[1] for row in await (
                await db.execute("PRAGMA table_info(moderator_console_sound_policy)")
            ).fetchall()
        }
        if "obs_token_hash" not in columns:
            await db.execute(
                "ALTER TABLE moderator_console_sound_policy "
                "ADD COLUMN obs_token_hash TEXT NOT NULL DEFAULT ''"
            )
        await db.commit()
    finally:
        if own:
            await db.close()


async def _audit(action: str, detail: str) -> None:
    from app.routes import log_action
    await log_action(action, detail)


async def _scope_exists(db, account_id: int, channel: str) -> bool:
    return bool(await (await db.execute(
        "SELECT 1 FROM channels WHERE account_id=? AND lower(ltrim(channel_name, '#'))=? AND enabled=1",
        (account_id, channel),
    )).fetchone())


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def valid_obs_token(account_id: int, channel: str, token: str) -> bool:
    channel = normalize_channel(channel)
    if not channel or not token:
        return False
    db = await get_db()
    try:
        await ensure_schema(db)
        row = await (await db.execute(
            "SELECT obs_token_hash FROM moderator_console_sound_policy "
            "WHERE account_id=? AND channel=?",
            (account_id, channel),
        )).fetchone()
    finally:
        await db.close()
    return bool(
        row and row["obs_token_hash"]
        and secrets.compare_digest(row["obs_token_hash"], _hash_token(token))
    )


async def rotate_obs_token(account_id: int, channel: str) -> dict[str, Any]:
    channel = normalize_channel(channel)
    db = await get_db()
    try:
        await ensure_schema(db)
        if not await _scope_exists(db, account_id, channel):
            return {"ok": False, "error": "scope_not_found"}
        token = secrets.token_urlsafe(32)
        await db.execute(
            "INSERT INTO moderator_console_sound_policy "
            "(account_id,channel,obs_token_hash) VALUES(?,?,?) "
            "ON CONFLICT(account_id,channel) DO UPDATE SET "
            "obs_token_hash=excluded.obs_token_hash,updated_at=CURRENT_TIMESTAMP",
            (account_id, channel, _hash_token(token)),
        )
        await db.commit()
    finally:
        await db.close()
    await _audit(
        "moderator_sound_obs_token_rotate",
        f"account={account_id} channel={channel}",
    )
    return {
        "ok": True,
        "widget_url": (
            f"/widget/soundboard?account_id={account_id}&channel={channel}&token={token}"
        ),
    }


async def save_sound_approval(account_id: int, channel: str, track_id: int, *, enabled: bool) -> dict[str, Any]:
    channel = normalize_channel(channel)
    if not channel or track_id < 1:
        return {"ok": False, "error": "invalid_approval"}
    db = await get_db()
    try:
        await ensure_schema(db)
        if not await _scope_exists(db, account_id, channel):
            return {"ok": False, "error": "scope_not_found"}
        if not await (await db.execute("SELECT 1 FROM soundboard_tracks WHERE id=?", (track_id,))).fetchone():
            return {"ok": False, "error": "track_not_found"}
        await db.execute(
            "INSERT INTO moderator_console_sound_approvals (account_id,channel,track_id,enabled) VALUES (?,?,?,?) "
            "ON CONFLICT(account_id,channel,track_id) DO UPDATE SET enabled=excluded.enabled,updated_at=CURRENT_TIMESTAMP",
            (account_id, channel, track_id, int(enabled)),
        )
        await db.commit()
    finally:
        await db.close()
    await _audit("moderator_sound_approval", f"account={account_id} channel={channel} track_id={track_id} enabled={int(enabled)}")
    return {"ok": True, "account_id": account_id, "channel": channel, "track_id": track_id, "enabled": enabled}


async def save_sound_policy(account_id: int, channel: str, data: dict[str, Any]) -> dict[str, Any]:
    channel = normalize_channel(channel)
    if not channel:
        return {"ok": False, "error": "invalid_policy"}
    try:
        cooldown, rate = max(0, min(600, int(data.get("cooldown_sec", 5)))), max(1, min(60, int(data.get("max_per_minute", 5))))
    except (TypeError, ValueError):
        return {"ok": False, "error": "invalid_limits"}
    db = await get_db()
    try:
        await ensure_schema(db)
        if not await _scope_exists(db, account_id, channel):
            return {"ok": False, "error": "scope_not_found"}
        enabled = data.get("enabled", True) is True
        await db.execute(
            "INSERT INTO moderator_console_sound_policy (account_id,channel,enabled,cooldown_sec,max_per_minute) VALUES (?,?,?,?,?) "
            "ON CONFLICT(account_id,channel) DO UPDATE SET enabled=excluded.enabled,cooldown_sec=excluded.cooldown_sec,"
            "max_per_minute=excluded.max_per_minute,updated_at=CURRENT_TIMESTAMP",
            (account_id, channel, int(enabled), cooldown, rate),
        )
        await db.commit()
    finally:
        await db.close()
    await _audit("moderator_sound_policy", f"account={account_id} channel={channel} enabled={int(enabled)} cooldown={cooldown} rate={rate}")
    return {"ok": True, "account_id": account_id, "channel": channel, "enabled": enabled, "cooldown_sec": cooldown, "max_per_minute": rate}


async def list_approved_sounds(session: dict[str, Any]) -> dict[str, Any]:
    if "play_sound" not in session.get("permissions", []):
        return {"ok": False, "error": "permission_denied"}
    db = await get_db()
    try:
        await ensure_schema(db)
        rows = await (await db.execute(
            "SELECT t.id,t.name,t.mime,t.created_at,EXISTS(SELECT 1 FROM moderator_console_sound_favorites f WHERE f.account_id=a.account_id AND f.channel=a.channel AND f.twitch_user_id=? AND f.track_id=t.id) AS favorite "
            "FROM moderator_console_sound_approvals a JOIN soundboard_tracks t ON t.id=a.track_id "
            "WHERE a.account_id=? AND a.channel=? AND a.enabled=1 ORDER BY favorite DESC,t.name COLLATE NOCASE,t.id",
            (session["twitch_user_id"], session["account_id"], normalize_channel(session["channel"])),
        )).fetchall()
    finally:
        await db.close()
    return {"ok": True, "items": [dict(row) for row in rows]}


async def _reserve_command(session: dict[str, Any], key: str, track_id: int) -> tuple[int, dict[str, Any] | None]:
    db = await get_db()
    try:
        channel = normalize_channel(session["channel"])
        cursor = await db.execute(
            "INSERT OR IGNORE INTO moderator_console_sound_commands (account_id,channel,twitch_user_id,idempotency_key,track_id) VALUES (?,?,?,?,?)",
            (session["account_id"], channel, session["twitch_user_id"], key, track_id),
        )
        await db.commit()
        if cursor.rowcount:
            return int(cursor.lastrowid), None
        row = await (await db.execute(
            "SELECT id,track_id,status,reason FROM moderator_console_sound_commands WHERE account_id=? AND channel=? AND twitch_user_id=? AND idempotency_key=?",
            (session["account_id"], channel, session["twitch_user_id"], key),
        )).fetchone()
        return 0, dict(row) if row else {"id": 0, "track_id": track_id, "status": "rejected", "reason": "duplicate_unknown"}
    finally:
        await db.close()


async def _finish_command(command_id: int, status: str, reason: str = "") -> None:
    db = await get_db()
    try:
        await db.execute("UPDATE moderator_console_sound_commands SET status=?,reason=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (status, reason, command_id))
        await db.commit()
    finally:
        await db.close()


def _result(command_id: int, track_id: int, status: str, reason: str = "") -> dict[str, Any]:
    return {"ok": status == "accepted", "status": status, "command_id": command_id, "track_id": track_id, "error": reason}


async def play_moderator_sound(session: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    if "play_sound" not in session.get("permissions", []):
        await _audit("moderator_sound_command", f"user_id={session.get('twitch_user_id', '')} result=permission_denied")
        return {"ok": False, "error": "permission_denied"}
    key = str(data.get("idempotency_key") or "").strip()
    try:
        track_id = int(data.get("track_id"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "invalid_track"}
    if not _IDEMPOTENCY_RE.fullmatch(key):
        return {"ok": False, "error": "idempotency_key_required"}
    if track_id < 1:
        return {"ok": False, "error": "invalid_track"}
    command_id, existing = await _reserve_command(session, key, track_id)
    if existing is not None:
        return _result(int(existing["id"]), int(existing["track_id"]), str(existing["status"]), str(existing["reason"]))

    account_id, channel, user_id = int(session["account_id"]), normalize_channel(session["channel"]), str(session["twitch_user_id"])
    db = await get_db()
    try:
        await ensure_schema(db)
        policy = await (await db.execute("SELECT enabled,cooldown_sec,max_per_minute FROM moderator_console_sound_policy WHERE account_id=? AND channel=?", (account_id, channel))).fetchone()
        approved = await (await db.execute(
            "SELECT 1 FROM moderator_console_sound_approvals a JOIN soundboard_tracks t ON t.id=a.track_id WHERE a.account_id=? AND a.channel=? AND a.track_id=? AND a.enabled=1",
            (account_id, channel, track_id),
        )).fetchone()
        exists = await (await db.execute("SELECT 1 FROM soundboard_tracks WHERE id=?", (track_id,))).fetchone()
        scope_exists = await _scope_exists(db, account_id, channel)
    finally:
        await db.close()
    reason = "" if scope_exists else "scope_not_found"
    if policy and not policy["enabled"]:
        reason = reason or "policy_disabled"
    if not approved:
        reason = reason or ("unapproved_track" if exists else "track_not_found")
    cooldown, rate = (int(policy["cooldown_sec"]), int(policy["max_per_minute"])) if policy else (5, 5)
    runtime_key, now = (account_id, channel, user_id), time.monotonic()
    window = _runtime_window[runtime_key]
    while window and now - window[0] >= 60:
        window.popleft()
    if not reason and now - _runtime_last.get(runtime_key, 0.0) < cooldown:
        reason = "cooldown"
    if not reason and len(window) >= rate:
        reason = "rate_limit"
    if reason:
        await _finish_command(command_id, "rejected", reason)
        await _audit("moderator_sound_command", f"account={account_id} channel={channel} user_id={user_id} track_id={track_id} result={reason}")
        return _result(command_id, track_id, "rejected", reason)
    _runtime_last[runtime_key] = now
    window.append(now)
    from app.server import broadcast_log
    await broadcast_log({"type": "soundboard", "kind": "play", "track_id": track_id, "account_id": account_id, "channel": channel, "source": "moderator_console", "at": time.time()})
    await _finish_command(command_id, "accepted")
    await _audit("moderator_sound_command", f"account={account_id} channel={channel} user_id={user_id} track_id={track_id} result=accepted")
    return _result(command_id, track_id, "accepted")


async def stop_moderator_sound(session: dict[str, Any]) -> dict[str, Any]:
    if "play_sound" not in session.get("permissions", []):
        return {"ok": False, "error": "permission_denied"}
    account_id = int(session["account_id"])
    channel = normalize_channel(session["channel"])
    db = await get_db()
    try:
        if not await _scope_exists(db, account_id, channel):
            return {"ok": False, "error": "scope_not_found"}
    finally:
        await db.close()
    from app.soundboard_library import stop_playback
    result = await stop_playback(
        account_id=account_id, channel=channel, source="moderator_console",
    )
    await _audit(
        "moderator_sound_stop",
        f"account={account_id} channel={channel} user_id={session['twitch_user_id']} result=accepted",
    )
    return result


def reset_runtime_state() -> None:
    _runtime_last.clear()
    _runtime_window.clear()


async def _request_session(authorization: str = Header(default="")) -> dict[str, Any]:
    token = authorization[7:] if authorization.lower().startswith("bearer ") else ""
    session = await authenticate_session(token, "play_sound")
    if not session:
        raise HTTPException(status_code=401, detail="unauthorized")
    return session


@admin_router.put("/accounts/{account_id}/channels/{channel}/tracks/{track_id}")
async def api_save_sound_approval(account_id: int, channel: str, track_id: int, data: dict) -> dict[str, Any]:
    return await save_sound_approval(account_id, channel, track_id, enabled=data.get("enabled") is True)


@admin_router.put("/accounts/{account_id}/channels/{channel}/policy")
async def api_save_sound_policy(account_id: int, channel: str, data: dict) -> dict[str, Any]:
    return await save_sound_policy(account_id, channel, data)


@admin_router.post("/accounts/{account_id}/channels/{channel}/obs-token")
async def api_rotate_sound_obs_token(account_id: int, channel: str) -> dict[str, Any]:
    result = await rotate_obs_token(account_id, channel)
    if not result["ok"]:
        raise HTTPException(404, result["error"])
    return result


@admin_router.get("/accounts/{account_id}/channels/{channel}")
async def api_sound_admin_state(account_id: int, channel: str) -> dict[str, Any]:
    channel = normalize_channel(channel)
    db = await get_db()
    try:
        await ensure_schema(db)
        if not await _scope_exists(db, account_id, channel):
            raise HTTPException(404, "scope_not_found")
        tracks = await (await db.execute(
            "SELECT t.id,t.name,t.mime,COALESCE(a.enabled,0) AS approved FROM soundboard_tracks t LEFT JOIN moderator_console_sound_approvals a ON a.track_id=t.id AND a.account_id=? AND a.channel=? ORDER BY t.name COLLATE NOCASE,t.id",
            (account_id, channel),
        )).fetchall()
        policy = await (await db.execute("SELECT enabled,cooldown_sec,max_per_minute,obs_token_hash FROM moderator_console_sound_policy WHERE account_id=? AND channel=?", (account_id, channel))).fetchone()
    finally:
        await db.close()
    policy_data = dict(policy) if policy else {"enabled": 1, "cooldown_sec": 5, "max_per_minute": 5, "obs_token_hash": ""}
    configured = bool(policy_data.pop("obs_token_hash", ""))
    return {"ok": True, "tracks": [dict(row) for row in tracks], "policy": policy_data, "obs_configured": configured, "widget_url": ""}


@public_router.get("")
async def api_list_approved_sounds(session: dict[str, Any] = Depends(_request_session)) -> dict[str, Any]:
    return await list_approved_sounds(session)


@public_router.post("/play")
async def api_play_moderator_sound(data: dict, session: dict[str, Any] = Depends(_request_session)) -> dict[str, Any]:
    result = await play_moderator_sound(session, data)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@public_router.post("/stop")
async def api_stop_moderator_sound(session: dict[str, Any] = Depends(_request_session)) -> dict[str, Any]:
    result = await stop_moderator_sound(session)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@public_router.put("/favorites")
async def api_save_sound_favorites(data: dict, session: dict[str, Any] = Depends(_request_session)) -> dict[str, Any]:
    try:
        ids = sorted({int(value) for value in (data.get("track_ids") or []) if int(value) > 0})[:100]
    except (TypeError, ValueError):
        raise HTTPException(400, "invalid_favorites") from None
    account_id, channel, user_id = session["account_id"], normalize_channel(session["channel"]), session["twitch_user_id"]
    db = await get_db()
    try:
        await ensure_schema(db)
        rows = []
        if ids:
            marks = ",".join("?" for _ in ids)
            rows = await (await db.execute(
                f"SELECT track_id FROM moderator_console_sound_approvals WHERE account_id=? AND channel=? AND enabled=1 AND track_id IN ({marks})",
                (account_id, channel, *ids),
            )).fetchall()
        if {int(row["track_id"]) for row in rows} != set(ids):
            raise HTTPException(400, "invalid_favorites")
        await db.execute("DELETE FROM moderator_console_sound_favorites WHERE account_id=? AND channel=? AND twitch_user_id=?", (account_id, channel, user_id))
        await db.executemany(
            "INSERT INTO moderator_console_sound_favorites(account_id,channel,twitch_user_id,track_id) VALUES(?,?,?,?)",
            [(account_id, channel, user_id, track_id) for track_id in ids],
        )
        await db.commit()
    finally:
        await db.close()
    return {"ok": True, "track_ids": ids}


@public_router.get("/{track_id}/preview")
async def api_sound_preview(track_id: int, session: dict[str, Any] = Depends(_request_session)) -> FileResponse:
    from app.runtime_paths import SOUNDBOARD_DIR
    db = await get_db()
    try:
        row = await (await db.execute(
            "SELECT t.filename,t.mime FROM moderator_console_sound_approvals a JOIN soundboard_tracks t ON t.id=a.track_id WHERE a.account_id=? AND a.channel=? AND a.track_id=? AND a.enabled=1",
            (session["account_id"], normalize_channel(session["channel"]), track_id),
        )).fetchone()
    finally:
        await db.close()
    path = (SOUNDBOARD_DIR / row["filename"]) if row and Path(row["filename"]).name == row["filename"] else None
    if not path or not path.is_file():
        raise HTTPException(404, "track_not_found")
    return FileResponse(path, media_type=row["mime"], headers={"Cache-Control": "no-store"})
