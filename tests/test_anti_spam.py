"""Тесты Feature 7: anti-spam фильтры."""
from __future__ import annotations

import time

from app.anti_spam import AntiSpam, AntiSpamSettings


def test_disabled_passes_everything():
    a = AntiSpam()
    s = AntiSpamSettings(enabled=False, max_caps_pct=10)
    skip, _ = a.should_skip(1, "c", "u", "AAAAAAAAA", s)
    assert skip is False


def test_min_length():
    a = AntiSpam()
    s = AntiSpamSettings(enabled=True, min_msg_len=5)
    skip, reason = a.should_skip(1, "c", "u", "hi", s)
    assert skip and "слишком короткое" in reason
    skip, _ = a.should_skip(1, "c", "u", "hello!", s)
    assert skip is False


def test_caps_filter():
    a = AntiSpam()
    s = AntiSpamSettings(enabled=True, max_caps_pct=80)
    skip, reason = a.should_skip(1, "c", "u", "HELLO WORLD", s)
    assert skip and "капс" in reason
    # Mixed case below threshold passes
    skip, _ = a.should_skip(1, "c", "u", "Hello world", s)
    assert skip is False
    # Short ALL CAPS — letters < 6 — пропускаем
    skip, _ = a.should_skip(1, "c", "u", "OK!", s)
    assert skip is False


def test_link_filter():
    a = AntiSpam()
    s = AntiSpamSettings(enabled=True, block_links=True)
    skip, reason = a.should_skip(1, "c", "u", "Привет https://twitch.tv/foo", s)
    assert skip and "ссылк" in reason
    skip, reason = a.should_skip(1, "c", "u", "Зайди на streamer.gg", s)
    assert skip and "ссылк" in reason
    skip, _ = a.should_skip(1, "c", "u", "Привет, как дела?", s)
    assert skip is False


def test_per_user_cooldown():
    a = AntiSpam()
    s = AntiSpamSettings(enabled=True, per_user_cooldown_sec=60)
    # Первое сообщение проходит
    skip, _ = a.should_skip(1, "c", "alice", "hi", s)
    assert skip is False
    a.mark_replied(1, "c", "alice")
    # Сразу ещё одно — должно скипнуться
    skip, reason = a.should_skip(1, "c", "alice", "again", s)
    assert skip and "cooldown" in reason
    # Другой юзер не задет
    skip, _ = a.should_skip(1, "c", "bob", "hi", s)
    assert skip is False


def test_repeat_detection():
    a = AntiSpam()
    s = AntiSpamSettings(enabled=True, block_repeat_count=3)
    # Три раза одно и то же — на третий раз скип
    assert a.should_skip(1, "c", "u", "spam", s)[0] is False
    assert a.should_skip(1, "c", "u", "spam", s)[0] is False
    skip, reason = a.should_skip(1, "c", "u", "spam", s)
    assert skip and "повтор" in reason


def test_isolated_per_account_and_channel():
    """Фильтры повторов не должны протекать между каналами/аккаунтами."""
    a = AntiSpam()
    s = AntiSpamSettings(enabled=True, block_repeat_count=2)
    a.should_skip(1, "ch1", "u", "x", s)
    a.should_skip(1, "ch1", "u", "x", s)
    # На другом канале того же аккаунта — счётчик свой
    skip, _ = a.should_skip(1, "ch2", "u", "x", s)
    assert skip is False
