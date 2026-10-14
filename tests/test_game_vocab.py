"""Tests for app.game_vocab."""

from __future__ import annotations

import random

import pytest

from app.game_vocab import (
    DEFAULT_GAME_CATEGORIES,
    all_categories,
    extract_game_keywords,
    format_vocab_block,
    match_game_category,
    match_via_text,
    select_random_terms,
)


def test_match_exact_souls():
    assert match_game_category("Elden Ring") == "souls"
    assert match_game_category("Dark Souls III") == "souls"


def test_match_case_insensitive():
    assert match_game_category("DOTA 2") == "moba"
    assert match_game_category("dota 2") == "moba"
    assert match_game_category("  DoTa 2  ") == "moba"


def test_match_partial():
    # "Apex Legends Season 18" → fps (содержит "apex legends")
    assert match_game_category("Apex Legends Season 18") == "fps"


def test_match_unknown_returns_empty():
    assert match_game_category("Stardew Valley") == ""
    assert match_game_category("") == ""
    assert match_game_category(None) == ""  # type: ignore[arg-type]


def test_format_vocab_block_has_marker():
    block = format_vocab_block("souls")
    assert "[Игровой словарь]" in block
    assert "[/Игровой словарь]" in block
    assert "git gud" in block


def test_format_vocab_block_unknown_category():
    assert format_vocab_block("") == ""
    assert format_vocab_block("nonexistent") == ""


def test_format_vocab_block_tone_present():
    block = format_vocab_block("horror")
    assert "Тон:" in block
    assert "напряжённый" in block or "нервный" in block


def test_select_random_terms_n_le_pool():
    rng = random.Random(42)
    terms = select_random_terms("fps", n=3, rng=rng)
    assert len(terms) == 3
    assert all(isinstance(t, str) for t in terms)


def test_select_random_terms_n_larger_than_pool():
    """Если n больше пула — возвращаем весь пул."""
    rng = random.Random(42)
    pool_size = len(DEFAULT_GAME_CATEGORIES["minecraft"]["vocab"])
    terms = select_random_terms("minecraft", n=pool_size + 100, rng=rng)
    assert len(terms) == pool_size


def test_select_random_terms_unknown_category():
    assert select_random_terms("xxx", n=3) == []


def test_all_categories_nonempty():
    cats = all_categories()
    assert "souls" in cats
    assert "moba" in cats
    assert "irl" in cats
    assert len(cats) >= 10


def test_extract_game_keywords_filters_short():
    kws = extract_game_keywords("Hello a bc world!", min_len=3)
    # "a" and "bc" filtered
    assert "hello" in kws
    assert "world" in kws
    assert "a" not in kws
    assert "bc" not in kws


def test_extract_game_keywords_handles_empty():
    assert extract_game_keywords("") == []
    assert extract_game_keywords(None) == []  # type: ignore[arg-type]


def test_match_via_text_finds_in_long_string():
    # Если title стрима упоминает игру
    cat = match_via_text("Today playing Dark Souls 3 again because I hate myself")
    assert cat == "souls"


def test_match_via_text_no_match():
    assert match_via_text("hello world banana") == ""
    assert match_via_text("") == ""


def test_match_via_text_finds_irl_keyword():
    # "irl" — одно из match-слов в irl-категории
    assert match_via_text("streaming irl from the park") == "irl"


def test_custom_mapping_override():
    custom = {
        "test_cat": {
            "match": ["mygame"],
            "vocab": ["a", "b"],
            "tone": "test",
        }
    }
    assert match_game_category("MyGame", mapping=custom) == "test_cat"
    block = format_vocab_block("test_cat", mapping=custom)
    assert "a, b" in block


def test_all_default_categories_have_match_and_vocab():
    for cat, payload in DEFAULT_GAME_CATEGORIES.items():
        assert payload.get("match"), f"{cat} has no match list"
        assert payload.get("vocab"), f"{cat} has no vocab list"
