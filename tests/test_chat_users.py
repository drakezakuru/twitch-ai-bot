"""§9c: Chat Users — управление списком юзеров чата.

Спецификация: PLAN_ALL_IN_ONE.md §9c, FEATURE_OWNERSHIP.md §5,
AUDIT_SECTION1.md #12.

Проверяем:
1. on_message регистрирует юзера в chat_users (upsert, role detection).
2. Toggle enabled=0 через API реально блокирует ответы бота этому юзеру
   (без глобального Twitch-бана — работает наравне с banlist).
3. GET /api/accounts/{id}/chat-users отдаёт список с фильтрами.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

from app.chat_analyzer import ChatAnalyzer

pytestmark = pytest.mark.asyncio


class _FakeAI:
    async def generate_text(self, *a, **kw):
        return "ok"

    async def analyze_image(self, *a, **kw):
        return ""


class _FakeAuthor:
    def __init__(self, name, is_mod=False, is_vip=False, is_subscriber=False, is_broadcaster=False):
        self.name = name
        self.is_mod = is_mod
        self.is_vip = is_vip
        self.is_subscriber = is_subscriber
        self.is_broadcaster = is_broadcaster


class _FakeChannel:
    def __init__(self, name):
        self.name = name


class _FakeMessage:
    def __init__(self, channel, author, content):
        self.channel = _FakeChannel(channel)
        self.author = author
        self.content = content


class _FakeInstance:
    def __init__(self, account_id, nickname="mybot", token=""):
        self.account_id = account_id
        self.nickname = nickname
        self.token = token


_sent: list[tuple] = []


async def _capture_send(account_id, channel, text, **kwargs):
    _sent.append((account_id, channel, text))
    return True


def _new_analyzer() -> ChatAnalyzer:
    _sent.clear()
    return ChatAnalyzer(ai=_FakeAI(), send_fn=_capture_send)


async def _client():
    from fastapi import FastAPI
    from app.routes import router
    app = FastAPI()
    app.include_router(router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ──────────────── upsert / role detection ────────────────


async def test_on_message_registers_chat_user(tmp_db, disable_auth):
    from app import database
    await database.init_db()

    a = _new_analyzer()
    a.update_settings(1, {"enabled": True})
    instance = _FakeInstance(account_id=1)
    msg = _FakeMessage("testchan", _FakeAuthor("viewer1"), "привет чат")
    await a.on_message(instance, msg)

    db = await database.get_db()
    cur = await db.execute(
        "SELECT * FROM chat_users WHERE account_id=1 AND channel='testchan' AND username='viewer1'"
    )
    row = await cur.fetchone()
    assert row is not None
    assert row["role"] == "viewer"
    assert row["enabled"] == 1
    assert row["message_count"] == 1


async def test_on_message_detects_mod_role(tmp_db, disable_auth):
    from app import database
    await database.init_db()

    a = _new_analyzer()
    a.update_settings(1, {"enabled": True})
    instance = _FakeInstance(account_id=1)
    msg = _FakeMessage("testchan", _FakeAuthor("modder", is_mod=True), "hi")
    await a.on_message(instance, msg)

    db = await database.get_db()
    cur = await db.execute(
        "SELECT role FROM chat_users WHERE account_id=1 AND channel='testchan' AND username='modder'"
    )
    row = await cur.fetchone()
    assert row["role"] == "mod"


async def test_on_message_increments_message_count(tmp_db, disable_auth):
    from app import database
    await database.init_db()

    a = _new_analyzer()
    a.update_settings(1, {"enabled": True})
    instance = _FakeInstance(account_id=1)
    for i in range(3):
        msg = _FakeMessage("testchan", _FakeAuthor("viewer1"), f"msg {i}")
        await a.on_message(instance, msg)

    db = await database.get_db()
    cur = await db.execute(
        "SELECT message_count FROM chat_users WHERE account_id=1 AND channel='testchan' AND username='viewer1'"
    )
    row = await cur.fetchone()
    assert row["message_count"] == 3


# ──────────────── disabled toggle blocks bot replies ────────────────


async def test_disabled_chat_user_is_ignored(tmp_db, disable_auth):
    """Юзер с enabled=0 в chat_users не должен доходить дальше в on_message
    (не должен трекаться в mood/threads/live_mimicry и т.д.), аналогично banlist.
    """
    from app import database
    await database.init_db()
    db = await database.get_db()
    await db.execute(
        "INSERT INTO chat_users (account_id, channel, username, role, enabled) "
        "VALUES (1, 'testchan', 'muted_user', 'viewer', 0)"
    )
    await db.commit()

    a = _new_analyzer()
    a.update_settings(1, {"enabled": True, "mood_engine_enabled": True})
    instance = _FakeInstance(account_id=1)
    msg = _FakeMessage("testchan", _FakeAuthor("muted_user"), "бот ответь мне пожалуйста")
    await a.on_message(instance, msg)

    # message_count всё равно инкрементируется upsert-ом (регистрация происходит
    # до enabled-check), но дальше pipeline не идёт — ответа не будет.
    assert _sent == []


async def test_enabled_chat_user_not_blocked(tmp_db, disable_auth):
    from app import database
    await database.init_db()
    db = await database.get_db()
    await db.execute(
        "INSERT INTO chat_users (account_id, channel, username, role, enabled) "
        "VALUES (1, 'testchan', 'normal_user', 'viewer', 1)"
    )
    await db.commit()

    a = _new_analyzer()
    a.update_settings(1, {"enabled": True})
    ok = await a._is_chat_user_enabled(1, "testchan", "normal_user")
    assert ok is True


async def test_unknown_user_defaults_to_enabled(tmp_db, disable_auth):
    """Юзер без записи в chat_users (ещё не upsert-нут) считается разрешённым."""
    from app import database
    await database.init_db()

    a = _new_analyzer()
    ok = await a._is_chat_user_enabled(1, "testchan", "brand_new_user")
    assert ok is True


# ──────────────── REST API ────────────────


async def test_list_chat_users_api(tmp_db, disable_auth):
    from app import database
    await database.init_db()
    db = await database.get_db()
    await db.execute(
        "INSERT INTO accounts (id, nickname, token) VALUES (1, 'acc1', 'tok')"
    )
    await db.execute(
        "INSERT INTO chat_users (account_id, channel, username, role, message_count) "
        "VALUES (1, 'chan', 'alice', 'viewer', 5)"
    )
    await db.execute(
        "INSERT INTO chat_users (account_id, channel, username, role, message_count) "
        "VALUES (1, 'chan', 'bob_mod', 'mod', 10)"
    )
    await db.commit()

    client = await _client()
    async with client:
        r = await client.get("/api/accounts/1/chat-users")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        usernames = {u["username"] for u in data["users"]}
        assert usernames == {"alice", "bob_mod"}

        # search filter
        r2 = await client.get("/api/accounts/1/chat-users", params={"q": "alice"})
        assert {u["username"] for u in r2.json()["users"]} == {"alice"}

        # role filter
        r3 = await client.get("/api/accounts/1/chat-users", params={"role": "mod"})
        assert {u["username"] for u in r3.json()["users"]} == {"bob_mod"}


async def test_toggle_chat_user_api(tmp_db, disable_auth):
    from app import database
    await database.init_db()
    db = await database.get_db()
    await db.execute(
        "INSERT INTO accounts (id, nickname, token) VALUES (1, 'acc1', 'tok')"
    )
    await db.execute(
        "INSERT INTO chat_users (account_id, channel, username, role) "
        "VALUES (1, 'chan', 'alice', 'viewer')"
    )
    await db.commit()

    client = await _client()
    async with client:
        r = await client.put("/api/accounts/1/chat-users/alice", json={"enabled": 0})
        assert r.status_code == 200
        assert r.json()["ok"] is True

    db2 = await database.get_db()
    cur = await db2.execute(
        "SELECT enabled FROM chat_users WHERE account_id=1 AND username='alice'"
    )
    row = await cur.fetchone()
    assert row["enabled"] == 0
