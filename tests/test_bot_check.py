from __future__ import annotations

import asyncio

import pytest

from app.bot_check import ProbeError, run_bot_check


class FakeProbe:
    def __init__(self, account, channel, events, *, read=True, connect_error="", send=None):
        self.account = account
        self.channel = channel
        self.events = events
        self.read = read
        self.connect_error = connect_error
        self.send_result = send or {"ok": True}

    async def connect(self, timeout):
        self.events.append(("connect", self.account["id"], self.channel, timeout))
        if self.connect_error:
            raise ProbeError(self.connect_error)

    async def wait_for_message(self, timeout):
        self.events.append(("read", self.account["id"], timeout))
        return self.read

    async def send(self, text):
        self.events.append(("send", self.account["id"], text))
        return self.send_result

    async def close(self):
        self.events.append(("close", self.account["id"]))


@pytest.mark.asyncio
async def test_check_isolated_results_and_sequential_messages():
    events = []
    probes = {1: {"read": True}, 2: {"read": False}}

    async def valid(_token):
        return {"status": "valid"}

    async def no_sleep(seconds):
        events.append(("sleep", seconds))

    results = await run_bot_check(
        [
            {"id": 1, "nickname": "one", "token": "secret-one"},
            {"id": 2, "nickname": "two", "token": "secret-two"},
        ],
        "test_channel",
        "ping [ник]",
        validator=valid,
        probe_factory=lambda account, channel: FakeProbe(account, channel, events, **probes[account["id"]]),
        read_timeout=0.01,
        send_interval=2.5,
        sleep=no_sleep,
        send_message=True,
    )

    assert [item["result"] for item in results] == ["success", "not_confirmed"]
    assert [event for event in events if event[0] == "send"] == [
        ("send", 1, "ping one"),
        ("send", 2, "ping two"),
    ]
    assert ("sleep", 2.5) in events
    assert all("secret" not in str(item) for item in results)


@pytest.mark.asyncio
async def test_partial_failures_do_not_stop_other_accounts():
    events = []

    async def validator(token):
        if token == "expired":
            return {"status": "expired"}
        if token == "unknown":
            return {"status": "unknown"}
        return {"status": "valid"}

    def factory(account, channel):
        if account["id"] == 4:
            return FakeProbe(account, channel, events, connect_error="join_timeout")
        return FakeProbe(
            account, channel, events,
            send={"ok": False, "reason": "send_rejected", "error": "Twitch rejected"},
        )

    results = await run_bot_check(
        [
            {"id": 1, "nickname": "expired", "token": "expired"},
            {"id": 2, "nickname": "unknown", "token": "unknown"},
            {"id": 3, "nickname": "sender", "token": "valid"},
            {"id": 4, "nickname": "joiner", "token": "valid"},
            {"id": 5, "nickname": "", "missing": True},
        ],
        "test",
        validator=validator,
        probe_factory=factory,
        read_timeout=0.01,
        send_interval=0,
        sleep=lambda _seconds: asyncio.sleep(0),
        send_message=True,
    )

    assert [item["reason"] for item in results] == [
        "token_expired", "token_unknown", "send_rejected", "join_timeout", "bot_not_found",
    ]
    assert ("close", 3) in events and ("close", 4) in events


@pytest.mark.asyncio
async def test_cancel_during_connect_closes_transient_probe():
    closed = asyncio.Event()
    connecting = asyncio.Event()

    class WaitingProbe(FakeProbe):
        async def connect(self, timeout):
            connecting.set()
            await asyncio.Event().wait()

        async def close(self):
            closed.set()

    async def valid(_token):
        return {"status": "valid"}

    task = asyncio.create_task(run_bot_check(
        [{"id": 1, "nickname": "one", "token": "token"}], "test",
        validator=valid,
        probe_factory=lambda account, channel: WaitingProbe(account, channel, []),
    ))
    await connecting.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()


# ── Q07(а) / DEC-OWNER-011: контрольное сообщение опционально ──

async def _valid_token(_token):
    return {"status": "valid"}


class _SilentProbe:
    def __init__(self, account, channel, confirmed):
        self._confirmed = confirmed

    async def connect(self, timeout):
        return None

    async def wait_for_message(self, timeout):
        return self._confirmed

    async def send(self, text):
        raise AssertionError("send must not be called in passive check")

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_passive_check_without_send_confirms_on_real_message():
    """send_message=False: бот ничего не пишет; успех = реальное сообщение из чата."""
    def factory(account, channel):
        return _SilentProbe(account, channel, account["nickname"] == "alpha")

    results = await run_bot_check(
        [{"id": 1, "nickname": "alpha", "token": "t-a"},
         {"id": 2, "nickname": "beta", "token": "t-b"}],
        "test_channel", read_timeout=0, validator=_valid_token,
        probe_factory=factory, send_message=False,
    )
    by_nick = {r["nickname"]: r for r in results}
    assert by_nick["alpha"]["send_status"] == "not_run"
    assert by_nick["alpha"]["result"] == "success"
    assert by_nick["beta"]["result"] == "not_confirmed"
    assert by_nick["beta"]["reason"] == "no_messages"
