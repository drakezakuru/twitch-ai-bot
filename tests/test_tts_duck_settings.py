"""Тесты для настроек авто-приглушения TTS (Ducking & Речь стримера)."""
import pytest
from httpx import ASGITransport, AsyncClient

from app.database import get_db, init_db
from app.server import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.asyncio
async def test_tts_duck_settings_endpoints():
    """Проверка GET, PUT и duck-test для настроек ducking."""
    await init_db()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. GET duck-settings
        res = await ac.get("/api/tts/duck-settings")
        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is True
        assert "settings" in data
        assert "streamer_duck_volume" in data
        assert "streamer_duck_recovery_ms" in data

        settings = data["settings"]
        kinds = [s["event_kind"] for s in settings]
        assert "subscribe" in kinds
        assert "cheer" in kinds
        assert "raid" in kinds
        assert "streamer_speech" in kinds

        # 2. PUT duck-settings
        update_payload = {
            "settings": [
                {"event_kind": "subscribe", "enabled": 1, "duration_ms": 12000},
                {"event_kind": "streamer_speech", "enabled": 1, "duration_ms": 2500},
            ],
            "streamer_duck_volume": 25,
            "streamer_duck_recovery_ms": 2000,
        }
        res_put = await ac.put("/api/tts/duck-settings", json=update_payload)
        assert res_put.status_code == 200
        data_put = res_put.json()
        assert data_put["ok"] is True
        assert data_put["streamer_duck_volume"] == 25
        assert data_put["streamer_duck_recovery_ms"] == 2000

        sub_row = next(s for s in data_put["settings"] if s["event_kind"] == "subscribe")
        assert sub_row["duration_ms"] == 12000

        # 3. POST duck-test
        res_test = await ac.post("/api/tts/duck-test", json={"duration_ms": 2000, "channel": "testchan"})
        assert res_test.status_code == 200
        assert res_test.json()["ok"] is True
        assert res_test.json()["duration_ms"] == 2000
