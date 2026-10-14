"""Тесты Feature 5: долговременная память."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _setup(tmp_db, account_ids=(1,)):
    from app import database, user_memory
    await database.init_db()
    # Создаём аккаунты, необходимые для FK
    db = await database.get_db()
    for aid in account_ids:
        await db.execute(
            "INSERT OR IGNORE INTO accounts (id, nickname, token) VALUES (?, ?, ?)",
            (aid, f"acc{aid}", "tok"),
        )
    await db.commit()
    return user_memory


async def test_increment_and_get(tmp_db):
    um = await _setup(tmp_db)
    assert await um.get_user_memory(1, "alice") is None
    await um.increment_msg_count(1, "alice")
    await um.increment_msg_count(1, "alice")
    rec = await um.get_user_memory(1, "alice")
    assert rec is not None
    assert rec["username"] == "alice"
    assert rec["msg_count"] == 2
    assert rec["facts"] == []


async def test_add_and_remove_fact(tmp_db):
    um = await _setup(tmp_db)
    assert await um.add_fact(1, "bob", "играет в Dota") is True
    # дубликат
    assert await um.add_fact(1, "bob", "играет в Dota") is False
    assert await um.add_fact(1, "bob", "из Москвы") is True
    rec = await um.get_user_memory(1, "bob")
    assert sorted(rec["facts"]) == ["играет в Dota", "из Москвы"]
    # remove
    assert await um.remove_fact(1, "bob", "играет в Dota") is True
    rec = await um.get_user_memory(1, "bob")
    assert rec["facts"] == ["из Москвы"]


async def test_isolated_per_account(tmp_db):
    um = await _setup(tmp_db, account_ids=(1, 2))
    await um.add_fact(1, "u", "fact1")
    await um.add_fact(2, "u", "fact2")
    r1 = await um.get_user_memory(1, "u")
    r2 = await um.get_user_memory(2, "u")
    assert r1["facts"] == ["fact1"]
    assert r2["facts"] == ["fact2"]


async def test_username_normalisation(tmp_db):
    um = await _setup(tmp_db)
    await um.add_fact(1, "Alice", "  has cat  ")
    rec = await um.get_user_memory(1, "ALICE")
    assert rec is not None
    assert rec["facts"] == ["has cat"]


async def test_list_user_memory(tmp_db):
    um = await _setup(tmp_db)
    await um.increment_msg_count(1, "low")
    for _ in range(5):
        await um.increment_msg_count(1, "high")
    rows = await um.list_user_memory(1, limit=10)
    assert len(rows) == 2
    # Сортировка по msg_count desc
    assert rows[0]["username"] == "high"
    assert rows[0]["msg_count"] == 5


async def test_history_retention_isolated_by_account_channel_and_user(tmp_db):
    um = await _setup(tmp_db, account_ids=(1, 2))
    await um.add_message_history(1, "channel-a", "alice", "a1", max_history=1)
    await um.add_message_history(1, "channel-b", "alice", "b1", max_history=1)
    await um.add_message_history(1, "channel-a", "bob", "other-user", max_history=1)
    await um.add_message_history(2, "channel-a", "alice", "other-account", max_history=1)
    await um.add_message_history(1, "channel-a", "alice", "a2", max_history=1)

    assert [item["message"] for item in await um.get_message_history(1, "channel-a", "alice")] == ["a2"]
    assert [item["message"] for item in await um.get_message_history(1, "channel-b", "alice")] == ["b1"]
    assert [item["message"] for item in await um.get_message_history(1, "channel-a", "bob")] == ["other-user"]
    assert [item["message"] for item in await um.get_message_history(2, "channel-a", "alice")] == ["other-account"]
