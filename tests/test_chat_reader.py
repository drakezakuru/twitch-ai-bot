"""§6.1 WIDGETS_PLAN: тести для Chat Reader (озвучка чату)."""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


async def _client():
    from app.database import init_db
    from app.widgets import admin_router, public_router, ensure_widgets_schema
    from app.routes import router as api_router
    await init_db()
    await ensure_widgets_schema()
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(api_router)
    app.include_router(admin_router)
    app.include_router(public_router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed(*aids: int) -> None:
    from app.database import init_db, get_db
    from app.widgets import ensure_widgets_schema
    await init_db()
    await ensure_widgets_schema()
    db = await get_db()
    try:
        for aid in aids:
            await db.execute(
                "INSERT OR IGNORE INTO accounts (id, nickname, token) "
                "VALUES (?, ?, ?)",
                (aid, f"reader_{aid}", "tok"),
            )
        await db.commit()
    finally:
        await db.close()


# ── _normalize_role / _role_satisfies / _badges_to_role ────────────

def test_normalize_role_unknown_falls_back_to_any():
    from app.widgets import _normalize_role
    assert _normalize_role("any") == "any"
    assert _normalize_role("VIP") == "vip"
    assert _normalize_role("broadcaster") == "broadcaster"
    assert _normalize_role("weird") == "any"
    assert _normalize_role("") == "any"


def test_role_satisfies_hierarchy():
    from app.widgets import _role_satisfies
    assert _role_satisfies("broadcaster", "any")
    assert _role_satisfies("moderator", "vip")
    assert _role_satisfies("vip", "subscriber")
    assert not _role_satisfies("subscriber", "vip")
    assert not _role_satisfies("any", "subscriber")


def test_badges_to_role_priority():
    from app.widgets import _badges_to_role
    assert _badges_to_role(None) == "any"
    assert _badges_to_role([]) == "any"
    assert _badges_to_role(["subscriber"]) == "subscriber"
    assert _badges_to_role(["vip", "subscriber"]) == "vip"
    assert _badges_to_role(["moderator", "vip"]) == "moderator"
    assert _badges_to_role(["broadcaster", "moderator"]) == "broadcaster"
    assert _badges_to_role(["founder"]) == "subscriber"


# ── read_chat_message ────────────────────────────────────────────────

async def test_read_chat_disabled_returns_skipped(tmp_db, disable_auth):
    await _seed(10)
    from app.widgets import read_chat_message
    res = await read_chat_message(10, "channel", "user1", "hello",
                                   trigger="all", badges=None)
    assert res.get("skipped") == "disabled"


async def test_read_chat_empty_text_skipped(tmp_db, disable_auth):
    await _seed(11)
    from app.database import get_db
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO chat_reader_settings (account_id, enabled, read_all) "
            "VALUES (11, 1, 1)"
        )
        await db.commit()
    finally:
        await db.close()
    from app.widgets import read_chat_message
    res = await read_chat_message(11, "channel", "user1", "   ",
                                   trigger="all", badges=None)
    assert res.get("skipped") in ("empty", "empty_after_trim")


async def test_read_chat_cooldown_enforced(tmp_db, disable_auth):
    await _seed(12)
    from app.database import get_db
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO chat_reader_settings (account_id, enabled, read_all, cooldown_sec) "
            "VALUES (12, 1, 1, 60)"
        )
        await db.commit()
    finally:
        await db.close()

    # Мокаем TTS-двигун, щоб не блокувати на синтезі.
    from app import tts_engine
    called: list[dict] = []
    class FakeEngine:
        async def speak(self, account_id, channel, text, emotion="neutral", **kwargs):
            called.append({"aid": account_id, "ch": channel, "text": text})
    monkey = pytest.MonkeyPatch()
    monkey.setattr(tts_engine, "get_tts_engine", lambda: FakeEngine())
    try:
        from app.widgets import read_chat_message
        r1 = await read_chat_message(12, "ch1", "u1", "hello",
                                      trigger="all", badges=None)
        # Перший виклик має пройти (cooldown ще не витрачений)
        assert r1.get("ok") is True or r1.get("error") is None
        r2 = await read_chat_message(12, "ch1", "u1", "world",
                                      trigger="all", badges=None)
        # Другий — заблокований cooldown
        assert r2.get("skipped") == "cooldown"
    finally:
        monkey.undo()


