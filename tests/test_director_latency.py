"""Тесты для индикатора задержки ИИ (Latency / TTFT) в Режиссёре."""
from __future__ import annotations

import pytest

from app import director
from app.database import init_db

pytestmark = pytest.mark.asyncio


async def test_director_record_and_get_latency():
    """Проверка записи и чтения latency по каналам."""
    director.record_ai_latency("Test_Channel", 1234.5)
    assert director.get_ai_latency("test_channel") == 1234.5
    assert director.get_ai_latency("other_channel") is None


async def test_director_get_status_includes_latency(tmp_db):
    """get_status возвращает ai_latency_ms."""
    await init_db()
    director.record_ai_latency("testchan", 850.0)
    status = await director.get_status("testchan")
    assert status["ok"] is True
    assert status["ai_latency_ms"] == 850.0
