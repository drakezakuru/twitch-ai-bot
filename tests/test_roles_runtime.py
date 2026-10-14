"""PLAN_SESSION_ROLES §R1: рантайм-гейты по роли (lurker/moderator/voice/chatter)."""

from __future__ import annotations

import json

import pytest
import pytest_asyncio

from app import database

# app.server НЕ импортируем на уровне модуля — коллекция ломает изоляцию
# стабов app.server в соседних файлах (см. conftest); берём внутри тестов.


def _ca():
    from app.server import chat_analyzer
    return chat_analyzer


@pytest_asyncio.fixture(autouse=True)
async def _schema(tmp_db, disable_auth):
    await database.init_db()
    db = await database.get_db()
    try:
        for aid, role, cfg in [
            (1, "lurker", {}),
            (2, "lurker", {"mention_reply": True}),
            (3, "moderator", {"chat_activity": "chatter"}),
            (4, "moderator", {"chat_activity": "silent"}),
            (5, "moderator", {"chat_activity": "moderation_only"}),
            (6, "voice_companion", {}),
            (7, "chatter", {}),
        ]:
            # формат хранения — nested {роль: {...}} (§6.7), как пишет API
            await db.execute(
                "INSERT INTO accounts (id, nickname, token, bot_role, role_config_json) "
                "VALUES (?, ?, 't', ?, ?)",
                (aid, f"bot{aid}", role, json.dumps({role: cfg})),
            )
        await db.commit()
    finally:
        await db.close()
    _ca().invalidate_role_cache()


async def _set_account_role(aid: int, role: str, cfg: dict) -> None:
    db = await database.get_db()
    try:
        await db.execute(
            "UPDATE accounts SET bot_role = ?, role_config_json = ? WHERE id = ?",
            (role, json.dumps({role: cfg}), aid),
        )
        await db.commit()
    finally:
        await db.close()
    _ca().invalidate_role_cache()


@pytest.mark.asyncio
async def test_lurker_never_writes(tmp_db):
    ok, reason = await _ca()._role_reply_gate(1, is_mention=False)
    assert ok is False
    ok, _ = await _ca()._role_reply_gate(1, is_mention=True)
    assert ok is False  # mention_reply=false — молчит даже на @


@pytest.mark.asyncio
async def test_lurker_mention_reply_true(tmp_db):
    ok, _ = await _ca()._role_reply_gate(2, is_mention=True)
    assert ok is True
    ok, _ = await _ca()._role_reply_gate(2, is_mention=False)
    assert ok is False


@pytest.mark.asyncio
async def test_moderator_activity_modes(tmp_db):
    assert (await _ca()._role_reply_gate(3, False))[0] is True   # chatter
    assert (await _ca()._role_reply_gate(4, False))[0] is False  # silent
    assert (await _ca()._role_reply_gate(4, True))[0] is False   # silent даже на @
    assert (await _ca()._role_reply_gate(5, True))[0] is False   # moderation_only


@pytest.mark.asyncio
async def test_voice_companion_writes_to_public_chat(tmp_db):
    ok, reason = await _ca()._role_reply_gate(6, is_mention=True)
    assert ok is True and reason == ""


@pytest.mark.asyncio
async def test_chatter_regression(tmp_db):
    assert (await _ca()._role_reply_gate(7, False))[0] is True


@pytest.mark.asyncio
async def test_role_gate_reads_before_send(tmp_db):
    """Гейт стоит ДО send: _generate_and_send при запрещённой роли ничего не шлёт."""
    sent: list[str] = []
    _ca().invalidate_role_cache()
    await _set_account_role(1, "lurker", {})
    original_send = _ca().send_fn
    _ca().send_fn = lambda *a, **k: sent.append(a)
    try:
        await _ca()._generate_and_send(
            1, "chan", "botnick", "viewer", "привет", is_mention=True, extra_context="")
        assert sent == [], "lurker отправил сообщение — гейт не сработал"
    finally:
        _ca().send_fn = original_send
