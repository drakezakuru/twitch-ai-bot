"""PLAN_FEEDBACK_2908 P0: схема виджетов накатывается на старте панели.

Симптом из bot.log (29.08, 12:25): `no such table: now_playing_settings /
donation_integrations / top_donator_settings / countdown_timer`,
`no such column: stream_goals.percent`, `no such column:
song_request_settings.cooldown_sec` — ensure-блок widgets.py не выполнялся
на старте. Фикс: database.init_db() вызывает widgets.ensure_widgets_schema().

Тест: имитирует «старую БД» (без новых таблиц/колонок) → init_db →
публичные виджет-роуты отвечают 200.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio

# Таблицы виджетов, которых нет в database.py (создаёт только widgets.py).
WIDGET_ONLY_TABLES = (
    "bot_corrections",
    "chat_reader_settings",
    "countdown_timer",
    "custom_poll",
    "donation_challenges",
    "donation_goal_sync",
    "donation_integration_settings",
    "donation_integrations",
    "donations",
    "emoji_stats",
    "latest_event_card_settings",
    "now_playing_settings",
    "sr_priority_users",
    "stream_reports",
    "subathon_timer",
    "top_donator_settings",
    "widget_bindings",
)


async def _degrade_to_old_db(db_path) -> None:
    """Превращает свежую БД в «старую»: убирает новые таблицы и колонки."""
    import aiosqlite

    async with aiosqlite.connect(db_path) as db:
        for table in WIDGET_ONLY_TABLES:
            await db.execute(f"DROP TABLE IF EXISTS {table}")
        # Старые формы таблиц с «миграционными» колонками.
        await db.execute("DROP TABLE IF EXISTS stream_goals")
        await db.execute(
            "CREATE TABLE stream_goals ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "text TEXT NOT NULL,"
            "done INTEGER DEFAULT 0,"
            "sort_order INTEGER DEFAULT 0,"
            "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        await db.execute("DROP TABLE IF EXISTS song_request_settings")
        await db.execute(
            "CREATE TABLE song_request_settings ("
            "id INTEGER PRIMARY KEY,"
            "enabled INTEGER DEFAULT 1,"
            "max_queue INTEGER DEFAULT 50,"
            "theme TEXT DEFAULT 'neon',"
            "visible INTEGER DEFAULT 1,"
            "show_count INTEGER DEFAULT 4,"
            "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        await db.execute("DROP TABLE IF EXISTS song_request_queue")
        await db.execute(
            "CREATE TABLE song_request_queue ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "title TEXT NOT NULL,"
            "requested_by TEXT NOT NULL DEFAULT '',"
            "channel TEXT NOT NULL DEFAULT '',"
            "status TEXT NOT NULL DEFAULT 'queued',"
            "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        await db.commit()


async def _table_columns(db_path, table: str) -> set[str]:
    import aiosqlite

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(f"PRAGMA table_info({table})")
        return {row[1] for row in await cursor.fetchall()}


async def _table_exists(db_path, table: str) -> bool:
    import aiosqlite

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        )
        return await cursor.fetchone() is not None


async def test_init_db_repairs_old_db(tmp_db):
    from app.database import init_db

    await init_db()  # свежая БД
    await _degrade_to_old_db(tmp_db)
    for table in WIDGET_ONLY_TABLES:
        assert not await _table_exists(tmp_db, table)
    assert "percent" not in await _table_columns(tmp_db, "stream_goals")
    assert "cooldown_sec" not in await _table_columns(tmp_db, "song_request_settings")
    assert "priority" not in await _table_columns(tmp_db, "song_request_queue")

    await init_db()  # «старт панели» на старой БД — должен всё починить

    for table in WIDGET_ONLY_TABLES:
        assert await _table_exists(tmp_db, table), f"нет таблицы {table}"
    assert "percent" in await _table_columns(tmp_db, "stream_goals")
    assert "cooldown_sec" in await _table_columns(tmp_db, "song_request_settings")
    assert "max_per_user" in await _table_columns(tmp_db, "song_request_settings")
    assert "priority" in await _table_columns(tmp_db, "song_request_queue")


async def test_donation_challenge_scope_migration_preserves_legacy_rows(tmp_db):
    import aiosqlite
    from app.database import init_db
    from app.widgets import ensure_widgets_schema

    await init_db()
    async with aiosqlite.connect(tmp_db) as db:
        await db.execute("DROP TABLE donation_challenges")
        await db.execute(
            "CREATE TABLE donation_challenges ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, "
            "target_amount REAL NOT NULL, current_amount REAL DEFAULT 0, "
            "active INTEGER DEFAULT 1, completed INTEGER DEFAULT 0, "
            "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        await db.execute(
            "INSERT INTO donation_challenges (title, target_amount, current_amount) "
            "VALUES ('Legacy', 100, 25)"
        )
        await db.commit()

    await ensure_widgets_schema()

    assert {"account_id", "channel"} <= await _table_columns(tmp_db, "donation_challenges")
    async with aiosqlite.connect(tmp_db) as db:
        db.row_factory = aiosqlite.Row
        row = await (await db.execute(
            "SELECT title, current_amount, account_id, channel FROM donation_challenges"
        )).fetchone()
    assert dict(row) == {
        "title": "Legacy", "current_amount": 25.0,
        "account_id": None, "channel": None,
    }


async def test_widget_public_routes_200_after_old_db_init(tmp_db, disable_auth):
    """Список роутов из бага владельца: /goals, /countdown, /top-donator/*,
    /song-request, /now-playing — после init_db на «старой» БД отвечают 200."""
    from app.database import init_db

    await init_db()
    await _degrade_to_old_db(tmp_db)
    await init_db()

    from app.widgets import admin_router, public_router
    from app.routes import router as api_router

    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(api_router)
    app.include_router(admin_router)
    app.include_router(public_router)

    endpoints = (
        "/api/widgets/public/goals",
        "/api/widgets/public/countdown",
        "/api/widgets/public/top-donator/alltime",
        "/api/widgets/public/top-donator/month",
        "/api/widgets/public/top-donator/day",
        "/api/widgets/public/song-request",
        "/api/widgets/public/now-playing",
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for url in endpoints:
            resp = await client.get(url)
            assert resp.status_code == 200, f"{url} -> {resp.status_code}: {resp.text[:200]}"
