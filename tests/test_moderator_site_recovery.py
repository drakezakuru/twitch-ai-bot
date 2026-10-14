"""MOD-20 gate: restore на пустое хранилище, checksums, missing/corrupt, sessions/queue не оживают."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import pytest_asyncio

from app import moderator_site_recovery as recovery


@pytest_asyncio.fixture
async def db(tmp_path):
    import aiosqlite
    conn = await aiosqlite.connect(tmp_path / "recovery.db")
    from app import moderator_site_uploads as uploads
    from app import moderator_site_identity as ident
    from app import moderator_site_cues as cues
    from app import moderator_site_library as lib
    await uploads.ensure_schema(conn)
    await lib.ensure_schema(conn)
    await ident.ensure_schema(conn)
    await cues.ensure_schema(conn)
    yield conn
    await conn.close()


async def _seed(db, tmp_path):
    from app import moderator_site_uploads as uploads
    await uploads.ensure_schema(db)
    store = tmp_path / "store"
    store.mkdir(parents=True, exist_ok=True)
    rows = []
    for upload_id, blob in (("good1", b"artifact-one"), ("good2", b"artifact-two"), ("bad1", b"corrupted")):
        (store / f"{upload_id}.blob").write_bytes(blob)
        await db.execute(
            "INSERT INTO ms_uploads(id, account_id, channel, kind, title, status, sha256, size_bytes)"
            " VALUES (?,?,?,?,?,'approved',?,?)",
            (upload_id, 1, "chan", "media", upload_id, hashlib.sha256(blob).hexdigest(), len(blob)))
        rows.append(upload_id)
    # corrupt: manifest checksum will not match the stored blob
    (store / "bad1.blob").write_bytes(b"corrupted-different")
    await db.commit()
    return store


@pytest.mark.asyncio
async def test_backup_manifest_and_restore_on_empty_scratch(db, tmp_path):
    store = await _seed(db, tmp_path)
    manifest = await recovery.build_manifest(db, store)
    assert len(manifest["artifacts"]) == 3
    assert manifest["excluded"] and "ms_sessions" in manifest["excluded"]
    target = tmp_path / "scratch" / "restore"  # пустое временное хранилище
    report = await recovery.restore(db, manifest, store, target)
    assert sorted(report["restored"]) == ["good1", "good2"]
    assert report["corrupt"] == ["bad1"] and report["missing"] == []
    assert report["sessions_restored"] == 0 and report["queued_replayed"] == 0
    assert report["media_tokens_preserved"] == 3  # токены сохранены по действующему решению
    assert (target / "good1.blob").read_bytes() == b"artifact-one"


@pytest.mark.asyncio
async def test_missing_artifact_reported_not_fatal(db, tmp_path):
    store = await _seed(db, tmp_path)
    (store / "good2.blob").unlink()
    manifest = await recovery.build_manifest(db, store)
    report = recovery.verify_manifest(manifest)
    assert report["missing"] == ["good2"] and report["corrupt"] == ["bad1"]
    assert sorted(report["ok"]) == ["good1"]


@pytest.mark.asyncio
async def test_checksum_mismatch_detected(db, tmp_path):
    store = await _seed(db, tmp_path)
    manifest = await recovery.build_manifest(db, store)
    verdict = recovery.verify_manifest(manifest)
    assert verdict["corrupt"] == ["bad1"]  # содержимое подменено, sha256 не совпал


@pytest.mark.asyncio
async def test_after_restore_no_sessions_no_auto_replay(db, tmp_path):
    store = await _seed(db, tmp_path)
    # live session + queued cue существуют до restore
    await db.execute("INSERT INTO ms_sessions(id, twitch_user_id, twitch_login, cookie_token_hash,"
                     " browser_fingerprint, expires_at, created_at) VALUES ('s1','u','login','h','fp', 9999999999, CURRENT_TIMESTAMP)")
    await db.execute("INSERT INTO ms_cues(id, account_id, channel, grant_id, grant_version, fingerprint,"
                     " payload_json, status, policy_revision, created_at, expires_at)"
                     " VALUES ('cue1',1,'chan','g',1,'fp','{}','queued','p1',0,9999999999)")
    await db.commit()
    manifest = await recovery.build_manifest(db, store)
    await recovery.restore(db, manifest, store, tmp_path / "scratch2")
    state = await recovery.post_restore_state(db)
    assert state == {"live_sessions": 0, "queued_cues": 0}
