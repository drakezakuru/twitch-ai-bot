"""§5 WIDGETS_PLAN: виджеты отдаются из папки widgets/<name>/index.html.

Проверяем:
1. _widget_html() читает файл с диска, подключает shared assets и кэширует по mtime.
2. Редактирование файла на лету меняет ответ роута (без рестарта).
3. Каждый /widget/* роут отдаёт содержимое ровно своего файла
   (с учётом .replace() подстановок — проверяем уникальные маркеры файлов).
4. Отсутствующий виджет даёт понятную страницу ошибки, а не 500.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


def _widget_file(name: str):
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    return root / "widgets" / name / "index.html"


async def _client():
    from app.database import init_db
    from app.widgets import admin_router, public_router, ensure_widgets_schema
    await init_db()
    await ensure_widgets_schema()
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(public_router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


WIDGET_ROUTES = [
    ("/widget/goals", "goals"),
    ("/widget/now-playing", "now-playing"),
    ("/widget/sub-goal", "sub-goal"),
    ("/widget/schedule", "schedule"),
    ("/widget/uptime", "stream-session"),
    ("/widget/follower-ticker", "follower-ticker"),
    ("/widget/lower-third", "lower-third"),
    ("/widget/mascot", "mascot"),
    ("/widget/anime-runner", "anime-runner"),
    ("/widget/chat-highlight", "chat-highlight"),
    ("/widget/chat-roulette", "chat-roulette"),
    ("/widget/song-request", "song-request"),
    ("/widget/countdown", "countdown"),
    ("/widget/donation-challenge", "donation-challenge"),
    ("/widget/animated-bg", "animated-bg"),
]


@pytest.mark.parametrize("route,folder", WIDGET_ROUTES)
async def test_widget_route_serves_folder_file(tmp_db, disable_auth, route, folder):
    from app.widgets import _widget_html

    async with await _client() as c:
        r = await c.get(route)
    assert r.status_code == 200, route
    body = r.text
    runtime_html = _widget_html(folder)
    # Route-level placeholder substitutions are allowed; the probe must come
    # from the loader output after shared assets/layout metadata are injected.
    probe = next(
        (line for line in runtime_html.split("\n")
         if len(line.strip()) > 30 and "__" not in line and "<title>" not in line),
        None,
    )
    assert probe is not None, folder
    assert probe in body, f"{route}: marker from {folder}/index.html not in response"


async def test_widget_html_loader_live_reload(tmp_db, disable_auth):
    from app.widgets import _WIDGET_BOUNDED_ROOTS, _widget_html, _widget_cache
    path = _widget_file("goals")
    original = path.read_text(encoding="utf-8")
    try:
        v1 = _widget_html("goals")
        assert original.split("</head>", 1)[1] in v1
        assert 'data-widget-layout="bounded"' in v1
        assert f'data-widget-root="{_WIDGET_BOUNDED_ROOTS["goals"]}"' in v1
        assert "/widget/_shared/theme.css?v=" in v1
        assert "/widget/_shared/appearance.js?v=" in v1
        # Меняем файл на диске → loader должен отдать новое содержимое
        path.write_text(original.replace("<title>", "<title data-x>"), encoding="utf-8")
        v2 = _widget_html("goals")
        assert v2 != v1
        assert "data-x" in v2
        # Кэш работает: повторное чтение без изменения mtime возвращает то же
        assert _widget_html("goals") == v2
    finally:
        path.write_text(original, encoding="utf-8")
        _widget_cache.clear()


async def test_widget_missing_file_returns_error_page(tmp_db, disable_auth, monkeypatch):
    import app.widgets as w
    async with await _client() as c:
        r = await c.get("/widget/goals")  # существует
        assert r.status_code == 200
        html = w._widget_html("definitely-not-a-widget")
        assert "not found" in html
        assert "definitely-not-a-widget" in html
