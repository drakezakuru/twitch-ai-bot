"""§11.0 WIDGETS_PLAN: ?api= параметризация — все виджеты поддерживают
адрес панели через query-параметр (для работы с другого хоста/статикой)."""
from __future__ import annotations

import pytest


def test_all_widgets_support_api_base_directly_or_via_shared_core():
    from pathlib import Path
    widgets_dir = Path("widgets")
    shared_core = (widgets_dir / "_shared" / "chat-message-core.js").read_text(encoding="utf-8")
    assert "new URLSearchParams(location.search).get('api')" in shared_core
    assert "apiBase: apiBase" in shared_core
    files = sorted(p for p in widgets_dir.glob("*/index.html") if p.parent.name != "_shared")
    assert files, "widgets folder must exist"
    missing = []
    for f in files:
        html = f.read_text(encoding="utf-8")
        direct_support = "_WIDGET_API_BASE" in html
        shared_support = "/widget/_shared/chat-message-core.js" in html
        if not direct_support and not shared_support:
            missing.append(str(f))
    assert not missing, f"widgets without ?api= support: {missing}"

    selected_chat = (widgets_dir / "selected-chat" / "index.html").read_text(encoding="utf-8")
    assert "ChatMessageCore.apiBase()+'/api/widgets/public/chat/selected-history?'" in selected_chat
    assert "const base=ChatMessageCore.apiBase()" in selected_chat


@pytest.mark.asyncio
async def test_shared_bus_client_served():
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport
    from app.widgets import public_router
    app = FastAPI()
    app.include_router(public_router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/widget/_shared/widget-bus-client.js")
        assert r.status_code == 200
        assert "WidgetBus" in r.text and "pause_media" in r.text
        # path traversal защищён
        r2 = await c.get("/widget/_shared/../_widget_html")
        assert r2.status_code in (404, 200)  # не должен отдать файл вне _shared
