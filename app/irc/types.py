"""Twitch IRC types, constants, and classifiers."""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any

from twitchio.ext import commands

# Минимальная пауза между отправками одного бота (план §5.2: cooldown 1–2 сек).
SEND_COOLDOWN_SEC = 1.2

# Owner report 27.09.2026: PRIVMSG(ECHO) в TwitchIO 2.x — локальная подделка
# библиотеки (websocket.py: `send()` формирует "dummy"-эхо ДО реальной отправки
# в сокет), она НЕ доказывает, что Twitch принял сообщение. Единственный
# реальный сигнал сервера — настоящий NOTICE (msg_*), если отправку отклонили.
# Ждём короткое окно после ch.send(), чтобы успеть его увидеть.
NOTICE_WAIT_SEC = 0.6


@dataclass
class BotInstance:
    account_id: int
    nickname: str
    token: str
    channels: list[str] = field(default_factory=list)
    proxy: str = ""
    bot: commands.Bot | None = None
    task: asyncio.Task | None = None
    connected: bool = False
    state: str = "connecting"
    last_error: str = ""
    last_error_at: float = 0.0
    reconnect_count: int = 0  # OPS_PLAN §3: сколько раз бот переподключался после обрыва
    replay_session_id: int | None = None  # PLAN §9h: активная автозапись сессии
    replay_session_owner: bool = True  # E: True = сессия открыта этим ботом (закрывает при стопе)


def resolve_proxy(account_proxy: str = "") -> str:
    """Возвращает proxy URL для аккаунта или DEFAULT_PROXY из env, или ''."""
    p = (account_proxy or "").strip()
    if p:
        return p
    return os.getenv("DEFAULT_PROXY", "").strip()


def mask_proxy(p: str) -> str:
    """Маскирует пароль в proxy-URL для логов."""
    if not p:
        return ""
    if "@" in p:
        scheme_creds, host = p.rsplit("@", 1)
        if "://" in scheme_creds:
            scheme, _ = scheme_creds.split("://", 1)
            return f"{scheme}://***@{host}"
    return p


def classify_notice_rejection(msg_id: str | None) -> str | None:
    """Owner report 27.09.2026: ложный успех отправки — панель считала отправку
    подтверждённой по локальному PRIVMSG(ECHO), а Twitch реально отклонял
    сообщение молча. Единственный настоящий сигнал отказа от сервера — NOTICE
    с msg-id вида ``msg_*`` (см. https://dev.twitch.tv/docs/irc/msg-id/):
    msg_rejected, msg_banned, msg_channel_suspended, msg_ratelimit и т.п.
    Прочие NOTICE (host_on, room_mods и подобные информационные) отправку не
    затрагивают и отказом не считаются.
    """
    if not msg_id:
        return None
    mid = str(msg_id).strip().lower()
    if mid.startswith("msg_"):
        return mid
    return None


def classify_irc_send_error(exc: Exception) -> str:
    """Мэппинг исключения TwitchIO в machine-readable reason (план §5.2)."""
    s = str(exc).lower()
    if "login authentication failed" in s or "improperly formatted auth" in s or "invalid oauth" in s:
        return "oauth_expired"
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return "network_error"
    if any(k in s for k in ("timeout", "timed out", "connectionreset", "connection reset",
                            "oserror", "socket", "unavailable", "network")):
        return "network_error"
    return "twitch_error"
