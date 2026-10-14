import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


async def _client():
    from app.database import init_db
    from app.routes_tts_config import router
    await init_db()
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_tts_test_obs(tmp_db, disable_auth, monkeypatch):
    events = []

    async def fake_broadcast(**kwargs):
        events.append(kwargs)

    from app import tts_engine
    monkeypatch.setattr(tts_engine, "broadcast_tts_event", fake_broadcast)

    async with await _client() as c:
        r = await c.post("/api/accounts/1/tts-test-obs", json={
            "provider": "web_speech",
            "text": "Тестовая реплика в OBS",
            "channel": "mytestchannel",
        })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["broadcasted"] is True
    assert data["channel"] == "mytestchannel"

    assert len(events) == 1
    ev = events[0]
    assert ev["account_id"] == 1
    assert ev["channel"] == "mytestchannel"
    assert ev["text"] == "Тестовая реплика в OBS"
    assert "[OBS Test]" in ev["display_text"]
