import pytest
import httpx
from app.server import app, chat_analyzer

pytestmark = pytest.mark.asyncio


async def test_clear_bot_context():
    # Заполняем буфер сообщений
    chat_analyzer._add_to_buffer(account_id=99, channel="testchan", author="viewer1", text="сообщение 1")
    chat_analyzer._add_to_buffer(account_id=99, channel="testchan", author="viewer2", text="сообщение 2")
    assert len(chat_analyzer._chat_buffer.get("99:testchan", [])) == 2

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/api/accounts/99/clear-context", json={"channel": "testchan"})
        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is True
        assert data["cleared_messages"] == 2

    # Проверяем, что буфер очищен
    assert len(chat_analyzer._chat_buffer.get("99:testchan", [])) == 0
