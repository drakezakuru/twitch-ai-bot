"""Focused cancellation contracts for server-owned background tasks."""

from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.asyncio


async def test_server_task_cancellation_waits_for_finalizers():
    from app.server import _cancel_tasks

    finalized = asyncio.Event()

    async def worker() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            finalized.set()

    task = asyncio.create_task(worker(), name="lifecycle-test-worker")
    await asyncio.sleep(0)
    await _cancel_tasks(task)

    assert task.cancelled()
    assert finalized.is_set()


async def test_event_task_drain_waits_for_cleanup():
    from app import server

    finalized = asyncio.Event()

    async def event_worker() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            finalized.set()

    await server._cancel_event_tasks()
    task = server._spawn_event_task(event_worker(), name="event-lifecycle-test")
    await asyncio.sleep(0)
    await server._cancel_event_tasks()

    assert task.cancelled()
    assert finalized.is_set()
    assert server._event_tasks == set()


async def test_donation_parent_cancels_goal_sync_and_platform_children(monkeypatch):
    from app import donation_integrations as integrations

    dispatcher_started = asyncio.Event()
    finalized: set[str] = set()

    async def blocking_worker(name: str) -> None:
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            finalized.add(name)

    async def dispatcher() -> None:
        dispatcher_started.set()
        await asyncio.Event().wait()

    async def goal_sync() -> None:
        await blocking_worker("goal")

    await integrations.stop_integrations()
    child = asyncio.create_task(blocking_worker("platform"), name="donation-test-platform")
    integrations._integration_tasks[(1, "channel", "donatepay")] = child
    monkeypatch.setattr(integrations, "_dispatcher_loop", dispatcher)
    monkeypatch.setattr(integrations, "goal_sync_loop", goal_sync)

    parent = asyncio.create_task(integrations.integration_loop())
    await dispatcher_started.wait()
    await asyncio.sleep(0)
    parent.cancel()
    await asyncio.gather(parent, return_exceptions=True)

    assert parent.cancelled()
    assert child.cancelled()
    assert finalized == {"goal", "platform"}
    assert integrations._integration_tasks == {}
