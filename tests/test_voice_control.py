"""Owner voice control is scoped, phrase-gated and whitelist-only."""
from __future__ import annotations

import io
import math
import struct
import wave
from pathlib import Path

import pytest

pytestmark = pytest.mark.asyncio


def _wav(seconds: int = 30, frequency: int = 180, rate: int = 8000) -> bytes:
    raw = bytearray()
    for index in range(seconds * rate):
        value = int(8000 * math.sin(2 * math.pi * frequency * index / rate))
        raw.extend(struct.pack("<h", value))
    out = io.BytesIO()
    with wave.open(out, "wb") as dst:
        dst.setnchannels(1)
        dst.setsampwidth(2)
        dst.setframerate(rate)
        dst.writeframes(bytes(raw))
    return out.getvalue()


async def _setup(tmp_path: Path, monkeypatch) -> None:
    from app.database import get_db, init_db
    from app import voice_control

    monkeypatch.setattr(voice_control, "VOICE_CONTROL_DIR", tmp_path / "voice-control")
    await init_db()
    db = await get_db()
    try:
        await db.executemany(
            "INSERT OR IGNORE INTO accounts (id, nickname, token) VALUES (?, ?, 'fake')",
            ((1, "owner_one"), (2, "owner_two")),
        )
        await db.executemany(
            "INSERT OR IGNORE INTO channels (account_id, channel_name, enabled) VALUES (?, ?, 1)",
            ((1, "chan"), (1, "other"), (2, "chan")),
        )
        await db.commit()
    finally:
        await db.close()


async def test_enrollment_and_settings_are_exact_scope(tmp_db, tmp_path, monkeypatch):
    from app import voice_control

    await _setup(tmp_path, monkeypatch)
    await voice_control.save_config(1, "#CHAN", {
        "activation_phrase": "Помощник", "enabled": True,
    })
    own = await voice_control.enroll(1, "chan", _wav())
    other_channel = await voice_control.get_config(1, "other")
    other_account = await voice_control.get_config(2, "chan")

    assert own["profile_ready"] is True and own["enabled"] == 1
    assert own["activation_phrase"] == "Помощник"
    assert other_channel["profile_ready"] is False and other_channel["enabled"] == 0
    assert other_account["profile_ready"] is False
    assert Path(own["sample_path"]).is_file()
    with wave.open(own["sample_path"], "rb") as sample:
        assert sample.getframerate() == 16000
        assert sample.getnchannels() == 1

    deleted = await voice_control.delete_enrollment(1, "CHAN")
    assert deleted["profile_ready"] is False and deleted["enabled"] == 0
    assert not Path(own["sample_path"]).exists()


async def test_parser_requires_activation_phrase_and_typed_whitelist():
    from app.voice_control import parse_voice_intent

    assert parse_voice_intent("таймер старт", "помощник") is None
    assert parse_voice_intent("помощник таймер старт", "помощник") == {
        "widget": "countdown", "action": "start", "widget_key": "", "value": "",
        "reversible": True, "requires_confirmation": False,
    }
    goal = parse_voice_intent("Helper goal 12 add 5", "helper")
    assert goal and goal["widget_key"] == "12" and goal["value"] == "5"
    assert parse_voice_intent("помощник удали все данные", "помощник") == {
        "error": "unknown_command",
    }


async def test_verified_owner_command_executes_only_matching_scope(tmp_db, tmp_path, monkeypatch):
    from app import voice_control
    from app.database import get_db

    await _setup(tmp_path, monkeypatch)
    await voice_control.save_config(1, "chan", {
        "activation_phrase": "helper", "enabled": True,
    })
    config = await voice_control.enroll(1, "chan", _wav())
    sample = Path(config["sample_path"])
    async def verified(_reference, _candidate):
        return 1.0
    monkeypatch.setattr(voice_control, "verify_owner_voice", verified)

    result = await voice_control.handle_stream_transcript(
        1, "#CHAN", "helper countdown start", str(sample),
    )
    assert result["status"] == "executed" and result["confidence"] >= 0.99

    db = await get_db()
    try:
        own = await (await db.execute(
            "SELECT state FROM widget_countdown_scoped WHERE account_id = 1 AND channel = 'chan'"
        )).fetchone()
        other = await (await db.execute(
            "SELECT state FROM widget_countdown_scoped WHERE account_id = 1 AND channel = 'other'"
        )).fetchone()
    finally:
        await db.close()
    assert own and own["state"] == "running"
    assert other is None


