"""v9 AP/AQ: SENTIMENT TIMELINE + WORD CLOUD + TRENDING — вынесено из
app/routes.py (P5-сплит, PLAN.md). Декорирует ОБЩИЙ router из app.routes;
импортируется ВНИЗУ routes.py (после создания router).
"""
from typing import Any

from app.database import get_db
from app.routes import router  # noqa: E402 — валиден: импорт из конца routes.py


# ===================== v9 AP: SENTIMENT TIMELINE =====================

@router.get("/api/stats/sentiment")
async def get_sentiment_timeline(
    hours: int = 24,
    account_id: int = 0,
    channel: str = "",
    bucket_min: int = 5,
    include_bots: bool = False,
) -> dict:
    """Sentiment timeline — pos/neg/neu/net по 5-мин бакетам.

    Возвращает {hours, bucket_min, total, summary{pos,neg,neu,total,net}, points[]}.
    """
    from app.sentiment import aggregate_buckets

    hours = max(1, min(720, int(hours)))
    bucket_min = max(1, min(120, int(bucket_min)))
    bucket_size_sec = bucket_min * 60
    channel = (channel or "").strip().lstrip("#")

    db = await get_db()
    try:
        sql = (
            "SELECT timestamp, sentiment FROM chat_log "
            "WHERE timestamp > datetime('now', ?) "
        )
        params: list[Any] = [f"-{hours} hours"]
        if not include_bots:
            sql += "AND is_bot = 0 "
        if channel:
            sql += "AND channel = ? "
            params.append(channel)
        if account_id:
            sql += "AND account_id = ? "
            params.append(account_id)
        cursor = await db.execute(sql, tuple(params))
        rows = await cursor.fetchall()
    finally:
        await db.close()

    pairs = [(str(r["timestamp"]), int(r["sentiment"] or 0)) for r in rows]
    points = aggregate_buckets(pairs, bucket_size_sec=bucket_size_sec)
    total_pos = sum(p["pos"] for p in points)
    total_neg = sum(p["neg"] for p in points)
    total_neu = sum(p["neu"] for p in points)
    total_all = total_pos + total_neg + total_neu

    return {
        "hours": hours,
        "bucket_min": bucket_min,
        "channel": channel,
        "account_id": account_id,
        "total": total_all,
        "summary": {
            "pos": total_pos,
            "neg": total_neg,
            "neu": total_neu,
            "total": total_all,
            "net": total_pos - total_neg,
            "pos_pct": round(total_pos / total_all * 100, 1) if total_all else 0.0,
            "neg_pct": round(total_neg / total_all * 100, 1) if total_all else 0.0,
            "neu_pct": round(total_neu / total_all * 100, 1) if total_all else 0.0,
        },
        "points": points,
    }


@router.post("/api/stats/sentiment/backfill")
async def backfill_sentiment(limit: int = 5000, only_zero: bool = True) -> dict:
    """Бэкфилл sentiment для существующих сообщений (sentiment IS NULL OR = 0).

    Возвращает {scanned, updated}. Безопасно вызывать несколько раз.
    """
    from app.sentiment import classify as _classify

    limit = max(1, min(50000, int(limit)))
    db = await get_db()
    try:
        sql = "SELECT id, message FROM chat_log "
        if only_zero:
            sql += "WHERE sentiment = 0 OR sentiment IS NULL "
        sql += "ORDER BY id DESC LIMIT ?"
        cursor = await db.execute(sql, (limit,))
        rows = await cursor.fetchall()

        scanned = len(rows)
        updated = 0
        for r in rows:
            new_label = _classify(r["message"] or "")
            if new_label != 0:
                await db.execute(
                    "UPDATE chat_log SET sentiment = ? WHERE id = ?",
                    (new_label, r["id"]),
                )
                updated += 1
        await db.commit()
    finally:
        await db.close()

    return {"scanned": scanned, "updated": updated}


# ===================== v9 AQ: WORD CLOUD + TRENDING =====================

