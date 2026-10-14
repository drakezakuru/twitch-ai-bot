"""Тести для v11 модулів: BotPersona extended, AttentionFilter, BotLogs, BotPresets, BotDirs."""

from __future__ import annotations

import json
import time

import pytest

from app.bot_persona import (
    BotPersona,
    format_persona_for_prompt,
    format_extended_persona_for_prompt,
)
from app.bot_presets import PRESETS, apply_preset, list_presets
from app.attention_filter import (
    is_noise_message,
    BatchBuffer,
    AttentionFilter,
)


# ═══════════════════════════════════════════════════════════════════
# BotPersona Extended (v11)
# ═══════════════════════════════════════════════════════════════════

class TestBotPersonaExtended:
    def test_v11_fields_defaults(self):
        p = BotPersona()
        assert p.humor_level == 50
        assert p.darkness_level == 10
        assert p.sarcasm_level == 30
        assert p.emotionality == 50
        assert p.adult_humor == 0
        assert p.seriousness == 50
        assert p.contact_level == 50
        assert p.chat_affinity == 50
        assert p.observation_only is False
        assert p.asterisk_emotes is False
        assert p.dynamic_personality is False

    def test_v11_serialization_roundtrip(self):
        p = BotPersona(
            name="TestBot",
            humor_level=70,
            sarcasm_level=80,
            darkness_level=20,
            adult_humor=10,
            contact_level=60,
            bounds={"humor": (30, 90)},
        )
        data = p.to_dict()
        assert data["humor_level"] == 70
        assert data["sarcasm_level"] == 80
        assert data["bounds"] == {"humor": [30, 90]}

        p2 = BotPersona.from_dict(data)
        assert p2.humor_level == 70
        assert p2.sarcasm_level == 80
        assert p2.bounds == {"humor": (30, 90)}

    def test_v11_to_json_from_json(self):
        p = BotPersona(name="X", humor_level=90, adult_humor=50)
        j = p.to_json()
        p2 = BotPersona.from_json(j)
        assert p2.name == "X"
        assert p2.humor_level == 90
        assert p2.adult_humor == 50

    def test_clamp_with_bounds(self):
        p = BotPersona(humor_level=200, darkness_level=-10)
        p.clamp()
        assert p.humor_level == 100  # default bounds (0, 100)
        assert p.darkness_level == 0

    def test_clamp_custom_bounds(self):
        p = BotPersona(humor_level=5, bounds={"humor": (20, 80)})
        p.clamp()
        assert p.humor_level == 20

    def test_copy(self):
        p = BotPersona(name="X", humor_level=70)
        p2 = p.copy()
        p2.humor_level = 90
        assert p.humor_level == 70  # original unchanged

    def test_is_empty_with_v11_fields(self):
        # Default v11 values → still considered empty for extended fields
        p = BotPersona()
        # is_empty returns True when all v11 levels are default
        assert p.is_empty()

    def test_is_empty_non_default_v11(self):
        p = BotPersona(humor_level=80)
        assert not p.is_empty()

    def test_format_extended_persona(self):
        p = BotPersona(name="Test", humor_level=80, sarcasm_level=60)
        result = format_extended_persona_for_prompt(p)
        assert "[Твоя личность]" in result
        assert "[Характер]" in result
        assert "гумор=80" in result
        assert "сарказм=60" in result

    def test_format_extended_asterisk_emotes(self):
        p = BotPersona(name="Test", humor_level=80, asterisk_emotes=True)
        result = format_extended_persona_for_prompt(p)
        assert "*дії*" in result


# ═══════════════════════════════════════════════════════════════════
# C5 (PLAN_TODO ТРЕК 1): apply_dynamic_persona / MOOD_DELTA удалены —
# в проде их не вызывал никто, а UI-тумблер dynamic_personality был плацебо.
# ═══════════════════════════════════════════════════════════════════

class TestDynamicPersonaRemoved:
    def test_dynamic_persona_api_gone(self):
        import app.bot_persona as bp
        assert not hasattr(bp, "apply_dynamic_persona")
        assert not hasattr(bp, "MOOD_DELTA")

    def test_placebo_toggle_removed_from_ui(self):
        from pathlib import Path
        js = (Path(__file__).parent.parent / "static" / "app" / "03_bots.js").read_text(encoding="utf-8")
        assert "'dynamic_personality'" not in js, "плацебо-тумблер вернулся в PERSONA_TOGGLES"
        assert "'mood_influence'" not in js, "слайдер mood_influence вернулся (ни на что не влиял)"


# ═══════════════════════════════════════════════════════════════════
# Noise filter
# ═══════════════════════════════════════════════════════════════════

class TestNoiseFilter:
    def test_noise_messages(self):
        assert is_noise_message("+1")
        assert is_noise_message("+1+1+1")
        assert is_noise_message("llll")
        assert is_noise_message("хххх")
        assert is_noise_message(".")
        assert is_noise_message("!!!")
        assert is_noise_message("")

    def test_not_noise(self):
        assert not is_noise_message("Привіт всім!")
        assert not is_noise_message("як справи?")
        assert not is_noise_message("нормально")
        assert not is_noise_message("KEKW ти дурний")  # KEKW + text = not noise
        assert not is_noise_message("KEKW")  # 4 letters, not pure emoji, not matched
        assert not is_noise_message("KEKW")  # 4+ letters, not pure emoji, not matched


# ═══════════════════════════════════════════════════════════════════
# Attention Filter
# ═══════════════════════════════════════════════════════════════════

