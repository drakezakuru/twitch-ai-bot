"""Bulk bot/channel operations and the channel-oriented owner view."""

from __future__ import annotations

import asyncio
import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends

from app.bot_check import DEFAULT_CHECK_MESSAGE, run_bot_check
from app.database import get_db
from app.routes import log_action
from app.security import auth_dependency


router = APIRouter(dependencies=[Depends(auth_dependency)], tags=["bulk-channels"])
_jobs: dict[str, dict[str, Any]] = {}
_CHANNEL_RE = re.compile(r"^[a-z0-9_]{1,25}$")


def _runtime_manager() -> Any:
    from app.server import bot_manager
    return bot_manager


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in job.items() if key != "task"}


def _prune_jobs() -> None:
    completed = [key for key, job in _jobs.items() if job["status"] != "running"]
    for key in completed[:-20]:
        _jobs.pop(key, None)


def _empty_check() -> dict[str, str]:
    return {
        "token_status": "not_run",
        "join_status": "not_run",
        "read_status": "not_run",
        "send_status": "not_run",
        "check_result": "error",
        "check_reason": "not_run",
    }


async def _load_accounts(account_ids: list[int]) -> dict[int, dict[str, Any]]:
    db = await get_db()
    try:
        placeholders = ",".join("?" for _ in account_ids)
        cursor = await db.execute(
            f"SELECT id, nickname, token FROM accounts WHERE id IN ({placeholders})", account_ids,
        )
        return {row["id"]: dict(row) for row in await cursor.fetchall()}
    finally:
        await db.close()


