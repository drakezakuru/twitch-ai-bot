"""MOD-13 gate: fingerprint idempotency, bounds, stop/policy checks, revoked-grant race."""
from __future__ import annotations

import pytest
import pytest_asyncio

from app import moderator_site_cues as cues
from app import moderator_site_permissions as perms
from app import moderator_site_schema as ms


@pytest_asyncio.fixture
async def db(tmp_path):
    import aiosqlite
    conn = await aiosqlite.connect(tmp_path / "cues.db")
    await cues.ensure_schema(conn)
    await ms.ensure_schema(conn)
    await perms.ensure_schema(conn)
    yield conn
    await conn.close()


def _kwargs(**overrides):
    base = dict(account_id=1, channel="chan", grant_id="g1", grant_version=1,
                payload={"asset_id": "a1", "action": "play"}, policy_revision="p1",
                current_policy_revision="p1", scope_stopped=False)
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_duplicate_payload_is_idempotent(db):
    await db.execute("INSERT INTO ms_grants(id, account_id, channel, twitch_user_id) VALUES ('g1',1,'chan','userA')")
    await db.commit()
    first = await cues.submit_cue(db, **_kwargs())
    assert first["duplicate"] is False
    again = await cues.submit_cue(db, **_kwargs())
    assert again["duplicate"] is True and again["cue_id"] == first["cue_id"]
    count = await (await db.execute("SELECT count(*) FROM ms_cues")).fetchone()
    assert count[0] == 1
    # A changed payload is a different cue, not a duplicate.
    changed = await cues.submit_cue(db, **_kwargs(payload={"asset_id": "a2", "action": "play"}))
    assert changed["duplicate"] is False and changed["cue_id"] != first["cue_id"]


@pytest.mark.asyncio
async def test_bounds_and_policy_and_stop_fail_closed(db):
    await db.execute("INSERT INTO ms_grants(id, account_id, channel, twitch_user_id) VALUES ('g1',1,'chan','userA')")
    await db.commit()
    with pytest.raises(ValueError, match="cue_payload_missing_fields"):
        await cues.submit_cue(db, **_kwargs(payload={"asset_id": "a1"}))
    with pytest.raises(ValueError, match="cue_invalid_action"):
        await cues.submit_cue(db, **_kwargs(payload={"asset_id": "a1", "action": "raid"}))
    with pytest.raises(ValueError, match="cue_payload_too_large"):
        await cues.submit_cue(db, **_kwargs(payload={"asset_id": "x" * 9000, "action": "play"}))
    with pytest.raises(ValueError, match="cue_policy_stale"):
        await cues.submit_cue(db, **_kwargs(policy_revision="p0"))
    with pytest.raises(ValueError, match="scope_stopped"):
        await cues.submit_cue(db, **_kwargs(scope_stopped=True))


@pytest.mark.asyncio
async def test_queue_full(db):
    await db.execute("INSERT INTO ms_grants(id, account_id, channel, twitch_user_id) VALUES ('g1',1,'chan','userA')")
    await db.commit()
    for i in range(cues.DEFAULT_QUEUE_LIMIT):
        await cues.submit_cue(db, **_kwargs(payload={"asset_id": f"a{i}", "action": "play"}))
    with pytest.raises(ValueError, match="cue_queue_full"):
        await cues.submit_cue(db, **_kwargs(payload={"asset_id": "overflow", "action": "play"}))


@pytest.mark.asyncio
async def test_revoked_grant_race_fails_inside_transaction(db):
    await db.execute("INSERT INTO ms_grants(id, account_id, channel, twitch_user_id) VALUES ('g1',1,'chan','userA')")
    await db.commit()
    # The grant is disabled between the moderator's click and admission.
    await db.execute("UPDATE ms_grants SET enabled=0, grant_version=2 WHERE id='g1'")
    await db.commit()
    # Same grant_version as the cookie: revoked mid-flight -> disabled.
    with pytest.raises(ValueError, match="grant_disabled"):
        await cues.submit_cue(db, **_kwargs(grant_version=2))
    # Stale cookie version: reported before the disabled state.
    with pytest.raises(ValueError, match="grant_version_stale"):
        await cues.submit_cue(db, **_kwargs())


@pytest.mark.asyncio
async def test_admission_audits_atomically(db):
    await db.execute("INSERT INTO ms_grants(id, account_id, channel, twitch_user_id) VALUES ('g1',1,'chan','userA')")
    await db.commit()
    result = await cues.submit_cue(db, **_kwargs())
    events = await ms.claim_outbox(db)
    assert any(e[1] == "cue_admitted" and e[2]["cue_id"] == result["cue_id"] for e in events)
