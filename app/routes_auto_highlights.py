"""auto_highlights — вынесено из app/routes.py (P5-сплит, PLAN.md). Декорирует ОБЩИЙ
router из app.routes; импортируется ВНИЗУ routes.py (после создания router).
"""
from typing import Any

from app.database import get_db
from app.routes import logger
from app.routes import router  # noqa: E402


# ===================== AUTO-HIGHLIGHTS & POST-STREAM REPORT =====================

@router.post("/api/stream/auto-highlights")
async def stream_auto_highlights(data: dict[str, Any]) -> dict:
    """Generate YouTube-format timestamped highlights from clip moments and chat spikes.

    Body: {"account_id": int, "channel": str, "stream_duration_minutes": int?}
    """
    import datetime as _dt
    from app.server import ai_service

    account_id = int(data.get("account_id") or 0)
    channel = (data.get("channel") or "").strip().lower()
    try:
        stream_duration = int(data.get("stream_duration_minutes") or 180)
    except (TypeError, ValueError):
        stream_duration = 180
    stream_duration = max(1, min(1440, stream_duration))

    db = await get_db()
    try:
        # Query clip_moments for this account
        clip_sql = (
            "SELECT id, rate, avg_rate, clip_url, timestamp, created_at "
            "FROM clip_moments WHERE account_id = ? "
        )
        clip_params: list[Any] = [account_id]
        if channel:
            clip_sql += "AND channel = ? "
            clip_params.append(channel)
        clip_sql += "ORDER BY created_at DESC LIMIT 100"
        cursor = await db.execute(clip_sql, tuple(clip_params))
        clip_rows = await cursor.fetchall()

        # Query chat_log grouped by 5-minute windows to find spikes
        chat_sql = (
            "SELECT strftime('%Y-%m-%d %H:%M', timestamp, 'start of minute', "
            "printf('-%d minutes', cast(strftime('%M', timestamp) as int) % 5)) as window, "
            "COUNT(*) as msg_count "
            "FROM chat_log WHERE timestamp > datetime('now', ?) "
        )
        chat_params: list[Any] = [f"-{stream_duration} minutes"]
        if channel:
            chat_sql += "AND channel = ? "
            chat_params.append(channel)
        if account_id:
            chat_sql += "AND (account_id = ? OR account_id IS NULL) "
            chat_params.append(account_id)
        chat_sql += "GROUP BY window ORDER BY window"
        cursor = await db.execute(chat_sql, tuple(chat_params))
        chat_windows = await cursor.fetchall()
    finally:
        await db.close()

    # Calculate average chat rate and find spikes (2x+ average)
    chat_spikes = []
    if chat_windows:
        total_msgs = sum(r[1] for r in chat_windows)
        avg_msgs = total_msgs / len(chat_windows) if chat_windows else 1
        for row in chat_windows:
            if row[1] >= avg_msgs * 2:
                chat_spikes.append({"window": row[0], "count": row[1], "avg": round(avg_msgs, 1)})

    # Build prompt for AI
    clips_text = ""
    if clip_rows:
        clips_lines = []
        for c in clip_rows[:50]:
            clips_lines.append(
                f"- Clip at {c[4] or c[5]}: rate={c[1]:.1f}, avg_rate={c[2]:.1f}, url={c[3] or 'N/A'}"
            )
        clips_text = "\n".join(clips_lines)

    spikes_text = ""
    if chat_spikes:
        spikes_lines = []
        for s in chat_spikes[:30]:
            spikes_lines.append(f"- Chat spike at {s['window']}: {s['count']} msgs (avg: {s['avg']})")
        spikes_text = "\n".join(spikes_lines)

    if not clips_text and not spikes_text:
        return {
            "highlights": [],
            "message": "No clip moments or chat spikes found for this stream.",
        }

    prompt = (
        "You are a stream highlights editor. Based on the data below, generate YouTube-format "
        "timestamps with descriptions for the best moments of the stream.\n\n"
        "Format each highlight as:\n"
        "TIMESTAMP | TITLE | DESCRIPTION | SOURCE\n"
        "Where TIMESTAMP is like 00:05:23, TITLE is a short catchy title, "
        "DESCRIPTION explains what happened, SOURCE is 'clip' or 'chat_spike'.\n\n"
    )
    if clips_text:
        prompt += f"=== CLIP MOMENTS ===\n{clips_text}\n\n"
    if spikes_text:
        prompt += f"=== CHAT ACTIVITY SPIKES ===\n{spikes_text}\n\n"
    prompt += (
        f"Stream duration: ~{stream_duration} minutes.\n"
        "Generate 5-15 highlights, ordered chronologically. Be creative with titles."
    )

    try:
        raw_response = await ai_service.generate_text(
            prompt,
            system="You are a YouTube video editor assistant. Generate concise, engaging timestamps for stream highlights.",
            account_id=account_id,
            channel=channel,
        )
    except Exception as exc:
        logger.warning("AI auto-highlights error: %s", exc)
        return {"highlights": [], "error": "AI generation failed"}

    # Parse AI response into structured highlights
    highlights = []
    if raw_response:
        for line in raw_response.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 3:
                highlights.append({
                    "timestamp": parts[0].lstrip("- "),
                    "title": parts[1],
                    "description": parts[2],
                    "source": parts[3] if len(parts) > 3 else "clip",
                })

    # Store result in stream_reports table
    import json as _json
    report_data = _json.dumps({
        "highlights": highlights,
        "clip_count": len(clip_rows),
        "spike_count": len(chat_spikes),
    }, ensure_ascii=False)

    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO stream_reports (account_id, channel, report_type, data) VALUES (?, ?, ?, ?)",
            (account_id, channel, "auto_highlights", report_data),
        )
        await db.commit()
    finally:
        await db.close()

    result_dict: dict[str, Any] = {"highlights": highlights}
    # If parsing produced no highlights but AI returned content, note parse failure
    if not highlights and raw_response and raw_response.strip():
        result_dict["parse_note"] = "AI response could not be parsed into structured format"
    return result_dict


