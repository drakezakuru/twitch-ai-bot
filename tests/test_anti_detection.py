"""Юнит-тесты на app.anti_detection."""

from __future__ import annotations

import random

import pytest

from app.anti_detection import (
    TypoConfig,
    apply_typo,
    compute_self_similarity,
    humanized_delay_seconds,
    looks_like_bot,
)


class TestSelfSimilarity:
    def test_identical_texts_jaccard_1(self):
        assert compute_self_similarity("привет как дела друг", ["привет как дела друг"]) == 1.0

    def test_disjoint_texts_jaccard_0(self):
        s = compute_self_similarity(
            "погода сегодня солнечная очень тепло",
            ["игра вышла плохая на старте баги"],
        )
        assert s == 0.0

    def test_partial_overlap_above_threshold(self):
        # 4 шингла у нового; 1 общий → 1/7 ≈ 0.14. Низко, но не 0.
        s = compute_self_similarity(
            "новый стрим начинается через пять минут",
            ["новый стрим начинается завтра вечером"],
        )
        assert 0.0 < s < 1.0

    def test_empty_inputs_safe(self):
        assert compute_self_similarity("", ["abc def ghi"]) == 0.0
        assert compute_self_similarity("abc def ghi", []) == 0.0
        assert compute_self_similarity("", [""]) == 0.0

    def test_takes_max_over_history(self):
        new = "стример играет в новую игру сегодня"
        recent = [
            "ничего общего тут нет совсем",
            "стример играет в новую игру сегодня",  # 100% match
            "случайные слова без сходства",
        ]
        assert compute_self_similarity(new, recent) == 1.0

    def test_threshold_detects_paraphrase_match(self):
        # Реалистичный кейс: бот часто повторяет «согласен это интересно».
        new = "согласен это очень интересно"
        recent = ["согласен это интересно правда"]
        s = compute_self_similarity(new, recent)
        # Должно быть выше 0.3 — это «похожий» ответ.
        assert s >= 0.2


class TestHumanizedDelay:
    def test_short_text_short_delay(self):
        rng = random.Random(42)
        d = humanized_delay_seconds("ок", base=1.0, per_char=0.05, sigma=0.0, rng=rng)
        # 1.0 + 0.05*2 = 1.1, без шума.
        assert abs(d - 1.1) < 0.01

    def test_long_text_longer_delay(self):
        rng = random.Random(42)
        short = humanized_delay_seconds("привет", sigma=0.0, rng=rng)
        long = humanized_delay_seconds("привет " * 30, sigma=0.0, rng=rng)
        assert long > short

    def test_cap_enforced(self):
        rng = random.Random(42)
        d = humanized_delay_seconds("x" * 10000, cap=3.0, sigma=0.0, rng=rng)
        assert d <= 3.0

    def test_minimum_floor(self):
        rng = random.Random(42)
        # Базовая 0 → должна всё равно быть ≥ 0.2 (floor).
        d = humanized_delay_seconds("", base=0.0, per_char=0.0, sigma=0.0, rng=rng)
        assert d >= 0.2

    def test_distinct_seeds_distinct_delays(self):
        # Gauss-шум разный → задержки разные. Очень слабый assert: not equal.
        rng_a = random.Random(1)
        rng_b = random.Random(2)
        d_a = humanized_delay_seconds("привет привет", sigma=1.0, rng=rng_a)
        d_b = humanized_delay_seconds("привет привет", sigma=1.0, rng=rng_b)
        assert d_a != d_b


class TestTypo:
    def test_no_typo_when_rate_zero(self):
        rng = random.Random(0)
        cfg = TypoConfig(rate=0.0)
        out = apply_typo("hello world this is a test", cfg, rng=rng)
        assert out == "hello world this is a test"

    def test_typo_when_rate_one(self):
        rng = random.Random(0)
        cfg = TypoConfig(rate=1.0, max_typos_per_msg=1)
        original = "hello world test"
        out = apply_typo(original, cfg, rng=rng)
        # Длина та же, но 1 буква отличается.
        assert len(out) == len(original)
        diff_count = sum(1 for a, b in zip(out, original) if a != b)
        assert diff_count == 1

    def test_typo_skipped_for_short_text(self):
        rng = random.Random(0)
        cfg = TypoConfig(rate=1.0, min_length=10)
        out = apply_typo("привет", cfg, rng=rng)
        assert out == "привет"

    def test_max_typos_per_msg_respected(self):
        rng = random.Random(123)
        cfg = TypoConfig(rate=1.0, max_typos_per_msg=2)
        original = "hello world this is a long test message"
        out = apply_typo(original, cfg, rng=rng)
        diff_count = sum(1 for a, b in zip(out, original) if a != b)
        assert diff_count <= 2

    def test_punctuation_not_corrupted(self):
        rng = random.Random(0)
        cfg = TypoConfig(rate=1.0, max_typos_per_msg=10, min_length=1)
        # Только пунктуация — нечего ломать.
        out = apply_typo("!!! ??? ...", cfg, rng=rng)
        assert out == "!!! ??? ..."


class TestBotDetection:
    @pytest.mark.parametrize(
        "username",
        [
            "Nightbot",
            "nightbot",
            "StreamElements",
            "Moobot",
            "fossabot",
            "wizebot",
            "stay_hydrated_bot",
            "my_custom_BOT",
            "streamlabs",
        ],
    )
    def test_known_bot_nicks(self, username: str):
        assert looks_like_bot(username) is True

    @pytest.mark.parametrize("username", ["xqc", "tarik", "shroud", "test_channel"])
    def test_human_nicks_pass(self, username: str):
        assert looks_like_bot(username) is False

    @pytest.mark.parametrize(
        "message",
        [
            "!command",
            "$followage",
            ".timeout user 600",
            "[BOT] Welcome!",
            "User is being followed",
            "Added 'Song Title' to queue",
            "[server] reconnected",
        ],
    )
    def test_bot_phrases_detected(self, message: str):
        # Не-бот по нику, но фраза служебная.
        assert looks_like_bot("someuser", message) is True

    def test_empty_username_safe(self):
        assert looks_like_bot("", "any") is False

    def test_normal_message_passes(self):
        assert looks_like_bot("xqc", "lol that was epic") is False
