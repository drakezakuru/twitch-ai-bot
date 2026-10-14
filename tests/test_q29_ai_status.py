"""Q29 (DEF-04, `DEC-OWNER-017` п.14): честный трёхсостоянийный AI-статус.

Индикатор AI в панели Режиссёра перестаёт показывать «устарел/нет» в паузах
между планами: состояния working / pause / error. «Ошибка» — только при
реальной ошибке провайдера (сессия на паузе по ai_errors, где audit хранит
last_error из DEF-02). health.ai остаётся bool для обратной совместимости.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.director import _ai_health_state

pytestmark = pytest.mark.asyncio

SESSION = (Path(__file__).resolve().parents[1] / "static/app/20_director.js").read_text(encoding="utf-8")


def test_working_when_heartbeat_fresh():
    assert _ai_health_state(True, "live", None) == "working"
    assert _ai_health_state(True, "paused", "ai_errors") == "working"


def test_error_only_for_real_provider_failure():
    assert _ai_health_state(False, "paused", "ai_errors") == "error"


def test_pause_between_plans_is_not_an_error():
    assert _ai_health_state(False, "suggest", None) == "pause"
    assert _ai_health_state(False, "warming", None) == "pause"
    assert _ai_health_state(False, "live", None) == "pause"
    assert _ai_health_state(False, None, None) == "pause"


async def test_status_payload_exposes_ai_state(tmp_db):
    from app.database import init_db
    from app import director

    await init_db()
    status = await director.get_status("test_channel")
    # без конфига канала: ai_state честный None, health пуст
    assert status["ai_state"] is None
    assert status.get("ai_last_error") is None
    assert status["health"] == {}


def test_frontend_renders_three_ai_states():
    assert "function renderDirectorHealth(state)" in SESSION
    assert "state.ai_state" in SESSION and "state.ai_last_error" in SESSION
    assert "status_pause" in SESSION
    # i18n: director.status_pause на трёх языках
    assert SESSION.count("'director.status_pause'") == 3
