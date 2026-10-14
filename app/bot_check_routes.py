"""Owner API for cancellable, transient Twitch bot checks."""

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


router = APIRouter(dependencies=[Depends(auth_dependency)], tags=["bot-check"])
_jobs: dict[str, dict[str, Any]] = {}
_CHANNEL_RE = re.compile(r"^[a-z0-9_]{1,25}$")


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in job.items() if key != "task"}


def _prune_jobs() -> None:
    completed = [key for key, job in _jobs.items() if job["status"] != "running"]
    for key in completed[:-20]:
        _jobs.pop(key, None)


async def _load_accounts(account_ids: list[int]) -> list[dict[str, Any]]:
    db = await get_db()
    try:
        placeholders = ",".join("?" for _ in account_ids)
        cursor = await db.execute(
            f"SELECT id, nickname, token FROM accounts WHERE id IN ({placeholders})", account_ids,
        )
        found = {row["id"]: dict(row) for row in await cursor.fetchall()}
    finally:
        await db.close()
    return [found.get(account_id, {"id": account_id, "nickname": "", "missing": True}) for account_id in account_ids]


async def _execute_job(job_id: str, accounts: list[dict[str, Any]]) -> None:
    job = _jobs[job_id]
    try:
        results = await run_bot_check(
            accounts, job["channel"], job["message_template"], read_timeout=job["read_timeout"],
            send_message=job["send_message"],
        )
        job["results"] = results
        job["status"] = "completed"
        counts = {"success": 0, "not_confirmed": 0, "error": 0}
        for result in results:
            counts[result["result"]] = counts.get(result["result"], 0) + 1
        job["counts"] = counts
        await log_action(
            "bot_check",
            f"direction=check channel={job['channel']} success={counts['success']} "
            f"not_confirmed={counts['not_confirmed']} error={counts['error']}",
        )
    except asyncio.CancelledError:
        job["status"] = "cancelled"
        job["results"] = []
        await log_action("bot_check", f"direction=check channel={job['channel']} cancelled=1")
    except Exception:
        job["status"] = "failed"
        job["error"] = "check_failed"
        await log_action("bot_check", f"direction=check channel={job['channel']} failed=1")
    finally:
        job.pop("task", None)
        _prune_jobs()


@router.post("/api/bot-checks")
async def start_bot_check(data: dict[str, Any]) -> dict[str, Any]:
    raw_ids = data.get("account_ids") or []
    try:
        account_ids = list(dict.fromkeys(int(value) for value in raw_ids if int(value) > 0))
    except (TypeError, ValueError):
        return {"ok": False, "code": "invalid_account_ids", "params": {}}
    if not account_ids or len(account_ids) > 100:
        return {"ok": False, "code": "invalid_account_ids", "params": {}}
    channel = str(data.get("channel") or "").lower().strip().lstrip("#")
    if not _CHANNEL_RE.fullmatch(channel):
        return {"ok": False, "code": "invalid_channel", "params": {}}
    # Q07/DEC-OWNER-011: контрольное сообщение опционально, по умолчанию выкл.
    send_message = bool(data.get("send_message"))
    message_template = str(data.get("message_template") or DEFAULT_CHECK_MESSAGE).strip()
    if send_message and (not message_template or len(message_template) > 450):
        return {"ok": False, "code": "invalid_message", "params": {}}
    try:
        read_timeout = max(30, min(60, int(data.get("read_timeout", 45))))
    except (TypeError, ValueError):
        read_timeout = 45

    accounts = await _load_accounts(account_ids)
    job_id = uuid.uuid4().hex
    job: dict[str, Any] = {
        "ok": True,
        "check_id": job_id,
        "status": "running",
        "channel": channel,
        "message_template": message_template,
        "send_message": send_message,
        "read_timeout": read_timeout,
        "results": [],
    }
    _jobs[job_id] = job
    job["task"] = asyncio.create_task(_execute_job(job_id, accounts))
    return _public_job(job)


@router.get("/api/bot-checks/{job_id}")
async def get_bot_check(job_id: str) -> dict[str, Any]:
    job = _jobs.get(job_id)
    if not job:
        return {"ok": False, "code": "check_not_found", "params": {}}
    return _public_job(job)


@router.post("/api/bot-checks/{job_id}/cancel")
async def cancel_bot_check(job_id: str) -> dict[str, Any]:
    job = _jobs.get(job_id)
    if not job:
        return {"ok": False, "code": "check_not_found", "params": {}}
    task = job.get("task")
    if task and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    return _public_job(job)


async def cancel_active_checks() -> None:
    tasks = [job.get("task") for job in _jobs.values() if job.get("task")]
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

