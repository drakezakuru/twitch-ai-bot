"""Deterministic, isolated fake data for local panel QA."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import shutil
import sqlite3
import struct
import wave
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from app.runtime_paths import PROJECT_ROOT


PROFILE_VERSION = 1
PROFILE_KIND = "twitch-ai-bot-qa-profile"
QA_PROFILES_ROOT = PROJECT_ROOT / "data" / "qa-profiles"
ACCOUNT_IDS = (101, 102, 103)
ACCOUNT_NAMES = ("qa_modbot", "qa_ttsbot", "qa_chatbot")
CHANNEL_NAMES = ("qa_mod_channel", "qa_tts_channel", "qa_chat_channel")
NO_OAUTH_TOKEN = "qa-no-oauth"
_PROFILE_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_MARKER = ".qa-profile-root.json"
_FIXED_AT = "2026-09-05 00:00:00"


def profile_root(name: str, *, base_root: Path | None = None) -> Path:
    if not _PROFILE_NAME_RE.fullmatch(name or ""):
        raise ValueError("profile name must match [a-z][a-z0-9_-]{0,31}")
    namespace = (base_root or QA_PROFILES_ROOT).absolute()
    candidate = namespace / name
    if any(path.is_symlink() for path in (candidate, *candidate.parents)):
        raise ValueError("QA profile namespace cannot contain symlinks")
    base = namespace.resolve()
    root = candidate.resolve()
    if root.parent != base or root in {PROJECT_ROOT.resolve(), (PROJECT_ROOT / "data").resolve()}:
        raise ValueError("unsafe QA profile path")
    return root


def _marker_payload(name: str) -> dict:
    return {"kind": PROFILE_KIND, "name": name, "version": PROFILE_VERSION}


def _write_marker(root: Path, name: str) -> None:
    (root / _MARKER).write_text(
        json.dumps(_marker_payload(name), sort_keys=True) + "\n", encoding="utf-8"
    )


def _require_marker(root: Path, name: str) -> None:
    marker = root / _MARKER
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("refusing to use an unmarked QA profile directory") from exc
    if payload != _marker_payload(name):
        raise ValueError("QA profile marker does not match this profile")


@asynccontextmanager
async def _configured_runtime(root: Path) -> AsyncIterator[None]:
    from app import bot_dirs, database, soundboard_library

    await database.close_db()
    old = (
        database.DB_PATH,
        bot_dirs.BOTS_ROOT,
        soundboard_library.SOUNDBOARD_DIR,
        soundboard_library.LEGACY_SOUNDBOARD_DIR,
    )
    database.DB_PATH = root / "bot.db"
    bot_dirs.BOTS_ROOT = root / "bots"
    soundboard_library.SOUNDBOARD_DIR = root / "widgets" / "soundboard"
    soundboard_library.LEGACY_SOUNDBOARD_DIR = root / "soundboard"
    try:
        yield
    finally:
        await database.close_db()
        (
            database.DB_PATH,
            bot_dirs.BOTS_ROOT,
            soundboard_library.SOUNDBOARD_DIR,
            soundboard_library.LEGACY_SOUNDBOARD_DIR,
        ) = old


def _write_tone(path: Path, frequency: int) -> None:
    sample_rate = 8000
    frames = int(sample_rate * 0.08)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        samples = (
            struct.pack("<h", int(5000 * math.sin(2 * math.pi * frequency * i / sample_rate)))
            for i in range(frames)
        )
        audio.writeframes(b"".join(samples))


def _role_config(role: str) -> str:
    from app.bot_roles import ROLE_DEFAULT_CONFIGS

    return json.dumps({role: ROLE_DEFAULT_CONFIGS[role]}, ensure_ascii=False, sort_keys=True)


def _seed_database(db_path: Path, soundboard_dir: Path) -> None:
    rows = (
        (101, "qa_modbot", "moderator", "QA moderator: acts only on explicit policy."),
        (102, "qa_ttsbot", "voice_companion", "QA TTS companion with offline fixtures."),
        (103, "qa_chatbot", "chatter", "QA conversational bot with deterministic replies."),
    )
    with sqlite3.connect(db_path) as db:
        db.execute("PRAGMA foreign_keys=ON")
        for account_id, nickname, role, persona in rows:
            db.execute(
                "INSERT OR REPLACE INTO accounts "
                "(id,nickname,token,enabled,bot_role,role_config_json,persona_json) "
                "VALUES(?,?,?,?,?,?,?)",
                (account_id, nickname, NO_OAUTH_TOKEN, 0, role, _role_config(role),
                 json.dumps(
                     {
                         "name": nickname,
                         "personality": ["offline QA companion"],
                         "memories": [persona],
                     },
                     ensure_ascii=False,
                 )),
            )
        # The moderator remains disabled, but its local policy is ready for stubbed QA flows.
        db.execute(
            "UPDATE accounts SET moderation_mode = 'full', moderation_can_timeout = 1, "
            "antispam_viewer_enabled = 1, antispam_links = 1 "
            "WHERE id = 101"
        )
        for channel_id, account_id, channel in zip((201, 202, 203), ACCOUNT_IDS, CHANNEL_NAMES):
            db.execute(
                "INSERT OR REPLACE INTO channels(id,account_id,channel_name,enabled,auto_analyze) "
                "VALUES(?,?,?,?,?)", (channel_id, account_id, channel, 1, 0),
            )
            db.execute(
                "INSERT OR REPLACE INTO streamer_profile "
                "(account_id,channel,bio,interests,favorite_games,streaming_style,auto_updated,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (account_id, channel, f"Offline QA streamer for {channel}",
                 '["testing","accessibility"]', '["QA Arena"]', "entertaining", 0,
                 _FIXED_AT, _FIXED_AT),
            )

        chat_rows = (
            (91001, 101, "qa_mod_channel", "viewer_spam", "BUY NOW BUY NOW", 0),
            (91006, 101, "qa_mod_channel", "viewer_toxic", "you are a retard", 0),
            (91007, 101, "qa_mod_channel", "viewer_link", "visit https://unsafe.example", 0),
            (91002, 102, "qa_tts_channel", "viewer_tts", "Прочитай это тестовое сообщение", 0),
            (91003, 103, "qa_chat_channel", "trusted_viewer", "Привет, QA-бот! Kappa", 0),
            (91004, 103, "qa_chat_channel", "xss_viewer", '<img src=x onerror="alert(1)">', 0),
            (91005, 103, "qa_chat_channel", "qa_chatbot", "Привет! Это офлайн-ответ.", 1),
        )
        db.executemany(
            "INSERT OR REPLACE INTO chat_log(id,account_id,channel,author,message,is_bot,timestamp) "
            "VALUES(?,?,?,?,?,?,?)", [row + (_FIXED_AT,) for row in chat_rows],
        )
        user_rows = (
            (92001, 101, "qa_mod_channel", "qa_owner", "streamer", 4),
            (92002, 101, "qa_mod_channel", "qa_moderator", "mod", 3),
            (92003, 101, "qa_mod_channel", "qa_vip", "vip", 2),
            (92004, 103, "qa_chat_channel", "trusted_viewer", "subscriber", 5),
        )
        db.executemany(
            "INSERT OR REPLACE INTO chat_users"
            "(id,account_id,channel,username,role,enabled,message_count,last_seen) "
            "VALUES(?,?,?,?,?,1,?,?)", [row + (_FIXED_AT,) for row in user_rows],
        )
        db.execute(
            "INSERT OR REPLACE INTO user_memory(account_id,username,facts,msg_count,last_seen) "
            "VALUES(?,?,?,?,?)",
            (103, "trusted_viewer", '["QA viewer remembers the offline constellation"]', 5, _FIXED_AT),
        )
        mod_rows = (
            (93001, "viewer_spam", "spam", 2, "warn", "BUY NOW"),
            (93002, "viewer_repeat", "repeat", 3, "timeout", "same message x8"),
            (93003, "viewer_link", "links", 4, "block", "unsafe.example"),
            (93004, "viewer_toxic", "insult", 3, "block", "retard"),
        )
        db.executemany(
            "INSERT OR REPLACE INTO moderation_events"
            "(id,account_id,channel,username,rule_name,category,severity,action_taken,source,message_excerpt,created_at) "
            "VALUES(?,101,'qa_mod_channel',?,'QA rule',?,?,?,'chat_in',?,?)",
            [row + (_FIXED_AT,) for row in mod_rows],
        )
        db.execute(
            "INSERT OR REPLACE INTO tts_bot_config"
            "(account_id,provider,voice,emotion_preset,volume,enabled) VALUES(102,'web_speech','','neutral',0.8,1)"
        )
        db.execute(
            "INSERT OR REPLACE INTO channel_points_tts_config"
            "(account_id,enabled,reward_names,max_len,cooldown_sec,max_per_hour,blacklist,announce_user,channel,voice) "
            "VALUES(102,1,'QA TTS Reward',120,5,10,'blockedword',1,'qa_tts_channel','')"
        )
        db.execute(
            "INSERT OR REPLACE INTO settings(key,value) VALUES"
            "('chat_overlay_trusted_users','[\"qa_moderator\",\"qa_owner\",\"trusted_viewer\"]')"
        )
        db.execute(
            "INSERT OR REPLACE INTO settings(key,value) VALUES"
            "('chat_overlay_display_selected-chat','{\"max_messages\":8,\"lifetime_sec\":30,\"font_size\":24,\"emote_size\":32,\"show_badges\":1,\"history_limit\":8,\"history_minutes\":30}')"
        )
        db.executemany(
            "INSERT OR REPLACE INTO recent_events(id,kind,username,amount,created_at) VALUES(?,?,?,?,?)",
            (
                (94001, "follow", "qa_follower", 0, _FIXED_AT),
                (94002, "sub", "qa_subscriber", 1, _FIXED_AT),
                (94003, "raid", "qa_raider", 25, _FIXED_AT),
                (94004, "cheer", "qa_cheerer", 500, _FIXED_AT),
                (94005, "redemption", "qa_redeemer", 1000, _FIXED_AT),
            ),
        )
        db.executemany(
            "INSERT OR REPLACE INTO donations(id,username,amount,currency,message,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (
                (95001, "qa_donatepay", 5.0, "USD", "[donatepay] QA song one", _FIXED_AT),
                (95002, "qa_donatex", 7.0, "USD", "[donatex] QA song two", _FIXED_AT),
                (95003, "qa_donationalerts", 9.0, "USD", "[donationalerts] QA song three", _FIXED_AT),
            ),
        )
        db.executemany(
            "INSERT OR REPLACE INTO stream_goals(id,text,done,sort_order,created_at) VALUES(?,?,?,?,?)",
            ((96001, "QA overlay review", 0, 1, _FIXED_AT),
             (96002, "QA OBS acceptance", 1, 2, _FIXED_AT)),
        )
        db.execute(
            "INSERT OR REPLACE INTO sub_goal(id,target,current,theme,title,last_event_at) "
            "VALUES(1,50,17,'tree','QA Sub Goal',?)", (_FIXED_AT,),
        )
        db.execute(
            "INSERT OR REPLACE INTO now_playing(id,kind,text,subtext,icon_url,updated_at) "
            "VALUES(1,'music','QA Track','Offline Artist','',?)", (_FIXED_AT,),
        )
        db.execute(
            "INSERT OR REPLACE INTO lower_third(id,name,tagline,social,avatar_url,theme,visible,updated_at) "
            "VALUES(1,'QA Streamer','Offline test','@qa','','minimal',1,?)", (_FIXED_AT,),
        )
        db.execute(
            "INSERT OR REPLACE INTO chat_highlight"
            "(id,text,author,kind,theme,visible,auto_mode,display_sec,updated_at) "
            "VALUES(1,'Safe highlighted QA message','trusted_viewer','chat','glow',1,0,15,?)",
            (_FIXED_AT,),
        )
        db.execute(
            "INSERT OR REPLACE INTO chat_roulette"
            "(id,winner,participants,theme,spin_duration_sec,auto_interval_min,visible,updated_at) "
            "VALUES(1,'','[\"qa_owner\",\"qa_moderator\",\"trusted_viewer\"]','wheel',5,0,1,?)",
            (_FIXED_AT,),
        )
        db.executemany(
            "INSERT OR REPLACE INTO song_request_queue"
            "(id,title,requested_by,channel,status,created_at) VALUES(?,?,?,?,?,?)",
            ((97001, "QA Song One", "qa_viewer_one", "qa_chat_channel", "playing", _FIXED_AT),
             (97002, "QA Song Two", "qa_viewer_two", "qa_chat_channel", "queued", _FIXED_AT)),
        )
        db.executemany(
            "INSERT OR REPLACE INTO widget_bindings"
            "(id,account_id,channel,enabled,source,match,widget,widget_key,action,value,role,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            ((98001, 101, "qa_mod_channel", 1, "chat_command", "!qa goal", "goals", "96001", "add_percent", "5", "mod", _FIXED_AT),
             (98002, 101, "qa_mod_channel", 1, "hotkey", "ctrl+shift+q", "countdown", "", "start", "", "streamer", _FIXED_AT),
             (98003, 101, "qa_mod_channel", 1, "chat_command", "!qa sound", "soundboard", "", "play_track:99001", "", "mod", _FIXED_AT)),
        )

        tracks = ((99001, "QA Alert", "qa-alert.wav", 440),
                  (99002, "QA Win", "qa-win.wav", 660),
                  (99003, "QA Warning", "qa-warning.wav", 880))
        for track_id, label, filename, frequency in tracks:
            _write_tone(soundboard_dir / filename, frequency)
            db.execute(
                "INSERT OR REPLACE INTO soundboard_tracks(id,name,filename,mime,created_at) "
                "VALUES(?,?,?,'audio/wav',?)", (track_id, label, filename, _FIXED_AT),
            )
        db.commit()


async def reset_profile(name: str, *, base_root: Path | None = None) -> dict:
    root = profile_root(name, base_root=base_root)
    if root.exists():
        _require_marker(root, name)
        shutil.rmtree(root)
    root.mkdir(parents=True)
    _write_marker(root, name)
    async with _configured_runtime(root):
        from app.database import init_db
        from app.channel_points_tts import ensure_schema
        from app.database import get_db

        await init_db()
        db = await get_db()
        try:
            await ensure_schema(db)
            await db.commit()
        finally:
            await db.close()
    return profile_manifest(name, base_root=base_root)


async def seed_profile(name: str, *, base_root: Path | None = None) -> dict:
    root = profile_root(name, base_root=base_root)
    _require_marker(root, name)
    async with _configured_runtime(root):
        from app.database import init_db
        from app.channel_points_tts import ensure_schema
        from app.database import get_db

        await init_db()
        db = await get_db()
        try:
            await ensure_schema(db)
            await db.commit()
        finally:
            await db.close()
    _seed_database(root / "bot.db", root / "widgets" / "soundboard")
    return profile_manifest(name, base_root=base_root)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def profile_manifest(name: str, *, base_root: Path | None = None) -> dict:
    root = profile_root(name, base_root=base_root)
    _require_marker(root, name)
    db_path = root / "bot.db"
    if not db_path.is_file():
        raise ValueError("QA profile database is missing")
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        accounts = [dict(row) for row in db.execute(
            "SELECT id,nickname,enabled,bot_role FROM accounts ORDER BY id"
        )]
        channels = [dict(row) for row in db.execute(
            "SELECT id,account_id,channel_name,enabled FROM channels ORDER BY id"
        )]
        counts = {
            table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("chat_log", "chat_users", "moderation_events", "recent_events",
                          "donations", "song_request_queue", "widget_bindings", "soundboard_tracks")
        }
        foreign_key_errors = len(db.execute("PRAGMA foreign_key_check").fetchall())
        tokens = [row[0] for row in db.execute("SELECT token FROM accounts ORDER BY id")]
    audio = [
        {"name": path.name, "sha256": _file_sha256(path)}
        for path in sorted((root / "widgets" / "soundboard").glob("*.wav"))
    ]
    semantic = {
        "version": PROFILE_VERSION,
        "accounts": accounts,
        "channels": channels,
        "row_counts": counts,
        "audio": audio,
        "foreign_key_errors": foreign_key_errors,
    }
    fingerprint = hashlib.sha256(
        json.dumps(semantic, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {"profile": name, "root": str(root), **semantic, "fingerprint": fingerprint,
            "safe_tokens": tokens == [NO_OAUTH_TOKEN] * len(tokens)}


def verify_profile(name: str, *, base_root: Path | None = None) -> dict:
    manifest = profile_manifest(name, base_root=base_root)
    account_ids = tuple(item["id"] for item in manifest["accounts"])
    account_names = tuple(item["nickname"] for item in manifest["accounts"])
    if account_ids != ACCOUNT_IDS or account_names != ACCOUNT_NAMES:
        raise ValueError("QA profile must contain exactly the three expected bots")
    if any(item["enabled"] for item in manifest["accounts"]):
        raise ValueError("QA bots must stay disabled from live Twitch autoconnect")
    if not manifest["safe_tokens"]:
        raise ValueError("QA profile contains a non-sentinel token")
    if manifest["foreign_key_errors"]:
        raise ValueError("QA profile has foreign-key errors")
    if len(manifest["audio"]) != 3:
        raise ValueError("QA profile must contain three audio fixtures")
    return manifest


def run(coro):
    return asyncio.run(coro)
