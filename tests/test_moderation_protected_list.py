"""Q26 (DEC-OWNER-014): список защищённых от «бана навсегда» + кнопка «Разбанить».

Защищённые = модераторы/редакторы/стример (автоматически, PROTECTED_ROLES) + ручной
per-канал список; общего списка на все каналы нет. «Разбанить» — официальный
Unban User (DELETE /moderation/bans), 400 «not banned» = «уже не забанен».
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app import database
from app import moderation as M

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def _fresh_db(tmp_db, disable_auth):
    M.invalidate_cache()
    await database.init_db()
    yield
    M.invalidate_cache()


async def _make_bot(nickname: str = "modbot") -> int:
    db = await database.get_db()
    try:
        cur = await db.execute(
            "INSERT INTO accounts (nickname, token, bot_role) VALUES (?, ?, 'moderator')",
            (nickname, "oauth:tok"),
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


def _client() -> AsyncClient:
    from fastapi import FastAPI
    import app.routes_modpanel  # noqa: F401
    from app.moderation_journal_routes import router as journal_router
    from app.routes import router
    app = FastAPI()
    app.include_router(router)
    app.include_router(journal_router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_manual_list_is_per_channel_with_no_global_list():
    """Один и тот же ник защищён только на том канале, где вписан; общего списка нет."""
    aid = await _make_bot()
    await M.add_protected(aid, "#Chan", "Friend", note="друг канала")
    await M.add_protected(aid, "other", "VipGuy")

    assert await M.is_protected(aid, "chan", "friend") is True
    assert await M.is_protected(aid, "CHAN", "FRIEND") is True, "нормализация регистра и #"
    assert await M.is_protected(aid, "otherchan", "friend") is False
    assert await M.is_protected(aid + 1000, "chan", "friend") is False, \
        "список другого бота не утеает — защита per-бот × per-канал"


async def test_manual_list_overrides_role_and_can_be_removed():
    aid = await _make_bot()
    # vip не защищён автоматически — только ручным списком
    assert await M.is_protected(aid, "chan", "somevip", role="vip") is False
    await M.add_protected(aid, "chan", "SomeVip")
    assert await M.is_protected(aid, "chan", "somevip", role="vip") is True
    assert await M.remove_protected(aid, "chan", "SomeVip") is True
    assert await M.is_protected(aid, "chan", "somevip", role="vip") is False


async def test_api_protected_roundtrip_and_auto_roles():
    aid = await _make_bot()
    async with _client() as c:
        r = await c.post("/api/moderation/protected", json={
            "account_id": aid, "channel": "#Chan", "username": "Friend", "note": "vip",
        })
        assert r.json()["ok"] is True
        r = await c.get(f"/api/moderation/protected?account_id={aid}&channel=chan")
        body = r.json()
        assert body["entries"][0]["username"] == "friend" and body["entries"][0]["note"] == "vip"
        assert "moderator" in body["auto_roles"] and "editor" in body["auto_roles"]
        assert "vip" not in body["auto_roles"], "vip защищается только ручным списком"

        r = await c.delete(f"/api/moderation/protected/Friend?account_id={aid}&channel=chan")
        assert r.json()["removed"] is True
        r = await c.get(f"/api/moderation/protected?account_id={aid}&channel=chan")
        assert r.json()["entries"] == []


async def test_unban_route_uses_official_unban_and_reports_not_banned(monkeypatch):
    """Кнопка «Разбанить»: DELETE /moderation/bans; «not banned» — не ошибка."""
    aid = await _make_bot()
    calls: list = []

    async def fake_unban(token, channel, moderator_login, username):
        calls.append({"channel": channel, "mod": moderator_login, "user": username})
        return True, ""

    monkeypatch.setattr("app.twitch_helix.unban_user", fake_unban)
    async with _client() as c:
        r = await c.post("/api/moderation/journal/unban", json={
            "account_id": aid, "channel": "chan", "username": "friend",
        })
        assert r.json() == {"ok": True}
        assert calls and calls[0]["user"] == "friend"

        async def not_banned(token, channel, moderator_login, username):
            return False, "user_not_banned"
        monkeypatch.setattr("app.twitch_helix.unban_user", not_banned)
        r = await c.post("/api/moderation/journal/unban", json={
            "account_id": aid, "channel": "chan", "username": "friend",
        })
        assert r.json() == {"ok": True, "already_unbanned": True}


async def test_unban_route_requires_all_fields():
    async with _client() as c:
        r = await c.post("/api/moderation/journal/unban", json={"account_id": 1})
        assert r.json()["ok"] is False
