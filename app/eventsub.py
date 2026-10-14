"""Feature 3: EventSub WebSocket клиент.

Подписывается на события Twitch через WebSocket вместо IRC:
  - channel.follow
  - channel.subscribe
  - channel.raid
  - channel.cheer
  - channel.channel_points_custom_reward_redemption.add

При получении события вызывает callback, который смотрит таблицу `event_responses`
и отвечает в чат через bot_manager.

Включается из UI per-account. Требует TWITCH_CLIENT_ID/SECRET и USER token со скоупами:
  channel:read:subscriptions, moderator:read:followers, channel:read:redemptions, bits:read
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Awaitable

from app import twitch_credentials
from app.twitch_helix import _strip_oauth, get_user_id, is_helix_configured

logger = logging.getLogger(__name__)

EVENTSUB_WS_URL = "wss://eventsub.wss.twitch.tv/ws"

# (event_type, version, condition_extra_keys)
# Note: condition_extra_keys для channel.raid пуст, потому что у raid v1 condition
# имеет специальную форму: вместо broadcaster_user_id нужно from_broadcaster_user_id
# или to_broadcaster_user_id. Эта подмена делается в _subscribe_all (v10.4.3 fix).
SUBSCRIPTIONS = [
    ("channel.follow", "2", ["moderator_user_id"]),
    ("channel.subscribe", "1", []),
    ("channel.raid", "1", []),
    ("channel.cheer", "1", []),
    ("channel.channel_points_custom_reward_redemption.add", "1", []),
    # v10.4.5: predictions/polls — auto-vote (handler в server.py).
    ("channel.poll.begin", "1", []),
    ("channel.prediction.begin", "1", []),
]

EventCallback = Callable[[int, str, str, dict], Awaitable[None]]
# (account_id, event_type, channel, payload)


async def _chat_messages_enabled(account_id: int) -> bool:
    """v14: флаг accounts.eventsub_chat_messages (MODERATION_PLAN §3).

    При ошибке чтения БД возвращает False — message-события просто не подписываются.
    """
    try:
        from app.database import get_db
        db = await get_db()
        try:
            cur = await db.execute(
                "SELECT eventsub_chat_messages FROM accounts WHERE id = ?", (account_id,),
            )
            row = await cur.fetchone()
        finally:
            await db.close()
        return bool(row and row["eventsub_chat_messages"])
    except Exception:
        return False


class EventSubClient:
    """Один WebSocket-клиент на один аккаунт. Подписывается на события всех каналов аккаунта."""

    def __init__(self, account_id: int, nickname: str, token: str, channels: list[str], callback: EventCallback) -> None:
        self.account_id = account_id
        self.nickname = nickname
        self.token = _strip_oauth(token)
        self.channels = channels
        self.callback = callback
        self.session_id: str | None = None
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._processed_message_ids: dict[str, None] = {}
        self._reconnect_url: str | None = None
        self._awaiting_reconnect_welcome = False

    @property
    def is_running(self) -> bool:
        return bool(self._task and not self._task.done() and not self._stop.is_set())

    async def start(self) -> bool:
        if not is_helix_configured():
            logger.warning("[EventSub:%s] TWITCH_CLIENT_ID/SECRET не заданы — EventSub отключен", self.nickname)
            return False
        try:
            import websockets  # noqa: F401
        except ImportError:
            logger.warning("[EventSub:%s] websockets не установлен. pip install websockets", self.nickname)
            return False
        self._task = asyncio.create_task(
            self._run_loop(), name=f"eventsub-{self.account_id}"
        )
        return True

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run_loop(self) -> None:
        import websockets  # type: ignore[import-untyped]
        while not self._stop.is_set():
            try:
                url = self._reconnect_url or EVENTSUB_WS_URL
                async with websockets.connect(url, ping_interval=None) as ws:
                    logger.info("[EventSub:%s] WebSocket подключён", self.nickname)
                    async for raw_msg in ws:
                        if self._stop.is_set():
                            break
                        try:
                            msg = json.loads(raw_msg)
                        except Exception:
                            continue
                        await self._handle_message(msg)
                        if self._reconnect_url:
                            await self._handoff_connection(ws, websockets)
                            break
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("[EventSub:%s] connection error: %s, retry в 30сек", self.nickname, exc)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=30.0)
                    break
                except asyncio.TimeoutError:
                    continue

    async def _consume_socket(self, ws) -> None:
        async for raw_msg in ws:
            if self._stop.is_set():
                break
            try:
                msg = json.loads(raw_msg)
            except Exception:
                continue
            await self._handle_message(msg)

    async def _handoff_connection(self, old_ws, websockets_module) -> None:
        """Keep the old socket live until Twitch welcomes the replacement."""
        old_reader = asyncio.create_task(self._consume_socket(old_ws))
        try:
            while not self._stop.is_set() and self._reconnect_url:
                reconnect_url = self._reconnect_url
                try:
                    async with websockets_module.connect(reconnect_url, ping_interval=None) as new_ws:
                        welcomed = False
                        async for raw_msg in new_ws:
                            if self._stop.is_set():
                                break
                            try:
                                msg = json.loads(raw_msg)
                            except Exception:
                                continue
                            is_welcome = msg.get("metadata", {}).get("message_type") == "session_welcome"
                            await self._handle_message(msg)
                            if is_welcome and not welcomed:
                                welcomed = True
                                await old_ws.close()
                                await old_reader
                            elif welcomed and self._reconnect_url:
                                await self._handoff_connection(new_ws, websockets_module)
                                return
                        if welcomed:
                            return
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning(
                        "[EventSub:%s] reconnect handoff error: %s, retry в 30сек",
                        self.nickname,
                        exc,
                    )
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=30.0)
                except asyncio.TimeoutError:
                    continue
        finally:
            if not old_reader.done():
                old_reader.cancel()
                await asyncio.gather(old_reader, return_exceptions=True)

    async def _handle_message(self, msg: dict) -> None:
        meta = msg.get("metadata", {})
        msg_type = meta.get("message_type", "")
        payload = msg.get("payload", {})

        if msg_type == "session_welcome":
            session = payload.get("session", {})
            self.session_id = session.get("id")
            logger.info("[EventSub:%s] session_id=%s", self.nickname, self.session_id)
            if self._awaiting_reconnect_welcome:
                # Twitch переносит существующие WebSocket subscriptions в новую session.
                self._awaiting_reconnect_welcome = False
                self._reconnect_url = None
            else:
                await self._subscribe_all()

        elif msg_type == "notification":
            message_id = str(meta.get("message_id") or "")
            if message_id and message_id in self._processed_message_ids:
                logger.debug("[EventSub:%s] duplicate message ignored: %s", self.nickname, message_id)
                return
            sub = payload.get("subscription", {})
            event = payload.get("event", {})
            event_type = sub.get("type", "")
            event["_event_id"] = message_id
            event["_event_timestamp"] = str(meta.get("message_timestamp") or "")
            # v10.4.3: для channel.raid «канал» = откуда идёт рейд (from_broadcaster),
            # это нужно чтобы хендлер в server.py отвечал в правильном канале и мог
            # перевести бота за рейдом (см. raid_follow в server.py:on_eventsub_event).
            if event_type == "channel.raid":
                channel = (event.get("from_broadcaster_user_login")
                           or event.get("to_broadcaster_user_login", "")).lower()
            else:
                channel = (event.get("broadcaster_user_login")
                           or event.get("to_broadcaster_user_login", "")).lower()
            await self.callback(self.account_id, event_type, channel, event)
            if message_id:
                self._processed_message_ids[message_id] = None
                if len(self._processed_message_ids) > 2048:
                    self._processed_message_ids.pop(next(iter(self._processed_message_ids)))

        elif msg_type == "session_keepalive":
            return

        elif msg_type == "session_reconnect":
            session = payload.get("session", {})
            new_url = session.get("reconnect_url")
            logger.info("[EventSub:%s] reconnect requested: %s", self.nickname, new_url)
            if isinstance(new_url, str) and new_url:
                self._reconnect_url = new_url
                self._awaiting_reconnect_welcome = True
            else:
                logger.warning("[EventSub:%s] reconnect requested without reconnect_url", self.nickname)

        elif msg_type == "revocation":
            sub = payload.get("subscription", {})
            logger.warning("[EventSub:%s] revoked: %s, status=%s", self.nickname, sub.get("type"), sub.get("status"))

    async def _subscribe_all(self) -> None:
        if not self.session_id:
            return
        import httpx
        client_id = twitch_credentials.get_client_id()
        # v14 MODERATION_PLAN §3: message-события подписываются только если
        # флаг eventsub_chat_messages включён для аккаунта.
        subscriptions = list(SUBSCRIPTIONS)
        if await _chat_messages_enabled(self.account_id):
            subscriptions.append(("channel.chat.message", "1", []))
        async with httpx.AsyncClient(timeout=15.0) as client:
            headers = {
                "Authorization": f"Bearer {self.token}",
                "Client-Id": client_id,
                "Content-Type": "application/json",
            }
            for channel in self.channels:
                broadcaster_id = await get_user_id(channel, self.token)
                if not broadcaster_id:
                    logger.warning("[EventSub:%s] не нашёл user_id для #%s", self.nickname, channel)
                    continue
                moderator_id = await get_user_id(self.nickname, self.token)
                for event_type, version, extra_keys in subscriptions:
                    # v10.4.3 fix: channel.raid v1 не принимает broadcaster_user_id —
                    # нужно from_broadcaster_user_id (когда канал сам идёт в рейд).
                    # Это нужно, чтобы бот получил событие когда стример кидает рейд
                    # — и потом смог перейти за ним (server.py:on_eventsub_event).
                    if event_type == "channel.raid":
                        condition: dict[str, Any] = {"from_broadcaster_user_id": broadcaster_id}
                    else:
                        condition = {"broadcaster_user_id": broadcaster_id}
                    if event_type == "channel.chat.message":
                        if not moderator_id:
                            logger.warning("[EventSub:%s] не нашёл user_id бота для chat subscription", self.nickname)
                            continue
                        condition["user_id"] = moderator_id
                    missing_extra = [key for key in extra_keys if not moderator_id]
                    if missing_extra:
                        logger.warning(
                            "[EventSub:%s] пропускаю %s: нет %s",
                            self.nickname,
                            event_type,
                            ", ".join(missing_extra),
                        )
                        continue
                    for key in extra_keys:
                        condition[key] = moderator_id
                    try:
                        resp = await client.post(
                            "https://api.twitch.tv/helix/eventsub/subscriptions",
                            headers=headers,
                            json={
                                "type": event_type,
                                "version": version,
                                "condition": condition,
                                "transport": {"method": "websocket", "session_id": self.session_id},
                            },
                        )
                        if resp.status_code in (200, 202):
                            logger.info("[EventSub:%s] подписан: %s @ #%s", self.nickname, event_type, channel)
                        else:
                            logger.debug("[EventSub:%s] подписка %s @ #%s: %d %s",
                                         self.nickname, event_type, channel, resp.status_code, resp.text[:120])
                    except Exception as exc:
                        logger.warning("[EventSub:%s] subscribe error %s: %s", self.nickname, event_type, exc)


class EventSubManager:
    """Управляет EventSubClient'ами для всех включённых аккаунтов."""

    def __init__(self) -> None:
        self._clients: dict[int, EventSubClient] = {}
        self._callback: EventCallback | None = None

    def set_callback(self, callback: EventCallback) -> None:
        self._callback = callback

    async def start_for_account(self, account_id: int, nickname: str, token: str, channels: list[str]) -> bool:
        if not self._callback:
            return False
        existing = self._clients.get(account_id)
        if existing and existing.is_running:
            return False
        if existing:
            await existing.stop()
            self._clients.pop(account_id, None)
        client = EventSubClient(account_id, nickname, token, channels, self._callback)
        if not await client.start():
            return False
        self._clients[account_id] = client
        return True

    async def stop_for_account(self, account_id: int) -> bool:
        client = self._clients.pop(account_id, None)
        if not client:
            return False
        await client.stop()
        return True

    async def stop_all(self) -> None:
        for aid in list(self._clients):
            await self.stop_for_account(aid)

    def is_running(self, account_id: int) -> bool:
        client = self._clients.get(account_id)
        return bool(client and client.is_running)
