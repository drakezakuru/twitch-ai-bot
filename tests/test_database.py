"""Тесты Feature S: singleton-коннекшн пул и no-op close."""
from __future__ import annotations

import sqlite3

import pytest

pytestmark = pytest.mark.asyncio


async def test_init_creates_tables(tmp_db):
    from app import database
    await database.init_db()
    db = await database.get_db()
    cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in await cursor.fetchall()]
    await db.close()  # no-op
    for required in ("accounts", "channels", "prompt_variants", "user_memory"):
        assert required in tables, f"missing table {required}"


async def test_singleton_returns_same_real_connection(tmp_db):
    from app import database
    await database.init_db()
    db1 = await database.get_db()
    db2 = await database.get_db()
    # _DBProxy обёртки разные, но real коннект один
    assert db1._real is db2._real


async def test_close_is_noop(tmp_db):
    """db.close() не должен закрывать реальное соединение."""
    from app import database
    await database.init_db()
    db = await database.get_db()
    await db.close()
    # После close() всё ещё можно делать запросы
    cur = await db.execute("SELECT 1 AS v")
    row = await cur.fetchone()
    assert row[0] == 1


async def test_close_db_cleans_singleton(tmp_db):
    from app import database
    await database.init_db()
    db = await database.get_db()
    real = db._real
    await database.close_db()
    # После close_db singleton сброшен
    assert database._shared_db is None
    # Новое get_db() создаст новое реальное соединение
    db2 = await database.get_db()
    assert db2._real is not real


async def test_c7_response_patterns_are_absent_but_quality_tables_remain(tmp_db):
    from app import database
    await database.init_db()
    db = await database.get_db()
    rows = await (await db.execute("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    names = {row["name"] for row in rows}
    assert "patterns" not in names
    assert "pattern_variants" not in names
    assert {"prompt_variants", "ai_feedback", "bot_response_feedback"} <= names


async def test_init_preserves_legacy_tables_and_rows(tmp_db):
    legacy_tables = (
        "personality_shift_state", "shared_chatter_facts", "raid_context_log",
        "streamer_events", "streamer_stats", "voice_speakers",
    )
    with sqlite3.connect(tmp_db) as conn:
        for table in legacy_tables:
            conn.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, marker TEXT)")
            conn.execute(f"INSERT INTO {table} (marker) VALUES ('keep-me')")

    from app import database
    await database.init_db()
    db = await database.get_db()
    for table in legacy_tables:
        row = await (await db.execute(f"SELECT marker FROM {table}")).fetchone()
        assert row["marker"] == "keep-me"
