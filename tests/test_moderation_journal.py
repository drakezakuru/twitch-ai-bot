"""Q26 (DEC-OWNER-014): журнал наказаний, очередь подтверждения, автозакрытие.

Журнал — владельческий реестр per-канал: кто, когда, за что, какое действие, статус
(applied / pending / cancelled / expired). Нерешённые случаи закрываются через 30 дней.
Постановка в очередь без наказания — предохранитель «бана навсегда» из Q01-C2.
"""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

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


async def _make_bot(nickname: str = "modbot", bot_role: str = "moderator", **cols) -> int:
    db = await database.get_db()
    try:
        cur = await db.execute(
            "INSERT INTO accounts (nickname, token, bot_role) VALUES (?, ?, ?)",
            (nickname, "oauth:tok", bot_role),
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


def _verdict(action: str, *, duration=None) -> M.Verdict:
    return M.Verdict(category="insult", action=action, severity=5, rule_name="r1",
                     action_ext=action if action in ("ban", "timeout") else "",
                     duration_sec=duration)


def _client() -> AsyncClient:
    from fastapi import FastAPI
    import app.routes_modpanel  # noqa: F401
    from app.moderation_journal_routes import router as journal_router
    from app.routes import router
    app = FastAPI()
    app.include_router(router)
    app.include_router(journal_router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ─────────────────────────── журнал: записи и статусы ───────────────────────────


async def test_journal_schema_created_by_init_db():
    db = await database.get_db()
    try:
        cur = await db.execute("PRAGMA table_info(moderation_journal)")
        cols = {row["name"] for row in await cur.fetchall()}
    finally:
        await db.close()
    assert {"account_id", "channel", "username", "action", "duration_sec", "status",
            "detail", "pending_id", "created_at", "decided_at"} <= cols


async def test_applied_punishment_lands_in_journal(monkeypatch):
    """Применённый таймаут через maybe_punish → запись журнала applied."""
    aid = await _make_bot()
    seen: list = []
    monkeypatch.setattr("app.twitch_helix.timeout_user", _capture_timeout(seen, 3600))

    status = await M.maybe_punish(aid, "chan", "spammer", _verdict("timeout", duration=3600),
                                  token="oauth:x", bot_nickname="modbot")

    assert status == M.PUNISH_APPLIED
    entries = await J.list_journal(account_id=aid, channel="chan")
    assert len(entries) == 1
    e = entries[0]
    assert e["status"] == "applied" and e["action"] == "timeout" and e["duration_sec"] == 3600
    assert e["username"] == "spammer"


def _capture_timeout(seen: list, expect_duration: int):
    async def stub(token, channel, moderator_login, username, duration_sec=600, reason=""):
        seen.append({"duration": duration_sec})
        return True, ""
    return stub


async def test_protected_ban_creates_pending_case_without_punishment(monkeypatch):
    """Постановка в очередь без наказания: ни одного вызова Helix, статус pending."""
    aid = await _make_bot()
    await M.add_protected(aid, "chan", "friend")
    calls: list = []
    monkeypatch.setattr("app.twitch_helix.timeout_user", _capture_timeout(calls, 600))
    monkeypatch.setattr("app.twitch_helix.ban_user",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("Helix вызван!")))

    status = await M.maybe_punish(aid, "chan", "friend", _verdict("ban"),
                                  token="oauth:x", bot_nickname="modbot", role="viewer")

    assert status == M.PUNISH_DEFERRED
    assert calls == []
    cases = await J.list_pending_cases(account_id=aid, channel="chan")
    assert len(cases) == 1
    assert cases[0]["action"] == "ban" and cases[0]["status"] == "pending"
    assert "защищён" in cases[0]["detail"]


async def test_moderator_role_is_protected_automatically_in_journal_flow(monkeypatch):
    """Автоматическая защита модератора: вердикт ban → pending, не applied."""
    aid = await _make_bot()
    monkeypatch.setattr("app.twitch_helix.ban_user",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("Helix вызван!")))

    status = await M.maybe_punish(aid, "chan", "modfriend", _verdict("ban"),
                                  token="oauth:x", bot_nickname="modbot", role="moderator")

    assert status == M.PUNISH_DEFERRED
    cases = await J.list_pending_cases(account_id=aid)
    assert cases and cases[0]["username"] == "modfriend"


