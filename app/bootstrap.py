"""OPS_PLAN §2 — общая инициализация ботов (панель и standalone без дублирования).

Здесь живёт wiring, который раньше был только в server.py lifespan:
- загрузка AI-настроек из БД (включая per-account override и custom-провайдеров);
- подключение колбэков bot_manager ↔ chat_analyzer ↔ bot_logs;
- подключение аккаунтов (start_bot + токен + EventSub);
- авто-подключение включённых ботов (autoconnect);
- log_message (чтение чата в БД + per-bot логи).

server.py и app/standalone.py (run_bot.py) используют одни и те же функции —
чтобы не разъезжались поведение панели и standalone-бота.
"""

from __future__ import annotations

import asyncio
import json
import logging
import traceback
from typing import Any

from app.ai_service import AIService, set_ai_log_callback, ai_log
from app.bot_manager import TwitchBotManager
from app.chat_analyzer import ChatAnalyzer
from app.database import get_db, get_setting
from app.security import decrypt_token

logger = logging.getLogger(__name__)


# ── Логирование чтений чата (перенесено из server.py) ──

async def log_message(
    account_id: int, channel: str, author: str, message: str, is_bot: bool,
    *, badges: list[str] | None = None, message_id: str = "", channel_id: str = "",
) -> None:
    try:
        # v9 AP: классифицируем сообщение для sentiment timeline
        try:
            from app.sentiment import classify as _sent_classify
            sentiment = _sent_classify(message)
        except Exception:
            sentiment = 0
        db = await get_db()
        try:
            await db.execute(
                "INSERT INTO chat_log (account_id, channel, author, message, is_bot, sentiment) VALUES (?, ?, ?, ?, ?, ?)",
                (account_id, channel, author, message, 1 if is_bot else 0, sentiment),
            )
            await db.commit()
        finally:
            await db.close()

        # §25.2: чтения чата должны быть видны в «Глобальных логах» (bot_logs,
        # категория chat) — раньше туда попадали только AI/TTS/trigger-события.
        try:
            from app.bot_logs import log_per_bot
            prefix = "bot" if is_bot else "viewer"
            await log_per_bot(
                account_id, channel, "chat",
                f"[{prefix}] {author}: {message}", level="info",
            )
        except Exception:
            pass

        # When enabled for an account, regular viewer messages gently increase
        # chat affinity without overwriting the streamer's manual contact value.
        if not is_bot:
            try:
                db = await get_db()
                try:
                    await db.execute(
                        "UPDATE bot_affinity SET chat_affinity = MIN(100, chat_affinity + 1), "
                        "updated_at = CURRENT_TIMESTAMP WHERE account_id = ? AND channel = ? AND username = ? "
                        "AND auto_adjust = 1 AND manual_lock = 0",
                        (account_id, channel.lower().strip().lstrip("#"), author.lower().strip()),
                    )
                    await db.commit()
                finally:
                    await db.close()
            except Exception:
                logger.debug("affinity auto-adjust failed", exc_info=True)

        try:
            from app.chat_overlay_routes import chat_event_payload
            from app.routes import broadcast_log
            from app.widget_bus import claim_event
            from app.widget_channel_scope import remember_channel_identity
            await remember_channel_identity(channel, channel_id)
            if claim_event(channel, message_id):
                await broadcast_log(await chat_event_payload(
                    account_id=account_id,
                    channel=channel,
                    author=author,
                    message=message,
                    is_bot=is_bot,
                    badges=badges,
                    message_id=message_id,
                ))
        except Exception:
            pass  # broadcast не критичен (standalone без панели)
    except Exception as exc:
        logger.error("Ошибка записи лога: %s", exc)


