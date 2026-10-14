"""§2 WIDGETS_PLAN: тести для TTS-бот "Golden Voice".

Покриває:
1. /widget/tts-bot рендерить HTML з правильним акцент-кольором та іконкою.
2. Параметри ?color= та ?emoji= з URL перевизначають дефолт.
3. Якщо в tts_bot_config є widget_color/emoji — беремо з БД (по account_id).
4. GET/PUT /api/widgets/tts-bot/config працює (CRUD для адмін-форми).
5. _hex_to_rgba коректно конвертує + фолбек на gold.
6. _normalize_hex валідує колір (невалідний → дефолт).
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


async def _client(seed_accounts: tuple[int, ...] = ()):
    """Створює тестовий клієнт + БД. За потреби сіє accounts (для FK tts_bot_config)."""
    from app import database as db_mod
    # Скидаємо singleton-коннект, щоб новий init_db() гарантовано створив
    # таблиці у свіжій tmp-БД (а не повернув старий _shared_db з попереднього тесту).
    if db_mod._shared_db is not None:
        try:
            await db_mod._shared_db.close()
        except Exception:
            pass
        db_mod._shared_db = None
    from app.database import init_db
    from app.widgets import admin_router, public_router, ensure_widgets_schema
    await init_db()
    await ensure_widgets_schema()

    # Сидимо тестові акаунти (для FK tts_bot_config -> accounts.id).
    if seed_accounts:
        from app.database import get_db
        db = await get_db()
        try:
            for aid in seed_accounts:
                await db.execute(
                    "INSERT OR IGNORE INTO accounts (id, nickname, token) "
                    "VALUES (?, ?, ?)",
                    (aid, f"test_aid_{aid}", "test_token"),
                )
            await db.commit()
        finally:
            await db.close()

    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(public_router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_widget_tts_bot_default_gold(tmp_db, disable_auth):
    async with await _client() as c:
        r = await c.get("/widget/tts-bot")
        assert r.status_code == 200
        html = r.text
        assert "#FFD700" in html  # gold default
        assert "🎙️" in html
        # i18n-заглушка: бренд «Golden Voice» присутствует во всех локалях
        assert "Golden Voice" in html
        assert "0" in html  # account_id=0 за замовчуванням


async def test_widget_tts_bot_custom_color_emoji(tmp_db, disable_auth):
    async with await _client() as c:
        r = await c.get("/widget/tts-bot?color=%23ff00aa&emoji=🦊")
        assert r.status_code == 200
        html = r.text
        assert "#FF00AA" in html
        assert "🦊" in html


async def test_widget_tts_bot_invalid_color_falls_back(tmp_db, disable_auth):
    async with await _client() as c:
        r = await c.get("/widget/tts-bot?color=notahex")
        assert r.status_code == 200
        assert "#FFD700" in r.text  # gold fallback


async def _ensure_account(account_id: int) -> None:
    """DEPRECATED: use _seed_accounts(*ids). Залишено для зворотної сумісності."""
    await _seed_accounts(account_id)


async def test_widget_tts_bot_uses_db_config(tmp_db, disable_auth):
    """Якщо в tts_bot_config є колір/emoji — беремо звідти, а не з URL."""
    async with await _client(seed_accounts=(1,)) as c:
        # Заповнюємо через admin endpoint (заодно перевіряємо CRUD).
        r = await c.put(
            "/api/widgets/tts-bot/config?account_id=1",
            json={"widget_color": "#00FF88", "widget_emoji": "🐉"},
        )
        assert r.status_code == 200

        r2 = await c.get("/widget/tts-bot?account_id=1")
        assert r2.status_code == 200
        assert "#00FF88" in r2.text
        assert "🐉" in r2.text


async def test_widget_tts_bot_url_overrides_db(tmp_db, disable_auth):
    """?color= в URL має пріоритет над tts_bot_config."""
    async with await _client(seed_accounts=(2,)) as c:
        # Конфіг через admin
        await c.put(
            "/api/widgets/tts-bot/config?account_id=2",
            json={"widget_color": "#00FF88", "widget_emoji": "🐉"},
        )
        r = await c.get("/widget/tts-bot?account_id=2&color=%23aabbcc")
        assert r.status_code == 200
        # URL-колір виграв
        assert "#AABBCC" in r.text
        # Але іконка лишилась з конфігу
        assert "🐉" in r.text


async def test_tts_bot_config_get_default(tmp_db, disable_auth):
    async with await _client() as c:
        r = await c.get("/api/widgets/tts-bot/config?account_id=999")
        assert r.status_code == 200
        data = r.json()
        assert data["account_id"] == 999
        assert data["widget_color"] == "#FFD700"
        assert data["widget_emoji"] == "🎙️"
        assert data["emoji_prefix"] == ""
        assert data["emoji_suffix"] == ""


async def test_tts_bot_config_put_creates_and_updates(tmp_db, disable_auth):
    """PUT створює рядок, потім оновлює — values повертаються коректні."""
    async with await _client(seed_accounts=(5,)) as c:
        r = await c.put(
            "/api/widgets/tts-bot/config?account_id=5",
            json={
                "widget_color": "#abcdef",
                "widget_emoji": "🎤",
                "emoji_prefix": "✨",
                "emoji_suffix": "💫",
            },
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True

        r2 = await c.get("/api/widgets/tts-bot/config?account_id=5")
        data = r2.json()
        assert data["widget_color"] == "#ABCDEF"
        assert data["widget_emoji"] == "🎤"
        assert data["emoji_prefix"] == "✨"
        assert data["emoji_suffix"] == "💫"

        # Update — інший колір
        r3 = await c.put(
            "/api/widgets/tts-bot/config?account_id=5",
            json={"widget_color": "#123456"},
        )
        assert r3.status_code == 200
        r4 = await c.get("/api/widgets/tts-bot/config?account_id=5")
        assert r4.json()["widget_color"] == "#123456"
        # Іконка/префікс/суфікс лишились як були
        assert r4.json()["widget_emoji"] == "🎤"
        assert r4.json()["emoji_prefix"] == "✨"


async def test_tts_bot_config_put_validates_color(tmp_db, disable_auth):
    """PUT з невалідним кольором — нормалізуємо до дефолту gold."""
    async with await _client(seed_accounts=(7,)) as c:
        r = await c.put(
            "/api/widgets/tts-bot/config?account_id=7",
            json={"widget_color": "totally-not-hex"},
        )
        assert r.status_code == 200
        assert r.json()["widget_color"] == "#FFD700"


async def test_hex_to_rgba_basic():
    from app.widgets import _hex_to_rgba
    assert _hex_to_rgba("#FF0000", 0.5) == "rgba(255,0,0,0.5)"
    assert _hex_to_rgba("#00ff88", 1.0) == "rgba(0,255,136,1.0)"
    # Без # теж працює
    assert _hex_to_rgba("FFAA00", 0.25) == "rgba(255,170,0,0.25)"


async def test_hex_to_rgba_invalid_falls_back_to_gold():
    from app.widgets import _hex_to_rgba
    assert _hex_to_rgba("zzz", 0.5) == "rgba(255,215,0,0.5)"
    assert _hex_to_rgba("#12345", 0.5) == "rgba(255,215,0,0.5)"  # 5 chars → invalid
    assert _hex_to_rgba("", 0.7) == "rgba(255,215,0,0.7)"


async def test_normalize_hex():
    from app.widgets import _normalize_hex
    assert _normalize_hex("#abcdef") == "#ABCDEF"
    assert _normalize_hex("abcdef") == "#ABCDEF"
    assert _normalize_hex("  #aabbcc  ") == "#AABBCC"
    assert _normalize_hex("zzz") == "#FFD700"  # default gold
    assert _normalize_hex("") == "#FFD700"
    assert _normalize_hex(None) == "#FFD700"  # type: ignore[arg-type]
