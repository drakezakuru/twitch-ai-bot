"""Модуль подключения и взаимодействия ботов с Twitch IRC."""
from __future__ import annotations

from app.irc.types import (
    BotInstance,
    classify_notice_rejection,
    resolve_proxy,
    mask_proxy,
    classify_irc_send_error,
    SEND_COOLDOWN_SEC,
    NOTICE_WAIT_SEC,
)
from app.irc.client import TwitchBotClient, create_bot_client, parse_badges
from app.irc.connection import run_irc_loop, close_irc_connection

__all__ = [
    "BotInstance",
    "classify_notice_rejection",
    "resolve_proxy",
    "mask_proxy",
    "classify_irc_send_error",
    "SEND_COOLDOWN_SEC",
    "NOTICE_WAIT_SEC",
    "TwitchBotClient",
    "create_bot_client",
    "parse_badges",
    "run_irc_loop",
    "close_irc_connection",
]
