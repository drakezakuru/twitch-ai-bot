"""Управление флотом ботов, анти-детект, здоровье аккаунтов и автоматизация каналов.

Фичи:
1. Чекер токенов и прокси (Светофор: 🟢/🟡/🔴).
2. Плавный заход ботов (Staggered Join).
3. Авто-запуск по онлайну стримера (Live Trigger — тумблер per-channel).
4. Квота на канал с отбором самых активных ботов (chatter, contact_level, activity).
5. Подгонка числа ботов под реальных зрителей стрима (Q39).
6. Случайная задержка между сообщениями (Q36 Humanizer Jitter).
7. Автовыбор самого давно молчавшего бота (Q35 LRU Speaker).
8. Массовые действия над ботами (Bulk Actions).
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any

from app.database import get_db

logger = logging.getLogger(__name__)

# Хранилище времени последнего сообщения бота на канале: (account_id, channel) -> timestamp
_last_spoken: dict[tuple[int, str], float] = {}

# Активные задачи плавного захода: channel -> asyncio.Task
_active_stagger_tasks: dict[str, asyncio.Task] = {}


async def ensure_schema(db: Any = None) -> None:
    """Создаёт таблицы автоматизации каналов и кэша здоровья ботов."""
    close_db = False
    if db is None:
        db = await get_db()
        close_db = True
    try:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS channel_fleet_settings (
                channel_name TEXT PRIMARY KEY,
                auto_start_on_live INTEGER DEFAULT 0,
                bot_limit INTEGER DEFAULT 0,
                selection_mode TEXT DEFAULT 'active',
                scale_with_viewers INTEGER DEFAULT 0,
                viewer_ratio_percent INTEGER DEFAULT 20,
                stagger_sec_min REAL DEFAULT 3.0,
                stagger_sec_max REAL DEFAULT 8.0,
                message_jitter_min REAL DEFAULT 1.5,
                message_jitter_max REAL DEFAULT 4.5,
                updated_at REAL DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS account_health_status (
                account_id INTEGER PRIMARY KEY,
                token_status TEXT DEFAULT 'unknown',
                proxy_status TEXT DEFAULT 'unknown',
                health TEXT DEFAULT 'unknown',
                last_checked_at REAL DEFAULT 0,
                error_message TEXT DEFAULT ''
            )
        """)
        await db.commit()
    finally:
        if close_db:
            await db.close()


# ── Q35 / Q36: Humanizer (LRU спикер и рандомизация задержки) ──

def record_bot_spoken(account_id: int, channel: str, timestamp: float | None = None) -> None:
    """Фиксирует время отправки сообщения ботом на канале."""
    ch = str(channel or "").lower().strip().lstrip("#")
    if ch and account_id > 0:
        _last_spoken[(account_id, ch)] = timestamp if timestamp is not None else time.time()


def get_least_recently_spoken(channel: str, candidate_account_ids: list[int]) -> int | None:
    """Q35: Автовыбор аккаунта, который дольше всего молчал на данном канале."""
    ch = str(channel or "").lower().strip().lstrip("#")
    if not candidate_account_ids:
        return None
    # Сортируем: сначала те, кто вообще не говорил (last_time = 0), затем самый старый timestamp
    # Если несколько ботов еще не говорили — рандомизируем между ними
    unspoken = [aid for aid in candidate_account_ids if (aid, ch) not in _last_spoken]
    if unspoken:
        return random.choice(unspoken)
    return min(candidate_account_ids, key=lambda aid: _last_spoken.get((aid, ch), 0.0))


def get_humanizer_jitter(channel: str, min_delay: float = 1.5, max_delay: float = 4.5) -> float:
    """Q36: Возвращает случайную задержку (джиттер) перед отправкой реплики в чат."""
    if max_delay < min_delay:
        min_delay, max_delay = max_delay, min_delay
    return round(random.uniform(min_delay, max_delay), 2)


async def get_humanizer_jitter_for_channel(channel: str, default_min: float = 1.0, default_max: float = 5.0) -> float:
    """Q36: Возвращает случайную задержку с учетом настроек канала из БД."""
    settings = await get_channel_fleet_settings(channel)
    min_sec = settings.get("message_jitter_min_sec", default_min)
    max_sec = settings.get("message_jitter_max_sec", default_max)
    return get_humanizer_jitter(channel, min_sec, max_sec)


# ── Чекер здоровья ботов (Светофор: токен + прокси) ──

