"""highlights — вынесено из app/routes.py (P5-сплит, PLAN.md). Декорирует ОБЩИЙ
router из app.routes; импортируется ВНИЗУ routes.py (после создания router).
"""
from typing import Any

from app.database import get_db
from app.routes import router  # noqa: E402


# ===================== Feature W: HIGHLIGHTS =====================

@router.get("/api/highlights")
async def get_highlights(
    hours: int = 12,
    account_id: int = 0,
    channel: str = "",
    min_count: int = 8,
    spike_factor: float = 2.0,
    top_n: int = 20,
) -> dict:
    """Highlight / clip detector — всплески реакции в чате."""
    from app.highlights import detect_highlights, DEFAULT_REACTION_TOKENS

    hours = max(1, min(168, hours))  # до недели
    channel = (channel or "").strip().lstrip("#")
    spike_factor = max(1.1, min(10.0, float(spike_factor)))
    min_count = max(2, min(200, int(min_count)))
    top_n = max(1, min(100, int(top_n)))

    db = await get_db()
    try:
        sql = (
            "SELECT timestamp, channel, author, message FROM chat_log "
            "WHERE timestamp > datetime('now', ?) AND is_bot = 0 "
        )
        params: list[Any] = [f"-{hours} hours"]
        if channel:
            sql += "AND channel = ? "
            params.append(channel)
        if account_id:
            sql += "AND account_id = ? "
            params.append(account_id)
        sql += "ORDER BY id ASC"
        cursor = await db.execute(sql, tuple(params))
        rows = [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()

    highlights = detect_highlights(
        rows,
        min_count=min_count,
        spike_factor=spike_factor,
        top_n=top_n,
    )
    return {
        "hours": hours,
        "channel": channel,
        "account_id": account_id,
        "total_messages": len(rows),
        "highlights": [h.to_dict() for h in highlights],
        "reaction_tokens": list(DEFAULT_REACTION_TOKENS),
    }
