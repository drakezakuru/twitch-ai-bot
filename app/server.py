"""FastAPI сервер — точка входа."""

import asyncio
import logging
import os
import random
import time
import traceback
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI
import json

from fastapi.staticfiles import StaticFiles

from app.ai_service import AIService, set_ai_log_callback, ai_log
from app.api_errors import install_api_error_handlers
from app.bot_manager import TwitchBotManager
from app.chat_analyzer import ChatAnalyzer
from app.database import init_db, get_db, get_setting, close_db
from app.eventsub import EventSubManager
from app.routes import router, ws_router, broadcast_log, broadcast_ai_log, actor_middleware
from app.widget_channel_scope import widget_channel_middleware
from app import engagement as engagement_mod
from app.security import (
    credential_storage_mode,
    decrypt_token,
    encrypt_token,
    ensure_credential_storage_policy,
    is_auth_enabled,
    is_encryption_enabled,
)
from app import stream_vision as _sv_module
from app import channel_points_tts as _channel_points_tts  # P4: TTS за баллы канала
from app import brain_preview as _brain_preview  # P3: Мозг бота X + промпт-инспектор
from app.stream_vision import StreamVisionManager
from app import twitch_credentials
from app.twitch_helix import is_helix_configured, refresh_oauth_token
from app import summarizer as _summarizer
from app import user_memory as _user_memory
from app import affinity_rules as _affinity_rules  # BRAIN_PLAN §7
from app import brain_routes as _brain_routes  # BRAIN_PLAN §3/§6 (one-line include)

load_dotenv()

logger = logging.getLogger(__name__)

bot_manager = TwitchBotManager()
ai_service = AIService()
chat_analyzer = ChatAnalyzer(ai=ai_service, send_fn=bot_manager.send_message)
eventsub_manager = EventSubManager()
# Stream Vision подсоединяется к ai_log в lifespan, после set_ai_log_callback.
# chat_cb позволяет vision→chat: бот комментирует яркие моменты прямо в чат.
stream_vision_manager = StreamVisionManager(
    ai_service, chat_cb=bot_manager.send_message,
    # v10.4.8: vision-промпт обогащается категорией/названием стрима из Helix.
    # Токен берём из chat_analyzer (он уже хранит OAuth-токены аккаунтов).
    token_provider=lambda aid: chat_analyzer._account_token.get(aid) or None,  # noqa: SLF001
)
# v10.4: регистрируем менеджер в модуле, чтобы chat_analyzer мог получать last_observation
# без циклического импорта server.py.
_sv_module.set_manager(stream_vision_manager)

# PLAN §9g: реальный поток чата → трекер скорости clip-detector.
from app.routes import register_clip_rate_hook  # noqa: E402

register_clip_rate_hook(chat_analyzer)


async def bot_health_loop() -> None:
    """Publish state transitions so the panel can surface dropped bots."""
    previous: dict[int, bool] = {}
    while True:
        try:
            current = {int(aid): bool(status.get("connected")) for aid, status in bot_manager.get_all_statuses().items()}
            for account_id, connected in {**{aid: False for aid in previous if aid not in current}, **current}.items():
                if account_id in previous and previous[account_id] != connected:
                    await broadcast_log({
                        "type": "health_alert",
                        "account_id": account_id,
                        "status": "connected" if connected else "disconnected",
                        "detail": "Bot connection restored" if connected else "Bot connection lost",
                    })
            previous = current
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            return
        except Exception:
            logger.warning("Health-check error", exc_info=True)
            await asyncio.sleep(10)


async def _cancel_tasks(*tasks: asyncio.Task | None) -> None:
    owned = [task for task in tasks if task is not None]
    for task in owned:
        if not task.done():
            task.cancel()
    if owned:
        await asyncio.gather(*owned, return_exceptions=True)


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

        # When enabled for an account, message content adjusts chat affinity
        # via BRAIN_PLAN §7 rules (humor/support up, conflict down, default +1)
        # without overwriting the streamer's manual contact value.
        if not is_bot:
            try:
                await _affinity_rules.apply_message_affinity(
                    account_id, channel, author, message
                )
            except Exception:
                logger.debug("affinity auto-adjust failed", exc_info=True)

        # §9.3 WIDGETS_PLAN: emoji-leaderboard — счётчик эмодзи за сегодня.
        try:
            from app.widgets import on_chat_emoji as _on_chat_emoji
            await _on_chat_emoji(author, message)
        except Exception:
            pass

        from app.chat_overlay_routes import chat_event_payload
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
    except Exception as exc:
        logger.error("Ошибка записи лога: %s", exc)


_sched_next: dict[int, float] = {}  # schedule_id -> next_send_time


async def scheduled_messages_loop() -> None:
    """Background loop that sends scheduled messages at random intervals."""
    while True:
        try:
            await asyncio.sleep(10)
            db = await get_db()
            try:
                cursor = await db.execute(
                    "SELECT * FROM scheduled_messages WHERE enabled = 1"
                )
                schedules = await cursor.fetchall()
            finally:
                await db.close()

            now = asyncio.get_event_loop().time()
            for sched in schedules:
                sid = sched["id"]
                if sid not in _sched_next:
                    delay = random.randint(sched["min_interval"], sched["max_interval"]) * 60
                    _sched_next[sid] = now + delay
                    continue

                if now < _sched_next[sid]:
                    continue

                # Time to send
                msg = sched["message"]
                if sched["use_ai"] and sched["ai_prompt"]:
                    try:
                        msg = await ai_service.generate_text(sched["ai_prompt"])
                    except Exception as exc:
                        logger.warning("Scheduled AI error: %s", exc)

                if msg:
                    await bot_manager.send_message(sched["account_id"], sched["channel"], msg)
                    logger.info("Scheduled [%d] -> #%s: %s", sched["account_id"], sched["channel"], msg[:60])

                # Next random delay
                delay = random.randint(sched["min_interval"], sched["max_interval"]) * 60
                _sched_next[sid] = now + delay

        except asyncio.CancelledError:
            break
        except Exception:
            logger.warning("Scheduler error: %s", traceback.format_exc())
            await asyncio.sleep(30)


# ============== Feature 2: Auto-refresh background task ==============

