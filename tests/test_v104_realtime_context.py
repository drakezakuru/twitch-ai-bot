"""v10.4: тесты на near-realtime восприятие, источники контекста и расширение чата."""
from __future__ import annotations

import sys
from types import ModuleType

import pytest

from app import stream_vision
from app.stream_vision import StreamVisionConfig, StreamVisionManager


def _build_app():
    """Cобираем минимальный FastAPI с роутером — без side-effect'ов app.server."""
    from fastapi import FastAPI
    from app.routes import router
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture()
def stub_server():
    """Подменяет ``app.server`` минимальной заглушкой для эндпоинтов routes.py.

    routes.py делает ``from app.server import stream_vision_manager / chat_analyzer``
    в ленивом виде; заглушка предоставляет настоящие экземпляры этих классов,
    чтобы тесты были независимы от реального стартапа сервера.
    """
    from app.ai_service import AIService
    from app.chat_analyzer import ChatAnalyzer

    saved = sys.modules.get("app.server")
    fake = ModuleType("app.server")
    fake.ai_service = AIService()
    fake.stream_vision_manager = StreamVisionManager(fake.ai_service)
    fake.chat_analyzer = ChatAnalyzer(ai=fake.ai_service, send_fn=lambda *a, **kw: None)
    fake.bot_manager = None  # не нужен для наших эндпоинтов
    fake.eventsub_manager = None
    sys.modules["app.server"] = fake
    try:
        yield fake
    finally:
        if saved is not None:
            sys.modules["app.server"] = saved
        else:
            sys.modules.pop("app.server", None)


# ──────────────── 1) Near-realtime: pipelining + новые дефолты ────────────────


def test_v104_default_config_is_realtime():
    """Дефолты v10.4 — для near-realtime."""
    cfg = StreamVisionConfig()
    assert cfg.frame_interval_min == 3, "Min-интервал кадра в v10.4 — 3 секунды"
    assert cfg.audio_interval == 30, "Аудио-окно сократили до 30 секунд"
    assert cfg.quality == "360p", "Качество по умолчанию — 360p"
    assert cfg.pipelining is True, "Pipelining включён по умолчанию"


def test_v104_config_from_env_respects_pipelining_off(monkeypatch):
    monkeypatch.setenv("VISION_PIPELINING", "0")
    cfg = StreamVisionConfig.from_env()
    assert cfg.pipelining is False


def test_v104_config_from_env_min_interval(monkeypatch):
    monkeypatch.setenv("FRAME_INTERVAL_MIN", "5")
    cfg = StreamVisionConfig.from_env()
    assert cfg.frame_interval_min == 5


# ──────────────── 2) last_observation: storage + getter ────────────────


class _FakeAI:
    async def analyze_image(self, *a, **kw):
        return "ok"

    async def generate_text(self, *a, **kw):
        return "ok"


def test_v104_last_observation_round_trip():
    mgr = StreamVisionManager(_FakeAI())
    # сохранили описание
    mgr._store_observation(1, "ch", description="бот видит босса")
    # сохранили транскрипцию (не должна затирать описание)
    mgr._store_observation(1, "ch", transcript="стример смеётся")
    obs = mgr.get_last_observation(1, "ch")
    assert obs is not None
    assert obs["description"] == "бот видит босса"
    assert obs["transcript"] == "стример смеётся"


def test_v104_last_observation_age_cutoff(monkeypatch):
    mgr = StreamVisionManager(_FakeAI())
    mgr._store_observation(1, "ch", description="старое")
    # сделаем наблюдение «старым»
    obs = mgr._last_observation[(1, "ch")]
    obs["at"] -= 600  # 10 минут назад
    # лимит по умолчанию 120с -> ничего не вернёт
    assert mgr.get_last_observation(1, "ch") is None
    # с большим окном вернёт
    assert mgr.get_last_observation(1, "ch", max_age_sec=3600) is not None


