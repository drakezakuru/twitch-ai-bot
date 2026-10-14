"""DIR-LIVE-03 live frames: explicit-enable gate, retention (age/size), pin limits, integrity."""
from __future__ import annotations

import asyncio
import json

import pytest

from app import director
from app.database import get_db


@pytest.fixture
def storage_root(tmp_path, monkeypatch):
    root = tmp_path / "storage"
    monkeypatch.setattr(director, "DATA_ROOT", root)
    return root


async def _session(channel: str = "channel", session_id: str = "session", state: str = "live", *, store_frames: bool = False) -> None:
    from app.database import init_db
    await init_db()
    db = await get_db()
    try:
        await director.ensure_schema(db)
        await db.execute(
            "INSERT INTO director_sessions(id, channel, state, config_version) VALUES (?, ?, ?, 1)",
            (session_id, channel, state),
        )
        config = director.validate_config({"store_frames": store_frames} if store_frames else {})
        await db.execute(
            "INSERT INTO director_configs(channel, config_json, selected_workers_json, director_account_id) VALUES (?, ?, '[]', 2)",
            (channel, json.dumps(config)),
        )
        await db.commit()
    finally:
        await db.close()


async def _asset(asset_id: int, channel: str, session_id: str, path: str, size: int, *, pinned: int = 0, written_at: str | None = None, kind: str = "frame") -> None:
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO director_session_artifacts(id, session_id, kind, path, size_bytes, pinned, channel, state, written_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'committed', ?)",
            (asset_id, session_id, kind, path, size, pinned, channel, written_at),
        )
        await db.commit()
    finally:
        await db.close()


def _file(session_id: str, path: str):
    return director._session_root(session_id) / path


@pytest.mark.asyncio
async def test_frames_default_off_no_hidden_archive(storage_root, tmp_db):
    await _session()
    result = await director.frame_capture("channel", "session", b"\xff\xd8jpgdata")
    assert result == {"ok": False, "reason": "frame_storage_disabled"}
    manifest = await director.session_storage_manifest("channel", "session")
    assert manifest["artifacts"] == [] and manifest["total_size_bytes"] == 0
    assert not (director._session_root("session") / "frames").exists()


@pytest.mark.asyncio
async def test_frame_capture_writes_real_files_when_enabled(storage_root, tmp_db):
    await _session(store_frames=True)
    first = await director.frame_capture("channel", "session", b"\xff\xd8frame-one", at=1000.0)
    second = await director.frame_capture("channel", "session", b"\xff\xd8frame-two", at=1001.0)
    assert first["ok"] and second["ok"]
    assert first["size_bytes"] == len(b"\xff\xd8frame-one")
    manifest = await director.session_storage_manifest("channel", "session")
    assert [item["kind"] for item in manifest["artifacts"]] == ["frame", "frame"]
    assert manifest["total_size_bytes"] == first["size_bytes"] + second["size_bytes"]
    assert _file("session", "frames/1000000.jpg").is_file() and _file("session", "frames/1001000.jpg").is_file()


@pytest.mark.asyncio
async def test_frame_capture_failure_never_touches_vision_health(storage_root, tmp_db):
    await _session(store_frames=True)
    for source in ("ai", "vision", "speech", "twitch"):
        director.health.report("channel", source)

    async def broken_capturer(channel: str):
        raise RuntimeError("frame source exploded")

    try:
        director.scheduler.configure(frame_capturer=broken_capturer)
        await director.scheduler._tick()
        status = await director.get_status("channel")
        assert status["session"]["state"] == "live"
        assert all(status["health"].values())
    finally:
        director.scheduler.frame_capturer = None