async def token_refresh_loop() -> None:
    """Каждые 10 минут обновляет refreshable-токены перед истечением."""
    while True:
        try:
            enabled = await get_setting("auto_refresh_tokens", "1")
            if enabled != "1" or not is_helix_configured():
                await asyncio.sleep(60)
                continue

            now_ts = int(time.time())
            db = await get_db()
            try:
                cursor = await db.execute(
                    "SELECT id, nickname, refresh_token, token_expires_at FROM accounts "
                    "WHERE refresh_token != '' AND refresh_token IS NOT NULL"
                )
                rows = await cursor.fetchall()
            finally:
                await db.close()

            for row in rows:
                expires_at = int(row["token_expires_at"] or 0)
                # Если expires_at не задан или истекает в течение 30 минут → refresh
                if expires_at and expires_at - now_ts > 1800:
                    continue
                refresh = decrypt_token(row["refresh_token"] or "")
                if not refresh:
                    continue
                try:
                    result = await refresh_oauth_token(refresh)
                    if not result:
                        logger.warning("[%s] refresh_token устарел или Twitch отклонил", row["nickname"])
                        continue
                    new_access = result.get("access_token", "")
                    if not new_access:
                        logger.warning("[%s] Twitch не вернул access_token при refresh", row["nickname"])
                        continue
                    new_refresh = result.get("refresh_token", refresh)
                    expires_in = int(result.get("expires_in", 0))
                    new_expires = now_ts + expires_in if expires_in else 0
                    db2 = await get_db()
                    try:
                        await db2.execute(
                            "UPDATE accounts SET token = ?, refresh_token = ?, token_expires_at = ? WHERE id = ?",
                            (encrypt_token(new_access), encrypt_token(new_refresh), new_expires, row["id"]),
                        )
                        await db2.commit()
                    finally:
                        await db2.close()
                    await ai_log("token_refresh", f"[{row['nickname']}] токен обновлён, истекает через {expires_in}с", row["id"], "")
                    logger.info("[%s] Токен обновлён, expires_in=%d", row["nickname"], expires_in)
                except Exception as exc:
                    logger.warning("[%s] refresh exception: %s", row["nickname"], exc)

            await asyncio.sleep(600)  # 10 минут
        except asyncio.CancelledError:
            break
        except Exception:
            logger.warning("Token refresh loop error: %s", traceback.format_exc())
            await asyncio.sleep(120)


# ============== v16 BRAIN_PLAN §4 + §1 background loops ==============


async def summarizer_live_loop() -> None:
    """Каждые 5 минут проверяет активные каналы и пишет live-сводку за последние 30 мин.

    ВАЖНО: не стартует, если в настройках summarizer_live_enabled=False.
    Кешируем «когда последний раз считали» в памяти — чтобы не считать каждый цикл.
    """
    last_run_key: dict[tuple[int, str], float] = {}
    LIVE_INTERVAL_SEC = 30 * 60  # 30 мин между сводками на один канал
    TICK = 5 * 60               # 5 мин между опросами
    while True:
        try:
            await asyncio.sleep(TICK)
            now = time.time()
            db = await get_db()
            try:
                cursor = await db.execute(
                    "SELECT account_id, channel_name FROM channels WHERE enabled = 1"
                )
                channels = [dict(r) for r in await cursor.fetchall()]
            finally:
                await db.close()
            for ch in channels:
                aid = int(ch["account_id"])
                cname = (ch["channel_name"] or "").strip().lower().lstrip("#")
                if not cname:
                    continue
                s = chat_analyzer.get_settings(aid)
                # §2.3: per-channel override live-сводок с наследованием от бота
                try:
                    s = await chat_analyzer._merged_settings(aid, cname, s)
                except Exception:
                    pass
                if not s.get("summarizer_live_enabled"):
                    continue
                key = (aid, cname)
                if now - last_run_key.get(key, 0.0) < LIVE_INTERVAL_SEC:
                    continue
                end = datetime.now(timezone.utc)
                start = end - timedelta(seconds=LIVE_INTERVAL_SEC)
                try:
                    msgs = await _summarizer._fetch_chat_window(
                        aid, cname, start, end, limit=200
                    )
                except Exception:
                    continue
                if not msgs:
                    continue
                digest = ""
                try:
                    prompt = _summarizer._build_digest_prompt(
                        msgs, lang=(s.get("summarizer_live_lang") or "ru")
                    )
                    if prompt:
                        digest = await ai_service.generate_text(
                            prompt=prompt,
                            system="Краткая сводка окна чата.",
                            account_id=aid,
                            channel=cname,
                            temperature=0.2,
                        )
                except Exception as exc:
                    logger.debug("live digest error: %s", exc)
                if digest:
                    try:
                        await _summarizer.write_live_summary(aid, cname, start, end, digest)
                    except Exception:
                        pass
                last_run_key[key] = now
        except asyncio.CancelledError:
            break
        except Exception:
            logger.warning("summarizer_live_loop error: %s", traceback.format_exc())
            await asyncio.sleep(60)


async def memory_gc_loop() -> None:
    """Каждые 6 часов чистит просроченные факты (TTL/expires_at)."""
    while True:
        try:
            await asyncio.sleep(6 * 3600)
            n = await _user_memory.gc_expired_facts()
            if n:
                logger.info("memory_gc: удалено просроченных фактов: %d", n)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.warning("memory_gc_loop error: %s", traceback.format_exc())
            await asyncio.sleep(600)


# ============== v10.4.3: raid-follow handler ==============

# Активные сессии «бот идёт за рейдом»: (account_id, target_channel) → asyncio.Task.
# Если приходит ещё один рейд в тот же канал — продлеваем существующий таймер.
_raid_follow_tasks: dict[tuple[int, str], asyncio.Task] = {}
# Длительность активной сессии в секундах до автоматического выхода
# (для отображения в UI / тестах).
_raid_follow_until: dict[tuple[int, str], float] = {}
_event_tasks: set[asyncio.Task] = set()


def _event_task_done(task: asyncio.Task) -> None:
    _event_tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("Event background task %s failed", task.get_name(), exc_info=exc)


def _spawn_event_task(coro, *, name: str) -> asyncio.Task:
    task = asyncio.create_task(coro, name=name)
    _event_tasks.add(task)
    task.add_done_callback(_event_task_done)
    return task


