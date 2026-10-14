"""Track 6.6: dynamic read-only TTS routing map."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
KEYS = [
    "settings.tts_map_title",
    "settings.tts_map_hint",
    "settings.tts_source_bot",
    "settings.tts_source_mod_announcement",
    "settings.tts_source_twitch_mod",
    "settings.tts_source_chat",
    "settings.tts_source_reward",
    "settings.tts_output_unverified",
    "settings.tts_policy_legacy_account",
]


def test_tts_map_present_in_settings_card():
    # DEC-OWNER-016 (Q16 F3): ttsRoutingMap переехала из настроек в карточку бота (bots.html)
    html = (ROOT / "templates" / "partials" / "bots.html").read_text(encoding="utf-8")
    assert 'id="ttsRoutingMap"' in html
    assert "loadTTSRoutingMap" in (ROOT / "static" / "app" / "04_chat_settings.js").read_text(encoding="utf-8")


def test_tts_map_i18n_all_langs():
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    for key in KEYS:
        found = len(re.findall(rf"'{re.escape(key)}':", js)) if (re := __import__("re")) else 0
        assert found >= 3, f"{key}: переводов {found}, нужно ≥3 (ru/en/ua)"


@pytest.mark.asyncio
async def test_routing_map_is_exact_scoped_and_resolves_voices():
    from app.database import get_db, init_db
    from app.tts_routing_routes import build_tts_routing_map

    await init_db()
    db = await get_db()
    try:
        await db.executemany(
            "INSERT INTO accounts (id, nickname, token, bot_role, role_config_json) VALUES (?, ?, 'tok', ?, ?)",
            [(1, "modbot", "moderator", json.dumps({"moderator": {"tts_announce": True}})),
             (2, "chatbot", "chatter", "{}")],
        )
        await db.executemany(
            "INSERT INTO channels (account_id, channel_name) VALUES (?, ?)",
            [(1, "#Shared"), (2, "SHARED")],
        )
        await db.execute("INSERT INTO tts_voice_presets (provider, voice_id, label) VALUES ('piper', 'known', 'Known voice')")
        await db.execute("UPDATE tts_settings SET provider='piper', voice='known' WHERE id=1")
        await db.executemany(
            "INSERT INTO tts_bot_config (account_id, enabled, provider, voice) VALUES (?, 1, ?, ?)",
            [(1, "", ""), (2, "piper", "missing")],
        )
        await db.execute("INSERT INTO channel_overrides (account_id, channel, overrides_json) VALUES (1, 'shared', '{\"tts_mute\": true}')")
        await db.commit()
    finally:
        await db.close()

    data = await build_tts_routing_map()
    mod_reply = next(row for row in data["rows"] if row["account"]["id"] == 1 and row["source"] == "bot_reply")
    chatter = next(row for row in data["rows"] if row["account"]["id"] == 2 and row["source"] == "bot_reply")
    announcement = next(row for row in data["rows"] if row["source"] == "moderation_announcement")
    assert mod_reply["channel"] == chatter["channel"] == "shared"
    assert mod_reply["policy"]["channel_muted"] is True
    assert mod_reply["voice"] == {"provider": "piper", "id": "known", "label": "Known voice", "resolution": "preset", "inherited": True}
    assert chatter["voice"]["resolution"] == "unknown_id"
    assert announcement["policy"]["tts_announce"] is True
    assert data["obs_telemetry"] == "unavailable"


@pytest.mark.asyncio
async def test_reward_override_is_visible_with_legacy_scope():
    from app.channel_points_tts import ensure_schema
    from app.database import get_db, init_db
    from app.tts_routing_routes import build_tts_routing_map

    await init_db()
    db = await get_db()
    try:
        await db.execute("INSERT INTO accounts (id, nickname, token) VALUES (7, 'rewards', 'tok')")
        await db.execute("INSERT INTO channels (account_id, channel_name) VALUES (7, 'main')")
        await db.execute("INSERT INTO tts_bot_config (account_id, enabled, provider, voice) VALUES (7, 1, 'piper', 'bot_voice')")
        await ensure_schema(db)
        await db.execute("INSERT INTO channel_points_tts_config (account_id, enabled, channel, voice) VALUES (7, 1, '#Rewards', 'reward_voice')")
        await db.commit()
    finally:
        await db.close()

    rows = (await build_tts_routing_map())["rows"]
    reward = next(row for row in rows if row["source"] == "channel_points_reward" and row["channel"] == "rewards")
    assert reward["policy"]["storage"] == "legacy_per_account"
    assert reward["voice"]["id"] == "reward_voice"
    assert reward["voice"]["resolution"] == "unknown_id"
    assert reward["voice"]["inherited"] is False
