"""PLAN_FEEDBACK_2908 §3.1: hotkey-биндинги.

Нажатие клавиши в открытой панели → POST /api/widgets/bindings/hotkey
{combo} → матчинг enabled-биндингов source='hotkey' → тот же run_binding,
что и у чат-команд.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


async def _add_hotkey_binding(match: str, widget: str = "counter",
                              widget_key: str = "death", action: str = "increment",
                              value: str = "1", enabled: int = 1) -> int:
    from app.database import get_db

    db = await get_db()
    try:
        cur = await db.execute(
            "INSERT INTO widget_bindings (account_id, channel, enabled, source, match, widget, "
            "widget_key, action, value, role) VALUES (1, 'chan', ?, 'hotkey', ?, ?, ?, ?, ?, 'streamer')",
            (enabled, match, widget, widget_key, action, value),
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


def _norm(mods: list[str], key: str) -> str:
    parts = []
    for m in ("ctrl", "alt", "shift", "meta"):
        if m in mods:
            parts.append(m)
    parts.append(key)
    return "+".join(parts)


async def test_handle_hotkey_matches_and_executes(tmp_db):
    from app.database import get_db, init_db
    from app.widget_bindings import handle_hotkey

    await init_db()
    db = await get_db()
    try:
        await db.execute("INSERT INTO accounts (id, nickname, token) VALUES (1, 'hotkey_bot', 'fake')")
        await db.execute("INSERT INTO channels (account_id, channel_name) VALUES (1, 'chan')")
        await db.commit()
    finally:
        await db.close()
    await _add_hotkey_binding("ctrl+shift+d", value="1")
    await _add_hotkey_binding("f5", widget="countdown", action="start", value="")
    disabled_id = await _add_hotkey_binding("space", value="5", enabled=0)

    res = await handle_hotkey("CTRL+Shift+D", 1, "#CHAN")  # регистр не важен
    assert res["executed"], "hotkey-биндинг должен выполниться"
    assert res["executed"][0]["id"] is not None

    res = await handle_hotkey("f5", 1, "chan")
    assert len(res["executed"]) == 1

    res = await handle_hotkey("space", 1, "chan")  # выключенный биндинг не выполняется
    assert res["executed"] == []

    res = await handle_hotkey("ctrl+alt+x", 1, "chan")
    assert res["executed"] == []


async def test_hotkey_increments_counter(tmp_db):
    from app.database import init_db, get_db
    from app.widget_bindings import handle_hotkey

    await init_db()
    db = await get_db()
    try:
        await db.execute("INSERT INTO accounts (id, nickname, token) VALUES (1, 'hotkey_bot', 'fake')")
        await db.execute("INSERT INTO channels (account_id, channel_name) VALUES (1, 'chan')")
        await db.commit()
    finally:
        await db.close()
    await _add_hotkey_binding("ctrl+d", widget="counter", widget_key="death",
                              action="increment", value="1")
    await handle_hotkey("ctrl+d", 1, "chan")
    await handle_hotkey("ctrl+d", 1, "chan")

    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT value FROM widget_counters_scoped "
            "WHERE account_id = 1 AND channel = 'chan' AND key = 'death'"
        )
        row = await cur.fetchone()
        assert row is not None and int(row["value"]) == 2
    finally:
        await db.close()


async def test_bindings_api_accepts_hotkey_source(tmp_db, disable_auth):
    from app.database import get_db, init_db
    from app.widgets import admin_router, public_router
    from app.routes import router as api_router
    from fastapi import FastAPI

    await init_db()
    db = await get_db()
    try:
        await db.execute("INSERT INTO accounts (id, nickname, token) VALUES (1, 'api_hotkey_bot', 'fake')")
        await db.execute("INSERT INTO channels (account_id, channel_name) VALUES (1, 'chan')")
        await db.commit()
    finally:
        await db.close()
    app = FastAPI()
    app.include_router(api_router)
    app.include_router(admin_router)
    app.include_router(public_router)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # CRUD принимает source=hotkey
        resp = await client.post("/api/widgets/bindings", json={
            "account_id": 1, "channel": "chan",
            "source": "hotkey", "match": "ctrl+shift+d", "widget": "counter",
            "widget_key": "death", "action": "increment", "value": "1", "role": "streamer",
        })
        assert resp.status_code == 200, resp.text

        # нажатие хоткея через роут
        resp = await client.post("/api/widgets/bindings/hotkey",
                                 json={"combo": "ctrl+shift+d", "account_id": 1,
                                       "channel": "chan"})
        assert resp.status_code == 200
        assert len(resp.json()["executed"]) == 1
