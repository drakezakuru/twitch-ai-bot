"""Тесты v10.2: адаптивный кулдаун, эмоциональный детектор настроения чата."""
from __future__ import annotations

import pytest

from app.chat_analyzer import ChatAnalyzer
from app import stream_vision


class _FakeAI:
    async def generate_text(self, *a, **kw):
        return "ok"

    async def analyze_image(self, *a, **kw):
        return ""


async def _no_send(*args, **kwargs):
    return True


@pytest.fixture(autouse=True)
def reset_activity():
    stream_vision.chat_activity = stream_vision.ChatActivityTracker()
    yield


def _new_analyzer() -> ChatAnalyzer:
    return ChatAnalyzer(ai=_FakeAI(), send_fn=_no_send)


# ──────────────── adaptive cooldown ────────────────

def test_adaptive_cooldown_zero_activity_returns_min():
    a = _new_analyzer()
    a.update_settings(1, {"adaptive_cooldown": True, "adaptive_cooldown_min": 5, "adaptive_cooldown_max": 50})
    assert a._effective_cooldown(1, "ch") == 5.0


def test_adaptive_cooldown_busy_activity_returns_max():
    a = _new_analyzer()
    a.update_settings(1, {"adaptive_cooldown": True, "adaptive_cooldown_min": 5, "adaptive_cooldown_max": 50})
    for _ in range(35):
        stream_vision.chat_activity.on_message("ch")
    assert a._effective_cooldown(1, "ch") == 50.0


def test_adaptive_cooldown_disabled_returns_base():
    a = _new_analyzer()
    a.update_settings(1, {"adaptive_cooldown": False, "cooldown": 17})
    for _ in range(50):
        stream_vision.chat_activity.on_message("ch")
    assert a._effective_cooldown(1, "ch") == 17.0


def test_adaptive_cooldown_medium_interpolates():
    a = _new_analyzer()
    a.update_settings(1, {"adaptive_cooldown": True, "adaptive_cooldown_min": 10, "adaptive_cooldown_max": 50})
    for _ in range(15):
        stream_vision.chat_activity.on_message("ch")
    val = a._effective_cooldown(1, "ch")
    assert 25 <= val <= 35  # ratio ~0.5 → ~30


# ──────────────── mood detector ────────────────

def test_mood_detector_few_messages_returns_empty():
    a = _new_analyzer()
    a._chat_buffer["1:ch"] = [{"author": "u", "text": "привет", "ts": 0}]
    assert a._detect_mood(1, "ch") == ""


def test_mood_detector_positive_chat():
    a = _new_analyzer()
    a._chat_buffer["1:ch"] = [
        {"author": f"u{i}", "text": txt, "ts": 0}
        for i, txt in enumerate([
            "ору", "круто", "огонь", "нравится игра", "kek",
            "лол", "топ", "ничего сказать", "норм день", "ну",
        ])
    ]
    mood = a._detect_mood(1, "ch")
    assert "позитив" in mood or "весёлый" in mood


def test_mood_detector_toxic_chat():
    a = _new_analyzer()
    a._chat_buffer["1:ch"] = [
        {"author": f"u{i}", "text": txt, "ts": 0}
        for i, txt in enumerate([
            "трэш игра", "тупой стример", "слив команды", "ужас вообще",
            "трэш", "отстой", "тупой", "слив", "ужас",
        ])
    ]
    mood = a._detect_mood(1, "ch")
    assert "токсич" in mood or "агресс" in mood


def test_mood_detector_neutral_chat():
    a = _new_analyzer()
    a._chat_buffer["1:ch"] = [
        {"author": f"u{i}", "text": txt, "ts": 0}
        for i, txt in enumerate([
            "что будем играть", "сегодня день недели", "когда стрим начнётся",
            "видишь скилл там был", "пора кушать видимо",
        ])
    ]
    mood = a._detect_mood(1, "ch")
    assert mood in ("нейтральный", "нейтрально-позитивный")


# ──────────────── default settings ────────────────

def test_default_settings_have_v102_keys():
    a = _new_analyzer()
    s = a.get_settings(1)
    assert s["adaptive_cooldown"] is True
    assert s["use_topic_summary"] is True
    assert s["use_mood_detector"] is True
    assert s["use_topic_cooldown"] is True
    assert s["topic_cooldown_sec"] == 300
    assert s["temperature"] == 0.4
