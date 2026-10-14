"""Track 6.6: exact-scoped, owner-approved media cues for OBS."""

from __future__ import annotations

import hashlib
import io
import json
import secrets
import subprocess
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageSequence

from app.database import _add_column_if_missing, get_db
from app.moderator_console_routes import _owner_auth_dependency, _request_session
from app.runtime_paths import MODERATOR_MEDIA_ROOT
from app.security import require_loopback_client, require_same_origin_request
from app.tts_voice_policy import normalize_channel

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_VIDEO_BYTES = 20 * 1024 * 1024
MAX_DURATION_MS = 15_000
COOLDOWN_SECONDS = 2
MAX_PER_MINUTE = 20
ALLOWED_IMAGES = {"GIF": ("image/gif", ".gif"), "WEBP": ("image/webp", ".webp"), "PNG": ("image/png", ".png")}
ALLOWED_VIDEOS = {"mp4": ("video/mp4", ".mp4"), "webm": ("video/webm", ".webm")}
IDEMPOTENCY_MIN = 8

admin_router = APIRouter(prefix="/api/moderator-media/admin", dependencies=[Depends(_owner_auth_dependency)])
moderator_router = APIRouter(prefix="/api/moderator-media", tags=["moderator-media"])
public_router = APIRouter(tags=["moderator-media"])
templates = Jinja2Templates(directory="templates")


