"""Tests for app.vad_silence."""

from __future__ import annotations

import random

import pytest

from app.vad_silence import (
    DEFAULT_AFK_MESSAGES,
    SilenceWatcher,
    detect_silence,
    has_speech_in_segment,
    pick_afk_message,
    silence_duration_sec,
)


def test_silence_duration_zero_for_never_speech():
    assert silence_duration_sec(0.0) == 0.0


def test_silence_duration_basic():
    assert silence_duration_sec(900.0, now=1000.0) == 100.0


def test_silence_duration_negative_clamped():
    assert silence_duration_sec(2000.0, now=1000.0) == 0.0


def test_detect_silence_under_threshold():
    assert not detect_silence(900.0, threshold_sec=300, now=1000.0)


def test_detect_silence_over_threshold():
    assert detect_silence(500.0, threshold_sec=300, now=1000.0)


def test_has_speech_in_dict_segment():
    assert has_speech_in_segment({"text": "hello world"})


def test_has_speech_empty():
    assert not has_speech_in_segment({"text": ""})
    assert not has_speech_in_segment({"text": "   "})


def test_has_speech_only_punctuation():
    assert not has_speech_in_segment({"text": "..."})


def test_has_speech_string_segment():
    assert has_speech_in_segment("speak")


def test_has_speech_min_chars():
    assert not has_speech_in_segment({"text": "a"}, min_chars=3)
    assert has_speech_in_segment({"text": "abc"}, min_chars=3)


def test_pick_afk_message_uses_default():
    rng = random.Random(0)
    msg = pick_afk_message(rng=rng)
    assert msg in DEFAULT_AFK_MESSAGES


def test_pick_afk_message_custom():
    rng = random.Random(0)
    custom = ["a", "b", "c"]
    msg = pick_afk_message(custom, rng=rng)
    assert msg in custom


def test_pick_afk_message_empty_fallback():
    msg = pick_afk_message([])
    assert msg == "afk stream"


def test_silence_watcher_initial_state():
    w = SilenceWatcher(threshold_sec=300, cooldown_sec=600)
    # Без речи — should_emit_afk = False (мы ещё не знаем, что стрим вообще шёл)
    assert not w.should_emit_afk(now=1000.0)


def test_silence_watcher_feed_segment_with_speech():
    w = SilenceWatcher()
    assert w.feed_segment({"text": "hello there"}, now=1000.0)
    assert w.last_speech_ts == 1000.0


def test_silence_watcher_feed_segment_no_speech():
    w = SilenceWatcher()
    assert not w.feed_segment({"text": ""}, now=1000.0)
    assert w.last_speech_ts == 0.0


def test_silence_watcher_emit_afk_after_threshold():
    w = SilenceWatcher(threshold_sec=300, cooldown_sec=600)
    w.mark_speech(now=1000.0)
    # 200 сек — не достаточно
    assert not w.should_emit_afk(now=1200.0)
    # 350 сек — да
    assert w.should_emit_afk(now=1350.0)


def test_silence_watcher_cooldown_prevents_double_emit():
    w = SilenceWatcher(threshold_sec=300, cooldown_sec=600)
    w.mark_speech(now=1000.0)
    assert w.should_emit_afk(now=1400.0)
    w.mark_emitted(now=1400.0)
    # 500 сек cooldown ещё не вышли
    assert not w.should_emit_afk(now=1900.0)
    # после cooldown — снова можно
    assert w.should_emit_afk(now=2050.0)


def test_silence_watcher_mark_emitted_counts():
    w = SilenceWatcher()
    w.mark_speech(now=1000.0)
    w.mark_emitted(now=1400.0)
    w.mark_emitted(now=2050.0)
    assert w.total_silence_events == 2


def test_silence_watcher_reset_speech():
    w = SilenceWatcher()
    w.mark_speech(now=1000.0)
    w.reset_speech(now=2000.0)
    assert w.last_speech_ts == 2000.0


def test_silence_watcher_snapshot_keys():
    w = SilenceWatcher(threshold_sec=300)
    w.mark_speech(now=1000.0)
    snap = w.snapshot(now=1200.0)
    assert "last_speech_ts" in snap
    assert "silence_sec" in snap
    assert "silent" in snap
    assert snap["silent"] is False
    assert snap["silence_sec"] == 200.0


def test_silence_watcher_threshold_at_300_user_spec():
    """Согласно текущему ТЗ — порог 300 сек, реакция 'afk stream'."""
    w = SilenceWatcher(threshold_sec=300, cooldown_sec=600)
    w.mark_speech(now=1000.0)
    # 299 — нет
    assert not w.should_emit_afk(now=1299.0)
    # 300 — да
    assert w.should_emit_afk(now=1300.0)
    # выбираем сообщение из дефолтов
    msg = pick_afk_message(rng=random.Random(0))
    assert msg in DEFAULT_AFK_MESSAGES
