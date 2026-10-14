"""MOD-10: upload quarantine — bounded processing, checksums, owner review later.

Uploads from moderators never go straight into the library: the file is hashed
and stored with status 'pending' (invisible to moderators until the owner
approves it in the local panel). Oversized uploads are refused before reading;
decoding/verification happens in a bounded pass with a hard byte budget.
"""
from __future__ import annotations

import hashlib
import secrets
from typing import Any

MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # bounded processor budget
CHUNK = 1024 * 1024

STATUS = {"pending", "approved", "rejected", "failed"}


async def ensure_schema(db: Any) -> None:
    await db.executescript("""
    CREATE TABLE IF NOT EXISTS ms_uploads (
      id TEXT PRIMARY KEY, account_id INTEGER NOT NULL, channel TEXT NOT NULL,
      kind TEXT NOT NULL CHECK (kind IN ('media','sound')),
      title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
      sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL,
      content_type TEXT NOT NULL DEFAULT '',
      uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      owner_reviewed_at TEXT, review_note TEXT NOT NULL DEFAULT '');
    CREATE INDEX IF NOT EXISTS ms_uploads_review
      ON ms_uploads(status, account_id, channel);
    """)


def _validate_header(data: bytes, content_type: str) -> str | None:
    """Bounded decode-guard: reject obvious decode bombs by magic bytes/size."""
    if len(data) > MAX_UPLOAD_BYTES:
        return "upload_too_large"
    if not data:
        return "upload_empty"
    if content_type == "image/png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "upload_malformed"
    if content_type in {"audio/mpeg", "audio/mp3"} and data[:3] != b"ID3" and data[:2] != b"\xff\xfb":
        return "upload_malformed"
    return None


async def store_upload(db: Any, storage_root: Any, *, account_id: int, channel: str,
                       kind: str, title: str, content_type: str, read_chunk: Any) -> dict[str, Any]:
    """Stream the upload through a bounded processor; nothing is trusted in advance."""
    if kind not in {"media", "sound"}:
        raise ValueError("invalid_kind")
    digest = hashlib.sha256()
    size = 0
    head = b""
    tmp_id = secrets.token_hex(16)
    target = storage_root / f"{tmp_id}.blob"
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "wb") as sink:
        while True:
            chunk = await read_chunk(CHUNK)
            if chunk is None or chunk == b"":
                break
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                sink.close()
                target.unlink(missing_ok=True)
                raise ValueError("upload_too_large")
            if size <= CHUNK:
                head = (head + chunk)[:CHUNK]
            digest.update(chunk)
            sink.write(chunk)
    header_error = _validate_header(head, content_type)
    if header_error:
        target.unlink(missing_ok=True)
        raise ValueError(header_error)
    upload_id = secrets.token_hex(16)
    final = storage_root / f"{upload_id}.blob"
    target.rename(final)
    try:
        await db.execute(
            "INSERT INTO ms_uploads(id, account_id, channel, kind, title, status, sha256, size_bytes, content_type)"
            " VALUES (?,?,?,?,?,'pending',?,?,?)",
            (upload_id, account_id, channel, kind, title, digest.hexdigest(), size, content_type),
        )
        await db.commit()
    except Exception:
        await db.rollback()
        final.unlink(missing_ok=True)  # no orphan blob without its DB row
        raise
    return {"upload_id": upload_id, "sha256": digest.hexdigest(), "size_bytes": size, "status": "pending"}


async def owner_review(db: Any, upload_id: str, decision: str, note: str = "") -> dict[str, Any]:
    """Owner approval happens in the local panel; moderators never self-approve."""
    if decision not in {"approved", "rejected"}:
        raise ValueError("invalid_decision")
    cursor = await db.execute(
        "UPDATE ms_uploads SET status=?, owner_reviewed_at=CURRENT_TIMESTAMP, review_note=?"
        " WHERE id=? AND status='pending'",
        (decision, note, upload_id),
    )
    await db.commit()
    if not cursor.rowcount:
        raise ValueError("upload_missing_or_reviewed")
    return {"upload_id": upload_id, "status": decision}


async def list_pending_for_owner(db: Any, account_id: int, channel: str) -> list[dict[str, Any]]:
    rows = await (await db.execute(
        "SELECT id, kind, title, size_bytes, sha256 FROM ms_uploads"
        " WHERE account_id=? AND channel=? AND status='pending' ORDER BY uploaded_at",
        (account_id, channel),
    )).fetchall()
    return [{"id": r[0], "kind": r[1], "title": r[2], "size_bytes": r[3], "sha256": r[4]} for r in rows]


async def get_upload(db: Any, upload_id: str) -> dict[str, Any] | None:
    row = await (await db.execute(
        "SELECT id, account_id, channel, kind, title, status, sha256, size_bytes, content_type"
        " FROM ms_uploads WHERE id=?", (upload_id,),
    )).fetchone()
    if row is None:
        return None
    return {"id": row[0], "account_id": row[1], "channel": row[2], "kind": row[3],
            "title": row[4], "status": row[5], "sha256": row[6], "size_bytes": row[7], "content_type": row[8]}