async def _add_pairs(
    account_ids: list[int], channels: list[str], accounts: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for channel in channels:
        for account_id in account_ids:
            account = accounts.get(account_id)
            item = {
                "account_id": account_id,
                "nickname": str((account or {}).get("nickname") or ""),
                "channel": channel,
                "add_result": "error",
                "add_reason": "bot_not_found" if not account else "add_failed",
                **_empty_check(),
            }
            if not account:
                items.append(item)
                continue
            pair_enabled = False
            db = await get_db()
            try:
                cursor = await db.execute(
                    "INSERT OR IGNORE INTO channels (account_id, channel_name, enabled) VALUES (?, ?, 1)",
                    (account_id, channel),
                )
                await db.commit()
                if cursor.rowcount:
                    item.update(add_result="added", add_reason="added")
                    pair_enabled = True
                else:
                    item.update(add_result="skipped", add_reason="already_exists")
                    existing = await (await db.execute(
                        "SELECT enabled FROM channels WHERE account_id = ? AND channel_name = ?",
                        (account_id, channel),
                    )).fetchone()
                    pair_enabled = bool(existing and existing["enabled"])
            except Exception:
                item.update(add_result="error", add_reason="add_failed")
            finally:
                await db.close()
            if pair_enabled:
                bot_manager = _runtime_manager()
                status = bot_manager.get_status(account_id)
                if status.get("connected") and channel not in (status.get("channels") or []):
                    await bot_manager.join_channel(account_id, channel)
            items.append(item)
    return items


async def run_bulk_add_and_check(
    account_ids: list[int],
    channels: list[str],
    message_template: str,
    *,
    read_timeout: float = 45.0,
    send_interval: float = 2.5,
    send_message: bool = False,
) -> list[dict[str, Any]]:
    accounts = await _load_accounts(account_ids)
    items = await _add_pairs(account_ids, channels, accounts)
    item_map = {(item["account_id"], item["channel"]): item for item in items}
    checkable = [account_id for account_id in account_ids if account_id in accounts]
    for channel_index, channel in enumerate(channels):
        try:
            checks = await run_bot_check(
                [accounts[account_id] for account_id in checkable],
                channel,
                message_template,
                read_timeout=read_timeout,
                send_interval=send_interval,
                send_message=send_message,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            checks = [
                {"account_id": account_id, "result": "error", "reason": "check_failed"}
                for account_id in checkable
            ]
        for check in checks:
            item = item_map[(int(check["account_id"]), channel)]
            item.update(
                token_status=str(check.get("token_status") or "not_run"),
                join_status=str(check.get("join_status") or "not_run"),
                read_status=str(check.get("read_status") or "not_run"),
                send_status=str(check.get("send_status") or "not_run"),
                check_result=str(check.get("result") or "error"),
                check_reason=str(check.get("reason") or "check_failed"),
            )
        if channel_index < len(channels) - 1 and checkable:
            await asyncio.sleep(send_interval)
    return items


def _counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "added": 0, "skipped": 0, "add_error": 0,
        "check_success": 0, "not_confirmed": 0, "check_error": 0,
    }
    for item in items:
        add_key = item["add_result"] if item["add_result"] != "error" else "add_error"
        counts[add_key] += 1
        check_key = {
            "success": "check_success",
            "not_confirmed": "not_confirmed",
        }.get(item["check_result"], "check_error")
        counts[check_key] += 1
    return counts


async def _execute_job(job_id: str) -> None:
    job = _jobs[job_id]
    try:
        items = await run_bulk_add_and_check(
            job["account_ids"], job["channels"], job["message_template"],
            read_timeout=job["read_timeout"], send_message=job["send_message"],
        )
        job.update(status="completed", results=items, counts=_counts(items))
        counts = job["counts"]
        await log_action(
            "bulk_channels",
            f"direction={job['direction']} channels={len(job['channels'])} bots={len(job['account_ids'])} "
            f"added={counts['added']} skipped={counts['skipped']} add_error={counts['add_error']} "
            f"check_success={counts['check_success']} not_confirmed={counts['not_confirmed']} "
            f"check_error={counts['check_error']}",
        )
    except asyncio.CancelledError:
        job.update(status="cancelled", results=[])
        await log_action(
            "bulk_channels",
            f"direction={job['direction']} channels={len(job['channels'])} "
            f"bots={len(job['account_ids'])} cancelled=1",
        )
    except Exception:
        job.update(status="failed", error="bulk_failed")
        await log_action(
            "bulk_channels",
            f"direction={job['direction']} channels={len(job['channels'])} "
            f"bots={len(job['account_ids'])} failed=1",
        )
    finally:
        job.pop("task", None)
        _prune_jobs()


@router.get("/api/channel-overview")
async def channel_overview() -> dict[str, Any]:
    db = await get_db()
    try:
        cursor = await db.execute(
            # Q11a: роль нужна билдеру биндингов — бот-модератор подставляется сам
            "SELECT c.id, c.channel_name, c.account_id, c.enabled, a.nickname, a.bot_role "
            "FROM channels c JOIN accounts a ON a.id = c.account_id "
            "ORDER BY c.channel_name, a.nickname"
        )
        rows = await cursor.fetchall()
    finally:
        await db.close()
    statuses = _runtime_manager().get_all_statuses()
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        channel = row["channel_name"]
        entry = grouped.setdefault(channel, {"channel": channel, "bot_count": 0, "connected_count": 0, "bots": []})
        status = statuses.get(row["account_id"], {})
        connected = bool(status.get("connected") and channel in (status.get("channels") or []))
        entry["bot_count"] += 1
        entry["connected_count"] += int(connected)
        entry["bots"].append({
            "account_id": row["account_id"],
            "binding_id": row["id"],
            "nickname": row["nickname"],
            "role": (row["bot_role"] if "bot_role" in row.keys() else "") or "",
            "enabled": bool(row["enabled"]),
            "connected": connected,
        })
    return {"channels": list(grouped.values())}


@router.post("/api/bulk/channels")
async def start_bulk_channels(data: dict[str, Any]) -> dict[str, Any]:
    direction = str(data.get("direction") or "")
    if direction not in {"bots_to_channels", "channel_to_bots"}:
        return {"ok": False, "code": "invalid_direction", "params": {}}
    try:
        account_ids = list(dict.fromkeys(int(value) for value in (data.get("account_ids") or []) if int(value) > 0))
    except (TypeError, ValueError):
        return {"ok": False, "code": "invalid_account_ids", "params": {}}
    raw_channels = data.get("channels") or []
    if isinstance(raw_channels, str):
        raw_channels = re.split(r"[,\s]+", raw_channels)
    channels = list(dict.fromkeys(str(value).lower().strip().lstrip("#") for value in raw_channels if str(value).strip()))
    if not account_ids or len(account_ids) > 100:
        return {"ok": False, "code": "invalid_account_ids", "params": {}}
    if not channels or len(channels) > 25 or any(not _CHANNEL_RE.fullmatch(channel) for channel in channels):
        return {"ok": False, "code": "invalid_channels", "params": {}}
    if len(account_ids) * len(channels) > 500:
        return {"ok": False, "code": "too_many_pairs", "params": {}}
    # Q07/DEC-OWNER-011: контрольное сообщение опционально, по умолчанию выкл.
    send_message = bool(data.get("send_message"))
    message_template = str(data.get("message_template") or DEFAULT_CHECK_MESSAGE).strip()
    if send_message and (not message_template or len(message_template) > 450):
        return {"ok": False, "code": "invalid_message", "params": {}}
    try:
        read_timeout = max(30, min(60, int(data.get("read_timeout", 45))))
    except (TypeError, ValueError):
        read_timeout = 45

    job_id = uuid.uuid4().hex
    job: dict[str, Any] = {
        "ok": True,
        "job_id": job_id,
        "status": "running",
        "direction": direction,
        "account_ids": account_ids,
        "channels": channels,
        "message_template": message_template,
        "send_message": send_message,
        "read_timeout": read_timeout,
        "results": [],
    }
    _jobs[job_id] = job
    job["task"] = asyncio.create_task(_execute_job(job_id))
    return _public_job(job)


@router.get("/api/bulk/channels/{job_id}")
async def get_bulk_channels(job_id: str) -> dict[str, Any]:
    job = _jobs.get(job_id)
    return _public_job(job) if job else {"ok": False, "code": "bulk_not_found", "params": {}}


@router.post("/api/bulk/channels/{job_id}/cancel")
async def cancel_bulk_channels(job_id: str) -> dict[str, Any]:
    job = _jobs.get(job_id)
    if not job:
        return {"ok": False, "code": "bulk_not_found", "params": {}}
    task = job.get("task")
    if task and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    return _public_job(job)


async def cancel_active_bulk_jobs() -> None:
    tasks = [job.get("task") for job in _jobs.values() if job.get("task")]
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)



