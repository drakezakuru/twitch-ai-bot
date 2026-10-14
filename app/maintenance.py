"""OPS_PLAN §4 — эксплуатация: retention логов, авто-бэкап, SQLite-обслуживание.

Запускается фоновым maintenance_loop() и в панели (server.py), и в
standalone-режиме (app/standalone.py). Все интервалы настраиваются через .env:
- BOT_LOG_RETENTION_DAYS — чистка bot_logs старше N дней (0 = не чистить, дефолт 30);
- AUTO_BACKUP_DAYS — авто-бэкап раз в N дней (0 = выключить, дефолт 7);
- AUTO_BACKUP_KEEP — сколько бэкапов хранить (дефолт 5).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import traceback
from pathlib import Path

from app import database, backup as backup_mod

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKUPS_DIR = Path(os.getenv("AUTO_BACKUP_DIR", str(PROJECT_ROOT / "data" / "backups")))


def retention_days() -> int:
    try:
        return max(0, int(os.getenv("BOT_LOG_RETENTION_DAYS", "30")))
    except ValueError:
        return 30


def auto_backup_days() -> int:
    try:
        return max(0, int(os.getenv("AUTO_BACKUP_DAYS", "7")))
    except ValueError:
        return 7


def auto_backup_keep() -> int:
    try:
        return max(1, int(os.getenv("AUTO_BACKUP_KEEP", "5")))
    except ValueError:
        return 5


async def cleanup_database_logs(days: int = 30) -> dict[str, int]:
    """Комплексная очистка старых логов: bot_logs, chat_log, ai_feedback, moderation_events, action_log."""
    days = max(1, int(days))
    results: dict[str, int] = {
        "bot_logs": 0,
        "chat_log": 0,
        "ai_feedback": 0,
        "moderation_events": 0,
        "action_log": 0,
    }

    # 1. bot_logs
    try:
        from app.bot_logs import cleanup_old_logs
        results["bot_logs"] = await cleanup_old_logs(days)
    except Exception as exc:
        logger.warning("cleanup bot_logs error: %s", exc)

    # 2. Очистка таблиц логов через aiosqlite
    db = await database.get_db()
    try:
        for tbl, col in (
            ("chat_log", "timestamp"),
            ("ai_feedback", "created_at"),
            ("moderation_events", "created_at"),
            ("action_log", "timestamp"),
        ):
            try:
                cur = await db.execute(
                    f"DELETE FROM {tbl} WHERE {col} < datetime('now', '-{days} days')"
                )
                results[tbl] = cur.rowcount if cur.rowcount > 0 else 0
            except Exception as exc:
                logger.warning("cleanup %s error: %s", tbl, exc)
        await db.commit()
    finally:
        await db.close()

    await run_sqlite_optimize()

    total_deleted = sum(results.values())
    if total_deleted > 0:
        logger.info("cleanup_database_logs(%d days): удалено %d записей: %s", days, total_deleted, results)

    return results


async def run_log_retention() -> int:
    """Чистка всех логов по retention. Возвращает число удалённых записей суммарно."""
    days = retention_days()
    if days <= 0:
        return 0
    try:
        res = await cleanup_database_logs(days)
        return sum(res.values())
    except Exception as exc:
        logger.warning("log retention failed: %s", exc)
        return 0


async def run_sqlite_optimize() -> None:
    """PRAGMA optimize — дешёвая операция, безопасно делать часто."""
    try:
        db = await database.get_db()
        try:
            await db.execute("PRAGMA optimize")
            await db.commit()
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("PRAGMA optimize failed: %s", exc)


async def run_auto_backup() -> Path | None:
    """Складывает zip-бэкап в data/backups/ и ротирует старые. Возвращает путь."""
    days = auto_backup_days()
    if days <= 0:
        return None
    try:
        BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        data, fname = await backup_mod.make_backup_zip(include_env=False)
        path = BACKUPS_DIR / fname
        path.write_bytes(data)
        logger.info("Auto-backup: %s (%.1f КБ)", path, len(data) / 1024)
        _rotate_backups()
        return path
    except Exception as exc:
        logger.warning("auto-backup failed: %s", exc)
        return None


def _rotate_backups() -> int:
    """Оставляет последние AUTO_BACKUP_KEEP zip-файлов."""
    keep = auto_backup_keep()
    files = sorted(BACKUPS_DIR.glob("twitch-ai-bot-backup-*.zip"))
    removed = 0
    for old in files[:-keep] if len(files) > keep else []:
        try:
            old.unlink()
            removed += 1
        except Exception:
            pass
    return removed


def db_stats() -> dict:
    """Статистика БД для панели (Настройки → БД): размер + количество записей."""
    db_path = database.DB_PATH
    size = db_path.stat().st_size if db_path.exists() else 0
    counts: dict[str, int] = {}
    tables = (
        "accounts", "channels", "chat_log", "bot_logs", "triggers",
        "user_memory", "event_responses", "action_log", "ai_feedback",
    )
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            for t in tables:
                try:
                    counts[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                except Exception:
                    counts[t] = -1
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("db_stats failed: %s", exc)
    return {
        "path": str(db_path),
        "size_bytes": size,
        "counts": counts,
        "retention_days": retention_days(),
        "auto_backup_days": auto_backup_days(),
    }


async def maintenance_loop(interval_sec: float = 86400.0) -> None:
    """Суточный цикл обслуживания: retention → PRAGMA optimize → авто-бэкап.

    Первый проход — через минуту после старта (дать панели подняться).
    """
    await asyncio.sleep(60)
    first = True
    _backup_counter = 0
    while True:
        try:
            deleted = await run_log_retention()
            await run_sqlite_optimize()
            if first:
                # Считаем дни с прошлого бэкапа по файлу — если свежего нет, делаем сразу
                first = False
                if auto_backup_days() > 0 and not _has_fresh_backup():
                    await run_auto_backup()
            if deleted:
                logger.info("Maintenance: удалено %d старых bot_logs", deleted)
        except asyncio.CancelledError:
            return
        except Exception:
            logger.warning("maintenance loop error: %s", traceback.format_exc())
        try:
            await asyncio.sleep(interval_sec)
        except asyncio.CancelledError:
            return


def _has_fresh_backup() -> bool:
    """Есть ли бэкап моложе AUTO_BACKUP_DAYS дней."""
    days = auto_backup_days()
    if days <= 0:
        return True
    import time
    cutoff = time.time() - days * 86400
    for f in BACKUPS_DIR.glob("twitch-ai-bot-backup-*.zip"):
        try:
            if f.stat().st_mtime >= cutoff:
                return True
        except Exception:
            pass
    return False


__all__ = [
    "retention_days",
    "auto_backup_days",
    "cleanup_database_logs",
    "run_log_retention",
    "run_sqlite_optimize",
    "run_auto_backup",
    "db_stats",
    "maintenance_loop",
]