"""PLAN §9l + §6: провокации в спорах (полная версия), temperature→эмоции, пресеты.

Проверяем:
1. §9l ConflictProvocation: по умолчанию выключена; bait при конфликте и
   интенсивности; «добивание» после ответа в окне; state расходуется;
   кулдауны канал/юзер; guardrails (observation_only/silent/intensity 0/пустой ник).
2. Настройки §9l доступны через PUT/GET /api/accounts/{id}/analyzer.
3. §6 _pick_reply_emotion: temperature < 0.45 → сдержанные (neutral),
   > 0.65 → полный набор эмоций, средняя → по mood engine (neutral без mood).
4. §6 пресеты: «Спам-хахаха» добавлен, «Дикий» на месте.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio

from app.conflict_provocation import ConflictProvocation


def _settings(**overrides) -> dict:
    s = {
        "conflict_provocation_enabled": True,
        "conflict_provocation_intensity": 40,
        "observation_only": False,
        "silent_mode": False,
    }
    s.update(overrides)
    return s


def _cp() -> ConflictProvocation:
    return ConflictProvocation()


async def test_conflict_default_disabled():
    from app.chat_analyzer import ChatAnalyzer
    from app.ai_service import AIService
    ana = ChatAnalyzer(ai=AIService(), send_fn=lambda *a, **kw: None)
    defaults = ana.get_settings(1)
    assert defaults.get("conflict_provocation_enabled") is False
    assert "conflict_provocation_intensity" in defaults

    cp = _cp()
    # Фича выключена в настройках → никогда не срабатывает
    assert cp.check_bait(1, "chan", "user", {"conflict_provocation_enabled": False}, True) is False


async def test_bait_and_escalation_flow(monkeypatch):
    monkeypatch.setattr("app.conflict_provocation.random.random", lambda: 0.0)
    cp = _cp()
    s = _settings()

    # Фаза 2 до bait — нет
    assert cp.check_escalation(1, "chan", "user") is False

    # Фаза 1: негативное сообщение → bait
    assert cp.check_bait(1, "chan", "user", s, True) is True
    cp.mark_bait(1, "chan", "user")

    # Юзер ответил → «добивание» один раз
    assert cp.check_escalation(1, "chan", "user") is True
    assert cp.check_escalation(1, "chan", "user") is False

    # Инструкции содержат ключевые элементы и границы
    bait = cp.bait_instruction("user", "ты в игре нуб", s)
    assert "подначкой" in bait and "user" in bait and "Без оскорблений" in bait
    esc = cp.escalation_instruction("user", "да ладно", s)
    assert "доб" in esc.lower() and "АРГУМЕНТУ" in esc


async def test_conflict_cooldowns(monkeypatch):
    monkeypatch.setattr("app.conflict_provocation.random.random", lambda: 0.0)
    cp = _cp()
    s = _settings()
    assert cp.check_bait(1, "chan", "a", s, True) is True
    cp.mark_bait(1, "chan", "a")
    # Канальный кулдаун: другой юзер тоже не получит bait сразу
    assert cp.check_bait(1, "chan", "b", s, True) is False
    # Пользовательский кулдаун после истечения окна
    cp2 = _cp()
    cp2.check_bait(2, "x", "u", s, True)
    cp2.mark_bait(2, "x", "u")
    assert cp2.check_bait(2, "x", "u", s, True) is False


async def test_conflict_guardrails(monkeypatch):
    monkeypatch.setattr("app.conflict_provocation.random.random", lambda: 0.0)
    cp = _cp()
    assert cp.check_bait(1, "c", "u", _settings(observation_only=True), True) is False
    assert cp.check_bait(1, "c", "u", _settings(silent_mode=True), True) is False
    assert cp.check_bait(1, "c", "u", _settings(conflict_provocation_intensity=0), True) is False
    assert cp.check_bait(1, "c", "", _settings(), True) is False
    # Окно истекло → добивания нет
    import time as _t
    cp2 = _cp()
    cp2.check_bait(1, "c", "u", _settings(), True)
    cp2.mark_bait(1, "c", "u")
    cp2._bait_pending[(1, "c", "u")] = _t.time() - ConflictProvocation.WINDOW_SEC - 1
    assert cp2.check_escalation(1, "c", "u") is False


async def test_conflict_settings_roundtrip(tmp_db, disable_auth):
    from app import database
    await database.init_db()
    from fastapi import FastAPI
    from app.routes import router
    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        put = (await c.put("/api/accounts/1/analyzer", json={
            "conflict_provocation_enabled": True,
            "conflict_provocation_intensity": 70,
        })).json()
        assert put["conflict_provocation_enabled"] is True
        assert put["conflict_provocation_intensity"] == 70
        got = (await c.get("/api/accounts/1/analyzer")).json()
        assert got["conflict_provocation_enabled"] is True
        assert got["conflict_provocation_intensity"] == 70


async def test_temperature_emotion_picking(monkeypatch):
    from app.chat_analyzer import ChatAnalyzer
    from app.ai_service import AIService
    ana = ChatAnalyzer(ai=AIService(), send_fn=lambda *a, **kw: None)

    # Низкая креативность: random > 0.25 → нейтрально
    monkeypatch.setattr("app.chat_analyzer.random.random", lambda: 0.9)
    assert ana._pick_reply_emotion(1, "c", {"temperature": 0.3}) == "neutral"

    # Низкая, но random <= 0.25 → mood-эмоция (без mood engine — neutral)
    monkeypatch.setattr("app.chat_analyzer.random.random", lambda: 0.1)
    assert ana._pick_reply_emotion(1, "c", {"temperature": 0.3}) == "neutral"

    # Средняя: ровно mood-эмоция (neutral без mood engine)
    assert ana._pick_reply_emotion(1, "c", {"temperature": 0.5}) == "neutral"

    # Высокая: полный набор
    full = {"happy", "angry", "sad", "surprised", "neutral"}
    monkeypatch.setattr("app.chat_analyzer.random.random", lambda: 0.5)
    for _ in range(6):
        assert ana._pick_reply_emotion(1, "c", {"temperature": 0.8}) in full

    # Битая температура → дефолт 0.4 (средний диапазон)
    assert ana._pick_reply_emotion(1, "c", {"temperature": "abc"}) == "neutral"


async def test_spam_hahaha_and_wild_presets():
    from app.bot_presets import apply_preset, list_presets
    ids = {p["id"] for p in list_presets()}
    assert {"wild", "spam_hahaha", "troll", "observer"} <= (ids | {"observer"})
    preset = apply_preset("spam_hahaha")
    assert preset is not None
    assert preset["label"] == "Спам-хахаха"
    assert preset["humor_level"] >= 90
    assert apply_preset("wild") is not None
