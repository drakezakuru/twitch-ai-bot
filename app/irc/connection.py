"""Twitch IRC connection lifecycle and reconnect loop."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable

from app.irc.types import BotInstance
from app.per_bot_logging import get_bot_logger, log as plog

logger = logging.getLogger(__name__)


async def run_irc_loop(
    instance: BotInstance,
    health_callback: Callable[[BotInstance, str], Awaitable[None]] | None = None,
) -> None:
    """Запускает и поддерживает непрерывный цикл подключения бота к Twitch IRC.

    При разрыве соединения выполняет экспоненциальный backoff и переподключение.
    """
    bot = instance.bot
    if bot is None:
        raise RuntimeError(f"BotInstance {instance.nickname} has no bot client assigned")

    nickname = instance.nickname
    channels = instance.channels
    retry = 0
    bot_log = get_bot_logger(nickname)
    plog(bot_log, logging.INFO, "start", "Запуск бота %s (каналы: %s)", nickname, channels)

    async def _notify_health(old_state: str) -> None:
        if health_callback:
            try:
                await health_callback(instance, old_state)
            except Exception as exc:
                logger.warning("[%s] Health callback error: %s", nickname, exc)

    try:
        while True:
            try:
                old = instance.state
                instance.state = "connecting"
                await _notify_health(old)
                plog(bot_log, logging.INFO, "connect", "Подключение к Twitch IRC...")
                await bot.start()
                retry = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                old = instance.state
                instance.connected = False
                instance.state = "error"
                instance.last_error = str(exc)[:500]
                instance.last_error_at = time.time()
                instance.reconnect_count += 1
                await _notify_health(old)

                # Live Failover: если у бота был прокси и включен авто-переключатель
                if instance.proxy:
                    try:
                        from app.proxy_pool import get_proxy_pool_settings, failover_bot_proxy
                        s = await get_proxy_pool_settings()
                        if s.get("auto_failover", True):
                            fo = await failover_bot_proxy(instance.account_id, reason=str(exc)[:200])
                            if fo.get("ok"):
                                new_url = fo.get("new_proxy_url") or fo.get("new_proxy")
                                instance.proxy = new_url
                                if instance.bot and getattr(instance.bot, "_http", None) and getattr(instance.bot._http, "session", None):
                                    try:
                                        await instance.bot._http.session.close()
                                    except Exception:
                                        pass
                                retry = 0
                                plog(bot_log, logging.WARNING, "failover", "🔄 Авто-замена прокси: %s -> %s", fo.get("old_proxy"), fo.get("new_proxy"))
                                logger.warning("[%s] 🔄 Прокси бота заменен на %s", nickname, fo.get("new_proxy"))
                    except Exception as fo_err:
                        logger.debug("[%s] Failover error: %s", nickname, fo_err)

                retry = min(retry + 1, 6)
                delay = min(60, 2 ** retry)
                plog(bot_log, logging.ERROR, "error", "Ошибка соединения: %s; reconnect через %ss", exc, delay)
                logger.error("[%s] Ошибка соединения: %s; reconnect через %ss", nickname, exc, delay)
                await asyncio.sleep(delay)
    except asyncio.CancelledError:
        old = instance.state
        instance.connected = False
        instance.state = "offline"
        await _notify_health(old)
        raise


async def close_irc_connection(instance: BotInstance) -> None:
    """Безопасно останавливает клиент бота и отменяет фоновую задачу подключения."""
    if instance.bot:
        try:
            await instance.bot.close()
        except Exception as exc:
            logger.warning("Ошибка при закрытии IRC-клиента [%s]: %s", instance.nickname, exc)

    if instance.task and not instance.task.done():
        instance.task.cancel()

    instance.connected = False
    instance.state = "offline"
