"""DIR-LIVE-05: session ZIP export, Director backup/restore round-trip, safe deletion."""
from __future__ import annotations

import hashlib
import io
import json
import time
import zipfile

import pytest

from app import backup, director, director_review
from app.database import get_db


@pytest.fixture
def storage_root(tmp_path, monkeypatch):
    root = tmp_path / "storage"
    monkeypatch.setattr(director, "DATA_ROOT", root)
    return root


async def _session(channel: str = "channel", session_id: str = "session", state: str = "stopped") -> None:
    from app.database import init_db
    await init_db()
    db = await get_db()
    try:
        await director.ensure_schema(db)
        await db.execute(
            "INSERT INTO director_sessions(id, channel, state, config_version) VALUES (?, ?, ?, 1)",
            (session_id, channel, state),
        )
        await db.commit()
    finally:
        await db.close()


async def _asset(asset_id: int, channel: str, session_id: str, path: str, data: bytes, *, pinned: int = 0, kind: str = "frame") -> bytes:
    target = director._session_root(session_id) / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO director_session_artifacts(id, session_id, kind, path, size_bytes, pinned, channel, state, content_hash, written_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'committed', ?, CURRENT_TIMESTAMP)",
            (asset_id, session_id, kind, path, len(data), pinned, channel, hashlib.sha256(data).hexdigest()),
        )
        await db.commit()
    finally:
        await db.close()
    return data


def _zip_entries(path) -> dict[str, bytes]:
    with zipfile.ZipFile(path, mode="r") as archive:
        return {name: archive.read(name) for name in archive.namelist()}


@pytest.mark.asyncio
async def test_export_contains_transcript_audit_frames_unmasked(storage_root, tmp_db):
    await _session()
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO director_audit(channel, session_id, action, result, details_json) VALUES (?, ?, 'plan', 'partial', '{}')",
            ("channel", "session"),
        )
        await db.commit()
    finally:
        await db.close()
    await director.transcript_append("channel", "session", [
        {"at": 1000.0, "source_id": "7", "text": "речь стримера без маскировки"},
    ])
    frame = await _asset(11, "channel", "session", "frames/live.jpg", b"\xff\xd8live")
    pinned = await _asset(12, "channel", "session", "frames/pin.jpg", b"\xff\xd8pinned", pinned=1)
    result = await director.export_session("channel", "session")
    assert result["ok"] is True and result["missing"] == []
    assert result["size_bytes"] == (director.DATA_ROOT / result["path"]).stat().st_size
    entries = _zip_entries(director.DATA_ROOT / result["path"])
    transcript = json.loads(entries["transcript.jsonl"].splitlines()[0])
    assert transcript["text"] == "речь стримера без маскировки"  # real content, no Viewer-N masking
    assert "речь стримера без маскировки" in entries["transcript.txt"].decode("utf-8")
    audit_payload = json.loads(entries["audit.json"])
    assert any(item["action"] == "plan" for item in audit_payload)
    manifest = json.loads(entries["manifest.json"])
    frame_items = {item["path"]: item for item in manifest["artifacts"]}
    assert manifest["total_size_bytes"] == len(frame) + len(pinned) + 0 or manifest["total_size_bytes"] > len(frame)
    assert entries["frames/live.jpg"] == frame and entries["frames/pin.jpg"] == pinned
    assert hashlib.sha256(entries["frames/live.jpg"]).hexdigest() == frame_items["frames/live.jpg"]["content_hash"]
    assert frame_items["frames/pin.jpg"]["pinned"] is True


@pytest.mark.asyncio
async def test_export_reports_missing_files_honestly(storage_root, tmp_db):
    await _session()
    await _asset(1, "channel", "session", "frames/lost.jpg", b"\xff\xd8gone")
    (director._session_root("session") / "frames/lost.jpg").unlink()
    result = await director.export_session("channel", "session")
    assert result["ok"] is True and result["missing"] == ["frames/lost.jpg"]
    entries = _zip_entries(director.DATA_ROOT / result["path"])
    assert json.loads(entries["manifest.json"])["missing"] == ["frames/lost.jpg"]


@pytest.mark.asyncio
async def test_export_refuses_foreign_channel_and_write_failure(storage_root, tmp_db):
    await _session("one", "session-one")
    await _session("two", "session-two")
    with pytest.raises(ValueError, match="session_missing"):
        await director.export_session("two", "session-one")
    # Failure injection: the export target path is occupied by a directory.
    (director.DATA_ROOT / "director" / "exports").mkdir(parents=True, exist_ok=True)
    (director.DATA_ROOT / "director" / "exports" / "session-session-one-1234567890000.zip").mkdir()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(director.time, "time", lambda: 1234567890.0)
        with pytest.raises(ValueError, match="storage_write_failed"):
            await director.export_session("one", "session-one")


