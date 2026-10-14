"""Календарь недели (владелец, 27.09.2026 вечером, размер M).

Расписание каналов, пачек ботов и TTS-моментов на одной сетке (7 дней) вместо
разбросанных по разделам настроек. Разведка перед стартом (см. PLAN_TODO)
показала, что единой сущности «событие недели» в БД не было — ``schedule_blocks``
это зрительский виджет «Расписание» без дня недели и привязки к каналу/боту,
а окно пачки (``join_window_min``) не хранит день/время недели. Поэтому здесь —
новая небольшая таблица, а не переиспользование существующих; события «канал»
и «пачка» ссылаются на существующие сущности (channel-строка, ``bot_packs.id``),
событие «tts» — свободный текст, т.к. отдельной сущности TTS-моментов в проекте
нет (тоже находка разведки).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.database import get_db
from app.security import auth_dependency

router = APIRouter(dependencies=[Depends(auth_dependency)])

KINDS = ("channel", "pack", "tts")
TITLE_MAX = 120
NOTE_MAX = 300


def _bad(code: str) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": code})


async def ensure_schema(db: Any = None) -> None:
    own = db is None
    if own:
        db = await get_db()
    try:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS weekly_schedule_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          day_of_week INTEGER NOT NULL CHECK(day_of_week BETWEEN 0 AND 6),
          time_hhmm TEXT NOT NULL,
          kind TEXT NOT NULL CHECK(kind IN ('channel','pack','tts')),
          title TEXT NOT NULL,
          channel TEXT NOT NULL DEFAULT '',
          pack_id INTEGER,
          note TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE INDEX IF NOT EXISTS weekly_schedule_events_day ON weekly_schedule_events(day_of_week, time_hhmm);
        """)
        await db.commit()
    finally:
        if own:
            await db.close()


def _valid_time(value: str) -> bool:
    parts = value.split(":")
    if len(parts) != 2:
        return False
    try:
        h, m = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    return 0 <= h <= 23 and 0 <= m <= 59


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "day_of_week": row["day_of_week"],
        "time": row["time_hhmm"],
        "kind": row["kind"],
        "title": row["title"],
        "channel": row["channel"] or "",
        "pack_id": row["pack_id"],
        "pack_name": row["pack_name"] if "pack_name" in row.keys() else "",
        "note": row["note"] or "",
    }


@router.get("/api/weekly-schedule")
async def list_events() -> dict[str, Any]:
    db = await get_db()
    try:
        await ensure_schema(db)
        cursor = await db.execute(
            "SELECT e.*, p.name AS pack_name FROM weekly_schedule_events e "
            "LEFT JOIN bot_packs p ON p.id = e.pack_id "
            "ORDER BY e.day_of_week, e.time_hhmm"
        )
        rows = await cursor.fetchall()
    finally:
        await db.close()
    return {"events": [_row_to_dict(row) for row in rows]}


@router.post("/api/weekly-schedule")
async def create_event(data: dict[str, Any]) -> dict[str, Any]:
    try:
        day = int(data.get("day_of_week"))
    except (TypeError, ValueError):
        raise _bad("invalid_day_of_week")
    if not 0 <= day <= 6:
        raise _bad("invalid_day_of_week")
    time_hhmm = str(data.get("time") or "").strip()
    if not _valid_time(time_hhmm):
        raise _bad("invalid_time")
    kind = str(data.get("kind") or "").strip()
    if kind not in KINDS:
        raise _bad("invalid_kind")
    title = str(data.get("title") or "").strip()[:TITLE_MAX]
    if not title:
        raise _bad("invalid_title")
    channel = str(data.get("channel") or "").strip().lstrip("#").lower()[:64]
    pack_id = data.get("pack_id")
    pack_id = int(pack_id) if pack_id not in (None, "") else None
    note = str(data.get("note") or "").strip()[:NOTE_MAX]

    db = await get_db()
    try:
        await ensure_schema(db)
        cur = await db.execute(
            "INSERT INTO weekly_schedule_events(day_of_week, time_hhmm, kind, title, channel, pack_id, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (day, time_hhmm, kind, title, channel, pack_id, note),
        )
        await db.commit()
        return {"ok": True, "id": cur.lastrowid}
    finally:
        await db.close()


@router.put("/api/weekly-schedule/{event_id}")
async def update_event(event_id: int, data: dict[str, Any]) -> dict[str, Any]:
    db = await get_db()
    try:
        await ensure_schema(db)
        row = await (await db.execute(
            "SELECT id FROM weekly_schedule_events WHERE id=?", (event_id,)
        )).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail={"code": "not_found"})

        fields: dict[str, Any] = {}
        if "day_of_week" in data:
            try:
                day = int(data["day_of_week"])
            except (TypeError, ValueError):
                raise _bad("invalid_day_of_week")
            if not 0 <= day <= 6:
                raise _bad("invalid_day_of_week")
            fields["day_of_week"] = day
        if "time" in data:
            time_hhmm = str(data["time"] or "").strip()
            if not _valid_time(time_hhmm):
                raise _bad("invalid_time")
            fields["time_hhmm"] = time_hhmm
        if "kind" in data:
            kind = str(data["kind"] or "").strip()
            if kind not in KINDS:
                raise _bad("invalid_kind")
            fields["kind"] = kind
        if "title" in data:
            title = str(data["title"] or "").strip()[:TITLE_MAX]
            if not title:
                raise _bad("invalid_title")
            fields["title"] = title
        if "channel" in data:
            fields["channel"] = str(data["channel"] or "").strip().lstrip("#").lower()[:64]
        if "pack_id" in data:
            pack_id = data["pack_id"]
            fields["pack_id"] = int(pack_id) if pack_id not in (None, "") else None
        if "note" in data:
            fields["note"] = str(data["note"] or "").strip()[:NOTE_MAX]
        if not fields:
            return {"ok": True, "id": event_id}

        assignments = ", ".join(f"{k} = ?" for k in fields)
        await db.execute(
            f"UPDATE weekly_schedule_events SET {assignments} WHERE id = ?",
            (*fields.values(), event_id),
        )
        await db.commit()
        return {"ok": True, "id": event_id}
    finally:
        await db.close()


@router.delete("/api/weekly-schedule/{event_id}")
async def delete_event(event_id: int) -> dict[str, Any]:
    db = await get_db()
    try:
        await ensure_schema(db)
        await db.execute("DELETE FROM weekly_schedule_events WHERE id=?", (event_id,))
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()