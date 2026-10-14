"""BC-4: полный CRUD каналов — зависимости, переименование и перенос между ботами.

Панель раньше умела только добавить и удалить канал, причём удаление сносило
строку `channels`, оставляя висеть данные других таблиц (лог чата, биндинги
виджетов, overrides...). Здесь собраны операции, которые честно считают
зависимости перед удалением и переносят данные при переименовании/смене бота.
"""
from __future__ import annotations

import sqlite3
from typing import Any

# Таблица-источник привязок канала к боту; в ней сама привязка и живёт.
CHANNELS_TABLE = "channels"


def normalize_channel(value: Any) -> str:
    return str(value or "").strip().lower().lstrip("#")


async def _columns(db, table: str) -> set[str]:
    cursor = await db.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in await cursor.fetchall()}


async def channel_scoped_tables(db) -> list[tuple[str, bool]]:
    """Таблицы с колонкой ``channel`` и признаком наличия ``account_id``.

    Список считается по фактической схеме, а не по константе: тестовая БД и
    миграции добавляют таблицы, и зашитый перечень молча устареет.
    """
    cursor = await db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    names = [row[0] for row in await cursor.fetchall()]
    result: list[tuple[str, bool]] = []
    for name in sorted(names):
        if name == CHANNELS_TABLE or name.startswith("sqlite_"):
            continue
        columns = await _columns(db, name)
        if "channel" in columns:
            result.append((name, "account_id" in columns))
    return result


async def channel_dependencies(db, account_id: int, channel: str) -> dict[str, int]:
    """Сколько строк в каждой channel-таблице держится за эту связку бот×канал."""
    normalized = normalize_channel(channel)
    counts: dict[str, int] = {}
    for table, has_account in await channel_scoped_tables(db):
        where = "lower(ltrim(channel, '#')) = ?"
        params: list[Any] = [normalized]
        if has_account:
            where = f"account_id = ? AND {where}"
            params = [account_id, normalized]
        cursor = await db.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", tuple(params))
        row = await cursor.fetchone()
        if row and row[0]:
            counts[table] = int(row[0])
    return counts


def dependency_total(counts: dict[str, int]) -> int:
    return sum(counts.values())


async def delete_channel_rows(db, account_id: int, channel: str) -> dict[str, int]:
    """Удалить channel-зависимые строки связки бот×канал (без строки `channels`)."""
    normalized = normalize_channel(channel)
    deleted: dict[str, int] = {}
    for table, has_account in await channel_scoped_tables(db):
        where = "lower(ltrim(channel, '#')) = ?"
        params: list[Any] = [normalized]
        if has_account:
            where = f"account_id = ? AND {where}"
            params = [account_id, normalized]
        cursor = await db.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", tuple(params))
        row = await cursor.fetchone()
        count = int(row[0]) if row else 0
        if count:
            await db.execute(f"DELETE FROM {table} WHERE {where}", tuple(params))
            deleted[table] = count
    return deleted


async def _unique_channel_conflicts(db, account_id: int, target_channel: str) -> list[str]:
    """Таблицы, где UNIQUE(account_id, channel) уже занят целевым каналом.

    Перенос в такой канал упал бы IntegrityError; молча затирать чужие строки
    нельзя, поэтому вызывающий обязан решить конфликт явно.
    """
    conflicts: list[str] = []
    for table, has_account in await channel_scoped_tables(db):
        if not has_account:
            continue
        columns = await _columns(db, table)
        if not {"account_id", "channel"} <= columns:
            continue
        cursor = await db.execute(f"PRAGMA index_list({table})")
        indexes = await cursor.fetchall()
        unique = False
        for index in indexes:
            if not index[2]:
                continue
            cursor = await db.execute(f"PRAGMA index_info({index[1]})")
            cols = sorted(row[2] for row in await cursor.fetchall())
            if cols == ["account_id", "channel"]:
                unique = True
                break
        if not unique:
            continue
        cursor = await db.execute(
            "SELECT 1 FROM {t} WHERE account_id = ? AND lower(ltrim(channel, '#')) = ? LIMIT 1".format(t=table),
            (account_id, target_channel),
        )
        if await cursor.fetchone():
            conflicts.append(table)
    return conflicts