async def _cancel_event_tasks() -> None:
    while _event_tasks:
        current = tuple(_event_tasks)
        _event_tasks.difference_update(current)
        await _cancel_tasks(*current)


async def _handle_raid_follow(account_id: int, from_channel: str, payload: dict) -> None:
    """v10.4.3: реализует «бот следует за рейдом».

    - Читает per-account настройки `raid_follow_enabled`, min/max минут активности,
      нужно ли выходить из канала после окончания таймера.
    - Если включено и `from_broadcaster_user_login == from_channel` (то есть это
      исходящий рейд этого канала) — джойнит target-канал, активирует overlay
      «raid-active» (boosted auto_chat) в ChatAnalyzer на N минут (random в диапазоне),
      и после таймера опционально парт-канал.

    Если бот уже в target-канале — НЕ парт-канал по окончании, только убираем overlay.
    """
    target = (payload.get("to_broadcaster_user_login")
              or payload.get("to_broadcaster_user_name") or "").lower()
    origin = (payload.get("from_broadcaster_user_login")
              or payload.get("from_broadcaster_user_name") or "").lower()
    if not target:
        return
    # Бот реагирует только на исходящие рейды этого канала.
    if origin and origin != (from_channel or "").lower():
        return

    enabled, min_min, max_min, part_after = await _load_raid_follow_settings(account_id)
    if not enabled:
        return

    if min_min == max_min:
        duration_min = max(1, min_min)
    else:
        duration_min = max(1, random.randint(min_min, max_min))
    duration_sec = duration_min * 60

    key = (account_id, target)
    prev = _raid_follow_tasks.get(key)
    if prev and not prev.done():
        # Продлеваем существующую сессию вместо запуска новой.
        new_until = time.time() + duration_sec
        if new_until > _raid_follow_until.get(key, 0.0):
            _raid_follow_until[key] = new_until
        await ai_log(
            "raid_follow",
            f"⚡ Уже активничаю в #{target}, продлеваю до {duration_min} мин",
            account_id, from_channel,
        )
        return

    _raid_follow_until[key] = time.time() + duration_sec
    task = _spawn_event_task(
        _raid_follow_runner(account_id, from_channel, target, duration_sec, part_after),
        name=f"raid-follow-{account_id}-{target}",
    )
    _raid_follow_tasks[key] = task


async def _load_raid_follow_settings(account_id: int) -> tuple[bool, int, int, bool]:
    """Считывает (enabled, min_min, max_min, part_after) из таблицы accounts.
    Дефолты: off, 10..60, part_after=True.
    """
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT raid_follow_enabled, raid_follow_active_min, raid_follow_active_max, raid_follow_part_after "
            "FROM accounts WHERE id = ?",
            (account_id,),
        )
        row = await cursor.fetchone()
    finally:
        await db.close()
    if not row:
        return False, 10, 60, True
    enabled = bool(row["raid_follow_enabled"]) if "raid_follow_enabled" in row.keys() else False
    min_min = int(row["raid_follow_active_min"] or 10) if "raid_follow_active_min" in row.keys() else 10
    max_min = int(row["raid_follow_active_max"] or 60) if "raid_follow_active_max" in row.keys() else 60
    part_after = bool(row["raid_follow_part_after"]) if "raid_follow_part_after" in row.keys() else True
    if min_min > max_min:
        min_min, max_min = max_min, min_min
    return enabled, max(1, min_min), max(1, max_min), part_after


async def _raid_follow_runner(
    account_id: int, from_channel: str, target: str, duration_sec: int, part_after: bool
) -> None:
    """Основная фоновая корутина рейд-перехода:
    - join target (если бот ещё не там);
    - включает chat_analyzer raid_active overlay на duration_sec;
    - спит до окончания таймера (с учётом возможного продления);
    - выключает overlay;
    - парт target если part_after и бот сам туда зашёл.
    """
    key = (account_id, target)
    status = bot_manager.get_status(account_id)
    if not status.get("connected"):
        await ai_log("raid_follow", f"Бот #{account_id} не онлайн — пропускаю переход", account_id, from_channel)
        _raid_follow_tasks.pop(key, None)
        _raid_follow_until.pop(key, None)
        return

    already_in = target in {(c or "").lstrip("#").lower() for c in status.get("channels", [])}
    joined_by_us = False
    if not already_in:
        ok = await bot_manager.join_channel(account_id, target)
        joined_by_us = bool(ok)
        await ai_log(
            "raid_follow",
            f"➡️ Перешёл за рейдом в #{target} (активничаю ~{duration_sec // 60} мин)",
            account_id, target,
        )
    else:
        await ai_log(
            "raid_follow",
            f"Уже сидел в #{target}, активирую boost-режим на ~{duration_sec // 60} мин",
            account_id, target,
        )

    # Активируем overlay в chat_analyzer.
    until_ts = _raid_follow_until.get(key, time.time() + duration_sec)
    try:
        chat_analyzer.set_raid_active(account_id, target, until_ts)
    except Exception as exc:
        logger.debug("set_raid_active failed: %s", exc)

    # Ждём окончания (учитывая возможные продления — sleep до _raid_follow_until[key]).
    while True:
        until_now = _raid_follow_until.get(key, 0.0)
        delta = until_now - time.time()
        if delta <= 0:
            break
        try:
            await asyncio.sleep(min(30.0, delta))
        except asyncio.CancelledError:
            break

    try:
        chat_analyzer.clear_raid_active(account_id, target)
    except Exception as exc:
        logger.debug("clear_raid_active failed: %s", exc)

    if joined_by_us and part_after:
        await bot_manager.leave_channel(account_id, target)
        await ai_log(
            "raid_follow",
            f"⏹ Выхожу из #{target} (raid-follow таймер истёк)",
            account_id, target,
        )
    else:
        await ai_log(
            "raid_follow",
            f"Boost-режим в #{target} завершён",
            account_id, target,
        )
    _raid_follow_tasks.pop(key, None)
    _raid_follow_until.pop(key, None)


# ============== v10.4.5 Wave 2: Predictions / Polls auto-vote ==============

