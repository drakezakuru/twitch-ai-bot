"""О2 PLAN.md (§12.1 ОСТАТОК): статус последнего TTS-синтеза + тест-кнопки в чате.

Проверка, что хвост уже закрыт (сделано 29-31.08 — маркеры «§7.1 §12.1»
в routes.py / app.js / bots.html) и не регресснет.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport
from tests import _panel_js

pytestmark = pytest.mark.asyncio


async def _app():
    from app.database import init_db, get_db
    from app.routes import router
    await init_db()
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed(account_id: int, nickname: str):
    from app.database import init_db
    await init_db()
    from app.database import get_db
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO accounts (id, nickname, token) VALUES (?, ?, 't')",
            (account_id, nickname))
        await db.commit()
    finally:
        await db.close()


async def test_tts_last_empty(tmp_db, disable_auth):
    """Нет синтезов → has=False, 200."""
    async with await _app() as c:
        r = await c.get("/api/accounts/1/tts-last")
        assert r.status_code == 200
        assert r.json() == {"ok": True, "has": False}


async def test_tts_last_returns_last_entry(tmp_db, disable_auth):
    """Последняя запись категории 'tts' из bot_logs попадает в ответ (уровень+причина)."""
    await _seed(1, "b1")
    from app.database import get_db
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO bot_logs (account_id, channel, category, level, message, details) "
            "VALUES (1, 'ch1', 'tts', 'error', 'TTS error (piper): модель не найдена', '{}')")
        await db.commit()
    finally:
        await db.close()
    async with await _app() as c:
        r = await c.get("/api/accounts/1/tts-last")
        assert r.status_code == 200
        j = r.json()
        assert j["has"] is True
        assert j["level"] == "error"
        assert "piper" in j["message"]


async def test_tts_last_ignores_other_categories(tmp_db, disable_auth):
    """Логи других категорий не подмешиваются в TTS-статус."""
    await _seed(2, "b2")
    from app.database import get_db
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO bot_logs (account_id, channel, category, level, message, details) "
            "VALUES (2, 'ch1', 'chat', 'info', 'обычное сообщение', '{}')")
        await db.commit()
    finally:
        await db.close()
    async with await _app() as c:
        r = await c.get("/api/accounts/2/tts-last")
        assert r.status_code == 200
        assert r.json() == {"ok": True, "has": False}


def test_ui_wiring_present():
    """UI-обвязка: статус-строка в карточке бота + 🔊-кнопки в чате + i18n."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    tpl = (root / "templates" / "partials" / "bots.html").read_text()
    assert 'id="botTTSLastStatus"' in tpl
    js = _panel_js.panel_js()
    # статус последнего синтеза
    assert "tts-last" in js and "tts.last_status" in js
    assert js.count("'tts.last_status'") >= 3
    # кнопки 🔊 в чате: обычный голос + голос бота через OBS
    assert "testChatTTS" in js and "testBotChatTTS" in js
    assert "tts-test" in js
