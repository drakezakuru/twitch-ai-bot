"""PLAN_FEEDBACK_2908 §4.4: клип-детектор per-bot.

GET/PUT /api/bot/clip-detector/config с account_id — настройки конкретного
бота (per-account analyzer settings); без — глобальные settings (back-compat).
check-эндпоинт: per-bot значения имеют приоритет, глобальные — fallback.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


async def test_clip_config_per_bot_roundtrip(tmp_db, disable_auth):
    from app.database import init_db
    from app.routes import router
    from fastapi import FastAPI

    await init_db()
    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # глобальный конфиг
        await client.put("/api/bot/clip-detector/config",
                         json={"threshold_multiplier": 4.0, "window_sec": 90})
        glob = (await client.get("/api/bot/clip-detector/config")).json()
        assert glob["threshold_multiplier"] == 4.0
        assert glob["window_sec"] == 90

        # per-bot: пока не задан — отображается глобальное
        got = (await client.get("/api/bot/clip-detector/config?account_id=7")).json()
        assert got["account_id"] == 7
        assert got["threshold_multiplier"] == 4.0  # fallback на глобальное

        # per-bot roundtrip
        resp = await client.put("/api/bot/clip-detector/config", json={
            "account_id": 7, "threshold_multiplier": 2.5,
            "window_sec": 45, "cooldown_sec": 15,
        })
        assert resp.status_code == 200 and resp.json()["ok"] is True

        got = (await client.get("/api/bot/clip-detector/config?account_id=7")).json()
        assert got["threshold_multiplier"] == 2.5
        assert got["window_sec"] == 45
        assert got["cooldown_sec"] == 15

        # глобальное не затёрто per-bot значениями
        glob = (await client.get("/api/bot/clip-detector/config")).json()
        assert glob["threshold_multiplier"] == 4.0
        assert glob["window_sec"] == 90

        # другой бот — по-прежнему глобальный fallback
        got2 = (await client.get("/api/bot/clip-detector/config?account_id=8")).json()
        assert got2["threshold_multiplier"] == 4.0


async def test_update_settings_accepts_clip_keys():
    """§4.4: update_settings разрешает clip_* ключи, отсутствующие в дефолтах."""
    from app.chat_analyzer import ChatAnalyzer

    ca = ChatAnalyzer.__new__(ChatAnalyzer)  # без __init__ (не нужен для settings)
    ca._settings = {}
    s = ca.update_settings(42, {"clip_threshold_multiplier": 2.5, "clip_window_sec": 45})
    assert s["clip_threshold_multiplier"] == 2.5
    assert s["clip_window_sec"] == 45
    # несуществующий ключ по-прежнему отбрасывается
    s2 = ca.update_settings(42, {"bogus_key": 1})
    assert "bogus_key" not in s2