async def _handle_predictions_polls(account_id: int, event_type: str, channel: str, payload: dict) -> None:
    """v10.4.5: AI выбирает вариант в твич-голосовании или прогнозе.

    Учитывает per-account `predictions_polls_autovote_enabled`. По умолчанию выключено.
    Если `predictions_polls_dry_run` — только логируем без чата.
    """
    from app.chat_analyzer import chat_analyzer
    from app.predictions_polls import decide_vote, format_decision_for_chat, extract_choices, extract_question

    s = chat_analyzer.get_settings(account_id)
    if not s.get("predictions_polls_autovote_enabled"):
        return
    question = extract_question(payload)
    choices = extract_choices(payload)
    if not question or not choices:
        await ai_log(
            "predictions_polls",
            f"[{event_type}] payload без question/choices — пропускаем",
            account_id, channel,
        )
        return
    try:
        decision = await decide_vote(question, choices, channel=channel)
    except Exception as exc:
        logger.debug("decide_vote error: %s", exc)
        return
    dry = bool(s.get("predictions_polls_dry_run", True))
    msg = format_decision_for_chat(event_type, decision, dry_run=dry)
    await ai_log(
        "predictions_polls",
        f"[{event_type}] {msg}",
        account_id, channel,
    )
    if not dry and chat_analyzer.send_fn:
        try:
            await chat_analyzer.send_fn(account_id, channel, msg)
        except Exception as exc:
            logger.debug("predictions_polls send error: %s", exc)


# ============== Feature 3: EventSub event handler ==============

async def _moderation_eventsub_message(account_id: int, channel: str, payload: dict) -> None:
    """v14 MODERATION_PLAN §3: прогоняет message-событие EventSub через
    движок модерации (правила + built-in + антиспам) и пишет журнал."""
    from app import moderation as _mod
    user = (payload.get("chatter_user_login") or payload.get("chatter_user_name") or "")
    msg = payload.get("message")
    text = msg.get("text", "") if isinstance(msg, dict) else str(msg or "")
    if not text:
        return
    verdicts, hits = await _mod.check_incoming(account_id, channel, user, text)
    if verdicts or hits:
        await ai_log(
            "moderation",
            f"EventSub-модерация: {user} — {_mod.summarize(verdicts, hits)} | {text[:100]}",
            account_id, channel,
        )


async def on_eventsub_event(account_id: int, event_type: str, channel: str, payload: dict) -> None:
    """Принимает событие из EventSub, ищет реакцию в event_responses, отвечает в чат."""
    if event_type in {"stream.online", "stream.offline"}:
        from app.director import handle_stream_lifecycle
        await handle_stream_lifecycle(channel, event_type == "stream.online")
    if event_type in {"channel.follow", "channel.subscribe", "channel.cheer", "channel.raid"}:
        from app.director import notify_stream_event
        await notify_stream_event(channel, event_type, verified=True)
    from app.widget_channel_scope import remember_channel_identity
    channel_id = (payload.get("broadcaster_user_id")
                  or payload.get("from_broadcaster_user_id")
                  or payload.get("to_broadcaster_user_id") or "")
    await remember_channel_identity(channel, channel_id)

    # Маппинг event_type → внутренний type для таблицы event_responses
    mapping = {
        "channel.follow": "follow",
        "channel.subscribe": "subscribe",
        "channel.raid": "raid",
        "channel.cheer": "cheer",
        "channel.channel_points_custom_reward_redemption.add": "redemption",
    }

    # v10.4.5: predictions / polls — auto-vote (без записи в event_responses).
    if event_type in ("channel.poll.begin", "channel.prediction.begin"):
        try:
            _spawn_event_task(
                _handle_predictions_polls(account_id, event_type, channel, payload),
                name=f"event-autovote-{account_id}",
            )
        except Exception as exc:
            logger.debug("predictions-polls scheduling error: %s", exc)
        return

    # v14 MODERATION_PLAN §3: message-события EventSub (если включены)
    # тоже проходят движок модерации.
    if event_type == "channel.chat.message":
        try:
            await _moderation_eventsub_message(account_id, channel, payload)
        except Exception as exc:
            logger.warning("eventsub moderation error: %s", exc)
        return

    internal = mapping.get(event_type)
    from app.widget_bus import claim_event as _claim_widget_event, event_projection_id
    project_to_widgets = _claim_widget_event(channel, event_projection_id(event_type, payload))

    # P4 PLAN.md: TTS за баллы канала — redemption с настроенным reward
    # озвучивается через TTSEngine (app/channel_points_tts.py).
    if project_to_widgets and event_type == "channel.channel_points_custom_reward_redemption.add":
        try:
            _spawn_event_task(
                _channel_points_tts.handle_redemption(account_id, channel, payload),
                name=f"event-reward-tts-{account_id}",
            )
        except Exception as exc:
            logger.debug("channel-points-tts scheduling error: %s", exc)
        try:
            from app.song_request_service import handle_channel_points
            _spawn_event_task(
                handle_channel_points(account_id, channel, payload),
                name=f"event-song-request-{account_id}",
            )
        except Exception as exc:
            logger.debug("song-request redemption scheduling error: %s", exc)

    if not internal:
        return
    user = (payload.get("user_login") or payload.get("user_name")
            or payload.get("from_broadcaster_user_login") or "")
    await ai_log("eventsub", f"[{event_type}] {user} в #{channel}", account_id, channel)

    # §1+§3 WIDGETS_PLAN: підняти widget_bus.duck_start для подій, які мають
    # «заглушити» TTS (саб, чір/бітс, рейд, редемпшн). Тривалість і склад
    # типів подій керуються через tts_duck_settings (якщо є); якщо таблиці
    # ще немає (перший запуск після міграції) — дефолт 8000мс.
    try:
        from app.widget_bus import duck_start as _duck_start
        duration_ms = await _resolve_duck_duration(internal)
        if project_to_widgets and duration_ms > 0:
            await _duck_start(source=internal, reason=internal,
                              channel=channel, duration_ms=duration_ms, hard_mute=False)
    except Exception as exc:
        logger.debug("widget_bus duck_start failed (non-fatal): %s", exc)

    # v10.4.3: follow-raid. Когда `from_broadcaster_user_login == channel`,
    # бот переходит за рейдом в target и активничает там min..max минут.
    if event_type == "channel.raid":
        try:
            _spawn_event_task(
                _handle_raid_follow(account_id, channel, payload),
                name=f"event-raid-follow-{account_id}",
            )
        except Exception as exc:
            logger.warning("raid-follow scheduling error: %s", exc)

    # v10.4.5 (widgets): авто-инкремент sub-goal виджета на channel.subscribe.
    if project_to_widgets and event_type == "channel.subscribe":
        try:
            from app.widgets import on_subscribe_event
            from app.widget_bindings import has_sub_goal_subscribe_binding
            await on_subscribe_event(
                increment_sub_goal=not await has_sub_goal_subscribe_binding(account_id, channel),
                account_id=account_id,
                channel=channel,
            )
        except Exception as exc:
            logger.debug("[widgets] sub-goal increment failed: %s", exc)

    # v10.4.7 (widgets): centralized recent_events для ticker / mascot.
    if project_to_widgets and event_type in ("channel.follow", "channel.subscribe",
                      "channel.cheer", "channel.raid"):
        try:
            from app.widgets import on_stream_event
            amount = 0
            if event_type == "channel.cheer":
                amount = int(payload.get("bits") or 0)
            elif event_type == "channel.raid":
                amount = int(payload.get("viewers") or 0)
            await on_stream_event(
                internal, user, amount, account_id=account_id, channel=channel,
            )
        except Exception as exc:
            logger.debug("[widgets] on_stream_event failed: %s", exc)

    # §11.3 WIDGETS_PLAN: биндинги виджетов — eventsub-события → действия
    # (sub-goal +1, счётчики и т.д.). Список биндингов — панель, вкладка Виджеты.
    if project_to_widgets and event_type in ("channel.follow", "channel.subscribe",
                      "channel.cheer", "channel.raid"):
        try:
            from app.widget_bindings import handle_eventsub_event as _bindings_event
            ev_amount = 0
            if event_type == "channel.cheer":
                ev_amount = int(payload.get("bits") or 0)
            elif event_type == "channel.raid":
                ev_amount = int(payload.get("viewers") or 0)
            _spawn_event_task(
                _bindings_event(account_id, event_type, channel, user, ev_amount),
                name=f"event-widget-binding-{account_id}",
            )
        except Exception as exc:
            logger.debug("[widgets] bindings eventsub failed: %s", exc)

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM event_responses WHERE account_id = ? AND event_type = ? AND enabled = 1",
            (account_id, internal),
        )
        responses = await cursor.fetchall()
    finally:
        await db.close()

    for resp in responses:
        chance = int(resp["chance"] or 100)
        if random.randint(1, 100) > chance:
            continue
        if resp["use_ai"]:
            prompt = f"Событие {internal} от {user} в чате #{channel}. Напиши короткий ответ (10-15 слов)."
            text = await ai_service.generate_text(prompt, account_id=account_id, channel=channel)
        else:
            text = (resp["response"] or "").replace("{user}", user).replace("{channel}", channel)
        if text:
            await bot_manager.send_message(account_id, channel, text)