def make_health_logger(broadcast=None):
    """Health-события (план §5.1): смена состояния бота пишется в per-bot лог."""

    async def on_bot_health(account_id: int, nickname: str, old_state: str, new_state: str, error: str) -> None:
        from app.bot_logs import log_per_bot
        level = {"error": "error", "connecting": "warning"}.get(new_state, "info")
        msg = f"Health: {old_state} → {new_state}" + (f" ({error})" if error else "")
        await log_per_bot(account_id, "", "system", msg, level=level)
        if broadcast:
            try:
                await broadcast({"type": "health", "account_id": account_id, "nickname": nickname,
                                 "state": new_state, "error": error})
            except Exception:
                pass

    return on_bot_health


# ── AI-настройки из БД ──

async def load_ai_state(ai_service: AIService) -> None:
    """Загружает AI-настройки, per-account override и custom-провайдеров из БД."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT key, value FROM settings WHERE key LIKE 'ai_%'")
        rows = await cursor.fetchall()
        if rows:
            ai_cfg = {}
            for row in rows:
                k = row["key"].replace("ai_", "", 1)
                ai_cfg[k] = decrypt_token(row["value"])
            ai_service.update_config(ai_cfg)
            offline_mode = await get_setting("offline_mode", "0")
            ai_service.update_config({"offline_mode": offline_mode == "1"})
            logger.info("AI-настройки загружены из БД")
    finally:
        await db.close()

    # v10.4.3: per-account AI override — поднимаем из БД и заливаем в AIService cache.
    try:
        db_ov = await get_db()
        try:
            cur = await db_ov.execute(
                "SELECT id, ai_provider_override, ai_chat_model_override, "
                "ai_vision_model_override, openrouter_api_key_override, ai_api_key_override, "
                "custom_ai_base_url, custom_ai_api_key, "
                "ai_local_fallback, ai_smart_routing_json "
                "FROM accounts"
            )
            rows = await cur.fetchall()
        finally:
            await db_ov.close()
        from app.ai_service import AccountAIOverride as _Ov
        n_ov = 0

        def _get(r, k: str) -> str:
            try:
                return (r[k] or "").strip() if k in r.keys() else ""
            except Exception:
                return ""

        for r in rows:
            pv = _get(r, "ai_provider_override")
            cm = _get(r, "ai_chat_model_override")
            vm = _get(r, "ai_vision_model_override")
            or_key = _get(r, "openrouter_api_key_override")
            ak = _get(r, "ai_api_key_override")
            cbu = _get(r, "custom_ai_base_url")
            cak = _get(r, "custom_ai_api_key")
            lf = bool(r["ai_local_fallback"]) if "ai_local_fallback" in r.keys() else False
            try:
                sr = json.loads(r["ai_smart_routing_json"]) if r["ai_smart_routing_json"] else {}
            except (TypeError, ValueError):
                sr = {}
            if pv or cm or vm or or_key or ak or cbu or cak or lf or sr:
                ai_service.set_account_override(
                    r["id"],
                    _Ov(provider=pv, chat_model=cm, vision_model=vm,
                        openrouter_key=or_key, api_key=ak,
                        custom_base_url=cbu, custom_api_key=cak,
                        local_fallback=lf, smart_routing=sr),
                )
                n_ov += 1
        if n_ov:
            logger.info("AI per-account override: загружено для %d аккаунтов", n_ov)
    except Exception:
        logger.warning("AI override restore error: %s", traceback.format_exc())

    # §25.4: кастомные провайдеры из БД → кэш ai_service
    try:
        db3 = await get_db()
        try:
            cur3 = await db3.execute("SELECT name, base_url, api_key, models, enabled FROM custom_providers")
            ai_service.set_custom_providers([dict(r) for r in await cur3.fetchall()])
        finally:
            await db3.close()
        if ai_service.custom_provider_names():
            logger.info("Custom AI providers: %s", ", ".join(ai_service.custom_provider_names()))
    except Exception:
        logger.warning("custom providers load error: %s", traceback.format_exc())


# ── Wiring ──

def wire_components(
    bot_manager: TwitchBotManager,
    chat_analyzer: ChatAnalyzer,
    *,
    broadcast_log_cb=None,
    broadcast_ai_log_cb=None,
    health_broadcast=None,
) -> None:
    """Подключает колбэки менеджера, анализатора и AI-логов."""
    bot_manager.set_log_callback(log_message)
    bot_manager.on_message(chat_analyzer.on_message)
    bot_manager.set_health_callback(make_health_logger(health_broadcast))
    if broadcast_ai_log_cb:
        set_ai_log_callback(broadcast_ai_log_cb)
    # broadcast_log_cb используется WS-роутами панели напрямую (routes.py).


# ── Подключение аккаунтов ──

async def start_account(
    bot_manager: TwitchBotManager,
    chat_analyzer: ChatAnalyzer,
    account: dict[str, Any],
    channels: list[str],
    *,
    eventsub_manager=None,
    desired: bool = True,
) -> bool:
    """Запускает одного бота (+EventSub) и регистрирует желаемое состояние."""
    proxy = account.get("proxy", "") if isinstance(account, dict) else ""
    if not isinstance(account, dict):
        # sqlite3.Row → dict
        account = dict(account)
        proxy = account.get("proxy", "") or ""
    ok = await bot_manager.start_bot(
        account["id"], account["nickname"], account["token"], channels, proxy=proxy or "",
    )
    if ok:
        if chat_analyzer is not None:
            chat_analyzer.set_account_token(account["id"], decrypt_token(account["token"]))
            # B2/B1 (REWORK_PLAN): персист-настройки анализатора из БД + «Только наблюдает»
            # из accounts — единый источник (иначе гейт жил только в памяти).
            try:
                await chat_analyzer.load_persisted_settings(account["id"])
                chat_analyzer.update_settings(
                    account["id"], {"observation_only": bool(account.get("observation_only"))}
                )
            except Exception as exc:
                logger.debug("analyzer settings hydrate #%s: %s", account["id"], exc)
        if desired:
            bot_manager.set_desired(
                account["id"],
                {
                    "nickname": account["nickname"],
                    "token": account["token"],
                    "channels": list(channels),
                    "proxy": proxy or "",
                },
            )
        if eventsub_manager is not None:
            try:
                if account.get("eventsub_enabled"):
                    await eventsub_manager.start_for_account(
                        account["id"], account["nickname"],
                        decrypt_token(account["token"]), channels,
                    )
            except Exception as exc:
                logger.warning("EventSub start error: %s", exc)
    return ok


async def autoconnect_enabled_bots(
    bot_manager: TwitchBotManager,
    chat_analyzer: ChatAnalyzer,
    *,
    eventsub_manager=None,
    only_account_id: int | None = None,
) -> int:
    """Подключает включённых ботов с каналами. Возвращает число запущенных.

    Используется панелью (autoconnect=1 в настройках) и standalone-режимом.
    """
    db = await get_db()
    try:
        if only_account_id is not None:
            cursor = await db.execute("SELECT * FROM accounts WHERE id = ? AND enabled = 1", (only_account_id,))
        else:
            cursor = await db.execute("SELECT * FROM accounts WHERE enabled = 1")
        accounts = await cursor.fetchall()
    finally:
        await db.close()

    started = 0
    for acc in accounts:
        db2 = await get_db()
        try:
            cur2 = await db2.execute(
                "SELECT channel_name FROM channels WHERE account_id = ? AND enabled = 1", (acc["id"],)
            )
            channels = [r["channel_name"] for r in await cur2.fetchall()]
        finally:
            await db2.close()
        if not channels:
            continue
        if await start_account(bot_manager, chat_analyzer, dict(acc), channels,
                               eventsub_manager=eventsub_manager):
            started += 1
            logger.info("Авто-подключение: [%s] → %s", acc["nickname"], ", ".join(channels))
    return started


__all__ = [
    "log_message",
    "make_health_logger",
    "load_ai_state",
    "wire_components",
    "start_account",
    "autoconnect_enabled_bots",
]
