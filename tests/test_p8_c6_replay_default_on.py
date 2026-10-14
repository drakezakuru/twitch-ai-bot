"""P8-C6: Replay-автозапись — дефолт ВКЛ + честная подпись.

Бэкенд (bot_manager) уже пишет replay при старте бота по умолчанию (default=True),
но GET-ручка отдавала enabled=False на чистой базе — тумблер врал.
Подпись карточки теперь честно объясняет, что и сколько пишется.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio


async def _client():
    from app.database import init_db
    from app.routes import router
    await init_db()
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_replay_auto_record_default_enabled(tmp_db, disable_auth):
    """Чистая база → enabled=True (совпадает с поведением bot_manager)."""
    async with await _client() as c:
        r = await c.get("/api/settings/replay-auto-record")
    assert r.status_code == 200
    assert r.json()["enabled"] is True


async def test_replay_auto_record_toggle_persists(tmp_db, disable_auth):
    async with await _client() as c:
        r = await c.put("/api/settings/replay-auto-record", json={"enabled": False})
        assert r.json()["enabled"] is False
        r = await c.get("/api/settings/replay-auto-record")
        assert r.json()["enabled"] is False
        r = await c.put("/api/settings/replay-auto-record", json={"enabled": True})
        r = await c.get("/api/settings/replay-auto-record")
        assert r.json()["enabled"] is True


def test_replay_hint_is_honest():
    """Подпись объясняет: что пишется, сколько весит, как отключить.

    Q16 F5: карточка переехала в карточку бота (bots.html), глобальная убрана.
    """
    html = (__import__("pathlib").Path(__file__).parent.parent /
            "templates" / "partials" / "bots.html").read_text(encoding="utf-8")
    assert "Записывает чат и ответы бота этой сессии в архив" in html
    assert 'id="botReplayAutoRecord"' in html
    # что пишется и сколько весит — в подсказке карточки бота (Q16 F5)
    assert "Записывает чат и ответы бота этой сессии в архив" in html