def test_v104_module_level_helpers_use_singleton():
    assert stream_vision.get_last_observation(99, "no_such") is None  # без менеджера
    mgr = StreamVisionManager(_FakeAI())
    stream_vision.set_manager(mgr)
    try:
        mgr._store_observation(7, "ch", description="hello")
        obs = stream_vision.get_last_observation(7, "ch")
        assert obs and obs["description"] == "hello"
    finally:
        stream_vision.set_manager(None)


# ──────────────── 3) Chat analyzer: buffer_size, chat_window_size, sources ────────────────


def test_v104_chat_analyzer_default_settings():
    from app.ai_service import AIService
    from app.chat_analyzer import ChatAnalyzer

    ana = ChatAnalyzer(ai=AIService(), send_fn=lambda *a, **kw: None)
    s = ana.get_settings(123)
    assert s["buffer_size"] == 50
    assert s["chat_window_size"] == 30
    assert s["context_source_chat"] is True
    assert s["context_source_stream"] is False
    assert s["context_source_streamer"] is False
    assert s["use_db_chat_fallback"] is True


def test_v104_chat_buffer_respects_larger_size():
    from app.ai_service import AIService
    from app.chat_analyzer import ChatAnalyzer

    ana = ChatAnalyzer(ai=AIService(), send_fn=lambda *a, **kw: None)
    ana.update_settings(1, {"buffer_size": 200})
    for i in range(150):
        ana._add_to_buffer(1, "ch", f"u{i}", f"msg {i}")
    key = ana._buffer_key(1, "ch")
    assert len(ana._chat_buffer[key]) == 150


def test_v104_chat_window_size_limits_context():
    from app.ai_service import AIService
    from app.chat_analyzer import ChatAnalyzer

    ana = ChatAnalyzer(ai=AIService(), send_fn=lambda *a, **kw: None)
    ana.update_settings(1, {"buffer_size": 200, "chat_window_size": 10})
    for i in range(80):
        ana._add_to_buffer(1, "ch", f"u{i}", f"normal message {i}")
    ctx = ana._get_chat_context(1, "ch")
    # В синхронной версии хвост окна = 10 сообщений
    # В формате "Сообщения чата за последнее время — N штук"
    assert "10 штук" in ctx


@pytest.mark.asyncio
async def test_v104_chat_db_fallback_when_buffer_empty(tmp_db):
    from app.ai_service import AIService
    from app.chat_analyzer import ChatAnalyzer
    from app.database import init_db, get_db

    await init_db()
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO accounts (nickname, token) VALUES (?, ?)",
            ("u1", "tok"),
        )
        await db.commit()
        cur = await db.execute("SELECT id FROM accounts LIMIT 1")
        row = await cur.fetchone()
        account_id = row["id"]
        for i in range(20):
            await db.execute(
                "INSERT INTO chat_log (account_id, channel, author, message, is_bot) VALUES (?, ?, ?, ?, 0)",
                (account_id, "ch", f"u{i}", f"hello world {i}"),
            )
        await db.commit()
    finally:
        await db.close()

    ana = ChatAnalyzer(ai=AIService(), send_fn=lambda *a, **kw: None)
    ana.update_settings(account_id, {"chat_window_size": 30, "use_db_chat_fallback": True})
    ctx = await ana._get_chat_context_async(account_id, "ch")
    # Из БД должны были подтянуться 20 сообщений (даже без in-memory буфера).
    assert "hello world" in ctx
    assert "20 штук" in ctx


