"""PLAN_FEEDBACK_3008 §2.3: live-сводки Summarizer per-channel с наследованием."""

from __future__ import annotations

import json

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app import database
from app.brain_routes import router as brain_router

# ВАЖНО: app.server не импортируем на уровне модуля — коллекция тестов до
# запуска сломает изоляцию стабов app.server в соседних файлах (см. conftest
# _restore_app_server_module); берём chat_analyzer внутри тестов.


@pytest_asyncio.fixture(autouse=True)
async def _schema(tmp_db, disable_auth):
    await database.init_db()
    db = await database.get_db()
    try:
        await db.execute("INSERT OR IGNORE INTO accounts (id, nickname, token) VALUES (1, 'bot', 'tok')")
        await db.execute(
            "INSERT OR IGNORE INTO channels (account_id, channel_name, enabled) VALUES (1, 'alekzz', 1)"
        )
        await db.commit()
    finally:
        await db.close()


def _ca():
    from app.server import chat_analyzer
    return chat_analyzer


@pytest.mark.asyncio
async def test_live_loop_uses_channel_override_with_inheritance(tmp_db):
    """summarizer_live_enabled в CHANNEL_MERGE_KEYS: override канала побеждает,
    у остальных каналов — настройка бота."""
    ca = _ca()
    assert "summarizer_live_enabled" in ca.CHANNEL_MERGE_KEYS
    assert "summarizer_live_lang" in ca.CHANNEL_MERGE_KEYS
    base = ca.get_settings(1)
    base["summarizer_live_enabled"] = False
    # без override — настройка бота (False)
    merged = await ca._merged_settings(1, "other", base)
    assert merged["summarizer_live_enabled"] is False
    # с override — значение канала побеждает
    db = await database.get_db()
    try:
        await db.execute(
            "INSERT INTO channel_overrides (account_id, channel, overrides_json, enabled) "
            "VALUES (1, 'alekzz', ?, 1)",
            (json.dumps({"summarizer_live_enabled": True, "summarizer_live_lang": "en"}),),
        )
        await db.commit()
    finally:
        await db.close()
    ca.invalidate_channel_overrides(1, "alekzz")
    merged = await ca._merged_settings(1, "alekzz", base)
    assert merged["summarizer_live_enabled"] is True
    assert merged["summarizer_live_lang"] == "en"


@pytest.mark.asyncio
async def test_summarizer_settings_channel_roundtrip(tmp_db):
    ca = _ca()
    ca.update_settings(1, {"summarizer_live_enabled": False, "summarizer_live_lang": "ru"})
    app = FastAPI()
    app.include_router(brain_router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # уровень бота
        r = await client.get("/api/accounts/1/summarizer/settings")
        assert r.json()["scope"] == "bot" and r.json()["live_enabled"] is False
        # включаем live-сводки только для канала alekzz
        r = await client.post(
            "/api/accounts/1/summarizer/settings",
            json={"channel": "#alekzz", "live_enabled": True, "live_lang": "en"},
        )
        assert r.json()["ok"] is True and r.json()["scope"] == "channel"
        # GET по каналу: эффективные значения из override
        r = await client.get("/api/accounts/1/summarizer/settings?channel=alekzz")
        body = r.json()
        assert body["scope"] == "channel" and body["live_enabled"] is True and body["live_lang"] == "en"
        assert body["inherited_enabled"] is False
        # GET без канала: настройка бота не тронута
        r = await client.get("/api/accounts/1/summarizer/settings")
        assert r.json()["scope"] == "bot" and r.json()["live_enabled"] is False


@pytest.mark.asyncio
async def test_channel_override_merges_without_clobbering(tmp_db):
    """Summarizer-ключи дописываются в существующие overrides канала, а не заменяют их."""
    db = await database.get_db()
    try:
        await db.execute(
            "INSERT INTO channel_overrides (account_id, channel, overrides_json, enabled) "
            "VALUES (1, 'alekzz', ?, 1)",
            (json.dumps({"cooldown": 30}),),
        )
        await db.commit()
    finally:
        await db.close()
    ca = _ca()
    ca.invalidate_channel_overrides(1, "alekzz")
    app = FastAPI()
    app.include_router(brain_router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/accounts/1/summarizer/settings",
            json={"channel": "alekzz", "live_enabled": True},
        )
        assert r.json()["ok"] is True
    ca.invalidate_channel_overrides(1, "alekzz")
    ov = await ca._channel_overrides_cached(1, "alekzz")
    assert ov["cooldown"] == 30
    assert ov["summarizer_live_enabled"] is True
