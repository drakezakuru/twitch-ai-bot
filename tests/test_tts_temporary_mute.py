"""Тесты режима временного глушения озвучки (TTS Mute / Cinematic Mute, Task 6)."""
from __future__ import annotations

import time
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from app import tts_mute_state as MuteState

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def _cleanup():
    MuteState.reset_state()
    yield
    MuteState.reset_state()


def _client() -> AsyncClient:
    from app.routes import router
    import app.routes_tts_config  # noqa: F401
    from app.director_routes import router as director_router
    fastapi_app = FastAPI()
    fastapi_app.include_router(router)
    fastapi_app.include_router(director_router)
    return AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test")


async def test_mute_state_logic():
    # Изначально не заглушено
    muted, sec = MuteState.is_tts_muted("mychan")
    assert not muted
    assert sec == 0

    # Глобальное глушение на 5 минут
    res = MuteState.set_tts_mute(minutes=5)
    assert res["ok"] is True
    assert res["muted"] is True
    assert 295 <= res["remaining_sec"] <= 300

    muted, sec = MuteState.is_tts_muted("anychan")
    assert muted is True
    assert sec > 0

    # Снятие глобального глушения
    MuteState.clear_tts_mute()
    muted, sec = MuteState.is_tts_muted("anychan")
    assert not muted

    # Per-channel глушение
    MuteState.set_tts_mute("channel_a", minutes=1)
    muted_a, _ = MuteState.is_tts_muted("channel_a")
    muted_b, _ = MuteState.is_tts_muted("channel_b")
    assert muted_a is True
    assert muted_b is False

    MuteState.clear_tts_mute("channel_a")
    assert MuteState.is_tts_muted("channel_a")[0] is False


async def test_tts_mute_api_endpoints():
    async with _client() as client:
        # 1. Проверяем статус
        resp = await client.get("/api/tts/mute/status?channel=streamer")
        assert resp.status_code == 200
        assert resp.json()["muted"] is False

        # 2. Включаем глушение на 5 минут
        resp = await client.post("/api/tts/mute", json={"channel": "streamer", "minutes": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["muted"] is True

        # 3. Проверяем статус снова
        resp = await client.get("/api/tts/mute/status?channel=streamer")
        assert resp.json()["muted"] is True
        assert resp.json()["remaining_sec"] > 0

        # 4. Снимаем глушение
        resp = await client.post("/api/tts/unmute", json={"channel": "streamer"})
        assert resp.status_code == 200
        assert resp.json()["muted"] is False

        resp = await client.get("/api/tts/mute/status?channel=streamer")
        assert resp.json()["muted"] is False


async def test_director_quick_action_tts_mute():
    async with _client() as client:
        # Режиссёр: mute_tts_5m
        resp = await client.post("/api/director/quick-action?action=mute_tts_5m&channel=testchan")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["action"] == "mute_tts"
        assert resp.json()["muted"] is True

        # Статус
        resp = await client.get("/api/director/quick-action?action=tts_mute_status&channel=testchan")
        assert resp.status_code == 200
        assert resp.json()["muted"] is True

        # Снятие: unmute_tts
        resp = await client.post("/api/director/quick-action?action=unmute_tts&channel=testchan")
        assert resp.status_code == 200
        assert resp.json()["muted"] is False


async def test_authorize_tts_respects_mute(tmp_db):
    from app import tts_voice_policy as policy
    from app import database
    await database.init_db()

    # Включаем глушение
    MuteState.set_tts_mute("mychan", minutes=5)

    decision = await policy.authorize_tts(
        account_id=1, channel="mychan", source="bot_reply",
        actor_role="bot", actor_id="1", text="Привет чат!",
    )
    assert decision["ok"] is False
    assert decision["reason"] == "tts_temporary_muted"

    # Снимаем глушение
    MuteState.clear_tts_mute("mychan")
    decision2 = await policy.authorize_tts(
        account_id=1, channel="mychan", source="bot_reply",
        actor_role="bot", actor_id="1", text="Привет чат!",
    )
    # По умолчанию для не настроенной политики возвращает legacy True
    assert decision2["ok"] is True
