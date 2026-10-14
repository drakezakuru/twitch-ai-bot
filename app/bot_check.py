"""Transient Twitch bot checks used by the owner panel."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from twitchio.ext import commands

from app.security import decrypt_token
from app.twitch_helix import validate_oauth_token_status


DEFAULT_CHECK_MESSAGE = "✅ проверка связи [ник]"


class ProbeError(RuntimeError):
    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = (detail or reason)[:300]


class TwitchCheckProbe:
    """One temporary IRC connection that never changes persisted bot state."""

    def __init__(self, account: dict[str, Any], channel: str) -> None:
        token = decrypt_token(str(account.get("token") or ""))
        if token and not token.startswith("oauth:"):
            token = f"oauth:{token}"
        self.channel = channel
        self._ready = asyncio.Event()
        self._message = asyncio.Event()
        self._task: asyncio.Task | None = None
        outer = self

        class ProbeBot(commands.Bot):
            async def event_ready(self) -> None:
                outer._ready.set()

            async def event_message(self, message: Any) -> None:
                if getattr(message, "echo", False):
                    return
                name = getattr(getattr(message, "channel", None), "name", "")
                if str(name).lower().lstrip("#") == outer.channel:
                    outer._message.set()

        self.bot = ProbeBot(
            token=token,
            nick=str(account.get("nickname") or ""),
            prefix="!",
            initial_channels=[channel],
        )

    async def connect(self, timeout: float) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        self._task = asyncio.create_task(self.bot.start())
        ready_task = asyncio.create_task(self._ready.wait())
        done, _ = await asyncio.wait(
            {self._task, ready_task}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED,
        )
        if ready_task in done and self._ready.is_set():
            while asyncio.get_running_loop().time() < deadline:
                if self.bot.get_channel(self.channel) is not None:
                    return
                await asyncio.sleep(0.1)
            raise ProbeError("join_timeout")
        ready_task.cancel()
        if self._task in done:
            try:
                self._task.result()
            except Exception as exc:
                raise ProbeError("join_failed", str(exc)) from exc
        raise ProbeError("join_timeout")

    async def wait_for_message(self, timeout: float) -> bool:
        try:
            await asyncio.wait_for(self._message.wait(), timeout=timeout)
            return True
        except TimeoutError:
            return False

    async def send(self, text: str) -> dict[str, Any]:
        target = self.bot.get_channel(self.channel)
        if target is None:
            return {"ok": False, "reason": "channel_not_connected"}
        try:
            await target.send(text[:500])
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "reason": "send_rejected", "error": str(exc)[:300]}

    async def close(self) -> None:
        try:
            await self.bot.close()
        finally:
            if self._task and not self._task.done():
                self._task.cancel()
                await asyncio.gather(self._task, return_exceptions=True)


@dataclass
class _PreparedCheck:
    result: dict[str, Any]
    probe: Any | None = None


def _base_result(account: dict[str, Any], channel: str) -> dict[str, Any]:
    return {
        "account_id": int(account.get("id") or 0),
        "nickname": str(account.get("nickname") or ""),
        "channel": channel,
        "token_status": "not_run",
        "join_status": "not_run",
        "read_status": "not_run",
        "send_status": "not_run",
        "result": "error",
        "reason": "bot_not_found" if account.get("missing") else "not_run",
    }


async def _prepare(
    account: dict[str, Any],
    channel: str,
    *,
    validator: Callable[[str], Awaitable[dict[str, Any]]],
    probe_factory: Callable[[dict[str, Any], str], Any],
    connect_timeout: float,
) -> _PreparedCheck:
    result = _base_result(account, channel)
    if account.get("missing"):
        return _PreparedCheck(result)
    token = decrypt_token(str(account.get("token") or ""))
    token_result = await validator(token)
    result["token_status"] = str(token_result.get("status") or "unknown")
    if result["token_status"] != "valid":
        result["reason"] = "token_expired" if result["token_status"] == "expired" else "token_unknown"
        return _PreparedCheck(result)
    probe = probe_factory(account, channel)
    try:
        await probe.connect(connect_timeout)
    except asyncio.CancelledError:
        await probe.close()
        raise
    except ProbeError as exc:
        result["join_status"] = "error"
        result["reason"] = exc.reason
        if exc.detail != exc.reason:
            result["detail"] = exc.detail
        await probe.close()
        return _PreparedCheck(result)
    except Exception as exc:
        result["join_status"] = "error"
        result["reason"] = "join_failed"
        result["detail"] = str(exc)[:300]
        await probe.close()
        return _PreparedCheck(result)
    result["join_status"] = "online"
    result["reason"] = "not_run"
    return _PreparedCheck(result, probe)


async def run_bot_check(
    accounts: list[dict[str, Any]],
    channel: str,
    message_template: str = DEFAULT_CHECK_MESSAGE,
    *,
    read_timeout: float = 45.0,
    connect_timeout: float = 15.0,
    send_interval: float = 2.5,
    validator: Callable[[str], Awaitable[dict[str, Any]]] = validate_oauth_token_status,
    probe_factory: Callable[[dict[str, Any], str], Any] = TwitchCheckProbe,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    send_message: bool = False,
) -> list[dict[str, Any]]:
    """Validate and probe accounts without persisting the selected test channel.

    Q07/DEC-OWNER-011: контрольное сообщение опционально (по умолчанию выкл).
    Проверка = OAuth-валидация + IRC join + чтение чата; без отправки бот ничего
    не пишет в реальный чат."""

    prepared = await asyncio.gather(*(
        _prepare(
            account, channel, validator=validator, probe_factory=probe_factory,
            connect_timeout=connect_timeout,
        )
        for account in accounts
    ))
    active = [item for item in prepared if item.probe is not None]
    try:
        reads = await asyncio.gather(*(
            item.probe.wait_for_message(read_timeout) for item in active
        ))
        for item, confirmed in zip(active, reads):
            item.result["read_status"] = "confirmed" if confirmed else "no_messages"

        if not send_message:
            # Q07: пассивная проверка — без записи в чат; подтверждение = реальное
            # сообщение из чата за окно ожидания (DEC-BULK-007).
            for item in active:
                if item.result["read_status"] == "confirmed":
                    item.result.update(result="success", reason="ok")
                else:
                    item.result.update(result="not_confirmed", reason="no_messages")
            return [item.result for item in prepared]

        for index, item in enumerate(active):
            nickname = item.result["nickname"]
            sent = await item.probe.send(message_template.replace("[ник]", nickname))
            if sent.get("ok"):
                item.result["send_status"] = "sent"
                if item.result["read_status"] == "confirmed":
                    item.result.update(result="success", reason="ok")
                else:
                    item.result.update(result="not_confirmed", reason="no_messages")
            else:
                item.result["send_status"] = "error"
                item.result["reason"] = str(sent.get("reason") or "send_rejected")
                if sent.get("error"):
                    item.result["detail"] = str(sent["error"])[:300]
            if index < len(active) - 1:
                await sleep(send_interval)
    finally:
        await asyncio.gather(*(item.probe.close() for item in active), return_exceptions=True)
    return [item.result for item in prepared]

