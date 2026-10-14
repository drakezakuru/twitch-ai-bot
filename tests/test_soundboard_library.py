from __future__ import annotations

from pathlib import Path

import pytest
from starlette.datastructures import UploadFile

pytestmark = pytest.mark.asyncio


def _upload(name: str, data: bytes, content_type: str = "application/octet-stream") -> UploadFile:
    import io

    return UploadFile(io.BytesIO(data), filename=name, headers={"content-type": content_type})


async def test_batch_upload_detects_content_and_reports_each_file(tmp_db, tmp_path, monkeypatch):
    from app import soundboard_library as library
    from app.database import init_db

    await init_db()
    monkeypatch.setattr(library, "SOUNDBOARD_DIR", tmp_path / "soundboard")
    result = await library.store_uploads([
        _upload("tone.wav", b"RIFF\x10\x00\x00\x00WAVEfmt ", "text/html"),
        _upload("not-audio.mp3", b"<script>alert(1)</script>", "audio/mpeg"),
        _upload("../clip.ogg", b"OggS\x00payload", "text/plain"),
    ])

    assert result["accepted"] == 2 and result["rejected"] == 1
    assert result["items"][0]["mime"] == "audio/wav"
    assert result["items"][1]["error"] == "unsupported_audio"
    assert result["items"][2]["name"] == "clip.ogg"
    assert sorted(path.suffix for path in library.SOUNDBOARD_DIR.iterdir()) == [".ogg", ".wav"]


async def test_batch_limits_are_enforced_before_storage(tmp_db, tmp_path, monkeypatch):
    from app import soundboard_library as library
    from app.database import init_db

    await init_db()
    monkeypatch.setattr(library, "SOUNDBOARD_DIR", tmp_path / "soundboard")
    monkeypatch.setattr(library, "MAX_BATCH_BYTES", 20)
    with pytest.raises(ValueError, match="batch_too_large"):
        await library.store_uploads([
            _upload("one.ogg", b"OggS" + b"a" * 8),
            _upload("two.ogg", b"OggS" + b"b" * 8),
        ])
    assert not library.SOUNDBOARD_DIR.exists()


async def test_storage_failure_does_not_leave_orphan_file(tmp_db, tmp_path, monkeypatch):
    from app import soundboard_library as library
    from app.database import init_db

    await init_db()
    monkeypatch.setattr(library, "SOUNDBOARD_DIR", tmp_path / "soundboard")

    async def broken_db():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(library, "get_db", broken_db)
    result = await library.store_uploads([_upload("tone.mp3", b"ID3payload")])
    assert result["items"][0]["error"] == "storage_failed"
    assert list(library.SOUNDBOARD_DIR.iterdir()) == []


async def test_track_lifecycle_cleans_file_and_rejects_stale_play(tmp_db, tmp_path, monkeypatch):
    from app import soundboard_library as library
    from app.database import init_db

    await init_db()
    monkeypatch.setattr(library, "SOUNDBOARD_DIR", tmp_path / "soundboard")
    created = await library.store_uploads([_upload("tone.ogg", b"OggSpayload")])
    track_id = created["id"]
    updated = await library.update_track(track_id, {
        "name": "Alert", "volume": 0.4, "cooldown_sec": 3, "sort_order": -2,
    })
    assert updated == {
        "ok": True, "id": track_id, "name": "Alert", "volume": 0.4,
        "cooldown_sec": 3, "sort_order": -2,
    }
    assert (await library.list_tracks())[0]["name"] == "Alert"

    deleted = await library.delete_track(track_id)
    assert deleted == {"ok": True, "id": track_id}
    assert list(library.SOUNDBOARD_DIR.iterdir()) == []
    with pytest.raises(ValueError, match="track_not_found"):
        await library.play_track(track_id, account_id=1, channel="chan")


async def test_play_checks_file_applies_volume_and_track_cooldown(tmp_db, tmp_path, monkeypatch):
    from app import soundboard_library as library
    from app.database import init_db

    await init_db()
    monkeypatch.setattr(library, "SOUNDBOARD_DIR", tmp_path / "soundboard")
    created = await library.store_uploads([_upload("tone.mp3", b"ID3payload")])
    await library.update_track(created["id"], {
        "name": "Tone", "volume": 0.25, "cooldown_sec": 5, "sort_order": 0,
    })
    events = []

    async def broadcast(event):
        events.append(event)

    monkeypatch.setattr(library, "_broadcast", broadcast)
    library.reset_runtime_state()
    result = await library.play_track(created["id"], account_id=1, channel="chan")
    assert result["volume"] == 0.25 and events[0]["channel"] == "chan"
    with pytest.raises(ValueError, match="track_cooldown"):
        await library.play_track(created["id"], account_id=1, channel="chan")

    stored = next(library.SOUNDBOARD_DIR.iterdir())
    stored.unlink()
    library.reset_runtime_state()
    with pytest.raises(ValueError, match="track_file_missing"):
        await library.play_track(created["id"], account_id=1, channel="chan")


