"""Moderator-site persistence primitives (MOD-04).

Idempotent schema: revision ledger, transactional outbox and the stop-state record.
The panel reads legacy data unchanged; no GET path ever inserts defaults.
"""
from __future__ import annotations

import json
from typing import Any

SCHEMA_REVISION = "moderator-site/v1"


async def ensure_schema(db: Any) -> None:
    """Create idempotent tables/indexes; safe to run twice and on legacy databases."""
    await db.executescript("""
    CREATE TABLE IF NOT EXISTS ms_schema_revisions (
      name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);

    CREATE TABLE IF NOT EXISTS ms_outbox (
      id TEXT PRIMARY KEY, event_type TEXT NOT NULL,
      payload_json TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      dispatched_at TEXT);

    CREATE INDEX IF NOT EXISTS ms_outbox_pending
      ON ms_outbox(dispatched_at, created_at);

    CREATE TABLE IF NOT EXISTS ms_stop_state (
      id TEXT PRIMARY KEY CHECK (id = 'current'),
      stopped_at TEXT NOT NULL,
      origin TEXT NOT NULL DEFAULT 'moderator',
      ack_result_json TEXT NOT NULL DEFAULT '{}');
    """)
    existing = {row[0] for row in await (await db.execute("SELECT name FROM ms_schema_revisions")).fetchall()}
    if SCHEMA_REVISION not in existing:
        # One deterministic marker row; second run is a no-op (idempotent).
        await db.execute("INSERT OR IGNORE INTO ms_schema_revisions(name) VALUES (?)", (SCHEMA_REVISION,))
    await db.commit()


async def append_outbox(db: Any, event_id: str, event_type: str, payload: dict[str, Any]) -> None:
    """Transactional enqueue: committed atomically with the caller's writes."""
    await db.execute(
        "INSERT INTO ms_outbox(id, event_type, payload_json) VALUES (?,?,?)",
        (event_id, event_type, json.dumps(payload, ensure_ascii=False)),
    )


async def claim_outbox(db: Any, limit: int = 10) -> list[tuple[str, str, dict]]:
    """Atomically claim pending events: UPDATE marks them dispatched inside one tx."""
    await db.execute("BEGIN IMMEDIATE")
    try:
        rows = await (await db.execute(
            "SELECT id, event_type, payload_json FROM ms_outbox WHERE dispatched_at IS NULL ORDER BY created_at LIMIT ?",
            (limit,),
        )).fetchall()
        for row in rows:
            await db.execute("UPDATE ms_outbox SET dispatched_at=CURRENT_TIMESTAMP WHERE id=?", (row[0],))
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return [(row[0], row[1], json.loads(row[2])) for row in rows]


async def get_stop_state(db: Any) -> dict[str, Any] | None:
    """Read-only; never creates a default row (GET inserts nothing)."""
    row = await (await db.execute(
        "SELECT stopped_at, origin, ack_result_json FROM ms_stop_state WHERE id='current'"
    )).fetchone()
    if row is None:
        return None
    return {"stopped_at": row[0], "origin": row[1], "ack": json.loads(row[2])}


async def set_stop_state(db: Any, stopped_at: str, origin: str = "moderator") -> None:
    """Stop state survives unknown playback results; the ack may arrive later."""
    await db.execute(
        "INSERT INTO ms_stop_state(id, stopped_at, origin) VALUES ('current', ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET stopped_at=excluded.stopped_at, origin=excluded.origin",
        (stopped_at, origin),
    )
    await db.commit()


async def set_stop_ack(db: Any, ack: dict[str, Any]) -> None:
    await db.execute(
        "UPDATE ms_stop_state SET ack_result_json=? WHERE id='current'",
        (json.dumps(ack, ensure_ascii=False),),
    )
    await db.commit()
