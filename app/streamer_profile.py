"""Streamer profile — автозаповнення факти про стримера з чату + Helix.

Функції:
- ``auto_update_profile`` — раз на N хвилин збирає факти з чату + Helix → LLM extraction → upsert
- ``upsert_streamer_profile`` — запис/оновлення профілю
- ``get_streamer_profile`` — отримання профілю
- ``get_streamer_face`` / ``upsert_streamer_face`` / ``delete_streamer_face`` — CRUD фото обличчя
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.database import get_db

logger = logging.getLogger(__name__)

# ── Streamer Profile ──────────────────────────────────────────────

async def get_streamer_profile(account_id: int, channel: str = "") -> dict[str, Any] | None:
    """Return an exact channel profile (empty channel is legacy migration data only)."""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM streamer_profile WHERE account_id = ? AND channel = ?",
            (account_id, (channel or "").lower()),
        )
        row = await cur.fetchone()
        if not row:
            return None
        return dict(row)
    finally:
        await db.close()


async def get_streamer_profile_resolved(account_id: int, channel: str = "") -> dict[str, Any] | None:
    """§5 PLAN_FEEDBACK_2908: профиль для генерации с fallback-цепочкой.

    W4: only exact per-channel profiles participate in runtime resolution.
    Legacy global rows are copied to a compatible channel by the DB migration.
    """
    ch = (channel or "").lower()
    if not ch:
        return None
    for acc, ch_key in ((account_id, ch), (0, ch)):
        profile = await get_streamer_profile(acc, ch_key)
        if profile:
            profile["scope"] = (
                f"bot#{acc}/{ch_key or 'global'}" if acc else (f"global/#{ch_key or 'all'}")
            )
            return profile
    return None


async def upsert_streamer_profile(account_id: int, facts: dict[str, Any], channel: str = "") -> None:
    """Оновлює профіль стримера. facts може містити будь-які з полів таблиці.

    §5: channel='' — глобальний профіль; '#name' — профіль конкретного каналу."""
    ch = (channel or "").lower()
    db = await get_db()
    try:
        existing = await get_streamer_profile(account_id, ch)
        if existing:
            sets = []
            vals: list[Any] = []
            for key in (
                "age", "gender", "location", "occupation", "bio",
                "streaming_style", "auto_updated",
            ):
                if key in facts:
                    sets.append(f"{key} = ?")
                    vals.append(facts[key])
            for key in ("interests", "favorite_games", "likes", "dislikes"):
                if key in facts:
                    sets.append(f"{key} = ?")
                    val = facts[key]
                    if isinstance(val, list):
                        val = json.dumps(val, ensure_ascii=False)
                    vals.append(val)
            if sets:
                sets.append("updated_at = CURRENT_TIMESTAMP")
                vals.extend([account_id, ch])
                await db.execute(
                    f"UPDATE streamer_profile SET {', '.join(sets)} "
                    "WHERE account_id = ? AND channel = ?",
                    vals,
                )
        else:
            interests = facts.get("interests", [])
            if isinstance(interests, list):
                interests = json.dumps(interests, ensure_ascii=False)
            games = facts.get("favorite_games", [])
            if isinstance(games, list):
                games = json.dumps(games, ensure_ascii=False)
            likes = facts.get("likes", [])
            if isinstance(likes, list):
                likes = json.dumps(likes, ensure_ascii=False)
            dislikes = facts.get("dislikes", [])
            if isinstance(dislikes, list):
                dislikes = json.dumps(dislikes, ensure_ascii=False)
            await db.execute(
                """INSERT INTO streamer_profile
                   (account_id, channel, age, gender, location, occupation, bio,
                    interests, favorite_games, streaming_style, likes, dislikes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    account_id,
                    ch,
                    facts.get("age", 0),
                    facts.get("gender", ""),
                    facts.get("location", ""),
                    facts.get("occupation", ""),
                    facts.get("bio", ""),
                    interests,
                    games,
                    facts.get("streaming_style", ""),
                    likes,
                    dislikes,
                ),
            )
        await db.commit()
    finally:
        await db.close()


