"""Integration tests for v10.4.5 Wave 2 features.

Не вызываем реальные сетевые/AI ресурсы — проверяем, что:
- настройки появились с правильными дефолтами (все выключены),
- per-account state (mood / friendly trackers) корректно создаётся,
- routes.py регистрирует endpoints.
"""

from __future__ import annotations

import asyncio

import pytest


def test_chat_analyzer_has_wave2_defaults():
    from app.server import chat_analyzer

    s = chat_analyzer.get_settings(account_id=99999)
    # все мастер-тогглы по умолчанию выключены
    assert s["multi_bot_chat_enabled"] is False
    assert s["mood_engine_enabled"] is False
    assert s["game_vocab_enabled"] is False
    assert s["predictions_polls_autovote_enabled"] is False
    assert s["vad_silence_enabled"] is False
    # P8-C2: cross_bot_memory_* удалены (общая память убрана)
    assert "cross_bot_memory_enabled" not in s
    # sane defaults для всех числовых параметров
    assert s["mood_alpha"] == 0.25
    assert s["mood_throttle_threshold"] == -0.5
    assert s["mood_temperature_span"] == 0.3
    assert s["multi_bot_min_delay_sec"] == 15.0
    assert s["multi_bot_max_delay_sec"] == 40.0
    assert s["vad_silence_threshold_sec"] == 300
    assert s["game_vocab_max_words"] == 8
    assert s["predictions_polls_dry_run"] is True


def test_chat_analyzer_get_mood_tracker_lazy_creates():
    from app.server import chat_analyzer

    tr = chat_analyzer._get_mood_tracker(account_id=42, channel="testchan")
    assert tr is not None
    # повторный вызов вернёт тот же экземпляр
    tr2 = chat_analyzer._get_mood_tracker(account_id=42, channel="testchan")
    assert tr is tr2
    assert tr.alpha == 0.25  # дефолт из settings


def test_chat_analyzer_get_friendly_tracker_parses_nicks():
    from app.server import chat_analyzer

    # set custom nicks setting
    chat_analyzer.update_settings(7777, {"multi_bot_friendly_nicks": "botA, botB; botC"})
    tr = chat_analyzer._get_friendly_tracker(account_id=7777, channel="abc", own_nick="me")
    assert tr is not None
    assert "bota" in [n.lower() for n in tr.friendly_nicks]
    assert "botc" in [n.lower() for n in tr.friendly_nicks]
    assert tr.own_nick == "me"


def test_routes_module_exposes_wave2_endpoints():
    from app import routes

    paths = {getattr(r, "path", "") for r in routes.router.routes}
    assert "/api/ab-dashboard" in paths
    # P8-C2: shared-user-facts роуты удалены (общая память убрана)
    assert "/api/shared-user-facts/{username}" not in paths
    assert "/api/shared-user-facts" not in paths
    assert "/api/shared-user-facts/decay" not in paths
    assert "/api/game-vocab/categories" in paths
    assert "/api/game-vocab/detect" in paths
    assert "/api/accounts/{account_id}/mood" in paths
    assert "/api/accounts/{account_id}/multi-bot" in paths
    assert "/api/predictions/decide" in paths
    assert "/api/vad-silence/{account_id}" in paths


def test_eventsub_subscriptions_include_polls_and_predictions():
    from app.eventsub import SUBSCRIPTIONS

    types = {entry[0] for entry in SUBSCRIPTIONS}
    assert "channel.poll.begin" in types
    assert "channel.prediction.begin" in types


def test_predictions_polls_extract_helpers():
    from app.predictions_polls import extract_choices, extract_question

    payload = {
        "subscription": {"type": "channel.poll.begin"},
        "event": {
            "broadcaster_user_login": "abc",
            "title": "Какой стрим лучше?",
            "choices": [
                {"id": "1", "title": "First"},
                {"id": "2", "title": "Second"},
            ],
        },
    }
    assert extract_question(payload) == "Какой стрим лучше?"
    assert extract_choices(payload) == ["First", "Second"]


def test_predictions_polls_format_decision():
    from app.predictions_polls import VoteDecision, format_decision_for_chat

    d = VoteDecision(choice_idx=0, choice_text="First", confidence=0.8, reasoning="r")
    msg = format_decision_for_chat("channel.poll.begin", d, dry_run=True)
    assert "DRY-RUN" in msg
    assert "poll" in msg
    assert "First" in msg
    msg2 = format_decision_for_chat("channel.prediction.begin", d, dry_run=False)
    assert "DRY-RUN" not in msg2
    assert "prediction" in msg2


@pytest.mark.asyncio
async def test_stream_vision_silence_watcher_emits_afk(tmp_path, monkeypatch):
    """Проверяем что StreamVisionManager.feed_silence_watcher эмитит сообщение в chat_cb."""
    from app.stream_vision import StreamVisionConfig, StreamVisionManager
    from app.server import chat_analyzer

    # enable vad on a test account
    acc = 88888
    chat_analyzer.update_settings(
        acc,
        {
            "vad_silence_enabled": True,
            "vad_silence_threshold_sec": 0.1,
            "vad_silence_cooldown_sec": 60,
        },
    )

    sent = []

    async def fake_chat(account_id, channel, text):
        sent.append(text)
        return True

    cfg = StreamVisionConfig()
    sv = StreamVisionManager(ai_service=None, log_cb=None, chat_cb=fake_chat, cfg=cfg)
    # сперва речь чтобы watcher знал baseline
    await sv._feed_silence_watcher(acc, "tester", transcript="hello chat")
    await asyncio.sleep(0.2)
    await sv._feed_silence_watcher(acc, "tester", transcript="")  # threshold passed
    assert sent, "VAD должно было эмитнуть afk-сообщение"
    assert sent[0]  # любое непустое сообщение