async def check_single_account_health(
    account_id_or_dict: int | dict[str, Any],
    token: str = "",
    proxy: str = ""
) -> dict[str, Any]:
    """Проверяет валидность токена и доступность прокси для бота."""
    from app.security import decrypt_token
    from app.twitch_helix import validate_token

    if isinstance(account_id_or_dict, dict):
        account_id = int(account_id_or_dict.get("id") or 0)
        token = str(account_id_or_dict.get("token") or token)
        proxy = str(account_id_or_dict.get("proxy") or proxy)
    else:
        account_id = int(account_id_or_dict)

    raw_tok = decrypt_token(token) if token else ""
    if raw_tok.startswith("oauth:"):
        raw_tok = raw_tok[6:]

    token_status = "invalid"
    login = ""
    error_msg = ""

    if raw_tok:
        try:
            info = await asyncio.wait_for(validate_token(raw_tok), timeout=7.0)
            if info and info.get("login"):
                token_status = "valid"
                login = info.get("login", "")
            else:
                token_status = "invalid"
                error_msg = "Токен отклонён Twitch"
        except asyncio.TimeoutError:
            token_status = "timeout"
            error_msg = "Таймаут проверки Twitch"
        except Exception as e:
            token_status = "error"
            error_msg = str(e)[:100]
    else:
        error_msg = "Токен отсутствует"

    # Проверка прокси
    proxy_status = "none"
    if proxy:
        proxy_status = await _ping_proxy(proxy)

    # Итоговый светофор:
    # 🟢 green / ok = токен валиден и прокси (если есть) живой
    # 🟡 yellow / proxy_error = токен валиден, но прокси лагает/оффлайн
    # 🔴 red / auth_error = токен невалиден
    token_valid = (token_status == "valid")
    proxy_ok = (proxy_status in {"ok", "slow", "none"})

    failover_info = None
    if proxy and not proxy_ok:
        try:
            from app.proxy_pool import get_proxy_pool_settings, failover_bot_proxy
            p_settings = await get_proxy_pool_settings()
            if p_settings.get("auto_failover"):
                fo_res = await failover_bot_proxy(account_id, reason=f"Здоровье флота: прокси {proxy_status}")
                failover_info = fo_res
                if fo_res.get("ok"):
                    proxy_ok = True
                    proxy_status = "replaced"
                    error_msg = f"Прокси заменен на {fo_res.get('new_proxy')}"
                else:
                    error_msg = f"Прокси упал: {fo_res.get('message')}"
            else:
                error_msg = "Прокси не отвечает. Требуется замена!"
        except Exception as fe:
            logger.warning("[bot_fleet] Ошибка авто-failover для бота %d: %s", account_id, fe)

    if token_valid:
        if proxy and not proxy_ok:
            health = "yellow"
            status = "proxy_error"
        else:
            health = "green"
            status = "ok"
    else:
        health = "red"
        status = "auth_error"

    return {
        "account_id": account_id,
        "login": login,
        "token_status": token_status,
        "proxy_status": proxy_status,
        "health": health,
        "status": status,
        "token_valid": token_valid,
        "proxy_ok": proxy_ok,
        "failover": failover_info,
        "error": error_msg,
        "checked_at": time.time(),
    }


async def _ping_proxy(proxy_url: str) -> str:
    """Быстрый ping прокси соединения."""
    try:
        import httpx
        # Проверяем простой connect через прокси к надежному endpoint с таймаутом 4 сек
        async with httpx.AsyncClient(proxy=proxy_url, timeout=4.0) as client:
            resp = await client.get("https://id.twitch.tv/oauth2/validate", timeout=4.0)
            # Если ответил (даже 401 unauth) — прокси рабочий и пропускает HTTPS!
            return "ok" if resp.status_code in {200, 401, 400} else "slow"
    except (httpx.ConnectTimeout, asyncio.TimeoutError):
        return "timeout"
    except Exception:
        return "dead"


