"""v10.3 5 — tests for action_log actor + revert flow + Ctrl+K bulk endpoints."""
from __future__ import annotations

import base64
import sys
from types import ModuleType

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


def _build_app():
    """Полное FastAPI приложение, как в server.py, но без lifespan: с middleware и роутами."""
    from fastapi import FastAPI
    from app.routes import router, actor_middleware
    app = FastAPI()
    app.middleware("http")(actor_middleware)
    app.include_router(router)
    return app


@pytest.fixture()
def stub_server():
    """Заглушка app.server для эндпоинтов, которые лезут за bot_manager / chat_analyzer."""
    saved = sys.modules.get("app.server")
    fake = ModuleType("app.server")

    class _BotManager:
        async def start_bot(self, *a, **kw):
            return True
        async def stop_bot(self, *a, **kw):
            return True
        async def send_message(self, *a, **kw):
            return True

    class _EventSubManager:
        async def start_for_account(self, *a, **kw):
            return True
        async def stop_for_account(self, *a, **kw):
            return True

    class _ChatAnalyzer:
        def set_account_token(self, *a, **kw):
            return None
        def update_settings(self, *a, **kw):
            return None

    fake.bot_manager = _BotManager()
    fake.eventsub_manager = _EventSubManager()
    fake.chat_analyzer = _ChatAnalyzer()
    fake.ai_service = None  # не нужен здесь
    sys.modules["app.server"] = fake
    try:
        yield fake
    finally:
        if saved is not None:
            sys.modules["app.server"] = saved
        else:
            sys.modules.pop("app.server", None)


def _basic_auth(user: str, password: str = "x") -> str:
    raw = f"{user}:{password}".encode()
    return "Basic " + base64.b64encode(raw).decode()


# ============ ACTOR MIDDLEWARE ============

async def test_actor_middleware_writes_actor_from_basic_auth(tmp_db, disable_auth, stub_server):
    from app import database
    await database.init_db()
    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        # Создаём аккаунт от имени "alice" — actor должен попасть в лог
        r = await client.post(
            "/api/accounts",
            json={"nickname": "bot1", "token": "tok", "refresh_token": "rfr", "proxy": ""},
            headers={"Authorization": _basic_auth("alice")},
        )
        assert r.status_code == 200

        r2 = await client.get("/api/action-log?action=account_add")
        d = r2.json()
        assert d["total"] == 1
        item = d["items"][0]
        assert item["action"] == "account_add"
        assert item["actor"] == "alice"
        # actors список доступен
        assert "alice" in d["actors"]
        # can_revert — потому что мы записали revert_payload
        assert item["can_revert"] is True


async def test_actor_filter_returns_only_matching(tmp_db, disable_auth, stub_server):
    from app import database
    await database.init_db()
    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        await client.post("/api/accounts", json={"nickname": "a", "token": "t"}, headers={"Authorization": _basic_auth("alice")})
        await client.post("/api/accounts", json={"nickname": "b", "token": "t"}, headers={"Authorization": _basic_auth("bob")})

        r = await client.get("/api/action-log?actor=alice")
        d = r.json()
        assert d["total"] == 1
        assert d["items"][0]["actor"] == "alice"


async def test_csv_export_includes_actor_column(tmp_db, disable_auth, stub_server):
    from app import database
    await database.init_db()
    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        await client.post(
            "/api/accounts",
            json={"nickname": "x", "token": "t"},
            headers={"Authorization": _basic_auth("alice")},
        )
        r = await client.get("/api/action-log/export.csv")
        text = r.text
        # v10.3 5: header теперь включает колонку actor
        assert text.startswith('"timestamp","actor","action","detail"')
        assert ',"alice","account_add"' in text


# ============ REVERT FLOW ============

