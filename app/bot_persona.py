"""Bio / persona бота: структурированная биография на каждый аккаунт.

Хранится в ``accounts.persona_json`` (см. database.py). Сериализуется
через ``BotPersona.to_dict`` / ``from_json``.

В системный промпт вставляется через ``format_persona_for_prompt`` —
блок начинается с ``[Твоя личность]`` и описывает кто бот такой
(возраст, пол, любимые игры, увлечения, манера речи). Это даёт AI
структуру, на которую он опирается, без раздутого system_prompt.

Поля опциональные — пустая persona даёт пустую строку (т.е. ничего
не меняет относительно v10.4.3).
"""

from __future__ import annotations

import copy
import json
import random
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BotPersona:
    """Структурированная биография бота.

    Любое поле может быть пустым. Пустая ``BotPersona()`` → пустой блок
    в промпте.
    """

    name: str = ""
    age: int = 0  # 0 = не указан
    gender: str = ""  # "м" | "ж" | "" | произвольное
    location: str = ""
    occupation: str = ""

    personality: list[str] = field(default_factory=list)  # traits
    favorite_games: list[str] = field(default_factory=list)
    favorite_streamers: list[str] = field(default_factory=list)
    hobbies: list[str] = field(default_factory=list)

    speaking_style: str = ""  # "zoomer" | "casual" | "formal" | ...
    quirks: list[str] = field(default_factory=list)  # "часто пишет лол", "избегает CAPS"
    catchphrases: list[str] = field(default_factory=list)  # любимые слова/мемы
    memories: list[str] = field(default_factory=list)  # "я уже год смотрю этого стримера"

    background: str = ""  # свободный текст-биография

    # ── v11: Розширений характер ─────────────────────────────────
    humor_level: int = 50          # 0-100
    darkness_level: int = 10       # 0-100 (чорний гумор)
    crudeness_level: int = 0       # 0-100 (пошлість, мати)
    seriousness: int = 50          # 0-100 (0=тільки жарти, 100=ніколи не жартує)
    sarcasm_level: int = 30        # 0-100
    emotionality: int = 50         # 0-100
    emotion_intensity: int = 50   # 0-100 (інтенсивність емоцій)
    adult_humor: int = 0           # 0-100 (інтимний/вульгарний гумор)
    asterisk_emotes: bool = False  # *обиженно смотрит*
    observation_only: bool = False # тільки спостерігає, не пише
    canadian_mode: bool = False # вимкнути юмор/емоції
    contact_level: int = 50        # 0-100 (прив'язаність до стрімера)
    chat_affinity: int = 50        # 0-100 (прив'язаність до чату)
    auto_adjust_contact: bool = False
    dynamic_personality: bool = False  # сам змінює параметри під ситуацію
    mood_influence: int = 0        # 0-100 (наскільки настрій чату впливає)
    bounds: dict[str, tuple[int, int]] = field(default_factory=dict)  # e.g. {"humor": (30, 80)}

    # Тогли "AI вирішує" — якщо True, AI сам обирає рівень
    humor_enabled: bool = True
    sarcasm_enabled: bool = True
    darkness_enabled: bool = True
    crudeness_enabled: bool = True
    adult_enabled: bool = True
    emotionality_enabled: bool = True
    seriousness_enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "age": self.age,
            "gender": self.gender,
            "location": self.location,
            "occupation": self.occupation,
            "personality": list(self.personality),
            "favorite_games": list(self.favorite_games),
            "favorite_streamers": list(self.favorite_streamers),
            "hobbies": list(self.hobbies),
            "speaking_style": self.speaking_style,
            "quirks": list(self.quirks),
            "catchphrases": list(self.catchphrases),
            "memories": list(self.memories),
            "background": self.background,
            # v11 fields
            "humor_level": self.humor_level,
            "darkness_level": self.darkness_level,
            "crudeness_level": self.crudeness_level,
            "seriousness": self.seriousness,
            "sarcasm_level": self.sarcasm_level,
            "emotionality": self.emotionality,
            "emotion_intensity": self.emotion_intensity,
            "adult_humor": self.adult_humor,
            "asterisk_emotes": self.asterisk_emotes,
            "observation_only": self.observation_only,
            "canadian_mode": self.canadian_mode,
            "contact_level": self.contact_level,
            "chat_affinity": self.chat_affinity,
            "auto_adjust_contact": self.auto_adjust_contact,
            "dynamic_personality": self.dynamic_personality,
            "mood_influence": self.mood_influence,
            "humor_enabled": self.humor_enabled,
            "sarcasm_enabled": self.sarcasm_enabled,
            "darkness_enabled": self.darkness_enabled,
            "crudeness_enabled": self.crudeness_enabled,
            "adult_enabled": self.adult_enabled,
            "emotionality_enabled": self.emotionality_enabled,
            "seriousness_enabled": self.seriousness_enabled,
        }
        if self.bounds:
            d["bounds"] = {k: list(v) for k, v in self.bounds.items()}
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: Any) -> "BotPersona":
        if not isinstance(data, dict):
            return cls()
        bounds_raw = data.get("bounds", {})
        bounds = {}
        if isinstance(bounds_raw, dict):
            for k, v in bounds_raw.items():
                if isinstance(v, (list, tuple)) and len(v) == 2:
                    bounds[str(k)] = (int(v[0]), int(v[1]))
        return cls(
            name=str(data.get("name", "")),
            age=_safe_int(data.get("age")),
            gender=str(data.get("gender", "")),
            location=str(data.get("location", "")),
            occupation=str(data.get("occupation", "")),
            personality=_str_list(data.get("personality")),
            favorite_games=_str_list(data.get("favorite_games")),
            favorite_streamers=_str_list(data.get("favorite_streamers")),
            hobbies=_str_list(data.get("hobbies")),
            speaking_style=str(data.get("speaking_style", "")),
            quirks=_str_list(data.get("quirks")),
            catchphrases=_str_list(data.get("catchphrases")),
            memories=_str_list(data.get("memories")),
            background=str(data.get("background", "")),
            # v11 fields
            humor_level=_safe_int(data.get("humor_level", 50)),
            darkness_level=_safe_int(data.get("darkness_level", 10)),
            crudeness_level=_safe_int(data.get("crudeness_level", 0)),
            seriousness=_safe_int(data.get("seriousness", 50)),
            sarcasm_level=_safe_int(data.get("sarcasm_level", 30)),
            emotionality=_safe_int(data.get("emotionality", 50)),
            adult_humor=_safe_int(data.get("adult_humor", 0)),
            asterisk_emotes=bool(data.get("asterisk_emotes", False)),
            observation_only=bool(data.get("observation_only", False)),
            contact_level=_safe_int(data.get("contact_level", 50)),
            chat_affinity=_safe_int(data.get("chat_affinity", 50)),
            auto_adjust_contact=bool(data.get("auto_adjust_contact", False)),
            dynamic_personality=bool(data.get("dynamic_personality", False)),
            mood_influence=_safe_int(data.get("mood_influence", 0)),
            bounds=bounds,
            humor_enabled=bool(data.get("humor_enabled", True)),
            sarcasm_enabled=bool(data.get("sarcasm_enabled", True)),
            darkness_enabled=bool(data.get("darkness_enabled", True)),
            crudeness_enabled=bool(data.get("crudeness_enabled", True)),
            adult_enabled=bool(data.get("adult_enabled", True)),
            emotionality_enabled=bool(data.get("emotionality_enabled", True)),
            seriousness_enabled=bool(data.get("seriousness_enabled", True)),
        )

    @classmethod
    def from_json(cls, text: str | None) -> "BotPersona":
        if not text:
            return cls()
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return cls()
        return cls.from_dict(data)

    def is_empty(self) -> bool:
        base_empty = not any(
            [
                self.name,
                self.age,
                self.gender,
                self.location,
                self.occupation,
                self.personality,
                self.favorite_games,
                self.favorite_streamers,
                self.hobbies,
                self.speaking_style,
                self.quirks,
                self.catchphrases,
                self.memories,
                self.background,
            ]
        )
        # v11: не вважаємо порожньою якщо є хоча б один рівень характеру
        extended_empty = (
            self.humor_level == 50 and self.darkness_level == 10 and
            self.crudeness_level == 0 and self.sarcasm_level == 30 and
            self.adult_humor == 0 and self.seriousness == 50 and
            self.emotionality == 50 and self.contact_level == 50 and
            self.chat_affinity == 50
        )
        return base_empty and extended_empty

    def clamp(self) -> None:
        """Обмежує значення рівнів в межах bounds або 0-100."""
        fields = (
            "humor_level", "darkness_level", "crudeness_level",
            "seriousness", "sarcasm_level", "emotionality",
            "adult_humor", "contact_level", "chat_affinity",
        )
        for f in fields:
            v = getattr(self, f)
            lo, hi = self.bounds.get(f.replace("_level", ""), (0, 100))
            setattr(self, f, max(lo, min(hi, int(v))))

    def copy(self) -> "BotPersona":
        return copy.deepcopy(self)