@router.post("/api/stream/post-report")
async def stream_post_report(data: dict[str, Any]) -> dict:
    """Generate comprehensive post-stream report with stats and AI analysis.

    Body: {"account_id": int, "channel": str, "minutes": int?}
    """
    import datetime as _dt
    from app.server import ai_service

    account_id = int(data.get("account_id") or 0)
    channel = (data.get("channel") or "").strip().lower()
    try:
        minutes = int(data.get("minutes") or 0)
    except (TypeError, ValueError):
        minutes = 0

    db = await get_db()
    try:
        # If minutes not specified, try to get from stream_session
        if minutes <= 0:
            cursor = await db.execute(
                "SELECT start_time FROM stream_session WHERE is_live = 0 ORDER BY id DESC LIMIT 1"
            )
            row = await cursor.fetchone()
            if row and row[0]:
                minutes = 240  # default 4 hours if session found but can't calculate
            else:
                minutes = 240  # default
        minutes = max(1, min(1440, minutes))

        time_filter = f"-{minutes} minutes"

        # Top chatters (message count by author)
        chat_sql = (
            "SELECT author, COUNT(*) as cnt FROM chat_log "
            "WHERE timestamp > datetime('now', ?) AND is_bot = 0 "
        )
        chat_params: list[Any] = [time_filter]
        if channel:
            chat_sql += "AND channel = ? "
            chat_params.append(channel)
        if account_id:
            chat_sql += "AND (account_id = ? OR account_id IS NULL) "
            chat_params.append(account_id)
        chat_sql += "GROUP BY author ORDER BY cnt DESC LIMIT 10"
        cursor = await db.execute(chat_sql, tuple(chat_params))
        top_chatters_rows = await cursor.fetchall()

        # Total messages and unique chatters
        stats_sql = (
            "SELECT COUNT(*) as total, COUNT(DISTINCT author) as uniq FROM chat_log "
            "WHERE timestamp > datetime('now', ?) AND is_bot = 0 "
        )
        stats_params: list[Any] = [time_filter]
        if channel:
            stats_sql += "AND channel = ? "
            stats_params.append(channel)
        if account_id:
            stats_sql += "AND (account_id = ? OR account_id IS NULL) "
            stats_params.append(account_id)
        cursor = await db.execute(stats_sql, tuple(stats_params))
        stats_row = await cursor.fetchone()
        total_messages = stats_row[0] if stats_row else 0
        unique_chatters = stats_row[1] if stats_row else 0

        # Peak activity period (5-min window with most messages)
        peak_sql = (
            "SELECT strftime('%H:%M', timestamp) as t5, COUNT(*) as cnt FROM chat_log "
            "WHERE timestamp > datetime('now', ?) AND is_bot = 0 "
        )
        peak_params: list[Any] = [time_filter]
        if channel:
            peak_sql += "AND channel = ? "
            peak_params.append(channel)
        if account_id:
            peak_sql += "AND (account_id = ? OR account_id IS NULL) "
            peak_params.append(account_id)
        peak_sql += "GROUP BY t5 ORDER BY cnt DESC LIMIT 1"
        cursor = await db.execute(peak_sql, tuple(peak_params))
        peak_row = await cursor.fetchone()
        peak_activity = peak_row[0] if peak_row else "N/A"

        # Recent events (follows, subs, cheers, raids)
        cursor = await db.execute(
            "SELECT kind, COUNT(*) as cnt FROM recent_events "
            "WHERE created_at > datetime('now', ?) GROUP BY kind",
            (time_filter,),
        )
        events_rows = await cursor.fetchall()
        events_summary = {"follows": 0, "subs": 0, "cheers": 0, "raids": 0}
        for ev in events_rows:
            kind = (ev[0] or "").lower()
            if "follow" in kind:
                events_summary["follows"] += ev[1]
            elif "sub" in kind:
                events_summary["subs"] += ev[1]
            elif "cheer" in kind or "bit" in kind:
                events_summary["cheers"] += ev[1]
            elif "raid" in kind:
                events_summary["raids"] += ev[1]

        # Clips created during stream
        clip_sql = (
            "SELECT id, rate, avg_rate, clip_url, timestamp, created_at "
            "FROM clip_moments WHERE created_at > datetime('now', ?) "
        )
        clip_params2: list[Any] = [time_filter]
        if account_id:
            clip_sql += "AND account_id = ? "
            clip_params2.append(account_id)
        if channel:
            clip_sql += "AND channel = ? "
            clip_params2.append(channel)
        clip_sql += "ORDER BY rate DESC LIMIT 20"
        cursor = await db.execute(clip_sql, tuple(clip_params2))
        clip_rows = await cursor.fetchall()

        # Sample of chat messages for AI analysis (last 300 non-bot)
        sample_sql = (
            "SELECT timestamp, author, message FROM chat_log "
            "WHERE timestamp > datetime('now', ?) AND is_bot = 0 "
        )
        sample_params: list[Any] = [time_filter]
        if channel:
            sample_sql += "AND channel = ? "
            sample_params.append(channel)
        if account_id:
            sample_sql += "AND (account_id = ? OR account_id IS NULL) "
            sample_params.append(account_id)
        sample_sql += "ORDER BY id DESC LIMIT 300"
        cursor = await db.execute(sample_sql, tuple(sample_params))
        sample_rows = list(reversed(await cursor.fetchall()))
    finally:
        await db.close()

    top_chatters = [{"username": r[0], "count": r[1]} for r in top_chatters_rows]
    clips = []
    for c in clip_rows:
        clips.append({
            "id": c[0], "rate": c[1], "avg_rate": c[2],
            "clip_url": c[3] or "", "timestamp": c[4] or "", "created_at": str(c[5] or ""),
        })

    # Build AI prompt with all the data
    chat_sample_text = ""
    char_budget = 6000
    used = 0
    lines: list[str] = []
    for r in sample_rows:
        line = f"{str(r[0])[11:19]} {r[1]}: {(r[2] or '')[:150]}"
        if used + len(line) + 1 > char_budget:
            break
        lines.append(line)
        used += len(line) + 1
    chat_sample_text = "\n".join(lines)

    prompt = (
        f"Analyze this stream session data and provide:\n"
        f"1. A brief summary of the stream (2-3 sentences)\n"
        f"2. Most discussed topics (list 3-5 topics)\n"
        f"3. Recommendations for next stream (3-5 actionable items)\n\n"
        f"=== STATS ===\n"
        f"Duration: ~{minutes} minutes\n"
        f"Total messages: {total_messages}\n"
        f"Unique chatters: {unique_chatters}\n"
        f"Top chatters: {', '.join(tc['username'] + '(' + str(tc['count']) + ')' for tc in top_chatters[:5])}\n"
        f"Events: {events_summary}\n"
        f"Clips created: {len(clips)}\n"
        f"Peak activity: around {peak_activity}\n\n"
    )
    if chat_sample_text:
        prompt += f"=== CHAT SAMPLE ===\n{chat_sample_text}\n\n"
    prompt += (
        "Respond in this exact format:\n"
        "SUMMARY: <your summary>\n"
        "TOPICS: topic1 | topic2 | topic3\n"
        "RECOMMENDATIONS: rec1 | rec2 | rec3\n"
    )

    ai_analysis = {"topics": [], "recommendations": [], "summary": ""}
    raw_ai_response = ""

    try:
        raw_ai_response = await ai_service.generate_text(
            prompt,
            system="You are a stream analytics assistant. Provide concise, actionable post-stream analysis.",
            account_id=account_id,
            channel=channel,
        )
    except Exception as exc:
        logger.warning("AI post-report error: %s", exc)
        raw_ai_response = f"Error: {exc}"

    # Parse AI response
    if raw_ai_response and not raw_ai_response.startswith("Error:"):
        for line in raw_ai_response.split("\n"):
            line = line.strip()
            if line.upper().startswith("SUMMARY:"):
                ai_analysis["summary"] = line[8:].strip()
            elif line.upper().startswith("TOPICS:"):
                ai_analysis["topics"] = [t.strip() for t in line[7:].split("|") if t.strip()]
            elif line.upper().startswith("RECOMMENDATIONS:"):
                ai_analysis["recommendations"] = [r.strip() for r in line[16:].split("|") if r.strip()]

    # If parsing produced no structured data but AI returned content, note parse failure
    parse_note = ""
    if (not ai_analysis["summary"] and not ai_analysis["topics"] and not ai_analysis["recommendations"]
            and raw_ai_response and raw_ai_response.strip() and not raw_ai_response.startswith("Error:")):
        parse_note = "AI response could not be parsed into structured format"

    result: dict[str, Any] = {
        "stats": {
            "total_messages": total_messages,
            "unique_chatters": unique_chatters,
            "top_chatters": top_chatters,
            "peak_activity_period": peak_activity,
            "events_summary": events_summary,
        },
        "clips": clips,
        "ai_analysis": ai_analysis,
    }
    if parse_note:
        result["parse_note"] = parse_note

    # Store result in stream_reports table
    import json as _json
    report_data = _json.dumps(result, ensure_ascii=False)

    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO stream_reports (account_id, channel, report_type, data) VALUES (?, ?, ?, ?)",
            (account_id, channel, "post_stream", report_data),
        )
        await db.commit()
    finally:
        await db.close()

    return result