async def auto_update_profile(
    account_id: int, channel: str, chat_sample: list[dict[str, str]]
) -> dict[str, Any]:
    """Раз на N хвилин збирає факти з чату + Helix channel_info -> LLM extraction -> upsert.

    Повертає згенерований профіль (dict).
    """
    try:
        from app.twitch_helix import get_channel_info  # noqa: F811
        from app.ai_service import AIService

        info = await get_channel_info(channel)
    except Exception:
        info = {}

    # Формуємо текст для LLM
    chat_text = "\n".join(
        f"{m.get('author', '?')}: {m.get('text', '')}" for m in chat_sample[:20]
    )
    prompt = (
        f"Виділи факти про стримера з чату та Helix:\n"
        f"Helix info: {json.dumps(info, ensure_ascii=False, default=str)}\n"
        f"Зразки чату:\n{chat_text}\n\n"
        f"Поверни JSON з полями: age (int), gender (str), location (str), "
        f"occupation (str), bio (str), interests (list[str]), "
        f"favorite_games (list[str]), streaming_style (str), "
        f"likes (list[str]), dislikes (list[str]). "
        f"Якщо факт невідомий — порожнє значення."
    )

    try:
        ai = AIService()
        facts = await ai.generate_json(prompt, account_id=account_id)
        if isinstance(facts, dict):
            await upsert_streamer_profile(account_id, facts, channel=channel)
            return facts
    except Exception as exc:
        logger.warning("auto_update_profile LLM failed for account %d: %s", account_id, exc)

    return {}


# ── Streamer Face (фото обличчя для Vision) ───────────────────────

async def get_streamer_face(account_id: int, include_image: bool = False, channel: str = "") -> dict[str, Any] | None:
    ch = (channel or "").lower()
    db = await get_db()
    try:
        if include_image:
            cur = await db.execute(
                "SELECT account_id, face_image_base64, mime_type, updated_at, "
                "CASE WHEN face_image_base64 != '' THEN 1 ELSE 0 END as has_face "
                "FROM streamer_face WHERE account_id = ? AND channel = ?",
                (account_id, ch),
            )
        else:
            cur = await db.execute(
                "SELECT account_id, mime_type, updated_at, "
                "CASE WHEN face_image_base64 != '' THEN 1 ELSE 0 END as has_face "
                "FROM streamer_face WHERE account_id = ? AND channel = ?",
                (account_id, ch),
            )
        row = await cur.fetchone()
        if not row:
            return None
        return dict(row)
    finally:
        await db.close()


async def get_streamer_face_resolved(account_id: int, channel: str = "", include_image: bool = False) -> dict[str, Any] | None:
    """§5: фото с fallback-цепочкой (bot+channel → bot global → panel channel → panel global)."""
    ch = (channel or "").lower()
    for acc, ch_key in ((account_id, ch), (account_id, ""), (0, ch), (0, "")):
        face = await get_streamer_face(acc, include_image=include_image, channel=ch_key)
        if face:
            return face
    return None


async def upsert_streamer_face(account_id: int, face_image_base64: str, mime_type: str = "image/jpeg", channel: str = "") -> None:
    ch = (channel or "").lower()
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO streamer_face (account_id, channel, face_image_base64, mime_type, updated_at)
               VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(account_id, channel) DO UPDATE SET
                 face_image_base64 = excluded.face_image_base64,
                 mime_type = excluded.mime_type,
                 updated_at = CURRENT_TIMESTAMP""",
            (account_id, ch, face_image_base64, mime_type),
        )
        await db.commit()
    finally:
        await db.close()


async def delete_streamer_face(account_id: int, channel: str = "") -> None:
    db = await get_db()
    try:
        await db.execute(
            "DELETE FROM streamer_face WHERE account_id = ? AND channel = ?",
            (account_id, (channel or "").lower()),
        )
        await db.commit()
    finally:
        await db.close()


async def delete_streamer_profile(account_id: int, channel: str = "") -> None:
    """§5: удалить профиль (панельный глобальный / per-channel)."""
    db = await get_db()
    try:
        await db.execute(
            "DELETE FROM streamer_profile WHERE account_id = ? AND channel = ?",
            (account_id, (channel or "").lower()),
        )
        await db.commit()
    finally:
        await db.close()


__all__ = [
    "get_streamer_profile",
    "get_streamer_profile_resolved",
    "upsert_streamer_profile",
    "delete_streamer_profile",
    "auto_update_profile",
    "get_streamer_face",
    "get_streamer_face_resolved",
    "upsert_streamer_face",
    "delete_streamer_face",
]