@pytest.mark.asyncio
async def test_retention_age_boundary_keeps_pinned_and_transcript(storage_root, tmp_db):
    await _session(store_frames=True)
    old = "2025-01-01 00:00:00"
    fresh = "2026-09-01 00:00:00"
    for asset_id, path, at in ((1, "frames/old1.jpg", old), (2, "frames/new.jpg", fresh)):
        _file("session", path).parent.mkdir(parents=True, exist_ok=True)
        _file("session", path).write_bytes(b"f" * 50)
        await _asset(asset_id, "channel", "session", path, 50, written_at=at)
    _file("session", "frames/pinned-old.jpg").write_bytes(b"p" * 50)
    await _asset(3, "channel", "session", "frames/pinned-old.jpg", 50, pinned=1, written_at=old)
    _file("session", "transcript").mkdir(parents=True, exist_ok=True)
    _file("session", "transcript/session.jsonl").write_bytes(b"t" * 30)
    await _asset(4, "channel", "session", "transcript/session.jsonl", 30, written_at=old, kind="transcript")

    result = await director.sweep_frame_retention("channel", now=1757500000.0)
    assert result["deleted_by_age"] == 1 and result["deleted_by_size"] == 0
    assert not _file("session", "frames/old1.jpg").exists()
    assert _file("session", "frames/new.jpg").is_file()
    assert _file("session", "frames/pinned-old.jpg").is_file()
    assert _file("session", "transcript/session.jsonl").is_file()
    manifest = await director.session_storage_manifest("channel", "session")
    assert manifest["total_size_bytes"] == 50 + 50 + 30


@pytest.mark.asyncio
async def test_retention_size_limit_deletes_oldest_first(storage_root, tmp_db, monkeypatch):
    await _session(store_frames=True)
    monkeypatch.setattr(director, "STORAGE_LIMITS", {
        "transcript": {"scope": "session", "limit_bytes": None},
        "frame": {"scope": "channel", "limit_bytes": 150},
        "rejected_evidence": {"scope": "channel", "limit_bytes": None},
    })
    fresh = "2026-09-01 00:00:00"
    for asset_id, path in ((1, "frames/oldest.jpg"), (2, "frames/middle.jpg"), (3, "frames/newest.jpg")):
        _file("session", path).parent.mkdir(parents=True, exist_ok=True)
        _file("session", path).write_bytes(b"f" * 100)
        await _asset(asset_id, "channel", "session", path, 100, written_at=fresh)
    result = await director.sweep_frame_retention("channel", now=1757500000.0)
    assert result["deleted_by_size"] == 2
    assert not _file("session", "frames/oldest.jpg").exists() and not _file("session", "frames/middle.jpg").exists()
    assert _file("session", "frames/newest.jpg").is_file()
    manifest = await director.session_storage_manifest("channel", "session")
    assert manifest["total_size_bytes"] == 100 <= 150


@pytest.mark.asyncio
async def test_pin_limit_refuses_without_autodelete_or_silent_unpin(storage_root, tmp_db, monkeypatch):
    await _session(store_frames=True)
    monkeypatch.setattr(director, "PINNED_FRAME_LIMIT_BYTES", 150)
    for asset_id, path in ((1, "frames/a.jpg"), (2, "frames/b.jpg")):
        _file("session", path).parent.mkdir(parents=True, exist_ok=True)
        _file("session", path).write_bytes(b"f" * 100)
        await _asset(asset_id, "channel", "session", path, 100)
    assert (await director.set_frame_pin("channel", "session", 1, True))["pinned"] is True
    with pytest.raises(ValueError, match="pinned_storage_full"):
        await director.set_frame_pin("channel", "session", 2, True)
    rows = await _rows()
    assert {row[0]: row[1] for row in rows} == {1: 1, 2: 0}  # no silent unpin, no auto-delete
    assert _file("session", "frames/a.jpg").is_file() and _file("session", "frames/b.jpg").is_file()
    await director.set_frame_pin("channel", "session", 1, False)
    assert (await director.set_frame_pin("channel", "session", 2, True))["pinned"] is True