_DEFAULT_DUCK_DURATION_MS = 8000


async def _resolve_duck_duration(event_kind: str) -> int:
    """Повертає тривалість duck-вікна для події (мс), або 0 якщо вимкнено.

    Використовує спільну таблицю ``tts_duck_settings`` з admin endpoint'у
    ``/api/tts/duck-settings``. Якщо таблиці/рядка немає — повертає
    дефолт 8000мс.
    """
    try:
        from app.database import get_db
        from app.routes import _ensure_duck_settings as _ensure
        db = await get_db()
        try:
            await _ensure(db)
            cur = await db.execute(
                "SELECT enabled, duration_ms FROM tts_duck_settings WHERE event_kind = ?",
                (event_kind,),
            )
            row = await cur.fetchone()
        finally:
            await db.close()
        if not row:
            return _DEFAULT_DUCK_DURATION_MS
        return int(row["duration_ms"] or 0) if int(row["enabled"] or 0) else 0
    except Exception:
        return _DEFAULT_DUCK_DURATION_MS

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    _sched_task: asyncio.Task | None = None
    _refresh_task: asyncio.Task | None = None
    _engagement_task: asyncio.Task | None = None
    _health_task: asyncio.Task | None = None
    _watchdog_task: asyncio.Task | None = None
    _summarizer_live_task: asyncio.Task | None = None
    _memory_gc_task: asyncio.Task | None = None
    _maintenance_task: asyncio.Task | None = None
    _np_sources_task: asyncio.Task | None = None
    _donation_task: asyncio.Task | None = None
    _blur_task: asyncio.Task | None = None
    _proxy_clean_task: asyncio.Task | None = None
    _dead_air_task: asyncio.Task | None = None
    try:
        ensure_credential_storage_policy()
        await init_db()

        # §S2 STREAM_PLAN: схема Beep Guard — после init_db (см. комментарий
        # у импорта: module-level create_task вызывал flaky db-lock в тестах).
        try:
            from app.beep_guard import ensure_schema as _beep_ensure
            await _beep_ensure()
        except Exception as exc:
            logger.warning("beep_guard schema init failed: %s", exc)

        # Загружаем сохранённые в БД Twitch credentials (Client ID / Secret).
        # Если в БД пусто — fallback на TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET из .env.
        await twitch_credentials.load_from_db()

        # Загружаем AI-настройки из БД
        db = await get_db()
        try:
            cursor = await db.execute("SELECT key, value FROM settings WHERE key LIKE 'ai_%'")
            rows = await cursor.fetchall()
            if rows:
                ai_cfg = {}
                for row in rows:
                    k = row["key"].replace("ai_", "", 1)
                    from app.security import decrypt_token
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

        bot_manager.set_log_callback(log_message)
        bot_manager.on_message(chat_analyzer.on_message)

        # Health-события (план §5.1): смена состояния бота пишется в per-bot лог
        async def on_bot_health(account_id: int, nickname: str, old_state: str, new_state: str, error: str) -> None:
            from app.bot_logs import log_per_bot
            level = {"error": "error", "connecting": "warning"}.get(new_state, "info")
            msg = f"Health: {old_state} → {new_state}" + (f" ({error})" if error else "")
            await log_per_bot(account_id, "", "system", msg, level=level)
            await broadcast_log({"type": "health", "account_id": account_id, "nickname": nickname,
                                 "state": new_state, "error": error})

        bot_manager.set_health_callback(on_bot_health)
        eventsub_manager.set_callback(on_eventsub_event)
        set_ai_log_callback(broadcast_ai_log)
        from app.director import install_production_adapters, scheduler as _director_scheduler
        install_production_adapters(ai_service, stream_vision_manager, bot_manager)
        await _director_scheduler.start()
        # Stream Vision эмитит события через тот же ai_log канал —
        # они появляются в "AI Мозге" вместе с обычными vision/think событиями.
        stream_vision_manager.log_cb = broadcast_ai_log
        logger.info("=== Twitch AI Bot Panel запущена ===")
        logger.info("AI-провайдер: %s", ai_service.provider)
        logger.info("Анализ чата: активен")
        logger.info("Безопасность: auth=%s, credential_storage=%s, helix=%s",
                    is_auth_enabled(), credential_storage_mode(), is_helix_configured())
        logger.info("Откройте http://localhost:8000 в браузере")

        # Авто-подключение если включено
        try:
            db2 = await get_db()
            try:
                cursor = await db2.execute("SELECT value FROM settings WHERE key = 'autoconnect'")
                row = await cursor.fetchone()
                if row and row["value"] == "1":
                    cursor = await db2.execute("SELECT * FROM accounts WHERE enabled = 1")
                    accounts = await cursor.fetchall()
                    for acc in accounts:
                        cur2 = await db2.execute(
                            "SELECT channel_name FROM channels WHERE account_id = ? AND enabled = 1", (acc["id"],)
                        )
                        channels = [r["channel_name"] for r in await cur2.fetchall()]
                        if not channels:
                            continue
                        proxy = acc["proxy"] if "proxy" in acc.keys() else ""
                        ok = await bot_manager.start_bot(
                            acc["id"], acc["nickname"], acc["token"], channels, proxy=proxy or "",
                        )
                        if ok:
                            bot_manager.set_desired(
                                acc["id"],
                                {
                                    "nickname": acc["nickname"],
                                    "token": acc["token"],
                                    "channels": channels,
                                    "proxy": proxy or "",
                                },
                            )
                            chat_analyzer.set_account_token(acc["id"], decrypt_token(acc["token"]))
                            try:
                                if "eventsub_enabled" in acc.keys() and acc["eventsub_enabled"]:
                                    await eventsub_manager.start_for_account(
                                        acc["id"], acc["nickname"], decrypt_token(acc["token"]), channels,
                                    )
                            except Exception as exc:
                                logger.warning("EventSub auto-start error: %s", exc)
                    logger.info("Авто-подключение: запущено %d ботов", len(accounts))
            finally:
                await db2.close()
        except Exception:
            logger.warning("Ошибка авто-подключения: %s", traceback.format_exc())

        # Q34c: восстановить распределённые заходы пачек после рестарта панели.
        try:
            from app.bot_packs import ensure_join_worker
            await ensure_join_worker()
            logger.info("Bot pack join worker: запущен")
        except Exception as exc:
            logger.warning("Bot pack join worker start failed: %s", exc)

        # Запуск планировщика расписания
        _sched_task = asyncio.create_task(scheduled_messages_loop())
        logger.info("Планировщик расписания: запущен")

        # Feature 2: фоновый refresh-токенов
        _refresh_task = asyncio.create_task(token_refresh_loop())
        logger.info("Token refresh loop: запущен")

        # v10.3 4B: engagement-tracking фон-задача
        _engagement_task = asyncio.create_task(engagement_mod.engagement_loop())
        logger.info("Engagement loop: запущен")
        _health_task = asyncio.create_task(bot_health_loop())
        _watchdog_task = asyncio.create_task(bot_manager.watchdog_loop(interval=15.0))
        logger.info("Watchdog автовосстановления ботов: запущен")

        # v16 BRAIN_PLAN §4: live summary + §1: memory GC
        try:
            await _summarizer.ensure_tables()
        except Exception as exc:
            logger.warning("summarizer tables init: %s", exc)
        _summarizer_live_task = asyncio.create_task(summarizer_live_loop())
        logger.info("Summarizer live loop: запущен")
        _memory_gc_task = asyncio.create_task(memory_gc_loop())
        logger.info("Memory GC loop: запущен")

        # OPS_PLAN §4: retention bot_logs + авто-бэкап + PRAGMA optimize (раз в сутки)
        from app.maintenance import maintenance_loop
        _maintenance_task = asyncio.create_task(maintenance_loop())
        logger.info("Maintenance loop: запущен")

        # Автоматизация каналов: Live-триггер (автостарт ботов при начале стрима)
        from app.bot_fleet import stream_live_trigger_loop
        _fleet_live_task = asyncio.create_task(stream_live_trigger_loop(interval=45.0), name="fleet-live-trigger")
        logger.info("Fleet live trigger loop: запущен")

        # §11.2 WIDGETS_PLAN: автозаполнение виджета «Сейчас играет» (Last.fm/MPRIS)
        try:
            from app.now_playing_sources import now_playing_loop as _np_sources_loop
            _np_sources_task = asyncio.create_task(_np_sources_loop(), name="now-playing-sources")
            logger.info("Now-playing sources loop: запущен")
        except Exception as exc:
            logger.warning("now-playing sources loop start failed: %s", exc)

        # §11.4 WIDGETS_PLAN: донат-интеграции (DonatePay / DonationAlerts)
        try:
            from app.donation_integrations import integration_loop as _donation_loop
            _donation_task = asyncio.create_task(_donation_loop(), name="donation-integrations")
            logger.info("Donation integrations loop: запущен")
        except Exception as exc:
            logger.warning("donation integrations loop start failed: %s", exc)

        # §13 WIDGETS_PLAN: Blur Guard — цикл анализа кадров
        try:
            from app.blur_guard import analysis_loop as _blur_loop
            _blur_task = asyncio.create_task(_blur_loop(), name="blur-guard-analysis")
            logger.info("Blur Guard analysis loop: запущен")
        except Exception as exc:
            logger.warning("blur guard loop start failed: %s", exc)

        # Пул прокси: фоновая периодическая авто-чистка (удаление >2000мс и ошибок раз в 15 минут)
        try:
            from app.proxy_pool import proxy_pool_clean_loop
            _proxy_clean_task = asyncio.create_task(proxy_pool_clean_loop(interval=900.0), name="proxy-pool-clean")
            logger.info("Proxy pool auto-clean loop: запущен")
        except Exception as exc:
            logger.warning("proxy pool auto-clean loop start failed: %s", exc)

        # Smart Anti-Dead-Air: фоновый мониторинг затишья эфира
        async def _dead_air_monitor_loop(interval: float = 15.0) -> None:
            while True:
                try:
                    await asyncio.sleep(interval)
                    for acc_id, inst in list(bot_manager.instances.items()):
                        if inst.state != "running":
                            continue
                        for ch in inst.channels:
                            try:
                                await chat_analyzer.check_dead_air(acc_id, ch, inst.nickname)
                            except Exception as _e:
                                logger.debug("dead air check bot #%s %s: %s", acc_id, ch, _e)
                except asyncio.CancelledError:
                    break
                except Exception as _exc:
                    logger.debug("dead_air_monitor_loop error: %s", _exc)

        _dead_air_task = asyncio.create_task(_dead_air_monitor_loop(), name="anti-dead-air-loop")
        logger.info("Smart Anti-Dead-Air monitor loop: запущен")

        # Stream Vision: восстанавливаем включённые ранее каналы
        try:
            db3 = await get_db()
            try:
                cursor = await db3.execute(
                    "SELECT account_id, channel_name FROM channels "
                    "WHERE enabled = 1 AND stream_vision_enabled = 1"
                )
                rows = await cursor.fetchall()
            finally:
                await db3.close()
            for r in rows:
                await stream_vision_manager.start(r["account_id"], r["channel_name"])
            if rows:
                logger.info("Stream Vision: восстановлено %d каналов", len(rows))
        except Exception:
            logger.warning("Stream Vision restore error: %s", traceback.format_exc())

    except Exception:
        logger.critical("Ошибка инициализации:\n%s", traceback.format_exc())
        raise
    try:
        yield
    finally:
        from app.bot_check_routes import cancel_active_checks
        from app.bulk_channels_routes import cancel_active_bulk_jobs
        await cancel_active_checks()
        await cancel_active_bulk_jobs()
        await _cancel_tasks(
            _sched_task,
            _refresh_task,
            _engagement_task,
            _health_task,
            _watchdog_task,
            _summarizer_live_task,
            _memory_gc_task,
            _maintenance_task,
            _np_sources_task,
            _donation_task,
            _blur_task,
            _proxy_clean_task,
            _dead_air_task,
        )
        await _director_scheduler.stop()
        await stream_vision_manager.stop_all()
        await eventsub_manager.stop_all()
        await _cancel_event_tasks()
        await bot_manager.stop_all()
        await close_db()
        logger.info("Сервер остановлен.")


