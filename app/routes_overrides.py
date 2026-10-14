"""overrides — вынесено из app/routes.py (P5-сплит, PLAN.md). Декорирует ОБЩИЙ
router из app.routes; импортируется ВНИЗУ routes.py (после создания router).
"""
from typing import Any

from fastapi import Request

from app.database import get_db
import json
from app.routes import router  # noqa: E402


# ===================== v12: PER-CHANNEL OVERRIDES =====================

# Поля, які можна перевизначати per-channel (застосовуються в chat_analyzer
# при рейдах та як базові overrides поведінки).
# PLAN §2.1: + активность (auto_chat/silent/cooldown), источники контекста и tts_mute.
_CHANNEL_OVERRIDE_FIELDS = (
    "humor_level", "sarcasm_level", "darkness_level", "adult_humor",
    "crudeness_level", "contact_level", "chat_affinity", "observation_only",
    "canadian_mode", "emotion_intensity",
    "auto_chat", "silent_mode", "cooldown",
    "context_source_chat", "context_source_stream", "context_source_streamer",
    "tts_mute",
)

# Булевы ключи overrides (сохраняются как true/false, не как 0..100)
_CHANNEL_OVERRIDE_BOOL_FIELDS = {
    "observation_only", "canadian_mode", "auto_chat", "silent_mode",
    "context_source_chat", "context_source_stream", "context_source_streamer",
    "tts_mute",
}


@router.get("/api/accounts/{account_id}/channel-overrides")
async def list_channel_overrides(account_id: int):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT id, channel, overrides_json, enabled, updated_at "
            "FROM channel_overrides WHERE account_id = ? ORDER BY channel",
            (account_id,),
        )
        rows = await cur.fetchall()
        overrides = []
        for r in rows:
            try:
                data = json.loads(r["overrides_json"] or "{}")
            except Exception:
                data = {}
            overrides.append({
                "id": r["id"],
                "channel": r["channel"],
                "enabled": bool(r["enabled"]),
                "updated_at": r["updated_at"],
                "overrides": data,
            })
        return {"ok": True, "overrides": overrides}
    finally:
        await db.close()


@router.put("/api/accounts/{account_id}/channel-overrides")
async def upsert_channel_override(account_id: int, request: Request):
    """Зберігає overrides для одного каналу.

    body: {"channel": "name", "enabled": true, "overrides": {...}}
    """
    body = await request.json()
    channel = (body.get("channel") or "").lower().strip().lstrip("#")
    if not channel:
        return {"error": "channel required"}
    enabled = 1 if body.get("enabled", True) else 0
    raw = body.get("overrides") or {}
    # Фільтруємо до дозволених полів: булеві — як є, числа — clamp 0..100 (cooldown 0..3600)
    clean: dict[str, Any] = {}
    for k in _CHANNEL_OVERRIDE_FIELDS:
        if k not in raw:
            continue
        v = raw[k]
        if k in _CHANNEL_OVERRIDE_BOOL_FIELDS:
            clean[k] = bool(v)
        elif isinstance(v, (int, float)):
            if k == "cooldown":
                clean[k] = max(0, min(3600, int(v)))
            else:
                clean[k] = max(0, min(100, int(v)))
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO channel_overrides (account_id, channel, overrides_json, enabled, updated_at) "
            "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(account_id, channel) DO UPDATE SET "
            "overrides_json=excluded.overrides_json, enabled=excluded.enabled, "
            "updated_at=CURRENT_TIMESTAMP",
            (account_id, channel, json.dumps(clean, ensure_ascii=False), enabled),
        )
        await db.commit()
        # PLAN §2.1: сброс кэша overrides, чтобы рантайм увидел изменения сразу
        try:
            from app.server import chat_analyzer
            chat_analyzer.invalidate_channel_overrides(account_id, channel)
        except Exception:
            pass
        return {"ok": True, "channel": channel, "overrides": clean}
    finally:
        await db.close()


@router.delete("/api/accounts/{account_id}/channel-overrides/{channel}")
async def delete_channel_override(account_id: int, channel: str):
    db = await get_db()
    try:
        await db.execute(
            "DELETE FROM channel_overrides WHERE account_id = ? AND channel = ?",
            (account_id, channel.lower().strip().lstrip("#")),
        )
        await db.commit()
        # PLAN §2.1: сброс кэша overrides
        try:
            from app.server import chat_analyzer
            chat_analyzer.invalidate_channel_overrides(account_id, channel)
        except Exception:
            pass
        return {"ok": True}
    finally:
        await db.close()


@router.get("/api/accounts/{account_id}/chat-users")
async def list_chat_users(account_id: int, channel: str = "", q: str = "", role: str = ""):
    db = await get_db()
    try:
        conditions = ["account_id = ?"]
        params: list = [account_id]
        if channel:
            conditions.append("channel = ?")
            params.append(channel)
        if q:
            conditions.append("username LIKE ?")
            params.append(f"%{q}%")
        if role:
            conditions.append("role = ?")
            params.append(role)
        where = f"WHERE {' AND '.join(conditions)}"
        cur = await db.execute(
            f"SELECT * FROM chat_users {where} ORDER BY message_count DESC LIMIT 200",
            params,
        )
        rows = await cur.fetchall()
        return {"ok": True, "users": [dict(r) for r in rows]}
    finally:
        await db.close()


@router.put("/api/accounts/{account_id}/chat-users/{username}")
async def toggle_chat_user(account_id: int, username: str, request: Request):
    body = await request.json()
    enabled = body.get("enabled", 1)
    db = await get_db()
    try:
        await db.execute(
            "UPDATE chat_users SET enabled = ? WHERE account_id = ? AND username = ?",
            (enabled, account_id, username),
        )
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()
