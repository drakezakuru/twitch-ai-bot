"""Q27a (DEC-OWNER-017 п.4): контракт v2 — осмысленные действия для остальных виджетов.

Каждое новое действие идёт через публичные функции widgets.py, как будто его
вызвала админ-форма. Twitch/OBS в тестах не нужны: blur-роуты и валидация
мокаются, всё остальное работает на tmp-базе.
"""
from __future__ import annotations

import pytest

from app.widget_bindings import ALLOWED_ACTIONS, run_binding, validate_widget_action

NEW_PAIRS = {
    "mascot": ("preset",),
    "uptime": ("start", "stop"),
    "subathon_timer": ("extend", "start", "stop"),
    "donation_challenge": ("add_funds",),
    "song_request": ("skip", "clear"),
    "chat_highlight": ("highlight",),
    "chat_roulette": ("spin",),
    "recent_events": ("clear",),
    "blur_guard_v2": ("blur_on", "blur_off"),
}


def test_contract_v2_accepts_new_pairs_and_rejects_wrong_ones():
    for widget, actions in NEW_PAIRS.items():
        for action in actions:
            assert validate_widget_action(widget, action) is None, (widget, action)
    assert validate_widget_action("mascot", "spin") == "incompatible_widget_action"
    assert validate_widget_action("uptime", "extend") == "incompatible_widget_action"
    assert validate_widget_action("blur-guard-v2", "blur_on") == "unknown_widget"
    # legacy counter продолжает читаться движком (owning-тест на v1-строки)
    assert ALLOWED_ACTIONS["counter"] == ("increment", "set", "reset")


def _binding(widget: str, action: str, value: str = "") -> dict:
    return {
        "widget": widget, "action": action, "value": value,
        "source": "hotkey", "match": "f5", "role": "streamer",
        "account_id": 0, "channel": "",
    }


@pytest.mark.asyncio
async def test_run_binding_uptime_and_mascot(tmp_db, disable_auth):
    from app import database
    await database.init_db()
    started = await run_binding(_binding("uptime", "start"))
    assert started.get("ok") is True, started
    from app.widgets import stream_session_public
    assert (await stream_session_public())["is_live"] is True
    await run_binding(_binding("uptime", "stop"))
    assert (await stream_session_public())["is_live"] is False

    preset_res = await run_binding(_binding("mascot", "preset", "cat"))
    assert preset_res.get("ok") is True, preset_res


@pytest.mark.asyncio
async def test_run_binding_subathon_and_donation_challenge(tmp_db, disable_auth):
    from app import database
    from app.widgets import donation_challenges_create, subathon_get
    await database.init_db()
    assert (await run_binding(_binding("subathon_timer", "start"))).get("ok") is True
    extended = await run_binding(_binding("subathon_timer", "extend", "120"))
    assert extended == {"ok": True, "extended": 120}, extended
    row = await subathon_get()
    assert row.get("running") in (True, 1)

    created = await donation_challenges_create({"title": "Q27a", "target_amount": 1000})
    assert created.get("ok") is True
    funds = await run_binding(_binding("donation_challenge", "add_funds", "250"))
    assert funds.get("ok") is True, funds
    assert funds.get("current_amount") == 250.0
    # без активного челленджа — честная ошибка, не падение
    from app.widgets import donation_challenges_delete
    await donation_challenges_delete(created["id"])
    assert (await run_binding(_binding("donation_challenge", "add_funds", "1"))) == {
        "error": "no_active_challenge",
    }


@pytest.mark.asyncio
async def test_run_binding_song_request_and_recent_events(tmp_db, disable_auth):
    from app import database
    from app.widgets import recent_events_public
    await database.init_db()
    assert (await run_binding(_binding("song_request", "skip"))).get("ok") is True
    assert (await run_binding(_binding("song_request", "clear"))).get("ok") is True
    assert (await run_binding(_binding("recent_events", "clear"))).get("ok") is True
    from app.widgets import recent_events_add
    await recent_events_add({"kind": "manual", "username": "zr", "amount": 5})
    assert await recent_events_public()  # лента — список, не пустой
    await run_binding(_binding("recent_events", "clear"))
    # recent_events_clear сбрасывает TTL-кэш ленты (Q27a) — OBS видит очистку сразу
    assert (await recent_events_public()) == []


@pytest.mark.asyncio
async def test_run_binding_chat_highlight_and_roulette(tmp_db, disable_auth):
    from app import database
    from app.widgets import chat_highlight_get
    await database.init_db()
    res = await run_binding(_binding("chat_highlight", "highlight", "ГОСПОДИ, КЛИП!"))
    assert res.get("ok") is True, res
    row = await chat_highlight_get()
    assert row.get("text") == "ГОСПОДИ, КЛИП!"
    assert row.get("visible") in (True, 1)

    spin = await run_binding(_binding("chat_roulette", "spin"))
    assert isinstance(spin, dict)


@pytest.mark.asyncio
async def test_run_binding_blur_guard_dispatch(tmp_db, disable_auth, monkeypatch):
    from app import database
    await database.init_db()
    import app.blur_guard_routes as BGR

    calls: list[str] = []

    async def _on():
        return {"ok": True, "blur": True}

    async def _off():
        return {"ok": True, "blur": False}

    monkeypatch.setattr(BGR, "blur_guard_manual_on", _on)
    monkeypatch.setattr(BGR, "blur_guard_manual_off", _off)
    assert (await run_binding(_binding("blur_guard_v2", "blur_on"))) == {"ok": True, "blur": True}
    assert (await run_binding(_binding("blur_guard_v2", "blur_off"))) == {"ok": True, "blur": False}
    assert calls == []

    from fastapi import HTTPException

    async def _broken():
        raise HTTPException(status_code=502, detail="obs offline")

    monkeypatch.setattr(BGR, "blur_guard_manual_on", _broken)
    assert (await run_binding(_binding("blur_guard_v2", "blur_on"))) == {
        "error": "blur_unavailable", "detail": "obs offline",
    }
