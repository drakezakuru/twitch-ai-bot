"""maintenance — вынесено из app/routes.py (P5-сплит, PLAN.md). Декорирует ОБЩИЙ
router из app.routes; импортируется ВНИЗУ routes.py (после создания router).
"""
from app.routes import logger
from app.routes import log_action, router
from app.routes import router  # noqa: E402


# ===================== OPS_PLAN §4/§5: MAINTENANCE + VERSION =====================

@router.get("/api/version")
async def api_version() -> dict:
    """Версия приложения — показывается в footer панели."""
    from app.version import APP_VERSION, VERSION_LABEL
    return {"version": APP_VERSION, "label": VERSION_LABEL}


@router.get("/api/maintenance/db-stats")
async def maintenance_db_stats() -> dict:
    """Статистика БД: размер + количество записей (Настройки → БД)."""
    from app.maintenance import db_stats
    return db_stats()


@router.post("/api/maintenance/optimize")
async def maintenance_optimize() -> dict:
    """Кнопка «Оптимизировать» (Настройки → БД): PRAGMA optimize + VACUUM."""
    import sqlite3
    from app import database
    from app.maintenance import run_sqlite_optimize

    await run_sqlite_optimize()
    before = database.DB_PATH.stat().st_size if database.DB_PATH.exists() else 0
    try:
        conn = sqlite3.connect(str(database.DB_PATH))
        try:
            conn.execute("VACUUM")
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("VACUUM failed: %s", exc)
        return {"ok": False, "error": str(exc)}
    after = database.DB_PATH.stat().st_size if database.DB_PATH.exists() else 0
    await log_action("db_optimize", f"VACUUM: {before} → {after} байт")
    return {"ok": True, "before": before, "after": after}


@router.post("/api/maintenance/cleanup")
async def maintenance_cleanup(data: dict | None = None) -> dict:
    """Очистка старых записей логов (bot_logs, chat_log, ai_feedback, moderation_events, action_log)."""
    from app.maintenance import cleanup_database_logs
    days = 30
    if isinstance(data, dict) and "days" in data:
        try:
            days = max(1, int(data["days"]))
        except (ValueError, TypeError):
            pass
    results = await cleanup_database_logs(days)
    total = sum(results.values())
    await log_action("db_cleanup", f"Очищено {total} записей логов старше {days} дней")
    return {"ok": True, "days": days, "deleted": results, "total_deleted": total}
