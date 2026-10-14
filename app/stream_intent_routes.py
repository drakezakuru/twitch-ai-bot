"""PLAN_SESSION_ROLES §R3: HTTP-слой роль-стороны стрим-инструментов.

Admin (auth панели):
    GET  /api/stream-intents/modes?account_id=    — текущие stream_tool_modes
    POST /api/stream-intents/propose              — предложить/исполнить действие
    GET  /api/stream-intents/history?account_id=  — журнал (из bot_logs)
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends
from typing import Any

from app.security import auth_dependency

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stream-intents", tags=["stream-intents"],
                   dependencies=[Depends(auth_dependency)])


@router.get("/modes")
async def get_modes(account_id: int) -> dict:
    from app.stream_intents import _load_moderator, TOOL_SCOPES

    loaded = await _load_moderator(account_id)
    if not loaded:
        return {"ok": False, "error": "not_moderator"}
    _, cfg = loaded
    modes = cfg.get("stream_tool_modes") or {}
    return {
        "ok": True,
        "modes": {tool: modes.get(tool, "off") for tool in TOOL_SCOPES},
        "scopes": TOOL_SCOPES,
    }


@router.post("/propose")
async def propose(data: dict) -> dict:
    from app.stream_intents import propose_stream_action

    try:
        account_id = int(data.get("account_id") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "error": "bad_account_id"}
    tool = str(data.get("tool") or "")
    params = data.get("params") if isinstance(data.get("params"), dict) else {}
    source = str(data.get("source") or "manual")
    return await propose_stream_action(account_id, tool, params, source=source)


@router.get("/history")
async def history(account_id: int, limit: int = 50) -> dict:
    from app.database import get_db

    limit = max(1, min(limit, 200))
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT id, account_id, channel, level, message, details, created_at "
            "FROM bot_logs WHERE account_id = ? AND category = 'event' "
            "AND details LIKE '%\"stream_tool\": true%' "
            "ORDER BY id DESC LIMIT ?",
            (int(account_id), limit),
        )
        rows = [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()
    for r in rows:
        try:
            r["details"] = json.loads(r["details"])
        except (TypeError, ValueError):
            pass
    return {"ok": True, "items": rows}
