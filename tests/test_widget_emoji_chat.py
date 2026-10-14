"""§9.2 WIDGETS_PLAN: Emoji Chat виджет — роут отдаёт самостоятельный файл,
эмодзи сохраняются, ники раскрашиваются, параметры через query-string."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_emoji_chat_route_serves_widget(tmp_db):
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport
    from app.widgets import public_router
    app = FastAPI()
    app.include_router(public_router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/widget/emoji-chat")
        assert r.status_code == 200
        html = r.text
        # ключевые маркеры самодостаточного виджета
        assert "nickColor" in html            # цветные ники
        assert "type !== 'chat'" in html      # слушает живой чат по WS
        assert "location.search" in html      # параметры из query-string
        assert "/api/" not in html.split("const API")[1].split(";")[0]  # api из ?api=


async def test_emoji_chat_theme_is_substituted_by_route(tmp_db):
    """ТРЕК 4: `?theme=` обязан доезжать до разметки как CSS-класс.

    Баг, ради которого написан тест (найден обходом превью 04.09): роут не
    подставлял `__THEME__`, а JS его не читал — в OBS уезжал литерал
    `class="list __THEME__"`, и темы light/neon/fire/glass не работали вовсе.
    """
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport
    from app.widgets import public_router
    app = FastAPI()
    app.include_router(public_router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        for theme in ("dark", "light", "neon", "fire", "glass"):
            r = await c.get("/widget/emoji-chat", params={"theme": theme})
            assert r.status_code == 200
            assert f'class="list {theme}"' in r.text, f"тема {theme} не подставлена"
            assert "__THEME__" not in r.text

        # Неизвестная тема не попадает в разметку — иначе это HTML-инъекция.
        r = await c.get("/widget/emoji-chat", params={"theme": '"><script>x</script>'})
        assert r.status_code == 200
        assert "<script>x</script>" not in r.text
        assert 'class="list dark"' in r.text
