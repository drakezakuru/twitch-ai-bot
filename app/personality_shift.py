"""§9b BRAIN_PLAN: Personality Shift — лёгкая автономия. [DEPRECATED P8-C4]

P8-C4 (вердикт владельца 02.09): ручной Shift (карточка в Мозге, toggle/
интенсивность, GET/POST /shift) удалён; модуль оставлен только для внутренней
автоматики — временный сдвиг «raid» триггерится chat_analyzer'ом.
Новая эволюция характера — через learning («Обучение (предложения)»).

После сильных событий (raid, hype-тред, конфликт) — временный сдвиг
mood/emotionality (НЕ персоны!) на N минут. Восстанавливается по таймеру.
Тумблер интенсивности (0..2): 0 = выкл, 1 = мягкий, 2 = сильный.

Состояние держим in-memory + в БД (для восстановления после рестарта).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from app.database import get_db

logger = logging.getLogger(__name__)


SHIFT_KINDS = ("raid", "hype_thread", "conflict", "follow_spike", "sub_spike")


@dataclass
class ShiftState:
    account_id: int
    channel: str
    kind: str = ""
    intensity: int = 0         # 0..2
    mood_delta: float = 0.0    # -0.5..+0.5
    emotionality_delta: float = 0.0  # -0.3..+0.3
    started_at: float = 0.0
    expires_at: float = 0.0
    reason: str = ""

    def is_active(self, now: float | None = None) -> bool:
        if self.intensity <= 0:
            return False
        now = now if now is not None else time.time()
        return now < self.expires_at

    def remaining_sec(self, now: float | None = None) -> float:
        now = now if now is not None else time.time()
        return max(0.0, self.expires_at - now)


class PersonalityShiftManager:
    """In-memory state per (account_id, channel). Снапшот в БД."""

    def __init__(self) -> None:
        self._states: dict[tuple[int, str], ShiftState] = {}
        self._enabled: dict[tuple[int, str], bool] = {}
        self._intensity: dict[tuple[int, str], int] = {}

    @staticmethod
    def _key(account_id: int, channel: str) -> tuple[int, str]:
        return (int(account_id), (channel or "").lower().lstrip("#"))

    def is_enabled(self, account_id: int, channel: str) -> bool:
        return self._enabled.get(self._key(account_id, channel), False)

    def set_enabled(self, account_id: int, channel: str, enabled: bool) -> None:
        self._enabled[self._key(account_id, channel)] = bool(enabled)
        if not enabled:
            self._states.pop(self._key(account_id, channel), None)
            self._intensity.pop(self._key(account_id, channel), None)

    def get_intensity(self, account_id: int, channel: str) -> int:
        return int(self._intensity.get(self._key(account_id, channel), 0))

    def set_intensity(self, account_id: int, channel: str, intensity: int) -> None:
        try:
            v = max(0, min(2, int(intensity)))
        except (TypeError, ValueError):
            v = 0
        self._intensity[self._key(account_id, channel)] = v

    def trigger(
        self,
        account_id: int,
        channel: str,
        kind: str,
        *,
        duration_sec: int = 300,
        mood_delta: float = 0.0,
        emotionality_delta: float = 0.0,
        reason: str = "",
    ) -> Optional[ShiftState]:
        if kind not in SHIFT_KINDS:
            return None
        if not self.is_enabled(account_id, channel):
            return None
        intensity = self.get_intensity(account_id, channel)
        if intensity <= 0:
            return None
        # Эскалация интенсивности
        scale = {1: 0.6, 2: 1.0}.get(intensity, 0.5)
        now = time.time()
        # Если уже активен похожий — продлеваем (но не стакаем до безумия)
        key = self._key(account_id, channel)
        existing = self._states.get(key)
        if existing and existing.is_active(now) and existing.kind == kind:
            new_expires = now + min(duration_sec, 1800)  # cap 30 мин
            existing.expires_at = max(existing.expires_at, new_expires)
            existing.mood_delta = max(-0.5, min(0.5, existing.mood_delta + mood_delta * scale * 0.3))
            existing.emotionality_delta = max(-0.3, min(0.3, existing.emotionality_delta + emotionality_delta * scale * 0.3))
            existing.intensity = max(existing.intensity, intensity)
            return existing
        st = ShiftState(
            account_id=account_id,
            channel=channel.lower().lstrip("#"),
            kind=kind,
            intensity=intensity,
            mood_delta=max(-0.5, min(0.5, mood_delta * scale)),
            emotionality_delta=max(-0.3, min(0.3, emotionality_delta * scale)),
            started_at=now,
            expires_at=now + max(30, min(3600, int(duration_sec))),
            reason=(reason or "")[:200],
        )
        self._states[key] = st
        return st

    def get_active(self, account_id: int, channel: str) -> Optional[ShiftState]:
        key = self._key(account_id, channel)
        st = self._states.get(key)
        if not st:
            return None
        if st.is_active():
            return st
        # Протух — удаляем
        self._states.pop(key, None)
        return None

    def get_hint(self, account_id: int, channel: str) -> str:
        """Возвращает hint-строку для system_prompt, если shift активен."""
        st = self.get_active(account_id, channel)
        if not st:
            return ""
        remaining = int(st.remaining_sec() // 60)
        kind_ru = {
            "raid": "после рейда",
            "hype_thread": "хайп в треде",
            "conflict": "после конфликта",
            "follow_spike": "наплыв фолловеров",
            "sub_spike": "наплыв сабов",
        }.get(st.kind, st.kind)
        direction = "в сторону тепла/энергии" if st.mood_delta >= 0 else "в сторону сдержанности"
        return (
            f"[Personality shift active: {kind_ru}, ~{remaining} мин, "
            f"{direction}, intensity={st.intensity}/2]"
        )

    def to_dict(self, account_id: int, channel: str) -> dict:
        st = self.get_active(account_id, channel)
        return {
            "enabled": self.is_enabled(account_id, channel),
            "intensity": self.get_intensity(account_id, channel),
            "active": st.to_dict() if st else None,
        }


def state_to_dict(self) -> dict:  # type: ignore[no-redef]
    return {
        "kind": self.kind,
        "intensity": self.intensity,
        "mood_delta": self.mood_delta,
        "emotionality_delta": self.emotionality_delta,
        "started_at": self.started_at,
        "expires_at": self.expires_at,
        "remaining_sec": round(self.remaining_sec(), 1),
        "reason": self.reason,
    }


ShiftState.to_dict = state_to_dict  # type: ignore[attr-defined]


shift_manager = PersonalityShiftManager()

# §5 аудит 30.08: таблица personality_shift_state удалена как мёртвая
# (0 чтений/записей — состояние shift живёт в settings через менеджер выше).
