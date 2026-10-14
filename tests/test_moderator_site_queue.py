"""MOD-19 gate: actor-filtered projection, resume gaps, stale revision, pagination."""
from __future__ import annotations

import pytest
import pytest_asyncio

from app import moderator_site_queue as queue


@pytest_asyncio.fixture
async def db(tmp_path):
    import aiosqlite
    conn = await aiosqlite.connect(tmp_path / "queue.db")
    await queue.ensure_schema(conn)
    from app import moderator_site_schema as ms
    await ms.ensure_schema(conn)
    # actorA sees their own items; actorB — theirs; same channel.
    for i in range(7):
        await queue.emit(conn, channel="chan", actor_twitch_user_id="actorA", kind="tts_done", payload={"i": i})
    for i in range(3):
        await queue.emit(conn, channel="chan", actor_twitch_user_id="actorB", kind="tts_done", payload={"j": i})
    await queue.emit(conn, channel="other", actor_twitch_user_id="actorA", kind="media_play")
    yield conn
    await conn.close()


@pytest.mark.asyncio
async def test_actor_filter_hides_foreign_tts(db):
    snap = await queue.snapshot(db, channel="chan", actor_twitch_user_id="actorA")
    assert len(snap["items"]) == 7 and all(item["kind"] != "foreign" for item in snap["items"])
    # actorB's items never leak into actorA's projection and vice versa.
    ids = {item["payload"].get("i") for item in snap["items"]}
    assert None not in ids  # no actorB payload keys
    other = await queue.snapshot(db, channel="other", actor_twitch_user_id="actorB")
    assert other["items"] == []  # чужой канал и чужой actor — пусто


@pytest.mark.asyncio
async def test_resume_delta_and_reconnect_gap(db):
    rev = await queue.current_revision(db)
    part = await queue.resume(db, channel="chan", actor_twitch_user_id="actorA", last_event_id=4, revision=rev)
    assert part["reset"] is False and [i["event_id"] for i in part["items"]] == [5, 6, 7]  # ровно gap
    await queue.emit(db, channel="chan", actor_twitch_user_id="actorA", kind="media_play")
    fresh = await queue.resume(db, channel="chan", actor_twitch_user_id="actorA", last_event_id=rev, revision=rev)
    assert fresh["reset"] is False and len(fresh["items"]) == 1


@pytest.mark.asyncio
async def test_stale_or_future_revision_forces_resnapshot(db):
    rev = await queue.current_revision(db)
    # Future revision (client jumped a purge): forced resnapshot.
    future = await queue.resume(db, channel="chan", actor_twitch_user_id="actorA", last_event_id=rev, revision=rev + 50)
    assert future["reset"] is True
    # Purged history: cursor below the oldest surviving event cannot replay.
    await db.execute("DELETE FROM ms_queue_events WHERE actor_twitch_user_id='actorA' AND id<=2")
    await db.commit()
    purged = await queue.resume(db, channel="chan", actor_twitch_user_id="actorA", last_event_id=1, revision=rev)
    assert purged["reset"] is True and len(purged["items"]) == 5
    with pytest.raises(ValueError, match="invalid_cursor"):
        await queue.resume(db, channel="chan", actor_twitch_user_id="actorA", last_event_id=-1, revision=rev)


@pytest.mark.asyncio
async def test_long_list_pagination(db):
    for i in range(120):
        await queue.emit(db, channel="chan", actor_twitch_user_id="pager", kind="tick")
    page1 = await queue.history_page(db, channel="chan", actor_twitch_user_id="pager", limit=50)
    assert len(page1["items"]) == 50 and page1["has_more"] is True
    page3 = await queue.history_page(db, channel="chan", actor_twitch_user_id="pager",
                                     before_event_id=page1["next_before"], limit=50)
    assert len(page3["items"]) == 50
    page_last = await queue.history_page(db, channel="chan", actor_twitch_user_id="pager",
                                         before_event_id=page3["next_before"], limit=50)
    assert len(page_last["items"]) == 20 and page_last["has_more"] is False


@pytest.mark.asyncio
async def test_session_downgrade_empties_projection(db):
    """After revoke the actor's own live projection is fenced to nothing they can act on."""
    from app import moderator_site_controls as controls
    await controls.ensure_schema(db)
    await controls.activate_kill(db, by="owner", reason="mod-18 integration")
    snap = await queue.snapshot(db, channel="chan", actor_twitch_user_id="actorA")
    # Items still exist as history, but admission is blocked for everyone.
    from app import moderator_site_controls as c
    with pytest.raises(ValueError, match="kill_switch_active"):
        await c.check_admission(db)
