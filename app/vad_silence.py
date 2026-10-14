"""VAD-style silence detector for streamer audio (works on top of Whisper transcripts).

Идея:
  - после каждого Whisper-сегмента (или каждые N секунд опроса) мы помечаем
    `last_speech_ts = now`;
  - если с `last_speech_ts` прошло > silence_threshold_sec — стример молчит;
  - если ещё и в чате нет вопросов от бота на эту тему — выпускаем реплику "afk stream"
    (с cooldown, чтобы не спамить).

Это не "настоящий" VAD по аудио (для этого надо silero/webrtcvad), а более лёгкий
вариант: используем то, что у нас уже есть — Whisper-результаты из StreamVision.

Все функции — pure. Состояние держится в `SilenceWatcher` (per-account, per-channel).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterable


DEFAULT_AFK_MESSAGES = [
    "афк-стрим что ли?",
    "ало, ты где?",
    "стрим без стримера ха",
    "afk stream",
    "стример отошёл попить чай",
    "у нас тишина, стримера съели",
]


# --- pure helpers ----------------------------------------------------------


def silence_duration_sec(last_speech_ts: float, *, now: float | None = None) -> float:
    """Сколько секунд молчания накопилось."""
    if not last_speech_ts:
        return 0.0
    now = now if now is not None else time.time()
    return max(0.0, now - last_speech_ts)


def detect_silence(
    last_speech_ts: float,
    *,
    threshold_sec: float = 300.0,
    now: float | None = None,
) -> bool:
    """True если стример молчит дольше threshold."""
    return silence_duration_sec(last_speech_ts, now=now) >= threshold_sec


def has_speech_in_segment(segment: dict, *, min_chars: int = 2) -> bool:
    """Whisper-сегмент содержит реальную речь, а не только шум.

    Эвристика: текст после strip > min_chars и не состоит из одних многоточий/спецсимволов.
    """
    text = (segment.get("text") or "").strip() if isinstance(segment, dict) else str(segment or "").strip()
    if len(text) < min_chars:
        return False
    # одни знаки препинания / точки
    stripped = "".join(c for c in text if c.isalnum())
    return len(stripped) >= max(1, min_chars - 1)


def pick_afk_message(messages: Iterable[str] | None = None, *, rng=None) -> str:
    """Случайная AFK-фраза. Можно подменить список через UI."""
    import random as _r

    rng = rng or _r.Random()
    if messages is None:
        pool = list(DEFAULT_AFK_MESSAGES)
    else:
        pool = list(messages)
    if not pool:
        return "afk stream"
    return rng.choice(pool)


# --- stateful watcher ------------------------------------------------------


@dataclass
class SilenceWatcher:
    """Отслеживает периоды молчания стримера.

    Использование:
        w = SilenceWatcher(threshold_sec=300, cooldown_sec=600)
        # на каждом Whisper-сегменте:
        for seg in whisper_segments:
            w.feed_segment(seg)
        # периодически:
        if w.should_emit_afk():
            text = w.next_afk_message()
            ... отправляем в чат ...
            w.mark_emitted()
    """

    threshold_sec: float = 300.0
    cooldown_sec: float = 600.0  # не чаще раза в 10 минут
    last_speech_ts: float = 0.0
    last_emit_ts: float = 0.0
    total_silence_events: int = 0

    def feed_segment(self, segment, *, now: float | None = None) -> bool:
        """Возвращает True, если в сегменте есть речь."""
        now = now if now is not None else time.time()
        if has_speech_in_segment(segment):
            self.last_speech_ts = now
            return True
        return False

    def mark_speech(self, *, now: float | None = None) -> None:
        self.last_speech_ts = now if now is not None else time.time()

    def silence_for(self, *, now: float | None = None) -> float:
        return silence_duration_sec(self.last_speech_ts, now=now)

    def should_emit_afk(self, *, now: float | None = None) -> bool:
        if self.last_speech_ts == 0.0:
            # ещё ни одного речевого сегмента — не считаем что молчит,
            # возможно стрим только что начался без Whisper-данных.
            return False
        now = now if now is not None else time.time()
        if not detect_silence(self.last_speech_ts, threshold_sec=self.threshold_sec, now=now):
            return False
        if self.last_emit_ts and (now - self.last_emit_ts) < self.cooldown_sec:
            return False
        return True

    def mark_emitted(self, *, now: float | None = None) -> None:
        self.last_emit_ts = now if now is not None else time.time()
        self.total_silence_events += 1

    def reset_speech(self, *, now: float | None = None) -> None:
        """Сбрасываем, как будто только что заговорили (после длинной AFK-паузы)."""
        self.last_speech_ts = now if now is not None else time.time()

    def snapshot(self, *, now: float | None = None) -> dict:
        return {
            "last_speech_ts": self.last_speech_ts,
            "silence_sec": round(self.silence_for(now=now), 1),
            "threshold_sec": self.threshold_sec,
            "cooldown_sec": self.cooldown_sec,
            "silent": detect_silence(self.last_speech_ts, threshold_sec=self.threshold_sec, now=now),
            "events": self.total_silence_events,
        }
