"""search — вынесено из app/routes.py (P5-сплит, PLAN.md). Декорирует ОБЩИЙ
router из app.routes; импортируется ВНИЗУ routes.py (после создания router).
"""
from app.database import get_db
import json

from app.routes import router  # noqa: E402


# ===================== Feature T: GLOBAL SEARCH =====================

@router.get("/api/search")
async def global_search(q: str = "", account_id: int = 0, limit: int = 50) -> dict:
    """Глобальный поиск (Ctrl+K command palette).

    Ищет вхождения подстроки ``q`` (case-insensitive) во всех сущностях:
    аккаунты, каналы, паттерны, персоны, триггеры, фразы, банлист, фильтр слов,
    события, расписание, факты в памяти, последние сообщения чата.
    Если ``account_id`` > 0 — фильтрует по нему (где это применимо).
    """
    q = (q or "").strip()
    if not q or len(q) < 2:
        return {"results": [], "total": 0}
    like = f"%{q}%"

    results: list[dict] = []
    db = await get_db()
    try:
        # ---- 1. Аккаунты ----
        cursor = await db.execute(
            "SELECT id, nickname FROM accounts WHERE nickname LIKE ? ORDER BY id LIMIT ?",
            (like, limit),
        )
        for r in await cursor.fetchall():
            results.append({
                "kind": "account",
                "title": r["nickname"],
                "subtitle": "Аккаунт",
                "icon": "👤",
                "tab": "accounts",
                "payload": {"account_id": r["id"]},
            })

        # ---- 2. Каналы ----
        cursor = await db.execute(
            "SELECT c.id, c.channel_name, c.account_id, a.nickname "
            "FROM channels c JOIN accounts a ON a.id = c.account_id "
            "WHERE c.channel_name LIKE ? ORDER BY c.id LIMIT ?",
            (like, limit),
        )
        for r in await cursor.fetchall():
            results.append({
                "kind": "channel",
                "title": "#" + r["channel_name"],
                "subtitle": f"Канал @ {r['nickname']}",
                "icon": "📺",
                "tab": "accounts",
                "payload": {"account_id": r["account_id"], "channel": r["channel_name"]},
            })

        # ---- 4. Персоны ----
        cursor = await db.execute(
            "SELECT pe.id, pe.name, pe.system_prompt, pe.account_id, a.nickname "
            "FROM personas pe JOIN accounts a ON a.id = pe.account_id "
            "WHERE pe.name LIKE ? OR pe.system_prompt LIKE ? "
            "ORDER BY pe.id DESC LIMIT ?",
            (like, like, limit),
        )
        for r in await cursor.fetchall():
            results.append({
                "kind": "persona",
                "title": r["name"] or "(без имени)",
                "subtitle": "Характер @ " + r["nickname"],
                "icon": "🎭",
                "tab": "personas",
                "payload": {"persona_id": r["id"], "account_id": r["account_id"]},
            })

        # ---- 5. Триггеры ----
        cursor = await db.execute(
            "SELECT t.id, t.keyword, t.response, t.account_id, a.nickname "
            "FROM triggers t JOIN accounts a ON a.id = t.account_id "
            "WHERE t.keyword LIKE ? OR t.response LIKE ? "
            "ORDER BY t.id DESC LIMIT ?",
            (like, like, limit),
        )
        for r in await cursor.fetchall():
            results.append({
                "kind": "trigger",
                "title": r["keyword"],
                "subtitle": (r["response"] or "")[:80] + " @ " + r["nickname"],
                "icon": "⚡",
                "tab": "triggers",
                "payload": {"trigger_id": r["id"], "account_id": r["account_id"]},
            })

        # ---- 6. Быстрые фразы ----
        cursor = await db.execute(
            "SELECT qp.id, qp.phrase, qp.account_id, a.nickname "
            "FROM quick_phrases qp JOIN accounts a ON a.id = qp.account_id "
            "WHERE qp.phrase LIKE ? ORDER BY qp.id DESC LIMIT ?",
            (like, limit),
        )
        for r in await cursor.fetchall():
            results.append({
                "kind": "phrase",
                "title": r["phrase"],
                "subtitle": "Быстрая фраза @ " + r["nickname"],
                "icon": "💭",
                "tab": "chat",
                "payload": {"account_id": r["account_id"]},
            })

        # ---- 7. Бан-лист ----
        cursor = await db.execute(
            "SELECT b.id, b.username, b.account_id, a.nickname "
            "FROM banlist b JOIN accounts a ON a.id = b.account_id "
            "WHERE b.username LIKE ? ORDER BY b.id DESC LIMIT ?",
            (like, limit),
        )
        for r in await cursor.fetchall():
            results.append({
                "kind": "banlist",
                "title": r["username"],
                "subtitle": "В бан-листе @ " + r["nickname"],
                "icon": "🚫",
                "tab": "banlist",
                "payload": {"account_id": r["account_id"]},
            })

        # ---- 8. Word-filter ----
        cursor = await db.execute(
            "SELECT w.id, w.word, w.account_id, a.nickname "
            "FROM word_filter w JOIN accounts a ON a.id = w.account_id "
            "WHERE w.word LIKE ? ORDER BY w.id DESC LIMIT ?",
            (like, limit),
        )
        for r in await cursor.fetchall():
            results.append({
                "kind": "wordfilter",
                "title": r["word"],
                "subtitle": "Фильтр слов @ " + r["nickname"],
                "icon": "🛡️",
                "tab": "wordfilter",
                "payload": {"account_id": r["account_id"]},
            })

        # ---- 9. События ----
        cursor = await db.execute(
            "SELECT e.id, e.event_type, e.response, e.account_id, a.nickname "
            "FROM event_responses e JOIN accounts a ON a.id = e.account_id "
            "WHERE e.event_type LIKE ? OR e.response LIKE ? "
            "ORDER BY e.id DESC LIMIT ?",
            (like, like, limit),
        )
        for r in await cursor.fetchall():
            results.append({
                "kind": "event",
                "title": r["event_type"],
                "subtitle": (r["response"] or "")[:80] + " @ " + r["nickname"],
                "icon": "🔔",
                "tab": "events",
                "payload": {"event_id": r["id"], "account_id": r["account_id"]},
            })

        # ---- 10. Расписание ----
        cursor = await db.execute(
            "SELECT s.id, s.message, s.channel, s.account_id, a.nickname "
            "FROM scheduled_messages s JOIN accounts a ON a.id = s.account_id "
            "WHERE s.message LIKE ? OR s.channel LIKE ? "
            "ORDER BY s.id DESC LIMIT ?",
            (like, like, limit),
        )
        for r in await cursor.fetchall():
            results.append({
                "kind": "scheduled",
                "title": (r["message"] or "")[:60] or "(пустое)",
                "subtitle": f"Расписание #{r['channel']} @ " + r["nickname"],
                "icon": "⏰",
                "tab": "scheduled",
                "payload": {"sched_id": r["id"], "account_id": r["account_id"]},
            })

        # ---- 11. Память + факты ----
        cursor = await db.execute(
            "SELECT um.username, um.facts, um.msg_count, um.account_id, a.nickname "
            "FROM user_memory um JOIN accounts a ON a.id = um.account_id "
            "WHERE um.username LIKE ? OR um.facts LIKE ? "
            "ORDER BY um.msg_count DESC LIMIT ?",
            (like, like, limit),
        )
        for r in await cursor.fetchall():
            facts_str = (r["facts"] or "[]").replace('"', "")
            subtitle = f"Память: {r['msg_count']} сообщ. @ {r['nickname']}"
            if q.lower() in facts_str.lower():
                # Покажем первый факт со совпадением
                try:
                    facts = json.loads(r["facts"]) if r["facts"] else []
                    for f in facts:
                        if q.lower() in f.lower():
                            subtitle = f"💡 {f[:70]} @ " + r["nickname"]
                            break
                except Exception:
                    pass
            results.append({
                "kind": "memory",
                "title": r["username"],
                "subtitle": subtitle,
                "icon": "🧠",
                "tab": "memory",
                "payload": {"account_id": r["account_id"], "username": r["username"]},
            })

        # ---- 12. Чат-лог (последние сообщения) ----
        cursor = await db.execute(
            "SELECT id, channel, author, message, timestamp, is_bot "
            "FROM chat_log WHERE message LIKE ? OR author LIKE ? "
            "ORDER BY id DESC LIMIT ?",
            (like, like, min(limit, 30)),
        )
        for r in await cursor.fetchall():
            ts = str(r["timestamp"])[:19]
            results.append({
                "kind": "chat",
                "title": f"{r['author']}: {(r['message'] or '')[:70]}",
                "subtitle": f"{ts}  #{r['channel']}",
                "icon": "🤖" if r["is_bot"] else "💬",
                "tab": "logs",
                "payload": {
                    "search": q,
                    "channel": r["channel"],
                    "author": r["author"],
                },
            })

        # ---- 13. Вкладки UI (статический список) ----
        TABS_INDEX = [
            ("dashboard", "📊", "Главная", "обзор статистика главная"),
            ("livechat", "💬", "Живой чат", "live chat realtime"),
            ("accounts", "👤", "Аккаунты", "accounts токены"),
            ("chat", "💭", "Отправить в чат", "send chat сообщение"),
            ("logs", "📜", "Логи", "logs история"),
            ("ai", "🧠", "AI Мозг", "openrouter ollama gpt модель ai"),
            ("chatai", "🔍", "Анализ чата", "analyzer auto-chat авто"),
            ("personas", "🎭", "Характеры", "personas character"),
            ("memory", "🧠", "Память", "memory facts факты"),
            ("triggers", "⚡", "Триггеры", "triggers keywords"),
            ("events", "🔔", "События", "events sub raid follow"),
            ("scheduled", "⏰", "Расписание", "scheduled timer"),
            ("banlist", "🚫", "Бан-лист", "banlist ban"),
            ("wordfilter", "🛡️", "Фильтр слов", "filter wordfilter"),
            ("graphs", "📈", "Графики", "graphs analytics heatmap аналитика"),
            ("highlights", "🎬", "Хайлайты", "highlights clip кліп клипы хайлайт"),
            ("stats", "📉", "Статистика", "stats"),
            ("actionlog", "📓", "Журнал", "action log журнал"),
            ("obs", "📺", "OBS", "obs widget tts"),
            ("settings", "⚙️", "Настройки", "settings"),
            ("faq", "❓", "FAQ", "faq help"),
        ]
        ql = q.lower()
        for slug, icon, name, kw in TABS_INDEX:
            if ql in name.lower() or ql in slug.lower() or ql in kw.lower():
                results.append({
                    "kind": "tab",
                    "title": name,
                    "subtitle": "Вкладка",
                    "icon": icon,
                    "tab": slug,
                    "payload": {},
                })
    finally:
        await db.close()

    # Простой scoring: точное совпадение в title — выше, иначе — по позиции.
    def _score(item: dict) -> tuple[int, int]:
        ql_l = q.lower()
        title_l = (item.get("title") or "").lower()
        sub_l = (item.get("subtitle") or "").lower()
        if title_l == ql_l:
            return (0, 0)
        pos = title_l.find(ql_l)
        if pos >= 0:
            return (1, pos)
        pos = sub_l.find(ql_l)
        if pos >= 0:
            return (2, pos)
        return (3, 0)

    results.sort(key=_score)
    return {"results": results[:limit * 2], "total": len(results), "query": q}
