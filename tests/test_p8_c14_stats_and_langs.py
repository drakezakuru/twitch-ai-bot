"""P8-C14: статистика и языки.

1) «Статистика бота» — починена вместе с A2 (init-цепочка + автозагрузка
   списка ботов); здесь фиксируем, что ручка /stats жива и UI-цепочка полна;
2) i18n по select («Все боты» вместо хардкода);
3) карточка «Растущие и угасающие темы» удалена (тренды — мёртвый груз);
4) «Оценки ответов» — per-bot (селект бота + account_id в /stats).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).parent.parent


def test_trending_card_removed():
    html = (ROOT / "templates" / "partials" / "analytics.html").read_text(encoding="utf-8")
    assert 'id="trendingList"' not in html
    assert 'id="trendingPeriod"' not in html
    js = (ROOT / "static" / "app" / "07_widgets.js").read_text(encoding="utf-8")
    assert "async function loadTrendingWords" not in js


def test_all_bots_option_i18n():
    js = (ROOT / "static" / "app" / "04_chat_settings.js").read_text(encoding="utf-8")
    assert "Всі боти" not in js, "хардкод «Всі боти» остался"
    assert "analytics.all_bots" in js
    app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert app_js.count("'analytics.all_bots':") >= 3


def test_feedback_per_bot_ui():
    html = (ROOT / "templates" / "partials" / "analytics.html").read_text(encoding="utf-8")
    assert 'id="feedbackBotFilter"' in html, "нет селекта бота в «Оценках ответов»"
    js = (ROOT / "static" / "app" / "08_providers_moderation.js").read_text(encoding="utf-8")
    m = re.search(r"async function loadFeedbackSummary\(\) \{.*?\n\}", js, re.S)
    assert m and "feedbackBotFilter" in m.group(0) and "account_id" in m.group(0)


@pytest.fixture
def app(disable_auth, tmp_db):
    application = FastAPI()
    application.include_router(__import__("app.routes_ai_feedback", fromlist=["router"]).router)
    return application


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_feedback_stats_per_bot_filter(tmp_db, disable_auth):
    """per-bot фильтр: факты одного бота не попадают в сводку другого."""
    from app.database import init_db, get_db
    await init_db()
    db = await get_db()
    try:
        await db.execute("INSERT OR IGNORE INTO accounts (id, nickname, token) VALUES (1,'b1','t'), (2,'b2','t')")
        await db.execute(
            "INSERT INTO ai_feedback (account_id, channel, event_type, message, rating) VALUES "
            "(1, '#c', 'reply', 'msg1', 1), (1, '#c', 'reply', 'msg2', -1), (2, '#c', 'reply', 'msg3', 1)")
        await db.commit()
    finally:
        await db.close()

    from app.routes_ai_feedback import get_ai_feedback_stats
    all_stats = await get_ai_feedback_stats(account_id=0)
    assert all_stats["total"] == 3 and all_stats["positive"] == 2 and all_stats["negative"] == 1
    bot1 = await get_ai_feedback_stats(account_id=1)
    assert bot1["total"] == 2 and bot1["positive"] == 1 and bot1["negative"] == 1
    bot2 = await get_ai_feedback_stats(account_id=2)
    assert bot2["total"] == 1 and bot2["positive"] == 1 and bot2["negative"] == 0


def test_bot_stats_endpoint_and_ui_chain_intact():
    """(1) «Статистика бота»: ручка есть, init-цепочка вызывает лоадеры."""
    routes = (ROOT / "app" / "routes.py").read_text(encoding="utf-8")
    assert '@router.get("/api/accounts/{account_id}/stats")' in routes
    app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "loadPerBotStatsSelect()" in app_js
    wjs = (ROOT / "static" / "app" / "07_widgets.js").read_text(encoding="utf-8")
    assert "loadBotsList()" in wjs.split("async function loadPerBotStatsSelect")[1].split("}")[0], \
        "селект ботов не заполняется при первом открытии"
