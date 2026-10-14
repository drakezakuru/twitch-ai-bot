"""PLAN_FEEDBACK_2908 §7.1 §9: «Когда бот отвечает» — новые настройки.

- reply_to_mentions toggle (bot_attention_config) реально гейтит упоминания;
- dont_interrupt_streamer_sec: после реплики стримера бот молчит;
- tts_reply_percent: 0 = не озвучивать, 100 = всегда.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


async def test_attention_config_roundtrip_new_fields(tmp_db, disable_auth):
    from app.database import init_db
    from app.routes import router
    from fastapi import FastAPI

    await init_db()
    from app.database import get_db as _gdb
    _db = await _gdb()
    try:
        await _db.execute("INSERT OR IGNORE INTO accounts (id, nickname, token) VALUES (21, 'b21', 't')")
        await _db.commit()
    finally:
        await _db.close()
    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put("/api/accounts/21/attention-config", json={
            "attention_mode": "everyone",
            "dont_interrupt_streamer_sec": 45,
            "tts_reply_percent": 25,
            "reply_to_mentions": 0,
        })
        assert resp.status_code == 200, resp.text
        got = (await client.get("/api/accounts/21/attention-config")).json()["config"]
        assert got["dont_interrupt_streamer_sec"] == 45
        assert got["tts_reply_percent"] == 25
        assert got["reply_to_mentions"] == 0


async def test_interrupt_guard_blocks_auto_reply(tmp_db, monkeypatch):
    import time
    from app.database import init_db
    from app.chat_analyzer import ChatAnalyzer

    await init_db()
    ca = ChatAnalyzer.__new__(ChatAnalyzer)
    ca._settings = {}
    ca._last_streamer_msg = {}

    # стример писал 3 сек назад; guard 10 сек → автоответ блокирован
    ca._last_streamer_msg[(5, "#wow")] = time.time() - 3

    logs = []
    async def fake_merged(account_id, channel, base):
        return dict(base)
    monkeypatch.setattr(ca, "_merged_settings", fake_merged)
    async def fake_log(category, message, account_id=None, channel=None, **k):
        logs.append((category, message))
    monkeypatch.setattr("app.chat_analyzer.ai_log", fake_log)

    ca.get_settings(5)  # инициализация дефолтов
    ca._settings[5]["dont_interrupt_streamer_sec"] = 10

    await ca._generate_and_send(5, "#wow", "bot", "viewer", "text", is_mention=False)
    assert any(cat == "interrupt_guard" for cat, _ in logs), \
        "guard должен сработать и залогировать interrupt_guard"

    # упоминание guard НЕ проходит — interrupt_guard не появится от is_mention=True
    logs.clear()
    ca._last_streamer_msg[(5, "#wow")] = time.time() - 3
    try:
        await ca._generate_and_send(5, "#wow", "bot", "viewer", "@bot привет", is_mention=True)
    except Exception:
        pass  # дальше guard пойдёт в AI-ветку — там заглушек нет, падение допустимо
    assert not any(cat == "interrupt_guard" for cat, _ in logs), \
        "упоминания не должны гейтиться guard-ом"


async def test_tts_should_speak_percent(tmp_db):
    from app.database import init_db, get_db
    from app.chat_analyzer import ChatAnalyzer

    await init_db()
    db = await get_db()
    try:
        await db.execute("INSERT OR IGNORE INTO accounts (id, nickname, token) VALUES (31, 'b31', 't')")
        await db.execute(
            "INSERT OR IGNORE INTO bot_attention_config (account_id, tts_reply_percent) VALUES (31, 0)"
        )
        await db.commit()
    finally:
        await db.close()

    ca = ChatAnalyzer.__new__(ChatAnalyzer)
    assert await ca._tts_should_speak(31, "#x") is False, "0% → никогда не озвучивать"

    # без строки конфига → True (дефолт 100%)
    assert await ca._tts_should_speak(32, "#x") is True
