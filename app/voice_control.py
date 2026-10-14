"""Scoped owner-voice commands for reversible local widget actions."""
from __future__ import annotations

import json
import asyncio
import importlib.util
import logging
import re
import shutil
import subprocess
import tempfile
import time
import wave
from pathlib import Path
from typing import Any

from app.database import get_db
from app.runtime_paths import VOICE_CONTROL_DIR
from app.widget_bindings import normalize_channel, run_binding


VOICE_ACTIONS: dict[str, tuple[str, ...]] = {
    "goals": ("add_percent", "reset"),
    "sub_goal": ("increment", "set", "reset"),
    "countdown": ("start", "pause", "reset", "add_time"),
    "now_playing": ("set", "clear"),
    "lower_third": ("show", "hide"),
}
DEFAULT_THRESHOLD = 0.65
_MAX_AUDIO_BYTES = 12 * 1024 * 1024
_SPEAKER_MODEL = "speechbrain/spkrec-ecapa-voxceleb"
_speaker_verifier: Any = None
logger = logging.getLogger(__name__)


async def ensure_schema() -> None:
    db = await get_db()
    try:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS owner_voice_control_scoped (
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 0,
                activation_phrase TEXT NOT NULL DEFAULT '',
                profile_json TEXT NOT NULL DEFAULT '',
                sample_path TEXT NOT NULL DEFAULT '',
                confidence_threshold REAL NOT NULL DEFAULT 0.65,
                enrolled_at TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (account_id, channel),
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            )
        """)
        await db.commit()
    finally:
        await db.close()


async def verify_scope(account_id: int, channel: str) -> tuple[int, str]:
    normalized = normalize_channel(channel)
    if account_id <= 0 or not normalized:
        raise ValueError("voice_scope_required")
    db = await get_db()
    try:
        row = await (await db.execute(
            "SELECT 1 FROM channels WHERE account_id = ? AND enabled = 1 "
            "AND lower(ltrim(trim(channel_name), '#')) = ?",
            (account_id, normalized),
        )).fetchone()
    finally:
        await db.close()
    if not row:
        raise ValueError("voice_scope_not_found")
    return account_id, normalized


async def get_config(account_id: int, channel: str) -> dict:
    scope = await verify_scope(account_id, channel)
    db = await get_db()
    try:
        row = await (await db.execute(
            "SELECT enabled, activation_phrase, profile_json, sample_path, "
            "confidence_threshold, enrolled_at, updated_at "
            "FROM owner_voice_control_scoped WHERE account_id = ? AND channel = ?",
            scope,
        )).fetchone()
    finally:
        await db.close()
    if not row:
        return {
            "account_id": scope[0], "channel": scope[1], "enabled": 0,
            "activation_phrase": "", "profile_ready": False, "sample_path": "",
            "confidence_threshold": DEFAULT_THRESHOLD, "enrolled_at": None,
            "updated_at": None, "verifier_ready": speaker_verifier_available(),
        }
    data = dict(row)
    data.update({
        "account_id": scope[0], "channel": scope[1],
        "profile_ready": bool(data.pop("profile_json", "")),
        "verifier_ready": speaker_verifier_available(),
    })
    return data


async def save_config(account_id: int, channel: str, payload: dict) -> dict:
    scope = await verify_scope(account_id, channel)
    current = await get_config(*scope)
    enabled = 1 if payload.get("enabled", current["enabled"]) else 0
    phrase = str(payload.get("activation_phrase", current["activation_phrase"]) or "").strip()
    if enabled and len(_normalize_text(phrase)) < 3:
        raise ValueError("activation_phrase_required")
    try:
        threshold = float(payload.get("confidence_threshold", current["confidence_threshold"]))
    except (TypeError, ValueError) as exc:
        raise ValueError("bad_confidence_threshold") from exc
    threshold = max(0.5, min(0.99, threshold))
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO owner_voice_control_scoped "
            "(account_id, channel, enabled, activation_phrase, confidence_threshold) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(account_id, channel) DO UPDATE SET enabled = excluded.enabled, "
            "activation_phrase = excluded.activation_phrase, "
            "confidence_threshold = excluded.confidence_threshold, "
            "updated_at = CURRENT_TIMESTAMP",
            (*scope, enabled, phrase, threshold),
        )
        await db.commit()
    finally:
        await db.close()
    return await get_config(*scope)


def _sample_path(account_id: int, channel: str) -> Path:
    safe_channel = re.sub(r"[^a-z0-9_-]", "_", normalize_channel(channel))[:80]
    return VOICE_CONTROL_DIR / str(account_id) / safe_channel / "owner.wav"


def _read_pcm16_mono(path: Path) -> tuple[list[int], int, float]:
    if path.stat().st_size > _MAX_AUDIO_BYTES:
        raise ValueError("audio_too_large")
    try:
        with wave.open(str(path), "rb") as src:
            channels = src.getnchannels()
            width = src.getsampwidth()
            rate = src.getframerate()
            frames = src.getnframes()
            raw = src.readframes(frames)
    except (wave.Error, OSError) as exc:
        raise ValueError("wav_required") from exc
    if width != 2 or channels not in (1, 2) or rate < 8000 or rate > 96000:
        raise ValueError("unsupported_wav")
    import array
    values = array.array("h")
    values.frombytes(raw)
    if channels == 2:
        samples = [(values[i] + values[i + 1]) // 2 for i in range(0, len(values) - 1, 2)]
    else:
        samples = list(values)
    return samples, rate, len(samples) / rate


def speaker_verifier_available() -> bool:
    return importlib.util.find_spec("speechbrain") is not None


def _load_speaker_verifier() -> Any:
    global _speaker_verifier
    if _speaker_verifier is None:
        from speechbrain.inference.speaker import SpeakerRecognition
        _speaker_verifier = SpeakerRecognition.from_hparams(
            source=_SPEAKER_MODEL,
            savedir=str(VOICE_CONTROL_DIR / "models" / "spkrec-ecapa-voxceleb"),
        )
    return _speaker_verifier


async def verify_owner_voice(reference_path: Path, candidate_path: Path) -> float:
    """Return a normalized ECAPA similarity, failing closed when ML is unavailable."""
    def _verify() -> float:
        verifier = _load_speaker_verifier()
        score, prediction = verifier.verify_files(str(reference_path), str(candidate_path))
        raw_score = float(score.squeeze().item())
        if not bool(prediction.squeeze().item()):
            return 0.0
        return round(max(0.0, min(1.0, (raw_score + 1.0) / 2.0)), 4)

    try:
        return await asyncio.to_thread(_verify)
    except Exception as exc:
        logger.warning("owner voice verification unavailable: %s", exc)
        return 0.0


def _normalize_enrollment_audio(raw: bytes, mime_type: str) -> bytes:
    if raw[:4] == b"RIFF" and raw[8:12] == b"WAVE":
        with tempfile.TemporaryDirectory(prefix="voice_enroll_") as tmp:
            source = Path(tmp) / "source.wav"
            source.write_bytes(raw)
            _samples, rate, _duration = _read_pcm16_mono(source)
            if rate == 16000:
                return raw
    if shutil.which("ffmpeg") is None:
        raise ValueError("ffmpeg_required")
    if raw[:4] == b"RIFF" and raw[8:12] == b"WAVE":
        suffix = ".wav"
    else:
        suffix = ".webm" if "webm" in mime_type else ".ogg"
    with tempfile.TemporaryDirectory(prefix="voice_enroll_") as tmp:
        source = Path(tmp) / f"source{suffix}"
        target = Path(tmp) / "owner.wav"
        source.write_bytes(raw)
        result = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(source),
             "-ar", "16000", "-ac", "1", "-acodec", "pcm_s16le", str(target)],
            capture_output=True, timeout=30, check=False,
        )
        if result.returncode or not target.is_file():
            raise ValueError("unsupported_audio")
        return target.read_bytes()


async def enroll(
    account_id: int, channel: str, audio_bytes: bytes, mime_type: str = "audio/wav",
) -> dict:
    scope = await verify_scope(account_id, channel)
    if not audio_bytes or len(audio_bytes) > _MAX_AUDIO_BYTES:
        raise ValueError("invalid_audio")
    wav_bytes = _normalize_enrollment_audio(audio_bytes, mime_type)
    path = _sample_path(*scope)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(".pending.wav")
    pending.write_bytes(wav_bytes)
    try:
        _samples, rate, duration = _read_pcm16_mono(pending)
        if duration < 30.0 or duration > 65.0:
            raise ValueError("enrollment_duration")
        profile = {
            "version": 2, "model": _SPEAKER_MODEL, "sample_rate": rate,
            "duration_sec": round(duration, 2),
        }
        pending.replace(path)
    except Exception:
        pending.unlink(missing_ok=True)
        raise
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO owner_voice_control_scoped "
            "(account_id, channel, profile_json, sample_path, enrolled_at) "
            "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(account_id, channel) DO UPDATE SET "
            "profile_json = excluded.profile_json, sample_path = excluded.sample_path, "
            "enrolled_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP",
            (*scope, json.dumps(profile), str(path)),
        )
        await db.commit()
    finally:
        await db.close()
    return await get_config(*scope)


async def delete_enrollment(account_id: int, channel: str) -> dict:
    scope = await verify_scope(account_id, channel)
    path = _sample_path(*scope)
    path.unlink(missing_ok=True)
    db = await get_db()
    try:
        await db.execute(
            "UPDATE owner_voice_control_scoped SET enabled = 0, profile_json = '', "
            "sample_path = '', enrolled_at = NULL, updated_at = CURRENT_TIMESTAMP "
            "WHERE account_id = ? AND channel = ?", scope,
        )
        await db.commit()
    finally:
        await db.close()
    return await get_config(*scope)


def _normalize_text(text: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", str(text or "").casefold(), flags=re.UNICODE).split())


def parse_voice_intent(transcript: str, activation_phrase: str) -> dict | None:
    text = _normalize_text(transcript)
    phrase = _normalize_text(activation_phrase)
    if not phrase or not (text == phrase or text.startswith(phrase + " ")):
        return None
    command = text[len(phrase):].strip()
    simple = {
        "таймер старт": ("countdown", "start", "", ""),
        "таймер запусти": ("countdown", "start", "", ""),
        "countdown start": ("countdown", "start", "", ""),
        "таймер почати": ("countdown", "start", "", ""),
        "таймер пауза": ("countdown", "pause", "", ""),
        "countdown pause": ("countdown", "pause", "", ""),
        "таймер сброс": ("countdown", "reset", "", ""),
        "таймер скинути": ("countdown", "reset", "", ""),
        "countdown reset": ("countdown", "reset", "", ""),
        "саб цель сброс": ("sub_goal", "reset", "", ""),
        "sub goal reset": ("sub_goal", "reset", "", ""),
        "саб ціль скинути": ("sub_goal", "reset", "", ""),
        "сейчас играет очистить": ("now_playing", "clear", "", ""),
        "now playing clear": ("now_playing", "clear", "", ""),
        "зараз грає очистити": ("now_playing", "clear", "", ""),
        "плашка показать": ("lower_third", "show", "", ""),
        "lower third show": ("lower_third", "show", "", ""),
        "плашка показати": ("lower_third", "show", "", ""),
        "плашка скрыть": ("lower_third", "hide", "", ""),
        "lower third hide": ("lower_third", "hide", "", ""),
        "плашка сховати": ("lower_third", "hide", "", ""),
    }
    parsed = simple.get(command)
    patterns = (
        (r"^(?:таймер добавить|countdown add|таймер додати) (-?\d{1,5})$", "countdown", "add_time", ""),
        (r"^(?:саб цель плюс|sub goal add|саб ціль плюс) (-?\d{1,6})$", "sub_goal", "increment", ""),
        (r"^(?:саб цель установить|sub goal set|саб ціль встановити) (\d{1,6})$", "sub_goal", "set", ""),
        (r"^(?:цель|goal|ціль) (\d{1,9}) (?:плюс|add) (-?\d{1,3})$", "goals", "add_percent", "goal"),
        (r"^(?:цель|goal|ціль) (\d{1,9}) (?:сброс|reset|скинути)$", "goals", "reset", "goal_reset"),
        (r"^(?:сейчас играет|now playing set|зараз грає) (.{1,120})$", "now_playing", "set", "text"),
        (r"^(?:плашка показать|lower third show|плашка показати) (.{1,80})$", "lower_third", "show", "text"),
    )
    if parsed is None:
        for pattern, widget, action, shape in patterns:
            match = re.match(pattern, command)
            if not match:
                continue
            if shape == "goal":
                parsed = (widget, action, match.group(1), match.group(2))
            elif shape == "goal_reset":
                parsed = (widget, action, match.group(1), "")
            else:
                parsed = (widget, action, "", match.group(1))
            break
    if parsed is None:
        return {"error": "unknown_command"}
    widget, action, key, value = parsed
    if action not in VOICE_ACTIONS.get(widget, ()):
        return {"error": "unknown_command"}
    return {
        "widget": widget, "action": action, "widget_key": key, "value": value,
        "reversible": True, "requires_confirmation": False,
    }


async def handle_stream_transcript(
    account_id: int, channel: str, transcript: str, wav_path: str,
) -> dict:
    try:
        config = await get_config(int(account_id), channel)
    except (TypeError, ValueError):
        return {"status": "invalid_scope"}
    if not config["enabled"]:
        return {"status": "disabled"}
    intent = parse_voice_intent(transcript, config["activation_phrase"])
    if intent is None:
        return {"status": "activation_missing"}
    if intent.get("error"):
        return {"status": "unknown_command"}
    db = await get_db()
    try:
        row = await (await db.execute(
            "SELECT profile_json FROM owner_voice_control_scoped "
            "WHERE account_id = ? AND channel = ?",
            (config["account_id"], config["channel"]),
        )).fetchone()
    finally:
        await db.close()
    if not row or not row["profile_json"]:
        return {"status": "not_enrolled"}
    try:
        profile = json.loads(row["profile_json"])
        candidate_path = Path(wav_path)
        _samples, _rate, duration = _read_pcm16_mono(candidate_path)
        if duration < 1.5 or duration > 65.0 or profile.get("version") != 2:
            raise ValueError("sample_duration")
        confidence = await verify_owner_voice(
            Path(config["sample_path"]), candidate_path,
        )
    except (OSError, ValueError, json.JSONDecodeError):
        confidence = 0.0

    binding = {**intent, "account_id": config["account_id"], "channel": config["channel"]}
    if confidence < float(config["confidence_threshold"]):
        from app.mod_feed_routes import publish_event
        from app.mod_feed_i18n import caption
        suggested_at = time.monotonic()

        async def _execute_suggestion() -> dict:
            current = await get_config(config["account_id"], config["channel"])
            if not current["enabled"] or not current["profile_ready"]:
                return {"error": "voice_control_disabled"}
            if time.monotonic() - suggested_at > 300:
                return {"error": "voice_suggestion_expired"}
            return await execute_reversible_binding(binding, actor="moderator_approval")

        event = publish_event(
            config["account_id"], config["channel"], "intent",
            text=transcript[:200], action=f"{intent['widget']}:{intent['action']}",
            localization={"action": caption(f"mod-feed.caption.voice.{intent['widget']}.{intent['action']}")},
            intent={"source": "owner_voice", "confidence": confidence,
                    "command": intent, "_executor": _execute_suggestion},
            dedup=False,
        )
        return {"status": "suggested", "confidence": confidence,
                "intent": intent, "event_id": event["id"] if event else None}
    execution = await execute_reversible_binding(binding, actor="owner_voice")
    return {"status": "executed" if execution.get("ok") else "rejected",
            "confidence": confidence, "intent": intent, **execution}


async def execute_reversible_binding(binding: dict, *, actor: str) -> dict:
    before = await snapshot_widget_state(binding)
    result = await run_binding(binding)
    if result.get("error"):
        return {"ok": False, "result": result}
    after = await snapshot_widget_state(binding)
    from app.routes import log_action
    changed = before != after
    log_id = await log_action(
        f"voice:{binding['widget']}:{binding['action']}",
        f"account_id={binding['account_id']} channel={binding['channel']}",
        actor=actor,
        revert_payload={
            "action": "voice_widget_action",
            "params": {"binding": binding, "before": before, "after": after},
        } if changed else None,
    )
    return {"ok": True, "result": result, "undo_log_id": log_id if changed else None}


_STATE_SPECS = {
    "goals": ("widget_goals_scoped", ("percent", "done"), "id = ?"),
    "sub_goal": ("widget_sub_goal_scoped", ("current",), "1 = 1"),
    "countdown": (
        "widget_countdown_scoped",
        ("duration_sec", "remaining_sec", "state", "started_at"), "1 = 1",
    ),
    "now_playing": (
        "widget_now_playing_scoped", ("kind", "text", "subtext", "icon_url"), "1 = 1",
    ),
    "lower_third": (
        "widget_lower_third_scoped",
        ("name", "tagline", "social", "avatar_url", "theme", "visible"), "1 = 1",
    ),
}
_STATE_DEFAULTS = {
    "sub_goal": {"current": 0},
    "countdown": {
        "duration_sec": 300, "remaining_sec": 300,
        "state": "stopped", "started_at": None,
    },
    "now_playing": {"kind": "music", "text": "", "subtext": "", "icon_url": ""},
    "lower_third": {
        "name": "", "tagline": "", "social": "", "avatar_url": "",
        "theme": "minimal", "visible": 0,
    },
}


async def _snapshot_from_db(db: Any, binding: dict) -> dict | None:
    widget = str(binding.get("widget") or "")
    table, fields, key_sql = _STATE_SPECS[widget]
    params: list[Any] = []
    if widget == "goals":
        params.append(int(binding.get("widget_key") or 0))
    params.extend((int(binding["account_id"]), normalize_channel(binding["channel"])))
    row = await (await db.execute(
        f"SELECT {', '.join(fields)} FROM {table} WHERE {key_sql} "
        "AND account_id = ? AND channel = ?", tuple(params),
    )).fetchone()
    return dict(row) if row else _STATE_DEFAULTS.get(widget)


async def snapshot_widget_state(binding: dict) -> dict | None:
    db = await get_db()
    try:
        return await _snapshot_from_db(db, binding)
    finally:
        await db.close()


async def revert_widget_action(db: Any, payload: dict) -> tuple[bool, str]:
    binding = payload.get("binding") or {}
    widget = str(binding.get("widget") or "")
    if widget not in _STATE_SPECS:
        return False, "unsupported_widget"
    current = await _snapshot_from_db(db, binding)
    if current != payload.get("after"):
        return False, "stale_state"
    before = payload.get("before")
    if before is None:
        return False, "missing_before_state"
    table, fields, key_sql = _STATE_SPECS[widget]
    assignments = ", ".join(f"{field} = ?" for field in fields)
    params: list[Any] = [before[field] for field in fields]
    if widget == "goals":
        params.append(int(binding.get("widget_key") or 0))
    params.extend((int(binding["account_id"]), normalize_channel(binding["channel"])))
    params.extend(payload["after"][field] for field in fields)
    compare_sql = " AND ".join(f"{field} IS ?" for field in fields)
    cursor = await db.execute(
        f"UPDATE {table} SET {assignments} WHERE {key_sql} "
        f"AND account_id = ? AND channel = ? AND {compare_sql}", tuple(params),
    )
    if not cursor.rowcount:
        return False, "state_not_found"
    await db.commit()
    from app import widgets
    cache_names = {"goals": "goals", "sub_goal": "sub-goal", "now_playing": "now-playing"}
    if widget in cache_names:
        scope = (int(binding["account_id"]), normalize_channel(binding["channel"]))
        widgets._cache_invalidate(widgets._widget_cache_key(cache_names[widget], scope))
    return True, f"{widget} restored"


def capability_block(account_id: int, channel: str) -> str:
    scope = normalize_channel(channel)
    actions = ", ".join(
        f"{widget}=[{', '.join(values)}]" for widget, values in VOICE_ACTIONS.items()
    )
    return (
        "VOICE_WIDGET_CAPABILITIES\n"
        f"scope: account_id={int(account_id)}, channel={scope}\n"
        f"allowed reversible actions: {actions}\n"
        "parameters: goals.widget_key=int>0; numeric values=int; display text=bounded string\n"
        "roles: verified_owner=execute; moderator=approve suggestion; viewer=forbidden\n"
        "confirmation: low-confidence or unverified speaker requires moderator approval. "
        "Use only typed parameters from the command grammar and never invent actions."
    )


async def configured_capability_block(account_id: int, channel: str) -> str:
    try:
        config = await get_config(account_id, channel)
    except ValueError:
        return ""
    if not config["enabled"] or not config["profile_ready"]:
        return ""
    return capability_block(account_id, channel)
