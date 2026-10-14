"""v9 — API tests for sentiment timeline + wordcloud + trending."""
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
    return db


async def _client():
    return AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test")


# ---------- Sentiment timeline ----------

async def test_sentiment_empty_db(tmp_db, disable_auth):
    await _setup_db(tmp_db)
    async with await _client() as client:
        r = await client.get("/api/stats/sentiment", params={"hours": 24})
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 0
        assert data["points"] == []
        assert data["summary"]["pos"] == 0


async def test_sentiment_classifies_messages(tmp_db, disable_auth):
    db = await _setup_db(tmp_db)
    now = datetime.utcnow()
    # Положим сообщения с явными sentiment-значениями
    msgs = [
        ("u1", "это просто пушка, круто!", 1),  # pos
        ("u2", "это полная херня, отстой", -1),  # neg
        ("u3", "привет", 0),  # neutral
        ("u4", "KEKW топ момент 🔥", 1),
    ]
    for author, text, sentiment in msgs:
        await db.execute(
            "INSERT INTO chat_log (account_id, channel, author, message, is_bot, sentiment, timestamp) "
            "VALUES (1, 'main', ?, ?, 0, ?, ?)",
            (author, text, sentiment, _ts(now - timedelta(minutes=2))),
        )
    await db.commit()

    async with await _client() as client:
        r = await client.get("/api/stats/sentiment", params={"hours": 1})
        assert r.status_code == 200
        data = r.json()
        s = data["summary"]
        assert s["pos"] == 2
        assert s["neg"] == 1
        assert s["neu"] == 1
        assert s["total"] == 4
        assert s["net"] == 1
        assert abs(s["pos_pct"] - 50.0) < 0.01


async def test_sentiment_excludes_bots_by_default(tmp_db, disable_auth):
    db = await _setup_db(tmp_db)
    now = datetime.utcnow()
    await db.execute(
        "INSERT INTO chat_log (account_id, channel, author, message, is_bot, sentiment, timestamp) "
        "VALUES (1, 'main', 'u1', 'круто!', 0, 1, ?)",
        (_ts(now - timedelta(minutes=2)),),
    )
    await db.execute(
        "INSERT INTO chat_log (account_id, channel, author, message, is_bot, sentiment, timestamp) "
        "VALUES (1, 'main', 'bot', 'круто!', 1, 1, ?)",
        (_ts(now - timedelta(minutes=2)),),
    )
    await db.commit()

    async with await _client() as client:
        r = await client.get("/api/stats/sentiment", params={"hours": 1})
        assert r.json()["summary"]["pos"] == 1
        r = await client.get("/api/stats/sentiment", params={"hours": 1, "include_bots": True})
        assert r.json()["summary"]["pos"] == 2


async def test_sentiment_bucket_size(tmp_db, disable_auth):
    db = await _setup_db(tmp_db)
    now = datetime.utcnow()
    for i in range(5):
        await db.execute(
            "INSERT INTO chat_log (account_id, channel, author, message, is_bot, sentiment, timestamp) "
            "VALUES (1, 'main', ?, '!', 0, 1, ?)",
            (f"u{i}", _ts(now - timedelta(minutes=i))),
        )
    await db.commit()

    async with await _client() as client:
        r = await client.get("/api/stats/sentiment", params={"hours": 1, "bucket_min": 60})
        data = r.json()
        # При 60-минутном bucket все 5 сообщений должны быть в одном/двух бакетах
        assert data["bucket_min"] == 60


async def test_sentiment_channel_filter(tmp_db, disable_auth):
    db = await _setup_db(tmp_db)
    now = datetime.utcnow()
    await db.execute(
        "INSERT INTO chat_log (account_id, channel, author, message, is_bot, sentiment, timestamp) "
        "VALUES (1, 'main', 'u1', '+', 0, 1, ?)",
        (_ts(now - timedelta(minutes=2)),),
    )
    await db.execute(
        "INSERT INTO chat_log (account_id, channel, author, message, is_bot, sentiment, timestamp) "
        "VALUES (1, 'other', 'u2', '+', 0, 1, ?)",
        (_ts(now - timedelta(minutes=2)),),
    )
    await db.commit()

    async with await _client() as client:
        r = await client.get("/api/stats/sentiment", params={"hours": 1, "channel": "main"})
        assert r.json()["summary"]["total"] == 1


