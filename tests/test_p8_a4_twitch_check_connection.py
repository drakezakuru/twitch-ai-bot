"""P8-A4: «Проверить подключение» (Twitch API) — честный вывод ошибки.

Раньше: сетевой сбой падал 500-й (httpx.ConnectError неотловлен), 401 не
различал «неверный Client ID» от «невалидного токена», JS не показывал
подробное message и не тостил результат. Теперь: шаги network_error /
invalid_client_id / invalid_token / no_client_id + строка-лог в action_log.
Проверка на изолированном инстансе без кредов — качество сообщений.
"""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app import stream_tools_routes


@pytest.fixture
def app(disable_auth, tmp_db):
    application = FastAPI()
    application.include_router(stream_tools_routes.router)
    return application


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def inited_db(tmp_db):
    """init_db: таблицы (в т.ч. action_log) в изолированной tmp-базе."""
    from app.database import init_db
    await init_db()


@pytest.mark.asyncio
async def test_no_credentials_honest_message(client, monkeypatch):
    """Изолированный инстанс БЕЗ кредов: no_client_id с понятным сообщением."""
    monkeypatch.setattr(stream_tools_routes, "is_helix_configured", lambda: False)
    resp = await client.get("/api/stream-tools/check-connection", params={"account_id": "1"})
    assert resp.status_code == 400
    data = resp.json()
    assert data["ok"] is False
    assert data["reason"] == "no_client_id"
    assert "Client ID" in data["message"] and "Twitch" in data["message"]
    assert data.get("help_url", "").startswith("https://dev.twitch.tv")


@pytest.mark.asyncio
async def test_network_failure_is_separate_step(client, monkeypatch, inited_db):
    """Сетевой сбой — отдельный шаг, а не 500/«неизвестная ошибка»."""
    monkeypatch.setattr(stream_tools_routes, "is_helix_configured", lambda: True)

    # 1) _helix_request сам ловит httpx-сбой → {"status": -1}
    # (реальный ConnectError: HELIX_BASE на закрытый порт, класс не патчим —
    #  иначе ломается сам тестовый транспорт)
    async def fake_cid():
        return "cid"

    async def fake_tok(account_id):
        return "tok"

    monkeypatch.setattr(stream_tools_routes, "_get_client_id", fake_cid)
    monkeypatch.setattr(stream_tools_routes, "_get_account_token", fake_tok)
    monkeypatch.setattr(stream_tools_routes, "HELIX_BASE", "http://127.0.0.1:1")
    res = await stream_tools_routes._helix_request("GET", "/users", "1")
    assert res["status"] == -1 and "network" in res["text"]

    # 2) эндпоинт маппит status=-1 в честный network_error (502)
    async def fake_helix(method, path, account_id, **kw):
        return {"status": -1, "data": None, "text": "network: connection refused"}

    monkeypatch.setattr(stream_tools_routes, "_helix_request", fake_helix)
    resp = await client.get("/api/stream-tools/check-connection", params={"account_id": "1"})
    assert resp.status_code == 502
    data = resp.json()
    assert data["ok"] is False
    assert data["reason"] == "network_error"
    assert "api.twitch.tv" in data["message"]


@pytest.mark.asyncio
async def test_401_invalid_client_id_vs_invalid_token(client, monkeypatch):
    """401 различает неверный Client ID и невалидный токен."""
    monkeypatch.setattr(stream_tools_routes, "is_helix_configured", lambda: True)

    async def fake_helix_clientid(method, path, account_id, **kw):
        return {"status": 401, "data": None, "text": '{"message":"invalid client id"}'}

    monkeypatch.setattr(stream_tools_routes, "_helix_request", fake_helix_clientid)
    resp = await client.get("/api/stream-tools/check-connection", params={"account_id": "1"})
    data = resp.json()
    assert data["reason"] == "invalid_client_id"
    assert "Client ID" in data["message"]

    async def fake_helix_token(method, path, account_id, **kw):
        return {"status": 401, "data": None, "text": '{"message":"Invalid OAuth token"}'}

    monkeypatch.setattr(stream_tools_routes, "_helix_request", fake_helix_token)
    resp = await client.get("/api/stream-tools/check-connection", params={"account_id": "1"})
    data = resp.json()
    assert data["reason"] == "invalid_token"
    assert "авторизац" in data["message"]


@pytest.mark.asyncio
async def test_check_result_written_to_action_log(client, monkeypatch, inited_db):
    """Строка-лог: результат проверки попадает в action_log."""
    from app.database import get_db

    monkeypatch.setattr(stream_tools_routes, "is_helix_configured", lambda: True)

    async def fake_helix(method, path, account_id, **kw):
        return {"status": 200, "data": {"data": [{"id": "1", "login": "b1", "display_name": "B1"}]}}

    monkeypatch.setattr(stream_tools_routes, "_helix_request", fake_helix)
    resp = await client.get("/api/stream-tools/check-connection", params={"account_id": "1"})
    assert resp.json()["ok"] is True

    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT detail FROM action_log WHERE action = 'twitch_check' ORDER BY id DESC LIMIT 1")
        row = await cur.fetchone()
    finally:
        await db.close()
    assert row is not None and "ok" in row[0]


def test_api_js_error_carries_payload():
    """api() должен сохранять полный JSON-ответ в err.payload — иначе
    JS не может показать честный message/help_url из не-2xx ответа."""
    js = (stream_tools_routes.__file__ and
          (__import__("pathlib").Path(__file__).parent.parent / "static" / "app.js"))
    src = js.read_text(encoding="utf-8")
    assert "err.payload = payload" in src