# ── Q08(в) (DEC-OWNER-006): массовая смена канала для выбранных ботов ──
async def _change_channel_pairs(
    account_ids: list[int], channel: str, replace: bool,
    accounts: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for account_id in account_ids:
        account = accounts.get(account_id)
        item: dict[str, Any] = {
            "account_id": account_id,
            "nickname": str((account or {}).get("nickname") or ""),
            "channel": channel,
            "result": "error",
            "reason": "bot_not_found" if not account else "change_failed",
            "detached": 0,
        }
        pair_enabled = False
        if account:
            db = await get_db()
            try:
                detached = 0
                if replace:
                    cursor = await db.execute(
                        "DELETE FROM channels WHERE account_id = ? AND channel_name != ?",
                        (account_id, channel),
                    )
                    detached = cursor.rowcount
                cursor = await db.execute(
                    "INSERT OR IGNORE INTO channels (account_id, channel_name, enabled) VALUES (?, ?, 1)",
                    (account_id, channel),
                )
                await db.commit()
                existing = await (await db.execute(
                    "SELECT enabled FROM channels WHERE account_id = ? AND channel_name = ?",
                    (account_id, channel),
                )).fetchone()
                pair_enabled = bool(existing and existing["enabled"])
                if cursor.rowcount:
                    item.update(
                        result="changed" if (replace and detached) else "added",
                        reason="ok", detached=detached,
                    )
                elif pair_enabled:
                    item.update(result="skipped", reason="already_exists", detached=detached)
                else:
                    item.update(result="skipped", reason="binding_disabled", detached=detached)
            except Exception:
                item.update(result="error", reason="change_failed")
            finally:
                await db.close()
        if pair_enabled:
            bot_manager = _runtime_manager()
            status = bot_manager.get_status(account_id)
            if status.get("connected") and channel not in (status.get("channels") or []):
                try:
                    await bot_manager.join_channel(account_id, channel)
                except Exception:
                    pass  # join повторится обычным реконнектом; отчёт — по привязке в БД
        items.append(item)
    return items


def _change_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"changed": 0, "added": 0, "skipped": 0, "errors": 0}
    for item in items:
        counts["errors" if item["result"] == "error" else item["result"]] += 1
    return counts


