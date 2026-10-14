"""Тесты политики эскалации таймаутов за повторные нарушения (Task 4)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from app import database
from app import moderation as M
from app import moderation_journal as J

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def _fresh_db(tmp_db, disable_auth):
    M.invalidate_cache()
    await database.init_db()
    yield
    M.invalidate_cache()


async def _make_bot(nickname: str = "modbot", **cols) -> int:
    db = await database.get_db()
    try:
        cur = await db.execute(
            "INSERT INTO accounts (nickname, token) VALUES (?, ?)",
            (nickname, "oauth:fake"),
        )
        await db.commit()
        aid = cur.lastrowid
        sets = {"moderation_mode": "full", "moderation_can_timeout": 1, **cols}
        assignments = ", ".join(f"{k} = ?" for k in sets)
        await db.execute(f"UPDATE accounts SET {assignments} WHERE id = ?", (*sets.values(), aid))
        await db.commit()
    finally:
        await db.close()
    M.invalidate_cache(aid)
    return aid


def _client() -> AsyncClient:
    import app.routes_modpanel  # noqa: F401
    from app.routes import router
    app = FastAPI()
    app.include_router(router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_calculate_escalated_duration():
    # 0 повторов — базовое время
    dur, note = M.calculate_escalated_duration(60, 0)
    assert dur == 60
    assert note == ""

    # 1 повтор — 10 минут минимум
    dur, note = M.calculate_escalated_duration(60, 1)
    assert dur == 600
    assert "эскалация x2" in note

    # 1 повтор с базой 300 — max(300*5, 600) = 1500
    dur, note = M.calculate_escalated_duration(300, 1)
    assert dur == 1500

    # 2 повтора — 1 час минимум
    dur, note = M.calculate_escalated_duration(60, 2)
    assert dur == 3600
    assert "эскалация x3" in note

    # 3+ повтора — 24 часа минимум
    dur, note = M.calculate_escalated_duration(60, 3)
    assert dur == 86400
    assert "эскалация x4" in note

    # Лимит Twitch (2 недели)
    dur, _ = M.calculate_escalated_duration(100000, 3)
    assert dur == 1209600


async def test_get_recent_punishment_count():
    aid = await _make_bot()
    chan = "streamer"
    user = "troll123"

    assert await M.get_recent_punishment_count(aid, chan, user) == 0

    # Добавляем 1 применённый таймаут
    await J.journal_applied(
        aid, chan, user,
        category="spam", severity=2, rule_name="rule1",
        action="timeout", duration_sec=60,
    )
    assert await M.get_recent_punishment_count(aid, chan, user) == 1

    # Другой канал / пользователь не должны учитываться
    assert await M.get_recent_punishment_count(aid, "otherchan", user) == 0
    assert await M.get_recent_punishment_count(aid, chan, "otheruser") == 0


async def test_maybe_punish_escalation_flow():
    aid = await _make_bot()
    chan = "mychannel"
    user = "badguy"

    verdict = M.Verdict(
        category="spam", action="timeout", severity=2,
        rule_name="rule_spam", duration_sec=60,
    )

    with patch("app.twitch_helix.timeout_user", new=AsyncMock(return_value=(True, None))) as mock_timeout:
        # 1-е нарушение: 60 сек
        res1 = await M.maybe_punish(aid, chan, user, verdict, token="fake_tok", bot_nickname="modbot")
        assert res1 == M.PUNISH_APPLIED
        assert mock_timeout.call_count == 1
        _, kwargs1 = mock_timeout.call_args
        assert kwargs1["duration_sec"] == 60

        # 2-е нарушение: эскалация до 600 сек (10 мин)
        res2 = await M.maybe_punish(aid, chan, user, verdict, token="fake_tok", bot_nickname="modbot")
        assert res2 == M.PUNISH_APPLIED
        assert mock_timeout.call_count == 2
        _, kwargs2 = mock_timeout.call_args
        assert kwargs2["duration_sec"] == 600

        # 3-е нарушение: эскалация до 3600 сек (1 час)
        res3 = await M.maybe_punish(aid, chan, user, verdict, token="fake_tok", bot_nickname="modbot")
        assert res3 == M.PUNISH_APPLIED
        assert mock_timeout.call_count == 3
        _, kwargs3 = mock_timeout.call_args
        assert kwargs3["duration_sec"] == 3600


async def test_escalation_disabled_keeps_base_duration():
    aid = await _make_bot(moderation_escalation_enabled=0)
    chan = "mychannel"
    user = "badguy2"

    verdict = M.Verdict(
        category="spam", action="timeout", severity=2,
        rule_name="rule_spam", duration_sec=60,
    )

    with patch("app.twitch_helix.timeout_user", new=AsyncMock(return_value=(True, None))) as mock_timeout:
        # 1-е нарушение
        await M.maybe_punish(aid, chan, user, verdict, token="fake_tok", bot_nickname="modbot")
        assert mock_timeout.call_args[1]["duration_sec"] == 60

        # 2-е нарушение при выключенной эскалации — всё ещё 60 сек
        await M.maybe_punish(aid, chan, user, verdict, token="fake_tok", bot_nickname="modbot")
        assert mock_timeout.call_args[1]["duration_sec"] == 60


async def test_settings_api_escalation_toggle():
    aid = await _make_bot()
    async with _client() as client:
        # GET: по умолчанию True
        resp = await client.get(f"/api/accounts/{aid}/moderation/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["escalation_enabled"] is True

        # PUT: выключаем
        put_resp = await client.put(f"/api/accounts/{aid}/moderation/settings", json={"escalation_enabled": False})
        assert put_resp.status_code == 200
        assert put_resp.json()["ok"] is True

        # Проверяем GET
        resp2 = await client.get(f"/api/accounts/{aid}/moderation/settings")
        assert resp2.json()["escalation_enabled"] is False