async def _rows():
    db = await get_db()
    try:
        return await (await db.execute("SELECT id, pinned FROM director_session_artifacts WHERE session_id='session' ORDER BY id")).fetchall()
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_frames_do_not_cross_channels(storage_root, tmp_db):
    await _session("one", "session-one", store_frames=True)
    await _session("two", "session-two", store_frames=True)
    await director.frame_capture("one", "session-one", b"\xff\xd8one", at=1000.0)
    manifest_two = await director.session_storage_manifest("two", "session-two")
    assert manifest_two["artifacts"] == []
    with pytest.raises(ValueError, match="asset_missing"):
        await director.set_frame_pin("two", "session-two", 1, True)
    result = await director.sweep_frame_retention("one", now=1757500000.0)
    assert result["deleted_by_age"] == 0
    assert (await director.session_storage_manifest("two", "session-two"))["artifacts"] == []


@pytest.mark.asyncio
async def test_retention_and_concurrent_writer_stay_consistent(storage_root, tmp_db, monkeypatch):
    await _session(store_frames=True)
    monkeypatch.setattr(director, "STORAGE_LIMITS", {
        "transcript": {"scope": "session", "limit_bytes": None},
        "frame": {"scope": "channel", "limit_bytes": 1000},
        "rejected_evidence": {"scope": "channel", "limit_bytes": None},
    })
    _file("session", "frames").mkdir(parents=True, exist_ok=True)
    _file("session", "frames/old.jpg").write_bytes(b"f" * 100)
    await _asset(1, "channel", "session", "frames/old.jpg", 100, written_at="2026-09-01 00:00:00")

    async def write_new():
        return await director.frame_capture("channel", "session", b"\xff\xd8new" + b"x" * 100, at=1000.0)

    captured, swept = await asyncio.gather(write_new(), director.sweep_frame_retention("channel", now=1757500000.0))
    assert captured["ok"] and swept["ok"]
    manifest = await director.session_storage_manifest("channel", "session")
    real = sum(_file("session", item["path"]).stat().st_size for item in manifest["artifacts"])
    assert manifest["total_size_bytes"] == real


@pytest.mark.asyncio
async def test_approved_example_survives_frame_retention_and_deletion(storage_root, tmp_db):
    from app.database import init_db
    await init_db()
    await _session(store_frames=True)
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO director_examples(id, channel, source_plan_id, payload_json) VALUES ('ex', 'channel', 'plan', '{}')"
        )
        await db.commit()
    finally:
        await db.close()
    _file("session", "frames").mkdir(parents=True, exist_ok=True)
    _file("session", "frames/old.jpg").write_bytes(b"f" * 50)
    await _asset(1, "channel", "session", "frames/old.jpg", 50, written_at="2025-01-01 00:00:00")
    await director.sweep_frame_retention("channel", now=1757500000.0)
    await director.delete_session_evidence("channel", "session", "УДАЛИТЬ")
    db = await get_db()
    try:
        row = await (await db.execute("SELECT count(*) FROM director_examples WHERE id='ex'")).fetchone()
        assert row[0] == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_pin_route_localised_refusal(storage_root, tmp_db, monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from app import director_routes
    from app.database import init_db
    await init_db()
    await _session(store_frames=True)
    for asset_id, path in ((1, "frames/a.jpg"), (2, "frames/b.jpg")):
        _file("session", path).parent.mkdir(parents=True, exist_ok=True)
        _file("session", path).write_bytes(b"f" * 100)
        await _asset(asset_id, "channel", "session", path, 100)
    monkeypatch.setattr(director, "PINNED_FRAME_LIMIT_BYTES", 150)
    app = FastAPI()
    app.include_router(director_routes.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ok = await client.post("/api/director/channel/sessions/session/assets/1/pin", json={"pinned": True})
        assert ok.status_code == 200 and ok.json()["pinned"] is True
        refused = await client.post("/api/director/channel/sessions/session/assets/2/pin", json={"pinned": True})
        assert refused.status_code == 400
        assert refused.json()["detail"]["code"] == "pinned_storage_full"
        released = await client.post("/api/director/channel/sessions/session/assets/1/pin", json={"pinned": False})
        assert released.status_code == 200 and released.json()["pinned"] is False
        allowed = await client.post("/api/director/channel/sessions/session/assets/2/pin", json={"pinned": True})
        assert allowed.status_code == 200 and allowed.json()["pinned"] is True