async def ensure_schema(db=None) -> None:
    own = db is None
    db = db or await get_db()
    try:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS moderator_media_library (
                id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER NOT NULL, channel TEXT NOT NULL,
                name TEXT NOT NULL, filename TEXT NOT NULL, mime TEXT NOT NULL, media_kind TEXT NOT NULL,
                width INTEGER NOT NULL DEFAULT 0, height INTEGER NOT NULL DEFAULT 0, duration_ms INTEGER NOT NULL DEFAULT 0,
                approved INTEGER NOT NULL DEFAULT 0, created_by TEXT NOT NULL DEFAULT 'owner', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(account_id, channel, filename), FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS moderator_media_commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER NOT NULL, channel TEXT NOT NULL,
                media_id INTEGER NOT NULL, twitch_user_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued', reason TEXT NOT NULL DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(account_id, channel, twitch_user_id, idempotency_key),
                FOREIGN KEY(media_id) REFERENCES moderator_media_library(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS moderator_media_state (
                account_id INTEGER NOT NULL, channel TEXT NOT NULL, obs_token_hash TEXT NOT NULL DEFAULT '',
                obs_token TEXT NOT NULL DEFAULT '',
                kill_switch INTEGER NOT NULL DEFAULT 0, queue_policy TEXT NOT NULL DEFAULT 'queue',
                position_json TEXT NOT NULL DEFAULT '{"position":"center","width_pct":35,"duration_ms":5000,"fade_ms":250}',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(account_id, channel),
                FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS moderator_media_favorites (
                account_id INTEGER NOT NULL, channel TEXT NOT NULL, twitch_user_id TEXT NOT NULL,
                media_id INTEGER NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(account_id, channel, twitch_user_id, media_id),
                FOREIGN KEY(media_id) REFERENCES moderator_media_library(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_moderator_media_queue ON moderator_media_commands(account_id, channel, status, id);
        """)
        await _add_column_if_missing(db, "moderator_media_state", "obs_token", "TEXT NOT NULL DEFAULT ''")
        await db.commit()
    finally:
        if own:
            await db.close()


async def _audit(action: str, detail: str) -> None:
    from app.routes import log_action
    await log_action(action, detail)


async def _scope_exists(db, account_id: int, channel: str) -> bool:
    row = await (await db.execute("SELECT 1 FROM channels WHERE account_id=? AND lower(ltrim(channel_name, '#'))=? AND enabled=1", (account_id, channel))).fetchone()
    return row is not None


def _storage_dir(account_id: int, channel: str) -> Path:
    # Keep user-provided channel text out of filesystem path components.
    scope_key = hashlib.sha256(channel.encode("utf-8")).hexdigest()[:32]
    return MODERATOR_MEDIA_ROOT / str(int(account_id)) / scope_key


def _media_path(account_id: int, channel: str, filename: str) -> Path | None:
    root = _storage_dir(account_id, channel).resolve()
    if Path(filename).name != filename:
        return None
    path = (root / filename).resolve()
    return path if path.parent == root else None


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def _valid_obs_token(account_id: int, channel: str, token: str) -> bool:
    if not token:
        return False
    db = await get_db()
    try:
        await ensure_schema(db)
        row = await (await db.execute("SELECT obs_token_hash,obs_token FROM moderator_media_state WHERE account_id=? AND channel=?", (account_id, channel))).fetchone()
        if not row:
            return False
        if row["obs_token"]:
            return secrets.compare_digest(row["obs_token"], token)
        return bool(row["obs_token_hash"] and secrets.compare_digest(row["obs_token_hash"], _hash(token)))
    finally:
        await db.close()


def _image_metadata(data: bytes) -> tuple[str, str, int, int, int]:
    with Image.open(io.BytesIO(data)) as image:
        image.verify()
    with Image.open(io.BytesIO(data)) as image:
        fmt = str(image.format or "").upper()
        if fmt not in ALLOWED_IMAGES:
            raise ValueError("unsupported_media")
        width, height = image.size
        if not width or not height or width > 3840 or height > 2160:
            raise ValueError("invalid_dimensions")
        duration = sum(int(frame.info.get("duration", 0)) for frame in ImageSequence.Iterator(image))
    mime, extension = ALLOWED_IMAGES[fmt]
    if duration > MAX_DURATION_MS:
        raise ValueError("duration_exceeded")
    return mime, extension, width, height, duration


def _video_metadata(path: Path, data: bytes) -> tuple[str, str, int]:
    kind = "mp4" if len(data) >= 12 and data[4:8] == b"ftyp" else "webm" if data.startswith(b"\x1a\x45\xdf\xa3") else ""
    if kind not in ALLOWED_VIDEOS:
        raise ValueError("unsupported_media")
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=5, check=True,
        )
        duration = int(float(probe.stdout.strip()) * 1000)
    except (OSError, subprocess.SubprocessError, ValueError):
        raise ValueError("invalid_video") from None
    if duration <= 0 or duration > MAX_DURATION_MS:
        raise ValueError("duration_exceeded")
    mime, extension = ALLOWED_VIDEOS[kind]
    return mime, extension, duration


async def add_media(account_id: int, channel: str, upload, actor: str, approved: bool) -> dict[str, Any]:
    channel = normalize_channel(channel)
    if not channel:
        return {"ok": False, "error": "scope_not_found"}
    data = await upload.read(MAX_VIDEO_BYTES + 1)
    if not data or len(data) > MAX_VIDEO_BYTES:
        return {"ok": False, "error": "invalid_media_size"}
    db = await get_db()
    target: Path | None = None
    try:
        await ensure_schema(db)
        if not await _scope_exists(db, account_id, channel):
            return {"ok": False, "error": "scope_not_found"}
        try:
            mime, ext, width, height, duration = _image_metadata(data)
            if len(data) > MAX_IMAGE_BYTES:
                return {"ok": False, "error": "invalid_media_size"}
            kind = "image"
        except Exception as image_error:
            image_reason = str(image_error) if str(image_error) in {"unsupported_media", "invalid_dimensions", "duration_exceeded"} else ""
            target = _storage_dir(account_id, channel) / (secrets.token_hex(20) + ".upload")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            try:
                mime, ext, duration = _video_metadata(target, data)
                width = height = 0
                kind = "video"
            except ValueError as video_error:
                target.unlink(missing_ok=True)
                return {"ok": False, "error": image_reason or str(video_error)}
        filename = secrets.token_hex(20) + ext
        final = _storage_dir(account_id, channel) / filename
        final.parent.mkdir(parents=True, exist_ok=True)
        if target:
            target.replace(final)
        else:
            final.write_bytes(data)
        cur = await db.execute(
            "INSERT INTO moderator_media_library(account_id,channel,name,filename,mime,media_kind,width,height,duration_ms,approved,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (account_id, channel, str(getattr(upload, "filename", "media"))[:120] or "media", filename, mime, kind, width, height, duration, int(approved), actor[:64]),
        )
        await db.commit()
        item = {"id": cur.lastrowid, "name": str(getattr(upload, "filename", "media"))[:120], "mime": mime, "media_kind": kind, "approved": bool(approved), "duration_ms": duration}
    finally:
        await db.close()
    await _audit("moderator_media_upload", f"account={account_id} channel={channel} actor={actor[:64]} media_id={item['id']} approved={int(approved)}")
    return {"ok": True, "item": item}


async def enqueue_media(session: dict[str, Any], media_id: int, idempotency_key: str) -> dict[str, Any]:
    if "play_media" not in session["permissions"]:
        await _audit("moderator_media_play", f"user_id={session['twitch_user_id']} result=permission_denied")
        return {"ok": False, "error": "permission_denied"}
    if len(idempotency_key) < IDEMPOTENCY_MIN or len(idempotency_key) > 100:
        return {"ok": False, "error": "idempotency_required"}
    db = await get_db()
    try:
        await ensure_schema(db)
        await db.execute("BEGIN IMMEDIATE")
        existing = await (await db.execute(
            "SELECT id,status,reason FROM moderator_media_commands WHERE account_id=? AND channel=? AND twitch_user_id=? AND idempotency_key=?",
            (session["account_id"], session["channel"], session["twitch_user_id"], idempotency_key),
        )).fetchone()
        state = await (await db.execute("SELECT kill_switch,queue_policy FROM moderator_media_state WHERE account_id=? AND channel=?", (session["account_id"], session["channel"]))).fetchone()
        if existing:
            result = {"ok": True, "command_id": existing["id"], "status": existing["status"], "idempotent": True, "reason": existing["reason"]}
        elif state and state["kill_switch"]:
            result = {"ok": False, "error": "kill_switch_enabled"}
        else:
            media = await (await db.execute("SELECT id FROM moderator_media_library WHERE id=? AND account_id=? AND channel=? AND approved=1", (media_id, session["account_id"], session["channel"]))).fetchone()
            if not media:
                result = {"ok": False, "error": "media_not_approved"}
            else:
                recent = await (await db.execute("SELECT count(*) AS c FROM moderator_media_commands WHERE account_id=? AND channel=? AND twitch_user_id=? AND created_at >= datetime('now','-1 minute')", (session["account_id"], session["channel"], session["twitch_user_id"]))).fetchone()
                last = await (await db.execute("SELECT created_at FROM moderator_media_commands WHERE account_id=? AND channel=? AND twitch_user_id=? ORDER BY id DESC LIMIT 1", (session["account_id"], session["channel"], session["twitch_user_id"]))).fetchone()
                if recent["c"] >= MAX_PER_MINUTE:
                    result = {"ok": False, "error": "rate_limit"}
                elif last and (await (await db.execute("SELECT (julianday('now')-julianday(?))*86400 AS age", (last["created_at"],))).fetchone())["age"] < COOLDOWN_SECONDS:
                    result = {"ok": False, "error": "cooldown"}
                else:
                    if state and state["queue_policy"] == "replace":
                        await db.execute("UPDATE moderator_media_commands SET status='cleared',reason='replaced',updated_at=CURRENT_TIMESTAMP WHERE account_id=? AND channel=? AND status='queued'", (session["account_id"], session["channel"]))
                    cur = await db.execute("INSERT OR IGNORE INTO moderator_media_commands(account_id,channel,media_id,twitch_user_id,idempotency_key) VALUES(?,?,?,?,?)", (session["account_id"], session["channel"], media_id, session["twitch_user_id"], idempotency_key))
                    result = {"ok": True, "command_id": cur.lastrowid, "status": "queued"}
        await db.commit()
    finally:
        await db.close()
    await _audit("moderator_media_play", f"account={session['account_id']} channel={session['channel']} user_id={session['twitch_user_id']} media_id={media_id} result={result.get('error', result.get('status'))}")
    return result


async def _state(account_id: int, channel: str) -> dict[str, Any]:
    db = await get_db()
    try:
        await ensure_schema(db)
        state = await (await db.execute("SELECT kill_switch,queue_policy,position_json FROM moderator_media_state WHERE account_id=? AND channel=?", (account_id, channel))).fetchone()
        command = None if state and state["kill_switch"] else await (await db.execute("SELECT c.id AS command_id,m.id AS media_id,m.name,m.mime,m.media_kind,m.duration_ms FROM moderator_media_commands c JOIN moderator_media_library m ON m.id=c.media_id WHERE c.account_id=? AND c.channel=? AND c.status='queued' ORDER BY c.id LIMIT 1", (account_id, channel))).fetchone()
        try:
            position = json.loads(state["position_json"]) if state else {}
        except ValueError:
            position = {}
        return {"ok": True, "account_id": account_id, "channel": channel, "kill_switch": bool(state and state["kill_switch"]), "position": position, "cue": dict(command) if command else None}
    finally:
        await db.close()


def _obs_widget_url(account_id: int, channel: str, token: str) -> str:
    return f"/widget/moderator-media?account_id={account_id}&channel={channel}&token={token}"


@admin_router.get("/preview", response_class=HTMLResponse)
async def owner_safe_preview(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="obs_moderator_media.html", context={"preview": True})


@admin_router.get("/{account_id}/{channel}/token")
async def obs_token_status(account_id: int, channel: str) -> dict[str, Any]:
    channel = normalize_channel(channel)
    db = await get_db()
    try:
        await ensure_schema(db)
        if not await _scope_exists(db, account_id, channel):
            raise HTTPException(404, "scope_not_found")
        row = await (await db.execute(
            "SELECT obs_token_hash,obs_token FROM moderator_media_state WHERE account_id=? AND channel=?",
            (account_id, channel),
        )).fetchone()
    finally:
        await db.close()
    configured = bool(row and (row["obs_token"] or row["obs_token_hash"]))
    reveal_available = bool(row and row["obs_token"])
    return {
        "ok": True,
        "configured": configured,
        "reveal_available": reveal_available,
        "rotation_required": configured and not reveal_available,
        "masked_token": "••••••••" if configured else "",
    }


@admin_router.post("/{account_id}/{channel}/token")
async def rotate_obs_token(request: Request, account_id: int, channel: str) -> dict[str, Any]:
    require_loopback_client(request)
    require_same_origin_request(request)
    channel = normalize_channel(channel); token = secrets.token_urlsafe(32)
    db = await get_db()
    try:
        await ensure_schema(db)
        if not await _scope_exists(db, account_id, channel): raise HTTPException(404, "scope_not_found")
        await db.execute("INSERT INTO moderator_media_state(account_id,channel,obs_token_hash,obs_token) VALUES(?,?,?,?) ON CONFLICT(account_id,channel) DO UPDATE SET obs_token_hash=excluded.obs_token_hash,obs_token=excluded.obs_token,updated_at=CURRENT_TIMESTAMP", (account_id, channel, _hash(token), token))
        await db.commit()
    finally: await db.close()
    await _audit("moderator_media_obs_token_rotate", f"account={account_id} channel={channel}")
    return {"ok": True, "token": token, "url": _obs_widget_url(account_id, channel, token)}


@admin_router.post("/{account_id}/{channel}/token/reveal")
async def reveal_obs_token(request: Request, account_id: int, channel: str) -> dict[str, Any]:
    require_loopback_client(request)
    require_same_origin_request(request)
    channel = normalize_channel(channel)
    db = await get_db()
    try:
        await ensure_schema(db)
        if not await _scope_exists(db, account_id, channel):
            raise HTTPException(404, "scope_not_found")
        row = await (await db.execute(
            "SELECT obs_token_hash,obs_token FROM moderator_media_state WHERE account_id=? AND channel=?",
            (account_id, channel),
        )).fetchone()
    finally:
        await db.close()
    if not row or not (row["obs_token"] or row["obs_token_hash"]):
        raise HTTPException(404, "obs_token_not_configured")
    if not row["obs_token"]:
        raise HTTPException(409, "obs_token_rotation_required")
    await _audit("moderator_media_obs_token_reveal", f"account={account_id} channel={channel}")
    return {"ok": True, "token": row["obs_token"], "url": _obs_widget_url(account_id, channel, row["obs_token"])}


@admin_router.get("/{account_id}/{channel}/library")
async def owner_library(account_id: int, channel: str) -> dict[str, Any]:
    channel = normalize_channel(channel); db = await get_db()
    try:
        await ensure_schema(db)
        rows = await (await db.execute("SELECT id,name,mime,media_kind,width,height,duration_ms,approved,created_by,created_at FROM moderator_media_library WHERE account_id=? AND channel=? ORDER BY id DESC", (account_id, channel))).fetchall()
        return {"ok": True, "items": [dict(row) for row in rows]}
    finally: await db.close()


@admin_router.post("/{account_id}/{channel}/library")
async def owner_upload(account_id: int, channel: str, request: Request) -> dict[str, Any]:
    upload = (await request.form()).get("file")
    if not upload: raise HTTPException(400, "file_required")
    result = await add_media(account_id, channel, upload, "owner", True)
    if not result["ok"]: raise HTTPException(400 if result["error"] != "scope_not_found" else 404, result["error"])
    return result


@admin_router.put("/{account_id}/{channel}/library/{media_id}")
async def approve_media(account_id: int, channel: str, media_id: int, data: dict) -> dict[str, Any]:
    channel = normalize_channel(channel); approved = 1 if data.get("approved") is True else 0; db = await get_db()
    try:
        await ensure_schema(db); cur = await db.execute("UPDATE moderator_media_library SET approved=? WHERE id=? AND account_id=? AND channel=?", (approved, media_id, account_id, channel)); await db.commit()
    finally: await db.close()
    if not cur.rowcount: raise HTTPException(404, "media_not_found")
    await _audit("moderator_media_approval", f"account={account_id} channel={channel} media_id={media_id} approved={approved}")
    return {"ok": True, "approved": bool(approved)}


@admin_router.put("/{account_id}/{channel}/config")
async def owner_config(account_id: int, channel: str, data: dict) -> dict[str, Any]:
    channel = normalize_channel(channel)
    policy = str(data.get("queue_policy") or "queue")
    position = str(data.get("position") or "center")
    try:
        width = max(5, min(100, int(data.get("width_pct", 35))))
        duration = max(500, min(MAX_DURATION_MS, int(data.get("duration_ms", 5000))))
        fade = max(0, min(2000, int(data.get("fade_ms", 250))))
    except (TypeError, ValueError):
        raise HTTPException(400, "invalid_config") from None
    if policy not in {"queue", "replace"} or position not in {"center", "top", "bottom", "top-left", "top-right", "bottom-left", "bottom-right"}:
        raise HTTPException(400, "invalid_config")
    db = await get_db()
    try:
        await ensure_schema(db)
        if not await _scope_exists(db, account_id, channel):
            raise HTTPException(404, "scope_not_found")
        config = json.dumps({"position": position, "width_pct": width, "duration_ms": duration, "fade_ms": fade})
        await db.execute("INSERT INTO moderator_media_state(account_id,channel,queue_policy,position_json) VALUES(?,?,?,?) ON CONFLICT(account_id,channel) DO UPDATE SET queue_policy=excluded.queue_policy,position_json=excluded.position_json,updated_at=CURRENT_TIMESTAMP", (account_id, channel, policy, config))
        await db.commit()
    finally:
        await db.close()
    await _audit("moderator_media_config", f"account={account_id} channel={channel} queue_policy={policy}")
    return {"ok": True, "queue_policy": policy, "position": json.loads(config)}


@admin_router.post("/{account_id}/{channel}/control")
async def owner_control(account_id: int, channel: str, data: dict) -> dict[str, Any]:
    channel = normalize_channel(channel); action = str(data.get("action") or ""); db = await get_db()
    try:
        await ensure_schema(db)
        if not await _scope_exists(db, account_id, channel): raise HTTPException(404, "scope_not_found")
        if action == "stop":
            await db.execute("UPDATE moderator_media_commands SET status='stopped',reason='owner_stop',updated_at=CURRENT_TIMESTAMP WHERE account_id=? AND channel=? AND status IN ('queued','playing')", (account_id, channel))
        elif action == "clear":
            await db.execute("UPDATE moderator_media_commands SET status='cleared',reason='owner_clear',updated_at=CURRENT_TIMESTAMP WHERE account_id=? AND channel=? AND status='queued'", (account_id, channel))
        elif action == "kill_switch":
            enabled = 1 if data.get("enabled") is True else 0
            await db.execute("INSERT INTO moderator_media_state(account_id,channel,kill_switch) VALUES(?,?,?) ON CONFLICT(account_id,channel) DO UPDATE SET kill_switch=excluded.kill_switch,updated_at=CURRENT_TIMESTAMP", (account_id, channel, enabled))
            if enabled: await db.execute("UPDATE moderator_media_commands SET status='stopped',reason='kill_switch',updated_at=CURRENT_TIMESTAMP WHERE account_id=? AND channel=? AND status IN ('queued','playing')", (account_id, channel))
        else: raise HTTPException(400, "invalid_control")
        await db.commit()
    finally: await db.close()
    await _audit("moderator_media_control", f"account={account_id} channel={channel} action={action}")
    return {"ok": True, "state": await _state(account_id, channel)}


@moderator_router.post("/library")
async def moderator_upload(request: Request, session: dict[str, Any] = Depends(_request_session)) -> dict[str, Any]:
    if "upload_media" not in session["permissions"]: raise HTTPException(403, "permission_denied")
    upload = (await request.form()).get("file")
    if not upload: raise HTTPException(400, "file_required")
    result = await add_media(session["account_id"], session["channel"], upload, session["twitch_user_id"], False)
    if not result["ok"]: raise HTTPException(400, result["error"])
    return result


@moderator_router.get("/library")
async def moderator_library(session: dict[str, Any] = Depends(_request_session)) -> dict[str, Any]:
    if "play_media" not in session["permissions"]:
        raise HTTPException(403, "permission_denied")
    db = await get_db()
    try:
        await ensure_schema(db)
        rows = await (await db.execute(
            "SELECT m.id,m.name,m.mime,m.media_kind,m.duration_ms,"
            "EXISTS(SELECT 1 FROM moderator_media_favorites f WHERE f.account_id=m.account_id AND f.channel=m.channel AND f.twitch_user_id=? AND f.media_id=m.id) AS favorite "
            "FROM moderator_media_library m WHERE m.account_id=? AND m.channel=? AND m.approved=1 ORDER BY favorite DESC,m.name COLLATE NOCASE,m.id",
            (session["twitch_user_id"], session["account_id"], normalize_channel(session["channel"])),
        )).fetchall()
        return {"ok": True, "items": [dict(row) for row in rows]}
    finally:
        await db.close()


@moderator_router.put("/favorites")
async def moderator_media_favorites(data: dict, session: dict[str, Any] = Depends(_request_session)) -> dict[str, Any]:
    if "play_media" not in session["permissions"]:
        raise HTTPException(403, "permission_denied")
    try:
        ids = sorted({int(value) for value in (data.get("media_ids") or []) if int(value) > 0})[:100]
    except (TypeError, ValueError):
        raise HTTPException(400, "invalid_favorites") from None
    account_id, channel, user_id = session["account_id"], normalize_channel(session["channel"]), session["twitch_user_id"]
    db = await get_db()
    try:
        await ensure_schema(db)
        approved = set()
        if ids:
            marks = ",".join("?" for _ in ids)
            rows = await (await db.execute(
                f"SELECT id FROM moderator_media_library WHERE account_id=? AND channel=? AND approved=1 AND id IN ({marks})",
                (account_id, channel, *ids),
            )).fetchall()
            approved = {int(row["id"]) for row in rows}
        if approved != set(ids):
            raise HTTPException(400, "invalid_favorites")
        await db.execute("DELETE FROM moderator_media_favorites WHERE account_id=? AND channel=? AND twitch_user_id=?", (account_id, channel, user_id))
        await db.executemany(
            "INSERT INTO moderator_media_favorites(account_id,channel,twitch_user_id,media_id) VALUES(?,?,?,?)",
            [(account_id, channel, user_id, media_id) for media_id in ids],
        )
        await db.commit()
    finally:
        await db.close()
    return {"ok": True, "media_ids": ids}


@moderator_router.get("/library/{media_id}/preview")
async def moderator_media_preview(media_id: int, session: dict[str, Any] = Depends(_request_session)) -> FileResponse:
    if "play_media" not in session["permissions"]:
        raise HTTPException(403, "permission_denied")
    account_id, channel = session["account_id"], normalize_channel(session["channel"])
    db = await get_db()
    try:
        row = await (await db.execute(
            "SELECT filename,mime FROM moderator_media_library WHERE id=? AND account_id=? AND channel=? AND approved=1",
            (media_id, account_id, channel),
        )).fetchone()
    finally:
        await db.close()
    path = _media_path(account_id, channel, row["filename"]) if row else None
    if not path or not path.is_file():
        raise HTTPException(404, "media_not_found")
    return FileResponse(path, media_type=row["mime"], headers={"Cache-Control": "no-store"})


@moderator_router.post("/cues")
async def moderator_cue(data: dict, session: dict[str, Any] = Depends(_request_session)) -> dict[str, Any]:
    result = await enqueue_media(session, int(data.get("media_id") or 0), str(data.get("idempotency_key") or ""))
    if not result["ok"]: raise HTTPException(429 if result["error"] in {"cooldown", "rate_limit"} else 403, result["error"])
    return result


@public_router.get("/widget/moderator-media", response_class=HTMLResponse)
async def moderator_media_widget(request: Request, account_id: int, channel: str, token: str) -> HTMLResponse:
    channel = normalize_channel(channel)
    if not await _valid_obs_token(account_id, channel, token): raise HTTPException(403, "invalid_obs_token")
    return templates.TemplateResponse(request=request, name="obs_moderator_media.html", context={"preview": False})


@public_router.get("/api/moderator-media/public/state")
async def public_state(account_id: int, channel: str, token: str) -> dict[str, Any]:
    channel = normalize_channel(channel)
    if not await _valid_obs_token(account_id, channel, token): raise HTTPException(403, "invalid_obs_token")
    return await _state(account_id, channel)


@public_router.post("/api/moderator-media/public/complete")
async def complete_cue(data: dict) -> dict[str, Any]:
    account_id = int(data.get("account_id") or 0); channel = normalize_channel(data.get("channel")); token = str(data.get("token") or ""); command_id = int(data.get("command_id") or 0)
    if not await _valid_obs_token(account_id, channel, token): raise HTTPException(403, "invalid_obs_token")
    db = await get_db()
    try:
        await db.execute("UPDATE moderator_media_commands SET status='completed',updated_at=CURRENT_TIMESTAMP WHERE id=? AND account_id=? AND channel=? AND status='queued'", (command_id, account_id, channel)); await db.commit()
    finally: await db.close()
    return {"ok": True}


@public_router.get("/api/moderator-media/public/file/{media_id}")
async def public_file(media_id: int, account_id: int, channel: str, token: str) -> FileResponse:
    channel = normalize_channel(channel)
    if not await _valid_obs_token(account_id, channel, token): raise HTTPException(403, "invalid_obs_token")
    db = await get_db()
    try:
        row = await (await db.execute("SELECT filename,mime FROM moderator_media_library WHERE id=? AND account_id=? AND channel=? AND approved=1", (media_id, account_id, channel))).fetchone()
    finally: await db.close()
    path = _media_path(account_id, channel, row["filename"]) if row else None
    if not path or not path.is_file(): raise HTTPException(404, "media_not_found")
    return FileResponse(path, media_type=row["mime"], headers={"Cache-Control": "no-store"})
