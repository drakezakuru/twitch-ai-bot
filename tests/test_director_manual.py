"""Q40b: ручной режим Режиссёра — режим per канал, ручная отправка, fence, отказ start."""
from __future__ import annotations

import asyncio
import time

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app import director, director_manual, director_routes
from app.database import get_db, init_db

pytestmark = pytest.mark.asyncio


async def _seed() -> None:
    db = await get_db()
    try:
        await db.executemany(
            "INSERT INTO accounts (id, nickname, token, enabled, bot_role) VALUES (?, ?, 'x', ?, ?)",
            [(1, "lynx", 1, "lurker"), (2, "boss", 1, "director"), (3, "stranger", 1, "lurker"), (4, "sleepy", 0, "lurker")],
        )
        await db.executemany(
            "INSERT INTO channels (account_id, channel_name, enabled) VALUES (?, ?, 1)",
            [(1, "runtime"), (2, "runtime"), (3, "other"), (4, "runtime")],
        )
        await db.commit()
    finally:
        await db.close()


@pytest_asyncio.fixture
async def seeded(tmp_db, monkeypatch):
    await init_db()
    await _seed()
    sent: list[tuple[int, str, str]] = []

    async def moderate(account_id, channel, text):
        return True, text

    async def deliver(account_id, channel, text):
        sent.append((account_id, channel, text))
        return {"ok": True}

    monkeypatch.setattr(director_manual, "moderate", moderate)
    monkeypatch.setattr(director_manual, "deliver", deliver)
    monkeypatch.setattr(director_manual, "DUPLICATE_GUARD_SEC", 0)
    monkeypatch.setattr(director_manual, "SEND_RATE_LIMIT_SEC", 0)
    # Q36: per-channel asyncio.Lock живёт в event loop теста — с новым loop старый лок не годится.
    director_manual._channel_locks.clear()
    director_manual._channel_last_dispatch.clear()
    director_manual._channel_pending.clear()
    return sent


async def test_mode_defaults_to_ai_and_switches_only_without_live_session(seeded):
    assert (await director_manual.get_mode("#Runtime"))["mode"] == "ai"
    assert (await director_manual.set_mode("runtime", "manual"))["mode"] == "manual"
    assert (await director_manual.list_modes())["modes"] == {"runtime": {"mode": "manual", "fenced": False}}
    assert (await director.get_status("runtime"))["control_mode"] == "manual"
    with pytest.raises(ValueError, match="invalid_control_mode"):
        await director_manual.set_mode("runtime", "auto")
    db = await get_db()
    try:
        await db.execute("INSERT INTO director_sessions(id, channel, state, config_version) VALUES ('s1', 'runtime', 'paused', 1)")
        await db.commit()
    finally:
        await db.close()
    with pytest.raises(ValueError, match="settings_locked"):
        await director_manual.set_mode("runtime", "ai")


async def test_send_goes_only_from_the_chosen_channel_lurker_and_is_logged(seeded):
    with pytest.raises(ValueError, match="director_manual_required"):
        await director_manual.send("runtime", 1, "клатч года")
    await director_manual.set_mode("runtime", "manual")
    result = await director_manual.send("runtime", 1, "  клатч года  ")
    assert result["ok"] is True and result["message"]["state"] == "sent"
    assert seeded == [(1, "runtime", "клатч года")]
    for account_id in (2, 3, 4, 99):  # director, чужой канал, выключенный, несуществующий
        with pytest.raises(ValueError, match="manual_sender_not_channel_lurker"):
            await director_manual.send("runtime", account_id, "привет")
    with pytest.raises(ValueError, match="manual_sender_required"):
        await director_manual.send("runtime", None, "привет")
    for text, code in (("go www.example.com", "manual_url_forbidden"), ("@lynx hi", "manual_mention_forbidden"),
                       ("!drop", "manual_command_forbidden"), ("   ", "manual_text_empty")):
        with pytest.raises(ValueError, match=code):
            await director_manual.send("runtime", 1, text)
    assert len(seeded) == 1
    history = (await director_manual.list_messages("runtime"))["messages"]
    assert [(m["nickname"], m["text"], m["state"]) for m in history] == [("lynx", "клатч года", "sent")]


