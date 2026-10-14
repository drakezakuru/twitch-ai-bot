"""Календарь недели (владелец, 27.09.2026 вечером): CRUD для одной сетки
событий (каналы / пачки ботов / TTS-моменты), см. app/weekly_schedule.py.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.database import get_db, init_db

pytestmark = pytest.mark.asyncio


async def _client():
    from app.server import app
    await init_db()
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


async def _make_pack(name: str = "wave1") -> int:
    db = await get_db()
    try:
        cur = await db.execute("INSERT INTO bot_packs(name) VALUES (?)", (name,))
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


async def test_create_list_update_delete_roundtrip():
    async with await _client() as client:
        resp = await client.post("/api/weekly-schedule", json={
            "day_of_week": 0, "time": "19:00", "kind": "channel",
            "title": "Эфир на test_channel", "channel": "#Test_Channel",
        })
        assert resp.status_code == 200, resp.text
        event_id = resp.json()["id"]

        resp = await client.get("/api/weekly-schedule")
        events = resp.json()["events"]
        assert len(events) == 1
        ev = events[0]
        assert ev["day_of_week"] == 0 and ev["time"] == "19:00"
        assert ev["kind"] == "channel" and ev["channel"] == "test_channel", "канал нормализован без # и в lowercase"

        resp = await client.put(f"/api/weekly-schedule/{event_id}", json={"time": "20:30", "note": "перенесли"})
        assert resp.status_code == 200, resp.text
        events = (await client.get("/api/weekly-schedule")).json()["events"]
        assert events[0]["time"] == "20:30" and events[0]["note"] == "перенесли"

        resp = await client.delete(f"/api/weekly-schedule/{event_id}")
        assert resp.status_code == 200
        events = (await client.get("/api/weekly-schedule")).json()["events"]
        assert events == []


async def test_pack_event_carries_pack_name_via_join():
    await init_db()
    pack_id = await _make_pack("wave1")
    async with await _client() as client:
        resp = await client.post("/api/weekly-schedule", json={
            "day_of_week": 5, "time": "18:00", "kind": "pack",
            "title": "Начать пачку wave1", "pack_id": pack_id,
        })
        assert resp.status_code == 200, resp.text
        events = (await client.get("/api/weekly-schedule")).json()["events"]
        assert events[0]["pack_id"] == pack_id
        assert events[0]["pack_name"] == "wave1"


async def test_tts_event_is_freeform_no_entity_required():
    async with await _client() as client:
        resp = await client.post("/api/weekly-schedule", json={
            "day_of_week": 2, "time": "21:15", "kind": "tts",
            "title": "Момент тишины для TTS-заказов", "note": "объявить в чате заранее",
        })
        assert resp.status_code == 200, resp.text
        events = (await client.get("/api/weekly-schedule")).json()["events"]
        assert events[0]["kind"] == "tts" and events[0]["channel"] == "" and events[0]["pack_id"] is None


@pytest.mark.parametrize("payload,field", [
    ({"day_of_week": 7, "time": "10:00", "kind": "channel", "title": "x"}, "invalid_day_of_week"),
    ({"day_of_week": 0, "time": "25:00", "kind": "channel", "title": "x"}, "invalid_time"),
    ({"day_of_week": 0, "time": "10:00", "kind": "bogus", "title": "x"}, "invalid_kind"),
    ({"day_of_week": 0, "time": "10:00", "kind": "channel", "title": ""}, "invalid_title"),
])
async def test_create_rejects_invalid_input(payload, field):
    async with await _client() as client:
        resp = await client.post("/api/weekly-schedule", json=payload)
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == field


async def test_update_missing_event_404():
    async with await _client() as client:
        resp = await client.put("/api/weekly-schedule/999", json={"note": "x"})
        assert resp.status_code == 404


async def test_events_ordered_by_day_then_time():
    async with await _client() as client:
        await client.post("/api/weekly-schedule", json={
            "day_of_week": 3, "time": "22:00", "kind": "tts", "title": "поздний"})
        await client.post("/api/weekly-schedule", json={
            "day_of_week": 1, "time": "09:00", "kind": "tts", "title": "ранний, но раньше по дню"})
        await client.post("/api/weekly-schedule", json={
            "day_of_week": 3, "time": "08:00", "kind": "tts", "title": "тот же день, раньше по времени"})
        events = (await client.get("/api/weekly-schedule")).json()["events"]
        titles = [e["title"] for e in events]
        assert titles == [
            "ранний, но раньше по дню",
            "тот же день, раньше по времени",
            "поздний",
        ]