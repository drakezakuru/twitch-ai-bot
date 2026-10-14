"""К3 AUDIT_PLACEMENT / §1.4: отношение ботов к стримеру + строка в промпте."""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport
from tests import _panel_js

pytestmark = pytest.mark.asyncio


async def _seed_accounts(*nicknames):
    from app.database import init_db
    await init_db()
    from app.database import get_db
    db = await get_db()
    try:
        for i, nick in enumerate(nicknames, 1):
            await db.execute(
                "INSERT OR IGNORE INTO accounts (id, nickname, token) VALUES (?, ?, 't')",
                (i, nick))
        await db.commit()
    finally:
        await db.close()


async def test_attitude_roundtrip_and_is_strictly_per_channel(tmp_db, disable_auth):
    """PUT/GET строго per-channel (owner survey Q11, 03.09).

    Глобальный scope («🌐 Все каналы») убран намеренно: `set_attitude` без
    канала отвечает 400 `channel_required`, а отношение одного канала не
    протекает на другие — там остаётся `neutral`.
    """
    from fastapi import HTTPException
    from app.streamer_attitude import get_attitude, set_attitude
    await _seed_accounts("botA", "botB")
    assert await get_attitude(1, "ch1") == "neutral"  # ничего не задано
    r1 = await set_attitude(1, "ch1", "adore"); assert r1["ok"] is True
    r2 = await set_attitude(2, "ch2", "watching"); assert r2["ok"] is True
    assert await get_attitude(1, "#ch1") == "adore"    # # нормализуется
    assert await get_attitude(2, "ch2") == "watching"
    # Q11: канал не задан — это ошибка, а не «глобальное» отношение.
    with pytest.raises(HTTPException) as exc:
        await set_attitude(2, "", "watching")
    assert exc.value.status_code == 400
    # Отношение не протекает между каналами и ботами.
    assert await get_attitude(2, "anything") == "neutral"
    assert await get_attitude(1, "ch2") == "neutral"
    r3 = await set_attitude(1, "ch1", "banana"); assert r3["ok"] is False  # проверка значения


async def test_api_list_and_set(tmp_db, disable_auth):
    from app.database import init_db
    await init_db()
    await _seed_accounts("botA", "botB")
    from fastapi import FastAPI
    from app.routes import router
    from app.streamer_attitude import router as sa_router
    app = FastAPI()
    app.include_router(router)
    app.include_router(sa_router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/streamer-attitude?channel=")
        assert r.status_code == 200
        items = r.json()["items"]
        assert [i["attitude"] for i in items] == ["neutral", "neutral"]
        put = await c.put("/api/streamer-attitude/2", json={"channel": "chan", "attitude": "adore"})
        assert put.json()["ok"] is True
        items = (await c.get("/api/streamer-attitude?channel=chan")).json()["items"]
        assert items[1]["attitude"] == "adore"
        # Q11: без канала отношение не сохраняется — глобального scope нет.
        bad = await c.put("/api/streamer-attitude/2", json={"channel": "", "attitude": "adore"})
        assert bad.status_code == 400


async def test_prompt_line_in_profile_block(tmp_db, disable_auth):
    """Строка отношения попадает в блок «О стримере»; neutral — нет."""
    from app.database import init_db
    await init_db()
    await _seed_accounts("botA")
    from app.streamer_attitude import set_attitude
    await set_attitude(1, "ch1", "adore")
    from app.server import chat_analyzer
    block = await chat_analyzer._load_streamer_profile_block(1, "ch1")
    assert "ОБОЖАЕШЬ" in block
    # neutral не добавляет строку: сброс + пустой профиль → пустой блок
    await set_attitude(1, "ch1", "neutral")
    block2 = await chat_analyzer._load_streamer_profile_block(1, "ch1")
    assert block2 == ""


def test_ui_attitude_rows_and_i18n():
    """P8-C3: UI перенесён в карточку бота (вкладка «Роль»), i18n ×3."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    bots_tpl = (root / "templates" / "partials" / "bots.html").read_text()
    assert 'id="botAttitudeBox"' in bots_tpl
    js = _panel_js.panel_js()
    for key in ("streamer.attitude_title", "streamer.attitude_hint",
                "streamer.attitude_adore", "streamer.attitude_watching",
                "streamer.attitude_saved"):
        assert js.count(f"'{key}'") >= 3, key
    assert "loadBotAttitude" in js  # новый лоадер в 03_bots.js
    # включение роутера в server.py
    srv = (root / "app" / "server.py").read_text()
    assert "_streamer_attitude.router" in srv
