"""Тесты на app.bot_persona."""

from __future__ import annotations

import json
import random

import pytest

from app.bot_persona import BotPersona, format_persona_for_prompt


class TestBotPersonaSerialization:
    def test_default_is_empty(self):
        p = BotPersona()
        assert p.is_empty()
        assert format_persona_for_prompt(p) == ""

    def test_roundtrip_json(self):
        p = BotPersona(
            name="Жора",
            age=23,
            gender="м",
            location="Питер",
            personality=["саркастичный", "флегматичный"],
            favorite_games=["Tarkov", "Cyberpunk"],
            quirks=["часто пишет лол"],
        )
        text = p.to_json()
        decoded = BotPersona.from_json(text)
        assert decoded.name == "Жора"
        assert decoded.age == 23
        assert decoded.personality == ["саркастичный", "флегматичный"]
        assert decoded.favorite_games == ["Tarkov", "Cyberpunk"]

    def test_from_json_invalid_safe(self):
        assert BotPersona.from_json("not json {").is_empty()
        assert BotPersona.from_json("").is_empty()
        assert BotPersona.from_json(None).is_empty()

    def test_from_dict_with_comma_string(self):
        # На фронтенде поля-списки могут прийти comma-separated.
        p = BotPersona.from_dict({"favorite_games": "Tarkov, Cyberpunk, Dota"})
        assert p.favorite_games == ["Tarkov", "Cyberpunk", "Dota"]

    def test_from_dict_filters_empty_items(self):
        p = BotPersona.from_dict({"personality": ["", " ", "ok", None]})
        assert p.personality == ["ok"]

    def test_age_coerced_to_int(self):
        assert BotPersona.from_dict({"age": "25"}).age == 25
        assert BotPersona.from_dict({"age": "хуй"}).age == 0  # safe fallback
        assert BotPersona.from_dict({"age": None}).age == 0

    def test_is_empty_strict(self):
        # Любое непустое поле → не empty.
        assert not BotPersona(name="x").is_empty()
        assert not BotPersona(age=1).is_empty()
        assert not BotPersona(personality=["a"]).is_empty()
        assert not BotPersona(catchphrases=["лол"]).is_empty()


class TestFormatPersonaForPrompt:
    def test_empty_returns_empty(self):
        assert format_persona_for_prompt(BotPersona()) == ""

    def test_contains_name_and_age(self):
        p = BotPersona(name="Жора", age=23, gender="м", location="Питер")
        out = format_persona_for_prompt(p)
        assert "Жора" in out
        assert "23" in out
        assert "Питер" in out
        assert "[Твоя личность]" in out

    def test_lists_are_joined(self):
        p = BotPersona(favorite_games=["Tarkov", "Cyberpunk"], hobbies=["качалка", "кино"])
        out = format_persona_for_prompt(p)
        assert "Tarkov" in out
        assert "Cyberpunk" in out
        assert "качалка" in out
        assert "кино" in out

    def test_catchphrase_randomized(self):
        p = BotPersona(catchphrases=["лол", "крч", "лан"])
        rng = random.Random(42)
        out = format_persona_for_prompt(p, randomize_catchphrase=True, rng=rng)
        # Ровно одна из фраз должна быть, не все.
        present = [c for c in p.catchphrases if c in out]
        assert len(present) == 1

    def test_catchphrase_all_when_disabled_randomize(self):
        p = BotPersona(catchphrases=["лол", "крч"])
        out = format_persona_for_prompt(p, randomize_catchphrase=False)
        assert "лол" in out
        assert "крч" in out

    def test_quirks_section_present(self):
        p = BotPersona(quirks=["не использует точки", "избегает CAPS"])
        out = format_persona_for_prompt(p)
        assert "не использует точки" in out

    def test_background_included(self):
        p = BotPersona(background="Смотрю стримы 3 года, до этого играл в CS.")
        out = format_persona_for_prompt(p)
        assert "Смотрю стримы 3 года" in out

    def test_speaking_style_visible(self):
        p = BotPersona(speaking_style="zoomer-сленг, короткие предложения")
        out = format_persona_for_prompt(p)
        assert "zoomer-сленг" in out
