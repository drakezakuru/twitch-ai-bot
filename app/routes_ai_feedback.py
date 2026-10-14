"""ai_feedback — вынесено из app/routes.py (P5-сплит, PLAN.md). Декорирует ОБЩИЙ
router из app.routes; импортируется ВНИЗУ routes.py (после создания router).
"""
from app.database import get_db
from app.routes import logger, router
from app.routes import router, Any  # noqa: E402


# ===================== v10.2: AI FEEDBACK 👍/👎 =====================

@router.post("/api/ai-feedback")
async def post_ai_feedback(data: dict[str, Any]) -> dict:
    """Сохранить 👍/👎 фидбэк на ответ AI.

    body: ``{account_id, channel, event_type, message, rating}``
    rating: +1 (👍) или -1 (👎).
    """
    account_id = int(data.get("account_id") or 0)
    channel = str(data.get("channel") or "")
    event_type = str(data.get("event_type") or "send")
    message = str(data.get("message") or "")
    rating = int(data.get("rating") or 0)
    if rating not in (1, -1):
        return {"ok": False, "error": "rating must be 1 or -1"}
    # §7.1 §9k: расширенная категория оценки (длинный/токсичный/не в стиле/мимо темы)
    category = str(data.get("category") or "").strip().lower()
    if category not in ("", "too_long", "toxic", "off_style", "off_topic", "other"):
        category = "" 
    db = await get_db()
    try:
        # Убеждаемся что аккаунт существует, иначе FK падает.
        if account_id > 0:
            cur = await db.execute("SELECT 1 FROM accounts WHERE id=?", (account_id,))
            row = await cur.fetchone()
            if not row:
                account_id = 0  # фидбэк без привязки к аккаунту
        # Если account_id=0, используем 1-й аккаунт (или вставляем NULL — но FK не позволит).
        if account_id == 0:
            cur = await db.execute("SELECT id FROM accounts ORDER BY id LIMIT 1")
            row = await cur.fetchone()
            if row:
                account_id = row["id"] if isinstance(row, dict) or hasattr(row, "keys") else row[0]
            else:
                return {"ok": False, "error": "no accounts in DB"}
        await db.execute(
            "INSERT INTO ai_feedback (account_id, channel, event_type, message, rating, category) VALUES (?,?,?,?,?,?)",
            (account_id, channel, event_type, message, rating, category),
        )
        await db.commit()
        # §R4 PLAN_SESSION_ROLES: самообучение болтуна — 👍 ответ уходит в
        # learned_pool стиля, 👎 — исключается из пула.
        try:
            from app.bot_roles import learn_from_feedback
            cur2 = await db.execute(
                "SELECT role_config_json FROM accounts WHERE id = ?", (account_id,))
            acc_row = await cur2.fetchone()
            if acc_row and (acc_row["role_config_json"] or "").strip():
                new_json = learn_from_feedback(acc_row["role_config_json"], message, rating)
                if new_json:
                    await db.execute(
                        "UPDATE accounts SET role_config_json = ? WHERE id = ?",
                        (new_json, account_id),
                    )
                    await db.commit()
        except Exception as exc:
            logger.debug("chatter self-learn failed: %s", exc)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        await db.close()


@router.get("/api/ai-feedback/stats")
async def get_ai_feedback_stats(account_id: int = 0) -> dict:
    """Агрегированная статистика фидбэка.

    P8-C14: account_id>0 → per-bot (оценки ответов конкретного бота),
    иначе — глобально (как раньше).
    """
    db = await get_db()
    try:
        where, params = "", []
        if account_id > 0:
            where = " WHERE account_id = ?"
            params.append(int(account_id))
        cursor = await db.execute(
            f"SELECT rating, COUNT(*) as cnt FROM ai_feedback{where} GROUP BY rating",
            params,
        )
        rows = await cursor.fetchall()
        stats = {r["rating"]: r["cnt"] for r in rows}
        # §7.1 §9k: разбивка по категориям отрицательных оценок
        cat_cursor = await db.execute(
            f"SELECT category, COUNT(*) as cnt FROM ai_feedback"
            f"{(' WHERE account_id = ?' if account_id > 0 else '')}"
            f"{' AND ' if account_id > 0 else ' WHERE '}category != '' "
            "GROUP BY category ORDER BY cnt DESC",
            params,
        )
        categories = {r["category"]: r["cnt"] for r in await cat_cursor.fetchall()}
        return {
            "total": sum(stats.values()),
            "positive": stats.get(1, 0),
            "negative": stats.get(-1, 0),
            "categories": categories,
        }
    finally:
        await db.close()
