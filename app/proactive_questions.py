"""v10.4.7 Wave 4.3 — Proactive question generation.

Когда тишина в чате — бот не пишет случайную фразу, а генерит вопрос
на основе vision-описания текущего кадра («что у тебя за билд?», «новый чел в кооп?»).

Дизайн:
- Pure helpers строят prompt для AI-вызова.
- `ProactiveQuestionTracker` хранит cooldown per-channel (не спамим).
- `should_generate_question(...)` — решает можно ли сейчас (есть vision, тишина, кулдаун).
- `build_question_prompt(...)` — собирает системный prompt для AI с vision-блоком.
- `extract_question_text(answer)` — выдёргивает финальный вопрос (sanitize).
"""

from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass


# Дефолтные fallback-шаблоны (если AI отвалился — не молчим).
FALLBACK_TEMPLATES = [
    "что щас делаешь?",
    "это новая игра?",
    "ты сколько уже играешь?",
    "че по плану дальше?",
    "это легко или душно?",
    "а кто-то уже выбил это?",
    "что за билд?",
    "это сложный момент?",
]


@dataclass
class ProactiveQuestionTracker:
    """Per-channel state cooldown для proactive вопросов."""

    cooldown_sec: float = 180.0
    min_silence_sec: float = 90.0  # тишина в чате
    last_emit: float = 0.0
    last_chat_at: float = 0.0
    last_vision: str = ""
    last_vision_at: float = 0.0

    def mark_chat(self, now: float | None = None) -> None:
        self.last_chat_at = now if now is not None else time.time()

    def mark_vision(self, vision_text: str, now: float | None = None) -> None:
        if not vision_text:
            return
        self.last_vision = vision_text[:500]
        self.last_vision_at = now if now is not None else time.time()

    def mark_emit(self, now: float | None = None) -> None:
        self.last_emit = now if now is not None else time.time()

    def can_emit(self, now: float | None = None) -> tuple[bool, str]:
        now = now if now is not None else time.time()
        if not self.last_vision:
            return False, "no vision context"
        if (now - self.last_emit) < self.cooldown_sec:
            return False, "cooldown"
        # тишина в чате: считаем что last_chat_at был давно
        silence = now - self.last_chat_at
        if silence < self.min_silence_sec:
            return False, f"chat active {int(silence)}s"
        # vision не устарел больше 5 минут
        if (now - self.last_vision_at) > 300:
            return False, "vision stale"
        return True, "ok"


def build_question_prompt(vision_text: str, persona_hint: str = "") -> tuple[str, str]:
    """Строит (system, user) prompts для AI.

    AI должен вернуть короткий русский вопрос, словно живой зритель,
    основанный на vision-кадре стрима. БЕЗ greetings, БЕЗ "@".
    """
    sys = (
        "Ты — обычный зритель Twitch. Видишь кадр стрима и пишешь короткий "
        "вопрос в чат — естественный, как живой человек, БЕЗ обращений, БЕЗ эмодзи, "
        "БЕЗ кавычек. ОДНО предложение, до 12 слов. "
        "Если на кадре игровой момент — спрашивай про геймплей. "
        "Если IRL — про окружение. Не приветствуй, не благодари."
    )
    if persona_hint:
        sys += f"\nPersona: {persona_hint[:300]}"
    usr = f"Кадр стрима: {vision_text[:500]}\n\nНапиши вопрос:"
    return sys, usr


def extract_question_text(answer: str) -> str:
    """Sanitize AI-ответа: одна строка, обрезаем кавычки и greetings."""
    if not answer:
        return ""
    text = answer.strip()
    # отрезаем «Вопрос:» / «Q:» если AI добавил
    text = re.sub(r"^(Вопрос|Q|Ответ)\s*[:\-]\s*", "", text, flags=re.IGNORECASE)
    # берём первую строку
    text = text.splitlines()[0].strip()
    # убираем обёрточные кавычки
    if len(text) >= 2 and text[0] in "\"«'" and text[-1] in "\"»'":
        text = text[1:-1].strip()
    # убираем @mentions если просочились
    text = re.sub(r"@\w+", "", text).strip()
    # обрезаем длину
    if len(text) > 140:
        text = text[:140].rsplit(" ", 1)[0]
    return text


def fallback_question() -> str:
    return random.choice(FALLBACK_TEMPLATES)
