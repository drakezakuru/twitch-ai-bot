"""Tests for v10.4.7 Wave 4.6 — live-detection mimicry."""

from app.live_mimicry import (
    LiveProfile,
    LiveProfileCollector,
    _caps_ratio,
    _emoji_count,
    _p90,
    adjust_delay_for_mimicry,
    mimicry_hint_block,
)


def test_caps_ratio_empty():
    assert _caps_ratio("") == 0.0


def test_caps_ratio_all_upper():
    assert _caps_ratio("HELLO") == 1.0


def test_caps_ratio_mixed():
    assert _caps_ratio("HeLLo") == 0.6


def test_emoji_count():
    assert _emoji_count("ahaha 😂😂😂") == 3
    assert _emoji_count("no emoji") == 0


def test_p90():
    assert _p90([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]) >= 9


def test_collector_empty_returns_default():
    c = LiveProfileCollector()
    p = c.compute()
    assert p.samples == 0


def test_collector_collects():
    c = LiveProfileCollector()
    for i in range(20):
        c.feed(f"msg {i} 😂", now=1000.0 + i * 5)
    p = c.compute()
    assert p.samples == 20
    assert p.emoji_per_msg > 0
    assert p.interval_sec_median > 0


def test_collector_window_limit():
    c = LiveProfileCollector(window=10)
    c.msgs = type(c.msgs)(maxlen=10)
    for i in range(50):
        c.feed(f"msg {i}", now=1000.0 + i)
    assert len(c.msgs) == 10


def test_mimicry_block_skipped_for_few_samples():
    p = LiveProfile(samples=5)
    assert mimicry_hint_block(p) == ""


def test_mimicry_block_short_messages():
    p = LiveProfile(median_len=10, emoji_per_msg=0.0, caps_ratio=0.01, samples=20)
    block = mimicry_hint_block(p)
    assert "коротк" in block.lower()
    assert "не используй эмодзи" in block.lower()


def test_mimicry_block_emoji_heavy():
    p = LiveProfile(median_len=20, emoji_per_msg=1.5, caps_ratio=0.02, samples=20)
    block = mimicry_hint_block(p)
    assert "эмодзи" in block.lower()


def test_mimicry_block_caps_heavy():
    p = LiveProfile(median_len=20, emoji_per_msg=0.1, caps_ratio=0.5, samples=20)
    block = mimicry_hint_block(p)
    assert "caps" in block.lower()


def test_adjust_delay_no_samples_returns_base():
    p = LiveProfile(samples=5)
    m, s = adjust_delay_for_mimicry(p, base_mean=60.0, base_sigma=15.0)
    assert m == 60.0
    assert s == 15.0


def test_adjust_delay_with_samples():
    p = LiveProfile(samples=50, interval_sec_median=5.0, interval_sec_p90=15.0)
    m, s = adjust_delay_for_mimicry(p, base_mean=60.0, base_sigma=15.0)
    # быстрый чат → mean меньше базового
    assert m < 60.0
    assert s > 0


def test_adjust_delay_bounds():
    p = LiveProfile(samples=50, interval_sec_median=0.5, interval_sec_p90=200)
    m, s = adjust_delay_for_mimicry(p)
    assert m >= 15.0  # не падает ниже минимума
    assert s <= 45.0
