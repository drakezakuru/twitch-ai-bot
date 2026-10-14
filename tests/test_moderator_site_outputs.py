"""MOD-17 gate: lease roles, stale generation, duplicate/out-of-order ACK, heartbeat loss."""
from __future__ import annotations

import pytest
import pytest_asyncio

from app import moderator_site_outputs as outputs


@pytest_asyncio.fixture
async def db(tmp_path):
    import aiosqlite
    conn = await aiosqlite.connect(tmp_path / "outputs.db")
    await outputs.ensure_schema(conn)
    yield conn
    await conn.close()


@pytest.mark.asyncio
async def test_two_sources_executor_and_observer(db):
    lease = await outputs.acquire_lease(db, "media:chan", "renderer-A")
    assert lease["role"] == "executor" and lease["generation"] == 1
    second = await outputs.acquire_lease(db, "media:chan", "renderer-B")
    assert second["role"] == "observer"  # второй источник не перехватывает
    with pytest.raises(ValueError, match="observer_cannot_ack"):
        await outputs.record_ack(db, output="media:chan", executor_id="renderer-B", generation=1, seq=1)
    ok = await outputs.record_ack(db, output="media:chan", executor_id="renderer-A", generation=1, seq=1)
    assert ok["seq"] == 1


@pytest.mark.asyncio
async def test_stale_generation_rejected(db):
    await outputs.acquire_lease(db, "media:chan", "renderer-A")
    await outputs.release_lease(db, "media:chan", "renderer-A", generation=1)
    renewed = await outputs.acquire_lease(db, "media:chan", "renderer-A")  # generation bumps to 2
    assert renewed["generation"] == 2
    with pytest.raises(ValueError, match="stale_generation"):
        await outputs.record_ack(db, output="media:chan", executor_id="renderer-A", generation=1, seq=1)
    ok = await outputs.record_ack(db, output="media:chan", executor_id="renderer-A", generation=2, seq=1)
    assert ok["generation"] == 2


@pytest.mark.asyncio
async def test_duplicate_and_out_of_order_ack_rejected(db):
    await outputs.acquire_lease(db, "sound:chan", "renderer-A")
    await outputs.record_ack(db, output="sound:chan", executor_id="renderer-A", generation=1, seq=1)
    with pytest.raises(ValueError, match="duplicate_or_out_of_order_ack"):
        await outputs.record_ack(db, output="sound:chan", executor_id="renderer-A", generation=1, seq=1)
    with pytest.raises(ValueError, match="duplicate_or_out_of_order_ack"):
        await outputs.record_ack(db, output="sound:chan", executor_id="renderer-A", generation=1, seq=1)  # повтор
    ok = await outputs.record_ack(db, output="sound:chan", executor_id="renderer-A", generation=1, seq=2)
    assert ok["seq"] == 2  # строго инкрементальная последовательность


@pytest.mark.asyncio
async def test_heartbeat_loss_frees_lease_for_new_executor(db):
    import time as t
    first = await outputs.acquire_lease(db, "tts:chan", "renderer-A", now=t.time() - outputs.LEASE_TTL_SEC - 1)
    assert first["role"] == "executor"
    # renderer-A lost heartbeats: renderer-B takes over with a new generation.
    takeover = await outputs.acquire_lease(db, "tts:chan", "renderer-B")
    assert takeover["role"] == "executor" and takeover["generation"] == 2
    with pytest.raises(ValueError, match="stale_generation"):
        await outputs.record_ack(db, output="tts:chan", executor_id="renderer-A", generation=1, seq=1)


@pytest.mark.asyncio
async def test_evidence_is_not_obs_acceptance(db):
    await outputs.acquire_lease(db, "media:chan", "renderer-A")
    await outputs.record_ack(db, output="media:chan", executor_id="renderer-A", generation=1, seq=1, kind="ack")
    events = await outputs.evidence(db, "media:chan")
    assert events and events[0]["kind"] == "ack"  # renderer-reported evidence only
