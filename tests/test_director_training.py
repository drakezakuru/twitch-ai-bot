"""DIR-LIVE-04: training materials, example library, builtin moments, prompt lifecycle."""
from __future__ import annotations

import asyncio
import json
import time

import pytest

from app import director, director_review
from app.database import get_db


@pytest.fixture
def storage_root(tmp_path, monkeypatch):
    root = tmp_path / "storage"
    monkeypatch.setattr(director, "DATA_ROOT", root)
    return root


async def _session(channel: str = "channel", session_id: str = "session") -> None:
    from app.database import init_db
    await init_db()
    db = await get_db()
    try:
        await director.ensure_schema(db)
        await db.execute(
            "INSERT INTO director_sessions(id, channel, state, config_version) VALUES (?, ?, 'stopped', 1)",
            (session_id, channel),
        )
        await db.commit()
    finally:
        await db.close()


async def _frame_asset(asset_id: int, session_id: str, path: str, data: bytes) -> None:
    target = director._session_root(session_id) / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO director_session_artifacts(id, session_id, kind, path, size_bytes, channel, state, written_at) "
            "VALUES (?, ?, 'frame', ?, ?, 'channel', 'committed', CURRENT_TIMESTAMP)",
            (asset_id, session_id, path, len(data)),
        )
        await db.commit()
    finally:
        await db.close()


async def _suggestion(plan_id: str = "plan-1", channel: str = "channel") -> None:
    payload = {
        "plan_id": plan_id,
        "messages": [{"text": "Well played RealViewer"}],
        "context": {"chat": [{"author": "RealViewer", "text": "gg", "kind": "viewer"}], "vision": "win screen", "speech": "we won"},
    }
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO director_plans(id, session_id, channel, source_snapshot_id, mode, status, payload_json, created_at) "
            "VALUES (?, 'session', ?, 'snap', 'suggest', 'partial', ?, ?)",
            (plan_id, channel, json.dumps(payload), time.time()),
        )
        await db.commit()
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_approval_copies_frames_with_real_file_accounting(storage_root, tmp_db, monkeypatch):
    await _session()
    await _frame_asset(1, "session", "frames/moment.jpg", b"\xff\xd8moment-frame")
    await _suggestion()
    monkeypatch.setattr(director_review, "EXAMPLE_LIMIT_BYTES", 100000)
    result = await director_review.review_suggestion("channel", "plan-1", "approved", assets=[1])
    example_id = result["example_id"]
    stored = director_review.example_dir(example_id) / "frames" / "moment.jpg"
    assert stored.is_file() and stored.read_bytes() == b"\xff\xd8moment-frame"
    db = await get_db()
    try:
        row = await (await db.execute("SELECT size_bytes, content_hash, channel FROM director_example_files WHERE example_id=?", (example_id,))).fetchone()
        assert row[0] == len(b"\xff\xd8moment-frame") == stored.stat().st_size
        import hashlib
        assert row[1] == hashlib.sha256(b"\xff\xd8moment-frame").hexdigest() and row[2] == "channel"
    finally:
        await db.close()
    # Session deletion keeps the approved material.
    await director.delete_session_evidence("channel", "session", "УДАЛИТЬ")
    assert stored.is_file()
    assert (await director_review.list_examples("channel", kind="positive"))["examples"]


@pytest.mark.asyncio
async def test_example_quota_counts_files_and_json(storage_root, tmp_db, monkeypatch):
    await _session()
    await _frame_asset(1, "session", "frames/big.jpg", b"x" * 500)
    await _suggestion()
    monkeypatch.setattr(director_review, "EXAMPLE_LIMIT_BYTES", 400)
    with pytest.raises(ValueError, match="example_storage_full"):
        await director_review.review_suggestion("channel", "plan-1", "approved", assets=[1])
    # The refused approval leaves no rows and no orphan files.
    db = await get_db()
    try:
        assert (await (await db.execute("SELECT count(*) FROM director_examples")).fetchone())[0] == 0
        assert (await (await db.execute("SELECT count(*) FROM director_example_files")).fetchone())[0] == 0
    finally:
        await db.close()
    examples_root = director.DATA_ROOT / "director" / "examples"
    assert not examples_root.exists() or not list(examples_root.iterdir())