app = FastAPI(title="Twitch AI Bot Panel", lifespan=lifespan)
install_api_error_handlers(app)
# v10.3 5: actor-middleware ставит ContextVar.actor для всего цикла запроса,
# чтобы log_action() автоматически писал, кто из юзеров панели сделал действие.
app.middleware("http")(actor_middleware)
app.middleware("http")(widget_channel_middleware)


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, bool]:
    return {"ok": True}


# BUG-3: браузеры запрашивают /favicon.ico в корне — раздаём статический файл,
# иначе каждая страница панели пишет 404 в лог.
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    from fastapi.responses import FileResponse
    return FileResponse(static_dir / "favicon.ico", media_type="image/x-icon")


# Static files — проверяем что папка существует
static_dir = Path(__file__).parent.parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# v10.4.2: раздаём сохранённые stream_vision-кадры по /frames/<channel>/<file>.jpg.
# Папка создаётся при первом сохранении (см. stream_vision._save_frame_to_disk),
# но монтировать надо заранее — иначе StaticFiles упадёт с FileNotFoundError.
from app.stream_vision import FRAMES_DIR as _FRAMES_DIR  # noqa: E402
_FRAMES_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/frames", StaticFiles(directory=str(_FRAMES_DIR)), name="frames")

# Templates dir
templates_dir = Path(__file__).parent.parent / "templates"
templates_dir.mkdir(exist_ok=True)

