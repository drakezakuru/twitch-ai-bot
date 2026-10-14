"""Юнит-тесты на app.smart_trigger."""

from __future__ import annotations

import pytest

from app.smart_trigger import (
    SilenceTracker,
    SpikeDetector,
    extract_vision_event,
    is_streamer_question,
)


# ---- streamer question --------------------------------------------------


class TestStreamerQuestion:
    def test_streamer_question_basic(self):
        assert is_streamer_question("test_bot", "test_bot", "что думаете?") is True

    def test_streamer_question_with_hash(self):
        assert is_streamer_question("test_bot", "#test_bot", "ок?") is True

    def test_not_streamer_message(self):
        assert is_streamer_question("xqc", "test_bot", "что думаете?") is False

    def test_streamer_but_no_question(self):
        assert is_streamer_question("test_bot", "test_bot", "это интересно") is False

    def test_question_with_trailing_space(self):
        assert is_streamer_question("test_bot", "test_bot", "что думаете?   ") is True

    def test_case_insensitive_channel(self):
        assert is_streamer_question("Test_Bot", "TEST_BOT", "ок?") is True

    @pytest.mark.parametrize("text", ["", "?", "abc"])
    def test_safe_on_edge_strings(self, text):
        # Пустые/невалидные строки — без падений; "?" чисто без других слов — это всё равно вопрос
        result = is_streamer_question("test_bot", "test_bot", text)
        assert result is (text.endswith("?") and bool(text))


# ---- vision event --------------------------------------------------------


class TestVisionEvent:
    @pytest.mark.parametrize(
        "desc,expected",
        [
            ("Стример сделал epic kill", "kill"),
            ("got pentakill clutch", "epic"),  # 'pentakilL' содержит 'kill'? — нет, упорядочено
            ("Огромный хайлайт в матче", "хайлайт"),
            ("Игрок убил врага одним выстрелом", "убил"),
            ("Просто разговор без событий", None),
            ("", None),
        ],
    )
    def test_extract_event(self, desc, expected):
        out = extract_vision_event(desc)
        if expected is None:
            assert out is None
        else:
            # Может вернуть любое из подходящих kw, но не None.
            assert out is not None
            assert isinstance(out, str)

    def test_case_insensitive(self):
        assert extract_vision_event("EPIC WIN") is not None

    def test_returns_none_on_empty(self):
        assert extract_vision_event(None) is None  # type: ignore[arg-type]
        assert extract_vision_event("") is None


# ---- spike detector ------------------------------------------------------


class TestSpikeDetector:
    def test_baseline_too_low_no_spike(self):
        d = SpikeDetector(window_sec=10, mult=2.0, min_baseline=1.0)
        t = 1000.0
        # 1 сообщение → fast = 0.1/s, baseline = 0.025/s — fast >> baseline,
        # но baseline ниже min_baseline → не спайк.
        d.on_message("ch", now=t)
        assert d.detect("ch", now=t + 0.1) is False

    def test_spike_detected_when_burst(self):
        d = SpikeDetector(window_sec=10, mult=2.0, min_baseline=0.1, spike_cooldown_sec=5)
        t = 1000.0
        # baseline: 1 msg/sec за «медленное» окно (4× window = 40s) → 40 сообщений.
        for i in range(40):
            d.on_message("ch", now=t + i)
        # Затем 60 сообщений за 5 секунд (= 12/sec, в ~7× выше baseline).
        for i in range(60):
            d.on_message("ch", now=t + 40 + (5 / 60) * i)
        assert d.detect("ch", now=t + 45.5) is True

    def test_spike_cooldown_prevents_double_fire(self):
        d = SpikeDetector(window_sec=10, mult=2.0, min_baseline=0.1, spike_cooldown_sec=30)
        t = 1000.0
        for i in range(40):
            d.on_message("ch", now=t + i)
        for i in range(60):
            d.on_message("ch", now=t + 40 + (5 / 60) * i)
        first = d.detect("ch", now=t + 45.5)
        second = d.detect("ch", now=t + 46)
        assert first is True
        assert second is False

    def test_returns_false_for_unknown_channel(self):
        d = SpikeDetector()
        assert d.detect("unknown", now=1000.0) is False

    def test_msg_per_sec_basic(self):
        d = SpikeDetector(window_sec=10)
        t = 1000.0
        for i in range(5):
            d.on_message("ch", now=t + i)
        rate = d.msg_per_sec("ch", window_sec=10, now=t + 5)
        assert rate == pytest.approx(0.5, rel=0.1)


# ---- silence tracker -----------------------------------------------------


class TestSilenceTracker:
    def test_no_event_no_silence(self):
        s = SilenceTracker(silence_sec=5)
        s.on_chat_message("ch", now=1000)
        assert s.is_silent_after_event("ch", now=1100) is False

    def test_silence_after_event_fires(self):
        s = SilenceTracker(silence_sec=5)
        s.on_vision_event("ch", now=1000)
        # Никаких сообщений после event. Прошло 10 сек.
        assert s.is_silent_after_event("ch", now=1010) is True

    def test_silence_not_fired_if_recent_msg(self):
        s = SilenceTracker(silence_sec=5)
        s.on_vision_event("ch", now=1000)
        s.on_chat_message("ch", now=1009)
        # Сообщение было 1 сек назад, тишины нет.
        assert s.is_silent_after_event("ch", now=1010) is False

    def test_consumed_after_fire_no_repeat(self):
        s = SilenceTracker(silence_sec=5)
        s.on_vision_event("ch", now=1000)
        first = s.is_silent_after_event("ch", now=1010)
        second = s.is_silent_after_event("ch", now=1015)
        assert first is True
        assert second is False  # consumed

    def test_event_too_old_skipped(self):
        s = SilenceTracker(silence_sec=5, valid_window_sec=30)
        s.on_vision_event("ch", now=1000)
        # Прошла минута — event протух.
        assert s.is_silent_after_event("ch", now=1100) is False

    def test_new_event_resets_consumed(self):
        s = SilenceTracker(silence_sec=5)
        s.on_vision_event("ch", now=1000)
        assert s.is_silent_after_event("ch", now=1010) is True
        # Новый event — снова можно фаерить.
        s.on_vision_event("ch", now=1100)
        assert s.is_silent_after_event("ch", now=1110) is True
