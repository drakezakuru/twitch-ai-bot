"""Q34 / DEC-OWNER-019: bot packs — named sets of bots for one-click stream start.

A pack is a snapshot of bot members (account + channel binding). Q34a ships the
model and CRUD; Q34b adds apply/collapse with a pre-pack state snapshot; Q34c
schedules staggered joins over the pack window (not all at once).
"""
from __future__ import annotations

import asyncio
import random
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from app.database import get_db
from app.security import auth_dependency

router = APIRouter(dependencies=[Depends(auth_dependency)])

PACK_NAME_MAX = 64
PACK_MEMBERS_MAX = 500
JOIN_WINDOW_MIN_MAX = 180
JOIN_BATCH = 50


async def ensure_schema(db: Any = None) -> None:
    own = db is None
    if own:
        db = await get_db()
    try:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS bot_packs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL UNIQUE,
          join_window_min INTEGER NOT NULL DEFAULT 5,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS bot_pack_members (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          pack_id INTEGER NOT NULL REFERENCES bot_packs(id) ON DELETE CASCADE,
          account_id INTEGER NOT NULL,
          channel_name TEXT NOT NULL DEFAULT '',
          UNIQUE(pack_id, account_id, channel_name));
        """)
        columns = {row[1] for row in await (await db.execute("PRAGMA table_info(bot_packs)")).fetchall()}
        if "state_json" not in columns:
            await db.execute("ALTER TABLE bot_packs ADD COLUMN state_json TEXT NOT NULL DEFAULT ''")
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS bot_pack_joins (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          pack_id INTEGER NOT NULL,
          account_id INTEGER NOT NULL,
          due_at REAL NOT NULL,
          state TEXT NOT NULL DEFAULT 'pending',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE INDEX IF NOT EXISTS bot_pack_joins_due ON bot_pack_joins(state, due_at);
        """)
        await db.commit()
    finally:
        if own:
            await db.close()


def _bad(code: str) -> HTTPException:
    return HTTPException(status_code=400, detail=code)


def _clean_name(name: Any) -> str:
    text = str(name or "").strip()
    if not text or len(text) > PACK_NAME_MAX:
        raise _bad("pack_name_invalid")
    return text


def _clean_window(window: Any) -> int:
    try:
        value = int(window)
    except (TypeError, ValueError):
        raise _bad("pack_window_invalid") from None
    if isinstance(window, bool) or not 0 <= value <= JOIN_WINDOW_MIN_MAX:
        raise _bad("pack_window_invalid")
    return value


async def _clean_members(db: Any, members: Any) -> list[tuple[int, str]]:
    if not isinstance(members, list) or len(members) > PACK_MEMBERS_MAX:
        raise _bad("pack_members_invalid")
    cleaned: list[tuple[int, str]] = []
    for item in members:
        if not isinstance(item, dict):
            raise _bad("pack_members_invalid")
        account_id = item.get("account_id")
        if isinstance(account_id, bool) or not isinstance(account_id, int) or account_id < 1:
            raise _bad("pack_members_invalid")
        row = await (
            await db.execute("SELECT 1 FROM accounts WHERE id=?", (account_id,))
        ).fetchone()
        if not row:
            raise _bad("pack_account_missing")
        channel_raw = item.get("channel_name")
        if channel_raw is not None and not isinstance(channel_raw, str):
            raise _bad("pack_members_invalid")
        channel = channel_raw.strip().lstrip("#").lower()[:100] if channel_raw else ""
        entry = (account_id, channel)
        if entry not in cleaned:
            cleaned.append(entry)
    return cleaned


async def _pack_row(db: Any, pack_id: int) -> Any:
    row = await (
        await db.execute("SELECT id, name, join_window_min, created_at, updated_at FROM bot_packs WHERE id=?", (pack_id,))
    ).fetchone()
    if not row:
        raise _bad("pack_missing")
    return row