async def test_sentiment_backfill(tmp_db, disable_auth):
    db = await _setup_db(tmp_db)
    now = datetime.utcnow()
    # Записи с sentiment=0 (нейтральный default), но их сообщения явно позитивные
    await db.execute(
        "INSERT INTO chat_log (account_id, channel, author, message, is_bot, sentiment, timestamp) "
        "VALUES (1, 'main', 'u1', 'это просто пушка круто!', 0, 0, ?)",
        (_ts(now - timedelta(minutes=2)),),
    )
    await db.execute(
        "INSERT INTO chat_log (account_id, channel, author, message, is_bot, sentiment, timestamp) "
        "VALUES (1, 'main', 'u2', 'отстой ужас', 0, 0, ?)",
        (_ts(now - timedelta(minutes=2)),),
    )
    await db.commit()

    async with await _client() as client:
        r = await client.post("/api/stats/sentiment/backfill", params={"limit": 100})
        data = r.json()
        assert data["scanned"] == 2
        assert data["updated"] == 2

        # После backfill — sentiment-эндпоинт должен видеть классифицированные
        r2 = await client.get("/api/stats/sentiment", params={"hours": 1})
        s = r2.json()["summary"]
        assert s["pos"] == 1
        assert s["neg"] == 1


# ---------- Word cloud ----------

async def test_wordcloud_empty(tmp_db, disable_auth):
    await _setup_db(tmp_db)
    async with await _client() as client:
        r = await client.get("/api/stats/wordcloud", params={"hours": 1})
        assert r.status_code == 200
        data = r.json()
        assert data["total_messages"] == 0
        assert data["items"] == []


async def test_wordcloud_top_words(tmp_db, disable_auth):
    db = await _setup_db(tmp_db)
    now = datetime.utcnow()
    msgs = [
        "играем в дотку",
        "опять дотка",
        "дотка дотка дотка",
        "патч новый сегодня",
    ]
    for i, m in enumerate(msgs):
        await db.execute(
            "INSERT INTO chat_log (account_id, channel, author, message, is_bot, timestamp) "
            "VALUES (1, 'main', ?, ?, 0, ?)",
            (f"u{i}", m, _ts(now - timedelta(minutes=i))),
        )
    await db.commit()

    async with await _client() as client:
        r = await client.get("/api/stats/wordcloud", params={"hours": 1, "top_n": 10})
        data = r.json()
        words = [item["word"] for item in data["items"]]
        assert "дотка" in words
        # «дотка» — самое частое
        assert data["items"][0]["word"] == "дотка"
        assert data["total_messages"] == 4


async def test_wordcloud_excludes_bots(tmp_db, disable_auth):
    db = await _setup_db(tmp_db)
    now = datetime.utcnow()
    await db.execute(
        "INSERT INTO chat_log (account_id, channel, author, message, is_bot, timestamp) "
        "VALUES (1, 'main', 'u1', 'играем в доту весь день', 0, ?)",
        (_ts(now - timedelta(minutes=2)),),
    )
    await db.execute(
        "INSERT INTO chat_log (account_id, channel, author, message, is_bot, timestamp) "
        "VALUES (1, 'main', 'bot', 'привет дота', 1, ?)",
        (_ts(now - timedelta(minutes=2)),),
    )
    await db.commit()

    async with await _client() as client:
        r = await client.get("/api/stats/wordcloud", params={"hours": 1})
        # Сообщение бота исключено
        assert r.json()["total_messages"] == 1


async def test_wordcloud_channel_filter(tmp_db, disable_auth):
    db = await _setup_db(tmp_db)
    now = datetime.utcnow()
    await db.execute(
        "INSERT INTO chat_log (account_id, channel, author, message, is_bot, timestamp) "
        "VALUES (1, 'main', 'u1', 'дотка дотка', 0, ?)",
        (_ts(now - timedelta(minutes=2)),),
    )
    await db.execute(
        "INSERT INTO chat_log (account_id, channel, author, message, is_bot, timestamp) "
        "VALUES (1, 'other', 'u2', 'фортнайт', 0, ?)",
        (_ts(now - timedelta(minutes=2)),),
    )
    await db.commit()

    async with await _client() as client:
        r = await client.get("/api/stats/wordcloud", params={"hours": 1, "channel": "main"})
        words = [item["word"] for item in r.json()["items"]]
        assert "дотка" in words
        assert "фортнайт" not in words


