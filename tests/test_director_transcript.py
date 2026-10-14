"""DIR-LIVE-02 full session transcripts: order, dedup, limits, close/restart, export composition."""
from __future__ import annotations

import errno
import hashlib
import json

import pytest

from app import director
from app.database import get_db


@pytest.fixture
def storage_root(tmp_path, monkeypatch):
    root = tmp_path / "storage"
    monkeypatch.setattr(director, "DATA_ROOT", root)
    return root


async def _session(channel: str = "channel", session_id: str = "session", state: str = "live") -> None:
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


async def _cursor(session_id: str = "session"):
    db = await get_db()
    try:
        return await (await db.execute("SELECT state, size_bytes, entry_count, warning_sent FROM director_transcript_state WHERE session_id=?", (session_id,))).fetchone()
    finally:
        await db.close()


def _lines(session_id: str = "session") -> list[dict]:
    path = director._transcript_path(session_id)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


@pytest.mark.asyncio
async def test_append_writes_ordered_jsonl_with_timestamps_and_source_ids(storage_root, tmp_db):
    await _session()
    result = await director.transcript_append("channel", "session", [
        {"at": 1000.5, "source_id": "7", "text": "привет стрим"},
        {"at": 1001.0, "source_id": "7", "text": "второй сегмент"},
    ])
    assert result["appended"] == 2 and result["duplicates"] == 0
    lines = _lines()
    assert [item["text"] for item in lines] == ["привет стрим", "второй сегмент"]
    assert lines[0]["at"] == 1000.5 and lines[0]["source_id"] == "7"
    cursor = await _cursor()
    assert cursor[2] == 2
    artifact_size = (await director.session_storage_manifest("channel", "session"))["total_size_bytes"]
    path = director._transcript_path("session")
    assert artifact_size == path.stat().st_size == result["size_bytes"]
    # Audit never carries verbatim speech.
    audit_dump = json.dumps((await director.list_audit("channel"))["entries"], ensure_ascii=False)
    assert "привет стрим" not in audit_dump and "второй сегмент" not in audit_dump


@pytest.mark.asyncio
async def test_dedup_replayed_segment_after_reconnect(storage_root, tmp_db):
    await _session()
    first = await director.transcript_append("channel", "session", [{"at": 100.0, "source_id": "7", "text": "сегмент A"}])
    assert first["appended"] == 1
    replay = await director.transcript_append("channel", "session", [{"at": 101.0, "source_id": "7", "text": "сегмент A"}])
    assert replay["appended"] == 0 and replay["duplicates"] == 1
    second = await director.transcript_append("channel", "session", [{"at": 102.0, "source_id": "7", "text": "сегмент B"}])
    assert second["appended"] == 1
    genuine = await director.transcript_append("channel", "session", [{"at": 500.0, "source_id": "7", "text": "сегмент A"}])
    assert genuine["appended"] == 1
    assert [item["text"] for item in _lines()] == ["сегмент A", "сегмент B", "сегмент A"]


@pytest.mark.asyncio
async def test_warning_and_hard_limit_stop_history_not_live(storage_root, tmp_db, monkeypatch):
    await _session()
    monkeypatch.setattr(director, "TRANSCRIPT_WARNING_BYTES", 40)
    monkeypatch.setattr(director, "STORAGE_LIMITS", {
        "transcript": {"scope": "session", "limit_bytes": 100},
        "frame": {"scope": "channel", "limit_bytes": None},
        "rejected_evidence": {"scope": "channel", "limit_bytes": None},
    })
    first = await director.transcript_append("channel", "session", [{"at": 1.0, "source_id": "7", "text": "a" * 20}])
    assert first["state"] == "recording"
    status = await director.transcript_status("channel", "session")
    assert status["warning"] is True and status["size_bytes"] >= 40
    second = await director.transcript_append("channel", "session", [{"at": 2.0, "source_id": "7", "text": "b" * 60}])
    assert second["state"] == "limit_reached" and second["appended"] == 0
    blocked = await director.transcript_append("channel", "session", [{"at": 3.0, "source_id": "7", "text": "c"}])
    assert blocked["ok"] is False and blocked["reason"] == "limit_reached"
    assert director._transcript_path("session").stat().st_size == first["size_bytes"] <= 100
    session_row = await _session_query()
    assert session_row == "live"  # live context is untouched by the recording limit
    summary = await director.transcript_summary("channel")
    assert summary["state"] == "limit_reached" and summary["entry_count"] == 1