# Флот регистрируется до основного router: иначе GET /api/accounts/{account_id}
# из app/routes.py перехватывает /api/accounts/health-status и отдаёт 422.
from app.bot_fleet_routes import router as _bot_fleet_router  # noqa: E402
app.include_router(_bot_fleet_router)
from app.proxy_pool_routes import router as _proxy_pool_router  # noqa: E402
app.include_router(_proxy_pool_router)

app.include_router(router)
app.include_router(ws_router)
from app.bot_check_routes import router as _bot_check_router  # noqa: E402
app.include_router(_bot_check_router)
from app.bulk_channels_routes import router as _bulk_channels_router  # noqa: E402
app.include_router(_bulk_channels_router)
from app.bot_packs import router as _bot_packs_router  # noqa: E402
app.include_router(_bot_packs_router)
from app.director_routes import router as _director_router  # noqa: E402
app.include_router(_director_router)

# v10.4.5: OBS-виджеты (animated bg, goals, now-playing, sub-goal).
# admin_router → крепится к auth-router (CRUD из панели).
# public_router → к ws_router (без auth, для OBS Browser Source).
from app.widgets import admin_router as _widgets_admin, public_router as _widgets_public  # noqa: E402

app.include_router(_widgets_admin)
app.include_router(_widgets_public)
from app.media_share_routes import router as _media_share_router  # noqa: E402
app.include_router(_media_share_router)
from app.chat_overlay_routes import admin_router as _chat_overlay_admin, public_router as _chat_overlay_public  # noqa: E402
app.include_router(_chat_overlay_admin)
app.include_router(_chat_overlay_public)

# §13 WIDGETS_PLAN (widgets): Blur Guard — настройки (admin) + публичные
# бинды/фидбек для OBS-оверлея /obs/blur-guard.
from app.blur_guard_routes import admin_router as _blur_admin, public_router as _blur_public  # noqa: E402
app.include_router(_blur_admin)
app.include_router(_blur_public)
# v14 MODERATION_PLAN: политика «кто таймаутит» (auto/ask/learn) + очередь вопросов.
from app.moderation_routes import router as _moderation_policy_router  # noqa: E402

app.include_router(_moderation_policy_router)
# Q26 (DEC-OWNER-014): журнал наказаний + очередь подтверждения + защищённые + разбан.
from app.moderation_journal_routes import router as _moderation_journal_router  # noqa: E402