# ---------- Trending ----------

async def test_trending_empty(tmp_db, disable_auth):
    await _setup_db(tmp_db)
    async with await _client() as client:
        r = await client.get("/api/stats/trending", params={"period": "hour"})
        assert r.status_code == 200
        data = r.json()
        assert data["trending"] == []
        assert data["cooling"] == []


async def test_trending_finds_new_word(tmp_db, disable_auth):
    db = await _setup_db(tmp_db)
    now = datetime.utcnow()
    # Baseline (1-7h ago): обсуждали «доту»
    for i in range(20):
        await db.execute(
            "INSERT INTO chat_log (account_id, channel, author, message, is_bot, timestamp) "
            "VALUES (1, 'main', ?, 'опять дота', 0, ?)",
            (f"u{i}", _ts(now - timedelta(hours=2, minutes=i))),
        )
    # Current (last 1h): обсуждаем «патч»
    for i in range(15):
        await db.execute(
            "INSERT INTO chat_log (account_id, channel, author, message, is_bot, timestamp) "
            "VALUES (1, 'main', ?, 'новый патч сегодня', 0, ?)",
            (f"v{i}", _ts(now - timedelta(minutes=i + 1))),
        )
    await db.commit()

    async with await _client() as client:
        r = await client.get("/api/stats/trending", params={"period": "hour", "min_current": 3})
        data = r.json()
        words = [t["word"] for t in data["trending"]]
        assert "патч" in words
        # «патч» — в топ-3 trending (вместе с «новый»/«сегодня» равно частыми)
        top3 = [t["word"] for t in data["trending"][:3]]
        assert "патч" in top3


async def test_trending_returns_cooling_too(tmp_db, disable_auth):
    db = await _setup_db(tmp_db)
    now = datetime.utcnow()
    # Baseline: «дотка» 50 раз, «фарм» 50 раз
    for i in range(30):
        await db.execute(
            "INSERT INTO chat_log (account_id, channel, author, message, is_bot, timestamp) "
            "VALUES (1, 'main', ?, 'дотка фарм', 0, ?)",
            (f"u{i}", _ts(now - timedelta(hours=3, minutes=i))),
        )
    # Current: «дотка» исчезла, «патч» новый
    for i in range(20):
        await db.execute(
            "INSERT INTO chat_log (account_id, channel, author, message, is_bot, timestamp) "
            "VALUES (1, 'main', ?, 'патч сегодня', 0, ?)",
            (f"v{i}", _ts(now - timedelta(minutes=i + 1))),
        )
    await db.commit()

    async with await _client() as client:
        r = await client.get("/api/stats/trending", params={"period": "hour"})
        data = r.json()
        cooling_words = [c["word"] for c in data["cooling"]]
        assert "дотка" in cooling_words or "фарм" in cooling_words


async def test_trending_period_validation(tmp_db, disable_auth):
    await _setup_db(tmp_db)
    async with await _client() as client:
        r = await client.get("/api/stats/trending", params={"period": "invalid"})
        assert r.json()["period"] == "hour"  # default fallback


async def test_trending_day_period(tmp_db, disable_auth):
    db = await _setup_db(tmp_db)
    now = datetime.utcnow()
    for i in range(10):
        await db.execute(
            "INSERT INTO chat_log (account_id, channel, author, message, is_bot, timestamp) "
            "VALUES (1, 'main', ?, 'патч сегодня выходной', 0, ?)",
            (f"u{i}", _ts(now - timedelta(hours=i + 1))),
        )
    await db.commit()

    async with await _client() as client:
        r = await client.get("/api/stats/trending", params={"period": "day"})
        assert r.status_code == 200
        assert r.json()["period"] == "day"