async def _session_query():
    db = await get_db()
    try:
        row = await (await db.execute("SELECT state FROM director_sessions WHERE id='session'")).fetchone()
        return row[0]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_stop_closes_transcript_and_blocks_appends(storage_root, tmp_db):
    await _session()
    await director.transcript_append("channel", "session", [{"at": 1.0, "source_id": "7", "text": "финальный контекст"}])
    path = director._transcript_path("session")
    await director.transition("channel", "stop")
    cursor = await _cursor()
    assert cursor[0] == "closed"
    manifest = (await director.session_storage_manifest("channel", "session"))["artifacts"][0]
    assert manifest["content_hash"] == hashlib.sha256(path.read_bytes()).hexdigest()
    after = await director.transcript_append("channel", "session", [{"at": 9.0, "source_id": "7", "text": "позже"}])
    assert after["ok"] is False and after["reason"] == "closed"
    assert path.stat().st_size == manifest["size_bytes"]
    again = await director.close_transcript("channel", "session", reason="stop")
    assert again == {"ok": True, "state": "closed"}


@pytest.mark.asyncio
async def test_restart_keeps_recording_and_resyncs_disk_truth(storage_root, tmp_db):
    await _session()
    await director.transcript_append("channel", "session", [{"at": 1.0, "source_id": "7", "text": "до рестарта"}])
    db = await get_db()
    try:
        await db.execute("UPDATE director_transcript_state SET size_bytes=1 WHERE session_id='session'")
        await db.execute("UPDATE director_session_artifacts SET size_bytes=1 WHERE session_id='session'")
        await db.commit()
    finally:
        await db.close()
    await director.recover_after_restart()
    status = await director.transcript_status("channel", "session")
    assert status["state"] == "recording"
    # Disk is the source of truth for an open recording after a crash.
    assert status["size_bytes"] == director._transcript_path("session").stat().st_size > 1
    resumed = await director.transcript_append("channel", "session", [{"at": 2.0, "source_id": "7", "text": "после резюме"}])
    assert resumed["appended"] == 1


@pytest.mark.asyncio
async def test_transcript_does_not_cross_channels(storage_root, tmp_db):
    await _session("one", "session-one")
    await _session("two", "session-two")
    await director.transcript_append("one", "session-one", [{"at": 1.0, "source_id": "7", "text": "только для первого"}])
    with pytest.raises(ValueError, match="session_missing"):
        await director.transcript_append("two", "session-one", [{"at": 2.0, "source_id": "7", "text": "чужой канал"}])
    manifest_two = await director.session_storage_manifest("two", "session-two")
    assert manifest_two["artifacts"] == [] and manifest_two["total_size_bytes"] == 0
    assert await director.transcript_summary("two") == {}


@pytest.mark.asyncio
async def test_silence_entries_do_not_touch_recording(storage_root, tmp_db):
    await _session()
    result = await director.transcript_append("channel", "session", [
        {"at": 1.0, "source_id": "7", "text": "  "},
        {"at": 2.0, "source_id": "7", "text": ""},
        {"at": 3.0},
    ])
    assert result["appended"] == 0
    assert await _cursor() is None
    assert await director.transcript_summary("channel") == {}


@pytest.mark.asyncio
async def test_summary_is_bounded_and_partial(storage_root, tmp_db):
    await _session()
    entries = [{"at": float(index), "source_id": "7", "text": f"реплика {index}"} for index in range(8)]
    await director.transcript_append("channel", "session", entries)
    summary = await director.transcript_summary("channel")
    assert summary["entry_count"] == 8 and summary["state"] == "recording"
    assert len(summary["recent"]) == 5
    assert summary["recent"][-1] == "реплика 7"
    assert summary["size_bytes"] == director._transcript_path("session").stat().st_size


@pytest.mark.asyncio
async def test_txt_export_composition(storage_root, tmp_db):
    await _session()
    await director.transcript_append("channel", "session", [{"at": 1757500000.0, "source_id": "7", "text": "строка экспорта"}])
    rendered = director.transcript_txt(_lines())
    assert rendered.startswith("[") and "строка экспорта" in rendered
    assert rendered.split("] ", 1)[1] == "строка экспорта"


@pytest.mark.asyncio
async def test_scheduler_captures_segments_for_running_sessions(storage_root, tmp_db):
    await _session()
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO director_configs(channel, config_json, selected_workers_json, director_account_id) VALUES ('channel', ?, '[]', 2)",
            (json.dumps(director.validate_config({})),),
        )
        await db.commit()
    finally:
        await db.close()
    now = 1000.0
    segments = [{"at": now, "source_id": "7", "text": "сегмент из scheduler"}]

    async def capturer(channel: str):
        return segments.pop(0) if segments else None

    for source in ("ai", "vision", "speech", "twitch"):
        director.health.report("channel", source)
    try:
        director.scheduler.configure(transcript_capturer=capturer)
        await director.scheduler._tick()
        assert [item["text"] for item in _lines()] == ["сегмент из scheduler"]
        await director.scheduler._tick()  # no re-delivery: the capturer has nothing new
        assert len(_lines()) == 1
    finally:
        director.scheduler.transcript_capturer = None


