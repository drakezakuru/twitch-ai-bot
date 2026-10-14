"""ai_summary — вынесено из app/routes.py (P5-сплит, PLAN.md). Декорирует ОБЩИЙ
router из app.routes; импортируется ВНИЗУ routes.py (после создания router).
"""
from typing import Any

from app.database import get_db
from app.routes import logger
from app.routes import router  # noqa: E402


# ===================== Feature U: AI SUMMARY =====================

@router.post("/api/ai/summary")
async def ai_chat_summary(data: dict[str, Any]) -> dict:
    """AI-резюме «что было пока я отходил» за последние N минут.

    Body: {"minutes": 10|30|60, "channel": "name?" , "account_id": int?, "max_messages": int?}.
    Возвращает: {"summary": str, "msg_count": int, "events": [...], "minutes": int}.
    """
    from app.server import ai_service

    try:
        minutes = int(data.get("minutes") or 10)
    except (TypeError, ValueError):
        minutes = 10
    minutes = max(1, min(360, minutes))
    channel = (data.get("channel") or "").strip().lstrip("#")
    try:
        account_id = int(data.get("account_id") or 0)
    except (TypeError, ValueError):
        account_id = 0
    try:
        max_messages = int(data.get("max_messages") or 250)
    except (TypeError, ValueError):
        max_messages = 250
    max_messages = max(20, min(500, max_messages))

    db = await get_db()
    try:
        # Сообщения чата
        sql = (
            "SELECT timestamp, author, message, channel, is_bot "
            "FROM chat_log WHERE timestamp > datetime('now', ?) "
        )
        params: list[Any] = [f"-{minutes} minutes"]
        if channel:
            sql += "AND channel = ? "
            params.append(channel)
        if account_id:
            sql += "AND (account_id = ? OR account_id IS NULL) "
            params.append(account_id)
        sql += "ORDER BY id DESC LIMIT ?"
        params.append(max_messages)
        cursor = await db.execute(sql, tuple(params))
        rows = list(reversed(await cursor.fetchall()))

        # Последние EventSub-события из action_log
        cursor = await db.execute(
            "SELECT timestamp, action, detail FROM action_log "
            "WHERE timestamp > datetime('now', ?) AND action LIKE 'eventsub_%' "
            "ORDER BY id DESC LIMIT 50",
            (f"-{minutes} minutes",),
        )
        events_rows = list(reversed(await cursor.fetchall()))
    finally:
        await db.close()

    if not rows:
        return {
            "summary": f"_За последние {minutes} мин. сообщений не было._",
            "msg_count": 0,
            "minutes": minutes,
            "events": [],
        }

    # Формируем компактный лог для AI
    lines: list[str] = []
    char_budget = 7500
    used = 0
    for r in rows:
        ts = str(r["timestamp"])[11:19]
        prefix = "[BOT] " if r["is_bot"] else ""
        line = f"{ts} #{r['channel']} {prefix}{r['author']}: {(r['message'] or '')[:200]}"
        if used + len(line) + 1 > char_budget:
            break
        lines.append(line)
        used += len(line) + 1

    chat_dump = "\n".join(lines)
    events_dump = ""
    if events_rows:
        ev_lines = []
        for ev in events_rows:
            ts = str(ev["timestamp"])[11:19]
            ev_lines.append(f"{ts} {ev['action']}: {(ev['detail'] or '')[:120]}")
        events_dump = "\n".join(ev_lines)

    prompt = (
        f"Ниже — лог Twitch-чата за последние {minutes} минут.\n"
        f"Напиши краткое резюме на русском (3–5 буллет-пунктов, маркировка `-`):\n"
        f"  • что обсуждали / основная тема\n"
        f"  • кто что важное спросил или сказал\n"
        f"  • были ли заметные события (саб/рейд/донат/бан)\n"
        f"  • общий тон/настроение чата\n"
        f"Без воды, только факты. Если событий нет — пропусти этот пункт.\n\n"
        f"=== ЧАТ ===\n{chat_dump}\n"
    )
    if events_dump:
        prompt += f"\n=== СОБЫТИЯ (EventSub) ===\n{events_dump}\n"

    try:
        summary = await ai_service.generate_text(
            prompt,
            system="Ты помощник Twitch-стримера. Пишешь сжатые, информативные резюме чата.",
            account_id=account_id,
            channel=channel,
        )
    except Exception as exc:
        logger.warning("AI summary error: %s", exc)
        return {
            "summary": f"_Ошибка AI: {exc}_",
            "msg_count": len(rows),
            "minutes": minutes,
            "events": [dict(e) for e in events_rows],
            "error": str(exc),
        }

    # P8-C8.3: подпись провайдера — видно, кто делал резюме
    provider_label = ""
    try:
        prov, model, _v, _k = ai_service._resolve(account_id)
        provider_label = f"{prov}/{model}" if (prov and model) else (prov or "")
    except Exception:
        provider_label = ""

    return {
        "summary": (summary or "").strip() or "_(AI вернул пустой ответ)_",
        "provider_label": provider_label,
        "msg_count": len(rows),
        "minutes": minutes,
        "events": [
            {"timestamp": str(e["timestamp"]), "action": e["action"], "detail": e["detail"]}
            for e in events_rows
        ],
    }
