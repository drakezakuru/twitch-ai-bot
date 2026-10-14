"""P1 §9a: профиль стримера + фото — API-флоу для UI вкладки «О стримере».

README ранее утверждал, что streamer-profile покрыт тестами — проверка показала,
что тестов не было. Здесь закрывается весь цикл, который делает новая вкладка:
1. Пустой профиль → UI показывает empty state.
2. PUT профиля со списками (interests/games/likes/dislikes) → GET возвращает.
3. Повторный PUT обновляет поля (не создаёт дубликат).
4. Фото: multipart upload → has_face + include=1 → base64 → DELETE.
5. Валидация размера (2 МБ).
"""
from __future__ import annotations

import base64

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


async def _client():
    from fastapi import FastAPI
    from app.routes import router
    app = FastAPI()
    app.include_router(router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed_account(db, account_id: int = 1) -> None:
    await db.execute(
        "INSERT INTO accounts (id, nickname, token, enabled) VALUES (?, 'testbot', 'oauth:x', 1) "
        "ON CONFLICT(id) DO NOTHING",
        (account_id,),
    )
    await db.commit()


async def test_profile_empty_state(tmp_db, disable_auth):
    from app import database
    await database.init_db()
    await _seed_account(await database.get_db())
    (await database.get_db()).close()

    async with await _client() as c:
        r = await c.get("/api/accounts/1/streamer-profile?channel=%23test")
        body = r.json()
        assert r.status_code == 200
        assert body["ok"] is True
        assert body["profile"] is None


async def test_profile_save_and_load_with_lists(tmp_db, disable_auth):
    from app import database
    await database.init_db()
    db = await database.get_db()
    await _seed_account(db)
    await db.close()

    payload = {
        "age": 27,
        "gender": "female",
        "location": "Kyiv",
        "occupation": "full-time streamer",
        "bio": " VTuber и кофейный энтузиаст ",
        "streaming_style": "entertaining",
        "auto_updated": True,
        "interests": ["anime", "synthwave"],
        "favorite_games": ["Dota 2"],
        "likes": ["speedrun"],
        "dislikes": ["spoilers"],
    }
    async with await _client() as c:
        r = await c.put("/api/accounts/1/streamer-profile?channel=%23test", json=payload)
        assert r.json()["ok"] is True
        loaded = (await c.get("/api/accounts/1/streamer-profile?channel=%23test")).json()["profile"]

    assert loaded["age"] == 27
    assert loaded["gender"] == "female"
    assert loaded["streaming_style"] == "entertaining"
    assert loaded["auto_updated"] in (1, True)
    for key in ("interests", "favorite_games", "likes", "dislikes"):
        assert isinstance(loaded[key], (list, str)), key
        if isinstance(loaded[key], str):
            import json as _json
            loaded[key] = _json.loads(loaded[key])
    assert loaded["interests"] == ["anime", "synthwave"]
    assert loaded["dislikes"] == ["spoilers"]


async def test_profile_upsert_updates_without_duplicates(tmp_db, disable_auth):
    from app import database
    await database.init_db()
    db = await database.get_db()
    await _seed_account(db)
    await db.close()

    async with await _client() as c:
        await c.put("/api/accounts/1/streamer-profile?channel=%23test", json={"age": 30, "bio": "first"})
        await c.put("/api/accounts/1/streamer-profile?channel=%23test", json={"age": 31, "bio": "second"})
        loaded = (await c.get("/api/accounts/1/streamer-profile?channel=%23test")).json()["profile"]

    assert loaded["age"] == 31
    assert loaded["bio"] == "second"

    db = await database.get_db()
    cur = await db.execute("SELECT COUNT(*) AS n FROM streamer_profile WHERE account_id = 1")
    row = await cur.fetchone()
    await db.close()
    assert row["n"] == 1


async def test_face_upload_preview_delete(tmp_db, disable_auth):
    from app import database
    await database.init_db()
    db = await database.get_db()
    await _seed_account(db)
    await db.close()

    png = base64.b64encode(b"\x89PNG fake image bytes").decode()
    async with await _client() as c:
        r = await c.post(
            "/api/accounts/1/streamer-face",
            files={"file": ("face.png", base64.b64decode(png), "image/png")},
        )
        assert r.json()["ok"] is True

        listed = (await c.get("/api/accounts/1/streamer-face")).json()
        # SQLite отдаёт 1/0, JS-проверка truthiness — принимаем оба варианта
        assert listed["has_face"] in (1, True)
        assert listed["mime_type"] == "image/png"

        full = (await c.get("/api/accounts/1/streamer-face?include=1")).json()
        assert full["has_face"] in (1, True)
        assert full["face_image_base64"]

        deleted = await c.delete("/api/accounts/1/streamer-face")
        assert deleted.json()["ok"] is True
        after = (await c.get("/api/accounts/1/streamer-face")).json()
        assert after["has_face"] is False


async def test_face_upload_rejects_oversize(tmp_db, disable_auth):
    from app import database
    await database.init_db()
    db = await database.get_db()
    await _seed_account(db)
    await db.close()

    big = b"x" * (2 * 1024 * 1024 + 100)
    async with await _client() as c:
        r = await c.post(
            "/api/accounts/1/streamer-face",
            files={"file": ("big.png", big, "image/png")},
        )
        body = r.json()
        assert body.get("ok") is not True
        assert "large" in body.get("error", "").lower() or "больш" in body.get("error", "")
