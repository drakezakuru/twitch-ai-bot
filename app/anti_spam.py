"""Feature 7: Анти-флуд / per-user cooldown / caps / link / repeat фильтры.

Чисто in-memory детекторы — не требуют БД.
Каждое правило можно включить/выключить отдельно через настройки chat-аналайзера:

    per_user_cooldown_sec   (int, 0 = выкл)
    max_caps_pct            (int 0..100, 0/100 = выкл)
    block_links             (bool)
    block_repeat_count      (int, 0 = выкл; N подряд одинаковых сообщений → игнор)
    min_msg_len             (int, 0 = выкл)

Используется ChatAnalyzer'ом, чтобы решить: реагировать на сообщение или нет.
"""

from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass, field

LINK_RE = re.compile(r"(https?://|www\.|\.com|\.ru|\.net|\.io|\.tv|\.gg|\.org)\b", re.IGNORECASE)


@dataclass
class AntiSpamSettings:
    enabled: bool = False
    per_user_cooldown_sec: int = 0      # игнорировать ответы юзеру если он недавно уже триггерил бота
    max_caps_pct: int = 0               # 0/100 = выкл; иначе сколько % КАПСА в сообщении считается спамом
    block_links: bool = False
    block_repeat_count: int = 0         # 0 = выкл; иначе N подряд одинаковых сообщений → игнор
    min_msg_len: int = 0                # сообщения короче — игнор


@dataclass
class _ChannelState:
    user_last_replied: dict[str, float] = field(default_factory=dict)
    user_history: dict[str, deque] = field(default_factory=dict)


class AntiSpam:
    """Принимает (account_id, channel, user, text) и settings, говорит — реагировать или нет."""

    def __init__(self) -> None:
        self._state: dict[str, _ChannelState] = {}

    def _key(self, account_id: int, channel: str) -> str:
        return f"{account_id}:{channel}"

    def _state_for(self, account_id: int, channel: str) -> _ChannelState:
        key = self._key(account_id, channel)
        st = self._state.get(key)
        if st is None:
            st = _ChannelState()
            self._state[key] = st
        return st

    def should_skip(self, account_id: int, channel: str, user: str,
                    text: str, settings: AntiSpamSettings) -> tuple[bool, str]:
        """Возвращает (skip, reason). skip=True → бот игнорирует сообщение."""
        if not settings.enabled:
            return False, ""

        # Минимальная длина
        if settings.min_msg_len > 0 and len(text.strip()) < settings.min_msg_len:
            return True, f"слишком короткое (<{settings.min_msg_len})"

        # Капс
        if 0 < settings.max_caps_pct < 100:
            letters = [c for c in text if c.isalpha()]
            if letters:
                caps = sum(1 for c in letters if c.isupper())
                pct = (caps * 100) // len(letters)
                if pct >= settings.max_caps_pct and len(letters) >= 6:
                    return True, f"капс ({pct}% >= {settings.max_caps_pct}%)"

        # Ссылки
        if settings.block_links and LINK_RE.search(text):
            return True, "содержит ссылку"

        # Per-user cooldown
        if settings.per_user_cooldown_sec > 0:
            st = self._state_for(account_id, channel)
            last = st.user_last_replied.get(user.lower(), 0.0)
            if (time.time() - last) < settings.per_user_cooldown_sec:
                return True, f"per-user cooldown ({settings.per_user_cooldown_sec}s)"

        # Repeat detection (N подряд одинаковых сообщений от одного юзера)
        if settings.block_repeat_count >= 2:
            st = self._state_for(account_id, channel)
            hist = st.user_history.get(user.lower())
            if hist is None:
                hist = deque(maxlen=settings.block_repeat_count)
                st.user_history[user.lower()] = hist
            hist.append(text.strip().lower())
            if (len(hist) == settings.block_repeat_count
                    and len(set(hist)) == 1):
                return True, f"повтор {settings.block_repeat_count}x подряд"

        return False, ""

    def mark_replied(self, account_id: int, channel: str, user: str) -> None:
        """Запомнить, что мы только что ответили этому юзеру (для per-user cooldown)."""
        if not user:
            return
        st = self._state_for(account_id, channel)
        st.user_last_replied[user.lower()] = time.time()


# Singleton
anti_spam = AntiSpam()
