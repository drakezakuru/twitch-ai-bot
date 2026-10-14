from __future__ import annotations

import pytest

from app.eventsub import EventSubClient


pytestmark = pytest.mark.asyncio


def _notification(message_id: str, user: str = "viewer") -> dict:
    return {
        "metadata": {
            "message_type": "notification",
            "message_id": message_id,
        },
        "payload": {
            "subscription": {"type": "channel.subscribe"},
            "event": {
                "broadcaster_user_login": "#CHAN",
                "user_login": user,
            },
        },
    }


async def test_eventsub_notification_message_id_is_processed_once():
    calls: list[tuple[int, str, str, dict]] = []

    async def callback(account_id: int, event_type: str, channel: str, event: dict) -> None:
        calls.append((account_id, event_type, channel, event))

    client = EventSubClient(7, "fake", "fake", ["chan"], callback)
    await client._handle_message(_notification("same-id"))
    await client._handle_message(_notification("same-id"))
    await client._handle_message(_notification("another-id", "other"))

    assert [(account_id, event_type, channel) for account_id, event_type, channel, _ in calls] == [
        (7, "channel.subscribe", "#chan"),
        (7, "channel.subscribe", "#chan"),
    ]


async def test_eventsub_failed_callback_allows_delivery_retry():
    attempts = 0

    async def callback(*_args) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary failure")

    client = EventSubClient(7, "fake", "fake", ["chan"], callback)
    with pytest.raises(RuntimeError, match="temporary failure"):
        await client._handle_message(_notification("retry-id"))
    await client._handle_message(_notification("retry-id"))

    assert attempts == 2
