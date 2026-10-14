"""v10.4.1: тесты на пресеты «режима бота» и last-observation эндпоинты."""
from __future__ import annotations

import sys
import time
from types import ModuleType

import pytest

from app.stream_vision import StreamVisionManager


def _build_app():
    from fastapi import FastAPI
    from app.routes import router
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture()
def stub_server():
    """Заглушка app.server с настоящими экземплярами analyzer/stream_vision."""
    from app.ai_service import AIService
    from app.chat_analyzer import ChatAnalyzer

    saved = sys.modules.get("app.server")
    fake = ModuleType("app.server")
    fake.ai_service = AIService()
    fake.stream_vision_manager = StreamVisionManager(fake.ai_service)
    fake.chat_analyzer = ChatAnalyzer(ai=fake.ai_service, send_fn=lambda *a, **kw: None)
    fake.bot_manager = None
    fake.eventsub_manager = None
    sys.modules["app.server"] = fake
    try:
        yield fake
    finally:
        if saved is not None:
            sys.modules["app.server"] = saved
        else:
            sys.modules.pop("app.server", None)


# ─────────────── A) Пресеты «режима бота» ───────────────


@pytest.mark.asyncio
async def test_v1041_list_presets(tmp_db, disable_auth, stub_server):
    from httpx import ASGITransport, AsyncClient
    from app import database

    await database.init_db()
    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        r = await client.get("/api/analyzer-presets")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        ids = {p["id"] for p in data["presets"]}
        assert ids == {"chat_only", "realtime_stream", "full_context"}


@pytest.mark.asyncio
async def test_v1041_apply_realtime_stream_preset(tmp_db, disable_auth, stub_server):
    from httpx import ASGITransport, AsyncClient
    from app import database

    await database.init_db()
    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        r = await client.post("/api/accounts/7/analyzer-presets/realtime_stream")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        # Analyzer-настройки совпадают с пресетом
        assert data["analyzer"]["context_source_chat"] is False
        assert data["analyzer"]["context_source_stream"] is True
        assert data["analyzer"]["context_source_streamer"] is True
        # Stream Vision реально обновился
        sv = stub_server.stream_vision_manager
        assert sv.cfg.frame_interval_min == 3
        assert sv.cfg.quality == "360p"
        assert sv.cfg.pipelining is True
        assert data["stream_vision_changed"]["frame_interval_min"] == 3


@pytest.mark.asyncio
async def test_v1041_apply_chat_only_preset(tmp_db, disable_auth, stub_server):
    from httpx import ASGITransport, AsyncClient
    from app import database

    await database.init_db()
    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        r = await client.post("/api/accounts/8/analyzer-presets/chat_only")
        d = r.json()
        assert d["ok"] is True
        assert d["analyzer"]["context_source_chat"] is True
        assert d["analyzer"]["context_source_stream"] is False
        assert d["analyzer"]["context_source_streamer"] is False
        assert d["stream_vision_changed"] == {}  # chat_only не трогает SV


@pytest.mark.asyncio
async def test_v1041_apply_full_context_preset(tmp_db, disable_auth, stub_server):
    from httpx import ASGITransport, AsyncClient
    from app import database

    await database.init_db()
    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        r = await client.post("/api/accounts/9/analyzer-presets/full_context")
        d = r.json()
        assert d["ok"] is True
        assert d["analyzer"]["context_source_chat"] is True
        assert d["analyzer"]["context_source_stream"] is True
        assert d["analyzer"]["context_source_streamer"] is True
        assert d["analyzer"]["chat_window_size"] == 50


@pytest.mark.asyncio
async def test_v1041_unknown_preset(tmp_db, disable_auth, stub_server):
    from httpx import ASGITransport, AsyncClient
    from app import database

    await database.init_db()
    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        r = await client.post("/api/accounts/9/analyzer-presets/nope")
        d = r.json()
        assert d["ok"] is False
        assert "unknown preset" in (d.get("error") or "")


# ─────────────── B) Last-observation эндпоинты ───────────────


@pytest.mark.asyncio
async def test_v1041_last_observation_per_account(tmp_db, disable_auth, stub_server):
    from httpx import ASGITransport, AsyncClient
    from app import database

    await database.init_db()
    sv = stub_server.stream_vision_manager
    sv._store_observation(5, "ninja", description="играет в Apex", transcript="привет всем")

    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        r = await client.get("/api/stream-vision/last-observation/5/ninja")
        d = r.json()
        assert d["ok"] is True
        assert d["observation"]["description"] == "играет в Apex"
        assert d["observation"]["transcript"] == "привет всем"
        assert isinstance(d["observation"]["age_sec"], int)


@pytest.mark.asyncio
async def test_v1041_last_observation_by_channel_picks_freshest(tmp_db, disable_auth, stub_server):
    from httpx import ASGITransport, AsyncClient
    from app import database

    await database.init_db()
    sv = stub_server.stream_vision_manager
    sv._store_observation(1, "shroud", description="старое", transcript="")
    # подложим более свежее от другого аккаунта
    sv._last_observation[(1, "shroud")]["at"] = time.time() - 60
    sv._store_observation(2, "shroud", description="свежее", transcript="новый звук")

    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        r = await client.get("/api/stream-vision/last-observation-by-channel/shroud")
        d = r.json()
        assert d["ok"] is True
        assert d["observation"]["description"] == "свежее"
        assert d["account_id"] == 2


@pytest.mark.asyncio
async def test_v1041_last_observation_by_channel_no_data(tmp_db, disable_auth, stub_server):
    from httpx import ASGITransport, AsyncClient
    from app import database

    await database.init_db()
    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        r = await client.get("/api/stream-vision/last-observation-by-channel/empty_chan")
        d = r.json()
        assert d["ok"] is True
        assert d["observation"] is None


@pytest.mark.asyncio
async def test_v1041_last_observation_by_channel_age_cutoff(tmp_db, disable_auth, stub_server):
    from httpx import ASGITransport, AsyncClient
    from app import database

    await database.init_db()
    sv = stub_server.stream_vision_manager
    sv._store_observation(3, "stale_chan", description="устарело")
    # искусственно состарим запись
    sv._last_observation[(3, "stale_chan")]["at"] = time.time() - 600

    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        r = await client.get("/api/stream-vision/last-observation-by-channel/stale_chan?max_age_sec=60")
        d = r.json()
        assert d["ok"] is True
        assert d["observation"] is None  # за пределами max_age_sec
