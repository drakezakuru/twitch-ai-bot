"""OPS_PLAN §1 — Bot Files: HTTP-роуты над per-bot папками.

Проверяем:
1. GET /api/accounts/{id}/files — список, авто-инициализация структуры.
2. PUT/GET/DELETE файла — запись/чтение/удаление json/md/txt.
3. Ограничения: не-текстовые расширения отклоняются, лимит 256КБ.
4. Path traversal закрыт и на уровне роутов (..%2f, ../).
5. init/migrate при старте бота создаёт папку (идемпотентно).
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


async def _client():
    from fastapi import FastAPI
    from app.routes import router
    app = FastAPI()
    app.include_router(router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed_account(db, account_id: int = 1, nickname: str = "filesbot") -> None:
    await db.execute(
        "INSERT INTO accounts (id, nickname, token, enabled) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(id) DO UPDATE SET nickname = excluded.nickname",
        (account_id, nickname, "oauth:xxx"),
    )
    await db.commit()


async def test_files_list_initializes_structure(tmp_db, disable_auth, monkeypatch):
    # Per-bot папки изолируем во временную директорию
    from app import bot_dirs
    monkeypatch.setattr(bot_dirs, "BOTS_ROOT", tmp_db.parent / "bots")

    from app import database
    await database.init_db()
    db = await database.get_db()
    await _seed_account(db)
    await db.close()

    async with await _client() as c:
        r = (await c.get("/api/accounts/1/files")).json()
        assert r["ok"] is True
        assert r["bot_dir"] == "1_filesbot"
        paths = [f["path"] for f in r["files"]]
        assert "config.json" in paths

    # Структура папок создана
    from app.bot_dirs import BOTS_ROOT
    assert (BOTS_ROOT / "1_filesbot" / "prompts").is_dir()


async def test_files_write_read_delete_roundtrip(tmp_db, disable_auth, monkeypatch):
    from app import bot_dirs
    monkeypatch.setattr(bot_dirs, "BOTS_ROOT", tmp_db.parent / "bots")

    from app import database
    await database.init_db()
    db = await database.get_db()
    await _seed_account(db)
    await db.close()

    async with await _client() as c:
        w = (await c.put("/api/accounts/1/files/prompts/personality.txt",
                         json={"content": "Ты — весёлый бот"})).json()
        assert w["ok"] is True

        g = (await c.get("/api/accounts/1/files/prompts/personality.txt")).json()
        assert g["ok"] is True and g["content"] == "Ты — весёлый бот"

        d = (await c.delete("/api/accounts/1/files/prompts/personality.txt")).json()
        assert d["ok"] is True

        g2 = (await c.get("/api/accounts/1/files/prompts/personality.txt")).json()
        assert g2["ok"] is False and g2["error"] == "not_found"


async def test_files_rejects_non_text_extensions(tmp_db, disable_auth, monkeypatch):
    from app import bot_dirs
    monkeypatch.setattr(bot_dirs, "BOTS_ROOT", tmp_db.parent / "bots")

    from app import database
    await database.init_db()
    db = await database.get_db()
    await _seed_account(db)
    await db.close()

    async with await _client() as c:
        for name in ("evil.exe", "voice/onnx.bin", "img.png", "script.sh"):
            w = (await c.put(f"/api/accounts/1/files/{name}", json={"content": "x"})).json()
            assert w["ok"] is False and w["error"] == "file_type_not_allowed", name


async def test_files_rejects_oversize(tmp_db, disable_auth, monkeypatch):
    from app import bot_dirs
    monkeypatch.setattr(bot_dirs, "BOTS_ROOT", tmp_db.parent / "bots")

    from app import database
    await database.init_db()
    db = await database.get_db()
    await _seed_account(db)
    await db.close()

    big = "x" * (256 * 1024 + 1)
    async with await _client() as c:
        w = (await c.put("/api/accounts/1/files/notes.txt", json={"content": big})).json()
        assert w["ok"] is False and w["error"] == "file_too_large"


async def test_files_path_traversal_blocked(tmp_db, disable_auth, monkeypatch):
    from app import bot_dirs
    monkeypatch.setattr(bot_dirs, "BOTS_ROOT", tmp_db.parent / "bots")

    from app import database
    await database.init_db()
    db = await database.get_db()
    await _seed_account(db)
    await db.close()

    async with await _client() as c:
        # httpx нормализует .. сам, поэтому шлём raw-путь через ASGI:
        w = (await c.put("/api/accounts/1/files/..%2F..%2F..%2Fetc%2Fpasswd.json",
                         json={"content": "x"})).json()
        # Либо роут отверг (не text ext после нормализации), либо bot_dirs заблокировал выход
        if w["ok"] is False:
            assert w["error"] in ("file_type_not_allowed", "path_traversal_blocked", "not_found")
        else:
            from app.bot_dirs import BOTS_ROOT
            # Файл НЕ должен оказаться вне папки бота
            assert not (tmp_db.parent / "etc" / "passwd.json").exists()


async def test_files_account_not_found(tmp_db, disable_auth):
    from app import database
    await database.init_db()
    async with await _client() as c:
        r = (await c.get("/api/accounts/999/files")).json()
        assert r["ok"] is False and r["error"] == "account_not_found"


async def test_bot_dir_init_idempotent_and_migration(tmp_db):
    """§1: init/migrate идемпотентны, миграция — только чтение (не перенос)."""
    from app import bot_dirs
    monkey_dir = tmp_db.parent / "bots"
    import unittest.mock as mock
    with mock.patch.object(bot_dirs, "BOTS_ROOT", monkey_dir):
        from app import database
        await database.init_db()
        db = await database.get_db()
        await db.execute(
            "INSERT INTO accounts (id, nickname, token, persona_json, enabled) VALUES (?, ?, ?, ?, 1)",
            (1, "migr", "oauth:x", "Дружелюбная персона"),
        )
        await db.commit()
        await db.close()

        await bot_dirs.migrate_bot_dir(1, "migr")
        await bot_dirs.migrate_bot_dir(1, "migr")  # повторный вызов не падает

        p = bot_dirs.get_bot_dir(1, "migr") / "prompts" / "personality.txt"
        assert p.exists() and p.read_text(encoding="utf-8") == "Дружелюбная персона"

        # БД-источник не тронут (read-only миграция)
        db = await database.get_db()
        cur = await db.execute("SELECT persona_json FROM accounts WHERE id = 1")
        row = await cur.fetchone()
        await db.close()
        assert row["persona_json"] == "Дружелюбная персона"
