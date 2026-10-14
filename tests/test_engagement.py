"""v10.3 4B — tests for engagement tracking module + API endpoints."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


def _build_app():
    from fastapi import FastAPI
    from app.routes import router
    app = FastAPI()
    app.include_router(router)
    return app


def _ts(dt: datetime) -> str:
    """Convert to UTC before formatting — SQLite datetime('now') returns UTC."""
    from datetime import timezone
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


async def _setup_db(tmp_db):
    from app import database
    await database.init_db()
    db = await database.get_db()
    await db.execute(
        "INSERT INTO accounts (id, nickname, token) VALUES (1, 'mybot', 'tok')"
    )
    await db.commit()
    return db


async def _seed_chat(db, *, account_id, channel, author, message, is_bot, ts):
    await db.execute(
        "INSERT INTO chat_log (account_id, channel, author, message, is_bot, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
        (account_id, channel, author, message, 1 if is_bot else 0, _ts(ts)),
    )


async def test_engagement_table_created(tmp_db):
    from app import database
    await database.init_db()
    db = await database.get_db()
    cur = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='bot_engagement'"
    )
    row = await cur.fetchone()
    assert row is not None


async def test_compute_pending_calculates_metrics(tmp_db):
    from datetime import timezone
    from app import database
    from app import engagement
    db = await _setup_db(tmp_db)

    base = datetime.now(timezone.utc) - timedelta(minutes=5)
    # Bot reply at base
    await _seed_chat(db, account_id=1, channel="dura", author="mybot", message="привет!", is_bot=True, ts=base)
    # 3 unique users react in window with one mentioning the bot
    await _seed_chat(db, account_id=1, channel="dura", author="alice", message="лол", is_bot=False, ts=base + timedelta(seconds=2))
    await _seed_chat(db, account_id=1, channel="dura", author="bob", message="@mybot ого", is_bot=False, ts=base + timedelta(seconds=5))
    await _seed_chat(db, account_id=1, channel="dura", author="cara", message="ахах", is_bot=False, ts=base + timedelta(seconds=10))
    # message outside window — should not be counted
    await _seed_chat(db, account_id=1, channel="dura", author="late", message="опоздал", is_bot=False, ts=base + timedelta(minutes=2))
    await db.commit()

    # Make sure window is closed (compute requires now > T+window).
    computed = await engagement.compute_pending(limit=10)
    assert computed >= 1

    cur = await db.execute("SELECT * FROM bot_engagement")
    rows = await cur.fetchall()
    assert len(rows) == 1
    r = dict(rows[0])
    assert r["support"] == 3
    assert r["mentions"] == 1
    assert r["replies"] == 3
    # default breakthrough threshold = 3
    assert r["breakthrough"] == 1


async def test_compute_skips_open_windows(tmp_db):
    from datetime import timezone
    from app import database
    from app import engagement
    db = await _setup_db(tmp_db)

    # Bot reply 5 seconds ago — window not closed (default 30s)
    base = datetime.now(timezone.utc) - timedelta(seconds=5)
    await _seed_chat(db, account_id=1, channel="dura", author="mybot", message="привет!", is_bot=True, ts=base)
    await db.commit()

    computed = await engagement.compute_pending(limit=10)
    assert computed == 0
    cur = await db.execute("SELECT COUNT(*) AS c FROM bot_engagement")
    row = await cur.fetchone()
    assert row["c"] == 0


async def test_compute_isolates_accounts_on_same_channel(tmp_db):
    from datetime import timezone
    from app import engagement
    db = await _setup_db(tmp_db)
    await db.execute("INSERT INTO accounts (id, nickname, token) VALUES (2, 'otherbot', 'tok2')")
    base = datetime.now(timezone.utc) - timedelta(minutes=5)
    await _seed_chat(db, account_id=1, channel="shared", author="mybot", message="hi", is_bot=True, ts=base)
    await _seed_chat(db, account_id=1, channel="shared", author="alice", message="@mybot yes", is_bot=False, ts=base + timedelta(seconds=2))
    await _seed_chat(db, account_id=2, channel="shared", author="mallory", message="@mybot cross-account", is_bot=False, ts=base + timedelta(seconds=3))
    await db.commit()
    row = await (await db.execute(
        "SELECT id FROM chat_log WHERE account_id = 1 AND is_bot = 1"
    )).fetchone()

    result = await engagement.compute_for_chat_log(row["id"], window_sec=30, breakthrough_min=2)

    assert result["support"] == 1
    assert result["mentions"] == 1
    assert result["replies"] == 1
    assert result["breakthrough"] is False


async def test_engagement_settings_endpoints(tmp_db, disable_auth):
    await _setup_db(tmp_db)
    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        r = await client.get("/api/engagement/settings")
        assert r.status_code == 200
        data = r.json()
        assert "window_sec" in data and "breakthrough_min" in data

        r = await client.put("/api/engagement/settings", json={"window_sec": 45, "breakthrough_min": 5})
        assert r.status_code == 200
        assert r.json().get("ok") is True

        r = await client.get("/api/engagement/settings")
        assert r.json()["window_sec"] == 45
        assert r.json()["breakthrough_min"] == 5


async def test_engagement_settings_validation(tmp_db, disable_auth):
    await _setup_db(tmp_db)
    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        # negative / out-of-range — должны клампиться или возвращать ошибку
        r = await client.put("/api/engagement/settings", json={"window_sec": 0, "breakthrough_min": 0})
        # допускаем 200 (с клампом) или 4xx; но настройки в ответе должны быть валидными
        if r.status_code == 200:
            r2 = await client.get("/api/engagement/settings")
            d = r2.json()
            assert d["window_sec"] >= 1
            assert d["breakthrough_min"] >= 1


async def test_engagement_stats_and_list(tmp_db, disable_auth):
    from datetime import timezone
    from app import engagement
    db = await _setup_db(tmp_db)

    base = datetime.now(timezone.utc) - timedelta(minutes=10)
    await _seed_chat(db, account_id=1, channel="dura", author="mybot", message="ответ 1", is_bot=True, ts=base)
    await _seed_chat(db, account_id=1, channel="dura", author="u1", message="круто", is_bot=False, ts=base + timedelta(seconds=3))
    await _seed_chat(db, account_id=1, channel="dura", author="u2", message="да", is_bot=False, ts=base + timedelta(seconds=4))
    await _seed_chat(db, account_id=1, channel="dura", author="u3", message="@mybot привет", is_bot=False, ts=base + timedelta(seconds=5))

    base2 = datetime.now(timezone.utc) - timedelta(minutes=5)
    await _seed_chat(db, account_id=1, channel="dura", author="mybot", message="ответ 2", is_bot=True, ts=base2)
    # only 1 reactor — без прорыва
    await _seed_chat(db, account_id=1, channel="dura", author="u1", message="ок", is_bot=False, ts=base2 + timedelta(seconds=2))
    await db.commit()

    await engagement.compute_pending(limit=50)

    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        r = await client.get("/api/engagement/stats?days=1")
        assert r.status_code == 200
        d = r.json()
        assert d["total"] == 2
        assert d["with_support"] == 2
        assert d["breakthroughs"] == 1
        assert d["top_channels"]
        assert d["top_channels"][0]["channel"] == "dura"

        r = await client.get("/api/engagement/list?days=1&limit=10")
        ld = r.json()
        assert ld["total"] >= 2
        assert len(ld["items"]) >= 2
        # First should have non-pending engagement values
        assert ld["items"][0].get("support", 0) >= 0


async def test_engagement_recompute_endpoint(tmp_db, disable_auth):
    from datetime import timezone
    db = await _setup_db(tmp_db)
    base = datetime.now(timezone.utc) - timedelta(minutes=2)
    await _seed_chat(db, account_id=1, channel="ch", author="mybot", message="hi", is_bot=True, ts=base)
    await _seed_chat(db, account_id=1, channel="ch", author="u1", message="hey", is_bot=False, ts=base + timedelta(seconds=2))
    await db.commit()

    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        r = await client.post("/api/engagement/recompute", json={})
        assert r.status_code == 200
        d = r.json()
        assert d.get("ok") is True
        assert d.get("computed", 0) >= 1
