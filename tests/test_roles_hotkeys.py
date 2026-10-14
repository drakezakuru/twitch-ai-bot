"""PLAN_SESSION_ROLES §R5: хоткеи модератора (timeout_last/warn_last/slow/clear)."""

from __future__ import annotations

import json

import pytest
import pytest_asyncio

from app import database
from app.mod_feed_routes import (
    _BUFFER,
    _DEDUP,
    _LAST_VIOLATOR,
    _moderator_action,
    publish_event,
)


@pytest_asyncio.fixture()
async def helix_calls(tmp_db, disable_auth, monkeypatch):
    await database.init_db()
    db = await database.get_db()
    try:
        await db.execute(
            "INSERT INTO accounts (id, nickname, token, bot_role, role_config_json) "
            "VALUES (1, 'modbot', 't', 'moderator', ?)",
            (json.dumps({"moderator": {"ladder_t1_min": 3}}),),
        )
        await db.execute(
            "INSERT INTO channels (account_id, channel_name, enabled) VALUES (1, 'alekzz', 1)")
        await db.commit()
    finally:
        await db.close()
    _BUFFER.clear()
    _DEDUP.clear()
    _LAST_VIOLATOR.clear()
    calls: list[dict] = []

    await database.close_db()  # app.server импортируем на чистом синглтоне
    from app.server import chat_analyzer
    chat_analyzer._account_token.clear()
    chat_analyzer._account_token[1] = "oauth:fake"

    async def fake_timeout(token, channel, mod, username, duration_sec=600, reason=""):
        calls.append({"fn": "timeout", "user": username, "sec": duration_sec, "ch": channel})
        return True, ""

    async def fake_settings(token, channel, mod, **kw):
        calls.append({"fn": "settings", "ch": channel, **kw})
        return True, ""

    async def fake_clear(token, channel, mod):
        calls.append({"fn": "clear", "ch": channel})
        return True, ""

    monkeypatch.setattr("app.twitch_helix.timeout_user", fake_timeout)
    monkeypatch.setattr("app.twitch_helix.update_chat_settings", fake_settings)
    monkeypatch.setattr("app.twitch_helix.clear_chat_messages", fake_clear)
    monkeypatch.setattr("app.twitch_helix.is_helix_configured", lambda: True)
    return calls


@pytest.mark.asyncio
async def test_timeout_last_uses_last_violator_and_ladder(helix_calls):
    publish_event(1, "alekzz", "violation", user="badguy", text="мат", severity=4)
    res = await _moderator_action(1, "alekzz", "timeout_last")
    assert res.get("ok") is True
    assert helix_calls == [{"fn": "timeout", "user": "badguy", "sec": 180, "ch": "alekzz"}]
    assert any(e["kind"] == "action" and "хоткею" in e["text"] for e in _BUFFER)


@pytest.mark.asyncio
async def test_warn_last(helix_calls):
    publish_event(1, "alekzz", "violation", user="u1", text="мат", severity=2)
    res = await _moderator_action(1, "alekzz", "warn_last")
    assert res == {"ok": True, "warned": "u1"}
    assert helix_calls == []  # warn не дергает Helix


@pytest.mark.asyncio
async def test_slow_on_off_and_clear(helix_calls):
    res = await _moderator_action(1, "alekzz", "slow_on", "3")
    assert res.get("ok") is True
    assert helix_calls[0]["fn"] == "settings" and helix_calls[0]["slow_mode"] is True
    assert helix_calls[0]["slow_mode_wait_time"] == 3
    await _moderator_action(1, "alekzz", "slow_off")
    assert helix_calls[1]["slow_mode"] is False
    await _moderator_action(1, "alekzz", "clear")
    assert helix_calls[2] == {"fn": "clear", "ch": "alekzz"}


@pytest.mark.asyncio
async def test_no_violator_error(tmp_db, disable_auth):
    await database.init_db()
    res = await _moderator_action(1, "alekzz", "timeout_last")
    assert res in ({"error": "no_last_violator"}, {"error": "no_moderator_bot"})


@pytest.mark.asyncio
async def test_moderator_action_never_falls_back_to_another_scope(helix_calls):
    publish_event(1, "alekzz", "violation", user="scoped-user", text="x", severity=2)
    assert await _moderator_action(999, "alekzz", "timeout_last") == {
        "error": "no_moderator_bot"
    }
    assert await _moderator_action(1, "other", "timeout_last") == {
        "error": "no_channel"
    }
    assert helix_calls == []


@pytest.mark.asyncio
async def test_run_binding_dispatch_moderation(helix_calls):
    """run_binding widget='moderation' → _moderator_action."""
    from app.widget_bindings import run_binding
    publish_event(1, "alekzz", "violation", user="u2", text="мат", severity=3)
    res = await run_binding({
        "account_id": 1, "channel": "alekzz",
        "widget": "moderation", "action": "timeout_last",
        "widget_key": "", "value": "", "role": "broadcaster",
    }, {})
    assert res.get("ok") is True
    assert helix_calls == [{"fn": "timeout", "user": "u2", "sec": 180, "ch": "alekzz"}]
