"""BOT INTELLIGENCE: CLIP MOMENT DETECTION — вынесено из app/routes.py
(P5-сплит, PLAN.md). Декорирует ОБЩИЙ router из app.routes; импортируется
ВНИЗУ routes.py (после создания router), поэтому `from app.routes import router`
здесь валиден. Имена _chat_rate_tracker/_clip_cooldowns/register_clip_rate_hook
реэкспортируются обратно в app.routes (их импортируют tests и server.py).
"""
import time as _time

from fastapi import Request

import time
from app.database import get_db, get_setting, set_setting
from app import chat_analyzer  # noqa: E402
import logging
from app.routes import router  # noqa: E402 — валиден: импорт из конца routes.py


# ===================== BOT INTELLIGENCE: CLIP MOMENT DETECTION =====================

_chat_rate_tracker: dict[tuple[int, str], list[float]] = {}
_clip_cooldowns: dict[tuple[int, str], float] = {}


def _note_clip_rate(account_id: int, channel: str) -> None:
    """PLAN §9g: одна точка пополнения трекера скорости чата (реальный поток + standalone API)."""
    key = (int(account_id), (channel or "").lstrip("#").lower())
    now = _time.time()
    _chat_rate_tracker.setdefault(key, []).append(now)
    cutoff = now - 300
    _chat_rate_tracker[key] = [t for t in _chat_rate_tracker[key] if t > cutoff]


def register_clip_rate_hook(analyzer) -> None:
    """PLAN §9g: подключить реальный поток чата (chat_analyzer.on_message) к трекеру."""
    analyzer.set_clip_rate_listener(_note_clip_rate)


@router.post("/api/bot/clip-detector/message")
async def bot_clip_message(req: Request) -> dict:
    data = await req.json()
    account_id = data.get("account_id")
    channel = data.get("channel")
    if account_id is None or channel is None:
        return {"ok": False, "error": "Missing required fields: account_id, channel"}
    _note_clip_rate(int(account_id), str(channel).lower())
    now = _time.time()
    key = (int(account_id), str(channel).lstrip("#").lower())
    # Count last 60s
    count_60 = sum(1 for t in _chat_rate_tracker[key] if t > now - 60)
    return {"ok": True, "count_last_60s": count_60}


@router.get("/api/bot/clip-detector/check/{account_id}/{channel}")
async def bot_clip_check(account_id: int, channel: str) -> dict:
    import datetime
    key = (account_id, channel.lower())
    now = _time.time()
    timestamps = _chat_rate_tracker.get(key, [])
    # Get config — §4.4: per-bot настройки имеют приоритет, глобальные — fallback
    try:
        from app.server import chat_analyzer as _ca
        _s = _ca.get_settings(account_id)
    except Exception:
        _s = {}
    threshold_multiplier = float(
        _s.get("clip_threshold_multiplier")
        if _s.get("clip_threshold_multiplier") is not None
        else (await get_setting("clip_threshold_multiplier") or "3.0")
    )
    window_sec = int(
        _s.get("clip_window_sec")
        if _s.get("clip_window_sec") is not None
        else (await get_setting("clip_window_sec") or "60")
    )
    cooldown_sec = int(
        _s.get("clip_cooldown_sec")
        if _s.get("clip_cooldown_sec") is not None
        else (await get_setting("clip_cooldown_sec") or "30")
    )
    # Count messages in last window_sec
    current_count = sum(1 for t in timestamps if t > now - window_sec)
    current_rate = current_count / max(window_sec, 1)
    # Average rate over last 5 min
    total_5min = sum(1 for t in timestamps if t > now - 300)
    avg_rate = total_5min / 300.0
    # Check spike
    spike = False
    if avg_rate > 0.5 / 60.0 and current_rate > threshold_multiplier * avg_rate:
        # Check cooldown
        last_clip = _clip_cooldowns.get(key, 0)
        if now - last_clip > cooldown_sec:
            spike = True
            _clip_cooldowns[key] = now
            # PLAN §9g: фиксируем момент (без клипа) — попадает в список моментов и Dashboard.
            try:
                db = await get_db()
                try:
                    await db.execute(
                        "INSERT INTO clip_moments (account_id, channel, rate, avg_rate, clip_url, timestamp) "
                        "VALUES (?, ?, ?, ?, '', ?)",
                        (account_id, channel.lower(), round(current_rate, 4), round(avg_rate, 4),
                         datetime.datetime.utcnow().isoformat()),
                    )
                    await db.commit()
                finally:
                    await db.close()
            except Exception as exc:
                logging.getLogger(__name__).debug("clip moment insert error: %s", exc)
    return {
        "spike": spike,
        "rate": round(current_rate, 4),
        "avg_rate": round(avg_rate, 4),
        "timestamp": datetime.datetime.utcnow().isoformat() if spike else "",
    }


