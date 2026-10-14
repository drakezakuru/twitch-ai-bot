"""Mood engine — настроение бота, накапливаемое от реакции чата.

Идея:
  - после каждого ответа бота смотрим последующие сообщения чата (N штук, ~30 секунд);
  - оцениваем sentiment (используя app.sentiment.classify);
  - агрегируем в EMA-mood [-1..1];
  - mood влияет на:
      - temperature генерации (позитив → выше, токсик → ниже)
      - self-throttle (если очень токсично — замолкаем на cooldown_sec)
      - выбор стиля (можно добавить позже: разные persona под mood)

Все функции — pure, состояние держится в `MoodTracker` (per-account, per-channel).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

try:
    from app.sentiment import classify as sentiment_classify
except Exception:  # pragma: no cover
    def sentiment_classify(text: str) -> str:  # type: ignore
        return "neutral"


SENTIMENT_TO_SCORE = {
    "positive": 1.0,
    "support": 0.8,
    "laugh": 0.6,
    "neutral": 0.0,
    "question": 0.1,
    "negative": -0.7,
    "toxic": -1.0,
    "spam": -0.3,
}


# --- pure helpers ----------------------------------------------------------


def score_message(text: str, classifier=sentiment_classify) -> float:
    """Возвращает skalar [-1..1] для одного сообщения."""
    if not text:
        return 0.0
    try:
        label = classifier(text)
    except Exception:
        label = "neutral"
    return float(SENTIMENT_TO_SCORE.get(label, 0.0))


def mood_to_temperature(mood: float, *, base: float = 0.8, span: float = 0.3) -> float:
    """Переводит mood [-1..1] в temperature ≈ base ± span.

    Позитив → выше (бот веселее, креативнее).
    Токсик → ниже (бот сдержаннее, чтобы не нагнетать).
    """
    return max(0.1, min(2.0, base + mood * span))


def mood_label(mood: float) -> str:
    """Человечный лейбл (для UI / логов)."""
    if mood >= 0.5:
        return "happy"
    if mood >= 0.15:
        return "good"
    if mood >= -0.15:
        return "neutral"
    if mood >= -0.5:
        return "tense"
    return "toxic"


def should_self_throttle(mood: float, *, threshold: float = -0.5) -> bool:
    """Если mood ниже порога — рекомендуем замолчать."""
    return mood <= threshold


# --- stateful tracker ------------------------------------------------------


@dataclass
class MoodTracker:
    """Накапливает sentiment-EMA per (account, channel).

    Использование:
        tr = MoodTracker(alpha=0.25)
        # после каждого user-msg:
        tr.feed("nice", classifier=sentiment_classify)
        # перед генерацией:
        temp = mood_to_temperature(tr.mood)
        if tr.is_throttled(): skip()
        # после ответа бота можно увеличить вес следующих сообщений как "реакция":
        tr.mark_bot_response()
    """

    alpha: float = 0.25
    throttle_threshold: float = -0.5
    throttle_cooldown_sec: float = 120.0  # 2 минуты замолкаем при mood ≤ threshold
    reaction_window_sec: float = 30.0  # окно реакции после ответа бота

    mood: float = 0.0
    last_bot_response_ts: float = 0.0
    throttle_until_ts: float = 0.0
    samples: int = 0

    def feed(self, text: str, *, now: float | None = None, classifier=sentiment_classify) -> float:
        """Кормит трекер одним сообщением чата. Возвращает текущее mood."""
        if not text:
            return self.mood
        score = score_message(text, classifier=classifier)
        # Усиливаем вес сообщений в окне реакции после бот-ответа
        now = now if now is not None else time.time()
        weight = 1.0
        if self.last_bot_response_ts and (now - self.last_bot_response_ts) <= self.reaction_window_sec:
            weight = 1.8
        effective = max(-1.0, min(1.0, score * weight))
        self.mood = self.alpha * effective + (1.0 - self.alpha) * self.mood
        self.mood = max(-1.0, min(1.0, self.mood))
        self.samples += 1
        # Если mood упал в токсик-зону — взводим throttle
        if should_self_throttle(self.mood, threshold=self.throttle_threshold):
            self.throttle_until_ts = max(self.throttle_until_ts, now + self.throttle_cooldown_sec)
        return self.mood

    def mark_bot_response(self, *, now: float | None = None) -> None:
        self.last_bot_response_ts = now if now is not None else time.time()

    def is_throttled(self, *, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        return now < self.throttle_until_ts

    def label(self) -> str:
        return mood_label(self.mood)

    def temperature(self, base: float = 0.8, span: float = 0.3) -> float:
        return mood_to_temperature(self.mood, base=base, span=span)

    def snapshot(self) -> dict:
        return {
            "mood": round(self.mood, 3),
            "label": self.label(),
            "samples": self.samples,
            "throttled": self.is_throttled(),
            "throttle_until_ts": self.throttle_until_ts,
        }

    def reset(self) -> None:
        self.mood = 0.0
        self.samples = 0
        self.throttle_until_ts = 0.0
        self.last_bot_response_ts = 0.0