async def _execute_change_job(job_id: str) -> None:
    job = _jobs[job_id]
    summary = (
        f"direction=change_channel channel={job['channel']} replace={job['replace']} "
        f"bots={len(job['account_ids'])}"
    )
    try:
        accounts = await _load_accounts(job["account_ids"])
        items = await _change_channel_pairs(
            job["account_ids"], job["channel"], job["replace"], accounts,
        )
        job.update(status="completed", results=items, counts=_change_counts(items))
        counts = job["counts"]
        await log_action(
            "bulk_channels",
            f"{summary} changed={counts['changed']} added={counts['added']} "
            f"skipped={counts['skipped']} errors={counts['errors']}",
        )
    except asyncio.CancelledError:
        job.update(status="cancelled", results=[])
        await log_action("bulk_channels", f"{summary} cancelled=1")
    except Exception:
        job.update(status="failed", error="bulk_failed")
        await log_action("bulk_channels", f"{summary} failed=1")
    finally:
        job.pop("task", None)
        _prune_jobs()


@router.post("/api/bulk/change-channel")
async def start_bulk_change_channel(data: dict[str, Any]) -> dict[str, Any]:
    try:
        account_ids = list(dict.fromkeys(
            int(value) for value in (data.get("account_ids") or []) if int(value) > 0
        ))
    except (TypeError, ValueError):
        return {"ok": False, "code": "invalid_account_ids", "params": {}}
    channel = str(data.get("channel") or "").lower().strip().lstrip("#")
    if not account_ids or len(account_ids) > 100:
        return {"ok": False, "code": "invalid_account_ids", "params": {}}
    if not _CHANNEL_RE.fullmatch(channel):
        return {"ok": False, "code": "invalid_channels", "params": {}}
    replace = bool(data.get("replace"))

    job_id = uuid.uuid4().hex
    job: dict[str, Any] = {
        "ok": True,
        "job_id": job_id,
        "status": "running",
        "direction": "change_channel",
        "account_ids": account_ids,
        "channels": [channel],
        "channel": channel,
        "replace": replace,
        "results": [],
    }
    _jobs[job_id] = job
    job["task"] = asyncio.create_task(_execute_change_job(job_id))
    return _public_job(job)


@router.post("/api/channels/{channel}/start")
async def start_channel_bots(channel: str, stagger: bool = False) -> dict[str, Any]:
    """Запускает свободных ботов, привязанных к конкретному каналу,

    подключая их ТОЛЬКО к этому каналу (не пуская на другие каналы).
    Боты, уже работающие на другом канале, пропускаются (Вариант 1).
    Учитывает квоты, отбор самых активных (chatter) и подгонку под зрителей (Q39).
    При stagger=True использует плавный заход ботов (Staggered Join).
    """
    channel_clean = channel.lower().strip().lstrip("#")
    if not _CHANNEL_RE.fullmatch(channel_clean):
        return {"ok": False, "error": "invalid_channel"}

    from app.server import bot_manager, eventsub_manager, chat_analyzer
    from app.instance_lock import acquire_account_lock, release_account_lock
    from app.bootstrap import start_account
    from app.bot_dirs import migrate_bot_dir
    from app.bot_fleet import filter_and_limit_bots, get_channel_fleet_settings

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT a.* FROM accounts a "
            "JOIN channels c ON a.id = c.account_id "
            "WHERE LOWER(c.channel_name) = ? AND a.enabled = 1 AND c.enabled = 1",
            (channel_clean,),
        )
        raw_accounts = await cursor.fetchall()
    finally:
        await db.close()

    candidate_dicts = [dict(a) for a in raw_accounts]
    selected_accounts = await filter_and_limit_bots(channel_clean, candidate_dicts)
    selected_ids = {a["id"] for a in selected_accounts}

    fleet_cfg = await get_channel_fleet_settings(channel_clean)
    started: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for acc in candidate_dicts:
        aid = acc["id"]
        nickname = acc["nickname"]

        if aid not in selected_ids:
            skipped.append({"id": aid, "nickname": nickname, "reason": "limit_reached"})
            continue

        if bot_manager.is_running(aid):
            status = bot_manager.get_status(aid)
            cur_channels = [ch.lower().lstrip("#") for ch in (status.get("channels") or [])]
            if channel_clean in cur_channels:
                skipped.append({"id": aid, "nickname": nickname, "reason": "already_connected"})
            else:
                # Вариант 1: бот уже занят на другом канале — не срываем со стрима
                skipped.append({
                    "id": aid,
                    "nickname": nickname,
                    "reason": "busy_on_other_channel",
                    "channels": cur_channels,
                })
            continue

        if not acquire_account_lock(aid):
            skipped.append({"id": aid, "nickname": nickname, "reason": "locked"})
            continue

        try:
            await migrate_bot_dir(aid, nickname)
        except Exception:
            pass

        # Плавный заход ботов (Staggered Join, #2)
        if stagger and len(started) > 0:
            import random
            s_min = float(fleet_cfg.get("stagger_sec_min") or 2.0)
            s_max = float(fleet_cfg.get("stagger_sec_max") or 6.0)
            delay = round(random.uniform(s_min, s_max), 2)
            await asyncio.sleep(delay)

        # Запускаем бота ТОЛЬКО на этот целевой канал!
        ok = await start_account(
            bot_manager,
            chat_analyzer,
            dict(acc),
            [channel_clean],
            eventsub_manager=eventsub_manager,
        )
        if ok:
            started.append({"id": aid, "nickname": nickname})
            await log_action("Канал запущен", f"#{channel_clean} ← {nickname}")
        else:
            release_account_lock(aid)
            skipped.append({"id": aid, "nickname": nickname, "reason": "start_failed"})

    return {
        "ok": True,
        "channel": channel_clean,
        "started": started,
        "skipped": skipped,
        "count": len(started),
    }