async def test_revert_account_add_deletes_account(tmp_db, disable_auth, stub_server):
    from app import database
    await database.init_db()
    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        r = await client.post(
            "/api/accounts",
            json={"nickname": "victim", "token": "t"},
            headers={"Authorization": _basic_auth("admin")},
        )
        assert r.status_code == 200
        new_acc = r.json()
        aid = new_acc["id"]

        # Найдём id записи в action_log для отката
        r = await client.get("/api/action-log?action=account_add")
        log_id = r.json()["items"][0]["id"]

        r = await client.post(f"/api/action-log/{log_id}/revert", headers={"Authorization": _basic_auth("admin")})
        d = r.json()
        assert d["ok"] is True
        assert d["action"] == "account_add"

        # Аккаунт удалён
        r = await client.get("/api/accounts")
        nicks = [a["nickname"] for a in r.json()]
        assert "victim" not in nicks

        # В журнале появилась запись revert:account_add
        r = await client.get("/api/action-log")
        actions = [it["action"] for it in r.json()["items"]]
        assert "revert:account_add" in actions


async def test_revert_unknown_log_id_returns_error(tmp_db, disable_auth, stub_server):
    from app import database
    await database.init_db()
    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        r = await client.post("/api/action-log/99999/revert")
        assert r.status_code == 200
        assert r.json()["ok"] is False
        assert r.json()["error"] == "not_found"


async def test_revert_without_payload_returns_error(tmp_db, disable_auth, stub_server):
    from app import database
    await database.init_db()
    db = await database.get_db()
    await db.execute(
        "INSERT INTO action_log (action, detail, actor, revert_payload) VALUES (?, ?, ?, ?)",
        ("manual_action", "no payload", "u", ""),
    )
    await db.commit()
    cur = await db.execute("SELECT id FROM action_log ORDER BY id DESC LIMIT 1")
    log_id = (await cur.fetchone())["id"]

    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        r = await client.post(f"/api/action-log/{log_id}/revert")
        d = r.json()
        assert d["ok"] is False
        assert d["error"] == "no_revert_payload"



# ============ Ctrl+K bulk endpoints ============

async def test_start_all_endpoint_calls_bot_manager(tmp_db, disable_auth, stub_server):
    from app import database
    await database.init_db()
    db = await database.get_db()
    await db.execute("INSERT INTO accounts (id, nickname, token, enabled) VALUES (1, 'a1', 't1', 1)")
    await db.execute("INSERT INTO accounts (id, nickname, token, enabled) VALUES (2, 'a2', 't2', 1)")
    await db.execute("INSERT INTO channels (account_id, channel_name, enabled) VALUES (1, 'ch1', 1)")
    # account 2 — без каналов, должен попасть в skipped
    await db.commit()

    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        r = await client.post("/api/bots/start_all", json={})
        d = r.json()
        assert d["ok"] is True
        assert d["started"] == 1
        assert d["skipped"] == 1


async def test_stop_all_endpoint(tmp_db, disable_auth, stub_server):
    from app import database
    await database.init_db()
    db = await database.get_db()
    await db.execute("INSERT INTO accounts (id, nickname, token) VALUES (1, 'a1', 't1')")
    await db.execute("INSERT INTO accounts (id, nickname, token) VALUES (2, 'a2', 't2')")
    await db.commit()

    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        r = await client.post("/api/bots/stop_all", json={})
        d = r.json()
        assert d["ok"] is True
        assert d["stopped"] == 2


async def test_persona_activate_endpoint_exists(tmp_db, disable_auth, stub_server):
    """sanity-check: /api/personas/{id}/activate существует и работает."""
    from app import database
    await database.init_db()
    db = await database.get_db()
    await db.execute("INSERT INTO accounts (id, nickname, token) VALUES (1, 'a', 't')")
    await db.execute("INSERT INTO personas (id, account_id, name, system_prompt, is_active) VALUES (10, 1, 'fun', 'sys', 0)")
    await db.commit()

    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        r = await client.post("/api/personas/10/activate")
        assert r.status_code == 200
        d = r.json()
        assert d.get("ok") is True or "ok" in d
