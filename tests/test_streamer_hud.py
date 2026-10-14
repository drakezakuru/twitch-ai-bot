import pytest
from httpx import AsyncClient, ASGITransport

from app.server import app, chat_analyzer, bot_manager


@pytest.mark.asyncio
async def test_streamer_hud_widget_html():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/widget/streamer-hud")
        assert resp.status_code == 200
        html = resp.text
        assert "СУФЛЁР" in html
        assert "hud" in html
        assert "/api/widgets/streamer-hud/state" in html


@pytest.mark.asyncio
async def test_streamer_hud_preview_state():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/widgets/streamer-hud/state?preview=1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert len(data["questions"]) >= 1
        assert len(data["topics"]) >= 1
        assert len(data["notes"]) >= 1
        assert "silence_sec" in data
        assert "chat_speed_cpm" in data


@pytest.mark.asyncio
async def test_streamer_hud_notes_and_dismiss():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Добавляем заметку
        resp = await client.post("/api/widgets/streamer-hud/note", json={
            "text": "Тестовая заметка для стрима",
            "channel": "testhudchan",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        note_id = data["note"]["id"]

        # 2. Проверяем наличие заметки в state
        resp = await client.get("/api/widgets/streamer-hud/state?channel=testhudchan")
        assert resp.status_code == 200
        st = resp.json()
        assert any(n["id"] == note_id for n in st["notes"])

        # 3. Списываем заметку (dismiss)
        resp = await client.post("/api/widgets/streamer-hud/dismiss", json={
            "id": note_id,
            "type": "note",
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # 4. Проверяем, что заметка исчезла
        resp = await client.get("/api/widgets/streamer-hud/state?channel=testhudchan")
        st = resp.json()
        assert not any(n["id"] == note_id for n in st["notes"])


@pytest.mark.asyncio
async def test_streamer_hud_topic_rotation():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/widgets/streamer-hud/topic/new", json={
            "channel": "testhudchan",
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert "index" in resp.json()