async def test_duplicate_guard_and_moderation_block(seeded, monkeypatch):
    await director_manual.set_mode("runtime", "manual")
    monkeypatch.setattr(director_manual, "DUPLICATE_GUARD_SEC", 60)
    await director_manual.send("runtime", 1, "раз")
    with pytest.raises(ValueError, match="manual_send_too_fast"):
        await director_manual.send("runtime", 1, "два")
    monkeypatch.setattr(director_manual, "DUPLICATE_GUARD_SEC", 0)

    async def block(account_id, channel, text):
        return False, text
    monkeypatch.setattr(director_manual, "moderate", block)
    result = await director_manual.send("runtime", 1, "плохое")
    assert result["ok"] is False and result["message"]["reason"] == "moderation_blocked"
    assert seeded == [(1, "runtime", "раз")]


async def test_emergency_stop_fences_manual_mode_until_unfenced(seeded, monkeypatch):
    await director_manual.set_mode("runtime", "manual")
    await director.emergency_stop_all()
    with pytest.raises(ValueError, match="director_manual_fenced"):
        await director_manual.send("runtime", 1, "стоп")
    await director_manual.unfence("runtime")
    assert (await director_manual.send("runtime", 1, "снова"))["ok"] is True

    async def fence_mid_moderation(account_id, channel, text):
        await director.emergency_stop_all()
        return True, text
    monkeypatch.setattr(director_manual, "moderate", fence_mid_moderation)
    result = await director_manual.send("runtime", 1, "гонка")
    assert result["ok"] is False and result["message"]["reason"] == "director_manual_fenced"
    assert seeded == [(1, "runtime", "снова")]


async def test_ai_start_is_rejected_in_manual_mode(seeded):
    await director.save_config("runtime", {}, [1], 2)
    await director_manual.set_mode("runtime", "manual")
    with pytest.raises(ValueError, match="director_manual_mode"):
        await director.start("runtime")