@pytest.mark.asyncio
async def test_v104_db_fallback_disabled(tmp_db):
    from app.ai_service import AIService
    from app.chat_analyzer import ChatAnalyzer
    from app.database import init_db, get_db

    await init_db()
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO accounts (nickname, token) VALUES (?, ?)",
            ("u2", "tok"),
        )
        await db.commit()
        cur = await db.execute("SELECT id FROM accounts LIMIT 1")
        row = await cur.fetchone()
        account_id = row["id"]
        for i in range(10):
            await db.execute(
                "INSERT INTO chat_log (account_id, channel, author, message, is_bot) VALUES (?, ?, ?, ?, 0)",
                (account_id, "ch", f"u{i}", f"silent {i}"),
            )
        await db.commit()
    finally:
        await db.close()

    ana = ChatAnalyzer(ai=AIService(), send_fn=lambda *a, **kw: None)
    ana.update_settings(account_id, {"chat_window_size": 30, "use_db_chat_fallback": False})
    ctx = await ana._get_chat_context_async(account_id, "ch")
    # Буфер пуст и fallback выключен -> возвращаем пустую строку.
    assert ctx == ""


# ──────────────── 4) Stream Vision config endpoints ────────────────


@pytest.mark.asyncio
async def test_v104_stream_vision_config_endpoint(tmp_db, disable_auth, stub_server):
    """Чтение и запись /api/stream-vision/config обновляют live-конфигурацию."""
    from httpx import ASGITransport, AsyncClient
    from app import database

    await database.init_db()
    sv_mgr = stub_server.stream_vision_manager
    snap = (sv_mgr.cfg.frame_interval_min, sv_mgr.cfg.quality, sv_mgr.cfg.pipelining)
    try:
        async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
            r = await client.get("/api/stream-vision/config")
            assert r.status_code == 200
            assert r.json()["ok"] is True

            r = await client.put(
                "/api/stream-vision/config",
                json={"frame_interval_min": 7, "quality": "480p", "pipelining": False},
            )
            assert r.status_code == 200
            data = r.json()
            assert data["ok"] is True
            assert data["config"]["frame_interval_min"] == 7
            assert data["config"]["quality"] == "480p"
            assert data["config"]["pipelining"] is False

        assert sv_mgr.cfg.frame_interval_min == 7
        assert sv_mgr.cfg.quality == "480p"
        assert sv_mgr.cfg.pipelining is False
    finally:
        (
            sv_mgr.cfg.frame_interval_min,
            sv_mgr.cfg.quality,
            sv_mgr.cfg.pipelining,
        ) = snap


@pytest.mark.asyncio
async def test_v104_stream_vision_config_clamps(tmp_db, disable_auth, stub_server):
    """Глупые значения подрезаются."""
    from httpx import ASGITransport, AsyncClient
    from app import database

    await database.init_db()
    sv_mgr = stub_server.stream_vision_manager
    snap = sv_mgr.cfg.frame_interval_min
    try:
        async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
            r = await client.put("/api/stream-vision/config", json={"frame_interval_min": 99999})
            assert r.json()["config"]["frame_interval_min"] == 60
            r = await client.put("/api/stream-vision/config", json={"frame_interval_min": -5})
            assert r.json()["config"]["frame_interval_min"] == 1
    finally:
        sv_mgr.cfg.frame_interval_min = snap


# ──────────────── 5) PUT /api/accounts/.../analyzer принимает новые поля ────────────────


@pytest.mark.asyncio
async def test_v104_analyzer_settings_persist_new_fields(tmp_db, disable_auth, stub_server):
    from httpx import ASGITransport, AsyncClient
    from app import database

    await database.init_db()
    chat_analyzer = stub_server.chat_analyzer
    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        # account 42 — новый, дефолты должны быть из v10.4
        r = await client.get("/api/accounts/42/analyzer")
        assert r.status_code == 200
        data = r.json()
        assert data["buffer_size"] == 50
        assert data["chat_window_size"] == 30
        assert data["context_source_chat"] is True

        r = await client.put(
            "/api/accounts/42/analyzer",
            json={
                "context_source_chat": False,
                "context_source_stream": True,
                "context_source_streamer": True,
                "chat_window_size": 60,
                "buffer_size": 80,
            },
        )
        assert r.status_code == 200

    s = chat_analyzer.get_settings(42)
    assert s["context_source_chat"] is False
    assert s["context_source_stream"] is True
    assert s["context_source_streamer"] is True
    assert s["chat_window_size"] == 60
    assert s["buffer_size"] == 80