async def test_owner_decision_updates_journal_status(monkeypatch):
    """Забанить → applied; Не наказывать → cancelled (запись остаётся в журнале)."""
    aid = await _make_bot()
    await M.add_protected(aid, "chan", "friend")
    async def _ban_ok(*a, **k):
        return True, ""
    monkeypatch.setattr("app.twitch_helix.ban_user", _ban_ok)
    await M.maybe_punish(aid, "chan", "friend", _verdict("ban"),
                         token="", bot_nickname="modbot", role="viewer")
    case = (await J.list_pending_cases(account_id=aid))[0]

    result = await M.record_timeout_decision(case["pending_id"], True, token="oauth:x", bot_nickname="modbot")
    assert result["ok"] and result["executed"] is True
    entries = await J.list_journal(account_id=aid)
    assert entries[0]["status"] == "applied"
    assert "подтверждено владельцем" in entries[0]["detail"]

    # второй случай — отклоняем (тоже защищённый зритель, иначе движок его skipped)
    await M.add_protected(aid, "chan", "friend2")
    await M.maybe_punish(aid, "chan", "friend2", _verdict("ban"),
                         token="", bot_nickname="modbot", role="viewer")
    case2 = (await J.list_pending_cases(account_id=aid))[0]
    await M.record_timeout_decision(case2["pending_id"], False)
    entries = await J.list_journal(account_id=aid)
    statuses = {e["username"]: e["status"] for e in entries}
    assert statuses["friend2"] == "cancelled"


async def test_pending_case_expires_after_30_days():
    """Нерешённый случай закрывается сам: expired «не подтверждено, закрыт по сроку»."""
    aid = await _make_bot()
    await M.add_protected(aid, "chan", "friend")
    await M.maybe_punish(aid, "chan", "friend", _verdict("ban"),
                         token="", bot_nickname="modbot", role="viewer")
    db = await database.get_db()
    try:
        await db.execute(
            "UPDATE moderation_journal SET created_at = datetime('now', '-31 days') "
            "WHERE account_id = ?", (aid,),
        )
        await db.commit()
    finally:
        await db.close()

    entries = await J.list_journal(account_id=aid)  # чтение само гасит просрочку

    assert entries[0]["status"] == "expired"
    assert "закрыт по сроку" in entries[0]["detail"]
    assert await J.list_pending_cases(account_id=aid) == []


# ─────────────────────────── API журнала и разбана ───────────────────────────


async def test_journal_api_lists_and_resolves(monkeypatch):
    aid = await _make_bot()
    await M.add_protected(aid, "chan", "friend")
    async def _ban_ok(*a, **k):
        return True, ""
    monkeypatch.setattr("app.twitch_helix.ban_user", _ban_ok)
    await M.maybe_punish(aid, "chan", "friend", _verdict("ban"),
                         token="", bot_nickname="modbot", role="viewer")

    async with _client() as c:
        r = await c.get("/api/moderation/journal/pending?channel=chan")
        body = r.json()
        assert body["ok"] is True and body["total"] == 1
        entry_id = body["entries"][0]["id"]

        r = await c.post(f"/api/moderation/journal/{entry_id}/resolve", json={"approve": True})
        assert r.json()["ok"] is True

        r = await c.get("/api/moderation/journal?channel=chan")
        assert r.json()["entries"][0]["status"] == "applied"


async def test_journal_api_lists_and_resolves(monkeypatch):
    aid = await _make_bot()
    await M.add_protected(aid, "chan", "friend")
    async def _ban_ok(*a, **k):
        return True, ""
    monkeypatch.setattr("app.twitch_helix.ban_user", _ban_ok)
    await M.maybe_punish(aid, "chan", "friend", _verdict("ban"),
                         token="", bot_nickname="modbot", role="viewer")

    async with _client() as c:
        r = await c.get("/api/moderation/journal/pending?channel=chan")
        body = r.json()
        assert body["ok"] is True and body["total"] == 1
        entry_id = body["entries"][0]["id"]

        r = await c.post(f"/api/moderation/journal/{entry_id}/resolve", json={"approve": True})
        assert r.json()["ok"] is True

        r = await c.get("/api/moderation/journal?channel=chan")
        assert r.json()["entries"][0]["status"] == "applied"
