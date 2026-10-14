from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_disclosure_setting_round_trip(tmp_db, disable_auth):
    from app import database
    from app.media_share_routes import router

    await database.init_db()
    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/media-share/disclosure")).json() == {
            "acknowledged": False,
        }
        db = await database.get_db()
        try:
            cursor = await db.execute(
                "SELECT value FROM settings WHERE key = ?",
                ("media_share_youtube_disclosure_acknowledged",),
            )
            assert await cursor.fetchone() is None
        finally:
            await db.close()
        accepted = await client.put(
            "/api/media-share/disclosure", json={"acknowledged": True},
        )
        assert accepted.json() == {"ok": True, "acknowledged": True}
        assert (await client.get("/api/media-share/disclosure")).json()["acknowledged"] is True

        reset = await client.put(
            "/api/media-share/disclosure", json={"acknowledged": False},
        )
        assert reset.json() == {"ok": True, "acknowledged": False}


def test_media_share_panel_uses_persisted_disclosure_and_three_locales():
    template = (ROOT / "templates/partials/widgets.html").read_text(encoding="utf-8")
    base = (ROOT / "templates/base.html").read_text(encoding="utf-8")
    settings = (ROOT / "templates/partials/settings.html").read_text(encoding="utf-8")
    script = (ROOT / "static/app/07_widgets.js").read_text(encoding="utf-8")

    # Q16 F2: вместо модалки — постоянная подсказка в форме медиа-шары
    assert "waUseMediaShare" not in template
    assert "mediaShareDisclosureModal" not in base
    assert "mediaShareDisclosureModal" not in template
    assert "waShowMediaDisclosureAgain" not in settings
    assert "widgets.media_share_hint" in template
    assert "'/api/media-share/disclosure'" not in script
    for lang in ("ru", "en", "ua"):
        assert f"Object.assign(LANGS.{lang}, {{" in script
    assert script.count("'widgets.media_share_hint'") == 3
    for key in (
        "media.disclosure_title",
        "media.disclosure_body",
        "media.disclosure_accept",
        "media.settings_title",
    ):
        assert script.count(f"'{key}'") == 0


def test_media_share_widget_loads_tested_core_and_names_failure_states():
    html = (ROOT / "widgets/media-share/index.html").read_text(encoding="utf-8")
    assert "/widget/_shared/media-share-core.js" in html
    assert "onAutoplayBlocked" in html
    assert "youtube_api" in html
    assert "embed_error" in html
    assert "queue_offline" in html
    assert "bus_reconnecting" in html
    assert "const CHANNEL = qs.get('channel') || '';" in html
