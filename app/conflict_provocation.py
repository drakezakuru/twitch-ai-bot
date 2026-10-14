"""PLAN §9l — Conflict Provocation (полная версия: bait + «добивание»).

Решение владельца 28.08.2026: реализовать полную версию — бот провоцирует
конфликтного чатера вопросом-подначкой (bait), а когда тот отвечает — «добивает»
спор острой репликой (escalation). Настраивается вместе с эмоциями персоны
(интенсивность), включается одним тумблером.

Guardrails (обязательные, из плана §9l):
- фича ВЫКЛЮЧЕНА по умолчанию (per-account `conflict_provocation_enabled`);
- интенсивность 0-100 масштабирует ехидность промпта, но не отменяет запретов;
- реплики просят насмешку над АРГУМЕНТОМ/ситуацией, не над личностью:
  без оскорблений по внешности/семье/национальности/полу, без угроз и травли;
- кулдауны: на канал (CHANNEL_COOLDOWN_SEC) и на пользователя (USER_COOLDOWN_SEC);
- bait живёт WINDOW_SEC — после этого «добивание» не срабатывает;
- чат_analyzer вызывает контур только после observation_only/silent_analysis/
  word_filter/anti-spam проверок (guardrails входной точки).

Состояние — в памяти процесса (как _chat_rate_tracker): панель не переживает
рестарт в середине bait-фазы, что безопасно: просто не будет «добивания».
"""
from __future__ import annotations

import logging
import random
import time

logger = logging.getLogger(__name__)


class ConflictProvocation:
    WINDOW_SEC = 180            # сколько секунд ждём ответ на bait
    CHANNEL_COOLDOWN_SEC = 240  # не чаще одного bait на канал
    USER_COOLDOWN_SEC = 900     # не чаще одного bait на пользователя

    def __init__(self) -> None:
        self._bait_pending: dict[tuple[int, str, str], float] = {}
        self._user_last_bait: dict[tuple[int, str, str], float] = {}
        self._channel_last_bait: dict[tuple[int, str], float] = {}

    # ---------- фаза 1: bait ----------

    def check_bait(self, account_id: int, channel: str, author: str,
                   settings: dict, negative: bool) -> bool:
        """True — стоит отправить провокационный вопрос-подначку."""
        if not settings.get("conflict_provocation_enabled"):
            return False
        if settings.get("observation_only") or settings.get("silent_mode"):
            return False
        try:
            intensity = int(settings.get("conflict_provocation_intensity") or 0)
        except (TypeError, ValueError):
            intensity = 0
        if intensity <= 0:
            return False
        if not author:
            return False
        now = time.time()
        ck = (int(account_id), (channel or "").lower())
        uk = (int(account_id), (channel or "").lower(), author.lower())
        if now - self._channel_last_bait.get(ck, 0.0) < self.CHANNEL_COOLDOWN_SEC:
            return False
        if now - self._user_last_bait.get(uk, 0.0) < self.USER_COOLDOWN_SEC:
            return False
        # Триггер: конфликт (негатив) — основной путь; изредка и на нейтральных
        # сообщениях при высокой интенсивности (фоновая подначка).
        if negative:
            chance = 0.25 + intensity / 200.0  # 40 → ~45%
        else:
            chance = intensity / 1000.0        # 40 → 4%
        return random.random() < chance

    def mark_bait(self, account_id: int, channel: str, author: str) -> None:
        now = time.time()
        ck = (int(account_id), (channel or "").lower())
        uk = (int(account_id), (channel or "").lower(), (author or "").lower())
        self._bait_pending[uk] = now
        self._user_last_bait[uk] = now
        self._channel_last_bait[ck] = now

    # ---------- фаза 2: «добивание» ----------

    def check_escalation(self, account_id: int, channel: str, author: str) -> bool:
        """True — автор отвечает на свежий bait: пора «добить» (state расходуется)."""
        if not author:
            return False
        uk = (int(account_id), (channel or "").lower(), author.lower())
        ts = self._bait_pending.get(uk)
        if ts is None:
            return False
        self._bait_pending.pop(uk, None)
        if time.time() - ts > self.WINDOW_SEC:
            return False
        return True

    # ---------- промпты ----------

    def _bounds_text(self) -> str:
        return (
            "Жёсткие границы: насмешка над АРГУМЕНТОМ или СИТУАЦИЕЙ, а не над человеком. "
            "Без оскорблений внешности, семьи, национальности, пола, религии; без угроз, "
            "травли и призывов; без мата грубее уровня персоны."
        )

    def bait_instruction(self, author: str, text: str, settings: dict) -> str:
        intensity = int(settings.get("conflict_provocation_intensity") or 40)
        return (
            f"[Режим провокации в спорах, интенсивность {intensity}/100]\n"
            f"Чатер {author} написал: «{str(text)[:200]}». Ответь ОДНИМ коротким "
            f"(до 15 слов) ехидным ВОПРОСОМ-подначкой в сторону {author} — чем выше "
            f"интенсивность, тем настойчивее и едче вопрос. {self._bounds_text()}"
        )

    def escalation_instruction(self, author: str, text: str, settings: dict) -> str:
        intensity = int(settings.get("conflict_provocation_intensity") or 40)
        return (
            f"[Режим провокации: добивание спора, интенсивность {intensity}/100]\n"
            f"{author} ответил на твой провокационный вопрос: «{str(text)[:200]}». "
            f"Добей спор одной короткой (до 18 слов) острой репликой — едкий вывод "
            f"или ироничное подведение итога по АРГУМЕНТУ {author}. Чем выше "
            f"интенсивность, тем острее тон. {self._bounds_text()}"
        )


_instance: ConflictProvocation | None = None


def get_conflict_provocation() -> ConflictProvocation:
    global _instance
    if _instance is None:
        _instance = ConflictProvocation()
    return _instance


__all__ = ["ConflictProvocation", "get_conflict_provocation"]