async def list_packs() -> dict:
    db = await get_db()
    try:
        packs = await (
            await db.execute(
                "SELECT id, name, join_window_min, created_at, updated_at FROM bot_packs ORDER BY id"
            )
        ).fetchall()
        members = await (
            await db.execute(
                "SELECT m.pack_id, m.account_id, m.channel_name, a.nickname FROM bot_pack_members m "
                "LEFT JOIN accounts a ON a.id=m.account_id ORDER BY m.id"
            )
        ).fetchall()
        active_joins = await (
            await db.execute(
                "SELECT pack_id, COUNT(*) FROM bot_pack_joins WHERE state IN ('pending','running') GROUP BY pack_id"
            )
        ).fetchall()
    finally:
        await db.close()
    grouped: dict[int, list[dict]] = {}
    for pack_id, account_id, channel_name, nickname in members:
        grouped.setdefault(pack_id, []).append(
            {"account_id": account_id, "channel_name": channel_name, "nickname": nickname}
        )
    active = {row[0]: row[1] for row in active_joins}
    return {
        "ok": True,
        "packs": [
            {
                "id": row[0],
                "name": row[1],
                "join_window_min": row[2],
                "created_at": row[3],
                "updated_at": row[4],
                "members": grouped.get(row[0], []),
                "active_joins": active.get(row[0], 0),
            }
            for row in packs
        ],
    }


async def create_pack(data: dict) -> dict:
    db = await get_db()
    try:
        name = _clean_name(data.get("name"))
        window = _clean_window(data.get("join_window_min"))
        members = await _clean_members(db, data.get("members"))
        await db.execute("BEGIN IMMEDIATE")
        try:
            cursor = await db.execute(
                "INSERT INTO bot_packs(name, join_window_min) VALUES (?, ?)", (name, window)
            )
            pack_id = cursor.lastrowid
            await db.executemany(
                "INSERT INTO bot_pack_members(pack_id, account_id, channel_name) VALUES (?, ?, ?)",
                [(pack_id, account_id, channel) for account_id, channel in members],
            )
            await db.commit()
        except Exception as exc:
            await db.rollback()
            if "UNIQUE" in str(exc):
                raise _bad("pack_name_taken") from exc
            raise
    finally:
        await db.close()
    return {"ok": True, "id": pack_id, "members": len(members)}


async def update_pack(pack_id: int, data: dict) -> dict:
    db = await get_db()
    try:
        await _pack_row(db, pack_id)
        name = _clean_name(data.get("name"))
        window = _clean_window(data.get("join_window_min"))
        members = await _clean_members(db, data.get("members"))
        await db.execute("BEGIN IMMEDIATE")
        try:
            await db.execute(
                "UPDATE bot_packs SET name=?, join_window_min=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (name, window, pack_id),
            )
            await db.execute("DELETE FROM bot_pack_members WHERE pack_id=?", (pack_id,))
            await db.executemany(
                "INSERT INTO bot_pack_members(pack_id, account_id, channel_name) VALUES (?, ?, ?)",
                [(pack_id, account_id, channel) for account_id, channel in members],
            )
            await db.commit()
        except Exception as exc:
            await db.rollback()
            if "UNIQUE" in str(exc):
                raise _bad("pack_name_taken") from exc
            raise
    finally:
        await db.close()
    return {"ok": True, "id": pack_id, "members": len(members)}


async def delete_pack(pack_id: int) -> dict:
    db = await get_db()
    try:
        await _pack_row(db, pack_id)
        await db.execute("BEGIN IMMEDIATE")
        # Manual cascade: the shared connection does not enforce foreign_keys.
        await db.execute("DELETE FROM bot_pack_members WHERE pack_id=?", (pack_id,))
        await db.execute("DELETE FROM bot_packs WHERE id=?", (pack_id,))
        await db.commit()
    finally:
        await db.close()
    return {"ok": True, "id": pack_id}


@router.get("/api/packs")
async def packs_list() -> dict:
    return await list_packs()


@router.post("/api/packs")
async def packs_create(data: dict) -> dict:
    return await create_pack(data)


@router.put("/api/packs/{pack_id}")
async def packs_update(pack_id: int, data: dict) -> dict:
    return await update_pack(pack_id, data)


@router.delete("/api/packs/{pack_id}")
async def packs_delete(pack_id: int) -> dict:
    return await delete_pack(pack_id)


@router.post("/api/packs/{pack_id}/apply")
async def packs_apply(pack_id: int, data: dict = None) -> dict:
    return await apply_pack(pack_id, connect=bool((data or {}).get("connect", True)))


@router.post("/api/packs/{pack_id}/collapse")
async def packs_collapse(pack_id: int, data: dict = None) -> dict:
    return await collapse_pack(pack_id, disable_channels=bool((data or {}).get("disable_channels", False)))


