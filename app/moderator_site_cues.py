"""MOD-13: durable cue admission — fingerprinted POST contract with bounds.

A cue is admitted only when: the grant is live (enabled, version matches), the
scope is not stopped, the policy revision is current, the queue quota allows it
and the exact payload has not already been admitted (fingerprint idempotency).
Admission and its audit trail (outbox event) commit atomically.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from typing import Any

MAX_PAYLOAD_BYTES = 8 * 1024
DEFAULT_QUEUE_LIMIT = 5
CUE_TTL_SEC = 120

REQUIRED_PAYLOAD_KEYS = {"asset_id", "action"}


async def ensure_schema(db: Any) -> None:
    await db.executescript("""
    CREATE TABLE IF NOT EXISTS ms_cues (
      id TEXT PRIMARY KEY, account_id INTEGER NOT NULL, channel TEXT NOT NULL,
      grant_id TEXT NOT NULL, grant_version INTEGER NOT NULL,
      fingerprint TEXT NOT NULL, payload_json TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'queued',
      policy_revision TEXT NOT NULL,
      created_at REAL NOT NULL, expires_at REAL NOT NULL,
      claimed_at REAL, done_at REAL);
    CREATE UNIQUE INDEX IF NOT EXISTS ms_cues_live_fingerprint
      ON ms_cues(grant_id, fingerprint, status);
    """)


def fingerprint_of(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _payload_error(payload: dict[str, Any]) -> str | None:
    blob = json.dumps(payload, ensure_ascii=False)
    if len(blob.encode()) > MAX_PAYLOAD_BYTES:
        return "cue_payload_too_large"
    if not REQUIRED_PAYLOAD_KEYS <= set(payload):
        return "cue_payload_missing_fields"
    if payload.get("action") not in {"play", "stop"}:
        return "cue_invalid_action"
    return None


async def submit_cue(db: Any, *, account_id: int, channel: str, grant_id: str, grant_version: int,
                     payload: dict[str, Any], policy_revision: str, current_policy_revision: str,
                     scope_stopped: bool, queue_limit: int = DEFAULT_QUEUE_LIMIT,
                     now: float | None = None) -> dict[str, Any]:
    now = time.time() if now is None else now
    error = _payload_error(payload)
    if error:
        raise ValueError(error)
    if policy_revision != current_policy_revision:
        raise ValueError("cue_policy_stale")
    if scope_stopped:
        raise ValueError("scope_stopped")
    fp = fingerprint_of(payload)
    await db.execute("BEGIN IMMEDIATE")
    try:
        grant = await (await db.execute(
            "SELECT enabled, grant_version FROM ms_grants WHERE id=?", (grant_id,)
        )).fetchone()
        if grant is None:
            raise ValueError("grant_disabled")
        if int(grant[1]) != int(grant_version):
            # Version mismatch is reported first: the cookie predates the grant change.
            raise ValueError("grant_version_stale")
        if not grant[0]:
            raise ValueError("grant_disabled")  # revoked grant race: checked inside the tx
        duplicate = await (await db.execute(
            "SELECT id FROM ms_cues WHERE grant_id=? AND fingerprint=? AND status='queued'",
            (grant_id, fp),
        )).fetchone()
        if duplicate:
            await db.commit()  # idempotent admission: nothing new, no audit noise
            return {"cue_id": duplicate[0], "duplicate": True}
        queued = await (await db.execute(
            "SELECT count(*) FROM ms_cues WHERE grant_id=? AND status='queued' AND expires_at>?",
            (grant_id, now),
        )).fetchone()
        if queued[0] >= queue_limit:
            raise ValueError("cue_queue_full")
        cue_id = secrets.token_hex(16)
        await db.execute(
            "INSERT INTO ms_cues(id, account_id, channel, grant_id, grant_version, fingerprint,"
            " payload_json, status, policy_revision, created_at, expires_at)"
            " VALUES (?,?,?,?,?,?,?,'queued',?,?,?)",
            (cue_id, account_id, channel, grant_id, grant_version, fp,
             json.dumps(payload, ensure_ascii=False), policy_revision, now, now + CUE_TTL_SEC),
        )
        # Atomic audit: the admission event commits together with the cue row.
        from app.moderator_site_schema import append_outbox
        await append_outbox(db, f"cue-{cue_id}", "cue_admitted",
                            {"cue_id": cue_id, "channel": channel, "fingerprint": fp})
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return {"cue_id": cue_id, "duplicate": False}
