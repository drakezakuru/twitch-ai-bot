"""OPS_PLAN §4/§6 — эксплуатация БД и логов + линт-тесты качества.

1. Миграция «старая БД (снапшот схемы v10) + init_db»: данные сохраняются,
   новые колонки добавляются, bot_logs получает категорию 'fallback'.
2. bot_logs retention: cleanup_old_logs удаляет только старые записи.
3. Maintenance-хелперы: retention/AUTO_BACKUP env-парсинг, ротация бэкапов.
4. Линт-тест: в активных шаблонах нет onclick-атрибутов с кириллицей
   (хардкод-строки в новых рендерах запрещены — только i18n-ключи).
"""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

import pytest

pytestmark = pytest.mark.asyncio


# ── 1. Миграция старой схемы ──


def _create_old_v10_schema(path: Path) -> None:
    """Снапшот v10-схемы: accounts/channels/chat_log/triggers без новых колонок,
    bot_logs со старым CHECK (без 'fallback')."""
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript("""
            CREATE TABLE accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nickname TEXT NOT NULL UNIQUE,
                token TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                channel_name TEXT NOT NULL,
                enabled INTEGER DEFAULT 1
            );
            CREATE TABLE chat_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER,
                channel TEXT,
                author TEXT,
                message TEXT,
                is_bot INTEGER DEFAULT 0,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE triggers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER,
                keyword TEXT NOT NULL,
                response TEXT NOT NULL
            );
            CREATE TABLE bot_logs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                channel    TEXT NOT NULL DEFAULT '',
                level      TEXT NOT NULL CHECK(level IN ('debug','info','warning','error')),
                category   TEXT NOT NULL CHECK(category IN ('chat','ai','tts','trigger','event','system')),
                message    TEXT NOT NULL,
                details    TEXT NOT NULL DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO accounts (nickname, token) VALUES ('oldbot', 'oauth:old');
            INSERT INTO channels (account_id, channel_name) VALUES (1, 'oldchan');
            INSERT INTO chat_log (account_id, channel, author, message, is_bot) VALUES (1, 'oldchan', 'user1', 'привет', 0);
            INSERT INTO triggers (account_id, keyword, response) VALUES (1, 'ку', 'привет');
            INSERT INTO bot_logs (account_id, channel, level, category, message) VALUES (1, 'oldchan', 'info', 'ai', 'старый лог');
        """)
        conn.commit()
    finally:
        conn.close()


def _columns(path: Path, table: str) -> list[str]:
    conn = sqlite3.connect(str(path))
    try:
        return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    finally:
        conn.close()


async def test_old_db_migration_snapshot_v10(tmp_db):
    from app import database
    _create_old_v10_schema(tmp_db)

    await database.init_db()

    # Данные не потеряны
    conn = sqlite3.connect(str(tmp_db))
    try:
        assert conn.execute("SELECT nickname FROM accounts").fetchone()[0] == "oldbot"
        assert conn.execute("SELECT COUNT(*) FROM chat_log").fetchone()[0] == 1
        assert conn.execute("SELECT keyword FROM triggers").fetchone()[0] == "ку"
        assert conn.execute("SELECT message FROM bot_logs").fetchone()[0] == "старый лог"
    finally:
        conn.close()

    # Миграционные колонки добавлены
    for col in ("sentiment",):
        assert col in _columns(tmp_db, "chat_log")
    for col in ("channel", "fires", "last_fired_at"):
        assert col in _columns(tmp_db, "triggers")
    for col in ("ai_provider_override", "persona_json", "proxy"):
        assert col in _columns(tmp_db, "accounts")

    # bot_logs: категория 'fallback' принимается (§3)
    conn = sqlite3.connect(str(tmp_db))
    try:
        conn.execute(
            "INSERT INTO bot_logs (account_id, channel, level, category, message) "
            "VALUES (1, '', 'warning', 'fallback', 'OpenRouter 429 → ollama')"
        )
        conn.commit()
        assert conn.execute(
            "SELECT COUNT(*) FROM bot_logs WHERE category = 'fallback'"
        ).fetchone()[0] == 1
    finally:
        conn.close()

    # Повторный init_db идемпотентен
    await database.init_db()


