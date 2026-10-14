"""О7 PLAN.md (§24 ОСТАТОК): админ-формы для §24-виджетов — сверка списка.

wa2-секция (сделана 30.08) покрывает lower-third, mascot, anime-runner,
chat-roulette, recent-events, stream-session (+ latest-event-card бонусом).
Тест фиксирует, что все API форм отвечают и карточка с формами есть.
combo-counter выведен из эксплуатации (owner survey Q14) — его формы и API нет.
"""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest
from httpx import AsyncClient, ASGITransport


async def _client():
    from app.database import init_db
    from app.widgets import admin_router, public_router, ensure_widgets_schema
    from app import database as db_mod
    if db_mod._shared_db is not None:
        try:
            await db_mod._shared_db.close()
        except Exception:
            pass
        db_mod._shared_db = None
    await init_db()
    await ensure_widgets_schema()
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(public_router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_section24_admin_endpoints_alive(tmp_db, disable_auth):
    """GET-эндпоинты конфигов всех 7 §24-виджетов отвечают 200 с ok/config."""
    endpoints = (
        "/api/widgets/lower-third",
        "/api/widgets/mascot",
        "/api/widgets/anime-runner",
        "/api/widgets/chat-roulette",
        "/api/widgets/recent-events",
        "/api/widgets/stream-session",
        "/api/widgets/latest-event-card",
    )
    async with await _client() as c:
        for url in endpoints:
            r = await c.get(url)
            assert r.status_code == 200, f"{url} -> {r.status_code}"
            assert isinstance(r.json(), (dict, list)), url


def test_section24_panel_card_exists():
    """Карточка «Прочие виджеты — контент» содержит все 7 форм + примеры."""
    root = Path(__file__).resolve().parents[1]
    tpl = (root / "templates" / "partials" / "widgets.html").read_text()
    for marker in ("wa2LtName", "wa2MascotPreset", "wa2ArHair", "wa2RlParticipants",
                   "wa2ReUser", "wa2SessionStart"):
        assert marker in tpl, marker
    assert "Прочие виджеты" in tpl


def test_section24_panel_runtime_behavior():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for panel behavior tests")
    subprocess.run(
        [node, "--test", "tests/widget_admin_forms_ui.test.js"],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
    )
