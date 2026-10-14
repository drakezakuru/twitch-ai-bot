"""Validated storage helpers for the legacy-compatible Soundboard library."""

from __future__ import annotations

import os
import re
import secrets
import tempfile
import time
from pathlib import Path
from typing import Any

from app.database import get_db
from app.runtime_paths import LEGACY_SOUNDBOARD_DIR, SOUNDBOARD_DIR

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_BATCH_BYTES = 50 * 1024 * 1024
MAX_BATCH_FILES = 20
_last_played: dict[tuple[int, int, str], float] = {}
_AUDIO_SUFFIXES = {".mp3", ".ogg", ".wav", ".webm"}
_ARTIFACT_NAME_RE = re.compile(r"^[0-9a-f]{32}\.(?:mp3|ogg|wav|webm)$")


async def _broadcast(event: dict[str, Any]) -> None:
    from app.server import broadcast_log
    await broadcast_log(event)


async def ensure_schema(db: Any) -> None:
    columns = {
        row["name"] for row in await (await db.execute("PRAGMA table_info(soundboard_tracks)" )).fetchall()
    }
    additions = {
        "volume": "REAL NOT NULL DEFAULT 1.0",
        "cooldown_sec": "INTEGER NOT NULL DEFAULT 0",
        "sort_order": "INTEGER NOT NULL DEFAULT 0",
        "hotkey": "TEXT NOT NULL DEFAULT ''",
    }
    for name, definition in additions.items():
        if name not in columns:
            await db.execute(f"ALTER TABLE soundboard_tracks ADD COLUMN {name} {definition}")
    await db.commit()
    migrate_legacy_artifacts()


def _safe_filename(value: Any) -> str | None:
    filename = str(value or "")
    if (
        not filename
        or filename != Path(filename).name
        or "/" in filename
        or "\\" in filename
        or filename.startswith(".")
    ):
        return None
    return filename


def track_file_path(filename: Any) -> Path | None:
    """Prefer migrated media while preserving readable legacy Soundboard files."""
    safe_name = _safe_filename(filename)
    if not safe_name:
        return None
    for directory in (SOUNDBOARD_DIR, LEGACY_SOUNDBOARD_DIR):
        candidate = directory / safe_name
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    return None


def migrate_legacy_artifacts() -> list[str]:
    """Atomically move recognized legacy artifacts without changing SQLite references."""
    if not LEGACY_SOUNDBOARD_DIR.is_dir():
        return []
    SOUNDBOARD_DIR.mkdir(parents=True, exist_ok=True)
    migrated: list[str] = []
    for source in LEGACY_SOUNDBOARD_DIR.iterdir():
        filename = _safe_filename(source.name)
        if not filename or source.suffix.lower() not in _AUDIO_SUFFIXES or not source.is_file() or source.is_symlink():
            continue
        target = SOUNDBOARD_DIR / filename
        if target.exists():
            continue
        try:
            os.replace(source, target)
        except OSError:
            continue
        migrated.append(filename)
    return migrated


async def cleanup_orphaned_artifacts(*, grace_seconds: float) -> list[str]:
    """Delete only aged, generated artifacts with no durable track reference."""
    db = await get_db()
    try:
        rows = await (await db.execute("SELECT filename FROM soundboard_tracks")).fetchall()
    finally:
        await db.close()
    referenced = {_safe_filename(row["filename"]) for row in rows}
    cutoff = time.time() - max(0, grace_seconds)
    deleted: list[str] = []
    for directory in (SOUNDBOARD_DIR, LEGACY_SOUNDBOARD_DIR):
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if (
                path.name in referenced
                or not _ARTIFACT_NAME_RE.fullmatch(path.name)
                or not path.is_file()
                or path.is_symlink()
                or path.stat().st_mtime > cutoff
            ):
                continue
            path.unlink()
            deleted.append(path.name)
    return deleted


def detect_audio(data: bytes) -> tuple[str, str] | None:
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "audio/wav", ".wav"
    if data.startswith(b"OggS"):
        return "audio/ogg", ".ogg"
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return "audio/webm", ".webm"
    if data.startswith(b"ID3") or (
        len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE6 == 0xE2
    ):
        return "audio/mpeg", ".mp3"
    return None


def display_name(value: Any) -> str:
    name = Path(str(value or "track").replace("\x00", "")).name.strip()
    return (name or "track")[:120]


