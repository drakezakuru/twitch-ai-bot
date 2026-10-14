"""DIR-LIVE-01 storage contract: real-file accounting, quotas, recovery, confinement."""
from __future__ import annotations

import asyncio
import errno
import hashlib

import pytest

from app import director
from app.database import get_db


@pytest.fixture
def storage_root(tmp_path, monkeypatch):
    root = tmp_path / "storage"
    monkeypatch.setattr(director, "DATA_ROOT", root)
    return root


async def _session(channel: str = "channel", session_id: str = "session") -> str:
    from app.database import init_db
    await init_db()
    db = await get_db()
    try:
        await director.ensure_schema(db)
        await db.execute(
            "INSERT INTO director_sessions(id, channel, state, config_version) VALUES (?, ?, 'live', 1)",
            (session_id, channel),
        )
        await db.commit()
    finally:
        await db.close()
    return session_id


async def _asset_rows(channel: str):
    db = await get_db()
    try:
        return await (await db.execute(
            "SELECT id, kind, path, size_bytes, state, content_hash FROM director_session_artifacts "
            "WHERE channel=? ORDER BY id", (channel,)
        )).fetchall()
    finally:
        await db.close()


async def _examples_count(channel: str) -> int:
    db = await get_db()
    try:
        row = await (await db.execute("SELECT count(*) FROM director_examples WHERE channel=?", (channel,))).fetchone()
        return int(row[0])
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_write_records_real_file_facts(storage_root, tmp_db):
    await _session()
    data = b"x" * 1000
    result = await director.write_session_asset("channel", "session", "transcript", "speech/session.json", data)
    assert result["size_bytes"] == 1000
    assert result["content_hash"] == hashlib.sha256(data).hexdigest()
    rows = await _asset_rows("channel")
    assert rows[0][3] == 1000 and rows[0][4] == "committed" and rows[0][5] == result["content_hash"]
    manifest = await director.session_storage_manifest("channel", "session")
    assert manifest["total_size_bytes"] == 1000
    assert manifest["artifacts"][0]["state"] == "committed"


@pytest.mark.asyncio
async def test_register_requires_real_file_and_ignores_claimed_sizes(storage_root, tmp_db):
    await _session()
    with pytest.raises(ValueError, match="artifact_file_missing"):
        await director.register_session_artifact("channel", "session", "transcript", "speech/a.json")
    root = director._session_root("session")
    (root / "speech").mkdir(parents=True)
    (root / "speech/a.json").write_bytes(b"y" * 250)
    result = await director.register_session_artifact("channel", "session", "transcript", "speech/a.json")
    assert result["size_bytes"] == 250
    assert result["content_hash"] == hashlib.sha256(b"y" * 250).hexdigest()


@pytest.mark.asyncio
async def test_concurrent_writers_cannot_exceed_quota(storage_root, tmp_db, monkeypatch):
    await _session()
    monkeypatch.setattr(director, "STORAGE_LIMITS", {"frame": {"scope": "channel", "limit_bytes": 1500}})

    async def write(index: int):
        try:
            return await director.write_session_asset("channel", "session", "frame", f"frames/{index}.txt", b"z" * 600)
        except ValueError as exc:
            return exc

    results = await asyncio.gather(*(write(index) for index in range(5)))
    ok = [item for item in results if isinstance(item, dict)]
    failed = [item for item in results if isinstance(item, ValueError)]
    assert ok and failed
    assert all("storage_quota_exceeded" in str(item) for item in failed)
    rows = await _asset_rows("channel")
    used = sum(row[3] for row in rows if row[4] in ("pending", "committed"))
    assert used == len(ok) * 600 and used <= 1500
    root = director._session_root("session")
    assert len(list((root / "frames").glob("*.txt"))) == len(ok)
    assert len(list(root.rglob(".director-tmp-*"))) == 0


@pytest.mark.asyncio
async def test_disk_full_cleans_tmp_and_aborts_reservation(storage_root, tmp_db, monkeypatch):
    await _session()

    def broken_replace(tmp_path, target):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(director, "_atomic_replace", broken_replace)
    with pytest.raises(ValueError, match="storage_full"):
        await director.write_session_asset("channel", "session", "transcript", "speech/big.json", b"a" * 100)
    rows = await _asset_rows("channel")
    assert rows and all(row[4] == "aborted" for row in rows)
    root = director._session_root("session")
    assert not list(root.rglob(".director-tmp-*")) and not (root / "speech" / "big.json").exists()
    result = await director.reconcile_session_storage("channel", "session")
    assert result["recovered"] == [] and result["discarded"] == []
    manifest = await director.session_storage_manifest("channel", "session")
    assert manifest["total_size_bytes"] == 0


