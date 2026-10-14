"""Тесты Feature V: heatmap активности чата."""
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


async def _setup_with_recent_data(tmp_db):
    """Создаёт БД и наполняет сообщениями с известными dow/hour
    (timestamp в пределах последней недели — чтобы не зависеть от системной даты)."""
    from app import database
    await database.init_db()
    db = await database.get_db()
    await db.execute(
        "INSERT INTO accounts (id, nickname, token) VALUES (1, 'streamer', 'tok')"
    )

    # Берём «последнее воскресенье» относительно UTC-сейчас
    now = datetime.utcnow()
    # Найдём самое свежее воскресенье 12:00 (включая сегодняшнее, если сегодня вс)
    days_since_sunday = (now.weekday() + 1) % 7  # weekday: Mon=0..Sun=6 → days_since_sunday: Sun→0, Mon→1, ...
    last_sunday_noon = (now - timedelta(days=days_since_sunday)).replace(hour=12, minute=0, second=0, microsecond=0)
    # Если воскресенье 12:00 ещё впереди (т.е. сегодня = воскресенье и сейчас 11:00), берём предыдущее
    if last_sunday_noon > now:
        last_sunday_noon -= timedelta(days=7)
    sunday_noon = last_sunday_noon
    # Понедельник этой недели — sunday + 1 day at 18:00
    monday_eve = sunday_noon + timedelta(days=1)
    monday_eve = monday_eve.replace(hour=18, minute=0)
    if monday_eve > now:
        monday_eve -= timedelta(days=7)
    # Среда — sunday + 3 days at 02:00
    wednesday_night = sunday_noon + timedelta(days=3)
    wednesday_night = wednesday_night.replace(hour=2, minute=0)
    if wednesday_night > now:
        wednesday_night -= timedelta(days=7)

    msgs = []
    for i in range(5):
        msgs.append((sunday_noon + timedelta(minutes=i * 10), f"u_sun_{i}", 0))
    for i in range(3):
        msgs.append((monday_eve + timedelta(minutes=i * 10), f"u_mon_{i}", 0))
    for i in range(2):
        msgs.append((wednesday_night + timedelta(minutes=i * 10), f"u_wed_{i}", 0))
    # Бот-сообщение — не должно учитываться
    msgs.append((wednesday_night + timedelta(minutes=30), "bot", 1))

    for ts, author, is_bot in msgs:
        await db.execute(
            "INSERT INTO chat_log (account_id, channel, author, message, is_bot, timestamp) "
            "VALUES (1, 'main', ?, ?, ?, ?)",
            (author, "msg", is_bot, _ts(ts)),
        )
    await db.commit()
    return AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test")


async def test_heatmap_returns_7x24_grid(tmp_db, disable_auth):
    async with await _setup_with_recent_data(tmp_db) as client:
        r = await client.get("/api/stats/heatmap", params={"days": 30})
        assert r.status_code == 200
        data = r.json()
        assert len(data["grid"]) == 7 * 24
        for cell in data["grid"]:
            assert "dow" in cell and "hour" in cell and "count" in cell
            assert 0 <= cell["dow"] <= 6
            assert 0 <= cell["hour"] <= 23


async def test_heatmap_counts_correctly(tmp_db, disable_auth):
    """Counts попадают в правильные ячейки по ISO-day-of-week (Пн=0..Вс=6).

    Sunday → ISO dow=6 (5 сообщений в час 12:00),
    Monday → ISO dow=0 (3 сообщения в час 18:00),
    Wednesday → ISO dow=2 (2 сообщения в час 02:00).
    Бот не учитывается.
    """
    async with await _setup_with_recent_data(tmp_db) as client:
        r = await client.get("/api/stats/heatmap", params={"days": 30})
        data = r.json()
        cells_by_key = {(c["dow"], c["hour"]): c["count"] for c in data["grid"]}
        assert cells_by_key[(6, 12)] == 5  # воскресенье 12:00
        assert cells_by_key[(0, 18)] == 3  # понедельник 18:00
        assert cells_by_key[(2, 2)] == 2   # среда 02:00


async def test_heatmap_excludes_bot_messages(tmp_db, disable_auth):
    """Bot messages (is_bot=1) исключаются из heatmap."""
    async with await _setup_with_recent_data(tmp_db) as client:
        r = await client.get("/api/stats/heatmap", params={"days": 30})
        data = r.json()
        # 5 + 3 + 2 = 10 человеческих, бот не считается
        assert data["total"] == 10


async def test_heatmap_max_cell(tmp_db, disable_auth):
    async with await _setup_with_recent_data(tmp_db) as client:
        r = await client.get("/api/stats/heatmap", params={"days": 30})
        data = r.json()
        assert data["max_cell"] == 5


async def test_heatmap_filters_by_channel(tmp_db, disable_auth):
    async with await _setup_with_recent_data(tmp_db) as client:
        r = await client.get("/api/stats/heatmap", params={"days": 30, "channel": "other"})
        data = r.json()
        assert data["total"] == 0
        assert data["max_cell"] == 0
