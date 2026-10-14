"""DEF-02: ошибки провайдера Режиссёра больше не глотаются — причина в логе.

Приёмка 11–12.09: «generate_plan не-ok → без лога причины». Теперь:
  - исключение провайдера логируется с типом И сообщением (не только тип);
  - не-ok ответ провайдера логируется с payload ошибки (result.error);
  - пауза по ai_errors пишет последнюю ошибку в audit (details.last_error).
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from app import director


def _adapter(ai_service) -> director.ProductionDirectorAdapter:
    bots = SimpleNamespace(get_status=lambda _: {"connected": True}, get_all_statuses=lambda: {})
    return director.ProductionDirectorAdapter(ai_service, SimpleNamespace(), bots)


def _config() -> dict:
    return {"provider": "fake", "model": "m", "temperature": 0.4, "max_tokens": 64}


def _snapshot() -> dict:
    return {"scope": {"channel_id": "channel"}}


@pytest.mark.asyncio
async def test_provider_exception_logs_the_reason_not_just_type(caplog):
    class Boom:
        async def generate_text_with(self, *args, **kwargs):
            raise RuntimeError("quota exceeded for provider fake")

    adapter = _adapter(Boom())
    with caplog.at_level("WARNING", logger="app.director"):
        with pytest.raises(ValueError, match="director_ai_request_failed"):
            await adapter.generate_plan(_config(), "prompt", _snapshot())

    provider_logs = [r for r in caplog.records if "Director provider request failed" in r.message]
    assert provider_logs, "ошибка провайдера должна попадать в лог"
    assert "RuntimeError" in provider_logs[0].getMessage()
    assert "quota exceeded" in provider_logs[0].getMessage(), "причина, а не только тип"


@pytest.mark.asyncio
async def test_provider_not_ok_response_logs_error_payload(caplog):
    class NotOk:
        async def generate_text_with(self, *args, **kwargs):
            return {"ok": False, "error": {"code": 429, "message": "rate limited"}}

    adapter = _adapter(NotOk())
    with caplog.at_level("WARNING", logger="app.director"):
        with pytest.raises(ValueError, match="director_ai_request_failed"):
            await adapter.generate_plan(_config(), "prompt", _snapshot())

    logs = [r for r in caplog.records if "Director provider returned not-ok" in r.message]
    assert logs, "не-ok провайдера обязан попадать в лог с причиной"
    payload = json.loads(logs[0].getMessage().split("not-ok:", 1)[1])
    assert payload["error"] == {"code": 429, "message": "rate limited"}


@pytest.mark.asyncio
async def test_ai_errors_pause_audit_carries_last_error(caplog, tmp_db, monkeypatch):
    """Проброс причины в audit: при паузе по ai_errors details.last_error заполнен."""
    async def boom(request):
        raise RuntimeError("provider exploded: bad key")

    audited: list[tuple] = []

    async def fake_audit(channel, action, status, session_id=None, details=None):
        audited.append((channel, action, status, details))

    async def fake_transition(channel, action, reason=None):
        return {"ok": True}

    from app import database as db_mod
    await db_mod.init_db()
    scheduler = director.DirectorScheduler(clock=lambda: 1000.0)
    scheduler.configure(planner=boom)
    # без start(): раскладываем вручную то, что start() делает для анализа
    scheduler._analysis_lock = asyncio.Lock()
    scheduler._last_analysis = {}
    scheduler._ai_errors = {}
    monkeypatch.setattr(director, "audit", fake_audit)
    monkeypatch.setattr(director, "transition", fake_transition)
    monkeypatch.setattr(scheduler, "submit_response", lambda *a, **k: (_ for _ in ()).throw(AssertionError("не должен вызываться")))
    # конфиг нужен только ради ai_error_limit при паузе
    monkeypatch.setattr(director, "_config", lambda channel: [{"ai_error_limit": 1}])

    with caplog.at_level("WARNING", logger="app.director"):
        await scheduler._run_analysis("channel", {"ai_error_limit": 1, "analysis_interval_sec": 15, "priority_cooldown_sec": 15})

    paused = [a for a in audited if a[1] == "ai_errors"]
    assert paused, "пауза по ai_errors должна аудироваться"
    assert "provider exploded" in (paused[0][3] or {}).get("last_error", ""), \
        "причина последней ошибки пробрасывается в audit"
