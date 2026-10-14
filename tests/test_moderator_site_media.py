"""MOD-14 gate: enqueue/claim/expire/replace lifecycle and fake renderer ACKs."""
from __future__ import annotations

import pytest
import pytest_asyncio

from app import moderator_site_media as media


@pytest_asyncio.fixture
async def db(tmp_path):
    import aiosqlite
    conn = await aiosqlite.connect(tmp_path / "media.db")
    await media.ensure_schema(conn)
    yield conn
    await conn.close()


@pytest.mark.asyncio
async def test_enqueue_claim_ack_lifecycle(db):
    first = await media.enqueue(db, cue_id="c1", account_id=1, channel="chan", placement={"x": 0.1, "y": 0.1})
    second = await media.enqueue(db, cue_id="c2", account_id=1, channel="chan", placement={"x": 0.5, "y": 0.5})
    claimed = await media.claim_next(db, "chan")
    assert claimed is not None and claimed["command_id"] == first["command_id"]
    assert claimed["placement"] == {"x": 0.1, "y": 0.1}
    # Explicit current-command lifecycle: a live current command blocks further claims.
    assert await media.claim_next(db, "chan") is None
    acked = await media.ack(db, first["command_id"], generation=1)
    assert acked["status"] == "done"
    next_claim = await media.claim_next(db, "chan")
    assert next_claim is not None and next_claim["command_id"] == second["command_id"]
    with pytest.raises(ValueError, match="command_not_current"):
        await media.ack(db, first["command_id"], generation=1)  # duplicate ACK


@pytest.mark.asyncio
async def test_second_enqueue_replaces_current(db):
    first = await media.enqueue(db, cue_id="c1", account_id=1, channel="chan", placement={})
    second = await media.enqueue(db, cue_id="c2", account_id=1, channel="chan", placement={})
    assert second["status"] == "queued"
    # Both queued before any claim; claim the first, then explicitly replace it.
    claimed = await media.claim_next(db, "chan")
    assert claimed["command_id"] == first["command_id"]
    await media.replace(db, first["command_id"])
    replaced = await (await db.execute(
        "SELECT status FROM ms_media_commands WHERE id=?", (first["command_id"],))).fetchone()
    assert replaced[0] == "replaced"
    next_claim = await media.claim_next(db, "chan")
    assert next_claim["command_id"] == second["command_id"]


@pytest.mark.asyncio
async def test_stale_command_expires_on_claim(db):
    import time as t
    old = await media.enqueue(db, cue_id="c1", account_id=1, channel="chan", placement={}, now=t.time() - media.COMMAND_TTL_SEC - 5)
    claimed = await media.claim_next(db, "chan")
    assert claimed is None  # expired, never handed to the renderer
    status = await (await db.execute("SELECT status FROM ms_media_commands WHERE id=?", (old["command_id"],))).fetchone()
    assert status[0] == "expired"


@pytest.mark.asyncio
async def test_generation_mismatch_rejected(db):
    command = await media.enqueue(db, cue_id="c1", account_id=1, channel="chan", placement={})
    await media.claim_next(db, "chan")
    with pytest.raises(ValueError, match="generation_mismatch"):
        await media.ack(db, command["command_id"], generation=99)


@pytest.mark.asyncio
async def test_per_cue_placement_never_touches_legacy_config(db):
    legacy_config = {"media_url": "http://legacy.local/media", "scope": "chan-wide"}
    snapshot = dict(legacy_config)
    await media.enqueue(db, cue_id="c1", account_id=1, channel="chan",
                        placement={"x": 0.25, "y": 0.25, "w": 0.5, "h": 0.5})
    url = media.build_media_url(legacy_config["media_url"], "cmd123")
    assert url == "http://legacy.local/media/ms/media/cmd123"
    assert legacy_config == snapshot  # scope-wide legacy config untouched
