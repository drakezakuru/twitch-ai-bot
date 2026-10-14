"""Attention Filter + Batch Buffer — фільтрує шум, батчити повідомлення, режими уваги.

Блок 7 плану v11:
- Режими уваги: everyone, streamer_only, chat_only, streamer_and_chat, custom
- Батчинг: збирає повідомлення протягом batch_window_sec, потім один AI-запит
- Noise filter: ігнорує +1, KEKW, однолітерні повідомлення тощо
- Cooldown per-bot: cooldown_after_reply_sec, max_replies_per_minute
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

# ── Noise patterns ────────────────────────────────────────────────

_NOISE_PATTERNS = [
    re.compile(r"^[+1]+$"),  # +1, +1+1+1, 111, etc.
    re.compile(r"^[-]+$"),
    re.compile(r"^_+$"),
    re.compile(r"^\.+$"),
    re.compile(r"^!+$"),
    re.compile(r"^_kekw$", re.IGNORECASE),
    re.compile(r"^[a-zA-Z]{1,2}$"),  # one-two letters
    re.compile(r"^[?]+$", re.IGNORECASE),  # ?, ??, ???
    re.compile(r"^[?&]+$", re.IGNORECASE),  # &?, &&
    # A standalone emote-like word is still meaningful chat input; only
    # punctuation/emoji floods should be discarded here.
    re.compile(r"^[\U0001F600-\U0001F64F]+$"),  # only emojis
    re.compile(r"^[\U0001F300-\U0001F5FF]+$"),  # emoji symbols
    re.compile(r"^[lL]{2,}$"),  # llll
    re.compile(r"^[хХxX]{2,}$"),  # хххх
]


def is_noise_message(text: str) -> bool:
    """Перевіряє чи є повідомлення шумом."""
    text = text.strip()
    if not text:
        return True
    if len(text) <= 1:
        return True
    for pattern in _NOISE_PATTERNS:
        if pattern.match(text):
            return True
    return False


# ── Batch Buffer ──────────────────────────────────────────────────

class BatchBuffer:
    """Буфер для батчингу повідомлень per (account_id, channel)."""

    def __init__(self):
        self._batches: dict[tuple[int, str], list[dict[str, Any]]] = {}
        self._timers: dict[tuple[int, str], asyncio.TimerHandle] = {}

    def add(self, account_id: int, channel: str, message: dict[str, Any]) -> None:
        key = (account_id, channel.lower())
        if key not in self._batches:
            self._batches[key] = []
        self._batches[key].append(message)

    def get_batch(self, account_id: int, channel: str) -> list[dict[str, Any]]:
        key = (account_id, channel.lower())
        return self._batches.pop(key, [])

    def start_timer(
        self, account_id: int, channel: str, callback: Any, delay: float
    ) -> None:
        key = (account_id, channel.lower())
        if key in self._timers:
            self._timers[key].cancel()
        loop = asyncio.get_event_loop()
        handle: asyncio.TimerHandle

        def run_callback() -> None:
            if self._timers.get(key) is handle:
                self._timers.pop(key, None)
            asyncio.ensure_future(callback())

        handle = loop.call_later(delay, run_callback)
        self._timers[key] = handle

    def has_messages(self, account_id: int, channel: str) -> bool:
        key = (account_id, channel.lower())
        return len(self._batches.get(key, [])) > 0


# ── Attention Filter ──────────────────────────────────────────────

class AttentionFilter:
    """Фільтр уваги — вирішує чи відповідати на батч повідомлень."""

    def __init__(self):
        self._reply_timestamps: dict[int, list[float]] = {}  # account_id -> [timestamps]
        self._cooldown_until: dict[tuple[int, str], float] = {}  # (account_id, channel) -> until

    def apply_filter(
        self,
        batch: list[dict[str, Any]],
        config: dict[str, Any],
        enabled_users: set[str] | None,
        streamer_nick: str,
    ) -> list[dict[str, Any]]:
        """Фільтрує батч за config (attention_mode, ignore_noise).

        О6 PLAN.md: ``reply_to_keywords`` + ``reply_keywords`` — повідомлення
        з ключовим словом проходить ККІЗЬ шум і режим (як тумблер
        «відповідати на ключові слова»)."""
        mode = config.get("attention_mode", "everyone")
        keywords = [w.strip().lower() for w in str(config.get("reply_keywords") or "").split(",") if w.strip()]
        kw_hit: set[int] = set()
        if config.get("reply_to_keywords", 0) and keywords:
            for m in batch:
                txt = str(m.get("text", "")).lower()
                if any(k in txt for k in keywords):
                    kw_hit.add(id(m))

        # Noise filter (повідомлення з ключовим словом не відсікається шумом)
        if config.get("ignore_noise", 1):
            filtered = [m for m in batch
                        if id(m) in kw_hit or not is_noise_message(m.get("text", ""))]
        else:
            filtered = list(batch)

        # Attention mode (ключове слово — pass-through)
        if mode == "streamer_only":
            filtered = [m for m in filtered
                        if m.get("author", "").lower() == streamer_nick.lower() or id(m) in kw_hit]
        elif mode == "chat_only":
            filtered = [m for m in filtered
                        if m.get("author", "").lower() != streamer_nick.lower() or id(m) in kw_hit]
        elif mode == "streamer_and_chat":
            # Тільки noise filter, без додаткового
            pass
        elif mode == "custom" and enabled_users is not None:
            filtered = [m for m in filtered
                        if m.get("author", "").lower() in enabled_users or id(m) in kw_hit]

        return filtered

    def is_on_cooldown(self, account_id: int, channel: str) -> bool:
        """Перевіряє чи бот на кулдауні."""
        key = (account_id, channel.lower())
        until = self._cooldown_until.get(key, 0)
        return time.time() < until

    def mark_replied(self, account_id: int, channel: str, cooldown_sec: float) -> None:
        """Позначає що бот відповів — встановлює кулдаун."""
        key = (account_id, channel.lower())
        self._cooldown_until[key] = time.time() + cooldown_sec

        # Track reply timestamps for max_replies_per_minute
        if account_id not in self._reply_timestamps:
            self._reply_timestamps[account_id] = []
        self._reply_timestamps[account_id].append(time.time())

    def can_reply(self, account_id: int, config: dict[str, Any]) -> bool:
        """Перевіряє max_replies_per_minute."""
        max_rpm = config.get("max_replies_per_minute", 3)
        timestamps = self._reply_timestamps.get(account_id, [])
        now = time.time()
        # Очищаємо старі таймстемпи (> 60 сек)
        cutoff = now - 60
        self._reply_timestamps[account_id] = [t for t in timestamps if t > cutoff]
        return len(self._reply_timestamps[account_id]) < max_rpm

    def build_batch_context(self, batch: list[dict[str, Any]]) -> str:
        """Будує контекст для AI з батчу повідомлень."""
        lines = []
        for msg in batch:
            ts = msg.get("timestamp", "")
            author = msg.get("author", "?")
            text = msg.get("text", "")
            lines.append(f"[{ts}] {author}: {text}")
        return "\n".join(lines)


# ── Singleton ─────────────────────────────────────────────────────

_batch_buffer: BatchBuffer | None = None
_attention_filter: AttentionFilter | None = None


def get_batch_buffer() -> BatchBuffer:
    global _batch_buffer
    if _batch_buffer is None:
        _batch_buffer = BatchBuffer()
    return _batch_buffer


def get_attention_filter() -> AttentionFilter:
    global _attention_filter
    if _attention_filter is None:
        _attention_filter = AttentionFilter()
    return _attention_filter


__all__ = [
    "is_noise_message",
    "BatchBuffer",
    "AttentionFilter",
    "get_batch_buffer",
    "get_attention_filter",
]