async def rename_channel(
    db, account_id: int, old_channel: str, new_channel: str, *, force: bool = False,
) -> dict:
    """Переименовать канал у бота, перенеся все channel-зависимые строки."""
    old = normalize_channel(old_channel)
    new = normalize_channel(new_channel)
    if not new:
        return {"ok": False, "code": "invalid_channel_name"}
    if old == new:
        return {"ok": True, "channel_name": new, "moved": {}}

    cursor = await db.execute(
        "SELECT id FROM channels WHERE account_id = ? AND lower(ltrim(channel_name, '#')) = ?",
        (account_id, old),
    )
    if not await cursor.fetchone():
        return {"ok": False, "code": "channel_not_found"}
    cursor = await db.execute(
        "SELECT id FROM channels WHERE account_id = ? AND lower(ltrim(channel_name, '#')) = ?",
        (account_id, new),
    )
    if await cursor.fetchone():
        return {"ok": False, "code": "channel_exists"}

    conflicts = await _unique_channel_conflicts(db, account_id, new)
    if conflicts and not force:
        return {"ok": False, "code": "channel_data_conflict", "tables": conflicts}

    moved: dict[str, int] = {}
    for table, has_account in await channel_scoped_tables(db):
        where = "lower(ltrim(channel, '#')) = ?"
        params: list[Any] = [old]
        if has_account:
            where = f"account_id = ? AND {where}"
            params = [account_id, old]
        cursor = await db.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", tuple(params))
        row = await cursor.fetchone()
        count = int(row[0]) if row else 0
        if not count:
            continue
        if table in conflicts:
            # force: строки целевого канала в этой таблице уступают переносимым
            await db.execute(
                f"DELETE FROM {table} WHERE account_id = ? AND lower(ltrim(channel, '#')) = ?",
                (account_id, new),
            )
        await db.execute(f"UPDATE {table} SET channel = ? WHERE {where}", (new, *params))
        moved[table] = count

    await db.execute(
        "UPDATE channels SET channel_name = ? WHERE account_id = ? AND lower(ltrim(channel_name, '#')) = ?",
        (new, account_id, old),
    )
    await db.commit()
    return {"ok": True, "channel_name": new, "moved": moved}


async def move_channel(db, channel_id: int, target_account_id: int, *, force: bool = False) -> dict:
    """Сменить бота у канала: привязка (`channels.account_id`) и её данные."""
    cursor = await db.execute("SELECT * FROM channels WHERE id = ?", (channel_id,))
    row = await cursor.fetchone()
    if not row:
        return {"ok": False, "code": "channel_not_found"}
    source_account_id = int(row["account_id"])
    channel = normalize_channel(row["channel_name"])
    if source_account_id == int(target_account_id):
        return {"ok": True, "account_id": source_account_id, "channel_name": channel}
    cursor = await db.execute("SELECT id FROM accounts WHERE id = ?", (target_account_id,))
    if not await cursor.fetchone():
        return {"ok": False, "code": "account_not_found"}
    cursor = await db.execute(
        "SELECT id FROM channels WHERE account_id = ? AND lower(ltrim(channel_name, '#')) = ?",
        (target_account_id, channel),
    )
    if await cursor.fetchone():
        return {"ok": False, "code": "channel_exists"}

    conflicts = await _unique_channel_conflicts(db, target_account_id, channel)
    if conflicts and not force:
        return {"ok": False, "code": "channel_data_conflict", "tables": conflicts}

    moved: dict[str, int] = {}
    for table, has_account in await channel_scoped_tables(db):
        if not has_account:
            continue
        cursor = await db.execute(
            "SELECT COUNT(*) FROM {t} WHERE account_id = ? AND lower(ltrim(channel, '#')) = ?".format(t=table),
            (source_account_id, channel),
        )
        count_row = await cursor.fetchone()
        count = int(count_row[0]) if count_row else 0
        if not count:
            continue
        if table in conflicts:
            await db.execute(
                "DELETE FROM {t} WHERE account_id = ? AND lower(ltrim(channel, '#')) = ?".format(t=table),
                (target_account_id, channel),
            )
        await db.execute(
            "UPDATE {t} SET account_id = ? WHERE account_id = ? AND lower(ltrim(channel, '#')) = ?".format(t=table),
            (target_account_id, source_account_id, channel),
        )
        moved[table] = count

    await db.execute(
        "UPDATE channels SET account_id = ? WHERE id = ?", (target_account_id, channel_id),
    )
    await db.commit()
    return {"ok": True, "account_id": int(target_account_id), "channel_name": channel, "moved": moved}
