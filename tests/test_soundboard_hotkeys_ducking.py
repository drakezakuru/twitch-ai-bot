"""Tests for Soundboard hotkeys, triggering, and ducking / media pause integration."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from starlette.datastructures import UploadFile

pytestmark = pytest.mark.asyncio


def _upload(name: str, data: bytes) -> UploadFile:
    return UploadFile(io.BytesIO(data), filename=name, headers={"content-type": "audio/mpeg"})


async def _seed_track(tmp_path, monkeypatch, name="meme.mp3", hotkey="") -> int:
    from app import soundboard_library as library
    from app.database import init_db

    await init_db()
    monkeypatch.setattr(library, "SOUNDBOARD_DIR", tmp_path / "soundboard")
    created = await library.store_uploads([_upload(name, b"ID3soundpayload")])
    track_id = created["id"]
    if hotkey:
        await library.update_track(track_id, {"name": name, "hotkey": hotkey})
    return track_id


async def test_track_hotkey_persistence_and_lookup(tmp_db, tmp_path, monkeypatch):
    from app import soundboard_library as library

    track_id = await _seed_track(tmp_path, monkeypatch, name="Airhorn.mp3", hotkey="1")

    # Verify list_tracks includes hotkey
    tracks = await library.list_tracks()
    matched = [t for t in tracks if t["id"] == track_id]
    assert len(matched) == 1
    assert matched[0]["hotkey"] == "1"

    # Verify get_track_by_hotkey (case-insensitive)
    found = await library.get_track_by_hotkey("1")
    assert found is not None
    assert found["id"] == track_id
    assert found["name"] == "Airhorn.mp3"

    # Non-existent hotkey returns None
    assert await library.get_track_by_hotkey("numpad9") is None

    # Update hotkey to numpad1
    updated = await library.update_track(track_id, {"name": "Airhorn.mp3", "hotkey": "numpad1"})
    assert updated["hotkey"] == "numpad1"
    assert await library.get_track_by_hotkey("1") is None
    assert (await library.get_track_by_hotkey("numpad1"))["id"] == track_id


async def test_play_track_triggers_ducking_and_media_pause(tmp_db, tmp_path, monkeypatch):
    from app import soundboard_library as library
    from app import widget_bus

    track_id = await _seed_track(tmp_path, monkeypatch, name="Applause.mp3")

    duck_mock = AsyncMock()
    pause_mock = AsyncMock()
    monkeypatch.setattr(widget_bus, "duck_start", duck_mock)
    monkeypatch.setattr(widget_bus, "request_pause_media", pause_mock)
    monkeypatch.setattr(library, "_broadcast", AsyncMock())

    library.reset_runtime_state()
    res = await library.play_track(track_id, account_id=1, channel="streamer_chan")
    assert res["ok"] is True

    # Check ducking signal was raised
    duck_mock.assert_awaited_once()
    duck_kws = duck_mock.await_args.kwargs
    assert duck_kws["source"] == "soundboard"
    assert duck_kws["channel"] == "streamer_chan"
    assert f"soundboard:{track_id}" in duck_kws["reason"]
    assert duck_kws["duration_ms"] > 0

    # Check media pause signal was requested
    pause_mock.assert_awaited_once()
    pause_kws = pause_mock.await_args.kwargs
    assert pause_kws["source"] == "soundboard"
    assert pause_kws["channel"] == "streamer_chan"


async def test_stop_and_finish_playback_restore_audio(tmp_db, tmp_path, monkeypatch):
    from app import soundboard_library as library
    from app import widget_bus

    duck_end_mock = AsyncMock()
    resume_mock = AsyncMock()
    monkeypatch.setattr(widget_bus, "duck_end", duck_end_mock)
    monkeypatch.setattr(widget_bus, "request_resume_media", resume_mock)
    monkeypatch.setattr(library, "_broadcast", AsyncMock())

    # Stop playback
    stop_res = await library.stop_playback(account_id=1, channel="streamer_chan")
    assert stop_res["ok"] is True
    duck_end_mock.assert_awaited_once_with(source="soundboard", channel="streamer_chan")
    resume_mock.assert_awaited_once_with(source="soundboard", channel="streamer_chan")

    duck_end_mock.reset_mock()
    resume_mock.reset_mock()

    # Finish playback naturally
    finish_res = await library.finish_playback(account_id=1, channel="streamer_chan")
    assert finish_res["ok"] is True
    assert finish_res["status"] == "finished"
    duck_end_mock.assert_awaited_once_with(source="soundboard", channel="streamer_chan")
    resume_mock.assert_awaited_once_with(source="soundboard", channel="streamer_chan")


async def test_trigger_hotkey_endpoint(tmp_db, tmp_path, monkeypatch):
    from httpx import ASGITransport, AsyncClient
    from app.server import app
    from app import soundboard_library as library

    track_id = await _seed_track(tmp_path, monkeypatch, name="Meme.mp3", hotkey="alt+1")
    monkeypatch.setattr(library, "_broadcast", AsyncMock())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Missing combo -> 400
        res_empty = await client.post(
            "/api/widgets/soundboard/trigger-hotkey",
            json={"combo": "", "account_id": 1, "channel": "chan"},
        )
        assert res_empty.status_code == 400

        # Trigger unknown combo -> 404
        res_404 = await client.post(
            "/api/widgets/soundboard/trigger-hotkey",
            json={"combo": "ctrl+9", "account_id": 1, "channel": "chan"},
        )
        assert res_404.status_code == 404

        # Trigger matching combo -> 200
        library.reset_runtime_state()
        res_200 = await client.post(
            "/api/widgets/soundboard/trigger-hotkey",
            json={"combo": "alt+1", "account_id": 1, "channel": "chan"},
        )
        assert res_200.status_code == 200
        data = res_200.json()
        assert data["ok"] is True
        assert data["track_id"] == track_id
        assert data["hotkey"] == "alt+1"



async def test_public_track_ended_endpoint(tmp_db, tmp_path, monkeypatch):
    from httpx import ASGITransport, AsyncClient
    from app.server import app
    from app import widget_bus

    duck_end_mock = AsyncMock()
    monkeypatch.setattr(widget_bus, "duck_end", duck_end_mock)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/api/widgets/public/soundboard/track-ended",
            params={"account_id": 1, "channel": "streamer_chan"},
        )
        assert res.status_code == 200
        assert res.json() == {"ok": True, "status": "finished"}
        duck_end_mock.assert_awaited_once_with(source="soundboard", channel="streamer_chan")