@pytest.mark.asyncio
async def test_crash_recovery_is_idempotent(storage_root, tmp_db):
    await _session()
    root = director._session_root("session")
    (root / "speech").mkdir(parents=True)
    (root / "speech/crash.json").write_bytes(b"c" * 400)
    (root / "speech" / (director._TMP_PREFIX + "x")).write_bytes(b"t")
    (root / "speech/orphan.bin").write_bytes(b"o" * 50)
    db = await get_db()
    try:
        await director.ensure_schema(db)
        await db.executemany(
            "INSERT INTO director_session_artifacts(session_id, kind, path, size_bytes, channel, state) "
            "VALUES ('session', 'transcript', ?, ?, 'channel', 'pending')",
            [("speech/crash.json", 999), ("speech/lost.json", 100)],
        )
        await db.commit()
    finally:
        await db.close()
    result = await director.reconcile_session_storage("channel", "session")
    assert result["recovered"] == ["speech/crash.json"]
    assert result["discarded"] == ["speech/lost.json"]
    assert result["removed_tmp"] == 1
    assert result["unregistered"] == ["speech/orphan.bin"]
    rows = {row[2]: row for row in await _asset_rows("channel")}
    assert rows["speech/crash.json"][3] == 400 and rows["speech/crash.json"][4] == "committed"
    assert rows["speech/lost.json"][4] == "aborted"
    manifest = await director.session_storage_manifest("channel", "session")
    assert manifest["total_size_bytes"] == 400
    again = await director.reconcile_session_storage("channel", "session")
    assert again["recovered"] == [] and again["discarded"] == [] and again["removed_tmp"] == 0
    assert again["unregistered"] == ["speech/orphan.bin"]


@pytest.mark.asyncio
async def test_migration_preserves_legacy_rows(storage_root, tmp_db):
    from app.database import init_db
    await init_db()
    db = await get_db()
    try:
        await db.execute("DROP TABLE director_session_artifacts")
        await db.execute(
            "CREATE TABLE director_session_artifacts ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, kind TEXT NOT NULL, path TEXT NOT NULL, "
            "size_bytes INTEGER NOT NULL DEFAULT 0, pinned INTEGER NOT NULL DEFAULT 0, "
            "metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "UNIQUE(session_id, kind, path))"
        )
        await db.execute(
            "INSERT INTO director_sessions(id, channel, state, config_version) VALUES ('legacy', 'channel', 'stopped', 1)"
        )
        await db.execute(
            "INSERT INTO director_session_artifacts(session_id, kind, path, size_bytes, pinned, metadata_json) "
            "VALUES ('legacy', 'transcript', 'speech/old.json', 7, 0, '{}')"
        )
        await db.commit()
        await director.ensure_schema(db)
        row = await (await db.execute(
            "SELECT session_id, path, size_bytes, channel, state FROM director_session_artifacts WHERE session_id='legacy'"
        )).fetchone()
        assert row[0] == "legacy" and row[1] == "speech/old.json" and row[2] == 7
        assert row[3] == "channel" and row[4] == "committed"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_two_channel_isolation_and_quota_buckets(storage_root, tmp_db, monkeypatch):
    await _session("one", "session-one")
    await _session("two", "session-two")
    await director.write_session_asset("one", "session-one", "frame", "frames/a.txt", b"1" * 100)
    with pytest.raises(ValueError, match="session_missing"):
        await director.write_session_asset("two", "session-one", "frame", "frames/b.txt", b"2" * 100)
    monkeypatch.setattr(director, "STORAGE_LIMITS", {"frame": {"scope": "channel", "limit_bytes": 150}})
    await director.write_session_asset("two", "session-two", "frame", "frames/b.txt", b"2" * 100)
    with pytest.raises(ValueError, match="storage_quota_exceeded"):
        await director.write_session_asset("one", "session-one", "frame", "frames/c.txt", b"9" * 100)
    manifest_one = await director.session_storage_manifest("one", "session-one")
    manifest_two = await director.session_storage_manifest("two", "session-two")
    assert [item["path"] for item in manifest_one["artifacts"]] == ["frames/a.txt"]
    assert [item["path"] for item in manifest_two["artifacts"]] == ["frames/b.txt"]


