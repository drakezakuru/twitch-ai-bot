"""Тесты песочницы ответа бота (/api/accounts/{account_id}/sandbox-reply)."""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


async def _client():
    from app.database import init_db
    from app.sandbox_routes import router
    await init_db()
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed_account(account_id: int, nickname: str, channel: str = "mychannel") -> None:
    from app.database import init_db, get_db
    await init_db()
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO accounts (id, nickname, token, enabled) VALUES (?, ?, 't', 1)",
            (account_id, nickname),
        )
        if channel:
            await db.execute(
                "INSERT INTO channels (account_id, channel_name, enabled) VALUES (?, ?, 1)",
                (account_id, channel),
            )
        await db.commit()
    finally:
        await db.close()


async def test_sandbox_reply_validation(tmp_db, disable_auth):
    """Пустой текст возвращает ошибку валидации."""
    await _seed_account(1, "testerbot")
    async with await _client() as c:
        r = await c.post("/api/accounts/1/sandbox-reply", json={"text": ""})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert "error" in data


async def test_sandbox_reply_success(tmp_db, disable_auth, monkeypatch):
    """Песочница успешно генерирует ответ без отправки в Twitch."""
    await _seed_account(2, "smartbot", channel="coolchannel")

    class FakeAIService:
        provider = "fake_ai"

        def get_account_override(self, account_id: int):
            return None

        async def generate_text(self, prompt: str, system: str, account_id: int, channel: str, temperature: float = 0.5):
            return "Привет! Я тестовый бот, рад тебя видеть."

    from app import server
    monkeypatch.setattr(server, "ai_service", FakeAIService())

    async with await _client() as c:
        r = await c.post("/api/accounts/2/sandbox-reply", json={
            "text": "Привет бот!",
            "author": "Viewer99",
            "channel": "coolchannel",
        })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["reply"] == "Привет! Я тестовый бот, рад тебя видеть."
    assert data["author"] == "Viewer99"
    assert data["channel"] == "coolchannel"
    assert data["latency_ms"] >= 0
    assert "moderation" in data
    assert data["moderation"]["flagged"] is False


async def test_sandbox_moderation_flagged(tmp_db, disable_auth, monkeypatch):
    """Песочница детектирует нарушения модерации во входящем сообщении."""
    await _seed_account(3, "modbot", channel="modchannel")

    from app.database import get_db
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO moderation_rules (account_id, channel, name, category, pattern, action, severity, enabled) "
            "VALUES (3, 'modchannel', 'Тестовое правило', 'custom', 'запретка', 'block', 5, 1)"
        )
        await db.commit()
    finally:
        await db.close()

    class FakeAIService:
        provider = "fake_ai"

        def get_account_override(self, account_id: int):
            return None

        async def generate_text(self, **kwargs):
            return "Ответ"

    from app import server
    monkeypatch.setattr(server, "ai_service", FakeAIService())

    async with await _client() as c:
        r = await c.post("/api/accounts/3/sandbox-reply", json={
            "text": "Эй ты запретка",
            "author": "Troll",
            "channel": "modchannel",
        })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["moderation"]["flagged"] is True
    assert data["moderation"]["action"] == "block"


async def test_sandbox_save_style(tmp_db, disable_auth):
    """Сохранение удачного ответа из песочницы в few-shot примеры стиля."""
    await _seed_account(4, "stylishbot", channel="streamchannel")
    async with await _client() as c:
        # Проверка валидации пустого ответа
        r_err = await c.post("/api/accounts/4/sandbox-save-style", json={"reply": ""})
        assert r_err.status_code == 200
        assert r_err.json()["ok"] is False

        # Успешное сохранение
        r_ok = await c.post("/api/accounts/4/sandbox-save-style", json={
            "reply": "Отличная игра, стример затащил!",
            "trigger_msg": "Как игра?",
            "channel": "streamchannel",
        })
        assert r_ok.status_code == 200, r_ok.text
        data = r_ok.json()
        assert data["ok"] is True
        ex_id = data["id"]
        assert ex_id > 0

    from app.ai_quality_db import list_style_examples
    examples = await list_style_examples(4, channel="streamchannel")
    assert any(e["id"] == ex_id and "Отличная игра" in e["message"] for e in examples)


async def test_sandbox_context_status_and_flow(tmp_db, disable_auth, monkeypatch):
    """Песочница обновляет статус буфера памяти и очищает его."""
    await _seed_account(5, "memorybot", channel="memchannel")

    class FakeAIService:
        provider = "fake_ai"

        def get_account_override(self, account_id: int):
            return None

        async def generate_text(self, prompt: str, system: str, **kwargs):
            return "Ответ на реплику"

    from app import server
    monkeypatch.setattr(server, "ai_service", FakeAIService())

    async with await _client() as c:
        # Изначально статус памяти пустой (или сброшен)
        await c.post("/api/accounts/5/clear-context", json={"channel": "memchannel"})
        r_st1 = await c.get("/api/accounts/5/context-status?channel=memchannel")
        assert r_st1.status_code == 200
        assert r_st1.json()["count"] == 0

        # Отправляем сообщение через песочницу
        r_rep = await c.post("/api/accounts/5/sandbox-reply", json={
            "text": "Привет бот!",
            "author": "Viewer1",
            "channel": "memchannel",
        })
        assert r_rep.status_code == 200
        assert r_rep.json()["context_count"] == 2  # user + bot

        # Проверяем эндпоинт статуса
        r_st2 = await c.get("/api/accounts/5/context-status?channel=memchannel")
        assert r_st2.status_code == 200
        assert r_st2.json()["count"] == 2

        # Сбрасываем контекст
        r_clr = await c.post("/api/accounts/5/clear-context", json={"channel": "memchannel"})
        assert r_clr.status_code == 200
        assert r_clr.json()["cleared_messages"] == 2

        # Проверяем, что стало 0
        r_st3 = await c.get("/api/accounts/5/context-status?channel=memchannel")
        assert r_st3.status_code == 200
        assert r_st3.json()["count"] == 0


async def test_sandbox_reply_variation(tmp_db, disable_auth, monkeypatch):
    """Флаг variation передаёт повышенную температуру и помечает ответ в ответе."""
    await _seed_account(6, "varybot", channel="varychannel")

    captured_temp = []

    class FakeAIService:
        provider = "fake_ai"

        def get_account_override(self, account_id: int):
            return None

        async def generate_text(self, **kwargs):
            captured_temp.append(kwargs.get("temperature"))
            return "Вариативный ответ бота"

    from app import server
    monkeypatch.setattr(server, "ai_service", FakeAIService())

    async with await _client() as c:
        r = await c.post("/api/accounts/6/sandbox-reply", json={
            "text": "Расскажи шутку",
            "author": "ViewerX",
            "channel": "varychannel",
            "variation": True,
        })
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["is_variation"] is True
        assert captured_temp and captured_temp[-1] > 0.5