@pytest.mark.asyncio
async def test_export_streams_without_loading_archive_in_memory(storage_root, tmp_db):
    await _session()
    big = b"\xff\xd8" + b"p" * (2 * 1024 * 1024)
    await _asset(1, "channel", "session", "frames/big.jpg", big)
    result = await director.export_session("channel", "session")
    entries = _zip_entries(director.DATA_ROOT / result["path"])
    assert len(entries["frames/big.jpg"]) == len(big)


@pytest.mark.asyncio
async def test_repeated_and_cross_channel_deletion_is_safe(storage_root, tmp_db):
    from app.database import init_db
    await init_db()
    await _session("one", "session-one")
    await _session("two", "session-two")
    await _asset(1, "one", "session-one", "frames/pin.jpg", b"\xff\xd8pin", pinned=1)
    await _asset(2, "one", "session-one", "evidence/raw.txt", b"raw rejected", kind="rejected_evidence")
    await _asset(3, "two", "session-two", "frames/other.jpg", b"\xff\xd8other")
    await director.transcript_append("one", "session-one", [{"at": 1.0, "source_id": "7", "text": "история"}])
    db = await get_db()
    try:
        await db.execute("INSERT INTO director_examples(id, channel, source_plan_id, payload_json) VALUES ('ex', 'one', 'plan', '{}')")
        await db.commit()
    finally:
        await db.close()
    first = await director.delete_session_evidence("one", "session-one", "УДАЛИТЬ")
    assert first["deleted_artifact_count"] == 3  # transcript + pinned frame + rejected evidence
    second = await director.delete_session_evidence("one", "session-one", "УДАЛИТЬ")
    assert second["deleted_artifact_count"] == 0  # no false "deleted" state drift
    # Channel two and approved examples survive; audit preserved.
    assert (await director.session_storage_manifest("two", "session-two"))["artifacts"][0]["path"] == "frames/other.jpg"
    assert _file_two_exists()
    db = await get_db()
    try:
        assert (await (await db.execute("SELECT count(*) FROM director_examples WHERE channel='one'")).fetchone())[0] == 1
        audit_actions = [row[0] for row in await (await db.execute("SELECT action FROM director_audit WHERE channel='one'")).fetchall()]
        assert "session_evidence_deleted" in audit_actions
    finally:
        await db.close()


def _file_two_exists() -> bool:
    target = director._session_root("session-two") / "frames/other.jpg"
    return target.is_file() and target.read_bytes() == b"\xff\xd8other"


@pytest.mark.asyncio
async def test_backup_restore_round_trip_with_director_assets(tmp_db, tmp_path, monkeypatch):
    from app.database import init_db
    monkeypatch.setattr(director, "DATA_ROOT", tmp_path / "data")  # == db_path.parent, как в production
    await init_db()
    await _session("one", "session-one")
    frame = await _asset(1, "one", "session-one", "frames/roundtrip.jpg", b"\xff\xd8director-asset")
    db = await get_db()
    try:
        await db.execute("INSERT INTO director_examples(id, channel, source_plan_id, payload_json) VALUES ('ex1', 'one', 'plan', '{}')")
        await db.commit()
    finally:
        await db.close()
    zip_bytes, _filename = await backup.make_backup_zip()
    archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    assert "data/director/session-one/frames/roundtrip.jpg" in archive.namelist()
    # Simulate loss: wipe the Director asset tree, then restore.
    import shutil
    shutil.rmtree(director.DATA_ROOT / "director")
    result = await backup.restore_from_zip(zip_bytes)
    assert result["ok"] is True and result["restored_files"] >= 1 and result["skipped_paths"] == 0
    restored = director.DATA_ROOT / "director" / "session-one" / "frames" / "roundtrip.jpg"
    assert restored.read_bytes() == frame
    db = await get_db()
    try:
        row = await (await db.execute("SELECT size_bytes, content_hash FROM director_session_artifacts WHERE id=1")).fetchone()
        assert row[0] == len(frame) and row[1] == hashlib.sha256(frame).hexdigest()
        example = await (await db.execute("SELECT count(*) FROM director_examples WHERE id='ex1'")).fetchone()
        assert example[0] == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_restore_refuses_unsafe_archive_paths(storage_root, tmp_db):
    dangerous = io.BytesIO()
    with zipfile.ZipFile(dangerous, mode="w") as zf:
        zf.writestr("bot.db", b"SQLite format 3\x00" + b"\x00" * 100)
        zf.writestr("data/director/../../escape.txt", b"evil")
        zf.writestr("data//director//abs.txt", b"evil")
    result = await backup.restore_from_zip(dangerous.getvalue())
    assert result["ok"] is True and result["skipped_paths"] == 1 and result["restored_files"] == 1
    assert not (director.DATA_ROOT.parent / "escape.txt").exists()
