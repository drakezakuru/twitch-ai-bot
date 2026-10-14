"""Track 6.6: exact-scoped approved TTS voice policy."""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.asyncio


async def _seed() -> None:
    from app.database import get_db, init_db

    await init_db()
    db = await get_db()
    try:
        await db.executemany(
            "INSERT INTO accounts (id, nickname, token) VALUES (?, ?, 'tok')",
            [(1, "one"), (2, "two")],
        )
        await db.executemany(
            "INSERT INTO channels (account_id, channel_name) VALUES (?, ?)",
            [(1, "#Shared"), (2, "shared")],
        )
        await db.execute(
            "INSERT INTO tts_voice_presets (provider, voice_id, label) VALUES ('piper', 'voice-1', 'Voice One')"
        )
        await db.commit()
    finally:
        await db.close()


async def test_owner_alias_and_policy_are_exact_scoped(monkeypatch):
    from app.tts_voice_policy import api_put_alias, api_put_source_policy, get_scope_policy

    await _seed()
    monkeypatch.setattr("app.tts_voice_policy._audit", lambda *args: _noop())
    assert (await api_put_alias(1, "#SHARED", "calm", {"provider": "piper", "voice_id": "voice-1"}))["ok"]
    assert (await api_put_source_policy(1, "SHARED", "twitch_moderator_message", {
        "enabled": True, "allowed_role": "moderator", "default_alias": "calm",
        "allow_voice_choice": True, "cooldown_sec": 7, "max_per_minute": 4,
        "max_length": 140, "blacklist": "blocked",
    }))["ok"]

    own = await get_scope_policy(1, "shared")
    other = await get_scope_policy(2, "shared")
    assert own["aliases"][0]["alias"] == "calm"
    assert own["policies"][0]["allowed_role"] == "moderator"
    assert own["policies"][0]["cooldown_sec"] == 7
    assert other["aliases"] == [] and other["policies"] == []


async def test_unregistered_voice_and_cross_scope_default_are_rejected(monkeypatch):
    from app.tts_voice_policy import api_put_alias, api_put_source_policy

    await _seed()
    monkeypatch.setattr("app.tts_voice_policy._audit", lambda *args: _noop())
    unknown = await api_put_alias(1, "shared", "raw", {"provider": "piper", "voice_id": "raw-id"})
    cross_scope = await api_put_source_policy(2, "shared", "channel_points_reward", {
        "enabled": True, "default_alias": "calm",
    })
    assert unknown == {"ok": False, "error": "voice_not_registered"}
    assert cross_scope == {"ok": False, "error": "unapproved_default_alias"}


async def test_moderator_preferences_accept_only_approved_aliases(monkeypatch):
    from app.database import get_db
    from app.tts_voice_policy import api_put_alias, set_moderator_preferences

    await _seed()
    monkeypatch.setattr("app.tts_voice_policy._audit", lambda *args: _noop())
    await api_put_alias(1, "shared", "calm", {"provider": "piper", "voice_id": "voice-1"})
    saved = await set_moderator_preferences(
        1, "#SHARED", "twitch-42", default_alias="calm", favorites=["calm", "calm"]
    )
    rejected = await set_moderator_preferences(
        2, "shared", "twitch-42", default_alias="calm", favorites=[]
    )
    assert saved == {"ok": True, "default_alias": "calm", "favorites": ["calm"]}
    assert rejected == {"ok": False, "error": "unapproved_alias"}
    db = await get_db()
    try:
        row = await (await db.execute(
            "SELECT favorite_aliases_json FROM tts_moderator_voice_preferences WHERE account_id=1 AND channel='shared'"
        )).fetchone()
        assert json.loads(row["favorite_aliases_json"]) == ["calm"]
    finally:
        await db.close()


async def test_viewer_cannot_choose_global_voice_by_policy_shape(monkeypatch):
    from app.tts_voice_policy import api_put_source_policy

    await _seed()
    monkeypatch.setattr("app.tts_voice_policy._audit", lambda *args: _noop())
    result = await api_put_source_policy(1, "shared", "ordinary_chat", {
        "enabled": True, "allowed_role": "viewer", "allow_voice_choice": False,
    })
    assert result["ok"] is True


