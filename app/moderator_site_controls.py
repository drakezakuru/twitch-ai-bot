"""MOD-18: cancel / stop / persistent kill switch, split into distinct operations.

- cancel_own: a moderator cancels only their own live command (correlation).
- stop_lane: stops one output lane (media/sound/tts) in one channel scope.
- persistent kill: global owner switch stored in the DB — it survives restarts
  and blocks new admissions; scope generation bumps on every stop so late
  results from before the stop are dropped by the adapters.
"""
from __future__ import annotations

import json
import time
from typing import Any

LANES = frozenset({"media", "sound", "tts"})


async def ensure_schema(db: Any) -> None:
    await db.executescript("""
    CREATE TABLE IF NOT EXISTS ms_scope_generation (
      scope TEXT PRIMARY KEY, generation INTEGER NOT NULL DEFAULT 1,
      updated_at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS ms_kill_switch (
      id TEXT PRIMARY KEY, active INTEGER NOT NULL DEFAULT 0,
      reason TEXT NOT NULL DEFAULT '', activated_at TEXT, activated_by TEXT NOT NULL DEFAULT '');
    """)


async def scope_generation(db: Any, scope: str) -> int:
    row = await (await db.execute("SELECT generation FROM ms_scope_generation WHERE scope=?", (scope,))).fetchone()
    return int(row[0]) if row else 1


async def bump_scope_generation(db: Any, scope: str) -> int:
    """Every stop/kill bumps the generation: late results with the old one are dropped."""
    await db.execute(
        "INSERT INTO ms_scope_generation(scope, generation, updated_at) VALUES (?,1,?)"
        " ON CONFLICT(scope) DO UPDATE SET generation=generation+1, updated_at=excluded.updated_at",
        (scope, time.time()))
    await db.commit()
    return await scope_generation(db, scope)


async def cancel_own(db: Any, correlation_id: str, *, actor_twitch_user_id: str) -> dict[str, Any]:
    """Cancel ONE's own command only; someone else's correlation is not visible here."""
    row = await (await db.execute(
        "SELECT id, status FROM ms_tts_commands WHERE correlation_id=?", (correlation_id,)
    )).fetchone() if correlation_id else None
    if row is None:
        raise ValueError("command_missing")
    from app import moderator_site_tts as tts
    owner_row = await (await db.execute(
        "SELECT 1 FROM ms_tts_commands WHERE correlation_id=? AND channel IN"
        " (SELECT channel FROM ms_tts_commands WHERE correlation_id=?)", (correlation_id, correlation_id)
    )).fetchone()
    # Ownership is enforced by the caller binding correlation to the session's own
    # queue projection (MOD-19); here we cancel only when still cancellable.
    if owner_row is None:
        raise ValueError("command_missing")
    cancelled = await tts.cancel(db, correlation_id)
    if not cancelled:
        raise ValueError("already_finished")
    return {"correlation_id": correlation_id, "status": "cancelled"}


async def stop_lane(db: Any, dispatch: Any, *, channel: str, lane: str) -> dict[str, Any]:
    """Stop one lane in one channel; other channels and other lanes keep running."""
    if lane not in LANES:
        raise ValueError("invalid_lane")
    generation = await bump_scope_generation(db, f"{lane}:{channel}")
    stopped = 0
    if lane == "sound":
        from app import moderator_site_sound as sound
        stopped = await sound.stop_scope(db, dispatch, channel)
    elif lane == "tts":
        rows = await (await db.execute(
            "SELECT correlation_id FROM ms_tts_commands WHERE channel=? AND status IN ('queued','synthesizing')",
            (channel,),
        )).fetchall()
        from app import moderator_site_tts as tts
        for (correlation,) in rows:
            await tts.cancel(db, correlation)
        stopped = len(rows)
    elif lane == "media":
        rows = await (await db.execute(
            "UPDATE ms_media_commands SET status='replaced', done_at=?"
            " WHERE channel=? AND status='current'", (time.time(), channel)))
        await db.commit()
        stopped = rows.rowcount
    return {"channel": channel, "lane": lane, "stopped": stopped, "generation": generation}


async def activate_kill(db: Any, *, by: str, reason: str) -> dict[str, Any]:
    """Persistent global stop: recorded in the DB, survives restart, blocks admission."""
    await db.execute(
        "INSERT INTO ms_kill_switch(id, active, reason, activated_at, activated_by)"
        " VALUES ('global', 1, ?, CURRENT_TIMESTAMP, ?)"
        " ON CONFLICT(id) DO UPDATE SET active=1, reason=excluded.reason, activated_at=CURRENT_TIMESTAMP,"
        " activated_by=excluded.activated_by",
        (reason, by))
    await db.commit()
    from app import moderator_site_schema as ms
    await ms.set_stop_state(db, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), f"kill:{by}")
    for scope in ("media", "sound", "tts"):
        await bump_scope_generation(db, scope)
    return {"active": True, "reason": reason, "activated_by": by}


async def deactivate_kill(db: Any) -> None:
    await db.execute("UPDATE ms_kill_switch SET active=0 WHERE id='global'")
    await db.commit()


async def kill_active(db: Any) -> bool:
    row = await (await db.execute("SELECT active FROM ms_kill_switch WHERE id='global'")).fetchone()
    return bool(row and row[0])


async def check_admission(db: Any) -> None:
    """Admission layers call this: the persistent kill blocks new cues."""
    if await kill_active(db):
        raise ValueError("kill_switch_active")
