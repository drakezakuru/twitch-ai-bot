"""bot_logs — вынесено из app/routes.py (P5-сплит, PLAN.md). Декорирует ОБЩИЙ
router из app.routes; импортируется ВНИЗУ routes.py (после создания router).
"""
from fastapi import HTTPException

from app.routes import router  # noqa: E402


MAX_LOG_RETENTION_DAYS = 3650


# ===================== v11: BOT LOGS =====================

@router.get("/api/accounts/{account_id}/bot-logs")
async def get_bot_logs_route(
    account_id: int,
    level: str = "",
    category: str = "",
    channel: str = "",
    q: str = "",
    limit: int = 100,
    offset: int = 0,
):
    from app.bot_logs import get_bot_logs
    logs, total = await get_bot_logs(
        account_id=account_id,
        level=level or None,
        category=category or None,
        channel=channel or None,
        q=q or None,
        limit=limit,
        offset=offset,
    )
    return {"ok": True, "logs": logs, "total": total}


@router.get("/api/bot-logs")
async def get_all_bot_logs_route(
    account_id: int = 0,
    level: str = "",
    category: str = "",
    q: str = "",
    from_time: str = "",
    to_time: str = "",
    limit: int = 100,
    offset: int = 0,
):
    from app.bot_logs import get_bot_logs
    logs, total = await get_bot_logs(
        account_id=account_id or None,
        level=level or None,
        category=category or None,
        q=q or None,
        from_time=from_time or None,
        to_time=to_time or None,
        limit=limit,
        offset=offset,
    )
    return {"ok": True, "logs": logs, "total": total}


@router.get("/api/bot-logs/export")
async def export_all_bot_logs_route(
    account_id: int = 0,
    level: str = "",
    category: str = "",
    from_time: str = "",
    to_time: str = "",
):
    from app.bot_logs import get_bot_logs
    logs, _ = await get_bot_logs(
        account_id=account_id or None,
        level=level or None,
        category=category or None,
        from_time=from_time or None,
        to_time=to_time or None,
        limit=10000,
    )
    import csv
    import io
    output = io.StringIO()
    if logs:
        writer = csv.DictWriter(output, fieldnames=logs[0].keys())
        writer.writeheader()
        writer.writerows(logs)
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=bot_logs_all.csv"},
    )


@router.delete("/api/accounts/{account_id}/bot-logs")
async def cleanup_bot_logs_route(account_id: int, older_than: str = "30d"):
    from app.bot_logs import cleanup_old_logs
    days_text = older_than.removesuffix("d")
    if not older_than.endswith("d") or not days_text.isascii() or not days_text.isdecimal():
        raise HTTPException(status_code=400, detail="invalid_older_than")
    days = int(days_text)
    if not 0 <= days <= MAX_LOG_RETENTION_DAYS:
        raise HTTPException(status_code=400, detail="invalid_older_than")
    deleted = await cleanup_old_logs(days, account_id=account_id)
    return {"ok": True, "deleted": deleted}


@router.get("/api/accounts/{account_id}/bot-logs/export")
async def export_bot_logs_route(account_id: int, format: str = "json"):
    from app.bot_logs import export_logs
    content = await export_logs(account_id, fmt=format)
    if format == "csv":
        from starlette.responses import Response
        return Response(content=content, media_type="text/csv",
                       headers={"Content-Disposition": f"attachment; filename=bot_logs_{account_id}.csv"})
    else:
        return Response(content=content, media_type="application/json",
                       headers={"Content-Disposition": f"attachment; filename=bot_logs_{account_id}.json"})
