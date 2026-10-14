"""P8-C3: отношение к стримеру — в карточку бота + негативные тона.

Вердикт владельца: (1) UI перенесён из Мозга в карточку бота (вкладка
«Роль»); (2) добавлены тона «раздражает» / «не выносит» / «пренебрегает»
с промпт-блоками. Данные по-прежнему per-bot × канал (streamer_attitude).
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app import streamer_attitude as sa


@pytest.fixture
def app(disable_auth, tmp_db):
    application = FastAPI()
    application.include_router(sa.router)
    return application


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def test_negative_tones_in_attitudes_and_prompts():
    for tone in ("irritated", "intolerable", "dismissive"):
        assert tone in sa.ATTITUDES
        prompt = sa.format_attitude_line(tone)
        assert prompt, f"нет промпт-блока для {tone}"
    assert "РАЗДРАЖАЕТ" in sa.format_attitude_line("irritated")
    assert "НЕ ВЫНОСИШЬ" in sa.format_attitude_line("intolerable")
    assert "ПРЕНЕБРЕГАЕШЬ" in sa.format_attitude_line("dismissive")


@pytest.mark.asyncio
async def test_schema_migration_adds_negative_tones(tmp_db, disable_auth):
    """Старая таблица с CHECK на 4 тона пересоздаётся — новые сохраняются."""
    from app.database import init_db, get_db
    await init_db()
    db = await get_db()
    try:
        # seed аккаунта ДО set (FK)
        await db.execute(
            "INSERT OR IGNORE INTO accounts (id, nickname, token) VALUES (1,'b1','t')")
        await db.commit()
    finally:
        await db.close()
    # set_attitude сам накатывает ensure_schema (и миграцию CHECK)
    assert (await sa.set_attitude(1, "mychan", "intolerable")).get("ok") is True
    db = await get_db()
    try:
        cur = await db.execute("SELECT sql FROM sqlite_master WHERE name='streamer_attitude'")
        ddl = str((await cur.fetchone())[0])
        assert "dismissive" in ddl
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_set_and_get_negative_tone_roundtrip(tmp_db, disable_auth):
    from app.database import init_db, get_db
    await init_db()
    db = await get_db()
    try:
        await db.execute("INSERT OR IGNORE INTO accounts (id, nickname, token) VALUES (1,'b1','t')")
        await db.commit()
    finally:
        await db.close()
    res = await sa.set_attitude(1, "mychan", "irritated")
    assert res.get("ok") is True
    assert await sa.get_attitude(1, "mychan") == "irritated"
    assert await sa.get_attitude(1, "") == "neutral"  # fallback без канала
    # плохой тон не сохраняется
    bad = await sa.set_attitude(1, "", "hate")
    assert bad.get("ok") is False


@pytest.mark.asyncio
async def test_api_list_includes_per_channel_map(tmp_db, disable_auth):
    from app.database import init_db, get_db
    await init_db()
    db = await get_db()
    try:
        await db.execute("INSERT OR IGNORE INTO accounts (id, nickname, token) VALUES (1,'b1','t')")
        await db.commit()
    finally:
        await db.close()
    await sa.set_attitude(1, "chan1", "dismissive")
    items = (await sa.api_list()).get("items") or []
    assert items, "нет списка ботов"
    for it in items:
        assert "_per_channel" in it


def test_ui_moved_to_bot_card():
    root = __import__("pathlib").Path(__file__).parent.parent
    bots = (root / "templates" / "partials" / "bots.html").read_text(encoding="utf-8")
    brain = (root / "templates" / "partials" / "brain.html").read_text(encoding="utf-8")
    assert 'id="botAttitudeBox"' in bots, "блок отношения не в карточке бота"
    assert "saBotRows" not in brain, "старый блок остался в Мозге"
    assert "saBotRows" not in bots
    bots_js = (root / "static" / "app" / "03_bots.js").read_text(encoding="utf-8")
    assert "loadBotAttitude" in bots_js and "saveBotAttitude" in bots_js
    assert "attitude_irritated" in bots_js
    brain_js = (root / "static" / "app" / "09_brain_p3.js").read_text(encoding="utf-8")
    assert "function loadStreamerAttitudes" not in brain_js, "старый лоадер остался в 09-чанке"
    for key in ("attitude_irritated", "attitude_intolerable", "attitude_dismissive"):
        assert brain_js.count(f"'streamer.{key}'") >= 3, key
    settings_js = (root / "static" / "app" / "04_chat_settings.js").read_text(encoding="utf-8")
    assert "loadStreamerAttitudes()" not in settings_js