async def test_runtime_enforces_role_alias_limits_blacklist_and_scope(monkeypatch):
    from app.tts_voice_policy import (
        api_put_alias, api_put_source_policy, authorize_tts, reset_runtime_state,
    )

    await _seed()
    audits = []
    async def fake_audit(action, detail):
        audits.append((action, detail))
    monkeypatch.setattr("app.tts_voice_policy._audit", fake_audit)
    await api_put_alias(1, "shared", "calm", {"provider": "piper", "voice_id": "voice-1"})
    await api_put_source_policy(1, "shared", "twitch_moderator_message", {
        "enabled": True, "allowed_role": "moderator", "default_alias": "calm",
        "allow_voice_choice": True, "cooldown_sec": 10, "max_per_minute": 2,
        "max_length": 8, "blacklist": "bad",
    })
    reset_runtime_state()

    denied_role = await authorize_tts(1, "#SHARED", "twitch_moderator_message", actor_role="viewer", actor_id="u", text="ok")
    denied_word = await authorize_tts(1, "shared", "twitch_moderator_message", actor_role="moderator", actor_id="m", text="bad")
    accepted = await authorize_tts(1, "SHARED", "twitch_moderator_message", actor_role="moderator", actor_id="m", text="hello")
    cooldown = await authorize_tts(1, "shared", "twitch_moderator_message", actor_role="moderator", actor_id="m", text="again")
    legacy_other_scope = await authorize_tts(2, "shared", "twitch_moderator_message", actor_role="moderator", actor_id="m", text="hello")
    assert denied_role["reason"] == "role_denied"
    assert denied_word["reason"] == "blacklist"
    assert accepted["provider_override"] == "piper"
    assert accepted["voice_override"] == "voice-1"
    assert cooldown["reason"] == "cooldown"
    assert legacy_other_scope == {"ok": True, "legacy": True, "provider_override": "", "voice_override": ""}
    assert any("result=accepted" in detail for action, detail in audits if action == "tts_policy_command")


async def test_reward_runtime_forwards_approved_provider_and_voice(monkeypatch):
    from app import channel_points_tts
    from app.tts_voice_policy import api_put_alias, api_put_source_policy, reset_runtime_state

    await _seed()
    monkeypatch.setattr("app.tts_voice_policy._audit", lambda *args: _noop())
    await api_put_alias(1, "shared", "calm", {"provider": "piper", "voice_id": "voice-1"})
    await api_put_source_policy(1, "shared", "channel_points_reward", {
        "enabled": True, "allowed_role": "viewer", "default_alias": "calm",
        "cooldown_sec": 0,
    })
    await channel_points_tts.save_config(1, {"enabled": 1, "channel": "shared", "cooldown_sec": 0})
    reset_runtime_state()
    captured = {}
    async def fake_enqueue(kind, account_id, channel, text, **payload):
        captured.update(payload)
    monkeypatch.setattr("app.audio_queue.AudioQueue.enqueue", lambda self, *args, **kwargs: fake_enqueue(*args, **kwargs))

    ok = await channel_points_tts.handle_redemption(1, "shared", {
        "reward": {"title": "Speak"}, "user_id": "42", "user_login": "mod", "user_input": "hello",
    })
    assert ok is True
    assert captured["provider_override"] == "piper"
    assert captured["voice_override"] == "voice-1"


async def test_tts_engine_uses_provider_override(monkeypatch):
    from app.database import get_db
    from app.tts_engine import TTSEngine

    await _seed()
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO tts_bot_config (account_id, enabled, provider, voice) VALUES (1, 1, 'web_speech', '')"
        )
        await db.commit()
    finally:
        await db.close()
    engine = TTSEngine()
    calls = []
    class Provider:
        async def synthesize(self, text, voice, emotion, speed):
            calls.append((voice, text))
            return b"audio"
    async def fake_provider(name, account_id):
        assert name == "piper"
        return Provider()
    monkeypatch.setattr(engine, "_get_provider", fake_provider)
    monkeypatch.setattr("app.tts_engine.broadcast_tts_event", lambda **kwargs: _noop())
    await engine.speak(1, "shared", "hello", provider_override="piper", voice_override="voice-1")
    assert calls == [("voice-1", "hello")]


async def _noop():
    return None
