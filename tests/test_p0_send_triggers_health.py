"""P0-блок v12: причины отправки (§5.2), триггеры (§10), health (§5.1).

Спецификация: PLAN_ALL_IN_ONE.md §5, §10.

Проверяем:
1. POST /api/send возвращает machine-readable reason: bot_disabled,
   channel_disabled, moderation_blocked (все причины из списка плана §5.2).
2. Cooldown 1–2 сек между отправками одного бота (bot_manager).
3. Классификация ошибок Twitch: oauth_expired / network_error / twitch_error.
4. Триггеры: привязка к каналу, счётчик срабатываний + last_fired_at,
   тестовый запуск POST /api/triggers/{id}/test с причиной отказа.
5. Health: колбэк срабатывает при смене состояния бота.
"""
from __future__ import annotations

import asyncio
import time

import pytest
from httpx import AsyncClient, ASGITransport

from app.bot_manager import TwitchBotManager

pytestmark = pytest.mark.asyncio


async def _client():
    from fastapi import FastAPI
    from app.routes import router
    app = FastAPI()
    app.include_router(router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed_account(db, account_id: int = 1, enabled: int = 1) -> None:
    await db.execute(
        "INSERT INTO accounts (id, nickname, token, enabled) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET enabled = excluded.enabled",
        (account_id, "testbot", "oauth:xxx", enabled),
    )
    await db.commit()


async def _seed_channel(db, account_id: int = 1, channel: str = "chan", enabled: int = 1) -> None:
    await db.execute(
        "INSERT INTO channels (account_id, channel_name, enabled) VALUES (?, ?, ?) "
        "ON CONFLICT(account_id, channel_name) DO UPDATE SET enabled = excluded.enabled",
        (account_id, channel, enabled),
    )
    await db.commit()


# ──────────────── §5.2: причины отправки ────────────────


async def test_send_reason_bot_disabled(tmp_db, disable_auth):
    from app import database
    await database.init_db()
    db = await database.get_db()
    await _seed_account(db, enabled=0)
    await _seed_channel(db)
    await db.close()

    async with await _client() as c:
        r = await c.post("/api/send", json={"account_id": 1, "channel": "chan", "text": "hi"})
        body = r.json()
        assert r.status_code == 200
        assert body["ok"] is False
        assert body["reason"] == "bot_disabled"


async def test_send_reason_channel_disabled(tmp_db, disable_auth):
    from app import database
    await database.init_db()
    db = await database.get_db()
    await _seed_account(db, enabled=1)
    await _seed_channel(db, enabled=0)
    await db.close()

    async with await _client() as c:
        r = await c.post("/api/send", json={"account_id": 1, "channel": "chan", "text": "hi"})
        body = r.json()
        assert body["ok"] is False
        assert body["reason"] == "channel_disabled"


async def test_send_reason_moderation_blocked(tmp_db, disable_auth):
    from app import database
    await database.init_db()
    db = await database.get_db()
    await _seed_account(db)
    await _seed_channel(db)
    await db.execute("INSERT INTO word_filter (account_id, word) VALUES (1, 'badword')")
    await db.commit()
    await db.close()

    async with await _client() as c:
        r = await c.post("/api/send", json={"account_id": 1, "channel": "chan", "text": "это BadWord вообще"})
        body = r.json()
        assert body["ok"] is False
        assert body["reason"] == "moderation_blocked"

    # Причину видно в per-bot логах
    db = await database.get_db()
    cur = await db.execute(
        "SELECT message FROM bot_logs WHERE account_id = 1 AND category = 'system' ORDER BY id DESC LIMIT 1"
    )
    row = await cur.fetchone()
    await db.close()
    assert row is not None and "модерац" in row["message"]


async def test_send_reason_bot_not_connected(tmp_db, disable_auth):
    """Бот включён, но manager не запущен → bot_not_connected, и ошибка логируется."""
    from app import database
    await database.init_db()
    db = await database.get_db()
    await _seed_account(db)
    await _seed_channel(db)
    await db.close()

    class _FakeManager:
        async def send_message_detailed(self, account_id, channel, text):
            return {"ok": False, "reason": "bot_not_connected", "error": "Бот ещё не подключён"}

    from app import server
    original = getattr(server, "bot_manager", None)
    server.bot_manager = _FakeManager()
    try:
        async with await _client() as c:
            r = await c.post("/api/send", json={"account_id": 1, "channel": "chan", "text": "hi"})
            body = r.json()
            assert body["reason"] == "bot_not_connected"
    finally:
        server.bot_manager = original

    # Ошибка отправки попала в per-bot лог (§5.2: логировать ошибки отправки)
    db = await database.get_db()
    cur = await db.execute(
        "SELECT message, level FROM bot_logs WHERE account_id = 1 AND category = 'system' ORDER BY id DESC LIMIT 1"
    )
    row = await cur.fetchone()
    await db.close()
    assert row is not None
    assert "bot_not_connected" in row["message"]
    assert row["level"] == "error"


# ──────────────── §5.2: cooldown + классификация ошибок ────────────────


class _FakeTwitchChannel:
    def __init__(self, name: str, fail: bool = False, exc: Exception | None = None):
        self.name = name
        self._fail = fail
        self._exc = exc
        self.sent: list[str] = []

    async def send(self, text: str) -> None:
        if self._fail:
            raise self._exc or RuntimeError("boom")
        self.sent.append(text)


class _FakeBot:
    def __init__(self, channel: _FakeTwitchChannel):
        self._channel = channel

    def get_channel(self, name: str):
        return self._channel if self._channel.name == name else None


async def test_send_cooldown_between_sends():
    """Второй вызов подряд быстрее 1–2 сек получает reason='cooldown' (§5.2)."""
    from app.bot_manager import BotInstance
    ch = _FakeTwitchChannel("chan")
    m = TwitchBotManager()
    m.NOTICE_WAIT_SEC = 0  # ускоряем тест: реальный NOTICE-check покрыт отдельно
    inst = BotInstance(account_id=1, nickname="testbot", token="oauth:x", channels=["chan"])
    inst.bot = _FakeBot(ch)
    inst.connected = True
    inst.state = "online"
    m._bots[1] = inst

    first = await m.send_message_detailed(1, "chan", "one")
    assert first["ok"] is True
    assert first["confirmed"] is False
    second = await m.send_message_detailed(1, "chan", "two")
    assert second["ok"] is False
    assert second["reason"] == "cooldown"

    await asyncio.sleep(1.3)
    third = await m.send_message_detailed(1, "chan", "three")
    assert third["ok"] is True


def test_classify_send_errors():
    m = TwitchBotManager()
    assert m._classify_send_error(RuntimeError("login authentication failed")) == "oauth_expired"
    assert m._classify_send_error(TimeoutError("connection timed out")) == "network_error"
    assert m._classify_send_error(ConnectionResetError()) == "network_error"
    assert m._classify_send_error(RuntimeError("some weird twitch thing")) == "twitch_error"


def test_classify_notice_rejection():
    """Owner report 27.09.2026: только настоящий серверный NOTICE msg_* — отказ;
    информационные NOTICE (host_on и т.п.) отправку не блокируют."""
    from app.bot_manager import classify_notice_rejection
    assert classify_notice_rejection("msg_channel_suspended") == "msg_channel_suspended"
    assert classify_notice_rejection("MSG_Rejected") == "msg_rejected"
    assert classify_notice_rejection("host_on") is None
    assert classify_notice_rejection("") is None
    assert classify_notice_rejection(None) is None


async def test_send_detects_real_notice_rejection():
    """Owner report 27.09.2026: PRIVMSG(ECHO) — локальная подделка TwitchIO, не
    доказывает доставку. Настоящий серверный NOTICE msg_* должен превращать
    'успешный' ch.send() в честный reason='twitch_rejected'."""
    from app.bot_manager import BotInstance
    ch = _FakeTwitchChannel("chan")
    m = TwitchBotManager()
    m.NOTICE_WAIT_SEC = 0.05
    inst = BotInstance(account_id=1, nickname="testbot", token="oauth:x", channels=["chan"])
    inst.bot = _FakeBot(ch)
    inst.connected = True
    inst.state = "online"
    m._bots[1] = inst

    async def _deliver_notice():
        await asyncio.sleep(0.01)
        m._last_notice[1] = {
            "channel": "chan",
            "msg_id": "msg_channel_suspended",
            "message": "This channel does not exist or has been suspended.",
            "at": time.time(),
        }

    asyncio.get_event_loop().create_task(_deliver_notice())
    res = await m.send_message_detailed(1, "chan", "hello")
    assert res["ok"] is False
    assert res["reason"] == "twitch_rejected"
    assert res["twitch_msg_id"] == "msg_channel_suspended"
    assert ch.sent == ["hello"]  # реально ушло в сокет, но Twitch отклонил


async def test_send_ignores_unrelated_notice():
    """Информационный NOTICE без префикса msg_ не должен блокировать успешную отправку."""
    from app.bot_manager import BotInstance
    ch = _FakeTwitchChannel("chan")
    m = TwitchBotManager()
    m.NOTICE_WAIT_SEC = 0.05
    inst = BotInstance(account_id=1, nickname="testbot", token="oauth:x", channels=["chan"])
    inst.bot = _FakeBot(ch)
    inst.connected = True
    inst.state = "online"
    m._bots[1] = inst
    m._last_notice[1] = {
        "channel": "chan", "msg_id": "host_on", "message": "Now hosting.", "at": time.time() - 10,
    }

    res = await m.send_message_detailed(1, "chan", "hello")
    assert res["ok"] is True
    assert res["confirmed"] is False


async def test_send_failure_sets_error_state_and_reason():
    from app.bot_manager import BotInstance
    ch = _FakeTwitchChannel("chan", fail=True, exc=RuntimeError("login authentication failed"))
    m = TwitchBotManager()
    inst = BotInstance(account_id=1, nickname="testbot", token="oauth:x", channels=["chan"])
    inst.bot = _FakeBot(ch)
    inst.connected = True
    inst.state = "online"
    m._bots[1] = inst

    res = await m.send_message_detailed(1, "chan", "hi")
    assert res["ok"] is False
    assert res["reason"] == "oauth_expired"
    assert inst.state == "error"
    assert inst.last_error


# ──────────────── §5.1: health callback ────────────────


async def test_health_callback_fires_on_state_change():
    from app.bot_manager import BotInstance
    m = TwitchBotManager()
    inst = BotInstance(account_id=1, nickname="testbot", token="oauth:x")
    inst.state = "connecting"
    m._bots[1] = inst

    events: list[tuple] = []
    m.set_health_callback(lambda aid, nick, old, new, err: events.append((aid, old, new)) or asyncio.sleep(0))

    inst.state = "online"
    await m._health(inst, "connecting")
    assert events == [(1, "connecting", "online")]


# ──────────────── §10: триггеры ────────────────


async def _seed_trigger(db, account_id: int = 1, keyword: str = "привет", channel: str = "",
                        enabled: int = 1, use_ai: int = 0, response: str = "хай") -> int:
    cur = await db.execute(
        "INSERT INTO triggers (account_id, keyword, response, use_ai, enabled, channel) VALUES (?, ?, ?, ?, ?, ?)",
        (account_id, keyword, response, use_ai, enabled, channel),
    )
    await db.commit()
    return cur.lastrowid


async def test_trigger_channel_filtering(tmp_db, disable_auth):
    """Триггер с каналом не срабатывает в чужом канале; глобальный — срабатывает (§10, §2.1)."""
    from app import database
    from app.chat_analyzer import ChatAnalyzer
    await database.init_db()
    db = await database.get_db()
    await _seed_account(db)
    await _seed_trigger(db, keyword="quest", channel="chanA")
    await _seed_trigger(db, keyword="global", channel="")
    await db.close()

    class _FakeAI:
        async def generate_text(self, *a, **kw):
            return "ok"

    a = ChatAnalyzer(ai=_FakeAI(), send_fn=lambda *args, **kw: asyncio.sleep(0, result=True))

    hit = await a._check_triggers(1, "что за quest?", channel="chanA")
    assert hit is not None and hit["keyword"] == "quest"

    miss = await a._check_triggers(1, "что за quest?", channel="chanB")
    assert miss is None  # channel-specific триггер не работает в другом канале

    ghit = await a._check_triggers(1, "ну global же", channel="chanB")
    assert ghit is not None and ghit["keyword"] == "global"


async def test_trigger_fires_counter_and_last_fired(tmp_db, disable_auth):
    from app import database
    from app.chat_analyzer import ChatAnalyzer
    await database.init_db()
    db = await database.get_db()
    await _seed_account(db)
    tid = await _seed_trigger(db, keyword="gg")
    await db.close()

    class _FakeAI:
        async def generate_text(self, *a, **kw):
            return "ok"

    a = ChatAnalyzer(ai=_FakeAI(), send_fn=lambda *args, **kw: asyncio.sleep(0, result=True))
    hit = await a._check_triggers(1, "gg всем")
    assert hit is not None

    db = await database.get_db()
    cur = await db.execute("SELECT fires, last_fired_at FROM triggers WHERE id = ?", (tid,))
    row = await cur.fetchone()
    await db.close()
    assert row["fires"] == 1
    assert row["last_fired_at"] is not None


async def test_trigger_create_with_channel_api(tmp_db, disable_auth):
    from app import database
    await database.init_db()
    db = await database.get_db()
    await _seed_account(db)
    await db.close()

    async with await _client() as c:
        r = await c.post("/api/accounts/1/triggers",
                         json={"keyword": "кринж", "response": "согласен", "use_ai": False, "channel": "MyChan"})
        assert r.json()["ok"] is True
        tid = r.json()["trigger_id"]

    db = await database.get_db()
    cur = await db.execute("SELECT keyword, channel, use_ai FROM triggers WHERE id = ?", (tid,))
    row = await cur.fetchone()
    await db.close()
    assert row["keyword"] == "кринж"
    assert row["channel"] == "mychan"  # нормализация: lower + без #
    assert row["use_ai"] == 0


async def test_trigger_test_endpoint(tmp_db, disable_auth):
    """Тестовый запуск (§10): match / disabled / channel_mismatch / no_keyword_match."""
    from app import database
    await database.init_db()
    db = await database.get_db()
    await _seed_account(db)
    tid = await _seed_trigger(db, keyword="привет", channel="chanA", enabled=1, response="хай!")
    tid_disabled = await _seed_trigger(db, keyword="bye", enabled=0)
    await db.close()

    async with await _client() as c:
        ok = (await c.post(f"/api/triggers/{tid}/test", json={"text": "ну привет чат", "channel": "chanA"})).json()
        mismatch = (await c.post(f"/api/triggers/{tid}/test", json={"text": "привет", "channel": "chanB"})).json()
        nomatch = (await c.post(f"/api/triggers/{tid}/test", json={"text": "совсем другое", "channel": "chanA"})).json()
        disabled = (await c.post(f"/api/triggers/{tid_disabled}/test", json={"text": "bye"})).json()

    assert ok["fired"] is True and ok["use_ai"] is False and ok["response"] == "хай!"
    assert mismatch["fired"] is False and mismatch["reason"] == "channel_mismatch"
    assert nomatch["fired"] is False and nomatch["reason"] == "no_keyword_match"
    assert disabled["fired"] is False and disabled["reason"] == "trigger_disabled"


async def test_trigger_list_includes_channel_and_stats(tmp_db, disable_auth):
    from app import database
    await database.init_db()
    db = await database.get_db()
    await _seed_account(db)
    await _seed_trigger(db, keyword="word", channel="chanx")
    await db.close()

    async with await _client() as c:
        triggers = (await c.get("/api/accounts/1/triggers")).json()

    assert triggers[0]["channel"] == "chanx"
    assert triggers[0]["fires"] == 0
    assert triggers[0]["last_fired_at"] is None


# ──────────────── §25.1: фильтры истории чата ────────────────


async def test_logs_filters_by_channel_and_account(tmp_db, disable_auth):
    from app import database
    await database.init_db()
    db = await database.get_db()
    await _seed_account(db)
    await db.execute(
        "INSERT INTO accounts (id, nickname, token, enabled) VALUES (2, 'secondbot', 'oauth:y', 1) "
        "ON CONFLICT(id) DO NOTHING"
    )
    await db.commit()
    rows = [
        (1, "chanA", "u1", "привет A"),
        (1, "chanB", "u2", "привет B"),
        (2, "chanA", "u3", "привет от второго бота"),
    ]
    for acc, ch, author, msg in rows:
        await db.execute(
            "INSERT INTO chat_log (account_id, channel, author, message, is_bot) VALUES (?, ?, ?, ?, 0)",
            (acc, ch, author, msg),
        )
    await db.commit()
    await db.close()

    async with await _client() as c:
        all_rows = (await c.get("/api/logs?limit=100")).json()
        assert len(all_rows) == 3

        by_chan = (await c.get("/api/logs?channel=chanA")).json()
        assert len(by_chan) == 2 and all(r["channel"] == "chanA" for r in by_chan)

        by_acc = (await c.get("/api/logs?account_id=2")).json()
        assert len(by_acc) == 1 and by_acc[0]["author"] == "u3"

        by_both = (await c.get("/api/logs?channel=chanA&account_id=1")).json()
        assert len(by_both) == 1 and by_both[0]["author"] == "u1"

        # `#` и регистр нормализуются
        by_hash = (await c.get("/api/logs?channel=%23ChanA&account_id=1")).json()
        assert len(by_hash) == 1


# ──────────────── §25.2: чтения чата в bot_logs ────────────────


async def test_chat_reads_logged_to_bot_logs(tmp_db, disable_auth):
    from app.server import log_message
    from app import database
    await database.init_db()
    db = await database.get_db()
    await _seed_account(db)
    await db.close()

    await log_message(1, "chan", "viewer1", "тестовое сообщение", False)

    db = await database.get_db()
    cur = await db.execute(
        "SELECT category, message FROM bot_logs WHERE account_id = 1 AND category = 'chat'"
    )
    rows = await cur.fetchall()
    await db.close()
    assert rows, "chat read should appear in bot_logs"
    assert "viewer1" in rows[0]["message"]
