"""DEC-OWNER-018: массовое добавление люркеров по токенам (POST /api/accounts/bulk-lurkers)."""
from __future__ import annotations

import sys
from types import ModuleType

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


def _build_app():
    from fastapi import FastAPI
    from app.routes import router, actor_middleware
    app = FastAPI()
    app.middleware("http")(actor_middleware)
    app.include_router(router)
    return app


@pytest.fixture()
def stub_server():
    saved = sys.modules.get("app.server")
    fake = ModuleType("app.server")

    class _BotManager:
        async def start_bot(self, *a, **kw):
            return True

        async def stop_bot(self, *a, **kw):
            return True

    fake.bot_manager = _BotManager()
    fake.eventsub_manager = None
    fake.chat_analyzer = None
    sys.modules["app.server"] = fake
    try:
        yield fake
    finally:
        if saved is not None:
            sys.modules["app.server"] = saved
        else:
            sys.modules.pop("app.server", None)


@pytest.fixture()
def fake_validate(monkeypatch):
    """Токен 'tok_ok_N' → login 'botn'; остальные → невалидные."""
    from app import twitch_helix

    async def _validate(token: str):
        if token.startswith("tok_ok"):
            return {"login": "bot" + token.rsplit("_", 1)[-1], "user_id": "123", "expires_in": 3600}
        return None

    monkeypatch.setattr(twitch_helix, "validate_token", _validate)


async def test_bulk_lurkers_adds_enabled_lurkers_with_channel(tmp_db, disable_auth, stub_server, fake_validate):
    from app import database
    await database.init_db()
    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        r = await client.post("/api/accounts/bulk-lurkers", json={
            "tokens": ["tok_ok_1", "oauth:tok_ok_2", "tok_ok_3"],
            "channel": "Test_channel",
            "proxy": "socks5://h:1",
        })
        assert r.status_code == 200
        d = r.json()
        assert d["ok"] is True
        assert d["channel"] == "test_channel"
        assert [a["nickname"] for a in d["added"]] == ["bot1", "bot2", "bot3"]
        assert d["skipped"] == []

        accounts = await client.get("/api/accounts")
        by_nick = {a["nickname"]: a for a in accounts.json()}
        for nick in ("bot1", "bot2", "bot3"):
            acc = by_nick[nick]
            assert acc["bot_role"] == "lurker"
            assert acc["enabled"] in (True, 1)
            assert acc["proxy"] == "socks5://h:1"

        db = await database.get_db()
        try:
            rows = await (await db.execute(
                "SELECT channel_name FROM channels WHERE account_id = ? ORDER BY channel_name",
                (by_nick["bot1"]["id"],),
            )).fetchall()
            assert [r["channel_name"] for r in rows] == ["test_channel"]
        finally:
            await db.close()


async def test_bulk_lurkers_skips_invalid_and_duplicates_with_report(tmp_db, disable_auth, stub_server, fake_validate):
    from app import database
    await database.init_db()
    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        # бот bot1 уже существует в БД
        await client.post("/api/accounts", json={"nickname": "bot1", "token": "x"})

        r = await client.post("/api/accounts/bulk-lurkers", json={
            "tokens": ["tok_ok_1", "tok_bad", "tok_ok_1", "tok_ok_2", "tok_ok_dup_2"],
        })
        assert r.status_code == 200
        d = r.json()
        assert d["ok"] is True
        assert [a["nickname"] for a in d["added"]] == ["bot2"]

        reasons = sorted((s["reason"], s.get("nickname", "")) for s in d["skipped"])
        assert ("duplicate_nickname", "bot1") in reasons
        assert ("duplicate_token", "") in reasons
        assert ("duplicate_batch", "bot2") in reasons
        assert ("invalid_token", "") in reasons


async def test_bulk_restore_can_create_chatters_for_one_channel(tmp_db, disable_auth, stub_server, fake_validate):
    from app import database
    await database.init_db()
    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        response = await client.post("/api/accounts/bulk-lurkers", json={
            "tokens": ["tok_ok_4", "tok_ok_5"], "role": "chatter", "channel": "fresh_channel",
        })
        assert response.status_code == 200
        assert response.json()["role"] == "chatter"
        accounts = {item["nickname"]: item for item in (await client.get("/api/accounts")).json()}
        assert accounts["bot4"]["bot_role"] == "chatter"
        assert accounts["bot5"]["bot_role"] == "chatter"


async def test_bulk_lurkers_input_validation(tmp_db, disable_auth, stub_server, fake_validate):
    from app import database
    await database.init_db()
    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        r = await client.post("/api/accounts/bulk-lurkers", json={"tokens": ["", "  "]})
        assert r.json() == {"ok": False, "error": "tokens_required"}

        r = await client.post("/api/accounts/bulk-lurkers", json={"tokens": ["tok_ok_1"], "channel": "плохой канал!"})
        assert r.json() == {"ok": False, "error": "invalid_channel"}

        r = await client.post("/api/accounts/bulk-lurkers", json={"tokens": ["tok_ok_1"], "role": "director"})
        assert r.json() == {"ok": False, "error": "invalid_role"}

        r = await client.post("/api/accounts/bulk-lurkers", json={"tokens": [f"tok_ok_{i}" for i in range(201)]})
        assert r.json() == {"ok": False, "error": "too_many_tokens"}


async def test_bulk_lurkers_formats_login_pass_cookie_and_proxy(tmp_db, disable_auth, stub_server, fake_validate):
    from app import database
    await database.init_db()
    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        r = await client.post("/api/accounts/bulk-lurkers", json={
            "tokens": [
                "bot1:password123:tok_ok_1",
                "bot2:pass456:auth-token=tok_ok_2; unique_id=999;",
                "bot3:pass789:tok_ok_3:socks5://custom_proxy:1080",
            ],
            "role": "chatter",
        })
        assert r.status_code == 200
        d = r.json()
        assert d["ok"] is True
        assert [a["nickname"] for a in d["added"]] == ["bot1", "bot2", "bot3"]
        accounts = {item["nickname"]: item for item in (await client.get("/api/accounts")).json()}
        assert accounts["bot1"]["bot_role"] == "chatter"
        assert accounts["bot3"]["proxy"] == "socks5://custom_proxy:1080"


async def test_bulk_lurkers_json_cookie_array(tmp_db, disable_auth, stub_server, fake_validate):
    import json
    from app import database
    await database.init_db()
    cookie_json = json.dumps([
        {"name": "unique_id", "value": "12345"},
        {"name": "auth-token", "value": "tok_ok_1"},
    ])
    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        r = await client.post("/api/accounts/bulk-lurkers", json={
            "tokens": [cookie_json],
            "role": "chatter",
        })
        assert r.status_code == 200
        d = r.json()
        assert d["ok"] is True
        assert len(d["added"]) == 1
        assert d["added"][0]["nickname"] == "bot1"