async def _artifact_rows(session_id: str = "session"):
    db = await get_db()
    try:
        return await (await db.execute(
            "SELECT id, path, size_bytes, state FROM director_session_artifacts WHERE session_id=? ORDER BY id",
            (session_id,),
        )).fetchall()
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_append_disk_full_reverts_bytes_and_reservation(storage_root, tmp_db, monkeypatch):
    """Reserve/commit contract for the incremental writer: a failed write reverts both sides."""
    await _session()
    calls = {"n": 0}
    real_fsync = director.os.fsync

    def flaky_fsync(handle):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_fsync(handle)

    monkeypatch.setattr(director.os, "fsync", flaky_fsync)
    with pytest.raises(ValueError, match="storage_full"):
        await director.transcript_append("channel", "session", [{"at": 1.0, "source_id": "7", "text": "не пережило сбой"}])
    path = director._transcript_path("session")
    assert not path.exists()  # nothing was committed, nothing is left on disk
    rows = await _artifact_rows()
    assert rows and rows[0][3] == "aborted"  # the pending reservation was discarded
    # the flaky fsync only trips once, so the resumed append goes through
    resumed = await director.transcript_append("channel", "session", [{"at": 2.0, "source_id": "7", "text": "после сбоя"}])
    assert resumed["appended"] == 1 and resumed["state"] == "recording"
    rows = await _artifact_rows()
    assert rows[-1][3] == "committed" and rows[-1][2] == path.stat().st_size


@pytest.mark.asyncio
async def test_append_commit_rechecks_bucket_quota(storage_root, tmp_db, monkeypatch):
    """Appended bytes are re-checked against the session bucket at the commit step."""
    await _session()
    monkeypatch.setattr(director, "STORAGE_LIMITS", {
        "transcript": {"scope": "session", "limit_bytes": 200},
        "frame": {"scope": "channel", "limit_bytes": None},
        "rejected_evidence": {"scope": "channel", "limit_bytes": None},
    })
    db = await get_db()
    try:
        # A concurrent reservation of the same session already holds part of the bucket.
        await db.execute(
            "INSERT INTO director_session_artifacts(session_id, kind, path, size_bytes, channel, state) "
            "VALUES ('session', 'transcript', 'transcript/other.jsonl', 150, 'channel', 'pending')")
        await db.commit()
    finally:
        await db.close()
    with pytest.raises(ValueError, match="storage_quota_exceeded"):
        await director.transcript_append("channel", "session", [{"at": 1.0, "source_id": "7", "text": "a" * 120}])
    path = director._transcript_path("session")
    assert not path.exists()
    rows = await _artifact_rows()
    assert all(row[3] != "committed" or row[1] == "transcript/other.jsonl" for row in rows)
    used = sum(row[2] for row in rows if row[3] in ("pending", "committed"))
    assert used == 150
    db = await get_db()
    try:
        await db.execute("DELETE FROM director_session_artifacts WHERE path='transcript/other.jsonl'")
        await db.commit()
    finally:
        await db.close()
    fits = await director.transcript_append("channel", "session", [{"at": 2.0, "source_id": "7", "text": "b" * 20}])
    assert fits["appended"] == 1 and fits["size_bytes"] == path.stat().st_size


@pytest.mark.asyncio
async def test_crash_between_write_and_commit_is_recoverable(storage_root, tmp_db, monkeypatch):
    """A crash after the append but before the commit leaves a pending row reconcile completes."""
    await _session()
    real_reserve = director._reserve_quota

    async def crash_reserve(*args, **kwargs):
        raise RuntimeError("simulated crash before commit")

    monkeypatch.setattr(director, "_reserve_quota", crash_reserve)
    with pytest.raises(RuntimeError):
        await director.transcript_append("channel", "session", [{"at": 1.0, "source_id": "7", "text": "пережило крэш"}])
    path = director._transcript_path("session")
    assert path.is_file()  # bytes reached the disk
    rows = await _artifact_rows()
    assert rows[0][3] == "pending"  # the reservation outlives the crash
    monkeypatch.setattr(director, "_reserve_quota", real_reserve)
    result = await director.reconcile_session_storage("channel", "session")
    assert result["recovered"] == [director.TRANSCRIPT_ASSET_PATH]
    manifest = await director.session_storage_manifest("channel", "session")
    assert manifest["total_size_bytes"] == path.stat().st_size
    status = await director.transcript_status("channel", "session")
    assert status["state"] == "recording" and status["size_bytes"] == path.stat().st_size
    resumed = await director.transcript_append("channel", "session", [{"at": 2.0, "source_id": "7", "text": "после восстановления"}])
    assert resumed["appended"] == 1
    lines = _lines()
    assert [item["text"] for item in lines] == ["пережило крэш", "после восстановления"]
