"""Smart-trigger: реактивная активация бота вместо таймера.

Модуль содержит pure-функции и лёгкий ``SpikeDetector`` со state-per-channel.
Используется из ``chat_analyzer.on_message`` и ``_auto_chat_loop``.

Триггеры (любой → форсируем генерацию ответа, обходя cooldown):

* **streamer_question** — стример сам написал в чат с ``?`` в конце.
  Бот реагирует как живой зритель: отвечает на вопрос.
* **chat_spike** — msg/min внезапно вырос (текущий ≥ ``mult`` × baseline).
  Что-то происходит — бот вступает.
* **vision_event** — vision-описание содержит «громкие» ключевые слова
  («kill», «win», «гг», «ого», «эпик», «вайп»). Бот реагирует на хайлайт.
* **silence_after_event** — vision_event сработал, чат после этого
  замолчал на ``silence_sec`` — бот добавляет реакцию первым.

Все детекторы можно выключить независимо.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Optional


# ---- streamer question ------------------------------------------------

_QUESTION_END_RE = re.compile(r"\?\s*$")


def is_streamer_question(author: str, channel: str, text: str) -> bool:
    """Стример сам спрашивает в чат? (Часто реакция стримера на чат.)"""
    if not author or not channel or not text:
        return False
    if author.lower() != channel.lower().lstrip("#"):
        return False
    return bool(_QUESTION_END_RE.search(text.strip()))


# ---- vision event -----------------------------------------------------

# Ключевые слова которые обычно говорят «случилось что-то яркое на стриме».
_VISION_EVENT_KEYWORDS = (
    "kill", "kills", "killed", "ace", "epic", "victory", "win", "won",
    "death", "died", "wipe", "wiped", "clutch", "headshot", "hs", "1v",
    "хайлайт", "хайлайтище", "победа", "проигрыш", "слив", "слили",
    "убил", "убили", "убит", "убитый", "ваншот", "ушатал",
    "ого", "вау", "wow", "омг", "omg", "пп", "гг", "gg",
    "крутая", "круто", "крут", "красава", "красавчик",
    "эпик", "эпично", "эпичный", "ультра", "пентакилл", "комбо",
    "loot", "лут", "клатч", "рейд босс", "босс упал", "raid boss",
)


def extract_vision_event(description: str) -> Optional[str]:
    """Возвращает первый матчнутый keyword или None."""
    if not description:
        return None
    low = description.lower()
    for kw in _VISION_EVENT_KEYWORDS:
        if kw in low:
            return kw
    return None


# ---- chat spike -------------------------------------------------------


@dataclass
class SpikeDetector:
    """Простой EWMA-based detector chat-spike.

    На каждом сообщении считаем msg/sec, обновляем baseline (EWMA). Если
    current >> baseline * mult — спайк. После спайка ставим cooldown,
    чтобы не триггериться повторно на одной и той же волне.
    """

    window_sec: float = 30.0
    mult: float = 2.5
    min_baseline: float = 0.2  # ниже — считаем «тихий чат», игнор
    spike_cooldown_sec: float = 60.0

    _timestamps: dict[str, list[float]] = field(default_factory=dict)
    _last_spike: dict[str, float] = field(default_factory=dict)

    def on_message(self, channel: str, *, now: float | None = None) -> None:
        ts = now if now is not None else time.monotonic()
        ch = channel.lower().lstrip("#")
        lst = self._timestamps.setdefault(ch, [])
        lst.append(ts)
        # Чистим хвост — нам не нужны древние записи (> 4× окно).
        cutoff = ts - self.window_sec * 4
        if len(lst) > 200:
            self._timestamps[ch] = [t for t in lst if t > cutoff]

    def msg_per_sec(self, channel: str, window_sec: float | None = None, *, now: float | None = None) -> float:
        ts = now if now is not None else time.monotonic()
        w = window_sec or self.window_sec
        ch = channel.lower().lstrip("#")
        lst = self._timestamps.get(ch, [])
        cutoff = ts - w
        recent = [t for t in lst if t > cutoff]
        return len(recent) / w if w > 0 else 0.0

    def detect(self, channel: str, *, now: float | None = None) -> bool:
        """Сравниваем «быстрое» окно (window_sec) с «медленным» (×4)."""
        ts = now if now is not None else time.monotonic()
        ch = channel.lower().lstrip("#")
        last = self._last_spike.get(ch, 0.0)
        if ts - last < self.spike_cooldown_sec:
            return False
        fast = self.msg_per_sec(ch, self.window_sec, now=ts)
        baseline = self.msg_per_sec(ch, self.window_sec * 4, now=ts)
        if baseline < self.min_baseline:
            return False
        if fast >= baseline * self.mult and fast > baseline:
            self._last_spike[ch] = ts
            return True
        return False


# ---- silence after highlight -----------------------------------------


@dataclass
class SilenceTracker:
    """Трекаем «тишину после хайлайта»: vision-event случился, чат
    после него замолчал на ``silence_sec`` секунд — пора подкинуть реплику.
    """

    silence_sec: float = 8.0  # сколько ждать тишины
    valid_window_sec: float = 60.0  # после события считаем актуальным эту дельту

    _last_event: dict[str, float] = field(default_factory=dict)
    _last_msg: dict[str, float] = field(default_factory=dict)
    _consumed: dict[str, float] = field(default_factory=dict)

    def on_vision_event(self, channel: str, *, now: float | None = None) -> None:
        ts = now if now is not None else time.monotonic()
        ch = channel.lower().lstrip("#")
        self._last_event[ch] = ts

    def on_chat_message(self, channel: str, *, now: float | None = None) -> None:
        ts = now if now is not None else time.monotonic()
        ch = channel.lower().lstrip("#")
        self._last_msg[ch] = ts

    def is_silent_after_event(self, channel: str, *, now: float | None = None) -> bool:
        ts = now if now is not None else time.monotonic()
        ch = channel.lower().lstrip("#")
        evt = self._last_event.get(ch, 0.0)
        if not evt:
            return False
        if ts - evt > self.valid_window_sec:
            return False
        # Уже выстрелили на этом событии — повторно не реагируем.
        if self._consumed.get(ch, 0.0) >= evt:
            return False
        last_msg = self._last_msg.get(ch, evt)
        # Тишина = после event пришло сообщение в окне ≥ silence_sec назад
        # ИЛИ вообще никаких сообщений после event и event сам стал ≥ silence_sec назад.
        latest = max(evt, last_msg)
        if ts - latest >= self.silence_sec:
            self._consumed[ch] = evt
            return True
        return False


__all__ = [
    "SilenceTracker",
    "SpikeDetector",
    "extract_vision_event",
    "is_streamer_question",
]