async def test_legacy_media_is_readable_then_migrates_atomically(tmp_path, monkeypatch):
    from app import soundboard_library as library

    legacy = tmp_path / "soundboard"
    canonical = tmp_path / "widgets" / "soundboard"
    filename = "a" * 32 + ".mp3"
    legacy.mkdir(parents=True)
    (legacy / filename).write_bytes(b"ID3legacy")
    monkeypatch.setattr(library, "LEGACY_SOUNDBOARD_DIR", legacy)
    monkeypatch.setattr(library, "SOUNDBOARD_DIR", canonical)

    assert library.track_file_path(filename) == legacy / filename
    assert library.migrate_legacy_artifacts() == [filename]
    assert not (legacy / filename).exists()
    assert library.track_file_path(filename) == canonical / filename


async def test_schema_setup_migrates_legacy_media_after_restart(tmp_db, tmp_path, monkeypatch):
    from app import soundboard_library as library
    from app.database import get_db, init_db

    await init_db()
    legacy = tmp_path / "soundboard"
    canonical = tmp_path / "widgets" / "soundboard"
    filename = "1" * 32 + ".webm"
    legacy.mkdir(parents=True)
    (legacy / filename).write_bytes(b"\x1a\x45\xdf\xa3legacy")
    monkeypatch.setattr(library, "LEGACY_SOUNDBOARD_DIR", legacy)
    monkeypatch.setattr(library, "SOUNDBOARD_DIR", canonical)

    db = await get_db()
    try:
        await library.ensure_schema(db)
    finally:
        await db.close()
    assert library.track_file_path(filename) == canonical / filename


async def test_legacy_migration_keeps_original_when_rename_fails(tmp_path, monkeypatch):
    from app import soundboard_library as library

    legacy = tmp_path / "soundboard"
    canonical = tmp_path / "widgets" / "soundboard"
    filename = "b" * 32 + ".ogg"
    legacy.mkdir(parents=True)
    (legacy / filename).write_bytes(b"OggSlegacy")
    monkeypatch.setattr(library, "LEGACY_SOUNDBOARD_DIR", legacy)
    monkeypatch.setattr(library, "SOUNDBOARD_DIR", canonical)

    def fail_replace(source, target):
        raise OSError("disk full")

    monkeypatch.setattr(library.os, "replace", fail_replace)
    assert library.migrate_legacy_artifacts() == []
    assert library.track_file_path(filename) == legacy / filename


async def test_orphan_cleanup_preserves_referenced_and_recent_artifacts(tmp_db, tmp_path, monkeypatch):
    from app import soundboard_library as library
    from app.database import get_db, init_db

    await init_db()
    canonical = tmp_path / "widgets" / "soundboard"
    canonical.mkdir(parents=True)
    referenced = "d" * 32 + ".mp3"
    orphan = "e" * 32 + ".ogg"
    recent = "f" * 32 + ".wav"
    for filename in (referenced, orphan, recent):
        (canonical / filename).write_bytes(b"audio")
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO soundboard_tracks(name,filename,mime) VALUES(?,?,?)",
            ("Referenced", referenced, "audio/mpeg"),
        )
        await db.commit()
    finally:
        await db.close()
    monkeypatch.setattr(library, "SOUNDBOARD_DIR", canonical)
    monkeypatch.setattr(library, "LEGACY_SOUNDBOARD_DIR", tmp_path / "legacy")

    assert await library.cleanup_orphaned_artifacts(grace_seconds=60) == []
    assert await library.cleanup_orphaned_artifacts(grace_seconds=0) == [orphan, recent]
    assert (canonical / referenced).exists()


async def test_track_paths_reject_traversal_and_symlinks(tmp_path, monkeypatch):
    from app import soundboard_library as library

    canonical = tmp_path / "widgets" / "soundboard"
    canonical.mkdir(parents=True)
    filename = "c" * 32 + ".wav"
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"RIFF\x10\x00\x00\x00WAVEfmt ")
    (canonical / filename).symlink_to(outside)
    monkeypatch.setattr(library, "SOUNDBOARD_DIR", canonical)
    monkeypatch.setattr(library, "LEGACY_SOUNDBOARD_DIR", tmp_path / "legacy")

    assert library.track_file_path("../outside.wav") is None
    assert library.track_file_path("folder\\outside.wav") is None
    assert library.track_file_path(filename) is None
