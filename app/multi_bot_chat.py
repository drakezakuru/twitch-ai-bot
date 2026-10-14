"""Multi-bot роlёvка: боты на одном канале могут переписываться друг с другом.

Идея:
  - помимо обычной фильтрации `ignore_other_bots`, есть **friendly_bots** list —
    юзернеймы дружественных ботов (как правило — твои же боты на других аккаунтах);
  - когда от friendly-bot прилетает сообщение, наш бот может ответить
    с реалистичной задержкой (15-40 сек по умолчанию + gauss);
  - анти-дубль / анти-пинг-понг: не отвечаем чаще чем раз в `reply_cooldown_sec`
    на одного и того же friendly-bot; не отвечаем на свои собственные ответы.

Pure functions для решения, отвечать ли. Состояние — `FriendlyChatTracker` per channel.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Iterable


# --- pure helpers ----------------------------------------------------------


def normalize_nick(nick: str) -> str:
    return (nick or "").strip().lstrip("@").lower()


def is_friendly_bot(nick: str, friendly_nicks: Iterable[str]) -> bool:
    """True если ник присутствует в списке friendly ботов (case-insensitive)."""
    n = normalize_nick(nick)
    if not n:
        return False
    return any(normalize_nick(f) == n for f in friendly_nicks)


def should_reply_to_friendly(
    *,
    nick: str,
    text: str,
    friendly_nicks: Iterable[str],
    own_nick: str = "",
    reply_probability: float = 0.6,
    rng=None,
) -> bool:
    """Решаем, стоит ли отвечать на сообщение от friendly bot.

    - Не отвечаем себе.
    - Отвечаем только если nick в friendly_nicks.
    - С шансом reply_probability (default 60%).
    - Пустые сообщения игнорируем.
    """
    import random as _r

    if not text or not text.strip():
        return False
    n = normalize_nick(nick)
    o = normalize_nick(own_nick)
    if o and n == o:
        return False
    if not is_friendly_bot(nick, friendly_nicks):
        return False
    rng = rng or _r.Random()
    return rng.random() < max(0.0, min(1.0, reply_probability))


def reply_delay_seconds(
    *,
    min_sec: float = 15.0,
    max_sec: float = 40.0,
    rng=None,
) -> float:
    """Случайная задержка [min_sec..max_sec] — имитирует время "печати" живого зрителя."""
    import random as _r

    rng = rng or _r.Random()
    a = max(0.0, min(min_sec, max_sec))
    b = max(a, max_sec)
    return rng.uniform(a, b)


def format_friendly_context(messages: list[dict], *, max_messages: int = 5) -> str:
    """Форматирует последние сообщения friendly ботов в блок для prompt.

    messages = [{nick, text, ts}, ...]
    """
    if not messages:
        return ""
    items = messages[-max_messages:]
    parts = ["[Друзья в чате (другие боты)]"]
    for m in items:
        nick = (m.get("nick") or "?").strip()
        text = (m.get("text") or "").strip().replace("\n", " ")
        if len(text) > 160:
            text = text[:157] + "…"
        parts.append(f"  {nick}: {text}")
    parts.append("[/Друзья в чате]")
    return "\n".join(parts)


# --- stateful tracker ------------------------------------------------------


@dataclass
class FriendlyChatTracker:
    """Состояние per (account, channel).

    Хранит:
      - последние сообщения от friendly ботов (для контекста)
      - cooldown по парам (replier_nick → last_reply_ts) — анти-пинг-понг
    """

    friendly_nicks: list[str] = field(default_factory=list)
    own_nick: str = ""
    reply_probability: float = 0.6
    reply_cooldown_sec: float = 90.0
    min_delay_sec: float = 15.0
    max_delay_sec: float = 40.0
    history_size: int = 20

    recent_messages: list[dict] = field(default_factory=list)
    last_reply_to: dict[str, float] = field(default_factory=dict)

    def set_friendly_nicks(self, nicks: Iterable[str]) -> None:
        self.friendly_nicks = [normalize_nick(n) for n in nicks if n and n.strip()]

    def observe(self, nick: str, text: str, *, ts: float | None = None) -> None:
        """Просто запоминает сообщение friendly-бота для контекста."""
        if not is_friendly_bot(nick, self.friendly_nicks):
            return
        ts = ts if ts is not None else time.time()
        self.recent_messages.append({"nick": normalize_nick(nick), "text": text or "", "ts": ts})
        if len(self.recent_messages) > self.history_size:
            self.recent_messages = self.recent_messages[-self.history_size:]

    def can_reply_now(self, nick: str, *, now: float | None = None) -> bool:
        """Не на кулдауне ли пара (we, nick)?"""
        n = normalize_nick(nick)
        if not n:
            return False
        if self.reply_cooldown_sec <= 0:
            return True
        last = self.last_reply_to.get(n, 0.0)
        now = now if now is not None else time.time()
        return (now - last) >= self.reply_cooldown_sec

    def decide(
        self,
        nick: str,
        text: str,
        *,
        now: float | None = None,
        rng=None,
    ) -> bool:
        """Полное решение: friendly + cooldown + probability."""
        if not should_reply_to_friendly(
            nick=nick,
            text=text,
            friendly_nicks=self.friendly_nicks,
            own_nick=self.own_nick,
            reply_probability=self.reply_probability,
            rng=rng,
        ):
            return False
        if not self.can_reply_now(nick, now=now):
            return False
        return True

    def mark_replied(self, nick: str, *, now: float | None = None) -> None:
        n = normalize_nick(nick)
        if not n:
            return
        self.last_reply_to[n] = now if now is not None else time.time()

    def get_delay_seconds(self, *, rng=None) -> float:
        return reply_delay_seconds(
            min_sec=self.min_delay_sec,
            max_sec=self.max_delay_sec,
            rng=rng,
        )

    def context_block(self, *, max_messages: int = 5) -> str:
        return format_friendly_context(self.recent_messages, max_messages=max_messages)

    def snapshot(self) -> dict:
        return {
            "friendly_nicks": list(self.friendly_nicks),
            "own_nick": self.own_nick,
            "reply_probability": self.reply_probability,
            "cooldown_sec": self.reply_cooldown_sec,
            "messages_observed": len(self.recent_messages),
            "active_replies": len(self.last_reply_to),
        }
