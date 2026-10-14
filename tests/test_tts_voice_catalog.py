"""Focused contracts for the local-only Channel Points voice catalog."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_catalog_lists_registered_and_local_voices_without_provider_calls(monkeypatch):
    from app.database import get_db, init_db
    from app.tts_voice_catalog import list_voice_catalog

    await init_db()
    db = await get_db()
    try:
        await db.execute("INSERT INTO tts_voice_presets (provider, voice_id, label, lang) VALUES ('elevenlabs', 'allowed-el', 'Allowed EL', 'en')")
        await db.execute("INSERT INTO voice_clones (name, provider, voice_id, lang, status) VALUES ('Local voice', 'xtts', 'local-xtts', 'ru', 'ready')")
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('tts_clone_engine', 'f5tts')")
        await db.commit()
    finally:
        await db.close()

    monkeypatch.setattr("app.voice_clone.list_voice_models", lambda: [])
    voices = await list_voice_catalog()
    eleven = next(voice for voice in voices if voice["voice_id"] == "allowed-el")
    local = next(voice for voice in voices if voice["voice_id"] == "local-xtts")
    assert eleven["provider"] == "elevenlabs"
    assert eleven["license"]["id"] == "elevenlabs-library-terms"
    assert set(eleven["labels"]) == {"ru", "en", "ua"}
    assert local["provider"] == "xtts"
    assert local["engine"] == "f5"


async def test_reward_catalog_selection_preserves_provider_and_legacy_fallback(monkeypatch):
    from app import channel_points_tts as cpt
    from app.database import get_db, init_db

    await init_db()
    db = await get_db()
    try:
        await db.execute("INSERT INTO accounts (id, nickname, token) VALUES (91, 'reward', 'tok')")
        await db.commit()
    finally:
        await db.close()
    await cpt.save_config(91, {"enabled": 1, "channel": "reward", "voice": "allowed-el", "voice_provider": "elevenlabs", "cooldown_sec": 0})
    captured = {}

    async def enqueue(self, kind, account_id, channel, text, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("app.audio_queue.AudioQueue.enqueue", enqueue)
    assert await cpt.handle_redemption(91, "ignored", {"reward": {"title": "TTS"}, "user_login": "viewer", "user_input": "hello"})
    assert captured["provider_override"] == "elevenlabs"
    assert captured["voice_override"] == "allowed-el"
    await cpt.save_config(91, {"voice": "legacy-id"})
    assert (await cpt.get_config(91))["voice_provider"] == ""


async def test_catalog_search_matches_local_registry(monkeypatch):
    from app.database import get_db, init_db
    from app.tts_voice_catalog import list_voice_catalog

    await init_db()
    db = await get_db()
    try:
        await db.execute("INSERT INTO tts_voice_presets (provider, voice_id, label, lang) VALUES ('piper', 'searchable', 'Searchable voice', 'ua')")
        await db.commit()
    finally:
        await db.close()
    monkeypatch.setattr("app.voice_clone.list_voice_models", lambda: [])
    assert [voice["voice_id"] for voice in await list_voice_catalog("searchable")] == ["searchable"]


async def test_xtts_catalog_resolves_clone_by_voice_id_before_legacy_name(monkeypatch):
    from app.database import get_db, init_db
    from app.tts_engine import TTSEngine, XTTSProvider, _provider_voice_name

    await init_db()
    db = await get_db()
    try:
        await db.execute("INSERT INTO voice_clones(name,provider,voice_id,sample_path,status) VALUES('Display name','xtts','catalog-id','/tmp/sample.wav','ready')")
        await db.commit()
    finally:
        await db.close()
    monkeypatch.setattr(XTTSProvider, "__init__", lambda self, sample_path, **kwargs: setattr(self, "sample_path", sample_path))
    token = _provider_voice_name.set("catalog-id")
    try:
        provider = await TTSEngine()._get_provider("xtts", 1)
    finally:
        _provider_voice_name.reset(token)
    assert isinstance(provider, XTTSProvider) and provider.sample_path == "/tmp/sample.wav"