async def _read_upload(upload: Any) -> tuple[bytes, str]:
    data = await upload.read(MAX_FILE_BYTES + 1)
    if not data:
        raise ValueError("empty_audio")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("audio_too_large")
    return data, display_name(getattr(upload, "filename", "track"))


async def store_uploads(uploads: list[Any]) -> dict[str, Any]:
    if not uploads:
        raise ValueError("file_required")
    if len(uploads) > MAX_BATCH_FILES:
        raise ValueError("too_many_files")

    prepared: list[tuple[bytes, str, str, str] | tuple[None, str, str, str]] = []
    total = 0
    for upload in uploads:
        name = display_name(getattr(upload, "filename", "track"))
        try:
            data, name = await _read_upload(upload)
            total += len(data)
            detected = detect_audio(data)
            if not detected:
                raise ValueError("unsupported_audio")
            mime, suffix = detected
            prepared.append((data, name, mime, suffix))
        except ValueError as exc:
            prepared.append((None, name, str(exc), ""))
    if total > MAX_BATCH_BYTES:
        raise ValueError("batch_too_large")

    SOUNDBOARD_DIR.mkdir(parents=True, exist_ok=True)
    migrate_legacy_artifacts()
    results: list[dict[str, Any]] = []
    for data, name, mime, suffix in prepared:
        if data is None:
            results.append({"ok": False, "name": name, "error": mime})
            continue
        filename = secrets.token_hex(16) + suffix
        target = SOUNDBOARD_DIR / filename
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=SOUNDBOARD_DIR, prefix=".upload-", delete=False) as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
                temporary = Path(handle.name)
            os.replace(temporary, target)
            temporary = None
            db = await get_db()
            try:
                await ensure_schema(db)
                cursor = await db.execute(
                    "INSERT INTO soundboard_tracks(name,filename,mime) VALUES(?,?,?)",
                    (name, filename, mime),
                )
                await db.commit()
                track_id = int(cursor.lastrowid)
            finally:
                await db.close()
        except Exception:
            if temporary:
                temporary.unlink(missing_ok=True)
            target.unlink(missing_ok=True)
            results.append({"ok": False, "name": name, "error": "storage_failed"})
            continue
        results.append({"ok": True, "id": track_id, "name": name, "mime": mime})

    accepted = sum(item["ok"] for item in results)
    response: dict[str, Any] = {
        "ok": accepted > 0,
        "items": results,
        "accepted": accepted,
        "rejected": len(results) - accepted,
    }
    if len(results) == 1 and results[0]["ok"]:
        response["id"] = results[0]["id"]
    return response