@pytest.mark.asyncio
async def test_concurrent_approvals_do_not_duplicate_files(storage_root, tmp_db, monkeypatch):
    await _session()
    await _frame_asset(1, "session", "frames/once.jpg", b"\xff\xd8unique")
    await _suggestion()
    results = await asyncio.gather(*(
        director_review.review_suggestion("channel", "plan-1", "approved", assets=[1]) for _ in range(3)
    ))
    example_ids = {item["example_id"] for item in results}
    assert len(example_ids) == 1
    files_dir = director_review.example_dir(example_ids.pop())
    assert len(list((files_dir / "frames").glob("*"))) == 1
    db = await get_db()
    try:
        assert (await (await db.execute("SELECT count(*) FROM director_example_files")).fetchone())[0] == 1
        assert (await (await db.execute("SELECT count(*) FROM director_examples")).fetchone())[0] == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_edit_and_delete_example(storage_root, tmp_db, monkeypatch):
    await _session()
    await _suggestion()
    example_id = (await director_review.review_suggestion("channel", "plan-1", "approved"))["example_id"]
    with pytest.raises(ValueError, match="unsafe_example_text"):
        await director_review.edit_example("channel", example_id, [{"text": "https://spam.invalid"}])
    await director_review.edit_example("channel", example_id, [{"text": "Edited safe reply"}])
    stored = (await director_review.list_examples("channel", kind="positive"))["examples"][0]
    assert stored["messages"][0]["text"] == "Edited safe reply"
    await director_review.delete_example("channel", example_id)
    assert (await director_review.list_examples("channel"))["examples"] == []
    assert not director_review.example_dir(example_id).exists()
    audit_entries = (await director.list_audit("channel"))["entries"]
    actions = [entry["action"] for entry in audit_entries]
    assert "example_edited" in actions and "example_deleted" in actions


@pytest.mark.asyncio
async def test_builtin_moments_cover_all_scenarios_text_only():
    expected = {"game_video_change", "talk", "start", "end", "raid", "pause", "win", "loss", "donation", "chat_wave", "silence"}
    assert set(director_review.BUILTIN_MOMENTS) == expected
    assert director_review.BUILTIN_MOMENTS_VERSION == "builtin-moments/v1"
    for scenario, moments in director_review.BUILTIN_MOMENTS.items():
        assert moments and all(isinstance(item, str) and item for item in moments)


@pytest.mark.asyncio
async def test_prompt_diff_rollback_and_protection(storage_root, tmp_db, monkeypatch):
    await _session()
    v1 = await director.create_prompt_version("channel", "first prompt line\nsecond line")
    v2 = await director.create_prompt_version("channel", "first prompt line\nchanged line")
    diff = await director.prompt_diff("channel", v1["id"], v2["id"])
    assert any("-second line" in line for line in diff["diff"]) and any("+changed line" in line for line in diff["diff"])
    # Rollback (activating the older v1) cannot bypass the replay/quality gate.
    db = await get_db()
    try:
        for prompt in (v1, v2):
            await db.execute("UPDATE director_prompt_versions SET tested_at=CURRENT_TIMESTAMP WHERE id=?", (prompt["id"],))
        await db.commit()
    finally:
        await db.close()
    with pytest.raises(ValueError, match="prompt_replay_stale"):
        await director.activate_prompt_version("channel", v1["id"], quality_confirmed=True)
    # A legitimately activated version (full replay path covered by review tests) is protected.
    db = await get_db()
    try:
        await db.execute("UPDATE director_prompt_versions SET activated_at=CURRENT_TIMESTAMP WHERE id=?", (v1["id"],))
        await db.commit()
    finally:
        await db.close()
    with pytest.raises(ValueError, match="prompt_active_protected"):
        await director.delete_prompt_version("channel", v1["id"])
    with pytest.raises(ValueError, match="prompt_last_working_protected"):
        await director.delete_prompt_version("channel", v2["id"])
    v3 = await director.create_prompt_version("channel", "draft that never worked")
    deleted = await director.delete_prompt_version("channel", v3["id"])
    assert deleted["content_hash"] == v3["content_hash"]
    prompts = (await director.list_prompt_versions("channel"))["prompts"]
    by_id = {item["id"]: item for item in prompts}
    assert by_id[v3["id"]]["retired"] is True and by_id[v3["id"]]["prompt_text"] == ""
    assert by_id[v3["id"]]["content_hash"] == v3["content_hash"]
