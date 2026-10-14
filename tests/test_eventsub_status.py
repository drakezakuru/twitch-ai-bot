"""Truthful EventSub manager readiness and restart contracts."""

from __future__ import annotations

import asyncio

import pytest

from app.eventsub import EventSubClient, EventSubManager

pytestmark = pytest.mark.asyncio


async def _callback(*_args) -> None:
    return None


async def test_manager_does_not_register_client_when_configuration_is_missing(monkeypatch):
    monkeypatch.setattr("app.eventsub.is_helix_configured", lambda: False)
    manager = EventSubManager()
    manager.set_callback(_callback)

    assert not await manager.start_for_account(7, "fake", "fake", ["channel"])
    assert not manager.is_running(7)
    assert manager._clients == {}


async def test_manager_status_requires_a_live_task_and_restarts_stale_client(monkeypatch):
    started: list[EventSubClient] = []

    async def fake_start(client: EventSubClient) -> bool:
        client._task = asyncio.create_task(asyncio.sleep(3600))
        started.append(client)
        return True

    monkeypatch.setattr(EventSubClient, "start", fake_start)
    manager = EventSubManager()
    manager.set_callback(_callback)

    assert await manager.start_for_account(7, "first", "fake", ["channel"])
    assert manager.is_running(7)
    started[0]._task.cancel()
    await asyncio.gather(started[0]._task, return_exceptions=True)
    assert not manager.is_running(7)

    assert await manager.start_for_account(7, "second", "fake", ["channel"])
    assert manager.is_running(7)
    assert manager._clients[7].nickname == "second"
    await manager.stop_all()
    assert not manager.is_running(7)
