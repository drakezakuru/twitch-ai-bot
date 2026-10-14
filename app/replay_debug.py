"""v10.4.7 Wave 4.7 — Stream replay debug mode.

Сохраняем полный лог одного стрима (chat + vision frames + ответы бота +
причины генерации) → проигрываем offline для debug новых настроек
без живого стрима.

Схема таблицы:
  replay_sessions(id, name, account_id, channel, started_at, ended_at, notes)
  replay_events(id, session_id, ts, kind, payload_json)

kind enum:
  chat_in       — входящее сообщение от viewer
  bot_out       — ответ бота
  vision_frame  — vision-описание текущего кадра
  whisper_seg   — Whisper-сегмент (текст + tone)
  trigger       — smart-trigger сработал (с reason)
  setting       — изменение настроек в процессе
  mood          — обновление mood/streamer_mood
  thread        — открытие/закрытие conversation thread

API:
- start_session / end_session
- add_event (буферизуем, batch insert)
- list_sessions / get_session
- replay_session(...) — асинхронный итератор event'ов (yield в реальном времени или max-speed)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Iterable, Literal

logger = logging.getLogger(__name__)

EventKind = Literal[
    "chat_in", "bot_out", "vision_frame", "whisper_seg",
    "trigger", "setting", "mood", "thread",
]


async def ensure_tables() -> None:
    from app import database as db_mod

    await db_mod._ensure_shared()
    async with db_mod._shared_db.execute(  # type: ignore[union-attr]
        """
        CREATE TABLE IF NOT EXISTS replay_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            account_id INTEGER,
            channel TEXT,
            started_at REAL,
            ended_at REAL,
            n_events INTEGER DEFAULT 0,
            notes TEXT
        )
        """
    ):
        pass
    async with db_mod._shared_db.execute(  # type: ignore[union-attr]
        """
        CREATE TABLE IF NOT EXISTS replay_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            ts REAL,
            kind TEXT,
            payload_json TEXT
        )
        """
    ):
        pass
    async with db_mod._shared_db.execute(  # type: ignore[union-attr]
        "CREATE INDEX IF NOT EXISTS idx_replay_events_session_ts ON replay_events(session_id, ts)"
    ):
        pass


# E (REWORK_PLAN 03.09): дедуп replay — одна сессия на (канал, стрим), а не на каждого бота.
async def get_active_session_by_channel(channel: str) -> int | None:
    """Активная (незакрытая) сессия канала — для attach вторых ботов того же канала."""
    from app import database as db_mod

    await ensure_tables()
    cur = await db_mod._shared_db.execute(  # type: ignore[union-attr]
        "SELECT id FROM replay_sessions WHERE channel = ? AND ended_at IS NULL ORDER BY id DESC LIMIT 1",
        ((channel or "").lower(),),
    )
    row = await cur.fetchone()
    return int(row["id"]) if row else None
    await db_mod._shared_db.commit()  # type: ignore[union-attr]


async def start_session(name: str, account_id: int, channel: str, notes: str = "") -> int:
    from app import database as db_mod

    await ensure_tables()
    now = time.time()
    cur = await db_mod._shared_db.execute(  # type: ignore[union-attr]
        "INSERT INTO replay_sessions(name, account_id, channel, started_at, notes) VALUES(?,?,?,?,?)",
        (name, account_id, channel, now, notes),
    )
    await db_mod._shared_db.commit()  # type: ignore[union-attr]
    return cur.lastrowid or 0


async def end_session(session_id: int) -> bool:
    from app import database as db_mod

    await ensure_tables()
    await db_mod._shared_db.execute(  # type: ignore[union-attr]
        "UPDATE replay_sessions SET ended_at = ? WHERE id = ?",
        (time.time(), session_id),
    )
    await db_mod._shared_db.commit()  # type: ignore[union-attr]
    return True


async def add_event(session_id: int, kind: EventKind, payload: dict, ts: float | None = None) -> int:
    from app import database as db_mod

    await ensure_tables()
    ts = ts if ts is not None else time.time()
    try:
        payload_str = json.dumps(payload, ensure_ascii=False, default=str)
    except Exception:
        payload_str = json.dumps({"err": "non-serializable"}, ensure_ascii=False)
    cur = await db_mod._shared_db.execute(  # type: ignore[union-attr]
        "INSERT INTO replay_events(session_id, ts, kind, payload_json) VALUES(?,?,?,?)",
        (session_id, ts, kind, payload_str),
    )
    await db_mod._shared_db.execute(  # type: ignore[union-attr]
        "UPDATE replay_sessions SET n_events = n_events + 1 WHERE id = ?",
        (session_id,),
    )
    await db_mod._shared_db.commit()  # type: ignore[union-attr]
    return cur.lastrowid or 0


async def list_sessions(limit: int = 50) -> list[dict]:
    from app import database as db_mod

    await ensure_tables()
    async with db_mod._shared_db.execute(  # type: ignore[union-attr]
        "SELECT id, name, account_id, channel, started_at, ended_at, n_events, notes "
        "FROM replay_sessions ORDER BY id DESC LIMIT ?",
        (int(limit),),
    ) as cur:
        rows = await cur.fetchall()
    return [
        {
            "id": r[0], "name": r[1], "account_id": r[2], "channel": r[3],
            "started_at": r[4], "ended_at": r[5], "n_events": r[6], "notes": r[7],
        }
        for r in rows
    ]


async def get_session(session_id: int) -> dict | None:
    from app import database as db_mod

    await ensure_tables()
    async with db_mod._shared_db.execute(  # type: ignore[union-attr]
        "SELECT id, name, account_id, channel, started_at, ended_at, n_events, notes "
        "FROM replay_sessions WHERE id = ?",
        (session_id,),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    return {
        "id": row[0], "name": row[1], "account_id": row[2], "channel": row[3],
        "started_at": row[4], "ended_at": row[5], "n_events": row[6], "notes": row[7],
    }


async def delete_session(session_id: int) -> bool:
    from app import database as db_mod

    await ensure_tables()
    await db_mod._shared_db.execute("DELETE FROM replay_events WHERE session_id = ?", (session_id,))  # type: ignore[union-attr]
    await db_mod._shared_db.execute("DELETE FROM replay_sessions WHERE id = ?", (session_id,))  # type: ignore[union-attr]
    await db_mod._shared_db.commit()  # type: ignore[union-attr]
    return True


async def get_events(session_id: int, kinds: Iterable[EventKind] | None = None, limit: int = 5000) -> list[dict]:
    from app import database as db_mod

    await ensure_tables()
    sql = "SELECT id, session_id, ts, kind, payload_json FROM replay_events WHERE session_id = ?"
    args: list = [session_id]
    if kinds:
        placeholders = ",".join("?" * len(list(kinds)))
        sql += f" AND kind IN ({placeholders})"
        args.extend(list(kinds))
    sql += " ORDER BY ts ASC LIMIT ?"
    args.append(int(limit))
    async with db_mod._shared_db.execute(sql, args) as cur:  # type: ignore[union-attr]
        rows = await cur.fetchall()
    out: list[dict] = []
    for r in rows:
        try:
            payload = json.loads(r[4])
        except Exception:
            payload = {"raw": r[4]}
        out.append({"id": r[0], "session_id": r[1], "ts": r[2], "kind": r[3], "payload": payload})
    return out


async def replay_session(
    session_id: int,
    *,
    speed: float = 1.0,
    kinds: Iterable[EventKind] | None = None,
    max_events: int = 5000,
) -> AsyncIterator[dict]:
    """Async-итератор event'ов в порядке timestamp.

    speed=1.0  — реальное время.
    speed=10   — в 10 раз быстрее (для debug-прогона).
    speed=0   или meньше → без задержек (max-speed).
    """
    events = await get_events(session_id, kinds=kinds, limit=max_events)
    if not events:
        return
    base_ts = events[0]["ts"]
    base_real = time.time()
    for ev in events:
        if speed > 0:
            target_offset = (ev["ts"] - base_ts) / speed
            now_offset = time.time() - base_real
            wait = target_offset - now_offset
            if wait > 0:
                try:
                    await asyncio.sleep(min(wait, 60.0))
                except asyncio.CancelledError:
                    return
        yield ev
