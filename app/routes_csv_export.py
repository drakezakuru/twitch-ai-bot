"""csv_export — вынесено из app/routes.py (P5-сплит, PLAN.md). Декорирует ОБЩИЙ
router из app.routes; импортируется ВНИЗУ routes.py (после создания router).
"""
from typing import Any

from fastapi import Response
from fastapi.responses import StreamingResponse

from app.database import get_db
from app.routes import router  # noqa: E402


# ===================== v10 BA: CSV EXPORT =====================

@router.get("/api/chat-log/export.csv")
async def export_chat_log_csv(
    hours: int = 24,
    account_id: int = 0,
    channel: str = "",
    include_bots: bool = True,
    sentiment: str = "",
    limit: int = 50000,
) -> StreamingResponse:
    """v10 BA: CSV-экспорт chat_log с фильтрами.

    sentiment = '' (все) | 'pos' | 'neg' | 'neu'.
    """
    import csv as _csv
    import io

    hours = max(1, min(8760, int(hours)))  # до года
    limit = max(1, min(500000, int(limit)))
    channel = (channel or "").strip().lstrip("#")

    where: list[str] = ["timestamp > datetime('now', ?)"]
    params: list[Any] = [f"-{hours} hours"]
    if not include_bots:
        where.append("is_bot = 0")
    if channel:
        where.append("channel = ?")
        params.append(channel)
    if account_id:
        where.append("account_id = ?")
        params.append(account_id)
    sentiment = (sentiment or "").lower()
    if sentiment == "pos":
        where.append("sentiment = 1")
    elif sentiment == "neg":
        where.append("sentiment = -1")
    elif sentiment == "neu":
        where.append("sentiment = 0")
    where_sql = " WHERE " + " AND ".join(where)

    db = await get_db()
    try:
        cursor = await db.execute(
            f"SELECT timestamp, account_id, channel, author, is_bot, sentiment, message FROM chat_log{where_sql} ORDER BY id ASC LIMIT ?",
            tuple(params + [limit]),
        )
        rows = await cursor.fetchall()
    finally:
        await db.close()

    buf = io.StringIO()
    writer = _csv.writer(buf, quoting=_csv.QUOTE_ALL)
    writer.writerow(["timestamp", "account_id", "channel", "author", "is_bot", "sentiment", "message"])
    for r in rows:
        writer.writerow([
            r["timestamp"],
            r["account_id"] or 0,
            r["channel"],
            r["author"],
            r["is_bot"],
            r["sentiment"] if r["sentiment"] is not None else 0,
            r["message"],
        ])
    csv_text = buf.getvalue()
    buf.close()

    filename_parts = ["chat_log", f"{hours}h"]
    if channel:
        filename_parts.append(channel)
    if sentiment:
        filename_parts.append(sentiment)
    filename = "_".join(filename_parts) + ".csv"

    return StreamingResponse(
        iter([csv_text]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/action-log/export.csv")
async def export_action_log_csv(
    action: str = "",
    q: str = "",
    from_ts: str = "",
    to_ts: str = "",
    actor: str = "",
    limit: int = 50000,
) -> StreamingResponse:
    """v10 BA + v10.3 5: CSV-экспорт action_log с теми же фильтрами + actor."""
    import csv as _csv
    import io

    limit = max(1, min(500000, int(limit)))
    where: list[str] = []
    params: list[Any] = []
    if action:
        where.append("action = ?")
        params.append(action.strip())
    if q:
        where.append("(action LIKE ? OR detail LIKE ?)")
        params.append(f"%{q.strip()}%")
        params.append(f"%{q.strip()}%")
    if from_ts:
        where.append("timestamp >= ?")
        params.append(from_ts.strip())
    if to_ts:
        where.append("timestamp <= ?")
        params.append(to_ts.strip())
    if actor:
        where.append("actor = ?")
        params.append(actor.strip())
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    db = await get_db()
    try:
        cursor = await db.execute(
            f"SELECT timestamp, actor, action, detail FROM action_log{where_sql} ORDER BY id DESC LIMIT ?",
            tuple(params + [limit]),
        )
        rows = await cursor.fetchall()
    finally:
        await db.close()

    buf = io.StringIO()
    writer = _csv.writer(buf, quoting=_csv.QUOTE_ALL)
    writer.writerow(["timestamp", "actor", "action", "detail"])
    for r in rows:
        writer.writerow([
            r["timestamp"],
            (r["actor"] if "actor" in r.keys() else "") or "",
            r["action"],
            r["detail"],
        ])
    csv_text = buf.getvalue()
    buf.close()

    return StreamingResponse(
        iter([csv_text]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="action_log.csv"'},
    )
