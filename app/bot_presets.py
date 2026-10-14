"""Bot presets — готові пресети характеру бота + AI-генерація персони.

Пресети містять значення для humor_level, sarcasm_level, darkness_level,
crudeness_level, adult_humor, seriousness, emotionality, contact_level.

AI-генерація: опис персонажа → LLM генерує BotPersona + system_prompt.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Готові пресети ────────────────────────────────────────────────

PRESETS: dict[str, dict[str, Any]] = {
    "newbie": {
        "label": "Новачок",
        "description": "Тихий, обережний, ввічливий",
        "humor_level": 30,
        "darkness_level": 10,
        "crudeness_level": 0,
        "sarcasm_level": 20,
        "adult_humor": 0,
        "seriousness": 50,
        "emotionality": 30,
        "contact_level": 20,
        "chat_affinity": 30,
    },
    "friend": {
        "label": "Друг",
        "description": "Добрий, підтримує, жартує",
        "humor_level": 60,
        "darkness_level": 30,
        "crudeness_level": 20,
        "sarcasm_level": 40,
        "adult_humor": 30,
        "seriousness": 40,
        "emotionality": 60,
        "contact_level": 70,
        "chat_affinity": 70,
    },
    "troll": {
        "label": "Тролль",
        "description": "Підколює, провокує, але не злий",
        "humor_level": 80,
        "darkness_level": 50,
        "crudeness_level": 40,
        "sarcasm_level": 80,
        "adult_humor": 50,
        "seriousness": 20,
        "emotionality": 50,
        "contact_level": 40,
        "chat_affinity": 50,
    },
    "sage": {
        "label": "Мудрець",
        "description": "Поради + підкол, розумний",
        "humor_level": 40,
        "darkness_level": 20,
        "crudeness_level": 0,
        "sarcasm_level": 60,
        "adult_humor": 10,
        "seriousness": 80,
        "emotionality": 40,
        "contact_level": 60,
        "chat_affinity": 60,
    },
    "toxic": {
        "label": "Токсик",
        "description": "Жорсткий, без фільтрів, агресивний",
        "humor_level": 70,
        "darkness_level": 80,
        "crudeness_level": 80,
        "sarcasm_level": 90,
        "adult_humor": 80,
        "seriousness": 10,
        "emotionality": 70,
        "contact_level": 20,
        "chat_affinity": 30,
    },
    "calm": {
        "label": "Спокійний",
        "description": "Рівний тон, без емоцій, нейтральний",
        "humor_level": 20,
        "darkness_level": 10,
        "crudeness_level": 0,
        "sarcasm_level": 10,
        "adult_humor": 0,
        "seriousness": 50,
        "emotionality": 20,
        "contact_level": 50,
        "chat_affinity": 50,
    },
    "wild": {
        "label": "Дикий",
        "description": "Без кордонів, максимально емоційний",
        "humor_level": 90,
        "darkness_level": 70,
        "crudeness_level": 70,
        "sarcasm_level": 85,
        "adult_humor": 90,
        "seriousness": 5,
        "emotionality": 90,
        "contact_level": 30,
        "chat_affinity": 40,
    },
    # PLAN §6: спам-реакции (смех с чата, короткие громкие ответы).
    "spam_hahaha": {
        "label": "Спам-хахаха",
        "description": "Сміється з чату, шле короткі гучні реакції",
        "humor_level": 95,
        "darkness_level": 15,
        "crudeness_level": 10,
        "sarcasm_level": 25,
        "adult_humor": 0,
        "seriousness": 5,
        "emotionality": 85,
        "contact_level": 50,
        "chat_affinity": 95,
    },
}

# Canonical non-speaking behavior. Kept separate from the historical seven-item
# list so old clients consuming list_presets() remain compatible.
OBSERVER_PRESET = {
    "label": "👀 Спостерігач",
    "description": "Тільки дивиться стрім і накопичує контекст, без повідомлень",
    "observation_only": True,
}

BEHAVIOR_PRESETS = {**PRESETS, "observer": OBSERVER_PRESET}


def apply_preset(preset_id: str) -> dict[str, Any] | None:
    """Повертає копію пресету за ID або None."""
    return copy.deepcopy(BEHAVIOR_PRESETS.get(preset_id)) if preset_id in BEHAVIOR_PRESETS else None


def list_presets() -> list[dict[str, Any]]:
    """Список пресетів з ID."""
    return [{"id": pid, **p} for pid, p in PRESETS.items()]


# ── AI-генерація персони ──────────────────────────────────────────

async def generate_persona_via_ai(description: str, account_id: int) -> dict[str, Any]:
    """Генерує BotPersona за текстовим описом через LLM.

    Повертає dict з полями BotPersona + system_prompt.
    """
    from app.ai_service import AIService

    prompt = (
        f"Опис персонажа для Twitch AI бота:\n{description}\n\n"
        f"Згенеруй JSON з такими полями:\n"
        f'- name (str): ім\'я бота\n'
        f"- age (int): вік (0 якщо не вказано)\n"
        f"- gender (str): стать ('м'/'ж'/пусто)\n"
        f"- personality (list[str]):traits (3-5 шт)\n"
        f"- favorite_games (list[str]): улюблені ігри\n"
        f"- hobbies (list[str]): хоббі\n"
        f"- speaking_style (str): манера речі\n"
        f"- quirks (list[str]): особливості мовлення\n"
        f"- catchphrases (list[str]): фрази (2-3)\n"
        f"- humor_level (int 0-100): рівень гумору\n"
        f"- sarcasm_level (int 0-100): сарказм\n"
        f"- darkness_level (int 0-100): чорний гумор\n"
        f"- crudeness_level (int 0-100): пошлість\n"
        f"- adult_humor (int 0-100): дорослий гумор\n"
        f"- seriousness (int 0-100): серйозність\n"
        f"- emotionality (int 0-100): емоційність\n"
        f"- contact_level (int 0-100): прив'язаність\n"
        f"- system_prompt (str): короткий системний промпт для AI (до 800 символів)\n\n"
        f"Поверни ТІЛЬКИ JSON без пояснень."
    )

    ai = AIService()
    result = await ai.generate_json(prompt, account_id=account_id)
    if not isinstance(result, dict):
        raise ValueError("AI не зміг згенерувати персону")

    return result


__all__ = ["PRESETS", "BEHAVIOR_PRESETS", "OBSERVER_PRESET", "apply_preset", "list_presets", "generate_persona_via_ai"]