async def run_fleet_health_check(account_ids: list[int] | None = None, limit: int = 100) -> dict[str, Any]:
    """Массовая фоновая проверка здоровья всех ботов."""
    await ensure_schema()
    db = await get_db()
    try:
        if account_ids:
            placeholders = ",".join("?" for _ in account_ids)
            cur = await db.execute(f"SELECT id, nickname, token, proxy FROM accounts WHERE id IN ({placeholders})", account_ids)
            accounts = await cur.fetchall()
        else:
            cur = await db.execute("SELECT id, nickname, token, proxy FROM accounts ORDER BY id ASC LIMIT ?", (limit,))
            accounts = await cur.fetchall()
    finally:
        await db.close()

    tasks = [
        check_single_account_health(row["id"], row["token"], row["proxy"] or "")
        for row in accounts
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    formatted: list[dict[str, Any]] = []
    db = await get_db()
    try:
        for row, res in zip(accounts, results):
            if isinstance(res, Exception):
                data = {
                    "account_id": row["id"],
                    "nickname": row["nickname"],
                    "token_status": "error",
                    "proxy_status": "none",
                    "health": "red",
                    "status": "auth_error",
                    "token_valid": False,
                    "proxy_ok": False,
                    "error": str(res)[:100],
                    "checked_at": time.time(),
                }
            else:
                data = res
                data["nickname"] = row["nickname"]

            await db.execute("""
                INSERT INTO account_health_status (account_id, token_status, proxy_status, health, last_checked_at, error_message)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    token_status = excluded.token_status,
                    proxy_status = excluded.proxy_status,
                    health = excluded.health,
                    last_checked_at = excluded.last_checked_at,
                    error_message = excluded.error_message
            """, (
                data["account_id"],
                data["token_status"],
                data["proxy_status"],
                data["health"],
                data["checked_at"],
                data.get("error", ""),
            ))
            formatted.append(data)
        await db.commit()
    finally:
        await db.close()

    counts = {
        "green": sum(1 for r in formatted if r["health"] == "green"),
        "yellow": sum(1 for r in formatted if r["health"] == "yellow"),
        "red": sum(1 for r in formatted if r["health"] == "red"),
        "total": len(formatted),
    }
    results_map = {str(r["account_id"]): r for r in formatted}
    return {
        "ok": True,
        "counts": counts,
        "total": len(formatted),
        "items": formatted,
        "results": results_map,
    }


# ── Квоты, выбор самых активных и подгонка под зрителей (Q39) ──

async def get_channel_fleet_settings(channel: str) -> dict[str, Any]:
    """Возвращает настройки автоматизации флота для канала."""
    await ensure_schema()
    ch = str(channel or "").lower().strip().lstrip("#")
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM channel_fleet_settings WHERE channel_name = ?", (ch,))
        row = await cur.fetchone()
        if row:
            d = dict(row)
            d["auto_start_on_live"] = bool(d.get("auto_start_on_live"))
            d["auto_stop_on_offline"] = bool(d.get("auto_stop_on_offline"))
            d["scale_with_viewers"] = bool(d.get("scale_with_viewers"))
            d["message_jitter_min_sec"] = d.get("message_jitter_min", 1.5)
            d["message_jitter_max_sec"] = d.get("message_jitter_max", 4.5)
            return d
        return {
            "channel_name": ch,
            "auto_start_on_live": False,
            "auto_stop_on_offline": False,
            "bot_limit": 0,
            "selection_mode": "active_first",
            "scale_with_viewers": False,
            "viewer_ratio_percent": 20,
            "stagger_sec_min": 3.0,
            "stagger_sec_max": 8.0,
            "message_jitter_min": 1.5,
            "message_jitter_max": 4.5,
            "message_jitter_min_sec": 1.5,
            "message_jitter_max_sec": 4.5,
        }
    finally:
        await db.close()


async def save_channel_fleet_settings(channel: str, data: dict[str, Any]) -> dict[str, Any]:
    """Сохраняет настройки автоматизации флота для канала."""
    await ensure_schema()
    ch = str(channel or "").lower().strip().lstrip("#")
    db = await get_db()
    try:
        await db.execute("""
            INSERT INTO channel_fleet_settings (
                channel_name, auto_start_on_live, bot_limit, selection_mode,
                scale_with_viewers, viewer_ratio_percent, stagger_sec_min, stagger_sec_max,
                message_jitter_min, message_jitter_max, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(channel_name) DO UPDATE SET
                auto_start_on_live = excluded.auto_start_on_live,
                bot_limit = excluded.bot_limit,
                selection_mode = excluded.selection_mode,
                scale_with_viewers = excluded.scale_with_viewers,
                viewer_ratio_percent = excluded.viewer_ratio_percent,
                stagger_sec_min = excluded.stagger_sec_min,
                stagger_sec_max = excluded.stagger_sec_max,
                message_jitter_min = excluded.message_jitter_min,
                message_jitter_max = excluded.message_jitter_max,
                updated_at = excluded.updated_at
        """, (
            ch,
            int(bool(data.get("auto_start_on_live"))),
            max(0, int(data.get("bot_limit") or 0)),
            str(data.get("selection_mode") or "active_first"),
            int(bool(data.get("scale_with_viewers"))),
            max(1, min(100, int(data.get("viewer_ratio_percent") or 20))),
            max(0.5, float(data.get("stagger_sec_min") or 3.0)),
            max(1.0, float(data.get("stagger_sec_max") or 8.0)),
            float(data.get("message_jitter_min_sec") if data.get("message_jitter_min_sec") is not None else (data.get("message_jitter_min") or 1.5)),
            float(data.get("message_jitter_max_sec") if data.get("message_jitter_max_sec") is not None else (data.get("message_jitter_max") or 4.5)),
            time.time(),
        ))
        await db.commit()
        return await get_channel_fleet_settings(ch)
    finally:
        await db.close()


def sort_bots_by_activity(accounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Сортирует ботов так, чтобы самыми первыми шли наиболее активные (болтуны)."""
    def _bot_score(acc: dict[str, Any]) -> tuple[int, int, str]:
        role = str(acc.get("bot_role") or "lurker").lower()
        # chatter имеет высший приоритет над lurker
        role_prio = 2 if role == "chatter" else 1
        # contact_level если задан
        contact = int(acc.get("contact_level") or 5)
        # nickname для стабильности
        nick = str(acc.get("nickname") or "")
        return (role_prio, contact, nick)

    return sorted(accounts, key=_bot_score, reverse=True)


async def filter_and_limit_bots(
    channel_or_candidates: str | list[dict[str, Any]],
    candidates_or_settings: list[dict[str, Any]] | dict[str, Any] | None = None,
    current_viewers: int | None = None,
) -> list[dict[str, Any]]:
    """Применяет квоту, отбор самых активных и подгонку под зрителей (Q39)."""
    if isinstance(channel_or_candidates, str):
        channel = channel_or_candidates
        candidates = list(candidates_or_settings or [])
        cfg = await get_channel_fleet_settings(channel)
    else:
        candidates = list(channel_or_candidates)
        channel = ""
        cfg = dict(candidates_or_settings or {})

    limit = int(cfg.get("bot_limit") or 0)
    scale = bool(cfg.get("scale_with_viewers"))
    ratio = float(cfg.get("viewer_ratio_percent") or 20.0)
    mode = str(cfg.get("selection_mode") or "active").lower()

    # Сортируем кандидатов
    if mode in ("active", "active_first"):
        sorted_bots = sort_bots_by_activity(candidates)
    elif mode == "lru":
        ch = channel.lower().strip().lstrip("#")
        sorted_bots = sorted(candidates, key=lambda a: _last_spoken.get((a["id"], ch), 0.0))
    else:
        sorted_bots = list(candidates)
        random.shuffle(sorted_bots)

    target_count = len(sorted_bots)

    # Подгонка числа ботов под реальных зрителей (Q39)
    if scale:
        viewer_count = 0
        if current_viewers is not None:
            viewer_count = int(current_viewers)
        elif channel:
            from app import stream_health
            health_info = stream_health.get_channel_health(channel)
            viewer_count = int(health_info.get("viewer_count") or 0)

        if viewer_count > 0:
            scaled = max(1, round(viewer_count * (ratio / 100.0)))
            target_count = min(target_count, scaled)
            logger.info("[fleet] #%s подгонка под онлайн (%d зрителей, %.1f%%) -> %d ботов",
                        channel, viewer_count, ratio, target_count)

    if limit > 0:
        target_count = min(target_count, limit)

    return sorted_bots[:target_count]


async def stream_live_trigger_loop(interval: float = 60.0) -> None:
    """Фоновый цикл проверки Live-триггеров (авто-запуск ботов при начале стрима)."""
    while True:
        try:
            await asyncio.sleep(interval)
            await ensure_schema()
            db = await get_db()
            try:
                cur = await db.execute("SELECT * FROM channel_fleet_settings WHERE auto_start_on_live = 1")
                rows = await cur.fetchall()
            finally:
                await db.close()

            if not rows:
                continue

            from app.stream_health import get_channel_health
            from app.bulk_channels_routes import start_channel_bots, stop_channel_bots
            from app.server import bot_manager

            running_statuses = bot_manager.get_all_statuses()

            for row in rows:
                ch = row["channel_name"]
                health = get_channel_health(ch)
                is_live = bool(health.get("is_live"))

                is_connected = any(
                    ch.lower() in [c.lower().lstrip("#") for c in s.get("channels") or []]
                    for s in running_statuses.values()
                    if s.get("connected")
                )

                if is_live and not is_connected:
                    logger.info("[live-trigger] Стрим #%s в эфире! Автозапуск ботов...", ch)
                    await start_channel_bots(ch, stagger=True)
                elif not is_live and is_connected:
                    logger.info("[live-trigger] Стрим #%s оффлайн. Автоостановка ботов...", ch)
                    await stop_channel_bots(ch)
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.debug("stream_live_trigger_loop error: %s", e)

