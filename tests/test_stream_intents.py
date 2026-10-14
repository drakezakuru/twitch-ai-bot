"""PLAN_SESSION_ROLES §R3: роль-сторона стрим-инструментов.

Моки Helix: twitch_helix.update_chat_settings и stream_intents._update_channel_info
подменяются — реальных запросов нет. Проверяем auto/suggest/off, одобрение
интента, scope-ошибку (403) и историю в bot_logs.
"""
from __future__ import annotations

import json

import pytest
import pytest_asyncio

from app import database
from app.mod_feed_routes import _BUFFER, _DEDUP, _INTENTS, _INTENT_EXECUTORS
from app import stream_intents
from app.stream_intents import propose_stream_action, suggest_from_vision


@pytest_asyncio.fixture(autouse=True)
async def _schema(tmp_db, disable_auth):
    await database.init_db()
    db = await database.get_db()
    try:
        await db.execute(
            "INSERT INTO accounts (nickname, token, bot_role, role_config_json) "
            "VALUES ('modbot', 'tok', 'moderator', ?)",
            (json.dumps({"moderator": {"stream_tool_modes": {
                "category": "suggest", "slow": "auto",
                "ai_category": "suggest", "title": "off",
            }}}),),
        )
        await db.execute(
            "INSERT INTO channels (account_id, channel_name) VALUES (1, 'alekzz')")
        await db.commit()
    finally:
        await db.close()
    _BUFFER.clear(); _DEDUP.clear(); _INTENTS.clear(); _INTENT_EXECUTORS.clear()


@pytest.fixture
def mock_helix(monkeypatch):
    calls: list[dict] = []

    async def _chat_settings(token, channel, mod_login, **kwargs):
        calls.append({"channel": channel, "kwargs": kwargs})
        return True, ""

    async def _channel_info(token, channel, *, title=None, game_name=None):
        calls.append({"channel": channel, "title": title, "game_name": game_name})
        return {"ok": True, "error": ""}

    monkeypatch.setattr("app.twitch_helix.update_chat_settings", _chat_settings)
    monkeypatch.setattr(stream_intents, "_update_channel_info", _channel_info)
    return calls


async def _history_rows(account_id: int = 1) -> list[dict]:
    db = await database.get_db()
    try:
        cur = await db.execute(
            "SELECT message, details, level FROM bot_logs WHERE account_id = ? "
            "AND details LIKE '%stream_tool%' ORDER BY id", (account_id,))
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_off_mode_returns_disabled(mock_helix):
    res = await propose_stream_action(1, "title", {"title": "новый титул"})
    assert res["ok"] is False and res["error"] == "disabled"
    assert mock_helix == [], "выключенный инструмент не должен дергать Helix"


@pytest.mark.asyncio
async def test_auto_mode_executes_and_logs(mock_helix):
    res = await propose_stream_action(1, "slow", {"enabled": True, "wait": 10})
    assert res["ok"] and res["mode"] == "auto" and res["executed"]["ok"]
    assert mock_helix and mock_helix[0]["kwargs"]["slow_mode_wait_time"] == 10
    # фид: событие-действие
    assert any(e["kind"] == "action" for e in _BUFFER)
    # история: decision=auto
    rows = await _history_rows()
    assert rows and json.loads(rows[-1]["details"])["decision"] == "auto"


@pytest.mark.asyncio
async def test_suggest_waits_approval(mock_helix):
    res = await propose_stream_action(1, "category", {"game_name": "Just Chatting"})
    assert res["ok"] and res["mode"] == "suggest" and res["event"]["kind"] == "intent"
    assert mock_helix == [], "suggest не исполняет до одобрения"
    pending = [e for e in _BUFFER if e["kind"] == "intent" and e["status"] == "pending"]
    assert pending
    # одобряем через API mod-feed
    from app.mod_feed_routes import mod_feed_intent
    out = await mod_feed_intent(str(pending[0]["id"]), "approve")
    assert out["ok"] and out["event"]["intent"]["executed"]["ok"]
    assert mock_helix and mock_helix[0]["game_name"] == "Just Chatting"
    # история: pending → approved
    decisions = [json.loads(r["details"])["decision"] for r in await _history_rows()]
    assert "pending" in decisions and "approved" in decisions


@pytest.mark.asyncio
async def test_scope_error_honest_toast(monkeypatch):
    async def _fail(token, channel, mod_login, **kwargs):
        return False, "helix_403: insufficient scope"
    monkeypatch.setattr("app.twitch_helix.update_chat_settings", _fail)
    res = await propose_stream_action(1, "slow", {"enabled": True})
    assert res["ok"] and res["executed"]["scope_error"] is True
    ev = [e for e in _BUFFER if e["kind"] == "action"][-1]
    assert "moderator:manage:chat_settings" in ev["text"] and "dev.twitch.tv" in ev["text"], \
        "scope-ошибка должна честно называть право и консоль"
    rows = await _history_rows()
    assert rows[-1]["level"] == "warning"


@pytest.mark.asyncio
async def test_not_moderator_rejected(mock_helix):
    db = await database.get_db()
    await db.execute("UPDATE accounts SET bot_role = 'chatter' WHERE id = 1")
    await db.commit()
    await db.close()
    res = await propose_stream_action(1, "slow", {})
    assert res["ok"] is False and res["error"] == "not_moderator"


@pytest.mark.asyncio
async def test_vision_suggestion_routes_to_ai_category(mock_helix):
    res = await suggest_from_vision(1, "ELDEN RING")
    assert res["ok"] and res["mode"] == "suggest"
    from app.mod_feed_routes import mod_feed_intent
    pending = [e for e in _BUFFER if e["kind"] == "intent" and e["status"] == "pending"]
    out = await mod_feed_intent(str(pending[-1]["id"]), "approve")
    assert out["ok"]
    assert mock_helix and mock_helix[-1]["game_name"] == "ELDEN RING"
    rows = await _history_rows()
    assert json.loads(rows[-1]["details"])["source"] == "vision"
