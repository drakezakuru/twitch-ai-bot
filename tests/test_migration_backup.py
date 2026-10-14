"""PLAN_FEEDBACK_3008 §9: снапшот БД перед миграциями + проверка восстановления."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app import database as db_mod


def _make_db(path: Path, rows: int = 1) -> None:
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS t1 (id INTEGER PRIMARY KEY, v TEXT);
        DELETE FROM t1;
        """
    )
    for i in range(rows):
        con.execute("INSERT INTO t1 (v) VALUES (?)", (f"row{i}",))
    con.commit()
    con.close()


def _backups_dir(tmp_db: Path) -> Path:
    return tmp_db.parent / "backups"


@pytest.mark.asyncio
async def test_backup_creates_verified_copy(tmp_db):
    _make_db(tmp_db)
    dest = await db_mod.backup_before_migration("test", force=True)
    assert dest is not None
    assert dest.exists() and dest.parent == _backups_dir(tmp_db)
    assert dest.name.startswith("bot.db.test-")
    # проверка восстановления: копия читается, данные внутри
    assert db_mod._verify_backup_copy(dest)
    con = sqlite3.connect(dest)
    assert con.execute("SELECT count(*) FROM t1").fetchone()[0] == 1
    con.close()


@pytest.mark.asyncio
async def test_backup_dedup_skips_identical_db(tmp_db):
    _make_db(tmp_db)
    first = await db_mod.backup_before_migration("test", force=True)
    second = await db_mod.backup_before_migration("test")  # без force, тот же контент
    assert first is not None and second is None
    assert len(list(_backups_dir(tmp_db).glob("bot.db.*.db"))) == 1


@pytest.mark.asyncio
async def test_backup_changed_db_copies_again(tmp_db):
    _make_db(tmp_db)
    first = await db_mod.backup_before_migration("test", force=True)
    _make_db(tmp_db, rows=2)  # контент изменился
    second = await db_mod.backup_before_migration("test")
    assert first is not None and second is not None
    assert first != second


@pytest.mark.asyncio
async def test_backup_rotation_keeps_last_n(tmp_db, monkeypatch):
    monkeypatch.setenv("MIGRATION_BACKUP_KEEP", "2")
    for i in range(1, 4):
        _make_db(tmp_db, rows=i)  # разный контент, чтобы не сработал дедуп
        await db_mod.backup_before_migration("test", force=True)
    files = sorted(_backups_dir(tmp_db).glob("bot.db.*.db"))
    assert len(files) == 2


@pytest.mark.asyncio
async def test_backup_skipped_for_fresh_empty_db(tmp_db):
    # 0-байтная БД (свежая установка) — снапшот не нужен
    tmp_db.write_bytes(b"")
    assert await db_mod.backup_before_migration("test", force=True) is None
    assert not _backups_dir(tmp_db).exists()


@pytest.mark.asyncio
async def test_backup_failure_returns_none_without_required(tmp_db, monkeypatch):
    _make_db(tmp_db)

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(db_mod.shutil, "copy2", boom)
    assert await db_mod.backup_before_migration("test", force=True) is None
    assert not list(_backups_dir(tmp_db).glob("bot.db.*.db"))


@pytest.mark.asyncio
async def test_backup_failure_raises_with_required(tmp_db, monkeypatch):
    _make_db(tmp_db)

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(db_mod.shutil, "copy2", boom)
    with pytest.raises(RuntimeError):
        await db_mod.backup_before_migration("test", force=True, required=True)


@pytest.mark.asyncio
async def test_init_db_creates_pre_migration_snapshot(tmp_db):
    """Полный init_db на существующей БД должен оставить снапшот в data/backups."""
    _make_db(tmp_db, rows=3)
    await db_mod.init_db()
    snaps = list(_backups_dir(tmp_db).glob("bot.db.pre-migration-*.db"))
    assert snaps, "снапшот pre-migration не создан"
    assert db_mod._verify_backup_copy(snaps[-1])