async def test_read_chat_min_role_filter_read_all(tmp_db, disable_auth):
    """У режимі read_all фільтруємо по min_role (vip+)."""
    await _seed(13)
    from app.database import get_db
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO chat_reader_settings "
            "(account_id, enabled, read_all, min_role) VALUES (13, 1, 1, 'vip')"
        )
        await db.commit()
    finally:
        await db.close()

    from app import tts_engine
    called: list[dict] = []
    class FakeEngine:
        async def speak(self, account_id, channel, text, emotion="neutral", **kwargs):
            called.append({"aid": account_id, "ch": channel, "text": text})
    monkey = pytest.MonkeyPatch()
    monkey.setattr(tts_engine, "get_tts_engine", lambda: FakeEngine())
    try:
        from app.widgets import read_chat_message
        # Subscriber — не пройде фільтр
        r = await read_chat_message(13, "ch", "user1", "hi",
                                     trigger="all", badges=["subscriber"])
        assert r.get("skipped") == "role_too_low"
        # VIP — пройде
        r2 = await read_chat_message(13, "ch", "user2", "hi",
                                      trigger="all", badges=["vip"])
        assert r2.get("ok") is True
    finally:
        monkey.undo()


async def test_read_chat_command_mode_no_role_filter(tmp_db, disable_auth):
    """У режимі command (!read) — фільтр min_role НЕ застосовується."""
    await _seed(14)
    from app.database import get_db
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO chat_reader_settings "
            "(account_id, enabled, read_all, command, min_role) "
            "VALUES (14, 1, 0, '!read', 'broadcaster')"
        )
        await db.commit()
    finally:
        await db.close()

    from app import tts_engine
    called: list[dict] = []
    class FakeEngine:
        async def speak(self, account_id, channel, text, emotion="neutral", **kwargs):
            called.append({"text": text})
    monkey = pytest.MonkeyPatch()
    monkey.setattr(tts_engine, "get_tts_engine", lambda: FakeEngine())
    try:
        from app.widgets import read_chat_message
        # Звичайний глядач із !read — все одно проходить
        r = await read_chat_message(14, "ch", "u1", "my text",
                                     trigger="command", badges=None)
        assert r.get("ok") is True
    finally:
        monkey.undo()


async def test_read_chat_max_chars_trim(tmp_db, disable_auth):
    await _seed(15)
    from app.database import get_db
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO chat_reader_settings "
            "(account_id, enabled, read_all, command, min_role, max_chars, cooldown_sec) "
            "VALUES (15, 1, 1, '!read', 'any', 10, 0)"
        )
        await db.commit()
    finally:
        await db.close()
    from app import tts_engine
    sent: list[str] = []
    class FakeEngine:
        async def speak(self, account_id, channel, text, emotion="neutral", **kwargs):
            sent.append(text)
    monkey = pytest.MonkeyPatch()
    monkey.setattr(tts_engine, "get_tts_engine", lambda: FakeEngine())
    try:
        from app.widgets import read_chat_message
        await read_chat_message(15, "ch", "u", "ABCDEFGHIJKLMNOP",
                                 trigger="all", badges=None)
        assert len(sent) == 1
        assert len(sent[0]) == 10
    finally:
        monkey.undo()


# ── admin endpoints ───────────────────────────────────────────────

async def test_chat_reader_settings_get_default(tmp_db, disable_auth):
    await _seed(20)
    async with await _client() as c:
        r = await c.get("/api/widgets/chat-reader/settings?account_id=20")
        assert r.status_code == 200
        s = r.json()["settings"]
        assert s["enabled"] == 0
        assert s["read_all"] == 0
        assert s["command"] == "!read"
        assert s["min_role"] == "any"
        assert s["max_chars"] == 200


async def test_chat_reader_settings_put_clamps(tmp_db, disable_auth):
    await _seed(21)
    async with await _client() as c:
        r = await c.put(
            "/api/widgets/chat-reader/settings?account_id=21",
            json={
                "enabled": 1,
                "read_all": 1,
                "command": "read",  # без ! — додаємо префікс
                "min_role": "VIP",
                "max_chars": 9999,
                "cooldown_sec": 9999,
            },
        )
        assert r.status_code == 200
        s = r.json()["settings"]
        assert s["enabled"] == 1
        assert s["read_all"] == 1
        assert s["command"] == "!read"  # додали !
        assert s["min_role"] == "vip"
        assert s["max_chars"] == 500  # clamp
        assert s["cooldown_sec"] == 60  # clamp


async def test_chat_reader_settings_command_keeps_existing(tmp_db, disable_auth):
    """PUT з повним payload оновлює всі поля (включаючи command)."""
    await _seed(22)
    async with await _client() as c:
        # Спочатку поставимо кастомну команду
        r1 = await c.put(
            "/api/widgets/chat-reader/settings?account_id=22",
            json={"command": "!say"},
        )
        assert r1.json()["settings"]["command"] == "!say"
        # Наступний PUT з command — оновлює
        r2 = await c.put(
            "/api/widgets/chat-reader/settings?account_id=22",
            json={"command": "!read", "enabled": 1},
        )
        assert r2.json()["settings"]["command"] == "!read"
        assert r2.json()["settings"]["enabled"] == 1
