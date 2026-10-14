"""Тесты для эндпоинта мини-досье зрителя (viewer dossier)."""
import pytest
from httpx import ASGITransport, AsyncClient

from app.database import get_db
from app.server import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.asyncio
async def test_viewer_dossier_empty_args():
    """Проверка валидации обязательных параметров канала и зрителя."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/api/viewers/_/%20/dossier")
        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is False


@pytest.mark.asyncio
async def test_viewer_dossier_full_aggregation():
    """Проверка полного сбора досье: сообщения, память, защита, модерация."""
    from app.database import init_db
    await init_db()
    db = await get_db()
    try:
        # 1. Добавляем аккаунт бота
        await db.execute("INSERT OR REPLACE INTO accounts (id, nickname, token) VALUES (99, 'TestBot', 'oauth:fake')")

        # 2. Сообщения в чате
        await db.execute(
            "INSERT INTO chat_log (account_id, channel, author, message, timestamp) "
            "VALUES (99, 'dossierchan', 'coolviewer', 'Привет чат!', '2026-10-01 10:00:00')"
        )
        await db.execute(
            "INSERT INTO chat_log (account_id, channel, author, message, timestamp) "
            "VALUES (99, 'dossierchan', 'coolviewer', 'Как дела?', '2026-10-01 10:05:00')"
        )

        # 3. Белый список
        await db.execute(
            "INSERT OR REPLACE INTO moderation_protected (account_id, channel, username, note) "
            "VALUES (99, 'dossierchan', 'coolviewer', 'VIP зритель')"
        )

        # 4. Модерация в журнале
        await db.execute(
            "INSERT INTO moderation_journal (account_id, channel, username, category, severity, rule_name, action, duration_sec, status, detail) "
            "VALUES (99, 'dossierchan', 'coolviewer', 'caps', 1, 'CAPS_RULE', 'timeout', 60, 'applied', 'Слишком много капса')"
        )

        # 5. Память бота (user_memory)
        await db.execute(
            "INSERT OR REPLACE INTO user_memory (account_id, username, facts, msg_count, last_seen) "
            "VALUES (99, 'coolviewer', '[\"Любит кофе\", \"Играет в доту\"]', 2, '2026-10-01 10:05:00')"
        )
        await db.commit()
    finally:
        await db.close()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/api/viewers/dossierchan/coolviewer/dossier")
        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is True
        assert data["channel"] == "dossierchan"
        assert data["username"] == "coolviewer"

        # Статистика
        stats = data["stats"]
        assert stats["total_messages"] >= 2
        assert stats["first_seen"] is not None
        assert len(stats["recent_messages"]) >= 2
        assert stats["recent_messages"][0]["text"] == "Как дела?"

        # Статус
        status = data["status"]
        assert status["is_protected"] is True
        assert status["protected_note"] == "VIP зритель"
        assert status["last_punish"] is not None
        assert status["last_punish"]["action"] == "timeout"
        assert status["last_punish"]["duration_sec"] == 60

        # Модерация
        assert len(data["moderation_history"]) >= 1
        assert data["moderation_history"][0]["rule_name"] == "CAPS_RULE"

        # Память
        assert len(data["bot_memories"]) >= 1
        facts = data["bot_memories"][0]["facts"]
        assert "Любит кофе" in facts
        assert "Играет в доту" in facts
