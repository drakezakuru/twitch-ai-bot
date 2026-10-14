"""Tests for app.predictions_polls."""

from __future__ import annotations

import asyncio
import random

import pytest

from app.predictions_polls import (
    VoteDecision,
    build_vote_prompt,
    decide_vote,
    fallback_random_choice,
    is_obvious_loaded_question,
    parse_choice_index,
    serialize_event,
)


def test_parse_choice_digit():
    assert parse_choice_index("я выбираю 2", ["A", "B", "C"]) == 1
    assert parse_choice_index("3", ["A", "B", "C"]) == 2


def test_parse_choice_digit_out_of_range():
    assert parse_choice_index("99", ["A", "B"], default_idx=0) == 0


def test_parse_choice_by_substring():
    assert parse_choice_index("выбираю синий вариант", ["красный", "синий", "зелёный"]) == 1


def test_parse_choice_yes_no_binary():
    assert parse_choice_index("yes", ["Yes", "No"]) == 0
    assert parse_choice_index("конечно нет", ["Yes", "No"]) == 1
    assert parse_choice_index("да", ["Yes", "No"]) == 0
    assert parse_choice_index("против", ["Yes", "No"]) == 1


def test_parse_choice_unrecognized():
    assert parse_choice_index("xxxx", ["A", "B"], default_idx=None) is None
    assert parse_choice_index("xxxx", ["A", "B"], default_idx=0) == 0


def test_parse_choice_empty_reply():
    assert parse_choice_index("", ["A", "B"], default_idx=1) == 1


def test_build_vote_prompt_has_options():
    p = build_vote_prompt("Кто победит?", ["Стример", "Босс"])
    assert "Кто победит?" in p
    assert "1. Стример" in p
    assert "2. Босс" in p
    assert "1-2" in p


def test_build_vote_prompt_includes_channel():
    p = build_vote_prompt("?", ["A", "B"], channel="test_channel")
    assert "test_channel" in p


def test_is_obvious_loaded_question_positive():
    assert is_obvious_loaded_question("Пройду босса с первого раза?")
    assert is_obvious_loaded_question("Я выиграю эту катку?")
    assert is_obvious_loaded_question("Хайп будет?")


def test_is_obvious_loaded_question_negative():
    assert not is_obvious_loaded_question("Какой цвет лучше?")
    assert not is_obvious_loaded_question("")


def test_fallback_random_in_range():
    rng = random.Random(0)
    for _ in range(20):
        idx = fallback_random_choice(["A", "B", "C", "D"], rng=rng)
        assert 0 <= idx < 4


def test_fallback_random_empty():
    assert fallback_random_choice([]) == -1


@pytest.mark.asyncio
async def test_decide_vote_loaded_question_supports_streamer():
    decision = await decide_vote("Пройду босса?", ["Да, легко", "Помру"])
    assert decision.choice_idx == 0
    assert decision.choice_text == "Да, легко"
    assert decision.confidence >= 0.8


@pytest.mark.asyncio
async def test_decide_vote_ai_callback_returns_index():
    async def fake_ai(prompt: str) -> str:
        return "2"

    decision = await decide_vote("Какой цвет?", ["Красный", "Синий"], ai_callback=fake_ai)
    assert decision.choice_idx == 1
    assert decision.choice_text == "Синий"
    assert not decision.used_fallback


@pytest.mark.asyncio
async def test_decide_vote_ai_unparseable_falls_back():
    async def fake_ai(prompt: str) -> str:
        return "xxxx??"

    rng = random.Random(0)
    decision = await decide_vote("Кто?", ["A", "B"], ai_callback=fake_ai, rng=rng)
    assert decision.used_fallback
    assert 0 <= decision.choice_idx <= 1


@pytest.mark.asyncio
async def test_decide_vote_empty_choices():
    decision = await decide_vote("?", [])
    assert decision.choice_idx == -1
    assert decision.used_fallback


@pytest.mark.asyncio
async def test_decide_vote_ai_exception_falls_back():
    async def bad_ai(prompt: str) -> str:
        raise RuntimeError("api down")

    rng = random.Random(0)
    decision = await decide_vote(
        "Какой цвет?", ["Красный", "Синий"], ai_callback=bad_ai, rng=rng
    )
    assert decision.used_fallback
    assert decision.choice_idx in (0, 1)


def test_serialize_event_poll():
    payload = {
        "subscription": {"type": "channel.poll.begin"},
        "event": {
            "id": "abc",
            "broadcaster_user_name": "test_channel",
            "title": "Что играть?",
            "choices": [
                {"id": "1", "title": "Elden Ring"},
                {"id": "2", "title": "Dota"},
            ],
        },
    }
    out = serialize_event(payload)
    assert out["type"] == "channel.poll.begin"
    assert out["channel"] == "test_channel"
    assert out["title"] == "Что играть?"
    assert len(out["choices"]) == 2
    assert out["choices"][0]["title"] == "Elden Ring"


def test_serialize_event_prediction():
    payload = {
        "subscription": {"type": "channel.prediction.begin"},
        "event": {
            "id": "p1",
            "broadcaster_user_name": "test_channel",
            "title": "Пройдёт ли босса?",
            "outcomes": [
                {"id": "o1", "title": "Да"},
                {"id": "o2", "title": "Нет"},
            ],
        },
    }
    out = serialize_event(payload)
    assert out["type"] == "channel.prediction.begin"
    assert len(out["choices"]) == 2


def test_serialize_event_empty():
    assert serialize_event({}) == {}
    assert serialize_event(None) == {}  # type: ignore[arg-type]


def test_vote_decision_to_dict():
    d = VoteDecision(choice_idx=1, choice_text="Synth", confidence=0.5, reasoning="test")
    out = d.to_dict()
    assert out["choice_idx"] == 1
    assert out["choice_text"] == "Synth"
    assert out["confidence"] == 0.5
