"""BC-4: полный CRUD каналов — зависимости, переименование и перенос между ботами."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _client():
    """Клиент на routes.router с инициализированной схемой (tmp_db даёт только файл)."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from app.database import init_db
    from app.routes import router

    await init_db()
    app = FastAPI()
    app.include_router(router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _db():
    from app.database import init_db, get_db
    await init_db()
    return await get_db()


async def _ensure_account(account_id: int = 1, nickname: str = "bot_one") -> None:
    """channels.account_id — FK на accounts, поэтому аккаунт создаём явно."""
    db = await _db()
    try:
        cursor = await db.execute("SELECT id FROM accounts WHERE id = ?", (account_id,))
        if not await cursor.fetchone():
            await db.execute(
                "INSERT INTO accounts (id, nickname, token, enabled) VALUES (?, ?, 'tok', 1)",
                (account_id, nickname),
            )
            await db.commit()
    finally:
        await db.close()


async def _channel_id(c, account_id: int, channel: str) -> int:
    rows = (await c.get(f"/api/accounts/{account_id}/channels")).json()
    return next(row["id"] for row in rows if row["channel_name"] == channel)


async def test_dependencies_reported_before_delete(tmp_db, disable_auth):
    """Канал с данными не удаляется без force и честно перечисляет зависимости."""
    await _ensure_account()
    async with await _client() as c:
        assert (await c.post("/api/accounts/1/channels", json={"channel_name": "depchan"})).json()["ok"] is True
        channel_id = await _channel_id(c, 1, "depchan")

        db = await _db()
        try:
            await db.execute(
                "INSERT INTO chat_log (account_id, channel, author, message) VALUES (1, ?, 'u', 'm')",
                ("depchan",),
            )
            await db.commit()
        finally:
            await db.close()

        deps = (await c.get(f"/api/channels/{channel_id}/dependencies")).json()
        assert deps["ok"] is True
        assert deps["counts"].get("chat_log") == 1
        assert deps["total"] >= 1

        blocked = (await c.delete(f"/api/channels/{channel_id}")).json()
        assert blocked["ok"] is False
        assert blocked["code"] == "channel_has_dependencies"
        assert blocked["counts"].get("chat_log") == 1

        forced = (await c.delete(f"/api/channels/{channel_id}?force=true")).json()
        assert forced["ok"] is True

        db = await _db()
        try:
            cursor = await db.execute("SELECT COUNT(*) FROM chat_log WHERE channel = 'depchan'")
            assert (await cursor.fetchone())[0] == 0
            cursor = await db.execute("SELECT COUNT(*) FROM channels WHERE id = ?", (channel_id,))
            assert (await cursor.fetchone())[0] == 0
        finally:
            await db.close()


async def test_delete_empty_channel_without_force(tmp_db, disable_auth):
    """Пустой канал (нет зависимостей) удаляется без force."""
    await _ensure_account()
    async with await _client() as c:
        await c.post("/api/accounts/1/channels", json={"channel_name": "emptychan"})
        channel_id = await _channel_id(c, 1, "emptychan")
        assert (await c.delete(f"/api/channels/{channel_id}")).json()["ok"] is True
        rows = (await c.get("/api/accounts/1/channels")).json()
        assert all(row["channel_name"] != "emptychan" for row in rows)


async def test_rename_moves_channel_scoped_rows(tmp_db, disable_auth):
    """Переименование переносит данные канала, а не оставляет их под старым именем."""
    await _ensure_account()
    async with await _client() as c:
        await c.post("/api/accounts/1/channels", json={"channel_name": "oldname"})
        channel_id = await _channel_id(c, 1, "oldname")

        db = await _db()
        try:
            await db.execute(
                "INSERT INTO chat_log (account_id, channel, author, message) VALUES (1, 'oldname', 'u', 'm')")
            await db.commit()
        finally:
            await db.close()

        renamed = (await c.patch(f"/api/channels/{channel_id}", json={"channel_name": "newname"})).json()
        assert renamed["ok"] is True
        assert renamed["channel_name"] == "newname"
        assert renamed["moved"].get("chat_log") == 1

        rows = (await c.get("/api/accounts/1/channels")).json()
        assert [row["channel_name"] for row in rows] == ["newname"]

        db = await _db()
        try:
            cursor = await db.execute("SELECT COUNT(*) FROM chat_log WHERE channel = 'newname'")
            assert (await cursor.fetchone())[0] == 1
            cursor = await db.execute("SELECT COUNT(*) FROM chat_log WHERE channel = 'oldname'")
            assert (await cursor.fetchone())[0] == 0
        finally:
            await db.close()


async def test_rename_rejects_existing_target(tmp_db, disable_auth):
    await _ensure_account()
    async with await _client() as c:
        await c.post("/api/accounts/1/channels", json={"channel_name": "first"})
        await c.post("/api/accounts/1/channels", json={"channel_name": "second"})
        first_id = await _channel_id(c, 1, "first")
        result = (await c.patch(f"/api/channels/{first_id}", json={"channel_name": "second"})).json()
        assert result["ok"] is False
        assert result["code"] == "channel_exists"


async def test_move_channel_to_another_bot(tmp_db, disable_auth):
    """BC-1: «смена канала у бота» — привязка переезжает к другому аккаунту с данными."""
    await _ensure_account()
    async with await _client() as c:
        await c.post("/api/accounts/1/channels", json={"channel_name": "movechan"})
        channel_id = await _channel_id(c, 1, "movechan")

        db = await _db()
        try:
            cursor = await db.execute("SELECT id FROM accounts")
            accounts = [row[0] for row in await cursor.fetchall()]
            if len(accounts) < 2:
                await db.execute(
                    "INSERT INTO accounts (nickname, token, enabled) VALUES ('second_bot', 'tok', 1)")
                await db.commit()
                cursor = await db.execute("SELECT id FROM accounts")
                accounts = [row[0] for row in await cursor.fetchall()]
            target = next(acc for acc in accounts if acc != 1)
            await db.execute(
                "INSERT INTO chat_log (account_id, channel, author, message) VALUES (1, 'movechan', 'u', 'm')")
            await db.commit()
        finally:
            await db.close()

        moved = (await c.patch(f"/api/channels/{channel_id}", json={"account_id": int(target)})).json()
        assert moved["ok"] is True, moved
        assert moved["account_id"] == int(target)
        assert moved["moved"].get("chat_log") == 1

        db = await _db()
        try:
            cursor = await db.execute("SELECT account_id FROM channels WHERE id = ?", (channel_id,))
            assert int((await cursor.fetchone())[0]) == int(target)
            cursor = await db.execute("SELECT account_id FROM chat_log WHERE channel = 'movechan'")
            assert int((await cursor.fetchone())[0]) == int(target)
        finally:
            await db.close()