# ── Q34b: применение пачки («Начать стрим») и сворачивание («Свернуть стрим») ──

async def _pack_members(db: Any, pack_id: int) -> list[dict]:
    return [
        {"account_id": row[0], "channel_name": row[1]}
        for row in await (
            await db.execute(
                "SELECT account_id, channel_name FROM bot_pack_members WHERE pack_id=? ORDER BY id",
                (pack_id,),
            )
        ).fetchall()
    ]


async def _account_row(db: Any, account_id: int) -> Any:
    return await (await db.execute("SELECT * FROM accounts WHERE id=?", (account_id,))).fetchone()


async def _maybe_connect(account_id: int) -> bool:
    """Connect one enabled bot to its enabled channels (same path as manual toggle)."""
    from app.server import bot_manager

    try:
        if bot_manager.get_status(account_id).get("connected"):
            return False
    except AttributeError:
        return False
    db = await get_db()
    try:
        row = await _account_row(db, account_id)
        if not row:
            return False
        channels = [
            r["channel_name"]
            for r in await (
                await db.execute(
                    "SELECT channel_name FROM channels WHERE account_id=? AND enabled=1", (account_id,)
                )
            ).fetchall()
        ]
    finally:
        await db.close()
    if not channels:
        return False
    proxy = row["proxy"] if "proxy" in row.keys() else ""
    ok = await bot_manager.start_bot(account_id, row["nickname"], row["token"], channels, proxy=proxy or "")
    if not ok:
        return False
    try:
        from app.security import decrypt_token

        token = decrypt_token(row["token"])
        from app.server import chat_analyzer

        if chat_analyzer is not None:
            chat_analyzer.set_account_token(account_id, token)
    except Exception:
        pass
    try:
        if "eventsub_enabled" in row.keys() and row["eventsub_enabled"]:
            from app.security import decrypt_token
            from app.server import eventsub_manager

            if eventsub_manager is not None:
                await eventsub_manager.start_for_account(
                    account_id, row["nickname"], decrypt_token(row["token"]), channels
                )
    except Exception:
        pass
    return True


async def _disconnect(account_id: int) -> None:
    from app.server import bot_manager

    await bot_manager.stop_bot(account_id)
    try:
        from app.server import eventsub_manager

        if eventsub_manager is not None:
            await eventsub_manager.stop_for_account(account_id)
    except Exception:
        pass
    try:
        from app.director import revoke_worker

        await revoke_worker(account_id)
    except Exception:
        pass


