"""Global visual settings shared by the chat-reader and raw TTS widgets."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio


async def _client() -> AsyncClient:
    from app.database import init_db
    from app.routes import ws_router
    from app.widgets import admin_router, ensure_widgets_schema, public_router

    await init_db()
    await ensure_widgets_schema()
    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(public_router)
    app.include_router(ws_router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_design_defaults_preserve_legacy_appearance(tmp_db, disable_auth):
    async with await _client() as client:
        chat = (await client.get("/api/widgets/design/chat-reader")).json()["settings"]
        tts = (await client.get("/api/widgets/design/tts-raw")).json()["settings"]

    assert chat == {
        "theme": "dark", "accent": "#22D3EE", "bg": "#0F0F19",
        "opacity": 0.9, "radius": 14, "font": "sans", "size": 20,
        "scale": 1.0, "pos": "bc", "shadow": 1, "hold": 8, "maxw": 640,
    }
    assert tts["opacity"] == 0.65
    assert tts["accent"] == "#00FF7F"
    assert tts["showstatus"] == 1


async def test_design_put_normalizes_and_persists(tmp_db, disable_auth):
    async with await _client() as client:
        response = await client.put("/api/widgets/design/chat-reader", json={
            "accent": "#aabbcc", "bg": "not-a-color", "opacity": 2,
            "radius": -5, "font": "invalid", "size": 200, "scale": 0,
            "pos": "invalid", "shadow": "0", "hold": 999, "maxw": 10,
        })
        assert response.status_code == 200
        settings = response.json()["settings"]
        loaded = (await client.get("/api/widgets/design/chat-reader")).json()["settings"]

    assert settings["accent"] == "#AABBCC"
    assert settings["bg"] == "#0F0F19"
    assert settings["opacity"] == 1.0
    assert settings["radius"] == 0
    assert settings["font"] == "sans"
    assert settings["size"] == 48
    assert settings["scale"] == 0.5
    assert settings["pos"] == "bc"
    assert settings["shadow"] == 0
    assert settings["hold"] == 60
    assert settings["maxw"] == 240
    assert loaded == settings


async def test_design_unknown_widget_is_rejected(tmp_db, disable_auth):
    async with await _client() as client:
        assert (await client.get("/api/widgets/design/other")).status_code == 404
        assert (await client.put("/api/widgets/design/other", json={})).status_code == 404


async def test_url_values_override_saved_design_safely(tmp_db, disable_auth):
    async with await _client() as client:
        await client.put("/api/widgets/design/tts-raw", json={
            "accent": "#112233", "opacity": 0.4, "showstatus": 1,
        })
        response = await client.get(
            "/obs/tts?channel=demo&accent=%23fedcba&opacity=bad&showstatus=0"
        )

    assert response.status_code == 200
    assert "#FEDCBA" in response.text
    assert "rgba(0,0,0,0.4)" in response.text
    assert "__DESIGN_" not in response.text


async def test_inventory_tts_preview_renders_representative_state(tmp_db, disable_auth):
    from app.widget_inventory import WIDGET_INVENTORY

    preview_url = next(item.preview_url for item in WIDGET_INVENTORY if item.slug == "tts")
    async with await _client() as client:
        response = await client.get(preview_url)

    assert response.status_code == 200
    assert "new URLSearchParams(location.search).get('preview') === '1'" in response.text
    assert "DemoViewer: пример озвучиваемого сообщения" in response.text
    assert "document.body.style.background = '#0f0f1a'" in response.text


async def test_theme_and_malformed_url_values_cannot_inject_markup(tmp_db, disable_auth):
    async with await _client() as client:
        await client.put("/api/widgets/design/chat-reader", json={
            "theme": "neon", "accent": "#d946ef", "bg": "#090014",
        })
        response = await client.get("/widget/chat-reader", params={
            "theme": "dark", "accent": "</style><script>alert(1)</script>",
            "font": "sans;position:fixed", "pos": "tr<script>",
        })

    assert response.status_code == 200
    assert "alert(1)" not in response.text
    assert "sans;position:fixed" not in response.text
    assert "#22D3EE" in response.text
    assert "rgba(15,15,25,0.9)" in response.text