async def test_routes_expose_modes_send_history_and_error_codes(seeded, disable_auth):
    app = FastAPI()
    app.include_router(director_routes.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        denied = await client.post("/api/director/runtime/operator/send", json={"account_id": 1, "text": "hi"})
        assert denied.status_code == 400 and denied.json()["detail"]["code"] == "director_manual_required"
        assert (await client.put("/api/director/runtime/control-mode", json={"mode": "manual"})).json()["mode"] == "manual"
        assert (await client.get("/api/director/control-modes")).json()["modes"]["runtime"]["mode"] == "manual"
        sent = await client.post("/api/director/runtime/operator/send", json={"account_id": 1, "text": "hi"})
        assert sent.status_code == 200 and sent.json()["ok"] is True
        history = (await client.get("/api/director/runtime/operator/messages")).json()["messages"]
        assert history[0]["text"] == "hi"
        assert (await client.post("/api/director/runtime/operator/unfence")).json()["fenced"] is False


# ── Q35: заготовки с хоткеями Alt+1..Alt+9 ──

async def test_preset_crud_is_scoped_per_channel_and_ordered(seeded):
    assert (await director_manual.list_presets("runtime"))["presets"] == []
    created = await director_manual.create_preset("runtime", "  клатч! ")
    assert [p["text"] for p in created["presets"]] == ["клатч!"]
    preset_id = created["presets"][0]["id"]
    await director_manual.create_preset("runtime", "гг")
    assert [p["text"] for p in (await director_manual.list_presets("runtime"))["presets"]] == ["клатч!", "гг"]
    # Другой канал не видит чужие заготовки.
    assert (await director_manual.list_presets("other"))["presets"] == []

    updated = await director_manual.update_preset("runtime", preset_id, " клатч года ")
    assert updated["presets"][0]["text"] == "клатч года"
    with pytest.raises(ValueError, match="manual_preset_not_found"):
        await director_manual.update_preset("runtime", 99999, "x")
    with pytest.raises(ValueError, match="manual_preset_not_found"):
        await director_manual.update_preset("other", preset_id, "чужой")

    for text, code in (("go www.example.com", "manual_url_forbidden"), ("   ", "manual_text_empty")):
        with pytest.raises(ValueError, match=code):
            await director_manual.create_preset("runtime", text)

    after_delete = await director_manual.delete_preset("runtime", preset_id)
    assert [p["text"] for p in after_delete["presets"]] == ["гг"]
    with pytest.raises(ValueError, match="manual_preset_not_found"):
        await director_manual.delete_preset("runtime", preset_id)


async def test_preset_limit_and_reorder(seeded):
    ids = []
    for i in range(director_manual.PRESET_LIMIT):
        result = await director_manual.create_preset("runtime", f"заготовка {i}")
        ids = [p["id"] for p in result["presets"]]
    with pytest.raises(ValueError, match="manual_preset_limit_reached"):
        await director_manual.create_preset("runtime", "переполнение")

    reordered = await director_manual.reorder_presets("runtime", list(reversed(ids)))
    assert [p["id"] for p in reordered["presets"]] == list(reversed(ids))

    with pytest.raises(ValueError, match="manual_preset_order_invalid"):
        await director_manual.reorder_presets("runtime", ids[:-1])
    with pytest.raises(ValueError, match="manual_preset_order_invalid"):
        await director_manual.reorder_presets("runtime", ids + [123456])


async def test_preset_routes_crud_and_reorder(seeded, disable_auth):
    app = FastAPI()
    app.include_router(director_routes.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/api/director/runtime/manual/presets", json={"text": "гл"})
        assert created.status_code == 200
        preset_id = created.json()["presets"][0]["id"]
        listed = await client.get("/api/director/runtime/manual/presets")
        assert listed.json()["presets"][0]["text"] == "гл"
        updated = await client.put(f"/api/director/runtime/manual/presets/{preset_id}", json={"text": "гл!"})
        assert updated.json()["presets"][0]["text"] == "гл!"
        reordered = await client.post("/api/director/runtime/manual/presets/reorder", json={"order": [preset_id]})
        assert reordered.status_code == 200
        deleted = await client.delete(f"/api/director/runtime/manual/presets/{preset_id}")
        assert deleted.json()["presets"] == []
        missing = await client.delete(f"/api/director/runtime/manual/presets/{preset_id}")
        assert missing.status_code == 400 and missing.json()["detail"]["code"] == "manual_preset_not_found"


# ── Q36: очередь ручных отправок и фиксированный лимит темпа ──

async def test_concurrent_sends_to_the_same_channel_are_spaced_by_the_fixed_interval(seeded, monkeypatch):
    monkeypatch.setattr(director_manual, "SEND_RATE_LIMIT_SEC", 0.12)
    await director_manual.set_mode("runtime", "manual")
    started = time.monotonic()
    results = await asyncio.gather(
        director_manual.send("runtime", 1, "раз"),
        director_manual.send("runtime", 1, "два"),
        director_manual.send("runtime", 1, "три"),
    )
    elapsed = time.monotonic() - started
    assert all(r["ok"] for r in results)
    # Три отправки с фиксированным шагом 0.12s — минимум два интервала ожидания, без рандома сверху.
    assert elapsed >= 0.24
    assert elapsed < 0.24 + 0.5, "лимит темпа не должен разрастаться в неожиданно долгую задержку"
    # Порядок реальных отправок сохраняет FIFO постановки в очередь.
    assert [item[2] for item in seeded] == ["раз", "два", "три"]


async def test_different_channels_are_not_serialized_against_each_other(seeded, monkeypatch):
    monkeypatch.setattr(director_manual, "SEND_RATE_LIMIT_SEC", 0.2)
    await director_manual.set_mode("runtime", "manual")
    await director_manual.set_mode("other", "manual")
    started = time.monotonic()
    results = await asyncio.gather(
        director_manual.send("runtime", 1, "локальный"),
        director_manual.send("other", 3, "чужой"),
    )
    elapsed = time.monotonic() - started
    assert all(r["ok"] for r in results)
    # Разные каналы не делят одну очередь — обе отправки укладываются в один интервал, не в два.
    assert elapsed < 0.2 + 0.15


async def test_queue_depth_reports_pending_sends_and_route_exposes_it(seeded, monkeypatch, disable_auth):
    monkeypatch.setattr(director_manual, "SEND_RATE_LIMIT_SEC", 0.15)
    await director_manual.set_mode("runtime", "manual")
    assert director_manual.queue_depth("runtime") == 0
    # Первая отправка тоже должна ждать своего слота — иначе она завершится раньше, чем мы проверим глубину.
    director_manual._channel_last_dispatch["runtime"] = time.time()
    task_a = asyncio.ensure_future(director_manual.send("runtime", 1, "первое"))
    await asyncio.sleep(0.02)
    task_b = asyncio.ensure_future(director_manual.send("runtime", 1, "второе"))
    await asyncio.sleep(0.02)
    assert director_manual.queue_depth("runtime") == 2
    app = FastAPI()
    app.include_router(director_routes.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        queue = await client.get("/api/director/runtime/operator/queue")
        assert queue.json() == {"ok": True, "channel": "runtime", "pending": 2}
    await asyncio.gather(task_a, task_b)
    assert director_manual.queue_depth("runtime") == 0
