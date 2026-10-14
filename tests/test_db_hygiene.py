"""PLAN_CURRENT §5: гигиена БД — мёртвые таблицы удалены, cleanup детей бота."""

from __future__ import annotations

import pytest
import pytest_asyncio

from app import database
from app.database import ACCOUNT_CHILD_TABLES, cleanup_account_children

DEAD_TABLES = (
    "personality_shift_state", "shared_chatter_facts", "raid_context_log",
    "streamer_events", "streamer_stats", "voice_speakers",
)


@pytest_asyncio.fixture(autouse=True)
async def _schema(tmp_db):
    await database.init_db()


async def _tables(db) -> set[str]:
    cur = await db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    rows = await cur.fetchall()
    return {r["name"] for r in rows}


@pytest.mark.asyncio
async def test_legacy_dead_tables_preserved_until_owner_migration(tmp_db):
    """Политика 06.09 (стейт аудита, OPS): legacy-таблицы не дропаются автоматически.

    Destructive cleanup требует отдельной owner-approved миграции после проверки
    retention/restore (см. комментарий в app/database.py у roles-accounts).
    init_db не создаёт эти таблицы, но и не удаляет их из старых баз.
    """
    # сымитируем старую базу: создаём руками
    db = await database.get_db()
    try:
        for t in DEAD_TABLES:
            await db.execute(f"CREATE TABLE IF NOT EXISTS {t} (account_id INTEGER)")
        await db.commit()
    finally:
        await db.close()
    await database.init_db()  # повторный init — legacy не трогаем
    db = await database.get_db()
    try:
        tables = await _tables(db)
    finally:
        await db.close()
    assert set(DEAD_TABLES) <= tables, "legacy-таблицы должны сохраняться до owner-миграции"


@pytest.mark.asyncio
async def test_clip_moments_single_schema(tmp_db):
    """§5: clip_moments создаётся только из database.py (channel NOT NULL)."""
    db = await database.get_db()
    try:
        cur = await db.execute("PRAGMA table_info(clip_moments)")
        info = {r["name"]: (r["type"], r["notnull"]) for r in await cur.fetchall()}
    finally:
        await db.close()
    assert info["channel"][1] == 1  # NOT NULL (вариант database.py)
    assert info["timestamp"][0].upper() == "TIMESTAMP"


@pytest.mark.asyncio
async def test_cleanup_account_children_removes_orphans(tmp_db):
    db = await database.get_db()
    try:
        await db.execute("INSERT INTO accounts (id, nickname, token) VALUES (7, 'b7', 't')")
        await db.execute(
            "INSERT INTO bot_corrections (account_id, username, correction) VALUES (7, 'u', 'c')")
        await db.execute(
            "INSERT INTO stream_reports (account_id, channel, report_type, data) VALUES (7, 'ch', 'post_stream', '{}')")
        await db.execute(
            "INSERT INTO bot_topic_log (account_id, channel, topic) VALUES (7, 'ch', 'topic')")
        n = await cleanup_account_children(db, 7)
        assert n >= 3
        for t in ("bot_corrections", "stream_reports", "bot_topic_log"):
            cur = await db.execute(f"SELECT count(*) c FROM {t} WHERE account_id=7")
            row = await cur.fetchone()
            assert row["c"] == 0, t
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_delete_account_route_runs_cleanup(tmp_db, disable_auth):
    """DELETE /api/accounts/{id} чистит таблицы без FK перед удалением бота."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from app.routes import router

    db = await database.get_db()
    try:
        await db.execute("INSERT INTO accounts (id, nickname, token) VALUES (9, 'b9', 't')")
        await db.execute(
            "INSERT INTO bot_corrections (account_id, username, correction) VALUES (9, 'u', 'c')")
        await db.commit()
    finally:
        await db.close()

    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.delete("/api/accounts/9")
        assert r.json().get("ok") is True

    db = await database.get_db()
    try:
        cur = await db.execute("SELECT count(*) c FROM bot_corrections WHERE account_id=9")
        assert (await cur.fetchone())["c"] == 0
        cur = await db.execute("SELECT count(*) c FROM accounts WHERE id=9")
        assert (await cur.fetchone())["c"] == 0
    finally:
        await db.close()


def test_child_tables_list_sane():
    for t in ACCOUNT_CHILD_TABLES:
        assert t not in ("chat_log", "chat_users", "streamer_profile", "streamer_face"), \
            f"{t} — кросс-ботовая память, чистить нельзя"
