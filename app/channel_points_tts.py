"""P4 PLAN.md: TTS за баллы канала (channel points redemption → озвучка в OBS).

Зритель тратит channel points на redemption (например «Озвучить сообщение»),
текст redemption озвучивается через существующий TTSEngine (tts_bot_config).

Поток: EventSub `channel.channel_points_custom_reward_redemption.add` →
server.py:on_eventsub_event → handle_redemption():
    enabled? → reward name в списке? → текст не пуст? → длина ≤ max_len?
    → не в blacklist? → cooldown пройден? → часовой лимит? → speak.

Конфиг: таблица channel_points_tts_config (per-account). Панель:
GET/PUT /api/channel-points-tts/{account_id}, POST .../test.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, Request

from app.security import auth_dependency

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/channel-points-tts", tags=["channel-points-tts"],
                   dependencies=[Depends(auth_dependency)])

DEFAULTS = {
    "enabled": 0,
    "reward_names": "",      # запятая-разделённые названия reward; пусто = любой reward
    "max_len": 120,          # символов (обрезка)
    "cooldown_sec": 5,       # на юзера
    "max_per_hour": 10,      # на юзера
    "blacklist": "",         # запятая-разделённые слова (подстрока, без регистра)
    "announce_user": 1,      # «Говорит Nick: …»
    "channel": "",           # W8: free Twitch channel, independent of bot selector
    "voice": "",             # W8: explicit reward voice override
    "voice_provider": "",    # optional catalog provider; blank preserves legacy voice IDs
}

# runtime-состояние: (account_id, user_login) → [last_ts, hour_window_ts_list]
_state: dict[tuple[int, str], dict[str, Any]] = {}


async def ensure_schema(db) -> None:
    await db.execute("""
        CREATE TABLE IF NOT EXISTS channel_points_tts_config (
            account_id INTEGER PRIMARY KEY,
            enabled INTEGER DEFAULT 0,
            reward_names TEXT DEFAULT '',
            max_len INTEGER DEFAULT 120,
            cooldown_sec INTEGER DEFAULT 5,
            max_per_hour INTEGER DEFAULT 10,
            blacklist TEXT DEFAULT '',
            announce_user INTEGER DEFAULT 1,
            channel TEXT DEFAULT '',
            voice TEXT DEFAULT '',
            voice_provider TEXT DEFAULT '',
            FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
        )""")
    # Existing reward rows predate the provider-aware catalog. Keep their raw
    # voice IDs valid by making this strictly additive.
    from app.database import _add_column_if_missing
    await _add_column_if_missing(
        db, "channel_points_tts_config", "voice_provider", "TEXT DEFAULT ''"
    )


async def _load_config(account_id: int) -> dict:
    from app.database import get_db
    cfg = dict(DEFAULTS)
    db = await get_db()
    try:
        await ensure_schema(db)
        cur = await db.execute(
            "SELECT * FROM channel_points_tts_config WHERE account_id = ?", (account_id,))
        row = await cur.fetchone()
    finally:
        await db.close()
    if row:
        for k in DEFAULTS:
            v = row[k]
            cfg[k] = v if v is not None else DEFAULTS[k]
    return cfg


async def get_config(account_id: int) -> dict:
    return await _load_config(account_id)


async def save_config(account_id: int, data: dict) -> dict:
    from app.database import get_db
    merged = dict(DEFAULTS)
    for k in DEFAULTS:
        if k in data and data[k] is not None:
            merged[k] = data[k]
    merged["enabled"] = 1 if merged["enabled"] in (1, True, "1", "true") else 0
    merged["announce_user"] = 1 if merged["announce_user"] in (1, True, "1", "true") else 0
    merged["max_len"] = max(10, min(500, int(merged["max_len"] or 120)))
    merged["cooldown_sec"] = max(0, min(600, int(merged["cooldown_sec"] or 0)))
    merged["max_per_hour"] = max(1, min(200, int(merged["max_per_hour"] or 10)))
    db = await get_db()
    try:
        await ensure_schema(db)
        await db.execute(
            "INSERT INTO channel_points_tts_config (account_id, enabled, reward_names, "
            "max_len, cooldown_sec, max_per_hour, blacklist, announce_user, channel, voice, voice_provider) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(account_id) DO UPDATE SET enabled=excluded.enabled, "
            "reward_names=excluded.reward_names, max_len=excluded.max_len, "
            "cooldown_sec=excluded.cooldown_sec, max_per_hour=excluded.max_per_hour, "
            "blacklist=excluded.blacklist, announce_user=excluded.announce_user, "
            "channel=excluded.channel, voice=excluded.voice, voice_provider=excluded.voice_provider",
            (account_id, merged["enabled"], merged["reward_names"], merged["max_len"],
             merged["cooldown_sec"], merged["max_per_hour"], merged["blacklist"],
             merged["announce_user"], str(merged["channel"]).strip().lstrip("#").lower(),
             str(merged["voice"]).strip(), str(merged["voice_provider"]).strip().lower()))
        await db.commit()
    finally:
        await db.close()
    return merged


def _check_text(cfg: dict, text: str) -> tuple[bool, str]:
    """Статические фильтры: непусто + blacklist (длина обрезается позже)."""
    if not text.strip():
        return False, "empty"
    bl = [w.strip().lower() for w in (cfg["blacklist"] or "").split(",") if w.strip()]
    low = text.lower()
    for w in bl:
        if w in low:
            return False, "blacklist"
    return True, ""


def _check_rate(cfg: dict, account_id: int, user: str) -> tuple[bool, str]:
    """Кулдаун + часовой лимит на юзера. Возвращает (ok, причина)."""
    now = time.monotonic()
    key = (int(account_id), (user or "").lower())
    st = _state.setdefault(key, {"last": 0.0, "window": []})
    cd = int(cfg["cooldown_sec"] or 0)
    if cd and now - st["last"] < cd:
        return False, "cooldown"
    lim = int(cfg["max_per_hour"] or 0)
    if lim:
        st["window"] = [t for t in st["window"] if now - t < 3600]
        if len(st["window"]) >= lim:
            return False, "hour_limit"
        st["window"].append(now)
    st["last"] = now
    return True, ""


def _reset_rate_state() -> None:
    _state.clear()


async def handle_redemption(account_id: int, channel: str, payload: dict) -> bool:
    """Точка входа из server.py:on_eventsub_event. True — озвучено."""
    try:
        cfg = await _load_config(account_id)
    except Exception as exc:
        logger.debug("cp_tts config load error: %s", exc)
        return False
    if not int(cfg.get("enabled") or 0):
        return False

    reward_title = str(((payload.get("reward") or {}).get("title")) or "")
    names = [n.strip().lower() for n in (cfg.get("reward_names") or "").split(",") if n.strip()]
    if names and reward_title.lower() not in names:
        return False

    user = (payload.get("user_login") or payload.get("user_name") or "").strip()
    text = str(payload.get("user_input") or "").strip()

    ok, why = _check_text(cfg, text)
    if not ok:
        logger.debug("cp_tts skip (%s): %s", why, text[:40])
        return False
    ok, why = _check_rate(cfg, account_id, user)
    if not ok:
        logger.debug("cp_tts rate skip (%s): %s", why, user)
        return False

    channel = str(cfg.get("channel") or channel or "").strip().lstrip("#").lower()
    if not channel:
        logger.debug("cp_tts skip: channel is not configured")
        return False
    from app.tts_voice_policy import authorize_tts
    decision = await authorize_tts(
        account_id, channel, "channel_points_reward",
        actor_role="viewer", actor_id=str(payload.get("user_id") or user), text=text,
        requested_alias=str(payload.get("voice_alias") or ""),
    )
    if not decision["ok"]:
        logger.debug("cp_tts policy skip: %s", decision.get("reason"))
        return False
    text = text[: int(cfg["max_len"])]
    announce = int(cfg.get("announce_user") or 0)
    spoken = f"Говорит {user}: {text}" if announce else text
    try:
        from app.audio_queue import get_audio_queue
        await get_audio_queue().enqueue(
            "tts_redemption", account_id, channel, spoken,
            speaker=user,
            speaker_kind="viewer",
            display_text=text,
            provider_override=str(decision.get("provider_override") or cfg.get("voice_provider") or ""),
            voice_override=str(decision.get("voice_override") or cfg.get("voice") or ""),
        )
        return True
    except Exception as exc:
        logger.debug("cp_tts speak error: %s", exc)
        return False


async def test_speak(
    account_id: int, channel: str, text: str, *, voice: str = "", voice_provider: str = ""
) -> bool:
    """Кнопка «Тест» в панели — озвучить без фильтров (speaker = тест)."""
    from app.audio_queue import get_audio_queue
    cfg = await _load_config(account_id)
    await get_audio_queue().enqueue(
        "tts_redemption", account_id, channel, text[:300],
        speaker="test", speaker_kind="viewer", display_text=text[:300],
        provider_override=str(voice_provider or cfg.get("voice_provider") or ""),
        voice_override=str(voice or cfg.get("voice") or ""),
    )
    return True


# ── HTTP ────────────────────────────────────────────────────────────────

@router.get("/{account_id}")
async def api_get_config(account_id: int) -> dict:
    return {"ok": True, "config": await get_config(account_id)}


@router.put("/{account_id}")
async def api_put_config(account_id: int, request: Request) -> dict:
    data = await request.json()
    return {"ok": True, "config": await save_config(account_id, data or {})}


@router.post("/{account_id}/test")
async def api_test(account_id: int, request: Request) -> dict:
    data = await request.json()
    text = str((data or {}).get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "empty"}
    channel = str((data or {}).get("channel") or "").strip().lower().lstrip("#")
    if not channel:
        return {"ok": False, "error": "channel_required"}
    db = await get_db()
    try:
        scope = await (await db.execute(
            "SELECT 1 FROM channels WHERE account_id=? AND enabled=1 "
            "AND lower(ltrim(channel_name,'#'))=? LIMIT 1",
            (account_id, channel),
        )).fetchone()
    finally:
        await db.close()
    if not scope:
        return {"ok": False, "error": "scope_not_found"}
    await test_speak(
        account_id, channel, text,
        voice=str((data or {}).get("voice") or ""),
        voice_provider=str((data or {}).get("voice_provider") or ""),
    )
    return {"ok": True}