async def list_tracks() -> list[dict[str, Any]]:
    db = await get_db()
    try:
        await ensure_schema(db)
        rows = await (await db.execute(
            "SELECT id,name,mime,volume,cooldown_sec,sort_order,hotkey,created_at "
            "FROM soundboard_tracks ORDER BY sort_order,name COLLATE NOCASE,id"
        )).fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def get_track_by_hotkey(hotkey: str) -> dict[str, Any] | None:
    clean_key = str(hotkey or "").strip().lower()
    if not clean_key:
        return None
    db = await get_db()
    try:
        await ensure_schema(db)
        row = await (await db.execute(
            "SELECT id,name,mime,volume,cooldown_sec,sort_order,hotkey,created_at "
            "FROM soundboard_tracks WHERE LOWER(hotkey)=? LIMIT 1",
            (clean_key,),
        )).fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def update_track(track_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    name = display_name(payload.get("name"))
    if not str(payload.get("name") or "").strip():
        raise ValueError("track_name_required")
    try:
        volume = max(0.0, min(2.0, float(payload.get("volume", 1))))
        cooldown = max(0, min(600, int(payload.get("cooldown_sec", 0))))
        order = max(-10000, min(10000, int(payload.get("sort_order", 0))))
        hotkey = str(payload.get("hotkey", "") or "").strip().lower()[:32]
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_track_settings") from exc
    db = await get_db()
    try:
        await ensure_schema(db)
        if "hotkey" in payload:
            cursor = await db.execute(
                "UPDATE soundboard_tracks SET name=?,volume=?,cooldown_sec=?,sort_order=?,hotkey=? WHERE id=?",
                (name, volume, cooldown, order, hotkey, track_id),
            )
        else:
            cursor = await db.execute(
                "UPDATE soundboard_tracks SET name=?,volume=?,cooldown_sec=?,sort_order=? WHERE id=?",
                (name, volume, cooldown, order, track_id),
            )
        if not cursor.rowcount:
            raise ValueError("track_not_found")
        await db.commit()
    finally:
        await db.close()
    res = {
        "ok": True,
        "id": track_id,
        "name": name,
        "volume": volume,
        "cooldown_sec": cooldown,
        "sort_order": order,
    }
    if "hotkey" in payload:
        res["hotkey"] = hotkey
    return res


async def delete_track(track_id: int) -> dict[str, Any]:
    db = await get_db()
    staged: Path | None = None
    source: Path | None = None
    try:
        await ensure_schema(db)
        row = await (await db.execute(
            "SELECT filename FROM soundboard_tracks WHERE id=?", (track_id,)
        )).fetchone()
        if not row:
            raise ValueError("track_not_found")
        if _safe_filename(row["filename"]) is None:
            raise ValueError("invalid_track_path")
        source = track_file_path(row["filename"])
        if source is not None:
            staged = source.parent / f".delete-{secrets.token_hex(16)}"
            os.replace(source, staged)
        await db.execute("BEGIN")
        await db.execute("DELETE FROM moderator_console_sound_favorites WHERE track_id=?", (track_id,))
        await db.execute("DELETE FROM moderator_console_sound_approvals WHERE track_id=?", (track_id,))
        await db.execute("DELETE FROM soundboard_tracks WHERE id=?", (track_id,))
        await db.commit()
    except Exception:
        await db.rollback()
        if staged and source and staged.exists():
            os.replace(staged, source)
        raise
    finally:
        await db.close()
    if staged:
        staged.unlink(missing_ok=True)
    return {"ok": True, "id": track_id}


async def play_track(
    track_id: int, *, account_id: int, channel: str, source: str = "owner_panel",
) -> dict[str, Any]:
    channel = str(channel or "").strip().lower().lstrip("#")
    if account_id <= 0 or not channel:
        raise ValueError("widget_scope_required")
    db = await get_db()
    try:
        await ensure_schema(db)
        row = await (await db.execute(
            "SELECT filename,volume,cooldown_sec FROM soundboard_tracks WHERE id=?", (track_id,)
        )).fetchone()
    finally:
        await db.close()
    if not row:
        raise ValueError("track_not_found")
    if track_file_path(row["filename"]) is None:
        raise ValueError("track_file_missing")
    key = (track_id, int(account_id), str(channel))
    now = time.monotonic()
    if now - _last_played.get(key, 0.0) < int(row["cooldown_sec"]):
        raise ValueError("track_cooldown")
    _last_played[key] = now
    event = {
        "type": "soundboard", "kind": "play", "track_id": track_id,
        "volume": float(row["volume"]), "source": source, "at": time.time(),
    }
    event.update({"account_id": int(account_id), "channel": channel})
    await _broadcast(event)

    try:
        from app.widget_bus import duck_start, request_pause_media
        await duck_start(source="soundboard", channel=channel, reason=f"soundboard:{track_id}", duration_ms=8000)
        await request_pause_media(source="soundboard", channel=channel, reason=f"soundboard:{track_id}")
    except Exception:
        pass

    return {"ok": True, "track_id": track_id, "volume": float(row["volume"])}


async def stop_playback(*, account_id: int, channel: str, source: str = "owner_panel") -> dict[str, Any]:
    channel = str(channel or "").strip().lower().lstrip("#")
    if account_id <= 0 or not channel:
        raise ValueError("widget_scope_required")
    event = {"type": "soundboard", "kind": "stop", "source": source, "at": time.time()}
    event.update({"account_id": int(account_id), "channel": channel})
    await _broadcast(event)

    try:
        from app.widget_bus import duck_end, request_resume_media
        await duck_end(source="soundboard", channel=channel)
        await request_resume_media(source="soundboard", channel=channel)
    except Exception:
        pass

    return {"ok": True, "status": "accepted", "telemetry": "unverified"}


async def finish_playback(*, account_id: int, channel: str) -> dict[str, Any]:
    channel = str(channel or "").strip().lower().lstrip("#")
    if account_id <= 0 or not channel:
        raise ValueError("widget_scope_required")
    try:
        from app.widget_bus import duck_end, request_resume_media
        await duck_end(source="soundboard", channel=channel)
        await request_resume_media(source="soundboard", channel=channel)
    except Exception:
        pass
    return {"ok": True, "status": "finished"}


def reset_runtime_state() -> None:
    _last_played.clear()

