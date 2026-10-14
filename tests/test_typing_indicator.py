"""Typing Indicator выведен из эксплуатации (owner survey Q26: Д).

Виджет показывал пиллу «мод/VIP/broadcaster только что написал». Владелец
решил удалить его, поэтому вместе с карточкой убран и broadcast-хук
typing_indicator из chat_analyzer.on_message. Публичный URL сохранён тёмной
заглушкой ради уже настроенных OBS-сцен — тесты ниже это и фиксируют.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio

ROOT = Path(__file__).resolve().parents[1]


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


async def test_retired_url_still_answers_with_dark_notice(tmp_db, disable_auth):
    """OBS-сцена со старым источником не должна получить 404."""
    async with await _client() as c:
        r = await c.get("/widget/typing-indicator")
        assert r.status_code == 200
        assert "Typing indicator" in r.text
        assert "#0f0f1a" in r.text, "заглушка должна быть тёмной"
        assert "ti-pill" not in r.text, "старая разметка виджета вернулась"


def test_broadcast_hook_removed_from_chat_analyzer():
    src = (ROOT / "app" / "chat_analyzer.py").read_text(encoding="utf-8")
    assert "typing_indicator" not in src, "broadcast-хук удалённого виджета вернулся"


def test_widget_folder_and_card_removed():
    assert not (ROOT / "widgets" / "typing-indicator").exists()
    from app.widget_inventory import RETIRED_WIDGETS, WIDGET_INVENTORY
    assert "typing-indicator" not in {item.slug for item in WIDGET_INVENTORY}
    assert "/widget/typing-indicator" in RETIRED_WIDGETS
