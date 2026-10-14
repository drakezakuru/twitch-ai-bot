"""Validation and durable audit primitives for Song Request."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_DANGEROUS_SCHEME_RE = re.compile(r"^(?:javascript|data|file|vbscript):", re.IGNORECASE)
MAX_REQUEST_LENGTH = 200


def validate_request_text(value: Any) -> tuple[str, str]:
    """Return a bounded display value and a stable rejection reason."""
    raw = str(value or "").strip()
    if not raw:
        return "", "empty_request"
    if len(raw) > MAX_REQUEST_LENGTH:
        return "", "request_too_long"
    if _CONTROL_RE.search(raw):
        return "", "control_characters"
    if _DANGEROUS_SCHEME_RE.match(raw):
        return "", "unsafe_url"
    if "://" in raw:
        parsed = urlsplit(raw)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return "", "unsafe_url"
        if parsed.username is not None or parsed.password is not None:
            return "", "unsafe_url"
    return " ".join(raw.split()), ""


def request_identity(value: str) -> str:
    return " ".join(value.split()).casefold()


async def ensure_schema(db) -> None:
    await db.executescript(
        """
        CREATE TABLE IF NOT EXISTS song_request_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL DEFAULT 0,
            channel TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL,
            actor TEXT NOT NULL DEFAULT '',
            request_text TEXT NOT NULL DEFAULT '',
            accepted INTEGER NOT NULL DEFAULT 0,
            reason TEXT NOT NULL,
            queue_item_id INTEGER,
            event_id TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_song_request_audit_scope_time
            ON song_request_audit(account_id, channel, created_at DESC);
        CREATE TABLE IF NOT EXISTS song_request_entitlement_settings (
            account_id INTEGER NOT NULL,
            channel TEXT NOT NULL,
            points_create_reward_id TEXT NOT NULL DEFAULT '',
            points_create_reward_title TEXT NOT NULL DEFAULT '',
            points_priority_reward_id TEXT NOT NULL DEFAULT '',
            points_priority_reward_title TEXT NOT NULL DEFAULT '',
            donation_enabled INTEGER NOT NULL DEFAULT 0,
            donation_threshold REAL,
            donation_currency TEXT NOT NULL DEFAULT '',
            donation_action TEXT NOT NULL DEFAULT 'create'
                CHECK(donation_action IN ('create', 'priority')),
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (account_id, channel),
            FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS song_request_entitlement_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            channel TEXT NOT NULL,
            source TEXT NOT NULL,
            event_id TEXT NOT NULL,
            action TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'processing',
            reason TEXT NOT NULL DEFAULT 'processing',
            queue_item_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(account_id, channel, source, event_id)
        );
        """
    )


async def write_audit(
    db,
    scope: tuple[int, str] | None,
    *,
    source: str,
    actor: str,
    request_text: str,
    accepted: bool,
    reason: str,
    queue_item_id: int | None = None,
    event_id: str = "",
) -> None:
    await ensure_schema(db)
    account_id, channel = scope or (0, "")
    await db.execute(
        "INSERT INTO song_request_audit "
        "(account_id, channel, source, actor, request_text, accepted, reason, "
        "queue_item_id, event_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            account_id,
            channel,
            str(source)[:40],
            str(actor)[:100],
            str(request_text)[:MAX_REQUEST_LENGTH],
            1 if accepted else 0,
            str(reason)[:80],
            queue_item_id,
            str(event_id)[:200],
        ),
    )


async def list_audit(scope: tuple[int, str] | None, limit: int = 100) -> list[dict]:
    from app.database import get_db

    db = await get_db()
    try:
        await ensure_schema(db)
        account_id, channel = scope or (0, "")
        cursor = await db.execute(
            "SELECT id, source, actor, request_text, accepted, reason, queue_item_id, "
            "event_id, created_at FROM song_request_audit "
            "WHERE account_id = ? AND channel = ? ORDER BY id DESC LIMIT ?",
            (account_id, channel, max(1, min(int(limit), 500))),
        )
        return [dict(row) for row in await cursor.fetchall()]
    finally:
        await db.close()


async def get_entitlement_settings(scope: tuple[int, str]) -> dict:
    from app.database import get_db

    db = await get_db()
    try:
        await ensure_schema(db)
        cursor = await db.execute(
            "SELECT points_create_reward_id, points_create_reward_title, "
            "points_priority_reward_id, points_priority_reward_title, donation_enabled, "
            "donation_threshold, donation_currency, donation_action, updated_at "
            "FROM song_request_entitlement_settings WHERE account_id = ? AND channel = ?",
            scope,
        )
        row = await cursor.fetchone()
        if row:
            return dict(row)
        return {
            "points_create_reward_id": "",
            "points_create_reward_title": "",
            "points_priority_reward_id": "",
            "points_priority_reward_title": "",
            "donation_enabled": 0,
            "donation_threshold": None,
            "donation_currency": "",
            "donation_action": "create",
            "updated_at": "",
        }
    finally:
        await db.close()


async def save_entitlement_settings(scope: tuple[int, str], payload: dict) -> dict:
    current = await get_entitlement_settings(scope)
    merged = {**current, **{key: payload[key] for key in current if key in payload}}
    action = str(merged.get("donation_action") or "").strip().lower()
    if action not in {"create", "priority"}:
        raise ValueError("invalid_donation_action")
    currency = str(merged.get("donation_currency") or "").strip().upper()
    threshold_raw = merged.get("donation_threshold")
    threshold = None if threshold_raw in (None, "") else float(threshold_raw)
    enabled = 1 if merged.get("donation_enabled") in (1, True, "1", "true") else 0
    if enabled and (threshold is None or threshold <= 0 or not currency):
        raise ValueError("donation_policy_incomplete")

    values = (
        str(merged.get("points_create_reward_id") or "").strip()[:200],
        str(merged.get("points_create_reward_title") or "").strip()[:200],
        str(merged.get("points_priority_reward_id") or "").strip()[:200],
        str(merged.get("points_priority_reward_title") or "").strip()[:200],
        enabled,
        threshold,
        currency[:10],
        action,
    )
    from app.database import get_db

    db = await get_db()
    try:
        await ensure_schema(db)
        await db.execute(
            "INSERT INTO song_request_entitlement_settings "
            "(account_id, channel, points_create_reward_id, points_create_reward_title, "
            "points_priority_reward_id, points_priority_reward_title, donation_enabled, "
            "donation_threshold, donation_currency, donation_action) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(account_id, channel) DO UPDATE SET "
            "points_create_reward_id=excluded.points_create_reward_id, "
            "points_create_reward_title=excluded.points_create_reward_title, "
            "points_priority_reward_id=excluded.points_priority_reward_id, "
            "points_priority_reward_title=excluded.points_priority_reward_title, "
            "donation_enabled=excluded.donation_enabled, "
            "donation_threshold=excluded.donation_threshold, "
            "donation_currency=excluded.donation_currency, "
            "donation_action=excluded.donation_action, updated_at=CURRENT_TIMESTAMP",
            (*scope, *values),
        )
        await db.commit()
    finally:
        await db.close()
    return await get_entitlement_settings(scope)


async def _claim_event(
    scope: tuple[int, str], source: str, event_id: str, action: str,
) -> tuple[bool, dict]:
    from app.database import get_db

    db = await get_db()
    try:
        await ensure_schema(db)
        cursor = await db.execute(
            "INSERT OR IGNORE INTO song_request_entitlement_events "
            "(account_id, channel, source, event_id, action) VALUES (?, ?, ?, ?, ?)",
            (*scope, source, event_id, action),
        )
        await db.commit()
        selected = await db.execute(
            "SELECT status, reason, queue_item_id FROM song_request_entitlement_events "
            "WHERE account_id = ? AND channel = ? AND source = ? AND event_id = ?",
            (*scope, source, event_id),
        )
        row = await selected.fetchone()
        return cursor.rowcount == 1, dict(row)
    finally:
        await db.close()


async def _finish_event(
    scope: tuple[int, str], source: str, event_id: str, result: dict,
) -> None:
    from app.database import get_db

    db = await get_db()
    try:
        await db.execute(
            "UPDATE song_request_entitlement_events SET status = ?, reason = ?, "
            "queue_item_id = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE account_id = ? AND channel = ? AND source = ? AND event_id = ?",
            (
                "accepted" if result.get("ok") else "rejected",
                str(result.get("reason") or result.get("error") or "rejected")[:80],
                result.get("id"),
                *scope,
                source,
                event_id,
            ),
        )
        await db.commit()
    finally:
        await db.close()


async def apply_entitlement(
    scope: tuple[int, str], *, source: str, event_id: str, action: str,
    request_text: str, actor: str,
) -> dict:
    if not event_id:
        from app.database import get_db

        db = await get_db()
        try:
            await write_audit(
                db, scope, source=source, actor=actor, request_text=request_text,
                accepted=False, reason="missing_event_id",
            )
            await db.commit()
        finally:
            await db.close()
        return {"handled": True, "ok": False, "error": "missing_event_id"}
    claimed, prior = await _claim_event(scope, source, event_id, action)
    if not claimed:
        return {
            "handled": True,
            "ok": prior.get("status") == "accepted",
            "error": "duplicate_event",
            "reason": prior.get("reason"),
            "id": prior.get("queue_item_id"),
        }
    try:
        from app.widgets import add_song_request

        result = await add_song_request(
            request_text, actor, scope[1], account_id=scope[0], source=source,
            event_id=event_id, priority_override=10 if action == "priority" else 0,
            boost_duplicate=action == "priority",
        )
    except Exception:
        result = {"error": "internal_error"}
    await _finish_event(scope, source, event_id, result)
    return {"handled": True, **result}


async def reject_entitlement(
    scope: tuple[int, str], *, source: str, event_id: str, action: str,
    request_text: str, actor: str, reason: str,
) -> dict:
    if not event_id:
        return await apply_entitlement(
            scope, source=source, event_id="", action=action,
            request_text=request_text, actor=actor,
        )
    claimed, prior = await _claim_event(scope, source, event_id, action)
    if not claimed:
        return {
            "handled": True,
            "ok": prior.get("status") == "accepted",
            "error": "duplicate_event",
            "reason": prior.get("reason"),
            "id": prior.get("queue_item_id"),
        }
    from app.database import get_db

    db = await get_db()
    try:
        await write_audit(
            db, scope, source=source, actor=actor, request_text=request_text,
            accepted=False, reason=reason, event_id=event_id,
        )
        await db.commit()
    finally:
        await db.close()
    result = {"error": reason}
    await _finish_event(scope, source, event_id, result)
    return {"handled": True, "ok": False, **result}


def _reward_matches(configured_id: str, configured_title: str, reward: dict) -> bool:
    reward_id = str(reward.get("id") or "").strip()
    if configured_id:
        return reward_id == configured_id
    return bool(configured_title) and str(reward.get("title") or "").strip().casefold() == configured_title.casefold()


async def handle_channel_points(account_id: int, channel: str, payload: dict) -> dict:
    scope = (int(account_id), channel.strip().lstrip("#").lower())
    settings = await get_entitlement_settings(scope)
    reward = payload.get("reward") or {}
    if _reward_matches(
        settings["points_create_reward_id"], settings["points_create_reward_title"], reward,
    ):
        action = "create"
    elif _reward_matches(
        settings["points_priority_reward_id"], settings["points_priority_reward_title"], reward,
    ):
        action = "priority"
    else:
        return {"handled": False}
    return await apply_entitlement(
        scope, source="channel_points", event_id=str(payload.get("id") or "").strip(),
        action=action, request_text=str(payload.get("user_input") or ""),
        actor=str(payload.get("user_id") or payload.get("user_login") or ""),
    )


async def handle_donation(
    account_id: int | None, channel: str | None, *, platform: str, event_id: str,
    username: str, amount: float, currency: str, message: str,
) -> dict:
    if not account_id or not channel:
        return {"handled": False}
    scope = (int(account_id), channel.strip().lstrip("#").lower())
    settings = await get_entitlement_settings(scope)
    if not settings.get("donation_enabled"):
        return {"handled": False}
    source = f"donation:{platform}"
    if str(currency or "").upper() != settings["donation_currency"]:
        return await reject_entitlement(
            scope, source=source, event_id=str(event_id or "").strip(),
            action=settings["donation_action"], request_text=message, actor=username,
            reason="currency_mismatch",
        )
    if float(amount) < float(settings["donation_threshold"]):
        return await reject_entitlement(
            scope, source=source, event_id=str(event_id or "").strip(),
            action=settings["donation_action"], request_text=message, actor=username,
            reason="below_threshold",
        )
    return await apply_entitlement(
        scope, source=source, event_id=str(event_id or "").strip(),
        action=settings["donation_action"], request_text=message, actor=username,
    )