@router.get("/api/stats/wordcloud")
async def get_wordcloud(
    hours: int = 24,
    account_id: int = 0,
    channel: str = "",
    top_n: int = 50,
    include_bots: bool = False,
) -> dict:
    """Word cloud — top-N слов в чате за период.

    Возвращает {hours, top_n, total_messages, total_words, items: [{word, count}]}.
    """
    from app.word_stats import count_words, top_n as _top_n

    hours = max(1, min(720, int(hours)))
    top_n = max(5, min(200, int(top_n)))
    channel = (channel or "").strip().lstrip("#")

    db = await get_db()
    try:
        sql = "SELECT message FROM chat_log WHERE timestamp > datetime('now', ?) "
        params: list[Any] = [f"-{hours} hours"]
        if not include_bots:
            sql += "AND is_bot = 0 "
        if channel:
            sql += "AND channel = ? "
            params.append(channel)
        if account_id:
            sql += "AND account_id = ? "
            params.append(account_id)
        cursor = await db.execute(sql, tuple(params))
        rows = await cursor.fetchall()
    finally:
        await db.close()

    messages = [r["message"] for r in rows]
    counter = count_words(messages)
    items = [{"word": w, "count": c} for w, c in _top_n(counter, top_n)]

    return {
        "hours": hours,
        "channel": channel,
        "account_id": account_id,
        "top_n": top_n,
        "total_messages": len(messages),
        "total_words": sum(counter.values()),
        "unique_words": len(counter),
        "items": items,
    }


@router.get("/api/stats/trending")
async def get_trending(
    period: str = "hour",
    account_id: int = 0,
    channel: str = "",
    top_n: int = 20,
    min_current: int = 3,
    include_bots: bool = False,
) -> dict:
    """Trending topics — слова, которые выросли по сравнению с предыдущим периодом.

    period = 'hour' (current 1h vs previous 6h) или 'day' (current 1d vs previous 7d).
    Возвращает {period, trending: [...], cooling: [...]}.
    """
    from app.word_stats import count_words, trending as _trending, cooling as _cooling

    period = (period or "hour").lower()
    if period not in ("hour", "day", "30min"):
        period = "hour"
    top_n = max(3, min(100, int(top_n)))
    channel = (channel or "").strip().lstrip("#")

    if period == "30min":
        cur_window = "-30 minutes"
        base_window_start = "-3 hours"
        base_window_end = "-30 minutes"
    elif period == "day":
        cur_window = "-1 day"
        base_window_start = "-8 days"
        base_window_end = "-1 day"
    else:
        cur_window = "-1 hour"
        base_window_start = "-7 hours"
        base_window_end = "-1 hour"

    async def _fetch(start: str, end: str | None = None) -> list[str]:
        sql = "SELECT message FROM chat_log WHERE timestamp > datetime('now', ?) "
        params: list[Any] = [start]
        if end is not None:
            sql += "AND timestamp <= datetime('now', ?) "
            params.append(end)
        if not include_bots:
            sql += "AND is_bot = 0 "
        if channel:
            sql += "AND channel = ? "
            params.append(channel)
        if account_id:
            sql += "AND account_id = ? "
            params.append(account_id)
        cursor = await db.execute(sql, tuple(params))
        rows = await cursor.fetchall()
        return [r["message"] for r in rows]

    db = await get_db()
    try:
        cur_msgs = await _fetch(cur_window)
        base_msgs = await _fetch(base_window_start, base_window_end)
    finally:
        await db.close()

    cur_counter = count_words(cur_msgs)
    base_counter = count_words(base_msgs)
    trending_rows = _trending(cur_counter, base_counter, min_current=min_current)[:top_n]
    cooling_rows = _cooling(cur_counter, base_counter, min_baseline=min_current)[:top_n]

    return {
        "period": period,
        "channel": channel,
        "account_id": account_id,
        "current_messages": len(cur_msgs),
        "baseline_messages": len(base_msgs),
        "current_unique": len(cur_counter),
        "baseline_unique": len(base_counter),
        "trending": trending_rows,
        "cooling": cooling_rows,
    }
