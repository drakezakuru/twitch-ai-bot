"""MOD-17: output evidence and executor lease.

One active executor per output holds a generation-scoped lease with heartbeats;
everyone else is an observer with NO ack capability. ACKs are validated against
the lease generation and a strictly increasing sequence; evidence is recorded as
append-only events. Evidence proves the renderer reported success — it is NOT an
OBS acceptance claim.
"""
from __future__ import annotations

import secrets
import time
from typing import Any

LEASE_TTL_SEC = 60


async def ensure_schema(db: Any) -> None:
    await db.executescript("""
    CREATE TABLE IF NOT EXISTS ms_output_leases (
      output TEXT PRIMARY KEY, executor_id TEXT NOT NULL,
      generation INTEGER NOT NULL DEFAULT 1,
      heartbeat_at REAL NOT NULL, released INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS ms_output_events (
      id TEXT PRIMARY KEY, output TEXT NOT NULL, executor_id TEXT NOT NULL,
      generation INTEGER NOT NULL, seq INTEGER NOT NULL,
      kind TEXT NOT NULL, payload_json TEXT NOT NULL DEFAULT '{}',
      created_at REAL NOT NULL,
      UNIQUE(output, generation, seq));
    """)


async def acquire_lease(db: Any, output: str, executor_id: str, *, now: float | None = None) -> dict[str, Any]:
    """Active executor wins the lease; a second source becomes an observer."""
    now = time.time() if now is None else now
    row = await (await db.execute("SELECT executor_id, generation, heartbeat_at, released FROM ms_output_leases WHERE output=?", (output,))).fetchone()
    if row is not None and not row[3] and row[0] != executor_id and now - row[2] < LEASE_TTL_SEC:
        return {"output": output, "role": "observer", "generation": int(row[1]), "executor_id": row[0]}
    if row is None:
        generation = 1
        await db.execute(
            "INSERT INTO ms_output_leases(output, executor_id, generation, heartbeat_at) VALUES (?,?,1,?)",
            (output, executor_id, now))
    else:
        generation = int(row[1]) + 1  # every (re)acquire bumps the generation
        await db.execute(
            "UPDATE ms_output_leases SET executor_id=?, generation=?, heartbeat_at=?, released=0 WHERE output=?",
            (executor_id, generation, now, output))
    await db.commit()
    return {"output": output, "role": "executor", "generation": generation, "executor_id": executor_id}


async def heartbeat(db: Any, output: str, executor_id: str, *, generation: int, now: float | None = None) -> None:
    now = time.time() if now is None else now
    cursor = await db.execute(
        "UPDATE ms_output_leases SET heartbeat_at=? WHERE output=? AND executor_id=? AND generation=? AND released=0",
        (now, output, executor_id, generation))
    await db.commit()
    if not cursor.rowcount:
        raise ValueError("lease_lost")


async def release_lease(db: Any, output: str, executor_id: str, *, generation: int) -> None:
    cursor = await db.execute(
        "UPDATE ms_output_leases SET released=1 WHERE output=? AND executor_id=? AND generation=?",
        (output, executor_id, generation))
    await db.commit()
    if not cursor.rowcount:
        raise ValueError("lease_lost")


async def record_ack(db: Any, *, output: str, executor_id: str, generation: int, seq: int,
                     kind: str = "ack", payload: dict[str, Any] | None = None,
                     now: float | None = None) -> dict[str, Any]:
    """Limited ACK capability: only the active executor at the current generation."""
    now = time.time() if now is None else now
    if seq < 1:
        raise ValueError("invalid_sequence")
    lease = await (await db.execute(
        "SELECT executor_id, generation, heartbeat_at, released FROM ms_output_leases WHERE output=?", (output,)
    )).fetchone()
    if lease is None or lease[3]:
        raise ValueError("no_active_lease")
    if int(lease[1]) != int(generation):
        # A pre-takeover client reports its stale generation first.
        raise ValueError("stale_generation")
    if lease[0] != executor_id:
        raise ValueError("observer_cannot_ack")  # two sources: only the executor may ack
    if time.time() - lease[2] > LEASE_TTL_SEC:
        raise ValueError("heartbeat_lost")
    event_id = secrets.token_hex(16)
    try:
        await db.execute(
            "INSERT INTO ms_output_events(id, output, executor_id, generation, seq, kind, payload_json, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (event_id, output, executor_id, generation, seq, kind,
             __import__("json").dumps(payload or {}, ensure_ascii=False), now))
        await db.commit()
    except Exception as exc:
        await db.rollback()
        text = str(exc)
        if "UNIQUE" in text:
            raise ValueError("duplicate_or_out_of_order_ack") from exc
        raise
    return {"event_id": event_id, "output": output, "generation": generation, "seq": seq}


async def evidence(db: Any, output: str) -> list[dict[str, Any]]:
    rows = await (await db.execute(
        "SELECT generation, seq, kind, created_at FROM ms_output_events WHERE output=? ORDER BY generation, seq",
        (output,))).fetchall()
    return [{"generation": r[0], "seq": r[1], "kind": r[2], "created_at": r[3]} for r in rows]
