"""MOD-04 gate: idempotent ms_* schema, transactional outbox, stop state, legacy safety."""
from __future__ import annotations

import pytest
import pytest_asyncio

from app import moderator_site_schema as ms


@pytest_asyncio.fixture
async def legacy_db(tmp_path):
    """aiosqlite connection over a DB that already holds legacy panel data."""
    import aiosqlite
    conn = await aiosqlite.connect(tmp_path / "ms.db")
    conn.row_factory = None
    await conn.execute("PRAGMA foreign_keys=ON")
    # Legacy panel fixture: pre-existing data the site must never disturb.
    await conn.execute("CREATE TABLE IF NOT EXISTS accounts (id INTEGER PRIMARY KEY, nickname TEXT)")
    await conn.execute("INSERT INTO accounts(id, nickname) VALUES (1, 'legacy-bot')")
    await conn.commit()
    yield conn
    await conn.close()


@pytest.mark.asyncio
async def test_schema_is_idempotent_across_double_run(legacy_db):
    await ms.ensure_schema(legacy_db)
    await ms.ensure_schema(legacy_db)  # second run: no error, single revision row
    row = await (await legacy_db.execute("SELECT count(*) FROM ms_schema_revisions")).fetchone()
    assert row[0] == 1
    tables = {r[0] for r in await (await legacy_db.execute("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()}
    assert {"ms_schema_revisions", "ms_outbox", "ms_stop_state"} <= tables


@pytest.mark.asyncio
async def test_legacy_data_survives_migrations(legacy_db):
    await ms.ensure_schema(legacy_db)
    row = await (await legacy_db.execute("SELECT nickname FROM accounts WHERE id=1")).fetchone()
    assert row[0] == "legacy-bot"


@pytest.mark.asyncio
async def test_get_never_creates_defaults(legacy_db):
    await ms.ensure_schema(legacy_db)
    assert await ms.get_stop_state(legacy_db) is None  # pure read
    row = await (await legacy_db.execute("SELECT count(*) FROM ms_stop_state")).fetchone()
    assert row[0] == 0


@pytest.mark.asyncio
async def test_outbox_is_transactional_claim(legacy_db):
    await ms.ensure_schema(legacy_db)
    await ms.append_outbox(legacy_db, "e1", "stop_requested", {"channel": "x"})
    await ms.append_outbox(legacy_db, "e2", "stop_requested", {"channel": "y"})
    await legacy_db.commit()
    claimed = await ms.claim_outbox(legacy_db)
    assert {event_id for event_id, *_ in claimed} == {"e1", "e2"}
    # Second claim gets nothing: the first claim marked them dispatched atomically.
    assert await ms.claim_outbox(legacy_db) == []


@pytest.mark.asyncio
async def test_stop_state_survives_unknown_ack(legacy_db):
    await ms.ensure_schema(legacy_db)
    await ms.set_stop_state(legacy_db, "2026-09-10T20:00:00Z")
    state = await ms.get_stop_state(legacy_db)
    assert state is not None and state["stopped_at"] == "2026-09-10T20:00:00Z"
    # Late playback ack does not resurrect or erase the stop decision.
    await ms.set_stop_ack(legacy_db, {"acknowledged": True, "obs_confirmed": False})
    state = await ms.get_stop_state(legacy_db)
    assert state["ack"] == {"acknowledged": True, "obs_confirmed": False}
