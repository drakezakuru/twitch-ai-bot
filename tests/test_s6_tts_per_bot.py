"""PLAN_FEEDBACK_2908 §6: per-bot TTS end-to-end.

tts_bot_config бота (provider/voice) применяется в TTSEngine.speak() —
unit с фейковым провайдером и заглушкой broadcast.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


class _FakeProvider:
    def __init__(self):
        self.calls = []

    async def synthesize(self, text, voice, emotion, speed):
        self.calls.append({"text": text, "voice": voice, "emotion": emotion, "speed": speed})
        return b"fake_audio"


async def _seed_bot_config(account_id: int, provider: str, voice: str) -> None:
    from app.database import get_db

    db = await get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO accounts (id, nickname, token) VALUES (?, ?, ?)",
            (account_id, f"ttsbot{account_id}", "tok"),
        )
        await db.execute(
            "INSERT OR REPLACE INTO tts_bot_config "
            "(account_id, enabled, provider, voice, emotion_preset, volume, speed) "
            "VALUES (?, 1, ?, ?, 'neutral', 1.0, 1.0)",
            (account_id, provider, voice),
        )
        await db.commit()
    finally:
        await db.close()


async def test_per_bot_voice_used_in_speak(tmp_db, monkeypatch):
    from app.database import init_db
    from app.tts_engine import TTSEngine

    await init_db()
    await _seed_bot_config(11, "piper", "ru_RU-test-medium")

    engine = TTSEngine()
    fake = _FakeProvider()
    async def fake_get_provider(name, account_id):
        return fake if name == "piper" else None
    monkeypatch.setattr(engine, "_get_provider", fake_get_provider)

    captured = {}
    async def fake_broadcast(**kwargs):
        captured.update(kwargs)
    monkeypatch.setattr("app.tts_engine.broadcast_tts_event", fake_broadcast)

    await engine.speak(11, "#test", "привет из теста")

    assert len(fake.calls) == 1, "синтез должен произойти per-bot провайдером"
    assert fake.calls[0]["voice"] == "ru_RU-test-medium", "per-bot голос не применился"
    assert captured.get("provider") == "piper"
    assert captured.get("account_id") == 11


async def test_inherits_global_when_bot_config_empty(tmp_db, monkeypatch):
    from app.database import init_db, get_db
    from app.tts_engine import TTSEngine

    await init_db()
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO accounts (id, nickname, token) VALUES (12, 'ttsbot12', 'tok')"
        )
        await db.execute(
            "INSERT OR REPLACE INTO tts_settings (id, provider, voice, speed, volume) "
            "VALUES (1, 'piper', 'global_voice', 1.0, 1.0)"
        )
        # бот включил TTS (opt-in), провайдер пустой = «наследовать глобальный»
        await db.execute(
            "INSERT OR REPLACE INTO tts_bot_config "
            "(account_id, enabled, provider, voice, emotion_preset, volume, speed) "
            "VALUES (12, 1, '', '', 'neutral', 1.0, 1.0)"
        )
        await db.commit()
    finally:
        await db.close()

    engine = TTSEngine()
    fake = _FakeProvider()
    async def fake_get_provider(name, account_id):
        return fake if name == "piper" else None
    monkeypatch.setattr(engine, "_get_provider", fake_get_provider)
    async def fake_broadcast(**kwargs):
        pass
    monkeypatch.setattr("app.tts_engine.broadcast_tts_event", fake_broadcast)

    await engine.speak(12, "#test", "глобальный тест")
    assert fake.calls and fake.calls[0]["voice"] == "global_voice", \
        "пустой per-bot конфиг должен наследовать глобальный голос"