async def test_unverified_voice_becomes_approvable_suggestion(tmp_db, tmp_path, monkeypatch):
    from app import mod_feed_routes, voice_control

    await _setup(tmp_path, monkeypatch)
    await voice_control.save_config(1, "chan", {
        "activation_phrase": "helper", "enabled": True, "confidence_threshold": 0.99,
    })
    await voice_control.enroll(1, "chan", _wav(frequency=180))
    async def unverified(_reference, _candidate):
        return 0.0
    monkeypatch.setattr(voice_control, "verify_owner_voice", unverified)
    candidate = tmp_path / "other.wav"
    candidate.write_bytes(_wav(seconds=5, frequency=500))

    result = await voice_control.handle_stream_transcript(
        1, "chan", "helper countdown start", str(candidate),
    )
    assert result["status"] == "suggested" and result["confidence"] < 0.99
    event = next(item for item in mod_feed_routes._BUFFER if item["id"] == result["event_id"])
    assert event["status"] == "pending"
    assert event["account_id"] == 1 and event["channel"] == "chan"

    approved = await mod_feed_routes.mod_feed_intent(str(event["id"]), "approve")
    assert approved["ok"] is True
    assert approved["event"]["intent"]["executed"]["ok"] is True


async def test_pending_suggestion_rechecks_voice_control_before_approval(
    tmp_db, tmp_path, monkeypatch,
):
    from app import mod_feed_routes, voice_control

    await _setup(tmp_path, monkeypatch)
    await voice_control.save_config(1, "chan", {
        "activation_phrase": "helper", "enabled": True,
    })
    await voice_control.enroll(1, "chan", _wav())

    async def unverified(_reference, _candidate):
        return 0.0

    monkeypatch.setattr(voice_control, "verify_owner_voice", unverified)
    candidate = tmp_path / "candidate.wav"
    candidate.write_bytes(_wav(seconds=5))
    pending = await voice_control.handle_stream_transcript(
        1, "chan", "helper countdown start", str(candidate),
    )
    await voice_control.delete_enrollment(1, "chan")

    approved = await mod_feed_routes.mod_feed_intent(str(pending["event_id"]), "approve")
    assert approved["ok"] is True
    assert approved["event"]["intent"]["executed"] == {
        "error": "voice_control_disabled",
    }


async def test_voice_undo_is_one_shot_and_rejects_stale_state(
    tmp_db, tmp_path, monkeypatch,
):
    from app import voice_control
    from app.database import get_db
    from app.routes_engagement import revert_action_log

    await _setup(tmp_path, monkeypatch)
    await voice_control.save_config(1, "chan", {
        "activation_phrase": "helper", "enabled": True,
    })
    config = await voice_control.enroll(1, "chan", _wav())
    async def verified(_reference, _candidate):
        return 1.0
    monkeypatch.setattr(voice_control, "verify_owner_voice", verified)

    first = await voice_control.handle_stream_transcript(
        1, "chan", "helper countdown start", config["sample_path"],
    )
    undone = await revert_action_log(first["undo_log_id"])
    assert undone["ok"] is True
    assert (await revert_action_log(first["undo_log_id"]))["error"] == "no_revert_payload"

    second = await voice_control.handle_stream_transcript(
        1, "chan", "helper countdown start", config["sample_path"],
    )
    db = await get_db()
    try:
        await db.execute(
            "UPDATE widget_countdown_scoped SET remaining_sec = 111 "
            "WHERE account_id = 1 AND channel = 'chan'"
        )
        await db.commit()
    finally:
        await db.close()
    stale = await revert_action_log(second["undo_log_id"])
    assert stale == {"ok": False, "detail": "stale_state", "action": "voice_widget_action"}

    db = await get_db()
    try:
        row = await (await db.execute(
            "SELECT revert_payload FROM action_log WHERE id = ?", (second["undo_log_id"],),
        )).fetchone()
    finally:
        await db.close()
    assert row and row["revert_payload"]


