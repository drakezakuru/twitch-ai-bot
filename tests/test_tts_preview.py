"""Тесты эндпоинта предпрослушивания голоса бота (/api/accounts/{account_id}/tts-preview)."""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


async def _client():
    from app.database import init_db
    from app.routes_tts_config import router
    await init_db()
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_tts_preview_web_speech(tmp_db, disable_auth):
    """Web Speech режим возвращает инструкцию для воспроизведения в браузере."""
    async with await _client() as c:
        r = await c.post("/api/accounts/1/tts-preview", json={
            "provider": "web_speech",
            "voice": "Google русский",
            "emotion": "happy",
            "speed": 1.2,
            "volume": 0.8,
            "text": "Тест звука",
        })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["mode"] == "web_speech"
    assert data["voice"] == "Google русский"
    assert data["text"] == "Тест звука"
    assert data["volume"] == 0.8
    assert data["rate"] > 1.0


async def test_tts_preview_audio_provider(tmp_db, disable_auth, monkeypatch):
    """Серверный синтезатор возвращает base64 аудио."""
    class FakeProvider:
        async def synthesize(self, text: str, voice: str, emotion: str, speed: float) -> bytes:
            return b"RIFFfake_wav_data"

    class FakeEngine:
        async def _get_tts_config(self, account_id: int):
            return {"provider": "piper", "voice": "ru_RU-dmitri-medium"}

        async def _get_provider(self, name: str, account_id: int):
            return FakeProvider()

    from app import tts_engine
    monkeypatch.setattr(tts_engine, "get_tts_engine", lambda: FakeEngine())

    async with await _client() as c:
        r = await c.post("/api/accounts/1/tts-preview", json={
            "provider": "piper",
            "voice": "ru_RU-dmitri-medium",
            "text": "Привет мир",
        })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["mode"] == "audio"
    assert data["mime"] == "audio/wav"
    assert len(data["audio_b64"]) > 0