def _str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if v is not None and str(v).strip()]
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return []


def _safe_int(value: Any) -> int:
    if value is None or value == "":
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def format_persona_for_prompt(persona: BotPersona, *, randomize_catchphrase: bool = True,
                              rng: random.Random | None = None) -> str:
    """Возвращает блок ``[Твоя личность]`` для system_prompt.

    Пустая persona → пустая строка.
    Если задан ``catchphrases`` и ``randomize_catchphrase=True`` — в блок
    подмешивается 1 случайная фраза, чтобы AI время от времени их
    использовал (а не постоянно). Это даёт «характер» без скриптованного
    выглядения.
    """
    if persona.is_empty():
        return ""

    lines: list[str] = ["[Твоя личность]"]
    if persona.name:
        lines.append(f"Тебя зовут {persona.name}.")
    bio_parts: list[str] = []
    if persona.age:
        bio_parts.append(f"тебе {persona.age}")
    if persona.gender:
        bio_parts.append(f"{persona.gender}")
    if persona.location:
        bio_parts.append(f"из {persona.location}")
    if persona.occupation:
        bio_parts.append(f"работаешь/учишься: {persona.occupation}")
    if bio_parts:
        lines.append("Ты " + ", ".join(bio_parts) + ".")

    if persona.personality:
        lines.append("Характер: " + ", ".join(persona.personality) + ".")
    if persona.favorite_games:
        lines.append("Любимые игры: " + ", ".join(persona.favorite_games) + ".")
    if persona.favorite_streamers:
        lines.append("Любимые стримеры: " + ", ".join(persona.favorite_streamers) + ".")
    if persona.hobbies:
        lines.append("Хобби: " + ", ".join(persona.hobbies) + ".")
    if persona.speaking_style:
        lines.append(f"Манера речи: {persona.speaking_style}.")
    if persona.quirks:
        lines.append("Особенности речи: " + "; ".join(persona.quirks) + ".")
    if persona.memories:
        lines.append("Что ты помнишь о себе: " + "; ".join(persona.memories) + ".")
    if persona.background:
        lines.append(f"Биография: {persona.background}")

    if persona.catchphrases:
        if randomize_catchphrase:
            r = rng or random
            picked = r.choice(persona.catchphrases)
            lines.append(f"Иногда используй (естественно, не каждое сообщение!) фразу: «{picked}».")
        else:
            lines.append("Любимые фразы (используй редко и к месту): " + "; ".join(persona.catchphrases) + ".")

    return "\n".join(lines)


def format_extended_persona_for_prompt(p: BotPersona) -> str:
    """Розширений блок з рівнями характеру для system_prompt.

    Повертає базовий блок + [Характер] з рівнями.
    """
    base = format_persona_for_prompt(p)
    if p.is_empty() and not p.dynamic_personality:
        return base

    extra: list[str] = []
    # Формуємо рядок з рівнями
    levels = []
    levels.append(f"гумор={p.humor_level}")
    levels.append(f"сарказм={p.sarcasm_level}")
    levels.append(f"серйозність={p.seriousness}")
    levels.append(f"емоційність={p.emotionality}")
    levels.append(f"adult={p.adult_humor}")
    levels.append(f"darkness={p.darkness_level}")
    if p.crudeness_level > 0:
        levels.append(f"пошлість={p.crudeness_level}")
    extra.append("[Характер] " + " ".join(levels))

    if p.asterisk_emotes:
        extra.append("Можеш використовувати *дії* типу *смущенно отводит взгляд*.")

    extra_block = "\n".join(extra)
    return base + "\n" + extra_block if base else extra_block


__all__ = [
    "BotPersona",
    "format_persona_for_prompt",
    "format_extended_persona_for_prompt",
]
