"""Менеджер Twitch-ботов: управление несколькими аккаунтами одновременно."""

import asyncio
import logging
import os
import time
import traceback
from typing import Any

from twitchio.ext import commands

from app.security import decrypt_token
from app.per_bot_logging import get_bot_logger, get_chat_logger, log as plog
from app.irc import (
    BotInstance,
    classify_notice_rejection,
    resolve_proxy as _resolve_proxy,
    mask_proxy,
    classify_irc_send_error,
    create_bot_client,
    run_irc_loop,
    close_irc_connection,
    SEND_COOLDOWN_SEC,
    NOTICE_WAIT_SEC,
)

logger = logging.getLogger(__name__)


class TwitchBotManager:
    """Управляет несколькими Twitch-ботами одновременно."""

    # Минимальная пауза между отправками одного бота (план §5.2: cooldown 1–2 сек).
    SEND_COOLDOWN_SEC = 1.2
    # Owner report 27.09.2026: PRIVMSG(ECHO) в TwitchIO 2.x — локальная подделка
    # библиотеки (websocket.py: `send()` формирует "dummy"-эхо ДО реальной отправки
    # в сокет), она НЕ доказывает, что Twitch принял сообщение. Единственный
    # реальный сигнал сервера — настоящий NOTICE (msg_*), если отправку отклонили.
    # Ждём короткое окно после ch.send(), чтобы успеть его увидеть.
    NOTICE_WAIT_SEC = 0.6

    def __init__(self) -> None:
        self._bots: dict[int, BotInstance] = {}
        self._message_callbacks: list[Any] = []
        self._log_callback: Any = None
        self._health_callback: Any = None
        self._last_send_at: dict[int, float] = {}
        # account_id → {"channel", "msg_id", "message", "at"} — последний РЕАЛЬНЫЙ
        # NOTICE от сервера Twitch (не путать с локальным PRIVMSG(ECHO)).
        self._last_notice: dict[int, dict] = {}
        # OPS_PLAN §3: желаемое состояние (account_id → параметры запуска).
        # Watchdog сверяет его с фактическим и переподнимает упавшие таски.
        self._desired: dict[int, dict] = {}

    def set_log_callback(self, callback: Any) -> None:
        self._log_callback = callback

    def set_health_callback(self, callback: Any) -> None:
        """callback(account_id, nickname, old_state, new_state, error) — вызывается при смене health-состояния."""
        self._health_callback = callback

    async def _health(self, instance: BotInstance, old_state: str) -> None:
        if not self._health_callback or instance.state == old_state:
            return
        try:
            await self._health_callback(
                instance.account_id,
                instance.nickname,
                old_state,
                instance.state,
                instance.last_error,
            )
        except Exception as exc:
            logger.warning("health callback error: %s", exc)

    async def _log(
        self, account_id: int, channel: str, author: str, message: str,
        is_bot: bool = False, badges: list[str] | None = None,
        message_id: str = "", channel_id: str = "",
    ) -> None:
        if self._log_callback:
            await self._log_callback(
                account_id, channel, author, message, is_bot, badges=badges,
                message_id=message_id, channel_id=channel_id,
            )

    def _create_bot(self, instance: BotInstance) -> commands.Bot:
        manager = self

        async def _on_ready(inst: BotInstance, old_state: str) -> None:
            await manager._health(inst, old_state)

        async def _on_message(inst: BotInstance, message: Any, badges: list[str]) -> None:
            ch_name = getattr(getattr(message, "channel", None), "name", "")
            author_name = getattr(getattr(message, "author", None), "name", "")
            content = getattr(message, "content", "")
            await manager._log(
                inst.account_id,
                ch_name,
                author_name,
                content,
                is_bot=False,
                badges=badges,
                message_id=str(getattr(message, "id", "") or getattr(message, "tags", {}).get("id", "")),
                channel_id=str(getattr(message, "tags", {}).get("room-id", "")),
            )
            for cb in manager._message_callbacks:
                try:
                    await cb(inst, message)
                except Exception as exc:
                    logger.error("Callback error: %s", exc)

        async def _on_notice(inst: BotInstance, message: str, msg_id: str | None, channel: Any) -> None:
            ch_name = getattr(channel, "name", "") or ""
            manager._last_notice[inst.account_id] = {
                "channel": ch_name,
                "msg_id": msg_id or "",
                "message": message or "",
                "at": time.time(),
            }

        return create_bot_client(
            instance,
            on_ready=_on_ready,
            on_message=_on_message,
            on_notice=_on_notice,
        )

    # ---------- PLAN §9h: автозапись replay-сессии при старте/остановке бота ----------

    async def _replay_list(self) -> dict:
        from app.replay_debug import list_sessions
        return {"sessions": await list_sessions(limit=100)}

    async def _replay_auto_start(self, instance: BotInstance) -> None:
        """E (REWORK_PLAN): автозапись без дублей — если в канале уже идёт сессия,
        бот подключается к ней (attach) вместо создания своей копии."""
        try:
            from app.database import get_setting_bool, get_db
            # Q16 F5: явный выбор бота сильнее; NULL (не задано) — глобальный fallback
            db = await get_db()
            try:
                cur = await db.execute(
                    "SELECT replay_auto_record FROM accounts WHERE id = ?",
                    (instance.account_id,),
                )
                row = await cur.fetchone()
            finally:
                await db.close()
            own = row["replay_auto_record"] if row and "replay_auto_record" in row.keys() else None
            if own is None:
                if not await get_setting_bool("replay_auto_record", default=True):
                    return
            elif not own:
                return
            from app.replay_debug import start_session, get_active_session_by_channel
            from app.server import chat_analyzer
            channel = (instance.channels or [""])[0].lstrip("#").lower()
            if not channel:
                return
            existing_sid = await get_active_session_by_channel(channel)
            if existing_sid:
                instance.replay_session_id = existing_sid
                instance.replay_session_owner = False  # attach: не закрываем сессию при остановке
                chat_analyzer._replay_sessions[(instance.account_id, channel)] = existing_sid
                logger.info("[%s] §9h replay: подключён к активной сессии #%d (#%s)", instance.nickname, existing_sid, channel)
                return
            name = f"auto_{instance.nickname}_{time.strftime('%Y%m%d_%H%M')}"
            sid = await start_session(name=name, account_id=instance.account_id, channel=channel)
            instance.replay_session_id = sid
            instance.replay_session_owner = True
            chat_analyzer._replay_sessions[(instance.account_id, channel)] = sid
            logger.info("[%s] §9h автозапись replay-сессии #%d (#%s)", instance.nickname, sid, channel)
        except Exception as exc:
            logger.debug("replay auto start error: %s", exc)

    async def _replay_auto_end(self, instance: BotInstance) -> None:
        """E: закрывает сессию только её владелец; attach-боты просто отвязываются."""
        sid = getattr(instance, "replay_session_id", None)
        if not sid:
            return
        owner = getattr(instance, "replay_session_owner", True)
        instance.replay_session_id = None
        instance.replay_session_owner = True
        try:
            from app.replay_debug import end_session
            from app.server import chat_analyzer
            for key in [k for k, v in chat_analyzer._replay_sessions.items() if v == sid and k[0] == instance.account_id]:
                chat_analyzer._replay_sessions.pop(key, None)
            if owner:
                await end_session(sid)
                logger.info("[%s] §9h replay-сессия #%d закрыта (владелец)", instance.nickname, sid)
            else:
                logger.info("[%s] §9h replay: отвязан от сессии #%d", instance.nickname, sid)
        except Exception as exc:
            logger.debug("replay auto end error: %s", exc)

    async def start_bot(self, account_id: int, nickname: str, token: str, channels: list[str], proxy: str = "") -> bool:
        bot_log = get_bot_logger(nickname)
        # A pending connection owns the account as well.  Replacing it would
        # create a second Twitch connect attempt and break its normal backoff.
        if account_id in self._bots:
            plog(bot_log, logging.WARNING, "start", "[%s] Уже запущен", nickname)
            logger.warning("[%s] Уже запущен", nickname)
            return False

        # Расшифровываем токен (no-op если шифрование выключено)
        token = decrypt_token(token)

        # Нормализуем токен
        if not token.startswith("oauth:"):
            token = "oauth:" + token

        resolved_proxy = _resolve_proxy(proxy)
        if resolved_proxy:
            logger.info("[%s] Используется прокси: %s", nickname, _mask_proxy(resolved_proxy))

        instance = BotInstance(
            account_id=account_id,
            nickname=nickname,
            token=token,
            channels=channels,
            proxy=resolved_proxy,
        )

        bot = self._create_bot(instance)
        instance.bot = bot
        instance.task = asyncio.create_task(run_irc_loop(instance, health_callback=self._health))
        self._bots[account_id] = instance
        logger.info("[%s] Запущен для каналов: %s", nickname, channels)
        await self._replay_auto_start(instance)
        return True

    async def stop_bot(self, account_id: int) -> bool:
        instance = self._bots.get(account_id)
        if not instance:
            return False

        await self._replay_auto_end(instance)
        old = instance.state
        await close_irc_connection(instance)
        await self._health(instance, old)
        del self._bots[account_id]
        logger.info("[%s] Остановлен", instance.nickname)
        return True

    async def send_message(self, account_id: int, channel: str, text: str) -> bool:
        result = await self.send_message_detailed(account_id, channel, text)
        return bool(result["ok"])

    async def _decorate_outgoing(self, account_id: int, text: str) -> str:
        """PROMPT-BASE PB-3: декор исходящих сообщений на уровне панели (0 токенов).

        Эмодзи-префикс/суффикс бота оборачивают УЖЕ готовое сообщение перед
        отправкой в Twitch — LLM не участвует. Правила:
          * пустые настройки = no-op (дефолт, поведение не меняется);
          * команды (текст на «!») не декорируются;
          * повторного префикса/суффикса не наращиваем (идемпотентно).
        """
        text = text or ""
        if not text or text.startswith("!"):
            return text
        try:
            from app.server import chat_analyzer
            s = chat_analyzer.get_settings(int(account_id))
        except Exception:  # noqa: BLE001
            return text
        prefix = str(s.get("outgoing_emoji_prefix") or "").strip()
        suffix = str(s.get("outgoing_emoji_suffix") or "").strip()
        if prefix and not text.startswith(prefix):
            text = f"{prefix} {text}"
        if suffix and not text.endswith(suffix):
            text = f"{text} {suffix}"
        return text

    def _classify_send_error(self, exc: Exception) -> str:
        """Мэппинг исключения TwitchIO в machine-readable reason (план §5.2)."""
        return classify_irc_send_error(exc)

    async def send_message_detailed(self, account_id: int, channel: str, text: str) -> dict[str, object]:
        instance = self._bots.get(account_id)
        if not instance:
            logger.warning("[send] Bot %d not found in _bots", account_id)
            return {"ok": False, "reason": "bot_not_connected", "error": "Бот не подключён"}
        if not instance.bot or not instance.connected:
            logger.warning("[send] Bot %d not connected (state=%s, error=%s)", account_id, instance.state, instance.last_error)
            return {
                "ok": False,
                "reason": "bot_not_connected",
                "error": instance.last_error or "Бот ещё не подключён к чату",
            }

        ch = instance.bot.get_channel(channel)
        if ch is None:
            logger.warning("[send] [%s] Channel '%s' not found (connected_channels=%s)", instance.nickname, channel, [c for c in instance.bot.channels.keys()])
            return {"ok": False, "reason": "channel_not_connected", "error": f"Канал #{channel} не подключён"}

        loop = asyncio.get_running_loop()
        now = loop.time()
        last = self._last_send_at.get(account_id, 0.0)
        if now - last < self.SEND_COOLDOWN_SEC:
            wait = round(self.SEND_COOLDOWN_SEC - (now - last), 2)
            logger.warning("[send] [%s] Cooldown active: %.1fs remaining", instance.nickname, wait)
            return {"ok": False, "reason": "cooldown", "error": f"Cooldown {wait}s"}

        bot_log = get_bot_logger(instance.nickname)
        try:
            # PROMPT-BASE PB-3: эмодзи-декор панели (0 токенов) до отправки;
            # Twitch-лимит 500 считаем по уже декорированному тексту.
            send_text = await self._decorate_outgoing(account_id, text)

            # Q36: Случайная задержка (Humanizer Jitter), если включена для канала
            try:
                from app.bot_fleet import get_channel_fleet_settings, get_humanizer_jitter
                f_cfg = await get_channel_fleet_settings(channel)
                j_max = float(f_cfg.get("message_jitter_max") or 0.0)
                if j_max > 0:
                    j_min = float(f_cfg.get("message_jitter_min") or 1.0)
                    jitter = get_humanizer_jitter(channel, j_min, j_max)
                    await asyncio.sleep(jitter)
            except Exception:
                pass

            await ch.send(send_text[:500])
            self._last_send_at[account_id] = loop.time()
            sent_at = time.time()
            try:
                from app.bot_fleet import record_bot_spoken
                record_bot_spoken(account_id, channel)
            except Exception:
                pass
            plog(bot_log, logging.INFO, "send", "-> #%s: %s", channel, send_text[:100])
            logger.info("[%s] -> #%s: %s", instance.nickname, channel, send_text[:80])

            # Owner report 27.09.2026: TwitchIO подделывает PRIVMSG(ECHO) локально
            # (см. классификатор classify_notice_rejection выше) — ch.send() успешен,
            # даже если Twitch реально отклонил сообщение. Ждём короткое окно и
            # проверяем, не пришёл ли настоящий серверный NOTICE об отказе.
            await asyncio.sleep(self.NOTICE_WAIT_SEC)
            notice = self._last_notice.get(account_id)
            rejected = None
            if notice and notice["at"] >= sent_at and notice["channel"] == channel:
                rejected = classify_notice_rejection(notice["msg_id"])
            if rejected:
                old = instance.state
                instance.last_error = str(notice["message"])[:500]
                instance.last_error_at = time.time()
                await self._health(instance, old)
                plog(bot_log, logging.ERROR, "send_rejected",
                     "Twitch отклонил отправку (%s): %s", rejected, notice["message"])
                logger.error("[%s] Twitch отклонил отправку (%s): %s",
                             instance.nickname, rejected, notice["message"])
                return {
                    "ok": False,
                    "reason": "twitch_rejected",
                    "error": str(notice["message"])[:500],
                    "twitch_msg_id": rejected,
                }

            await self._log(account_id, channel, instance.nickname, send_text, is_bot=True)
            # confirmed=False всегда: Twitch не подтверждает обычные успешные
            # отправки положительно, только молчанием или отказом (NOTICE).
            return {"ok": True, "confirmed": False}
        except Exception as exc:
            old = instance.state
            instance.state = "error"
            instance.last_error = str(exc)[:500]
            instance.last_error_at = time.time()
            await self._health(instance, old)
            reason = self._classify_send_error(exc)
            plog(bot_log, logging.ERROR, "send_error", "Ошибка отправки (%s): %s", reason, exc)
            logger.error("[%s] Ошибка отправки (%s): %s", instance.nickname, reason, exc)
            return {"ok": False, "reason": reason, "error": str(exc)[:500]}

    async def join_channel(self, account_id: int, channel: str) -> bool:
        instance = self._bots.get(account_id)
        if not instance or not instance.bot or not instance.connected:
            return False
        try:
            await instance.bot.join_channels([channel])
            if channel not in instance.channels:
                instance.channels.append(channel)
            logger.info("[%s] Зашёл в #%s", instance.nickname, channel)
            return True
        except Exception as exc:
            logger.error("[%s] Ошибка входа в #%s: %s", instance.nickname, channel, exc)
            return False

    async def leave_channel(self, account_id: int, channel: str) -> bool:
        instance = self._bots.get(account_id)
        if not instance or not instance.bot or not instance.connected:
            return False
        try:
            await instance.bot.part_channels([channel])
            if channel in instance.channels:
                instance.channels.remove(channel)
            logger.info("[%s] Вышел из #%s", instance.nickname, channel)
            return True
        except Exception as exc:
            logger.error("[%s] Ошибка выхода из #%s: %s", instance.nickname, channel, exc)
            return False

    def get_status(self, account_id: int) -> dict:
        instance = self._bots.get(account_id)
        if not instance:
            return {"connected": False, "channels": []}
        return {
            "connected": instance.connected,
            "state": instance.state,
            "last_error": instance.last_error,
            "last_error_at": instance.last_error_at,
            "reconnect_count": instance.reconnect_count,
            "channels": instance.channels,
            "nickname": instance.nickname,
            "proxy": _mask_proxy(instance.proxy) if instance.proxy else "",
            "proxy_raw": instance.proxy or "",
        }

    def is_running(self, account_id: int) -> bool:
        """Есть ли инстанс бота (в т.ч. ещё подключается).

        Owner report 27.09.2026: `get_status().connected` == False, пока бот
        подключается, — этого мало, чтобы считать бота незанятым. Повторный
        /start на занятый аккаунт должен быть no-op, а не ошибкой.
        """
        return account_id in self._bots

    @property
    def instances(self) -> dict[int, BotInstance]:
        return self._bots

    def get_instance(self, account_id: int) -> BotInstance | None:
        return self._bots.get(account_id)

    def get_all_statuses(self) -> dict[int, dict]:
        return {aid: self.get_status(aid) for aid in self._bots}

    def on_message(self, callback: Any) -> None:
        self._message_callbacks.append(callback)

    def get_least_recently_spoken_bot(self, channel: str, candidate_ids: list[int] | None = None) -> int | None:
        """Q35: Автовыбор аккаунта, который дольше всего молчал на данном канале."""
        from app.bot_fleet import get_least_recently_spoken
        ch_clean = str(channel or "").lower().strip().lstrip("#")
        if candidate_ids is None:
            candidate_ids = [
                aid for aid, inst in self._bots.items()
                if inst.connected and ch_clean in [c.lower().lstrip("#") for c in inst.channels]
            ]
        return get_least_recently_spoken(ch_clean, candidate_ids)

    # ── OPS_PLAN §3: watchdog ──

    def get_desired(self, account_id: int) -> dict | None:
        """Возвращает текущие желаемые параметры бота (или None, если бот не должен работать)."""
        return self._desired.get(account_id)

    def set_desired(self, account_id: int, start_params: dict | None) -> None:
        """Регистрирует желаемое состояние: с параметрами → бот должен работать, None → остановлен."""
        if start_params is None:
            self._desired.pop(account_id, None)
        else:
            self._desired[account_id] = start_params

    async def watchdog_loop(self, interval: float = 60.0) -> None:
        """Раз в interval секунд сверяет желаемое состояние с фактическим.

        Перезапускает бота, если его task умер (крах), инстанс исчез или соединение
        зависло в ошибке надолго (>90 сек без восстановления).
        """
        import traceback as _tb
        while True:
            try:
                await asyncio.sleep(interval)
                now = time.time()
                for aid, params in list(self._desired.items()):
                    inst = self._bots.get(aid)
                    task_dead = (
                        inst is not None
                        and inst.task is not None
                        and inst.task.done()
                        and not inst.task.cancelled()
                    )
                    stuck_in_error = (
                        inst is not None
                        and not inst.connected
                        and inst.state == "error"
                        and (now - getattr(inst, "last_error_at", 0.0) > 90.0)
                    )
                    task_missing = inst is not None and inst.task is None
                    if inst is None or task_dead or stuck_in_error or task_missing:
                        reason = (
                            "задача умерла"
                            if task_dead
                            else ("завис в ошибке >90с" if stuck_in_error else "инстанс отсутствует")
                        )
                        logger.warning("[watchdog] бот %s требует автовосстановления (%s) — переподнять", aid, reason)
                        try:
                            from app.bot_logs import log_per_bot
                            await log_per_bot(
                                aid, "", "system",
                                f"Watchdog: автовосстановление бота ({reason})", level="warning",
                            )
                        except Exception:
                            pass
                        if inst is not None:
                            try:
                                await self.stop_bot(aid)
                            except Exception:
                                pass
                        await self.start_bot(
                            aid, params["nickname"], params["token"],
                            params["channels"], proxy=params.get("proxy", ""),
                        )
            except asyncio.CancelledError:
                return
            except Exception:
                logger.warning("watchdog error: %s", _tb.format_exc())
                await asyncio.sleep(interval)

    async def stop_all(self) -> None:
        for account_id in list(self._bots.keys()):
            await self.stop_bot(account_id)


def _mask_proxy(p: str) -> str:
    """Маскирует пароль в proxy-URL для логов."""
    return mask_proxy(p)
