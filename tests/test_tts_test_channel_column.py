"""Guard: «Тест озвучки» в карточке бота не падает 500.

Баг (найден прогоном настроек через API 04.09): `POST /api/accounts/{id}/tts-test`
читал `SELECT channel FROM channels`, тогда как в основной БД колонка называется
`channel_name` (`channel` есть только в отдельной БД chat-logger). Кнопка в панели
всегда отвечала 500 `no such column: channel`, и проверить голос бота было нельзя.

Тест держит контракт с двух сторон: channel scope обязателен, а выбранный канал
должен принадлежать этому боту и быть включён.
"""
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


async def _seed_account(account_id: int, nickname: str, channel: str = "") -> None:
    from app.database import init_db, get_db
    await init_db()
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO accounts (id, nickname, token) VALUES (?, ?, 't')",
            (account_id, nickname))
        if channel:
            await db.execute(
                "INSERT INTO channels (account_id, channel_name, enabled) VALUES (?, ?, 1)",
                (account_id, channel))
        await db.commit()
    finally:
        await db.close()


async def _speak_ok(monkeypatch) -> list[tuple]:
    """Подменяет TTS-движок: сам синтез не нужен, важен выбор канала."""
    calls: list[tuple] = []

    class _Engine:
        async def speak(self, account_id, channel, text):
            calls.append((account_id, channel, text))

    import app.routes_tts_config as mod
    monkeypatch.setattr(mod, "get_tts_engine", lambda: _Engine(), raising=False)
    from app import tts_engine
    monkeypatch.setattr(tts_engine, "get_tts_engine", lambda: _Engine(), raising=False)
    return calls


async def test_tts_test_without_channel_fails_closed(tmp_db, disable_auth, monkeypatch):
    await _seed_account(1, "ttsbot")
    calls = await _speak_ok(monkeypatch)
    async with await _client() as c:
        r = await c.post("/api/accounts/1/tts-test", json={"text": "проверка"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "no such column" not in str(body), "регрессия имени колонки channels"
    assert body == {"error": "channel_required"}
    assert calls == []


async def test_tts_test_uses_selected_channel_of_bot(tmp_db, disable_auth, monkeypatch):
    await _seed_account(2, "ttsbot2", channel="mychannel")
    calls = await _speak_ok(monkeypatch)
    async with await _client() as c:
        r = await c.post(
            "/api/accounts/2/tts-test", json={"channel": "#MYCHANNEL", "text": "проверка"}
        )
    assert r.status_code == 200, r.text
    assert r.json().get("channel") == "mychannel"
    assert calls and calls[0][1] == "mychannel"


async def test_tts_test_rejects_channel_from_other_bot(tmp_db, disable_auth, monkeypatch):
    await _seed_account(2, "ttsbot2", channel="mychannel")
    await _seed_account(4, "ttsbot4", channel="other")
    calls = await _speak_ok(monkeypatch)
    async with await _client() as c:
        r = await c.post(
            "/api/accounts/2/tts-test", json={"channel": "other", "text": "проверка"}
        )
    assert r.json() == {"error": "scope_not_found"}
    assert calls == []


async def test_tts_test_requires_text(tmp_db, disable_auth):
    await _seed_account(3, "ttsbot3")
    async with await _client() as c:
        r = await c.post("/api/accounts/3/tts-test", json={"text": "   "})
    assert r.status_code == 200
    assert r.json() == {"error": "text_required"}
