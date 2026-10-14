"""PLAN_SESSION_ROLES §R2 wire-in: нарушения бота-модератора → mod-feed."""

from __future__ import annotations

import json

import pytest
import pytest_asyncio

from app import database
from app.mod_feed_routes import _BUFFER, _DEDUP, _INTENTS

# app.server не импортируем на уровне модуля (изоляция стабов в conftest)
def _ca():
    from app.server import chat_analyzer
    return chat_analyzer


@pytest_asyncio.fixture(autouse=True)
async def _schema(tmp_db, disable_auth):
    await database.init_db()
    db = await database.get_db()
    try:
        # бот-модератор в режиме confirm + обычный бот (не модератор)
        await db.execute(
            "INSERT INTO accounts (id, nickname, token, bot_role, role_config_json) "
            "VALUES (1, 'modbot', 't', 'moderator', ?)",
            (json.dumps({"moderator": {"confirm_mode": "confirm"}}),),
        )
        await db.execute(
            "INSERT INTO accounts (id, nickname, token, bot_role, role_config_json) "
            "VALUES (2, 'plainbot', 't', 'chatter', '{}')",
        )
        await db.commit()
    finally:
        await db.close()
    _BUFFER.clear()
    _DEDUP.clear()
    _INTENTS.clear()
    _ca().invalidate_role_cache()


class _V:
    """Заглушка вердикта модерации."""

    def __init__(self, category="swear", action="timeout", severity=4):
        self.category = category
        self.action = action
        self.severity = severity
        self.rule_name = "test_rule"
        self.rule_id = None
        self.masked_text = "м***к"


@pytest.mark.asyncio
async def test_moderator_confirm_publishes_intent(tmp_db):
    await _ca()._modfeed_moderation(
        1, "alekzz", "badguy", [_V()], executed=False, nickname="modbot")
    kinds = [e["kind"] for e in _BUFFER]
    assert "intent" in kinds, "намерение не опубликовано"
    ev = next(e for e in _BUFFER if e["kind"] == "intent")
    assert ev["user"] == "badguy" and ev["status"] == "pending"
    assert "таймаут" in ev["text"] and ev["intent"]["minutes"] == 1


@pytest.mark.asyncio
async def test_moderator_auto_publishes_action(tmp_db):
    await _ca()._modfeed_moderation(
        1, "alekzz", "badguy", [_V()], executed=True, nickname="modbot")
    kinds = [e["kind"] for e in _BUFFER]
    assert "violation" in kinds and "action" in kinds
    assert not [e for e in _BUFFER if e["kind"] == "intent"]


@pytest.mark.asyncio
async def test_non_moderator_publishes_nothing(tmp_db):
    await _ca()._modfeed_moderation(
        2, "alekzz", "badguy", [_V()], executed=True, nickname="plainbot")
    assert len(_BUFFER) == 0, "не-модератор не должен писать в mod-feed"


@pytest.mark.asyncio
async def test_tts_announce_flag_duplicated(monkeypatch):
    """§R2-хвост: tts_announce=true → действие модератора озвучивается."""
    spoken: list[str] = []

    class _Tts:
        async def speak(self, account_id, channel, text, emotion="neutral", **kwargs):
            spoken.append(text)

    import app.tts_engine as _te
    monkeypatch.setattr(_te, "get_tts_engine", lambda: _Tts())
    # включаем опцию роли
    db = await database.get_db()
    await db.execute(
        "UPDATE accounts SET role_config_json = ? WHERE id = 1",
        (json.dumps({"moderator": {"confirm_mode": "confirm", "tts_announce": True}}),))
    await db.commit()
    await db.close()
    _ca().invalidate_role_cache()
    await _ca()._modfeed_moderation(
        1, "alekzz", "badguy", [_V()], executed=True, nickname="modbot")
    assert spoken and "badguy" in spoken[0], "TTS-дублирование не сработало"


@pytest.mark.asyncio
async def test_tts_announce_default_silent():
    """tts_announce=false (дефолт) → озвучки нет."""
    spoken: list[str] = []

    class _Tts:
        async def speak(self, account_id, channel, text, emotion="neutral", **kwargs):
            spoken.append(text)

    from app import tts_engine as _te
    orig = _te.get_tts_engine
    _te.get_tts_engine = lambda: _Tts()
    try:
        await _ca()._modfeed_moderation(
            1, "alekzz", "badguy", [_V()], executed=True, nickname="modbot")
    finally:
        _te.get_tts_engine = orig
    assert spoken == [], "без tts_announce озвучки быть не должно"
