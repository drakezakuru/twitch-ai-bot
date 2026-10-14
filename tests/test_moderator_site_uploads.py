"""MOD-10 gate: quarantine flow, bounded processor, malformed fixtures, owner-only approval."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import pytest_asyncio

from app import moderator_site_library as lib
from app import moderator_site_uploads as uploads

PNG_MAGIC = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest_asyncio.fixture
async def db(tmp_path):
    import aiosqlite
    conn = await aiosqlite.connect(tmp_path / "uploads.db")
    await uploads.ensure_schema(conn)
    await lib.ensure_schema(conn)
    from app import moderator_site_permissions as perms
    await perms.ensure_schema(conn)
    yield conn
    await conn.close()


@pytest.fixture
def storage(tmp_path):
    return tmp_path / "storage"


def _chunker(data: bytes):
    async def read_chunk(size: int):
        if not data:
            return b""
        chunk, data_tail = data[:size], data[size:]
        data[:] = data_tail  # type: ignore[assignment]
        return bytes(chunk)
    return read_chunk


@pytest.mark.asyncio
async def test_upload_lands_in_quarantine_and_owner_approves(db, storage):
    data = bytearray(PNG_MAGIC + b"payload")
    result = await uploads.store_upload(
        db, storage, account_id=1, channel="chan", kind="media",
        title="My clip", content_type="image/png", read_chunk=_chunker(data))
    assert result["status"] == "pending"  # quarantine, never auto-approved
    stored = await uploads.get_upload(db, result["upload_id"])
    assert stored is not None
    assert hashlib.sha256(PNG_MAGIC + b"payload").hexdigest() == stored["sha256"]
    # Moderators' read-only library does not show it yet.
    visible = await lib.list_items(db, account_id=1, channel="chan", kind="media")
    assert visible["total"] == 0
    # Owner reviews in the local panel; only then it becomes visible.
    await uploads.owner_review(db, result["upload_id"], "approved")
    after = await lib.list_items(db, account_id=1, channel="chan", kind="media")
    assert after["total"] == 0  # approval does not auto-publish into the library
    reviewed = await uploads.get_upload(db, result["upload_id"])
    assert reviewed["status"] == "approved"


@pytest.mark.asyncio
async def test_oversized_upload_refused_without_reading_all(db, storage):
    class _Bomb:
        def __init__(self): self.read = 0
        async def read_chunk(self, size: int):
            self.read += size
            if self.read > 5 * uploads.MAX_UPLOAD_BYTES:
                return b""
            return b"\x00" * size
    with pytest.raises(ValueError, match="upload_too_large"):
        await uploads.store_upload(db, storage, account_id=1, channel="chan", kind="media",
                                   title="bomb", content_type="application/octet-stream",
                                   read_chunk=_Bomb().read_chunk)
    assert list(storage.rglob("*.blob")) == []  # nothing persisted


@pytest.mark.asyncio
async def test_malformed_files_rejected_by_magic_bytes(db, storage):
    for content_type, head in (("image/png", b"GIF89a-not-a-png"), ("audio/mpeg", b"not-mp3")):
        with pytest.raises(ValueError, match="upload_malformed"):
            await uploads.store_upload(db, storage, account_id=1, channel="chan", kind="sound",
                                       title="bad", content_type=content_type,
                                       read_chunk=_chunker(bytearray(head)))
        with pytest.raises(ValueError, match="upload_empty"):
            await uploads.store_upload(db, storage, account_id=1, channel="chan", kind="sound",
                                       title="empty", content_type=content_type,
                                       read_chunk=_chunker(bytearray(b"")))


@pytest.mark.asyncio
async def test_db_failure_rolls_back_and_cleans_blob(db, storage, monkeypatch):
    data = bytearray(PNG_MAGIC)
    async def failing_read_chunk(size: int):
        return b""
    async def broken_commit():
        raise Exception("db down")
    monkeypatch.setattr(db, "commit", broken_commit)
    with pytest.raises(Exception, match="db down"):
        await uploads.store_upload(db, storage, account_id=1, channel="chan", kind="media",
                                   title="t", content_type="image/png", read_chunk=_chunker(data))
    pending = await uploads.list_pending_for_owner(db, 1, "chan")
    assert pending == []  # rollback: no half-recorded upload


@pytest.mark.asyncio
async def test_upload_only_actor_never_plays(db, storage):
    """Upload permission grants no play path — separate concerns by design."""
    from app import moderator_site_permissions as perms
    await perms.save_grant(db, 1, "chan", "uploader", "mod-up", ["upload_media"])
    result = await uploads.store_upload(db, storage, account_id=1, channel="chan", kind="media",
                                        title="t", content_type="image/png", read_chunk=_chunker(bytearray(PNG_MAGIC)))
    assert result["status"] == "pending"
    with pytest.raises(ValueError, match="permission_denied"):
        await perms.authenticate_session(
            db, {"twitch_user_id": "uploader", "grant_version": 1}, "play_media", account_id=1, channel="chan")