class TestAttentionFilter:
    def test_everyone_mode(self):
        af = AttentionFilter()
        batch = [
            {"author": "user1", "text": "привіт"},
            {"author": "streamer", "text": "вітаю"},
        ]
        config = {"attention_mode": "everyone", "ignore_noise": 0}
        result = af.apply_filter(batch, config, None, "streamer")
        assert len(result) == 2

    def test_streamer_only_mode(self):
        af = AttentionFilter()
        batch = [
            {"author": "user1", "text": "привіт"},
            {"author": "streamer", "text": "вітаю"},
        ]
        config = {"attention_mode": "streamer_only", "ignore_noise": 0}
        result = af.apply_filter(batch, config, None, "streamer")
        assert len(result) == 1
        assert result[0]["author"] == "streamer"

    def test_chat_only_mode(self):
        af = AttentionFilter()
        batch = [
            {"author": "user1", "text": "привіт"},
            {"author": "streamer", "text": "вітаю"},
        ]
        config = {"attention_mode": "chat_only", "ignore_noise": 0}
        result = af.apply_filter(batch, config, None, "streamer")
        assert len(result) == 1
        assert result[0]["author"] == "user1"

    def test_custom_mode(self):
        af = AttentionFilter()
        batch = [
            {"author": "user1", "text": "привіт"},
            {"author": "user2", "text": "хай"},
            {"author": "user3", "text": "йо"},
        ]
        config = {"attention_mode": "custom", "ignore_noise": 0}
        result = af.apply_filter(batch, config, {"user1", "user3"}, "streamer")
        assert len(result) == 2

    def test_noise_filter(self):
        af = AttentionFilter()
        batch = [
            {"author": "user1", "text": "привіт"},
            {"author": "user2", "text": "+1"},
            {"author": "user3", "text": "."},
        ]
        config = {"attention_mode": "everyone", "ignore_noise": 1}
        result = af.apply_filter(batch, config, None, "streamer")
        assert len(result) == 1  # only "привіт"

    def test_cooldown(self):
        af = AttentionFilter()
        account_id = 1
        channel = "#test"
        assert not af.is_on_cooldown(account_id, channel)
        af.mark_replied(account_id, channel, 30.0)
        assert af.is_on_cooldown(account_id, channel)

    def test_can_reply(self):
        af = AttentionFilter()
        config = {"max_replies_per_minute": 2}
        assert af.can_reply(1, config)
        af.mark_replied(1, "#test", 30.0)
        assert af.can_reply(1, config)
        af.mark_replied(1, "#test", 30.0)
        assert not af.can_reply(1, config)

    def test_build_batch_context(self):
        af = AttentionFilter()
        batch = [
            {"author": "user1", "text": "привіт", "timestamp": "18:00:01"},
            {"author": "user2", "text": "хай", "timestamp": "18:00:02"},
        ]
        ctx = af.build_batch_context(batch)
        assert "[18:00:01] user1: привіт" in ctx
        assert "[18:00:02] user2: хай" in ctx


# ═══════════════════════════════════════════════════════════════════
# BatchBuffer
# ═══════════════════════════════════════════════════════════════════

class TestBatchBuffer:
    def test_add_and_get(self):
        bb = BatchBuffer()
        bb.add(1, "#test", {"author": "user1", "text": "hi"})
        bb.add(1, "#test", {"author": "user2", "text": "hey"})
        batch = bb.get_batch(1, "#test")
        assert len(batch) == 2
        # After get, batch is cleared
        assert bb.get_batch(1, "#test") == []

    def test_has_messages(self):
        bb = BatchBuffer()
        assert not bb.has_messages(1, "#test")
        bb.add(1, "#test", {"author": "user1", "text": "hi"})
        assert bb.has_messages(1, "#test")

    def test_different_channels(self):
        bb = BatchBuffer()
        bb.add(1, "#ch1", {"author": "u1", "text": "a"})
        bb.add(1, "#ch2", {"author": "u2", "text": "b"})
        assert len(bb.get_batch(1, "#ch1")) == 1
        assert len(bb.get_batch(1, "#ch2")) == 1

    @pytest.mark.asyncio
    async def test_completed_timer_is_removed_and_key_can_be_reused(self):
        import asyncio

        bb = BatchBuffer()
        calls: list[str] = []

        async def first_callback():
            calls.append("first")

        async def replacement_callback():
            calls.append("replacement")

        bb.start_timer(1, "#test", first_callback, 0.001)
        await asyncio.sleep(0.02)
        assert calls == ["first"]
        assert bb._timers == {}

        bb.start_timer(1, "#test", replacement_callback, 0.001)
        await asyncio.sleep(0.02)
        assert calls == ["first", "replacement"]
        assert bb._timers == {}


# ═══════════════════════════════════════════════════════════════════
# Bot Presets
# ═══════════════════════════════════════════════════════════════════

class TestBotPresets:
    def test_all_presets_exist(self):
        assert len(PRESETS) == 8  # PLAN §6: + spam_hahaha (28.08)
        for pid in ["newbie", "friend", "troll", "sage", "toxic", "calm", "wild", "spam_hahaha"]:
            assert pid in PRESETS

    def test_apply_preset(self):
        p = apply_preset("friend")
        assert p is not None
        assert p["humor_level"] == 60
        assert p["label"] == "Друг"

    def test_apply_nonexistent_preset(self):
        assert apply_preset("nonexistent") is None

    def test_list_presets(self):
        presets = list_presets()
        assert len(presets) == 8  # PLAN §6: + spam_hahaha (28.08)
        assert all("id" in p for p in presets)

    def test_preset_values_in_range(self):
        for pid, p in PRESETS.items():
            for key in ("humor_level", "darkness_level", "crudeness_level",
                        "sarcasm_level", "adult_humor", "seriousness",
                        "emotionality", "contact_level", "chat_affinity"):
                assert key in p, f"{pid} missing {key}"
                assert 0 <= p[key] <= 100, f"{pid}.{key} = {p[key]} out of range"
