"""PLAN_FEEDBACK_2908 §5: профиль стримера — глобально + выбор канала.

- миграция старой БД (PK account_id → PK account_id+channel, строки → channel='');
- per-channel профиль не перетирает глобальный;
- fallback-цепочка resolved: bot+channel → bot global → panel channel → panel global;
- kb с channel; фото per-channel.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_migration_old_db_profile_becomes_global(tmp_db):
    """Старая БД (PK account_id, без channel) → init_db: строки становятся
    глобальными (channel=''), данные сохраняются."""
    import aiosqlite
    from app.database import init_db

    await init_db()  # создать всё
    # деградировать до старой формы
    async with aiosqlite.connect(tmp_db) as db:
        await db.execute("ALTER TABLE streamer_profile RENAME TO sp_old")
        await db.execute(
            "CREATE TABLE streamer_profile ("
            "account_id INTEGER PRIMARY KEY, age INTEGER DEFAULT 0, "
            "gender TEXT DEFAULT '', location TEXT DEFAULT '', occupation TEXT DEFAULT '', "
            "bio TEXT DEFAULT '', interests TEXT DEFAULT '[]', "
            "favorite_games TEXT DEFAULT '[]', streaming_style TEXT DEFAULT '', "
            "likes TEXT DEFAULT '[]', dislikes TEXT DEFAULT '[]', "
            "auto_updated INTEGER DEFAULT 1, "
            "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
            "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        await db.execute(
            "INSERT INTO streamer_profile (account_id, bio) VALUES (5, 'старый профиль')"
        )
        await db.execute("DROP TABLE sp_old")
        # face
        await db.execute("ALTER TABLE streamer_face RENAME TO sf_old")
        await db.execute(
            "CREATE TABLE streamer_face ("
            "account_id INTEGER PRIMARY KEY, face_image_base64 TEXT NOT NULL DEFAULT '', "
            "mime_type TEXT NOT NULL DEFAULT 'image/jpeg', "
            "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        await db.execute(
            "INSERT INTO streamer_face (account_id, mime_type) VALUES (5, 'image/png')"
        )
        await db.execute("DROP TABLE sf_old")
        await db.commit()

    await init_db()  # повторный старт панели — миграция

    from app.database import get_db
    db = await get_db()
    try:
        cur = await db.execute("SELECT account_id, channel, bio FROM streamer_profile")
        rows = [dict(r) for r in await cur.fetchall()]
        assert len(rows) == 1
        assert rows[0]["account_id"] == 5
        assert rows[0]["channel"] == ""
        assert rows[0]["bio"] == "старый профиль"

        cur = await db.execute("SELECT account_id, channel, mime_type FROM streamer_face")
        rows = [dict(r) for r in await cur.fetchall()]
        assert rows[0]["channel"] == "" and rows[0]["mime_type"] == "image/png"
    finally:
        await db.close()


async def test_per_channel_profile_does_not_overwrite_global(tmp_db):
    from app.database import init_db
    from app.streamer_profile import (
        get_streamer_profile, get_streamer_profile_resolved,
        upsert_streamer_profile,
    )

    await init_db()
    await upsert_streamer_profile(0, {"bio": "глобальный"}, channel="")
    await upsert_streamer_profile(0, {"bio": "для канала майнкрафт"}, channel="#minecraft")

    glob = await get_streamer_profile(0, "")
    chan = await get_streamer_profile(0, "#minecraft")
    assert glob["bio"] == "глобальный"
    assert chan["bio"] == "для канала майнкрафт"

    # resolved: bot не имеет своих → панельный per-channel
    res = await get_streamer_profile_resolved(7, "#minecraft")
    assert res["bio"] == "для канала майнкрафт"
    # без per-channel глобальный legacy больше не раскрывается
    res = await get_streamer_profile_resolved(7, "#other")
    assert res is None
    # у бота свой per-channel → он приоритетнее панельного
    await upsert_streamer_profile(7, {"bio": "бот-специфичный"}, channel="#minecraft")
    res = await get_streamer_profile_resolved(7, "#minecraft")
    assert res["bio"] == "бот-специфичный"
    # legacy global row remains stored for migration/rollback but is not resolved
    await upsert_streamer_profile(8, {"bio": "легаси глобал"}, channel="")
    res = await get_streamer_profile_resolved(8, "# unnoticed")
    assert res is None


async def test_face_per_channel_and_kb_channel(tmp_db):
    from app.database import init_db, get_db
    from app.streamer_profile import (
        get_streamer_face_resolved, upsert_streamer_face, upsert_streamer_profile,
    )
    from app.ai_quality_db import add_kb, list_kb

    await init_db()
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO accounts (id, nickname, token) VALUES (3, 'bot3', 'tok')"
        )
        await db.commit()
    finally:
        await db.close()

    await upsert_streamer_profile(0, {"bio": "panel global"})
    await upsert_streamer_face(0, "aGVsbG8=", "image/jpeg", channel="#wow")
    await upsert_streamer_face(0, "Z2xvYmFs", "image/jpeg", channel="")

    # per-channel не перетирает глобальное
    face = await get_streamer_face_resolved(3, "#wow", include_image=True)
    assert face["face_image_base64"] == "aGVsbG8="
    face = await get_streamer_face_resolved(3, "", include_image=True)
    assert face["face_image_base64"] == "Z2xvYmFs"
    # resolved: у бота 3 нет фото → панельное per-channel
    assert face["account_id"] == 0

    # kb: глобальное и per-channel сосуществуют
    await add_kb(3, "Игра", "Любит Minecraft", channel="")
    await add_kb(3, "Игра", "На #wow играет в варкрафт", channel="#wow")
    all_items = await list_kb(3)
    wow_items = await list_kb(3, channel="#wow")
    assert len(all_items) == 2
    assert len(wow_items) == 1
    assert wow_items[0]["content"] == "На #wow играет в варкрафт"
