"""v10 — tests for action log filters/pagination + CSV export endpoints."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


def _build_app():
    from fastapi import FastAPI
    from app.routes import router, ws_router
    app = FastAPI()
    app.include_router(router)
    app.include_router(ws_router)
    return app


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


async def _setup_db(tmp_db):
    from app import database
    await database.init_db()
    db = await database.get_db()
    await db.execute(
        "INSERT INTO accounts (id, nickname, token) VALUES (1, 'streamer', 'tok')"
    )
    await db.commit()
    return db


async def _client():
    return AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test")


# ========== Action log: filters + pagination ==========

async def test_action_log_empty(tmp_db, disable_auth):
    await _setup_db(tmp_db)
    async with await _client() as client:
        r = await client.get("/api/action-log")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 0
        assert data["items"] == []
        assert data["actions"] == []


async def test_action_log_returns_total_and_items(tmp_db, disable_auth):
    db = await _setup_db(tmp_db)
    for i in range(5):
        await db.execute(
            "INSERT INTO action_log (action, detail) VALUES (?, ?)",
            (f"act_{i % 2}", f"detail {i}"),
        )
    await db.commit()
    async with await _client() as client:
        r = await client.get("/api/action-log")
        data = r.json()
        assert data["total"] == 5
        assert len(data["items"]) == 5
        # actions list deduplicates and sorts
        assert sorted(data["actions"]) == ["act_0", "act_1"]


async def test_action_log_filter_by_action(tmp_db, disable_auth):
    db = await _setup_db(tmp_db)
    await db.execute("INSERT INTO action_log (action, detail) VALUES ('login', 'a')")
    await db.execute("INSERT INTO action_log (action, detail) VALUES ('login', 'b')")
    await db.execute("INSERT INTO action_log (action, detail) VALUES ('logout', 'c')")
    await db.commit()
    async with await _client() as client:
        r = await client.get("/api/action-log", params={"action": "login"})
        data = r.json()
        assert data["total"] == 2
        for it in data["items"]:
            assert it["action"] == "login"


async def test_action_log_filter_by_query(tmp_db, disable_auth):
    db = await _setup_db(tmp_db)
    await db.execute("INSERT INTO action_log (action, detail) VALUES ('config_changed', 'pattern foo updated')")
    await db.execute("INSERT INTO action_log (action, detail) VALUES ('config_changed', 'pattern bar updated')")
    await db.execute("INSERT INTO action_log (action, detail) VALUES ('login', 'user signed in')")
    await db.commit()
    async with await _client() as client:
        r = await client.get("/api/action-log", params={"q": "foo"})
        data = r.json()
        assert data["total"] == 1
        assert "foo" in data["items"][0]["detail"]


async def test_action_log_filter_by_date_range(tmp_db, disable_auth):
    db = await _setup_db(tmp_db)
    yesterday = datetime.utcnow() - timedelta(days=1)
    today = datetime.utcnow()
    long_ago = datetime.utcnow() - timedelta(days=10)
    for ts, det in [(long_ago, "old"), (yesterday, "y"), (today, "now")]:
        await db.execute(
            "INSERT INTO action_log (action, detail, timestamp) VALUES ('act', ?, ?)",
            (det, _ts(ts)),
        )
    await db.commit()
    from_ts = _ts(yesterday - timedelta(hours=1))
    async with await _client() as client:
        r = await client.get("/api/action-log", params={"from_ts": from_ts})
        data = r.json()
        # only «y» and «now» pass the filter (long_ago excluded)
        assert data["total"] == 2


async def test_action_log_pagination(tmp_db, disable_auth):
    db = await _setup_db(tmp_db)
    for i in range(25):
        await db.execute(
            "INSERT INTO action_log (action, detail) VALUES ('act', ?)",
            (f"d{i}",),
        )
    await db.commit()
    async with await _client() as client:
        r1 = await client.get("/api/action-log", params={"limit": 10, "offset": 0})
        r2 = await client.get("/api/action-log", params={"limit": 10, "offset": 10})
        d1, d2 = r1.json(), r2.json()
        assert d1["total"] == 25 and d2["total"] == 25
        assert len(d1["items"]) == 10
        assert len(d2["items"]) == 10
        # Не должны пересекаться (по id desc — на second странице id меньше)
        ids1 = {it["id"] for it in d1["items"]}
        ids2 = {it["id"] for it in d2["items"]}
        assert ids1.isdisjoint(ids2)


async def test_action_log_limit_clamped(tmp_db, disable_auth):
    await _setup_db(tmp_db)
    async with await _client() as client:
        r = await client.get("/api/action-log", params={"limit": 9999})
        data = r.json()
        # Server caps at 500
        assert data["limit"] <= 500


# ========== Action log CSV export ==========

async def test_action_log_csv_returns_csv_content_type(tmp_db, disable_auth):
    db = await _setup_db(tmp_db)
    await db.execute("INSERT INTO action_log (action, detail) VALUES ('login', 'user a')")
    await db.commit()
    async with await _client() as client:
        r = await client.get("/api/action-log/export.csv")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        text = r.text
        # v10.3 5: header теперь включает колонку actor.
        assert text.startswith('"timestamp","actor","action","detail"')
        assert "login" in text
        assert "user a" in text


async def test_action_log_csv_filters_apply(tmp_db, disable_auth):
    db = await _setup_db(tmp_db)
    await db.execute("INSERT INTO action_log (action, detail) VALUES ('login', 'user a')")
    await db.execute("INSERT INTO action_log (action, detail) VALUES ('logout', 'user a')")
    await db.commit()
    async with await _client() as client:
        r = await client.get("/api/action-log/export.csv", params={"action": "login"})
        text = r.text
        assert "login" in text
        assert "logout" not in text


async def test_action_log_csv_quoting(tmp_db, disable_auth):
    db = await _setup_db(tmp_db)
    # detail с запятой и кавычкой — должно быть корректно эскейпнуто
    await db.execute(
        "INSERT INTO action_log (action, detail) VALUES ('act', ?)",
        ('text with "quotes", and commas',),
    )
    await db.commit()
    async with await _client() as client:
        r = await client.get("/api/action-log/export.csv")
        text = r.text
        # Кавычка эскейпится как ""
        assert '""quotes""' in text


# ========== Chat log CSV export ==========

async def test_chat_log_csv_basic(tmp_db, disable_auth):
    db = await _setup_db(tmp_db)
    await db.execute(
        "INSERT INTO chat_log (account_id, channel, author, message, is_bot, sentiment) "
        "VALUES (1, 'main', 'alice', 'hello', 0, 1)"
    )
    await db.execute(
        "INSERT INTO chat_log (account_id, channel, author, message, is_bot, sentiment) "
        "VALUES (1, 'main', 'bot', 'hi', 1, 0)"
    )
    await db.commit()
    async with await _client() as client:
        r = await client.get("/api/chat-log/export.csv")
        assert r.status_code == 200
        text = r.text
        assert "alice" in text and "bot" in text
        # Header
        assert text.startswith('"timestamp","account_id","channel","author","is_bot","sentiment","message"')


async def test_chat_log_csv_excludes_bots(tmp_db, disable_auth):
    db = await _setup_db(tmp_db)
    await db.execute(
        "INSERT INTO chat_log (account_id, channel, author, message, is_bot) "
        "VALUES (1, 'main', 'alice', 'hi', 0)"
    )
    await db.execute(
        "INSERT INTO chat_log (account_id, channel, author, message, is_bot) "
        "VALUES (1, 'main', 'bot', 'auto', 1)"
    )
    await db.commit()
    async with await _client() as client:
        r = await client.get("/api/chat-log/export.csv", params={"include_bots": "false"})
        text = r.text
        assert "alice" in text
        assert "auto" not in text


async def test_chat_log_csv_sentiment_filter(tmp_db, disable_auth):
    db = await _setup_db(tmp_db)
    await db.execute(
        "INSERT INTO chat_log (account_id, channel, author, message, is_bot, sentiment) "
        "VALUES (1, 'main', 'a', 'pos!', 0, 1)"
    )
    await db.execute(
        "INSERT INTO chat_log (account_id, channel, author, message, is_bot, sentiment) "
        "VALUES (1, 'main', 'b', 'meh', 0, 0)"
    )
    await db.execute(
        "INSERT INTO chat_log (account_id, channel, author, message, is_bot, sentiment) "
        "VALUES (1, 'main', 'c', 'bad!', 0, -1)"
    )
    await db.commit()
    async with await _client() as client:
        r = await client.get("/api/chat-log/export.csv", params={"sentiment": "pos"})
        assert "pos!" in r.text
        assert "meh" not in r.text
        assert "bad!" not in r.text

        r = await client.get("/api/chat-log/export.csv", params={"sentiment": "neg"})
        assert "bad!" in r.text
        assert "pos!" not in r.text


async def test_chat_log_csv_channel_filter(tmp_db, disable_auth):
    db = await _setup_db(tmp_db)
    await db.execute(
        "INSERT INTO chat_log (account_id, channel, author, message, is_bot) "
        "VALUES (1, 'main', 'a', 'one', 0)"
    )
    await db.execute(
        "INSERT INTO chat_log (account_id, channel, author, message, is_bot) "
        "VALUES (1, 'other', 'b', 'two', 0)"
    )
    await db.commit()
    async with await _client() as client:
        r = await client.get("/api/chat-log/export.csv", params={"channel": "main"})
        assert "one" in r.text
        assert "two" not in r.text


async def test_chat_log_csv_filename_in_header(tmp_db, disable_auth):
    await _setup_db(tmp_db)
    async with await _client() as client:
        r = await client.get("/api/chat-log/export.csv", params={"hours": 12, "channel": "abc"})
        assert "attachment" in r.headers.get("content-disposition", "")
        assert "12h" in r.headers["content-disposition"]
        assert "abc" in r.headers["content-disposition"]


async def test_chat_log_csv_quoting_messages(tmp_db, disable_auth):
    db = await _setup_db(tmp_db)
    await db.execute(
        "INSERT INTO chat_log (account_id, channel, author, message, is_bot) "
        "VALUES (1, 'main', 'a', ?, 0)",
        ('msg with "quotes", and, commas',),
    )
    await db.commit()
    async with await _client() as client:
        r = await client.get("/api/chat-log/export.csv")
        # CSV должен корректно квотировать запятые и эскейпить кавычки
        assert '""quotes""' in r.text


async def test_chat_log_csv_empty(tmp_db, disable_auth):
    await _setup_db(tmp_db)
    async with await _client() as client:
        r = await client.get("/api/chat-log/export.csv")
        assert r.status_code == 200
        # Только header без строк
        lines = [ln for ln in r.text.splitlines() if ln.strip()]
        assert len(lines) == 1