# ── 2. Retention bot_logs ──


async def test_bot_logs_retention_cleanup(tmp_db):
    from app import database
    from app.bot_logs import cleanup_old_logs, log_per_bot
    await database.init_db()

    db = await database.get_db()
    try:
        await db.execute("INSERT INTO accounts (id, nickname, token) VALUES (1, 'rtbot', 'oauth:x')")
        await db.execute(
            "INSERT INTO bot_logs (account_id, channel, level, category, message, created_at) VALUES "
            "(1, '', 'info', 'ai', 'древний', datetime('now', '-60 days')), "
            "(1, '', 'info', 'ai', 'прошлогодний', datetime('now', '-400 days')), "
            "(1, '', 'info', 'ai', 'свежий', datetime('now', '-1 day'))"
        )
        await db.commit()
    finally:
        await db.close()

    deleted = await cleanup_old_logs(30)
    assert deleted == 2

    db = await database.get_db()
    try:
        cur = await db.execute("SELECT message FROM bot_logs")
        remaining = {r["message"] for r in await cur.fetchall()}
    finally:
        await db.close()
    assert remaining == {"свежий"}

    # retention=0/отрицательный — ничего не удалять (обрабатывается в maintenance)
    from app.maintenance import run_log_retention
    monkey_days = os.environ.get("BOT_LOG_RETENTION_DAYS")
    try:
        os.environ["BOT_LOG_RETENTION_DAYS"] = "0"
        assert await run_log_retention() == 0
    finally:
        if monkey_days is None:
            os.environ.pop("BOT_LOG_RETENTION_DAYS", None)
        else:
            os.environ["BOT_LOG_RETENTION_DAYS"] = monkey_days


# ── 3. Maintenance-хелперы ──


def test_maintenance_env_parsing(monkeypatch):
    from app import maintenance
    monkeypatch.setenv("BOT_LOG_RETENTION_DAYS", "14")
    monkeypatch.setenv("AUTO_BACKUP_DAYS", "3")
    monkeypatch.setenv("AUTO_BACKUP_KEEP", "2")
    assert maintenance.retention_days() == 14
    assert maintenance.auto_backup_days() == 3
    assert maintenance.auto_backup_keep() == 2

    monkeypatch.setenv("BOT_LOG_RETENTION_DAYS", "мусор")
    assert maintenance.retention_days() == 30  # дефолт


def test_backup_rotation(monkeypatch, tmp_path):
    from app import maintenance
    monkeypatch.setattr(maintenance, "BACKUPS_DIR", tmp_path)
    for i in range(7):
        (tmp_path / f"twitch-ai-bot-backup-2026080{i}.zip").write_bytes(b"x")
    removed = maintenance._rotate_backups()
    assert removed == 2  # 7 - keep(5)
    assert len(list(tmp_path.glob("*.zip"))) == 5


# ── 4. Линт: хардкод-строки в шаблонах ──

CYRILLIC_ONCLICK = re.compile(r'onclick="[^"]*[А-Яа-яЁёІіЇїЄєҐґ][^"]*"')
# Существующие хардкоды (legacy) — фиксируем как whitelist, новые запрещены
WHITELIST = {}


def test_templates_no_hardcoded_cyrillic_onclick():
    templates_dir = Path(__file__).resolve().parent.parent / "templates"
    violations: list[str] = []
    for html in sorted(templates_dir.rglob("*.html")):
        rel = html.relative_to(templates_dir).as_posix()
        if "_backup" in rel:  # архивные копии не проверяем
            continue
        content = html.read_text(encoding="utf-8")
        allowed = WHITELIST.get(rel, set())
        for match in CYRILLIC_ONCLICK.findall(content):
            if match not in allowed:
                violations.append(f"{rel}: {match[:80]}")
    assert not violations, (
        "Хардкод-строки в onclick запрещены — используй i18n-ключи (t('key')):\n"
        + "\n".join(violations)
    )
