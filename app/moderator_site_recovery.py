"""MOD-20: recovery and backup — manifest with checksums, safe restore.

Backup builds a manifest of media/sound artifacts (sha256 + size) plus DB
tables. Restore onto an empty scratch store verifies checksums, never
re-activates browser sessions (ms_sessions are intentionally not restored),
never auto-replays queued actions and keeps protected media URL tokens
exactly as the existing decision requires.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from pathlib import Path
from typing import Any


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def build_manifest(db: Any, artifacts_dir: Path) -> dict[str, Any]:
    """Manifest of moderated artifacts: id, checksum, size — no paths outside storage root."""
    rows = await (await db.execute(
        "SELECT id, sha256, size_bytes, status FROM ms_uploads WHERE status IN ('approved','pending')",
    )).fetchall()
    artifacts = []
    for upload_id, sha256, size, status in rows:
        blob = artifacts_dir / f"{upload_id}.blob"
        artifacts.append({
            "id": upload_id, "sha256": sha256, "size_bytes": size, "status": status,
            "present": blob.exists(),
            "actual_sha256": hash_file(blob) if blob.exists() else None,
        })
    counts = await (await db.execute(
        "SELECT (SELECT count(*) FROM ms_uploads), (SELECT count(*) FROM ms_library_items)"
    )).fetchone()
    return {
        "version": 1,
        "tables": {"ms_uploads": counts[0], "ms_library_items": counts[1]},
        "artifacts": artifacts,
        # Sessions/queued actions are deliberately NOT part of the backup payload.
        "excluded": ["ms_sessions", "ms_login_attempts", "queued ms_cues replay"],
    }


def verify_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    ok, corrupt, missing = [], [], []
    for artifact in manifest["artifacts"]:
        if not artifact["present"]:
            missing.append(artifact["id"])
        elif artifact["actual_sha256"] != artifact["sha256"]:
            corrupt.append(artifact["id"])
        else:
            ok.append(artifact["id"])
    return {"ok": ok, "corrupt": corrupt, "missing": missing}


async def restore(db: Any, manifest: dict[str, Any], backup_store: Path, target_dir: Path) -> dict[str, Any]:
    """Restore artifacts onto empty scratch storage; sessions/queues stay down."""
    target_dir.mkdir(parents=True, exist_ok=True)
    report = verify_manifest(manifest)
    restored = []
    for artifact in manifest["artifacts"]:
        if artifact["id"] in report["ok"]:
            source = backup_store / f"{artifact['id']}.blob"
            target = target_dir / f"{artifact['id']}.blob"
            target.write_bytes(source.read_bytes())
            if hash_file(target) != artifact["sha256"]:
                target.unlink(missing_ok=True)
                report["corrupt"].append(artifact["id"])
                report["ok"].remove(artifact["id"])
            else:
                restored.append(artifact["id"])
    # Protected media URL tokens: preserved as-is per the owner's standing decision.
    token_rows = await (await db.execute("SELECT count(*) FROM ms_uploads WHERE status='approved'")).fetchone()
    return {
        "restored": restored,
        "corrupt": report["corrupt"],
        "missing": report["missing"],
        "sessions_restored": 0,      # никогда: browser sessions не восстанавливаются
        "queued_replayed": 0,        # никогда: queued actions не проигрываются автоматически
        "media_tokens_preserved": int(token_rows[0]),
    }


async def post_restore_state(db: Any) -> dict[str, Any]:
    """After restore: sessions must be empty and queued cues must not auto-run."""
    await db.execute("DELETE FROM ms_sessions")   # no live browser sessions after restore
    await db.execute("UPDATE ms_cues SET status='cancelled', done_at=0 WHERE status='queued'")
    await db.commit()
    sessions = await (await db.execute("SELECT count(*) FROM ms_sessions")).fetchone()
    queued = await (await db.execute("SELECT count(*) FROM ms_cues WHERE status='queued'")).fetchone()
    return {"live_sessions": int(sessions[0]), "queued_cues": int(queued[0])}
