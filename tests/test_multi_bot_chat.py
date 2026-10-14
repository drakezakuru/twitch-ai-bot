"""Tests for app.multi_bot_chat."""

from __future__ import annotations

import random

import pytest

from app.multi_bot_chat import (
    FriendlyChatTracker,
    format_friendly_context,
    is_friendly_bot,
    normalize_nick,
    reply_delay_seconds,
    should_reply_to_friendly,
)


class _FixedRng:
    """RNG который возвращает заданные значения."""

    def __init__(self, values):
        self.values = list(values)

    def random(self) -> float:
        return float(self.values.pop(0))

    def uniform(self, a: float, b: float) -> float:
        v = float(self.values.pop(0))
        return a + (b - a) * v


def test_normalize_nick():
    assert normalize_nick("@DevinBot") == "devinbot"
    assert normalize_nick("  USER  ") == "user"
    assert normalize_nick("") == ""
    assert normalize_nick(None) == ""  # type: ignore[arg-type]


def test_is_friendly_bot_match():
    nicks = ["@BotA", "BotB"]
    assert is_friendly_bot("BotA", nicks)
    assert is_friendly_bot("@bota", nicks)
    assert is_friendly_bot("botb", nicks)


def test_is_friendly_bot_no_match():
    nicks = ["BotA"]
    assert not is_friendly_bot("BotC", nicks)
    assert not is_friendly_bot("", nicks)


def test_should_reply_to_friendly_yes():
    rng = _FixedRng([0.3])  # < 0.6 prob → True
    assert should_reply_to_friendly(
        nick="BotA",
        text="hi",
        friendly_nicks=["BotA"],
        own_nick="me",
        reply_probability=0.6,
        rng=rng,
    )


def test_should_reply_to_friendly_no_prob():
    rng = _FixedRng([0.9])  # > 0.6 → False
    assert not should_reply_to_friendly(
        nick="BotA",
        text="hi",
        friendly_nicks=["BotA"],
        own_nick="me",
        reply_probability=0.6,
        rng=rng,
    )


def test_should_reply_to_friendly_not_friendly():
    assert not should_reply_to_friendly(
        nick="RandomDude",
        text="hi",
        friendly_nicks=["BotA"],
        own_nick="me",
    )


def test_should_reply_to_friendly_self_skipped():
    assert not should_reply_to_friendly(
        nick="DevinBot",
        text="hi",
        friendly_nicks=["DevinBot", "BotA"],
        own_nick="DevinBot",
    )


def test_should_reply_to_friendly_empty_text():
    assert not should_reply_to_friendly(
        nick="BotA",
        text="   ",
        friendly_nicks=["BotA"],
    )


def test_reply_delay_in_range():
    rng = random.Random(42)
    for _ in range(20):
        d = reply_delay_seconds(min_sec=15, max_sec=40, rng=rng)
        assert 15 <= d <= 40


def test_reply_delay_swapped_args():
    """Если min > max — берём порядок наоборот, не падаем."""
    d = reply_delay_seconds(min_sec=40, max_sec=15, rng=random.Random(0))
    assert 15 <= d <= 40


def test_format_friendly_context_empty():
    assert format_friendly_context([]) == ""


def test_format_friendly_context_basic():
    msgs = [
        {"nick": "BotA", "text": "hi"},
        {"nick": "BotB", "text": "lol"},
    ]
    block = format_friendly_context(msgs)
    assert "[Друзья в чате" in block
    assert "BotA" in block
    assert "BotB" in block
    assert "hi" in block


def test_format_friendly_context_truncates_long():
    msgs = [{"nick": "BotA", "text": "x" * 500}]
    block = format_friendly_context(msgs)
    assert "…" in block


def test_format_friendly_context_max_messages():
    msgs = [{"nick": f"Bot{i}", "text": "hi"} for i in range(20)]
    block = format_friendly_context(msgs, max_messages=3)
    # должно быть только 3 строки с никами
    assert block.count("Bot") == 3


def test_friendly_chat_tracker_observe():
    t = FriendlyChatTracker(friendly_nicks=["BotA"])
    t.observe("BotA", "hi", ts=1000.0)
    t.observe("RandomDude", "hi", ts=1001.0)  # не friendly — игнор
    assert len(t.recent_messages) == 1


def test_friendly_chat_tracker_history_size():
    t = FriendlyChatTracker(friendly_nicks=["BotA"], history_size=5)
    for i in range(10):
        t.observe("BotA", f"msg{i}", ts=1000.0 + i)
    assert len(t.recent_messages) == 5
    # Последние 5
    assert t.recent_messages[-1]["text"] == "msg9"


def test_friendly_chat_tracker_decide_with_cooldown():
    rng = _FixedRng([0.1, 0.1])  # всегда reply
    t = FriendlyChatTracker(
        friendly_nicks=["BotA"],
        reply_probability=1.0,
        reply_cooldown_sec=60,
    )
    assert t.decide("BotA", "hi", now=1000.0, rng=rng)
    t.mark_replied("BotA", now=1000.0)
    # 30 сек прошло — ещё в cooldown
    assert not t.decide("BotA", "hi", now=1030.0, rng=_FixedRng([0.1]))
    # 90 сек — уже можно
    assert t.decide("BotA", "hi", now=1090.0, rng=_FixedRng([0.1]))


def test_friendly_chat_tracker_decide_skips_self():
    t = FriendlyChatTracker(friendly_nicks=["BotA"], own_nick="BotA")
    assert not t.decide("BotA", "hi", now=1000.0)


def test_friendly_chat_tracker_get_delay():
    t = FriendlyChatTracker(min_delay_sec=10, max_delay_sec=20)
    rng = random.Random(0)
    for _ in range(5):
        d = t.get_delay_seconds(rng=rng)
        assert 10 <= d <= 20


def test_friendly_chat_tracker_set_friendly_nicks_normalizes():
    t = FriendlyChatTracker()
    t.set_friendly_nicks(["@BotA", "  BotB ", "", None])  # type: ignore[list-item]
    assert "bota" in t.friendly_nicks
    assert "botb" in t.friendly_nicks
    assert "" not in t.friendly_nicks


def test_friendly_chat_tracker_context_block_uses_history():
    t = FriendlyChatTracker(friendly_nicks=["BotA"])
    t.observe("BotA", "first", ts=1000.0)
    t.observe("BotA", "second", ts=1010.0)
    block = t.context_block()
    assert "first" in block
    assert "second" in block


def test_friendly_chat_tracker_snapshot_keys():
    t = FriendlyChatTracker(friendly_nicks=["BotA"], own_nick="me")
    snap = t.snapshot()
    assert "friendly_nicks" in snap
    assert "own_nick" in snap
    assert "reply_probability" in snap
    assert "cooldown_sec" in snap
