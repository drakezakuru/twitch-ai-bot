"""v10.4.7 Wave 4.6 — Live-detection mimicry.

Анализируем профиль ЖИВОГО чата (не бота) — средняя длина сообщения,
частота эмодзи, % CAPS, интервал между сообщениями — и подгоняем бота
под этот профиль. Anti-detection становится adaptive вместо статичной.

Дизайн:
- LiveProfile (dataclass) — текущий снимок профиля канала.
- LiveProfileCollector — per-channel хранит window N последних сообщений
  от не-ботов и пересчитывает профиль.
- mimicry_hint_block(profile) → строка для system prompt с инструкцией
  имитировать профиль.
- adjust_delay_jitter(profile, base_delay) — корректирует randomness задержки.
"""

from __future__ import annotations

import re
import statistics
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Iterable

EMOJI_RE = re.compile(
    r"[\U0001F300-\U0001FAFF\U00002700-\U000027BF\U0001F600-\U0001F64F]"
)


def _caps_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isupper()) / len(letters)


def _emoji_count(text: str) -> int:
    return len(EMOJI_RE.findall(text or ""))


@dataclass
class LiveProfile:
    """Усреднённый профиль живого чата."""

    avg_len: float = 30.0
    median_len: float = 25.0
    emoji_per_msg: float = 0.4
    caps_ratio: float = 0.05
    interval_sec_median: float = 8.0
    interval_sec_p90: float = 30.0
    samples: int = 0

    def to_dict(self) -> dict:
        return {
            "avg_len": round(self.avg_len, 1),
            "median_len": round(self.median_len, 1),
            "emoji_per_msg": round(self.emoji_per_msg, 2),
            "caps_ratio": round(self.caps_ratio, 3),
            "interval_sec_median": round(self.interval_sec_median, 1),
            "interval_sec_p90": round(self.interval_sec_p90, 1),
            "samples": self.samples,
        }


@dataclass
class LiveProfileCollector:
    """Per-channel collector — учитывает только сообщения от не-ботов.

    Caller (chat_analyzer) сам решает кто bot а кто нет (через bot_nicks set).
    """

    window: int = 200
    msgs: deque = field(default_factory=lambda: deque(maxlen=200))  # (ts, text)
    last_profile: LiveProfile = field(default_factory=LiveProfile)

    def feed(self, text: str, now: float | None = None) -> None:
        if not text or not text.strip():
            return
        now = now if now is not None else time.time()
        self.msgs.append((now, text[:300]))

    def compute(self) -> LiveProfile:
        if not self.msgs:
            return LiveProfile()
        lengths = [len(t) for _, t in self.msgs]
        emojis = [_emoji_count(t) for _, t in self.msgs]
        caps = [_caps_ratio(t) for _, t in self.msgs]
        intervals: list[float] = []
        prev_ts = None
        for ts, _ in self.msgs:
            if prev_ts is not None:
                d = ts - prev_ts
                if 0 < d < 300:
                    intervals.append(d)
            prev_ts = ts
        prof = LiveProfile(
            avg_len=float(sum(lengths)) / len(lengths),
            median_len=float(statistics.median(lengths)),
            emoji_per_msg=float(sum(emojis)) / len(emojis),
            caps_ratio=float(sum(caps)) / len(caps),
            interval_sec_median=float(statistics.median(intervals)) if intervals else 8.0,
            interval_sec_p90=float(_p90(intervals)) if intervals else 30.0,
            samples=len(self.msgs),
        )
        self.last_profile = prof
        return prof


def _p90(xs: Iterable[float]) -> float:
    xs = sorted(xs)
    if not xs:
        return 0.0
    idx = int(len(xs) * 0.9)
    if idx >= len(xs):
        idx = len(xs) - 1
    return xs[idx]


def mimicry_hint_block(profile: LiveProfile) -> str:
    """Возвращает блок для system prompt.

    Цель — заставить AI подстраивать стиль под профиль канала.
    """
    if profile.samples < 10:
        return ""  # мало данных
    parts = ["[Профиль живого чата канала — подстраивайся под него]"]
    # длина
    if profile.median_len < 15:
        parts.append("Сообщения короткие (1-3 слова). Не пиши длинные предложения.")
    elif profile.median_len < 40:
        parts.append("Сообщения средней длины (до 8-12 слов).")
    else:
        parts.append("Сообщения длинные, можно писать развёрнуто.")
    # эмодзи
    if profile.emoji_per_msg >= 0.7:
        parts.append("Чат активно использует эмодзи — добавляй 1-2 в ответ.")
    elif profile.emoji_per_msg <= 0.1:
        parts.append("Чат почти без эмодзи — НЕ используй эмодзи.")
    # CAPS
    if profile.caps_ratio >= 0.3:
        parts.append("В чате много CAPS — можно использовать CAPS для эмоций.")
    else:
        parts.append("CAPS-LOCK в чате редкий — пиши строчными.")
    return "\n".join(parts)


def adjust_delay_for_mimicry(profile: LiveProfile, base_mean: float = 60.0, base_sigma: float = 15.0) -> tuple[float, float]:
    """Корректирует параметры gaussian-задержки под темп канала.

    Возвращает (mean, sigma).
    """
    if profile.samples < 10:
        return base_mean, base_sigma
    # подстраиваем mean ближе к медианному интервалу
    target = max(15.0, min(180.0, profile.interval_sec_median * 2.5))
    new_mean = (base_mean + target) / 2
    # sigma — на основе разброса (p90 - median)
    spread = max(5.0, profile.interval_sec_p90 - profile.interval_sec_median)
    new_sigma = max(5.0, min(45.0, (base_sigma + spread) / 2))
    return new_mean, new_sigma
