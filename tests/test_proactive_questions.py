"""Tests for v10.4.7 Wave 4.3 — proactive question generation."""

from app.proactive_questions import (
    ProactiveQuestionTracker,
    build_question_prompt,
    extract_question_text,
    fallback_question,
)


def test_can_emit_needs_vision():
    tr = ProactiveQuestionTracker()
    ok, reason = tr.can_emit(now=1000.0)
    assert not ok and "vision" in reason.lower()


def test_can_emit_silence_check():
    tr = ProactiveQuestionTracker(cooldown_sec=60, min_silence_sec=120)
    tr.mark_vision("игра Elden Ring", now=1000.0)
    tr.mark_chat(now=1000.0)
    ok, reason = tr.can_emit(now=1030.0)
    assert not ok
    assert "chat" in reason.lower() or "active" in reason.lower()


def test_can_emit_passes_after_silence():
    tr = ProactiveQuestionTracker(cooldown_sec=60, min_silence_sec=90)
    tr.mark_vision("игра Elden Ring", now=1000.0)
    tr.mark_chat(now=900.0)  # давно
    ok, reason = tr.can_emit(now=1100.0)
    assert ok, reason


def test_cooldown_blocks_emit():
    tr = ProactiveQuestionTracker(cooldown_sec=60, min_silence_sec=10)
    tr.mark_vision("vision data", now=1000.0)
    tr.mark_chat(now=900.0)
    tr.mark_emit(now=1000.0)
    ok, reason = tr.can_emit(now=1030.0)
    assert not ok and "cool" in reason.lower()


def test_stale_vision_blocks():
    tr = ProactiveQuestionTracker(cooldown_sec=60, min_silence_sec=10)
    tr.mark_vision("vision data", now=1000.0)
    tr.mark_chat(now=900.0)
    ok, reason = tr.can_emit(now=1500.0)  # vision устарел
    assert not ok and "stale" in reason.lower()


def test_build_question_prompt_contains_vision():
    sys, usr = build_question_prompt("Игра Elden Ring, идёт битва с боссом")
    assert "Twitch" in sys or "зритель" in sys
    assert "Elden Ring" in usr


def test_build_question_prompt_with_persona():
    sys, usr = build_question_prompt("vision", persona_hint="любитель souls")
    assert "souls" in sys.lower()


def test_extract_question_clean():
    out = extract_question_text("Вопрос: что у тебя за билд?")
    assert out == "что у тебя за билд?"


def test_extract_question_strips_quotes():
    out = extract_question_text('"это лёгкий босс?"')
    assert out == "это лёгкий босс?"


def test_extract_question_strips_mentions():
    out = extract_question_text("@user что играешь?")
    assert "@user" not in out
    assert "играешь" in out


def test_extract_question_takes_first_line():
    out = extract_question_text("первая\nвторая строка")
    assert out == "первая"


def test_extract_question_truncates_long():
    long = " ".join(["слово"] * 100)
    out = extract_question_text(long)
    assert len(out) <= 140


def test_fallback_question_is_string():
    q = fallback_question()
    assert isinstance(q, str)
    assert len(q) > 0