@pytest.mark.asyncio
async def test_pinned_frames_have_separate_hard_limit(storage_root, tmp_db, monkeypatch):
    await _session()
    monkeypatch.setattr(director, "PINNED_FRAME_LIMIT_BYTES", 20)
    await director.write_session_asset("channel", "session", "frame", "frames/pin.txt", b"p" * 15, pinned=True)
    with pytest.raises(ValueError, match="storage_quota_exceeded"):
        await director.write_session_asset("channel", "session", "frame", "frames/pin2.txt", b"q" * 10, pinned=True)
    await director.write_session_asset("channel", "session", "frame", "frames/live.txt", b"z" * 100)


@pytest.mark.asyncio
async def test_confinement_traversal_symlink_and_metadata_rules(storage_root, tmp_db):
    await _session()
    for bad_path in ("../escape.txt", "/etc/passwd", "a/../../b.txt"):
        with pytest.raises(ValueError, match="invalid_artifact_path"):
            await director.write_session_asset("channel", "session", "transcript", bad_path, b"x")
    root = director._session_root("session")
    escape_dir = director.DATA_ROOT / "director" / "escape-dir"
    escape_dir.mkdir(parents=True)
    root.mkdir(parents=True)
    (root / "frames-link").symlink_to(escape_dir, target_is_directory=True)
    with pytest.raises(ValueError, match="invalid_artifact_path"):
        await director.write_session_asset("channel", "session", "transcript", "frames-link/f.txt", b"x")
    (root / "speech").mkdir()
    outside = escape_dir / "outside.txt"
    outside.write_bytes(b"secret")
    (root / "speech/link.json").symlink_to(outside)
    with pytest.raises(ValueError, match="invalid_artifact_path"):
        await director.write_session_asset("channel", "session", "transcript", "speech/link.json", b"x")
    with pytest.raises(ValueError, match="artifact_metadata_too_large"):
        await director.write_session_asset("channel", "session", "transcript", "speech/big-meta.json", b"x", metadata={"blob": "v" * 5000})
    with pytest.raises(ValueError, match="invalid_artifact"):
        await director.write_session_asset("channel", "session", "transcript", "speech/pinned.json", b"x", pinned=True)
    with pytest.raises(ValueError, match="invalid_artifact_data"):
        await director.write_session_asset("channel", "session", "transcript", "speech/empty.json", b"")


@pytest.mark.asyncio
async def test_delete_evidence_keeps_approved_examples(storage_root, tmp_db):
    from app.database import init_db
    await init_db()
    await _session()
    await director.write_session_asset("channel", "session", "frame", "frames/pin.txt", b"p" * 10, pinned=True)
    db = await get_db()
    try:
        await director.ensure_schema(db)
        await db.execute(
            "INSERT INTO director_examples(id, channel, source_plan_id, payload_json) VALUES ('ex', 'channel', 'plan', '{}')"
        )
        await db.commit()
    finally:
        await db.close()
    manifest = await director.session_storage_manifest("channel", "session")
    assert manifest["artifacts"][0]["pinned"] is True
    result = await director.delete_session_evidence("channel", "session", "УДАЛИТЬ")
    assert result["deleted_artifact_count"] == 1
    assert not (director._session_root("session") / "frames/pin.txt").exists()
    assert await _asset_rows("channel") == []
    assert await _examples_count("channel") == 1


@pytest.mark.asyncio
async def test_soundboard_play_route_validates_scope_without_nameerror(storage_root, tmp_db):
    """ACCEPT-01 live regression: soundboard play/stop routes referenced an undefined
    normalize_channel and always failed with NameError -> 500; the widget-scope guard
    must run and return 400 on a missing scope instead."""
    from fastapi import HTTPException
    from app import widgets

    with pytest.raises(HTTPException) as exc_info:
        await widgets.soundboard_play_route(1, account_id=0, channel="")
    assert exc_info.value.status_code == 400
    with pytest.raises(HTTPException) as exc_info:
        await widgets.soundboard_stop_route(0, channel="")
    assert exc_info.value.status_code == 400