@router.post("/api/bot/clip-detector/create-clip")
async def bot_clip_create(req: Request) -> dict:
    import httpx
    import datetime
    data = await req.json()
    try:
        account_id = int(data.get("account_id") or 0)
    except (TypeError, ValueError):
        account_id = 0
    channel = str(data.get("channel") or "").strip().lower().lstrip("#")
    if account_id <= 0 or not channel:
        return {"ok": False, "error": "Missing required fields: account_id, channel"}
    db = await get_db()
    try:
        row = await db.execute(
            "SELECT token FROM accounts WHERE id = ?",
            (account_id,),
        )
        row = await row.fetchone()
        if not row:
            return {"ok": False, "error": "Account not found"}
        scoped_channel = await (await db.execute(
            "SELECT 1 FROM channels WHERE account_id = ? AND enabled = 1 "
            "AND lower(ltrim(trim(channel_name), '#')) = ?",
            (account_id, channel),
        )).fetchone()
        if not scoped_channel:
            return {"ok": False, "error": "Channel is not enabled for this account"}
        from app.security import decrypt_token
        from app import twitch_helix
        oauth_token = decrypt_token(row[0])
        client_id = twitch_helix._client_id()
        broadcaster_id = await twitch_helix.get_user_id(channel, oauth_token)
        if not oauth_token or not client_id or not broadcaster_id:
            return {"ok": False, "error": "Twitch clip credentials are not configured"}
        # Call Twitch Helix to create clip
        headers = {
            "Authorization": f"Bearer {oauth_token}",
            "Client-Id": client_id,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{twitch_helix.HELIX_BASE}/clips",
                headers=headers,
                params={"broadcaster_id": str(broadcaster_id)},
            )
            if resp.status_code in (401, 403):
                return {"ok": False, "error": "Twitch token expired or insufficient permissions. Please re-authenticate."}
            if resp.status_code not in (200, 202):
                return {"ok": False, "error": f"Twitch API error (HTTP {resp.status_code})"}
            result = resp.json()
        clip_url = ""
        edit_url = ""
        if "data" in result and result["data"]:
            clip_url = result["data"][0].get("id", "")
            edit_url = result["data"][0].get("edit_url", "")
        # Store in DB
        key = (account_id, channel)
        timestamps = _chat_rate_tracker.get(key, [])
        now = _time.time()
        current_count = sum(1 for t in timestamps if t > now - 60)
        current_rate = current_count / 60.0
        total_5min = sum(1 for t in timestamps if t > now - 300)
        avg_rate = total_5min / 300.0
        ts = datetime.datetime.utcnow().isoformat()
        await db.execute(
            "INSERT INTO clip_moments (account_id, channel, rate, avg_rate, clip_url, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
            (account_id, channel, current_rate, avg_rate, clip_url, ts),
        )
        await db.commit()
        return {"ok": True, "clip_url": clip_url, "edit_url": edit_url}
    finally:
        await db.close()


@router.get("/api/bot/clip-detector/moments/{account_id}")
async def bot_clip_moments(account_id: int) -> dict:
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT id, channel, rate, avg_rate, clip_url, timestamp, created_at FROM clip_moments WHERE account_id = ? ORDER BY id DESC LIMIT 50",
            (account_id,),
        )
        rows = await cur.fetchall()
        items = []
        for r in rows:
            items.append({
                "id": r[0], "channel": r[1], "rate": r[2], "avg_rate": r[3],
                "clip_url": r[4], "timestamp": r[5], "created_at": r[6],
            })
        return {"items": items}
    finally:
        await db.close()


@router.get("/api/bot/clip-detector/config")
async def bot_clip_config_get(account_id: int | None = None) -> dict:
    """§4.4 PLAN_FEEDBACK_2908: конфиг клип-детектора.

    С account_id — настройки конкретного бота (per-account analyzer settings);
    без — глобальные settings (обратная совместимость)."""
    if account_id is not None:
        from app.server import chat_analyzer
        s = chat_analyzer.get_settings(account_id)

        async def _per(key: str, cast, default):
            v = s.get(key)
            if v is None:  # не задано у бота → показываем глобальное
                v = await get_setting(key) or default
            return cast(v)

        return {
            "account_id": account_id,
            "threshold_multiplier": await _per("clip_threshold_multiplier", float, "3.0"),
            "window_sec": await _per("clip_window_sec", int, "60"),
            "cooldown_sec": await _per("clip_cooldown_sec", int, "30"),
        }
    return {
        "threshold_multiplier": float(await get_setting("clip_threshold_multiplier") or "3.0"),
        "window_sec": int(await get_setting("clip_window_sec") or "60"),
        "cooldown_sec": int(await get_setting("clip_cooldown_sec") or "30"),
    }


@router.put("/api/bot/clip-detector/config")
async def bot_clip_config_put(req: Request) -> dict:
    data = await req.json()
    # §4.4: account_id в теле → настройки конкретного бота (analyzer settings).
    if data.get("account_id") is not None:
        from app.server import chat_analyzer
        updates = {}
        if "threshold_multiplier" in data:
            updates["clip_threshold_multiplier"] = float(data["threshold_multiplier"])
        if "window_sec" in data:
            updates["clip_window_sec"] = int(data["window_sec"])
        if "cooldown_sec" in data:
            updates["clip_cooldown_sec"] = int(data["cooldown_sec"])
        chat_analyzer.update_settings(int(data["account_id"]), updates)
        return {"ok": True, "account_id": int(data["account_id"])}
    if "threshold_multiplier" in data:
        await set_setting("clip_threshold_multiplier", str(data["threshold_multiplier"]))
    if "window_sec" in data:
        await set_setting("clip_window_sec", str(data["window_sec"]))
    if "cooldown_sec" in data:
        await set_setting("clip_cooldown_sec", str(data["cooldown_sec"]))
    return {"ok": True}
