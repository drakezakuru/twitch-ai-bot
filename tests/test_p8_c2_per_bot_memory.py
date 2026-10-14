"""P8-C2: общая память (shared_user_facts) → per-bot user_memory.

Вердикт владельца: общая вкладка «Общие факты (все боты)» удалена; чтобы
факты не потерялись, при старте панели они копируются в user_memory
каждого бота (идемпотентно — метка в settings). Промпт собирает факты
только из per-bot памяти.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio


async def _client():
    from app.database import init_db
    from app.routes import router
    await init_db()
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed_bot_and_shared_facts(tmp_db):
    from app.database import init_db, get_db
    await init_db()
    db = await get_db()
    try:
        await db.execute("INSERT OR IGNORE INTO accounts (id, nickname, token) VALUES (1,'b1','t'), (2,'b2','t')")
        await db.execute(
            """CREATE TABLE IF NOT EXISTS shared_user_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL, fact TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0.8,
                source_account_id INTEGER NOT NULL DEFAULT 0,
                last_seen TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                source_channel TEXT DEFAULT '',
                UNIQUE(username, fact))""")
        await db.execute(
            "INSERT OR IGNORE INTO shared_user_facts (username, fact, confidence) VALUES ('viewer', 'любит Minecraft', 0.9)")
        await db.commit()
    finally:
        await db.close()


async def test_migration_copies_facts_to_each_bot(tmp_db, disable_auth):
    await _seed_bot_and_shared_facts(tmp_db)
    from app.database import init_db
    from app.database import get_db
    await init_db()  # второй вызов → срабатывает миграция

    db = await get_db()
    try:
        for bot_id in (1, 2):
            cur = await db.execute("SELECT facts FROM user_memory WHERE account_id=? AND username='viewer'", (bot_id,))
            row = await cur.fetchone()
            assert row, f"боту {bot_id} не мигрировали факты"
            assert "любит Minecraft" in row["facts"]
        cur = await db.execute("SELECT fact FROM shared_user_facts WHERE username='viewer'")
        assert (await cur.fetchone())["fact"] == "любит Minecraft"
        # метка идемпотентности
        cur = await db.execute("SELECT value FROM settings WHERE key='shared_facts_migrated_to_per_bot'")
        assert (await cur.fetchone())["value"] == "1"
    finally:
        await db.close()


async def test_migration_idempotent(tmp_db, disable_auth):
    await _seed_bot_and_shared_facts(tmp_db)
    from app.database import init_db
    from app.database import get_db
    await init_db()
    await init_db()  # повторно — копий больше не стало

    db = await get_db()
    try:
        cur = await db.execute("SELECT COUNT(*) c FROM user_memory WHERE username='viewer'")
        assert (await cur.fetchone())["c"] == 2  # по одному на бота
    finally:
        await db.close()


async def test_per_bot_memory_api_still_works(tmp_db, disable_auth):
    await _seed_bot_and_shared_facts(tmp_db)
    from app.database import init_db
    await init_db()
    async with await _client() as c:
        r = await c.get("/api/accounts/1/memory/viewer")
        assert r.status_code == 200
        data = r.json()
        facts = data.get("facts") or []
        assert any("Minecraft" in str(f) for f in facts)


def test_chat_prompt_has_no_shared_block():
    src = (__import__("pathlib").Path(__file__).parent.parent /
           "app" / "chat_analyzer.py").read_text(encoding="utf-8")
    assert "shared_facts_block" not in src, "shared-блок вернулся в промпт"