async def test_noop_voice_action_does_not_offer_undo(tmp_db, tmp_path, monkeypatch):
    from app import voice_control

    await _setup(tmp_path, monkeypatch)
    await voice_control.save_config(1, "chan", {
        "activation_phrase": "helper", "enabled": True,
    })
    config = await voice_control.enroll(1, "chan", _wav())

    async def verified(_reference, _candidate):
        return 1.0

    monkeypatch.setattr(voice_control, "verify_owner_voice", verified)
    result = await voice_control.handle_stream_transcript(
        1, "chan", "helper lower third hide", config["sample_path"],
    )

    assert result["status"] == "executed"
    assert result["undo_log_id"] is None


async def test_capability_block_is_scoped_and_excludes_irreversible_actions():
    from app.voice_control import capability_block

    block = capability_block(7, "#MyChannel")
    assert "account_id=7, channel=mychannel" in block
    assert "countdown=[start, pause, reset, add_time]" in block
    assert "verified_owner=execute" in block
    assert "viewer=forbidden" in block
    assert "requires moderator approval" in block
    for forbidden in ("soundboard", "moderation", "clip", "tts"):
        assert forbidden not in block.lower()


async def test_capability_block_is_injected_only_for_ready_scope(
    tmp_db, tmp_path, monkeypatch,
):
    from app import voice_control

    await _setup(tmp_path, monkeypatch)
    assert await voice_control.configured_capability_block(1, "chan") == ""
    await voice_control.save_config(1, "chan", {
        "activation_phrase": "helper", "enabled": True,
    })
    await voice_control.enroll(1, "chan", _wav())
    assert "scope: account_id=1, channel=chan" in (
        await voice_control.configured_capability_block(1, "#CHAN")
    )
    assert await voice_control.configured_capability_block(1, "other") == ""

    source = Path("app/chat_analyzer.py").read_text(encoding="utf-8")
    assert "voice_capability_block = await configured_capability_block(account_id, channel)" in source
    assert "corrections_block,\n            voice_capability_block," in source


async def test_stream_audio_calls_voice_control_before_wav_cleanup(tmp_path, monkeypatch):
    from app.stream_vision import StreamVisionConfig, StreamVisionManager
    from app import voice_control

    wav_path = tmp_path / "stream.wav"
    wav_path.write_bytes(_wav(seconds=2))
    seen = {}

    class FakeAI:
        pass

    manager = StreamVisionManager(
        FakeAI(), cfg=StreamVisionConfig(audio_diarization_mode="off"),
    )

    async def grab(_channel, duration):
        assert duration == manager.cfg.audio_interval
        return str(wav_path)

    async def transcribe(path):
        assert path == str(wav_path)
        return "helper countdown start", {}

    async def handle(account_id, channel, transcript, path):
        seen.update({
            "account_id": account_id, "channel": channel,
            "transcript": transcript, "exists": Path(path).is_file(),
        })
        return {"status": "disabled"}

    monkeypatch.setattr(manager, "_grab_audio", grab)
    monkeypatch.setattr(manager, "_transcribe", transcribe)
    monkeypatch.setattr(voice_control, "handle_stream_transcript", handle)
    await manager._capture_audio(7, "#Chan")

    assert seen == {
        "account_id": 7, "channel": "#Chan",
        "transcript": "helper countdown start", "exists": True,
    }
    assert not wav_path.exists()


async def test_owner_voice_panel_has_local_enrollment_and_three_locales():
    template = Path("templates/partials/bots.html").read_text(encoding="utf-8")
    script = Path("static/app/10_stream_p4_p6.js").read_text(encoding="utf-8")

    for element_id in (
        "voiceControlChannel", "voiceControlPhrase", "voiceControlThreshold",
        "voiceControlRecord", "voiceControlStop", "voiceControlPlayback",
        "voiceControlEnroll", "voiceControlSuggestions",
    ):
        assert f'id="{element_id}"' in template
    assert "navigator.mediaDevices.getUserMedia({audio: true})" in script
    assert "new MediaRecorder(_voiceStream)" in script
    assert "audio_b64" in script
    for locale in ("ru", "en", "ua"):
        assert f"Object.assign(LANGS.{locale}, {{" in script
    assert script.count("'voice_control.enroll_text':") == 3
    assert script.count("'voice_control.hotkey_review':") == 3
