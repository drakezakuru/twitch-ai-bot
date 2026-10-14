"""Twitch IRC bot client and message handling."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

import aiohttp
from twitchio.ext import commands

from app.irc.types import BotInstance
from app.per_bot_logging import get_chat_logger, get_bot_logger, log as plog

logger = logging.getLogger(__name__)


def parse_badges(message: Any) -> list[str]:
    """Извлекает имена бейджей чаттера из сообщения TwitchIO."""
    badges: list[str] = []
    try:
        author = getattr(message, "author", None)
        chatter_badges = getattr(author, "badges", None) if author else None
        if chatter_badges:
            badges = [badge.name for badge in chatter_badges if getattr(badge, "name", None)]
        elif getattr(message, "tags", None):
            raw_badges = message.tags.get("badges", "")
            badges = [badge.split("/", 1)[0] for badge in raw_badges.split(",") if badge]
    except Exception:
        badges = []
    return badges


class TwitchBotClient(commands.Bot):
    """TwitchIO-клиент отдельного бота для подключения к Twitch IRC через WebSocket."""

    def __init__(
        self,
        instance: BotInstance,
        on_ready: Callable[[BotInstance, str], Awaitable[None]] | None = None,
        on_message: Callable[[BotInstance, Any, list[str]], Awaitable[None]] | None = None,
        on_notice: Callable[[BotInstance, str, str | None, Any], Awaitable[None]] | None = None,
    ) -> None:
        try:
            super().__init__(
                token=instance.token,
                nick=instance.nickname,
                prefix="!",
                initial_channels=instance.channels,
            )
        except TypeError:
            super().__init__(
                client_id="dummy_twitch_client_id",
                prefix="!",
            )
        self._inst = instance
        self._on_ready = on_ready
        self._on_message = on_message
        self._on_notice = on_notice

    def _apply_proxy(self, session: Any) -> None:
        """Накладывает перехватчик proxy на aiohttp ClientSession бота.

        TwitchIO по умолчанию не имеет параметра proxy и подключается к
        Twitch IRC WebSocket и валидации напрямую с локального IP. Этот перехватчик
        динамически подставляет self._inst.proxy во все исходящие ws_connect и request.
        """
        if getattr(session, "_proxy_wrapped", False):
            return

        orig_ws_connect = session.ws_connect
        orig_request = session._request

        def _ws_connect(url: Any, *args: Any, **kwargs: Any) -> Any:
            proxy = getattr(self._inst, "proxy", "")
            if proxy and "proxy" not in kwargs:
                kwargs["proxy"] = proxy
            return orig_ws_connect(url, *args, **kwargs)

        def _request(method: Any, url: Any, *args: Any, **kwargs: Any) -> Any:
            proxy = getattr(self._inst, "proxy", "")
            if proxy and "proxy" not in kwargs:
                kwargs["proxy"] = proxy
            return orig_request(method, url, *args, **kwargs)

        session.ws_connect = _ws_connect
        session._request = _request
        session._proxy_wrapped = True

    async def start(self) -> None:
        """Переопределяет start(): накладывает proxy до старта соединения."""
        if not getattr(self._http, "session", None) or self._http.session.closed:
            self._http.session = aiohttp.ClientSession()
        self._apply_proxy(self._http.session)

        # Предотвращаем баг TwitchIO 2.10 (AttributeError при сбое раннего соединения до создания _keeper)
        conn = getattr(self, "_connection", None)
        if conn and getattr(conn, "_keeper", None) is None:
            conn._keeper = asyncio.create_task(asyncio.sleep(0))

        await super().start()

    async def close(self) -> None:
        """Безопасное закрытие соединения без исключений по незавершённым таскам."""
        conn = getattr(self, "_connection", None)
        if conn and getattr(conn, "_keeper", None) is None:
            conn._keeper = asyncio.create_task(asyncio.sleep(0))
        try:
            await super().close()
        except Exception as exc:
            logger.debug("[%s] Ошибка при вызове close() клиента: %s", self._inst.nickname, exc)

    async def event_ready(self) -> None:
        """Событие успешной авторизации и подключения к Twitch IRC."""
        old = self._inst.state
        self._inst.connected = True
        self._inst.state = "online"
        self._inst.last_error = ""
        logger.info("[%s] IRC подключён к: %s", self._inst.nickname, ", ".join(self._inst.channels))
        if self._on_ready:
            try:
                await self._on_ready(self._inst, old)
            except Exception as exc:
                logger.warning("[%s] Ошибка в on_ready: %s", self._inst.nickname, exc)

    async def event_message(self, message: Any) -> None:
        """Входящее сообщение из Twitch IRC чата."""
        if getattr(message, "echo", False):
            return

        chat_log = get_chat_logger(self._inst.nickname)
        author_name = getattr(getattr(message, "author", None), "name", "")
        content = getattr(message, "content", "")
        plog(chat_log, logging.INFO, "chat", "<%s> %s", author_name, content)

        badges = parse_badges(message)
        if self._on_message:
            try:
                await self._on_message(self._inst, message, badges)
            except Exception as exc:
                logger.error("[%s] Ошибка в обработчике сообщения: %s", self._inst.nickname, exc)

    async def event_notice(self, message: str, msg_id: str | None, channel: Any) -> None:
        """Серверный NOTICE от Twitch IRC."""
        ch_name = getattr(channel, "name", "") or ""
        bot_log = get_bot_logger(self._inst.nickname)
        plog(bot_log, logging.INFO, "notice", "NOTICE#%s #%s: %s", msg_id or "-", ch_name, message)
        if self._on_notice:
            try:
                await self._on_notice(self._inst, message, msg_id, channel)
            except Exception as exc:
                logger.warning("[%s] Ошибка в on_notice: %s", self._inst.nickname, exc)


def create_bot_client(
    instance: BotInstance,
    on_ready: Callable[[BotInstance, str], Awaitable[None]] | None = None,
    on_message: Callable[[BotInstance, Any, list[str]], Awaitable[None]] | None = None,
    on_notice: Callable[[BotInstance, str, str | None, Any], Awaitable[None]] | None = None,
) -> TwitchBotClient:
    """Создаёт экземпляр TwitchBotClient для заданного BotInstance."""
    return TwitchBotClient(instance, on_ready=on_ready, on_message=on_message, on_notice=on_notice)
