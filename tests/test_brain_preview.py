"""P3 PLAN_PANEL_REWORK: промпт-инспектор /api/brain-preview."""
from __future__ import annotations

import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app import database as db_mod


@pytest_asyncio.fixture(autouse=True)
async def _schema(tmp_db):
    await db_mod.init_db()
    db = await db_mod.get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO accounts (id, nickname, token, bot_role, persona_json) "
            "VALUES (1, 'bot1', 't', 'chatter', ?)",
            (json.dumps({"name": "Тестик", "humor_level": 42, "humor_enabled": True}),),
        )
        await db.commit()
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_brain_preview_shape(tmp_db, disable_auth):
    from fastapi import FastAPI
    from app.brain_preview import router

    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/brain-preview/1")
        assert r.status_code == 200
        d = r.json()
        assert d["ok"] is True and d["account_id"] == 1
        assert d["role"] == "chatter"
        assert d["persona"]["name"] == "Тестик"
        assert d["persona"]["levels"]["humor_level"] == 42
        assert d["lore_count"] == 0
        assert "style_examples" in d["counts"]
        # статический промпт содержит базовую инструкцию рантайма
        assert "зритель" in d["static_prompt"].lower()


@pytest.mark.asyncio
async def test_brain_preview_uses_analyzer_settings_without_patterns(tmp_db, disable_auth):
    from fastapi import FastAPI
    from app.brain_preview import router
    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        d = (await client.get("/api/brain-preview/1")).json()
        assert d["base_system"]
        assert "зритель" in d["static_prompt"].lower()


@pytest.mark.asyncio
async def test_prompt_snapshot_writes_files(tmp_db, disable_auth):
    from fastapi import FastAPI
    from app.brain_preview import router
    from app.bot_dirs import get_bot_dir
    from app.prompt_snapshot import refresh_prompt_snapshot

    res = await refresh_prompt_snapshot(1, "bot1")
    assert res["ok"] is True
    prompts = get_bot_dir(1, "bot1") / "prompts"
    assert (prompts / "system.txt").exists()
    assert (prompts / "personality.txt").exists()
    assert (prompts / "SUMMARY.txt").exists()
    summary = (prompts / "SUMMARY.txt").read_text(encoding="utf-8")
    assert "зритель" in summary  # базовая инструкция попала в статический промпт

    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/api/brain-preview/1/snapshot")
        assert r.status_code == 200
        assert r.json()["ok"] is True
