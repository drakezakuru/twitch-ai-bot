"""MOD-19: actor-filtered queue/history projection with snapshot/resume protocol.

A moderator's queue projection contains only items bound to their own grant
identity — another actor's TTS/commands are never included without the right.
The SSE protocol uses a monotonic revision: the client sends `Last-Event-ID`
(or revision+cursor); if the revision is stale it receives a fresh snapshot
instead of a replayed stream.
"""
from __future__ import annotations

import json
import secrets
import time
from typing import Any

HISTORY_PAGE = 50


async def ensure_schema(db: Any) -> None:
    await db.executescript("""
    CREATE TABLE IF NOT EXISTS ms_queue_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      channel TEXT NOT NULL, actor_twitch_user_id TEXT NOT NULL,
      kind TEXT NOT NULL, payload_json TEXT NOT NULL DEFAULT '{}',
      created_at REAL NOT NULL);
    CREATE INDEX IF NOT EXISTS ms_queue_actor ON ms_queue_events(channel, actor_twitch_user_id, id);
    """)


async def emit(db: Any, *, channel: str, actor_twitch_user_id: str, kind: str,
               payload: dict[str, Any] | None = None) -> int:
    cursor = await db.execute(
        "INSERT INTO ms_queue_events(channel, actor_twitch_user_id, kind, payload_json, created_at)"
        " VALUES (?,?,?,?,?)",
        (channel, actor_twitch_user_id, kind, json.dumps(payload or {}, ensure_ascii=False), time.time()))
    await db.commit()
    return cursor.lastrowid


async def current_revision(db: Any) -> int:
    row = await (await db.execute("SELECT max(id) FROM ms_queue_events")).fetchone()
    return int(row[0]) if row and row[0] else 0


def _dto(row: tuple) -> dict[str, Any]:
    return {"event_id": row[0], "kind": row[1], "payload": json.loads(row[2]), "created_at": row[3]}


async def snapshot(db: Any, *, channel: str, actor_twitch_user_id: str,
                   limit: int = HISTORY_PAGE) -> dict[str, Any]:
    """Actor-filtered projection: rows of OTHER actors are never revealed here."""
    rows = await (await db.execute(
        "SELECT id, kind, payload_json, created_at FROM ms_queue_events"
        " WHERE channel=? AND actor_twitch_user_id=? ORDER BY id DESC LIMIT ?",
        (channel, actor_twitch_user_id, max(1, min(limit, 200))),
    )).fetchall()
    return {"revision": await current_revision(db), "items": [_dto(r) for r in rows], "reset": True}


async def resume(db: Any, *, channel: str, actor_twitch_user_id: str,
                 last_event_id: int, revision: int) -> dict[str, Any]:
    """Delta since the client's cursor; stale revision forces a full snapshot."""
    current = await current_revision(db)
    if revision < 0 or last_event_id < 0:
        raise ValueError("invalid_cursor")
    if revision > current or last_event_id > current:
        # Client claims a future revision — cannot be trusted with a delta.
        return await snapshot(db, channel=channel, actor_twitch_user_id=actor_twitch_user_id)
    min_row = await (await db.execute(
        "SELECT min(id) FROM ms_queue_events WHERE channel=? AND actor_twitch_user_id=?",
        (channel, actor_twitch_user_id),
    )).fetchone()
    if min_row[0] is not None and last_event_id < int(min_row[0]) - 1:
        # The gap includes purged history: a delta would silently miss events.
        return await snapshot(db, channel=channel, actor_twitch_user_id=actor_twitch_user_id)
    rows = await (await db.execute(
        "SELECT id, kind, payload_json, created_at FROM ms_queue_events"
        " WHERE channel=? AND actor_twitch_user_id=? AND id>? ORDER BY id LIMIT ?",
        (channel, actor_twitch_user_id, last_event_id, 200),
    )).fetchall()
    return {"revision": current, "items": [_dto(r) for r in rows], "reset": False}


async def history_page(db: Any, *, channel: str, actor_twitch_user_id: str,
                       before_event_id: int | None = None,
                       limit: int = HISTORY_PAGE) -> dict[str, Any]:
    """Long-list pagination backwards from `before_event_id`."""
    limit = max(1, min(limit, 200))
    if before_event_id is not None:
        rows = await (await db.execute(
            "SELECT id, kind, payload_json, created_at FROM ms_queue_events"
            " WHERE channel=? AND actor_twitch_user_id=? AND id<? ORDER BY id DESC LIMIT ?",
            (channel, actor_twitch_user_id, before_event_id, limit + 1),
        )).fetchall()
    else:
        rows = await (await db.execute(
            "SELECT id, kind, payload_json, created_at FROM ms_queue_events"
            " WHERE channel=? AND actor_twitch_user_id=? ORDER BY id DESC LIMIT ?",
            (channel, actor_twitch_user_id, limit + 1),
        )).fetchall()
    has_more = len(rows) > limit
    items = [_dto(r) for r in rows[:limit]]
    return {"items": items, "has_more": has_more,
            "next_before": items[-1]["event_id"] if has_more and items else None}