async def apply_pack(pack_id: int, *, connect: bool = True) -> dict:
    """Enable pack bots, ensure their channel bindings, snapshot the prior state.

    The snapshot (per member: enabled flag + channel bindings) is what «Свернуть»
    restores, so collapse returns exactly to the pre-pack state.
    """
    import json as _json
    import time as _time

    db = await get_db()
    try:
        await _pack_row(db, pack_id)
        members = await _pack_members(db, pack_id)
        if not members:
            raise _bad("pack_empty")
        snapshot = {"applied_at": _time.time(), "members": []}
        enabled = 0
        for member in members:
            account_id = member["account_id"]
            row = await _account_row(db, account_id)
            if not row:
                continue  # bot deleted after pack was saved; skip without failing the batch
            channels_before = [
                {"name": r["channel_name"], "enabled": bool(r["enabled"])}
                for r in await (
                    await db.execute(
                        "SELECT channel_name, enabled FROM channels WHERE account_id=?", (account_id,)
                    )
                ).fetchall()
            ]
            snapshot["members"].append(
                {"account_id": account_id, "enabled_before": bool(row["enabled"]), "channels_before": channels_before}
            )
            await db.execute("UPDATE accounts SET enabled=1 WHERE id=?", (account_id,))
            enabled += 1
            channel = member["channel_name"]
            if channel:
                await db.execute(
                    "INSERT INTO channels(account_id, channel_name, enabled) VALUES (?, ?, 1) "
                    "ON CONFLICT(account_id, channel_name) DO UPDATE SET enabled=1",
                    (account_id, channel),
                )
        await db.execute("UPDATE bot_packs SET state_json=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                         (_json.dumps(snapshot, ensure_ascii=False), pack_id))
        await db.commit()
    finally:
        await db.close()
    scheduled_ids = [m["account_id"] for m in snapshot["members"]]
    if connect:
        window = (await _pack_window(pack_id)) or 0
        if window > 0 and scheduled_ids:
            count = await _schedule_staggered_joins(pack_id, scheduled_ids, window)
            return {"ok": True, "id": pack_id, "enabled": enabled, "scheduled": count, "window_min": window}
    connected: list[int] = []
    if connect:
        for account_id in scheduled_ids:
            if await _maybe_connect(account_id):
                connected.append(account_id)
    return {"ok": True, "id": pack_id, "enabled": enabled, "connected": connected}


async def _pack_window(pack_id: int) -> int:
    db = await get_db()
    try:
        row = await (await db.execute("SELECT join_window_min FROM bot_packs WHERE id=?", (pack_id,))).fetchone()
        return int(row[0]) if row else 0
    finally:
        await db.close()


async def _schedule_staggered_joins(pack_id: int, account_ids: list[int], window_min: int) -> int:
    """Spread joins over the window: even slots with jitter, shuffled order."""
    now = time.time()
    span = window_min * 60.0
    slots = [(index + random.random()) * span / len(account_ids) for index in range(len(account_ids))]
    random.shuffle(slots)
    db = await get_db()
    try:
        # Новый запуск заменяет старую очередь целиком: progress относится только
        # к текущему применению, а не суммирует предыдущие успешные входы.
        await db.execute("DELETE FROM bot_pack_joins WHERE pack_id=?", (pack_id,))
        await db.executemany(
            "INSERT INTO bot_pack_joins(pack_id, account_id, due_at) VALUES (?, ?, ?)",
            [(pack_id, account_id, now + slot) for account_id, slot in zip(account_ids, slots)],
        )
        await db.commit()
    finally:
        await db.close()
    await ensure_join_worker()
    return len(account_ids)


async def collapse_pack(pack_id: int, *, disable_channels: bool = False) -> dict:
    """Return the world to the pre-pack state from the apply snapshot.

    Members without a snapshot (pack applied before this feature, or members added
    later) are simply disabled. Optional: disable the pack's channel bindings too.
    """
    import json as _json

    db = await get_db()
    try:
        await _pack_row(db, pack_id)
        members = await _pack_members(db, pack_id)
        row = await (await db.execute("SELECT state_json FROM bot_packs WHERE id=?", (pack_id,))).fetchone()
        try:
            snapshot = _json.loads(row[0]) if row and row[0] else None
        except (TypeError, ValueError):
            snapshot = None
        before = {m["account_id"]: m for m in (snapshot or {}).get("members", [])}
        disabled = 0
        kept = 0
        to_disconnect: list[int] = []
        for member in members:
            account_id = member["account_id"]
            state = before.get(account_id)
            if state:
                target = 1 if state.get("enabled_before") else 0
                # Восстановить канал-биндинги «как было до пачки»: прежние флаги
                # вернуть, строки, которых до пачки не было, погасить (не удалять).
                channels_before = {
                    item["name"]: int(bool(item["enabled"]))
                    for item in state.get("channels_before", [])
                    if isinstance(item, dict)
                }
                current_rows = await (
                    await db.execute(
                        "SELECT channel_name FROM channels WHERE account_id=?", (account_id,)
                    )
                ).fetchall()
                for row in current_rows:
                    name = row[0]
                    await db.execute(
                        "UPDATE channels SET enabled=? WHERE account_id=? AND channel_name=?",
                        (channels_before.get(name, 0), account_id, name),
                    )
            else:
                target = 0
            await db.execute("UPDATE accounts SET enabled=? WHERE id=?", (target, account_id))
            if target:
                kept += 1
            else:
                disabled += 1
                to_disconnect.append(account_id)
        if disable_channels:
            channels = sorted({m["channel_name"] for m in members if m["channel_name"]})
            for channel in channels:
                await db.execute("UPDATE channels SET enabled=0 WHERE channel_name=?", (channel,))
        await db.execute("UPDATE bot_pack_joins SET state='cancelled' WHERE pack_id=? AND state IN ('pending','running')", (pack_id,))
        await db.execute("UPDATE bot_packs SET state_json='', updated_at=CURRENT_TIMESTAMP WHERE id=?", (pack_id,))
        await db.commit()
    finally:
        await db.close()
    for account_id in to_disconnect:
        try:
            await _disconnect(account_id)
        except Exception:
            pass
    return {
        "ok": True,
        "id": pack_id,
        "disabled": disabled,
        "kept": kept,
        "channels_disabled": bool(disable_channels),
    }


# ── Q34c: durable staggered joins + progress/cancel API ──

_join_task: asyncio.Task | None = None


async def ensure_join_worker() -> None:
    global _join_task
    if _join_task is None or _join_task.done():
        _join_task = asyncio.create_task(_join_loop(), name="bot-pack-joins")


async def _join_loop() -> None:
    while True:
        try:
            await process_due_joins()
        except asyncio.CancelledError:
            raise
        except Exception:
            # The next second retries pending rows; an individual row becomes failed.
            pass
        await asyncio.sleep(1)


async def _join_is_running(join_id: int) -> bool:
    db = await get_db()
    try:
        row = await (await db.execute("SELECT state FROM bot_pack_joins WHERE id=?", (join_id,))).fetchone()
        return bool(row and row[0] == "running")
    finally:
        await db.close()


async def _connected(account_id: int) -> bool:
    try:
        from app.server import bot_manager

        return bool(bot_manager.get_status(account_id).get("connected"))
    except Exception:
        return False


async def process_due_joins(now: float | None = None) -> int:
    """Claim due joins once, connect them, then persist joined/failed state."""
    now = time.time() if now is None else now
    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        rows = await (
            await db.execute(
                "SELECT id, account_id FROM bot_pack_joins WHERE state='pending' AND due_at<=? "
                "ORDER BY due_at, id LIMIT ?",
                (now, JOIN_BATCH),
            )
        ).fetchall()
        for join_id, _account_id in rows:
            await db.execute("UPDATE bot_pack_joins SET state='running' WHERE id=? AND state='pending'", (join_id,))
        await db.commit()
    finally:
        await db.close()
    joined = 0
    for join_id, account_id in rows:
        if not await _join_is_running(join_id):
            continue  # collapse/cancel won the race after this worker claimed it
        try:
            started = await _maybe_connect(account_id)
            state = "joined" if started or await _connected(account_id) else "failed"
        except Exception:
            state = "failed"
        db = await get_db()
        try:
            await db.execute("UPDATE bot_pack_joins SET state=? WHERE id=? AND state='running'", (state, join_id))
            await db.commit()
        finally:
            await db.close()
        if state == "joined":
            joined += 1
    return joined


async def pack_join_status(pack_id: int) -> dict:
    db = await get_db()
    try:
        await _pack_row(db, pack_id)
        rows = await (
            await db.execute(
                "SELECT j.id, j.account_id, a.nickname, j.due_at, j.state FROM bot_pack_joins j "
                "LEFT JOIN accounts a ON a.id=j.account_id WHERE j.pack_id=? ORDER BY j.due_at, j.id",
                (pack_id,),
            )
        ).fetchall()
    finally:
        await db.close()
    if any(row[4] == "pending" for row in rows):
        await ensure_join_worker()  # resumes a persisted queue after a panel restart
    counts = {state: sum(1 for row in rows if row[4] == state) for state in ("pending", "running", "joined", "failed", "cancelled")}
    return {
        "ok": True,
        "id": pack_id,
        "counts": counts,
        "items": [
            {"id": row[0], "account_id": row[1], "nickname": row[2], "due_at": row[3], "state": row[4]}
            for row in rows
        ],
    }


async def cancel_pack_joins(pack_id: int) -> dict:
    db = await get_db()
    try:
        await _pack_row(db, pack_id)
        await db.execute("BEGIN IMMEDIATE")
        cursor = await db.execute("UPDATE bot_pack_joins SET state='cancelled' WHERE pack_id=? AND state='pending'", (pack_id,))
        await db.commit()
    finally:
        await db.close()
    return {"ok": True, "id": pack_id, "cancelled": cursor.rowcount}


@router.get("/api/packs/{pack_id}/joins")
async def packs_joins(pack_id: int) -> dict:
    return await pack_join_status(pack_id)


@router.post("/api/packs/{pack_id}/joins/cancel")
async def packs_joins_cancel(pack_id: int) -> dict:
    return await cancel_pack_joins(pack_id)