@router.post("/api/channels/{channel}/stop")
async def stop_channel_bots(channel: str) -> dict[str, Any]:
    """Отключает ботов от конкретного канала.

    Если канал был единственным у бота — бот останавливается полностью.
    Если у бота есть другие каналы — бот только выходит из этого чата.
    """
    channel_clean = channel.lower().strip().lstrip("#")
    if not _CHANNEL_RE.fullmatch(channel_clean):
        return {"ok": False, "error": "invalid_channel"}

    from app.server import bot_manager, eventsub_manager
    from app.instance_lock import release_account_lock

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT a.id, a.nickname FROM accounts a "
            "JOIN channels c ON a.id = c.account_id "
            "WHERE LOWER(c.channel_name) = ?",
            (channel_clean,),
        )
        accounts = await cursor.fetchall()
    finally:
        await db.close()

    stopped: list[dict[str, Any]] = []

    for acc in accounts:
        aid = acc["id"]
        nickname = acc["nickname"]

        if not bot_manager.is_running(aid):
            continue

        status = bot_manager.get_status(aid)
        cur_channels = [ch.lower().lstrip("#") for ch in (status.get("channels") or [])]

        if channel_clean not in cur_channels:
            continue

        if len(cur_channels) <= 1:
            # Канал единственный — останавливаем бота целиком
            bot_manager.set_desired(aid, None)
            await bot_manager.stop_bot(aid)
            if eventsub_manager:
                try:
                    await eventsub_manager.stop_for_account(aid)
                except Exception:
                    pass
            release_account_lock(aid)
            stopped.append({"id": aid, "nickname": nickname, "action": "stopped_bot"})
            await log_action("Бот остановлен", f"#{channel_clean} (канал остановлен) ← {nickname}")
        else:
            # У бота есть другие каналы — только выходим из этого
            await bot_manager.leave_channel(aid, channel_clean)
            get_des = getattr(bot_manager, "get_desired", None)
            desired = get_des(aid) if callable(get_des) else None
            if desired and "channels" in desired:
                desired["channels"] = [c for c in desired["channels"] if c.lower().lstrip("#") != channel_clean]
                bot_manager.set_desired(aid, desired)
            stopped.append({"id": aid, "nickname": nickname, "action": "left_channel"})
            await log_action("Бот покинул канал", f"#{channel_clean} ← {nickname}")

    return {
        "ok": True,
        "channel": channel_clean,
        "stopped": stopped,
        "count": len(stopped),
    }