app.include_router(_moderation_journal_router)
# Q28 (DEC-OWNER-017): брендовая палитра виджетов — per-канал.
from app.widget_brand_routes import router as _widget_brand_router  # noqa: E402

app.include_router(_widget_brand_router)
# BRAIN_PLAN §3/§6: KB import/export + revert-last-learning (сессия brain)
app.include_router(_brain_routes.router)
# PLAN_FEEDBACK_3008 §6: роли ботов — смена роли + role-config (валидация по роли)
from app.role_routes import router as _role_routes  # noqa: E402
app.include_router(_role_routes)
# Q39: массовое применение одной настройки к большому числу ботов сразу
from app.bulk_account_settings_routes import router as _bulk_account_settings_router  # noqa: E402
app.include_router(_bulk_account_settings_router)
# PLAN_SESSION_ROLES §R2: mod-feed — канал событий ролей (OBS-виджет + тосты)
from app.mod_feed_routes import admin_router as _modfeed_admin, public_router as _modfeed_public  # noqa: E402
app.include_router(_modfeed_admin)
app.include_router(_modfeed_public)

# Per-bot логи (fixes §B4)
from app import log_routes  # noqa: E402
app.include_router(log_routes.router)

# §S5 STREAM_PLAN: Twitch Stream Tools (Helix channel/chat/scope endpoints)
from app.stream_tools_routes import router as _stream_tools_router  # noqa: E402
app.include_router(_stream_tools_router)
app.include_router(_channel_points_tts.router)  # P4: TTS за баллы канала
app.include_router(_brain_preview.router)  # P3: Мозг бота X + промпт-инспектор
from app import streamer_attitude as _streamer_attitude  # noqa: E402
app.include_router(_streamer_attitude.router)  # К3: отношение ботов к стримеру
from app import beep_pipeline as _beep_pipeline  # noqa: E402
app.include_router(_beep_pipeline.router)  # §7 фаза 3: запикивание-конвейер
from app.voice_control_routes import router as _voice_control_router  # noqa: E402
app.include_router(_voice_control_router)
from app.tts_routing_routes import router as _tts_routing_router  # noqa: E402
app.include_router(_tts_routing_router)
from app.tts_voice_policy import router as _tts_voice_policy_router  # noqa: E402
app.include_router(_tts_voice_policy_router)
from app.tts_voice_catalog import router as _tts_voice_catalog_router  # noqa: E402
app.include_router(_tts_voice_catalog_router)
from app.tts_output_routes import router as _tts_output_router  # noqa: E402
app.include_router(_tts_output_router)
from app.moderator_console_routes import admin_router as _mod_console_admin, page_router as _mod_console_page, public_router as _mod_console_public  # noqa: E402
app.include_router(_mod_console_admin)
app.include_router(_mod_console_public)
app.include_router(_mod_console_page)
from app.moderator_media_routes import admin_router as _moderator_media_admin, moderator_router as _moderator_media_moderator, public_router as _moderator_media_public  # noqa: E402
app.include_router(_moderator_media_admin)
# MOD-18: owner admin surface moderator-site (kill switch + grant revoke)
from app.moderator_site_admin_routes import admin_router as _modsite_admin_router  # noqa: E402
app.include_router(_modsite_admin_router)
app.include_router(_moderator_media_moderator)
app.include_router(_moderator_media_public)
from app.moderator_sound_routes import admin_router as _moderator_sound_admin, public_router as _moderator_sound_public  # noqa: E402
app.include_router(_moderator_sound_admin)
app.include_router(_moderator_sound_public)
from app.soundboard_routes import router as _soundboard_router  # noqa: E402
app.include_router(_soundboard_router)
from app.song_request_routes import router as _song_request_router  # noqa: E402
app.include_router(_song_request_router)
from app.twitch_predictions import router as _twitch_predictions_router  # noqa: E402
app.include_router(_twitch_predictions_router)

# §R3 ROLES_PLAN: роль-сторона стрим-инструментов (auto/suggest/off + история)
from app.stream_intent_routes import router as _stream_intent_router  # noqa: E402
app.include_router(_stream_intent_router)
# Владелец 27.09 (вечер): дашборд «здоровье эфира» — кто подключён/отвечает/молчит и почему
from app.stream_health import router as _stream_health_router  # noqa: E402
app.include_router(_stream_health_router)
# Владелец 27.09 (вечер): календарь недели — каналы/пачки/TTS-моменты одной сеткой
from app.weekly_schedule import router as _weekly_schedule_router  # noqa: E402
app.include_router(_weekly_schedule_router)
# PLAN.md «Чат-логгер»: статус/токен/каналы/поиск/экспорт (logger — отдельный процесс)
from app.chat_logger_routes import logger_router  # noqa: E402
app.include_router(logger_router)
# G (REWORK_PLAN 03.09): режим разговора с ботом без Twitch (dm-чат)
from app.dm_chat import router as _dm_router  # noqa: E402
app.include_router(_dm_router)
# Песочница тестирования ответа бота без отправки в Twitch
from app.sandbox_routes import router as _sandbox_router  # noqa: E402
app.include_router(_sandbox_router)
# Клонирование / перенос настроек между каналами
from app.channel_clone_routes import router as _channel_clone_router  # noqa: E402
app.include_router(_channel_clone_router)
# OBS Streamer HUD / Суфлёр (виджет подсказок тем и вопросов из чата)
from app.streamer_hud_routes import router as _streamer_hud_router  # noqa: E402
app.include_router(_streamer_hud_router)
# Синхронизация и сбор смайлов канала (7TV, BTTV, FFZ)
from app.channel_emotes_routes import router as _channel_emotes_router  # noqa: E402
app.include_router(_channel_emotes_router)
# Мини-досье зрителя в 1 клик
from app.viewer_dossier_routes import router as _viewer_dossier_router  # noqa: E402
app.include_router(_viewer_dossier_router)
# §S2 STREAM_PLAN: Beep Guard — детектор запретных слов (инициализация схемы)
# ВАЖНО: create_task здесь был на уровне модуля — при импорте app.server в
# тестах (running loop) таска гонялась с init_db() теста за свежий tmp-файл
# БД → flaky "database is locked" (HANDOFF_DB_LOCK_BUG.md). Схема теперь
# поднимается в lifespan() после init_db().

