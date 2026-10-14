"""Анализатор чата: читает сообщения, генерирует AI-ответы, пишет в чат."""

import asyncio
import json
import logging
import random
import re
import time
from typing import Any

from app.ai_service import AIService, ai_log
from app.anti_detection import (
    TypoConfig,
    apply_typo,
    compute_self_similarity,
    humanized_delay_seconds,
    looks_like_bot,
)
from app.anti_spam import AntiSpamSettings, anti_spam
from app.batched_gen import BatchedGenerator
from app.smart_trigger import (
    SilenceTracker,
    SpikeDetector,
    extract_vision_event,
    is_streamer_question,
)
# v10.4.5 Wave 2: новые подсистемы
from app.mood_engine import MoodTracker, mood_to_temperature
from app.multi_bot_chat import FriendlyChatTracker, is_friendly_bot
from app.game_vocab import (
    DEFAULT_GAME_CATEGORIES,
    format_vocab_block,
    match_game_category,
    match_via_text,
)
from app import stream_vision as _sv
# v10.4.7 Wave 4: новые подсистемы
from app.conversation_threads import ThreadTracker, format_thread_context
from app.proactive_questions import (
    ProactiveQuestionTracker,
    build_question_prompt,
    extract_question_text,
    fallback_question,
)
from app.local_fallback import FallbackRouter, classify_error_message, classify_error_status
from app.live_mimicry import LiveProfileCollector, mimicry_hint_block, adjust_delay_for_mimicry
from app import streamer_notify as _notify
from app import replay_debug as _replay
from app.ai_quality import (
    filter_output_heuristic,
    format_few_shot_block,
    format_kb_block,
    check_hallucination,
)
from app.ai_quality_db import (
    build_full_conversation_context,
    classify_message_db,
    check_topic_cooldown,
    record_bot_topic,
    check_banned_topics_db,
    retrieve_kb_for_query,
    pick_style_examples,
    pick_variant_for_account,
    increment_variant_count,
)
from app.database import get_db
from app.twitch_helix import format_channel_context, get_channel_info
from app import user_memory
from app import streamer_lore
from app import learning as learning_mod
from app import personality_shift
from app import summarizer
from app.bot_logs import log_per_bot

logger = logging.getLogger(__name__)


# P5-сплит: шум-эвристика в app/chat_noise.py (реэкспорт ниже), промпт-блоки в app/chat_prompt_blocks.py

from app.chat_noise import _is_noise_message  # noqa: F401
from app.chat_prompt_blocks import ChatPromptBlocksMixin

class ChatAnalyzer(ChatPromptBlocksMixin):

    def __init__(self, ai: AIService, send_fn: Any) -> None:
        self.ai = ai
        self.send_fn = send_fn
        self._settings: dict[int, dict] = {}
        # §7.1 §9: время последней реплики стримера (account_id, channel) → ts
        self._last_streamer_msg: dict[tuple[int, str], float] = {}
        self._chat_buffer: dict[str, list[dict]] = {}
        self._last_reply: dict[str, float] = {}
        self._auto_tasks: dict[str, asyncio.Task] = {}
        # Кэш токена аккаунта (для Helix вызовов)
        self._account_token: dict[int, str] = {}
        # §R1 PLAN_SESSION_ROLES: кэш роли бота (account_id → (ts, role, cfg)),
        # TTL 60с — role_config меняется редко, гейт читается на каждое сообщение.
        self._role_cache: dict[int, tuple[float, str, dict]] = {}
        # v10.4.3: raid-active overlay — (account_id, channel) -> until_ts (unix sec).
        # Пока активен — бот активно автогенерит сообщения с уменьшенным интервалом,
        # даже если auto_chat в основных настройках выключен.
        self._raid_active: dict[tuple[int, str], float] = {}
        # v10.4.4: smart-trigger детекторы (per-channel state, не per-account).
        self._spike_detector = SpikeDetector(window_sec=30, mult=2.5, min_baseline=0.2, spike_cooldown_sec=90)
        self._silence_tracker = SilenceTracker(silence_sec=8.0, valid_window_sec=60.0)
        # Последний vision-event который мы видели для канала (для дедуп логики).
        self._last_vision_event: dict[str, tuple[float, str]] = {}
        # v10.4.4: batched-generation для multi-bot. Опт-ин per-account через
        # settings["batched_gen_enabled"]. Шаринг буффера по каналу.
        self._batched_gen = BatchedGenerator(wait_ms=300, max_batch=4, enabled=False)
        # v10.4.5: per-account, per-channel state
        self._mood_trackers: dict[tuple[int, str], MoodTracker] = {}
        self._friendly_trackers: dict[tuple[int, str], FriendlyChatTracker] = {}
        # v10.4.7 Wave 4: per-account / per-channel state
        self._thread_trackers: dict[tuple[int, str], ThreadTracker] = {}
        self._proactive_trackers: dict[tuple[int, str], ProactiveQuestionTracker] = {}
        self._live_profiles: dict[tuple[int, str], LiveProfileCollector] = {}
        self._fallback_router = FallbackRouter(fallback_provider="ollama")
        self._notifiers: dict[int, _notify.StreamerNotifier] = {}
        self._replay_sessions: dict[tuple[int, str], int] = {}  # active replay sid per (acc, chan)
        # PLAN §9g: listener(account_id, channel) — реальный поток чата в трекер
        # скорости сообщений clip-detector (регистрируется из routes/server).
        self._clip_rate_listener = None
        # PLAN §2.1: кэш per-channel overrides — (acc, chan) -> (ts, overrides)
        self._channel_ov_cache: dict[tuple[int, str], tuple[float, dict]] = {}
        # Smart Anti-Dead-Air (детектор затишья эфира per-bot per-channel)
        self._channel_last_activity: dict[tuple[int, str], float] = {}
        self._channel_last_dead_air: dict[tuple[int, str], float] = {}
        self._channel_dead_air_channel_cooldown: dict[str, float] = {}
        # Emote Humanizer: реакция смайликами на хайп
        self._last_emote_humanizer: dict[tuple[int, str], float] = {}
        # Глобальная пауза ботов (Режиссёр / хоткеи / Stream Deck)
        self._global_pause_until: float = 0.0

    def pause_all(self, duration_sec: float = 120.0) -> float:
        """Приостановить все ответы ботов на duration_sec секунд (по умолчанию 2 мин)."""
        self._global_pause_until = time.time() + max(1.0, float(duration_sec))
        return self._global_pause_until

    def resume_all(self) -> None:
        """Снять глобальную паузу немедленно."""
        self._global_pause_until = 0.0

    def is_paused(self) -> tuple[bool, int]:
        """Возвращает (is_paused, remaining_seconds)."""
        now = time.time()
        if self._global_pause_until > now:
            return True, max(1, int(self._global_pause_until - now))
        return False, 0

    def set_clip_rate_listener(self, fn) -> None:
        self._clip_rate_listener = fn

    # ---------- PLAN §2.1: per-channel overrides (изоляция настроек по каналу) ----------

    # Ключи analyzer-настроек, которые можно переопределять на канал
    # (UI «🎛 Overrides» на карточке канала → таблица channel_overrides).
    CHANNEL_MERGE_KEYS = (
        # характер/персона (было в UI, теперь реально применяется в runtime)
        "humor_level", "sarcasm_level", "darkness_level", "adult_humor",
        "crudeness_level", "contact_level", "chat_affinity", "canadian_mode",
        "emotion_intensity", "observation_only",
        # активность (§2.1)
        "auto_chat", "silent_mode", "cooldown",
        # источники контекста (§2.1)
        "context_source_chat", "context_source_stream", "context_source_streamer",
        # TTS (§2.1): заглушить озвучку бота в конкретном канале
        "tts_mute",
        # PLAN_FEEDBACK_3008 §2.3: live-сводки Summarizer per-channel
        "summarizer_live_enabled", "summarizer_live_lang",
    )
    CHANNEL_OV_CACHE_TTL = 30.0  # сек; overrides меняются редко, чат читает часто

    async def _channel_overrides_cached(self, account_id: int, channel: str) -> dict:
        key = (int(account_id), (channel or "").lstrip("#").lower())
        now = time.time()
        cached = self._channel_ov_cache.get(key)
        if cached and now - cached[0] < self.CHANNEL_OV_CACHE_TTL:
            return cached[1]
        data: dict = {}
        try:
            from app.database import get_db
            db = await get_db()
            try:
                cur = await db.execute(
                    "SELECT overrides_json FROM channel_overrides WHERE account_id = ? AND channel = ? AND enabled = 1",
                    (account_id, key[1]),
                )
                row = await cur.fetchone()
                if row:
                    data = json.loads(row["overrides_json"] or "{}")
            finally:
                await db.close()
        except Exception as exc:
            logger.debug("channel overrides load error: %s", exc)
        self._channel_ov_cache[key] = (now, data)
        return data

    async def _merged_settings(self, account_id: int, channel: str, settings: dict) -> dict:
        """Базовые настройки аккаунта + per-channel overrides (только разрешённые ключи)."""
        ov = await self._channel_overrides_cached(account_id, channel)
        if not ov:
            return settings
        merged = dict(settings)
        for k, v in ov.items():
            if k in self.CHANNEL_MERGE_KEYS:
                merged[k] = v
        return merged

    def invalidate_channel_overrides(self, account_id: int | None = None, channel: str = "") -> None:
        """Сброс кэша overrides (вызывать после сохранения через UI/API)."""
        if account_id is None:
            self._channel_ov_cache.clear()
            return
        ch = (channel or "").lstrip("#").lower()
        if ch:
            self._channel_ov_cache.pop((int(account_id), ch), None)
        else:
            for k in [k for k in self._channel_ov_cache if k[0] == int(account_id)]:
                self._channel_ov_cache.pop(k, None)

    # ---------- v10.4.5: helpers для wave 2 state ----------

    def _get_mood_tracker(self, account_id: int, channel: str) -> MoodTracker:
        key = (int(account_id), (channel or "").lower())
        tr = self._mood_trackers.get(key)
        if tr is None:
            s = self.get_settings(account_id)
            tr = MoodTracker(
                alpha=float(s.get("mood_alpha", 0.25) or 0.25),
                throttle_threshold=float(s.get("mood_throttle_threshold", -0.5) or -0.5),
                throttle_cooldown_sec=float(s.get("mood_throttle_cooldown_sec", 120.0) or 120.0),
                reaction_window_sec=float(s.get("mood_reaction_window_sec", 30.0) or 30.0),
            )
            self._mood_trackers[key] = tr
        return tr

    def _get_friendly_tracker(self, account_id: int, channel: str, own_nick: str = "") -> FriendlyChatTracker:
        key = (int(account_id), (channel or "").lower())
        tr = self._friendly_trackers.get(key)
        s = self.get_settings(account_id)
        raw_nicks = (s.get("multi_bot_friendly_nicks") or "")
        nicks = [n.strip() for n in re.split(r"[\s,;]+", raw_nicks) if n.strip()]
        if tr is None:
            tr = FriendlyChatTracker(
                friendly_nicks=[],
                own_nick=own_nick,
                reply_probability=float(s.get("multi_bot_reply_probability", 0.6) or 0.6),
                reply_cooldown_sec=float(s.get("multi_bot_reply_cooldown_sec", 90.0) or 90.0),
                min_delay_sec=float(s.get("multi_bot_min_delay_sec", 15.0) or 15.0),
                max_delay_sec=float(s.get("multi_bot_max_delay_sec", 40.0) or 40.0),
            )
            self._friendly_trackers[key] = tr
        # Обновляем nicks/own_nick на лету (если поменялись в UI)
        tr.set_friendly_nicks(nicks)
        if own_nick:
            tr.own_nick = own_nick
        return tr

    # ---------- v10.4.7 Wave 4: helpers ----------

    def _get_thread_tracker(self, account_id: int, channel: str) -> ThreadTracker:
        key = (int(account_id), (channel or "").lower())
        tr = self._thread_trackers.get(key)
        if tr is None:
            s = self.get_settings(account_id)
            tr = ThreadTracker(
                similarity_threshold=float(s.get("threads_similarity_threshold", 0.18) or 0.18),
                stale_after_sec=float(s.get("threads_stale_after_sec", 600.0) or 600.0),
                max_active_threads=int(s.get("threads_max_active", 4) or 4),
            )
            self._thread_trackers[key] = tr
        return tr

    def _get_proactive_tracker(self, account_id: int, channel: str) -> ProactiveQuestionTracker:
        key = (int(account_id), (channel or "").lower())
        tr = self._proactive_trackers.get(key)
        if tr is None:
            s = self.get_settings(account_id)
            tr = ProactiveQuestionTracker(
                cooldown_sec=float(s.get("proactive_cooldown_sec", 180.0) or 180.0),
                min_silence_sec=float(s.get("proactive_min_silence_sec", 90.0) or 90.0),
            )
            self._proactive_trackers[key] = tr
        return tr

    def _get_live_profile(self, account_id: int, channel: str) -> LiveProfileCollector:
        key = (int(account_id), (channel or "").lower())
        c = self._live_profiles.get(key)
        if c is None:
            s = self.get_settings(account_id)
            c = LiveProfileCollector(window=int(s.get("live_mimicry_window", 200) or 200))
            self._live_profiles[key] = c
        return c

    def _get_notifier(self, account_id: int) -> _notify.StreamerNotifier:
        n = self._notifiers.get(account_id)
        if n is None:
            s = self.get_settings(account_id)
            settings = _notify.NotifySettings(
                discord_webhook=str(s.get("notify_discord_webhook", "") or ""),
                telegram_bot_token=str(s.get("notify_telegram_bot_token", "") or ""),
                telegram_chat_id=str(s.get("notify_telegram_chat_id", "") or ""),
                panel_enabled=bool(s.get("notify_panel_enabled", True)),
                rate_limit_per_min=int(s.get("notify_rate_limit_per_min", 6) or 6),
                min_severity=str(s.get("notify_min_severity", "info") or "info"),  # type: ignore[arg-type]
            )
            limiter = _notify.RateLimiter(max_per_window=settings.rate_limit_per_min)
            n = _notify.StreamerNotifier(settings=settings, limiter=limiter)
            self._notifiers[account_id] = n
        return n

    def invalidate_notifier(self, account_id: int) -> None:
        """Вызвать когда меняются notify-settings — пересоздадим."""
        self._notifiers.pop(account_id, None)

    async def record_replay_event(self, account_id: int, channel: str, kind: str, payload: dict) -> None:
        """Public hook: записать произвольный event в replay-сессию."""
        try:
            s = self.get_settings(account_id)
            if not s.get("replay_recording_enabled"):
                return
            sid = self._replay_sessions.get((int(account_id), (channel or "").lower()))
            if sid:
                await _replay.add_event(sid, kind, payload)  # type: ignore[arg-type]
        except Exception as exc:
            logger.debug("replay add_event error: %s", exc)

    # ---------- v10.4.3: raid-active overlay ----------

    def set_raid_active(self, account_id: int, channel: str, until_ts: float) -> None:
        """Активирует boost-режим автоответов для (account_id, channel) до ``until_ts``.
        Запускает фоновую задачу _auto_chat_loop если её ещё нет.
        """
        if not channel:
            return
        ch = channel.lstrip("#").lower()
        key = (account_id, ch)
        cur = self._raid_active.get(key, 0.0)
        if until_ts > cur:
            self._raid_active[key] = until_ts

        # v16 BRAIN_PLAN §7: personality shift «raid» (теплее/энергичнее)
        try:
            remaining = max(60, int(until_ts - time.time()))
            personality_shift.shift_manager.trigger(
                account_id, ch, "raid",
                duration_sec=min(remaining, 1800),
                mood_delta=0.25, emotionality_delta=0.15,
                reason="raid_active",
            )
        except Exception:
            pass

        # v11: Зберігаємо контекст рейду якщо увімкнено raid_save_context
        settings = self.get_settings(account_id)
        if settings.get("raid_save_context"):
            try:
                asyncio.create_task(
                    self._save_raid_context(account_id, channel, until_ts)
                )
            except Exception as exc:
                logger.debug("raid_save_context error: %s", exc)

        # v11: Застосовуємо per-channel overrides якщо увімкнено raid_apply_overrides
        if settings.get("raid_apply_overrides"):
            try:
                asyncio.create_task(
                    self._apply_raid_overrides(account_id, channel)
                )
            except Exception as exc:
                logger.debug("raid_apply_overrides error: %s", exc)

        # Убедимся, что auto-chat loop крутится для этого канала.
        # Используем тот же _auto_tasks ключ что и обычный auto_chat.
        loop_key = f"{account_id}:{ch}"
        if loop_key not in self._auto_tasks or self._auto_tasks[loop_key].done():
            # Проверяем что есть запущенный event loop — без него корутину
            # планировать нельзя (например, при синхронных тестах). Сначала
            # пробуем достать loop без побочных эффектов, чтобы не создавать
            # лишнюю корутину которую потом некому await-ить.
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return
            coro = self._auto_chat_loop(account_id, ch, nickname="")
            try:
                self._auto_tasks[loop_key] = asyncio.create_task(coro)
            except RuntimeError:
                coro.close()

    def clear_raid_active(self, account_id: int, channel: str) -> None:
        ch = (channel or "").lstrip("#").lower()
        self._raid_active.pop((account_id, ch), None)

    async def _save_raid_context(self, account_id: int, channel: str, until_ts: float) -> None:
        """v11: Зберігає контекст рейду в bot_conversation_history."""
        try:
            db = await get_db()
            try:
                # Зберігаємо системне повідомлення про початок рейду
                await db.execute(
                    "INSERT INTO bot_conversation_history (account_id, channel, role, author, content, metadata_json) "
                    "VALUES (?, ?, 'system', 'raid', ?, ?)",
                    (
                        account_id, channel,
                        f"Рейд почався в #{channel}",
                        json.dumps({"type": "raid_start", "until": until_ts}),
                    ),
                )
                await db.commit()
                await ai_log("raid_context", f"Контекст рейду збережено для #{channel}", account_id, channel)
            finally:
                await db.close()
        except Exception as exc:
            logger.debug("_save_raid_context error: %s", exc)

    async def _apply_raid_overrides(self, account_id: int, channel: str) -> None:
        """v11: Застосовує per-channel overrides для рейду."""
        try:
            db = await get_db()
            try:
                cur = await db.execute(
                    "SELECT overrides_json FROM channel_overrides WHERE account_id = ? AND channel = ? AND enabled = 1",
                    (account_id, channel.lower()),
                )
                row = await cur.fetchone()
                if not row:
                    return
                overrides = json.loads(row["overrides_json"] or "{}")
                if not overrides:
                    return
                # Зберігаємо оригінальні значення для відкату
                settings = self.get_settings(account_id)
                self._raid_overrides_backup = {}
                for key in ("humor_level", "sarcasm_level", "adult_humor", "contact_level"):
                    if key in overrides and key in settings:
                        self._raid_overrides_backup[key] = settings[key]
                        settings[key] = overrides[key]
                await ai_log("raid_overrides", f"Застосовано overrides для #{channel}: {list(overrides.keys())}", account_id, channel)
            finally:
                await db.close()
        except Exception as exc:
            logger.debug("_apply_raid_overrides error: %s", exc)

    async def _restore_raid_overrides(self, account_id: int) -> None:
        """v11: Відновлює оригінальні значення після рейду."""
        if hasattr(self, '_raid_overrides_backup') and self._raid_overrides_backup:
            settings = self.get_settings(account_id)
            for key, val in self._raid_overrides_backup.items():
                if key in settings:
                    settings[key] = val
            self._raid_overrides_backup = {}

    def is_raid_active(self, account_id: int, channel: str) -> bool:
        ch = (channel or "").lstrip("#").lower()
        until = self._raid_active.get((account_id, ch), 0.0)
        if until <= 0:
            return False
        if time.time() >= until:
            self._raid_active.pop((account_id, ch), None)
            return False
        return True

    def set_account_token(self, account_id: int, token: str) -> None:
        """Сохраняет токен аккаунта для Helix-запросов (channel context)."""
        self._account_token[account_id] = token

    def get_settings(self, account_id: int) -> dict:
        if account_id not in self._settings:
            self._settings[account_id] = {
                "enabled": False,
                "silent_mode": False,
                "reply_to_mentions": True,
                "auto_chat": False,
                "auto_chat_interval": 60,
                # §4.4 PLAN_FEEDBACK_2908: clip_* ключи здесь НЕ задаются
                # намеренно — пока бот не настроил свои значения, действует
                # глобальный конфиг (fallback в routes.bot_clip_check).
                # v10.4: больше буфер по умолчанию — чтобы бот «видел» больше чата и не обрезал контекст.
                "buffer_size": 50,
                # v10.4: сколько последних сообщений показывать AI в промпте (раньше было захардкожено 12).
                "chat_window_size": 30,
                # v10.4: если в in-memory буфере < `chat_window_size`, дочитываем хвост из chat_log БД.
                "use_db_chat_fallback": True,
                "db_chat_fallback_minutes": 5,
                # v10.4: тогглы источников контекста для генерации ответов.
                # «💬 чат» — последние сообщения чата (как раньше).
                # «🎥 стрим» — последнее vision/audio-наблюдение (что бот видит/слышит на стриме).
                # «👤 стример» — игра/название стрима из Helix (раньше было `use_channel_context`).
                "context_source_chat": True,
                "context_source_stream": False,
                "context_source_streamer": False,
                "cooldown": 10,
                # v10.2: адаптивный кулдаун по темпу чата (0 = выключен).
                "adaptive_cooldown": True,
                "adaptive_cooldown_min": 8,    # секунд — при тихом чате
                "adaptive_cooldown_max": 45,   # секунд — при бурном чате (≥30 msg/min)
                "system_prompt": (
                    "Ты — обычный зритель в Twitch-чате. Ты давно смотришь этот стрим "
                    "и помнишь общий контекст того, что происходит в чате и на стриме.\n"
                    "1. Понимай, о чём СЕЙЧАС говорят в чате — смотри на последние 3-5 содержательных реплик. "
                    "Спам-эмодзи (KEKW, LUL, Pog), односложные реакции (+, ?, лол) — это НЕ темы, их можно игнорировать.\n"
                    "2. Всегда храни контекст чата — не забывай, о чём говорили 5 минут назад. Отвечай по текущей теме.\n"
                    "3. Отвечай ОДНОЙ короткой репликой, 10-15 слов. Не больше. "
                    "Длинный ответ — только если тебя об этом попросили.\n"
                     "4. Не задавай встречные вопросы если тебя ни о чём не спрашивают.\n"
                     "5. Если добавить особо нечего или непонятно о чём речь — лучше промолчи (верни пустую строку).\n"
                     "6. Пиши естественно и по делу, без мета-комментариев и служебных пояснений. "
                     "Никаких команд. Просто пиши как обычный зритель.\n"
                    "Пиши на русском, неформально."
                ),
                "language": "ru",
                # Температура для генерации ответа (0.2-0.4 — фокус на теме; None — дефолт модели).
                "temperature": 0.4,
                # PLAN §9l: провокации в спорах (bait + добивание). ВЫКЛЮЧЕНО по умолчанию.
                "conflict_provocation_enabled": False,
                # Интенсивность подначек 0-100 (масштабирует ехидность промпта и шанс срабатывания).
                "conflict_provocation_intensity": 40,
                # Длина ответа: short (10-15 слов), medium или long.
                "response_length": "short",
                # Feature 4: контекст канала из Helix
                "use_channel_context": False,
                # Feature 5: долговременная память per-user
                "use_long_term_memory": False,
                # Feature 7: anti-spam
                "antispam_enabled": False,
                "per_user_cooldown_sec": 0,
                "max_caps_pct": 0,
                "block_links": False,
                "block_repeat_count": 0,
                "min_msg_len": 0,
                # v8: AI Quality
                "use_conversation_memory": False,  # 1) channel context + user-bot pairs
                "context_channel_msgs": 10,
                "context_user_pairs": 3,
                "use_pre_classifier": False,       # 5) should-reply heuristic
                "classifier_min_confidence": 0.4,
                "classifier_chat_gap_sec": 30,
                "use_topic_cooldown": True,        # 8) cooldown per-topic (вкл. по дефолту!)
                "topic_cooldown_sec": 300,         # 5 минут — не повторяем тему
                "topic_min_shared": 2,
                "use_few_shot": False,             # 6) style examples
                "few_shot_count": 4,
                "use_kb": False,                   # 11) streamer KB RAG
                "kb_top_k": 3,
                "use_banned_topics": False,        # 7) banned topics
                "use_hallucination_guard": False,  # 9) hallucination check
                "use_output_filter": False,        # 10) output safety filter
                "use_ab_variants": False,          # 3) A/B prompt variants
                # v10.2: мини-суммаризация темы перед ответом
                "use_topic_summary": True,
                # v10.2: эмоциональный детектор чата → тон ответа
                "use_mood_detector": True,
                # v10.4.4: anti-detection (маскируем бота под живого человека).
                "anti_detection_enabled": False,
                # Smart Anti-Dead-Air (оживление чата вопросом при затишье в эфире)
                "anti_dead_air_enabled": False,
                "anti_dead_air_minutes": 3,
                "anti_dead_air_cooldown_min": 10,
                "anti_dead_air_prompt": "",
                # Emote Humanizer (боты реагируют смайликами на хайп без LLM)
                "emote_humanizer_enabled": False,
                "emote_humanizer_chance": 75,
                "emote_humanizer_cooldown": 25,
                # Задержка перед отправкой ответа: гауссово, base + per_char * len(text).
                "humanize_delay": True,
                "humanize_delay_base": 1.2,
                "humanize_delay_per_char": 0.04,
                "humanize_delay_sigma": 0.35,
                "humanize_delay_cap": 8.0,
                # Self-similarity: если новый ответ слишком похож на N последних — скипаем.
                "self_similarity_check": True,
                "self_similarity_threshold": 0.55,
                "self_similarity_window": 30,
                # Опечатки: НЕ включать без серьёзной причины. По дефолту off.
                "humanize_typos": False,
                "humanize_typos_rate": 0.05,
                # Не отвечать другим ботам в чате.
                "ignore_other_bots": True,
                # v10.4.4: bio/persona блок (структурированная биография).
                # Если включено и в БД есть persona_json — он подмешивается в system.
                # B3 (REWORK_PLAN 03.09): по решению владельца характер влияет по умолчанию.
                "use_persona": True,
                # v10.4.4: smart-trigger — реактивная активация бота.
                # Каждый sub-trigger включается независимо.
                "smart_trigger_enabled": False,
                "trigger_streamer_question": True,  # отвечать когда стример сам пишет с ?
                "trigger_chat_spike": True,         # реагировать на резкий всплеск чата
                "trigger_vision_event": True,       # реагировать на vision-событие
                "trigger_silence_after_event": True,  # реагировать на тишину после события
                # v10.4.4: batched generation — один LLM-запрос на несколько ботов
                # одного канала (экономия токенов). Opt-in.
                "batched_gen_enabled": False,
                "batched_gen_wait_ms": 300,
                "batched_gen_max_batch": 4,
                # ---------- v10.4.5 Wave 2 ----------
                # Multi-bot ролёвка (бот ↔ бот в одном канале)
                "multi_bot_chat_enabled": False,
                "multi_bot_friendly_nicks": "",  # comma-separated nicks
                "multi_bot_reply_probability": 0.6,
                "multi_bot_min_delay_sec": 15.0,
                "multi_bot_max_delay_sec": 40.0,
                "multi_bot_reply_cooldown_sec": 90.0,
                # Mood engine — настроение по реакции чата
                "mood_engine_enabled": False,
                "mood_alpha": 0.25,
                "mood_throttle_threshold": -0.5,
                "mood_throttle_cooldown_sec": 120.0,
                "mood_temperature_span": 0.3,
                "mood_reaction_window_sec": 30.0,
                # Per-game vocabulary switcher
                "game_vocab_enabled": False,
                "game_vocab_force_category": "",  # "" → авто по Helix game_name
                "game_vocab_max_words": 8,
                # Predictions / Polls auto-vote
                "predictions_polls_autovote_enabled": False,
                "predictions_polls_dry_run": True,  # лог + чат-сообщение, без реального голоса
                # VAD silence detection (Whisper-based)
                "vad_silence_enabled": False,
                "vad_silence_threshold_sec": 300,
                "vad_silence_cooldown_sec": 600,
                "vad_silence_custom_messages": "",  # \n-separated. Пусто → DEFAULT_AFK_MESSAGES
                # v10.4.6 Wave 3: Voice cloning
                "voice_clone_enabled": False,
                "voice_clone_model_name": "",  # имя файла .onnx без расширения
                # v10.4.7 Wave 4.2: Conversation threads
                "threads_enabled": False,
                "threads_similarity_threshold": 0.18,
                "threads_stale_after_sec": 600.0,
                "threads_max_active": 4,
                "threads_max_messages_in_prompt": 6,
                # v10.4.7 Wave 4.3: Proactive question generation
                "proactive_questions_enabled": False,
                "proactive_cooldown_sec": 180.0,
                "proactive_min_silence_sec": 90.0,
                "proactive_use_ai": True,  # если False — только fallback-шаблоны
                # v10.4.7 Wave 4.4: Local fallback
                "local_fallback_enabled": False,
                "local_fallback_provider": "ollama",
                "local_fallback_threshold": 2,
                "local_fallback_window_sec": 300.0,
                # v10.4.7 Wave 4.5: Bot-to-streamer DM
                "notify_enabled": False,
                "notify_panel_enabled": True,
                "notify_discord_webhook": "",
                "notify_telegram_bot_token": "",
                "notify_telegram_chat_id": "",
                "notify_rate_limit_per_min": 6,
                "notify_min_severity": "info",  # info / warning / highlight
                # v10.4.7 Wave 4.6: Live-detection mimicry
                "live_mimicry_enabled": False,
                "live_mimicry_window": 200,
                # v10.4.7 Wave 4.7: Stream replay debug
                "replay_recording_enabled": False,
                "replay_session_name": "",
                # v11: Режим спостереження — пише в БД, але НЕ в чат
                "observation_only": False,
                # v11: Тихий аналіз — аналізує чат без відповідей (для статистики/mood)
                "silent_analysis": False,
                # v11: Зберігати всі повідомлення каналу в chat_log
                "log_all_messages": True,
                # AI-BUDGET AB-1: переключатели внимания — на что бот тратит
                # платный AI. attention_vision — vision-модель по кадрам стрима,
                # attention_hearing — аудио-конвейер (транскрипт/beep),
                # attention_chat_ai — платная модель, читающая чат.
                # Выключенный источник = 0 запросов модели (AB-3); сырой лог
                # чата пишется независимо от этих переключателей (AB-2).
                "attention_vision": True,
                "attention_hearing": True,
                "attention_chat_ai": True,
                # PROMPT-BASE PB-3: декор исходящих сообщений на уровне панели
                # (0 токенов, LLM не участвует). Панель сама оборачивает
                # готовое сообщение в bot_manager.send_message_detailed.
                # Пусто = декор выключен. Команды («!np …») не декорируются.
                "outgoing_emoji_prefix": "",
                "outgoing_emoji_suffix": "",
                # v11: Батчинг повідомлень — збирає повідомлення, потім один AI-запит
                "batch_enabled": False,
                "batch_window_sec": 5.0,
                "batch_max_size": 5,
                "min_messages_to_respond": 2,
                # v11: Розширена поведінка при рейдах
                "raid_save_context": False,       # зберігати контекст рейду в пам'ять
                "raid_apply_overrides": False,    # застосовувати per-channel overrides
                "raid_exit_after_message": 0,     # вийти через N сек після останнього повідомлення (0=вимкнено)
                "raid_exit_on_silence": False,    # вийти якщо тиша >N хвилин
                # v16 BRAIN_PLAN §5: streamer lore (одобренные факты о стримере)
                "streamer_lore_enabled": True,
                # D (REWORK_PLAN): рубильники «Влияния» per-bot — выключенное не
                # попадает в промпт, код не удаляется. Персист через analyzer_settings.
                "influence_mimicry": True,
                "influence_observations": True,
                "influence_learning": True,
                # v16 BRAIN_PLAN §4: live summary (30-мин digest'ы) в prompt
                "summarizer_live_enabled": False,
                # v16 BRAIN_PLAN §4 (решение владельца): язык live-сводок =
                # язык панели (ru/en; ua→ru). Меняется из вкладки «Мозг».
                "summarizer_live_lang": "ru",
                # v16 BRAIN_PLAN §7: personality shift (временный mood)
                "personality_shift_enabled": False,
                "personality_shift_intensity": 1,
            }
        return self._settings[account_id]

    # §4.4: per-bot ключи клип-детектора — разрешены, даже если их нет в дефолтах
    _CLIP_KEYS = ("clip_threshold_multiplier", "clip_window_sec", "clip_cooldown_sec")

    # B2 (REWORK_PLAN): персист настроек анализатора — раньше dict жил только
    # в памяти и слетал при рестарте панели (тихий режим, auto_chat, кулдаун,
    # провокации, use_persona).
    async def _ensure_settings_table(self) -> None:
        from app.database import _shared_db
        await _shared_db.execute(
            "CREATE TABLE IF NOT EXISTS analyzer_settings ("
            "account_id INTEGER PRIMARY KEY, settings_json TEXT NOT NULL, updated_at REAL)"
        )
        await _shared_db.commit()

    async def load_persisted_settings(self, account_id: int) -> dict:
        """Подтягивает сохранённые настройки из БД в память (bootstrap / старт панели)."""
        try:
            from app.database import _shared_db
            await self._ensure_settings_table()
            cur = await _shared_db.execute(
                "SELECT settings_json FROM analyzer_settings WHERE account_id = ?", (account_id,)
            )
            row = await cur.fetchone()
            if row:
                import json as _json
                saved = _json.loads(row[0] or "{}")
                settings = self.get_settings(account_id)
                for key, value in saved.items():
                    if key in settings or key in self._CLIP_KEYS:
                        settings[key] = value
        except Exception as exc:
            import logging
            logging.getLogger("twitchbot").debug("analyzer settings load #%s: %s", account_id, exc)
        return self.get_settings(account_id)

    async def persist_settings(self, account_id: int) -> None:
        """Сохраняет текущие in-memory настройки бота в БД."""
        try:
            import json as _json
            import time as _time
            from app.database import _shared_db
            await self._ensure_settings_table()
            settings = self.get_settings(account_id)
            await _shared_db.execute(
                "INSERT INTO analyzer_settings(account_id, settings_json, updated_at) VALUES(?,?,?) "
                "ON CONFLICT(account_id) DO UPDATE SET settings_json=excluded.settings_json, updated_at=excluded.updated_at",
                (account_id, _json.dumps(settings, ensure_ascii=False), _time.time()),
            )
            await _shared_db.commit()
        except Exception as exc:
            import logging
            logging.getLogger("twitchbot").debug("analyzer settings persist #%s: %s", account_id, exc)

    def update_settings(self, account_id: int, updates: dict) -> dict:
        settings = self.get_settings(account_id)
        changed = False
        for key, value in updates.items():
            if key in settings or key in self._CLIP_KEYS:
                if settings.get(key) != value:
                    settings[key] = value
                    changed = True
        if changed:
            # B2: фиксируем в БД (fire-and-forget — вызывается из async-контекста)
            try:
                import asyncio
                loop = asyncio.get_running_loop()
                loop.create_task(self.persist_settings(account_id))
            except RuntimeError:
                pass  # вне event loop — персист сделает вызывающий async-код
        return settings

    def _get_antispam_settings(self, account_id: int) -> AntiSpamSettings:
        s = self.get_settings(account_id)
        return AntiSpamSettings(
            enabled=bool(s.get("antispam_enabled")),
            per_user_cooldown_sec=int(s.get("per_user_cooldown_sec") or 0),
            max_caps_pct=int(s.get("max_caps_pct") or 0),
            block_links=bool(s.get("block_links")),
            block_repeat_count=int(s.get("block_repeat_count") or 0),
            min_msg_len=int(s.get("min_msg_len") or 0),
        )

    def _buffer_key(self, account_id: int, channel: str) -> str:
        return f"{account_id}:{channel}"

    def _add_to_buffer(self, account_id: int, channel: str, author: str, text: str) -> None:
        key = self._buffer_key(account_id, channel)
        if key not in self._chat_buffer:
            self._chat_buffer[key] = []
        settings = self.get_settings(account_id)
        self._chat_buffer[key].append({"author": author, "text": text, "time": time.time()})
        max_size = int(settings.get("buffer_size", 50) or 50)
        if len(self._chat_buffer[key]) > max_size:
            self._chat_buffer[key] = self._chat_buffer[key][-max_size:]

    def clear_chat_buffer(self, account_id: int, channel: str | None = None) -> int:
        """Очищает in-memory буфер недавних сообщений (все каналы бота или конкретный)."""
        count = 0
        target_prefix = f"{account_id}:"
        target_key = self._buffer_key(account_id, channel) if channel else None

        for k in list(self._chat_buffer.keys()):
            if target_key and k == target_key:
                count += len(self._chat_buffer.pop(k, []))
            elif not target_key and k.startswith(target_prefix):
                count += len(self._chat_buffer.pop(k, []))
        return count

    def get_chat_buffer_status(self, account_id: int, channel: str | None = None) -> dict:
        """Возвращает текущую заполненность оперативной памяти (буфера сообщений)."""
        target_prefix = f"{account_id}:"
        target_key = self._buffer_key(account_id, channel) if channel else None
        count = 0
        for k, msgs in self._chat_buffer.items():
            if target_key and k == target_key:
                count += len(msgs)
            elif not target_key and k.startswith(target_prefix):
                count += len(msgs)
        settings = self.get_settings(account_id)
        max_size = int(settings.get("buffer_size", 50) or 50)
        return {
            "count": count,
            "max_size": max_size,
        }

    def _recent_bot_messages(self, account_id: int, channel: str, nickname: str, limit: int) -> list[str]:
        """Возвращает последние сообщения этого бота на канале — для
        проверки self-similarity.
        """
        nick_lc = (nickname or "").lower()
        key = self._buffer_key(account_id, channel)
        buf = self._chat_buffer.get(key, [])
        out: list[str] = []
        for item in reversed(buf):
            if item.get("author", "").lower() == nick_lc:
                out.append(item.get("text", ""))
                if len(out) >= limit:
                    break
        return out

    @staticmethod
    def _last_substantive_messages(messages: list[dict], limit: int = 5) -> list[dict]:
        """Keep the latest meaningful turns as a compact topic signal."""
        meaningful = [m for m in messages if not _is_noise_message(m.get("text", ""))]
        return meaningful[-max(3, min(int(limit or 5), 5)):]

    async def _read_db_chat_tail(
        self, account_id: int, channel: str, limit: int, minutes: int
    ) -> list[dict]:
        """v10.4: подгружаем хвост чата из chat_log за последние ``minutes`` минут.

        Используется как fallback, когда in-memory буфер пуст / меньше окна
        (например, бот только что стартовал — буфера нет, а в БД есть история).
        """
        try:
            db = await get_db()
            try:
                cursor = await db.execute(
                    """
                    SELECT author, message, timestamp
                    FROM chat_log
                    WHERE account_id = ?
                      AND channel = ?
                      AND is_bot = 0
                      AND timestamp >= datetime('now', ?)
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (account_id, channel, f"-{int(minutes)} minutes", int(limit)),
                )
                rows = await cursor.fetchall()
            finally:
                await db.close()
        except Exception as exc:
            logger.warning("db chat fallback error: %s", exc)
            return []
        # Возвращаем в хронологическом порядке.
        return [
            {"author": r["author"], "text": r["message"], "time": 0.0}
            for r in reversed(rows)
        ]

    async def _get_chat_context_async(self, account_id: int, channel: str) -> str:
        """v10.4: асинхронная версия с DB-fallback'ом и настраиваемым размером окна.

        Возвращает текст с двумя секциями:
          [Полный поток]       — последние ``chat_window_size`` сообщений;
          [Содержательные]     — те же сообщения без эмоут-спама и односложных реакций.
        """
        settings = self.get_settings(account_id)
        window = max(1, min(100, int(settings.get("chat_window_size", 30) or 30)))
        key = self._buffer_key(account_id, channel)
        msgs = list(self._chat_buffer.get(key, []))

        # Если в памяти меньше окна — попробуем дочитать из chat_log.
        if len(msgs) < window and settings.get("use_db_chat_fallback", True):
            need = window - len(msgs)
            tail = await self._read_db_chat_tail(
                account_id,
                channel,
                limit=need + 5,
                minutes=int(settings.get("db_chat_fallback_minutes", 5) or 5),
            )
            # Дедуп по (author, text) — не дублируем то, что уже в памяти.
            seen = {(m["author"], m["text"]) for m in msgs}
            extra = [m for m in tail if (m["author"], m["text"]) not in seen]
            msgs = extra + msgs

        if not msgs:
            return ""

        recent = msgs[-window:]
        ignore_noise = settings.get("ignore_noise", True)
        if ignore_noise is None:
            ignore_noise = True
        substantive = self._last_substantive_messages(recent) if ignore_noise else recent
        full_block = "\n".join(f"{m['author']}: {m['text']}" for m in recent)
        if not substantive:
            return f"[Сообщения чата]\n{full_block}\n\n(в чате только эмодзи/реакции — содержательной темы нет)"
        # Содержательная подвыборка — последние ~min(20, window/2) штук.
        sub_block = "\n".join(f"{m['author']}: {m['text']}" for m in substantive)
        return (
            f"[Сообщения чата за последнее время — {len(recent)} штук]\n{full_block}\n\n"
            f"[Содержательные сообщения — фокусируйся на этих, это и есть текущая тема]\n{sub_block}"
        )

    def _get_chat_context(self, account_id: int, channel: str) -> str:
        """Синхронная версия — без DB fallback'а. Используется в legacy-местах
        (auto_chat_loop, topic_summary) где async уже снаружи.

        Сохраняем для обратной совместимости. Новая логика — в ``_get_chat_context_async``.
        """
        settings = self.get_settings(account_id)
        window = max(1, min(100, int(settings.get("chat_window_size", 30) or 30)))
        key = self._buffer_key(account_id, channel)
        msgs = self._chat_buffer.get(key, [])
        if not msgs:
            return ""
        recent = msgs[-window:]
        ignore_noise = settings.get("ignore_noise", True)
        if ignore_noise is None:
            ignore_noise = True
        substantive = self._last_substantive_messages(recent) if ignore_noise else recent
        full_block = "\n".join(f"{m['author']}: {m['text']}" for m in recent)
        if not substantive:
            return f"[Сообщения чата]\n{full_block}\n\n(в чате только эмодзи/реакции — содержательной темы нет)"
        sub_block = "\n".join(f"{m['author']}: {m['text']}" for m in substantive)
        return (
            f"[Сообщения чата за последнее время — {len(recent)} штук]\n{full_block}\n\n"
            f"[Содержательные сообщения — фокусируйся на этих, это и есть текущая тема]\n{sub_block}"
        )

    def _effective_cooldown(self, account_id: int, channel: str) -> float:
        """Адаптивный кулдаун: при бурном чате бот отвечает реже (не теряется).

        msg/min ≥ 30 → adaptive_cooldown_max (45с);
        msg/min == 0  → adaptive_cooldown_min (8с);
        линейно между ними. Если adaptive_cooldown выключен — фиксированный cooldown.
        """
        settings = self.get_settings(account_id)
        base = float(settings.get("cooldown", 10))
        if not settings.get("adaptive_cooldown"):
            return base
        mpm = _sv.chat_activity.msg_per_min(channel)
        lo = float(settings.get("adaptive_cooldown_min", 8))
        hi = float(settings.get("adaptive_cooldown_max", 45))
        if mpm >= 30:
            return hi
        if mpm <= 0:
            return lo
        ratio = mpm / 30.0
        return lo + ratio * (hi - lo)

    def _is_on_cooldown(self, account_id: int, channel: str) -> bool:
        key = self._buffer_key(account_id, channel)
        last = self._last_reply.get(key, 0)
        return (time.time() - last) < self._effective_cooldown(account_id, channel)

    def _mark_replied(self, account_id: int, channel: str) -> None:
        key = self._buffer_key(account_id, channel)
        now = time.time()
        self._last_reply[key] = now
        ch_lower = (channel or "").lstrip("#").lower()
        self._channel_last_activity[(account_id, ch_lower)] = now
        # v10.4.5: mood engine — отмечаем bot-response для усиления реакций.
        try:
            s = self._settings.get(account_id, {})
            if s.get("mood_engine_enabled"):
                self._get_mood_tracker(account_id, channel).mark_bot_response()
        except Exception:
            pass

    async def _is_banned(self, account_id: int, username: str) -> bool:
        try:
            db = await get_db()
            try:
                cursor = await db.execute(
                    "SELECT id FROM banlist WHERE account_id = ? AND username = ?",
                    (account_id, username.lower()),
                )
                return await cursor.fetchone() is not None
            finally:
                await db.close()
        except Exception:
            return False

    @staticmethod
    def _detect_chat_role(message_author: Any) -> str:
        """Best-effort роль юзера чата из twitchio Chatter-объекта.

        Если атрибуты недоступны (напр. в тестах с простыми mock-ами) —
        возвращает 'viewer'.
        """
        try:
            if getattr(message_author, "is_broadcaster", False):
                return "streamer"
            if getattr(message_author, "is_mod", False):
                return "mod"
            if getattr(message_author, "is_vip", False):
                return "vip"
            if getattr(message_author, "is_subscriber", False):
                return "subscriber"
        except Exception:
            pass
        return "viewer"

    async def _upsert_chat_user(self, account_id: int, channel: str, username: str, role: str = "viewer") -> None:
        """v9c: реєструє/оновлює юзера чату в `chat_users` (Chat Users tab).

        Не перезаписує `enabled` — тільки role/message_count/last_seen,
        щоб не скидати toggle disabled/enabled виставлений в UI.
        """
        if not username:
            return
        try:
            db = await get_db()
            try:
                await db.execute(
                    """
                    INSERT INTO chat_users (account_id, channel, username, role, message_count, last_seen)
                    VALUES (?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
                    ON CONFLICT(account_id, channel, username) DO UPDATE SET
                        role = excluded.role,
                        message_count = message_count + 1,
                        last_seen = CURRENT_TIMESTAMP
                    """,
                    (account_id, (channel or "").lower().lstrip("#"), username.lower(), role),
                )
                await db.commit()
            finally:
                await db.close()
        except Exception as exc:
            logger.debug("chat_users upsert error: %s", exc)

    async def _is_chat_user_enabled(self, account_id: int, channel: str, username: str) -> bool:
        """v9c: перевіряє чи юзер не вимкнений (toggle enabled=0) в Chat Users.

        Якщо запису немає — вважаємо enabled (True), бо запис ще не
        встигнув з'явитись (upsert відбувається паралельно) або юзер
        новий і за замовчуванням дозволений.
        """
        if not username:
            return True
        try:
            db = await get_db()
            try:
                cursor = await db.execute(
                    "SELECT enabled FROM chat_users WHERE account_id = ? AND channel = ? AND username = ?",
                    (account_id, (channel or "").lower().lstrip("#"), username.lower()),
                )
                row = await cursor.fetchone()
                if row is None:
                    return True
                return bool(row["enabled"])
            finally:
                await db.close()
        except Exception:
            return True

    async def _get_word_filter(self, account_id: int, channel: str = "") -> list[str]:
        """PLAN §2.1: слова фильтра по каналам.

        Глобальные слова (channel='') действуют во всех каналах; слова с
        привязкой к каналу — только в нём. channel='' → только глобальные
        (контекст канала неизвестен). Fallback на старый запрос без колонки
        для БД, где миграция ещё не прошла.
        """
        ch = (channel or "").lstrip("#").lower()
        try:
            db = await get_db()
            try:
                if ch:
                    cursor = await db.execute(
                        "SELECT word FROM word_filter WHERE account_id = ? AND (channel = '' OR channel = ?)",
                        (account_id, ch),
                    )
                else:
                    cursor = await db.execute(
                        "SELECT word FROM word_filter WHERE account_id = ?", (account_id,),
                    )
                rows = await cursor.fetchall()
                return [r["word"].lower() for r in rows]
            finally:
                await db.close()
        except Exception:
            try:
                db = await get_db()
                try:
                    cursor = await db.execute(
                        "SELECT word FROM word_filter WHERE account_id = ?", (account_id,),
                    )
                    rows = await cursor.fetchall()
                    return [r["word"].lower() for r in rows]
                finally:
                    await db.close()
            except Exception:
                return []

    async def _has_banned_words(self, account_id: int, text: str, channel: str = "") -> bool:
        words = await self._get_word_filter(account_id, channel)
        text_lower = text.lower()
        return any(w in text_lower for w in words)

    async def _filter_reply(self, account_id: int, reply: str, channel: str = "") -> str:
        words = await self._get_word_filter(account_id, channel)
        for w in words:
            if w in reply.lower():
                reply = reply.replace(w, "***")
                reply = reply.replace(w.capitalize(), "***")
                reply = reply.replace(w.upper(), "***")
        return reply

    async def _check_triggers(self, account_id: int, text: str, channel: str = "") -> dict | None:
        try:
            db = await get_db()
            try:
                cursor = await db.execute(
                    "SELECT * FROM triggers WHERE account_id = ? AND enabled = 1",
                    (account_id,),
                )
                triggers = await cursor.fetchall()
                text_lower = text.lower()
                ch = (channel or "").lower()
                for t in triggers:
                    keys = t.keys()
                    # channel '' = триггер работает во всех каналах (план §10)
                    trig_ch = (t["channel"] or "").lower() if "channel" in keys else ""
                    if trig_ch and ch and trig_ch != ch:
                        continue
                    if t["keyword"].lower() in text_lower:
                        row = dict(t)
                        # Статистика срабатываний (план §10: количество + последний запуск)
                        if "fires" in keys:
                            try:
                                await db.execute(
                                    "UPDATE triggers SET fires = COALESCE(fires, 0) + 1, "
                                    "last_fired_at = CURRENT_TIMESTAMP WHERE id = ?",
                                    (row["id"],),
                                )
                                await db.commit()
                            except Exception:
                                pass
                        return row
                return None
            finally:
                await db.close()
        except Exception:
            return None

    # ── v10.2: детекция настроения чата (быстрая эвристика, без API) ──

    _POSITIVE_WORDS = {"хахах", "ахах", "лол", "kek", "lol", "lul", "ору", "ор", "kekw", "lulw", "pog",
                        "gg", "гг", "круто", "огонь", "супер", "nice", "ez", "top", "топ", "класс",
                        "красава", "лучший", "смешно", "хех", "фанатик", "шикарно", "браво"}
    _NEGATIVE_WORDS = {"trash", "трэш", "отстой", "бан", "мут", "cringe", "кринж", "noob", "нуб",
                        "слив", "слабый", "зачем", "ужас", "фу", "dumb", "idiot", "тупой", "тупо",
                        "уёбок", "хуй", "пизд", "бляд", "сука", "дебил"}

    def _detect_mood(self, account_id: int, channel: str) -> str:
        """Возвращает строку-подсказку о настроении чата (без API-запросов)."""
        key = self._buffer_key(account_id, channel)
        msgs = self._chat_buffer.get(key, [])[-15:]
        if len(msgs) < 3:
            return ""
        pos = 0
        neg = 0
        for m in msgs:
            low = m["text"].lower()
            tokens = set(low.split())
            if tokens & self._POSITIVE_WORDS:
                pos += 1
            if tokens & self._NEGATIVE_WORDS:
                neg += 1
        total = len(msgs)
        if neg > total * 0.4:
            return "токсичный / агрессивный — лучше промолчать"
        if pos > total * 0.5:
            return "весёлый / позитивный — реагируй ярче"
        if pos > neg:
            return "нейтрально-позитивный"
        return "нейтральный"

    def _check_smart_triggers(
        self, account_id: int, channel: str, author: str, text: str, settings: dict
    ) -> str | None:
        """Возвращает строку с причиной триггера или None.

        Порядок проверок: streamer-question (приоритет) → chat-spike →
        vision-event → silence-after-event.
        """
        # 1) Стример сам что-то спрашивает в чат.
        if settings.get("trigger_streamer_question") and is_streamer_question(author, channel, text):
            return "streamer_question"

        # 2) Резкий всплеск чата.
        if settings.get("trigger_chat_spike") and self._spike_detector.detect(channel):
            return "chat_spike"

        # 3) Vision-event (опционально, требует включённый stream_vision).
        if settings.get("trigger_vision_event"):
            obs = _sv.get_last_observation(account_id, channel, max_age_sec=30)
            if obs and obs.get("description"):
                desc = obs["description"]
                event_kw = extract_vision_event(desc)
                if event_kw:
                    last = self._last_vision_event.get(channel)
                    obs_ts = float(obs.get("ts") or 0)
                    # Дедупликация: один и тот же vision-кадр триггерим один раз.
                    if not last or last[0] != obs_ts:
                        self._last_vision_event[channel] = (obs_ts, event_kw)
                        self._silence_tracker.on_vision_event(channel)
                        return f"vision_event:{event_kw}"

        # 4) Тишина после события.
        if settings.get("trigger_silence_after_event") and self._silence_tracker.is_silent_after_event(channel):
            return "silence_after_event"

        return None

    async def _tts_should_speak(self, account_id: int, channel: str) -> bool:
        """§7.1 §9: «не озвучивать каждое сообщение» — tts_reply_percent (0-100).

        Процент берётся из bot_attention_config (fallback/100 = озвучивать всё).
        per-channel override tts_mute проверяется вызывающим кодом."""
        try:
            pct = 100
            db = await get_db()
            try:
                cur = await db.execute(
                    "SELECT tts_reply_percent FROM bot_attention_config WHERE account_id = ?",
                    (account_id,),
                )
                row = await cur.fetchone()
                if row and row["tts_reply_percent"] is not None:
                    pct = int(row["tts_reply_percent"])
            finally:
                await db.close()
        except Exception as exc:
            logger.debug("tts percent read error: %s", exc)
            return True
        if pct >= 100:
            return True
        if pct <= 0:
            return False
        return random.random() * 100 < pct

    async def on_message(self, instance: Any, message: Any) -> None:
        account_id = instance.account_id
        nickname = instance.nickname
        channel = message.channel.name
        author = message.author.name
        text = message.content

        # Трекаем активность чата для smart-полинга Stream Vision и Smart Anti-Dead-Air.
        _sv.chat_activity.on_message(channel)
        ch_lower = (channel or "").lstrip("#").lower()
        self._channel_last_activity[(account_id, ch_lower)] = time.time()

        # PLAN §9g: кормим трекер скорости сообщений clip-detector (реальный чат).
        if self._clip_rate_listener:
            try:
                self._clip_rate_listener(account_id, channel)
            except Exception as exc:
                logger.debug("clip rate listener error: %s", exc)

        # Сохраняем токен аккаунта (для Helix)
        if account_id not in self._account_token and getattr(instance, "token", ""):
            self._account_token[account_id] = instance.token

        settings = self.get_settings(account_id)
        if not settings["enabled"]:
            return

        # PLAN §2.1: per-channel overrides (характер/активность/источники контекста)
        # применяются ко всему дальнейшему пайплайну этого сообщения.
        settings = await self._merged_settings(account_id, channel, settings)

        self._add_to_buffer(account_id, channel, author, text)

        # v11: логування вхідного повідомлення
        try:
            await log_per_bot(account_id, channel, "chat", f"{author}: {text}")
        except Exception:
            pass

        # v11: Батчинг — якщо увімкнено, додаємо в буфер і чекаємо батч
        if settings.get("batch_enabled"):
            try:
                from app.attention_filter import get_batch_buffer, get_attention_filter
                buf = get_batch_buffer()
                af = get_attention_filter()
                buf.add(account_id, channel, {
                    "author": author, "text": text,
                    "timestamp": time.strftime("%H:%M:%S"),
                })
                # Запускаємо таймер обробки батчу
                batch_window = float(settings.get("batch_window_sec", 5.0))
                async def _process_batch():
                    await self._process_batched_messages(account_id, channel, nickname)
                buf.start_timer(account_id, channel, _process_batch, batch_window)
            except Exception as exc:
                logger.debug("batch add error: %s", exc)
            return  # Обробка відбудеться по таймеру

        # Feature 5: счётчик сообщений per-user
        if settings.get("use_long_term_memory"):
            try:
                await user_memory.increment_msg_count(account_id, author)
            except Exception:
                pass

        # v12: зберігаємо повідомлення в історію per-user (для контексту AI)
        try:
            await user_memory.add_message_history(account_id, channel, author, text, is_bot=False)
        except Exception:
            pass

        # Бан-лист
        if await self._is_banned(account_id, author):
            await ai_log("banlist", f"Игнорирую {author} (бан-лист)", account_id, channel)
            try:
                await log_per_bot(account_id, channel, "chat", f"Бан-лист: ігнорую {author}", level="info")
            except Exception:
                pass
            return

        # v9c: Chat Users — реєструємо юзера (для вкладки «Пользователи чата»)
        # і перевіряємо персональний toggle enabled/disabled.
        role = "viewer"
        try:
            role = self._detect_chat_role(getattr(message, "author", None))
            await self._upsert_chat_user(account_id, channel, author, role)
        except Exception as exc:
            logger.debug("chat_users upsert error: %s", exc)
        # §7.1 §9: «Не перебивать стримера» — фиксируем время реплики стримера
        if role == "streamer":
            self._last_streamer_msg[(account_id, channel.lower())] = time.time()
        if not await self._is_chat_user_enabled(account_id, channel, author):
            await ai_log("chat_user_disabled", f"Игнорирую {author} (disabled в Chat Users)", account_id, channel)
            try:
                await log_per_bot(account_id, channel, "chat", f"Chat Users: ігнорую {author} (disabled)", level="info")
            except Exception:
                pass
            return

        # v14 MODERATION_PLAN §1-§2: движок модерации входящего чата + антиспам зрителей.
        # Угрозы (threat 4-5) попадают в moderation_events даже в режиме off.
        try:
            from app import moderation as _mod
            _verdicts, _hits = await _mod.check_incoming(account_id, channel, author, text, role=role)
            if _verdicts or _hits:
                await ai_log(
                    "moderation",
                    f"Модерация: {author} — {_mod.summarize(_verdicts, _hits)} | {text[:100]}",
                    account_id, channel,
                )
                try:
                    await log_per_bot(account_id, channel, "system",
                                      f"Модерация: {author} — {_mod.summarize(_verdicts, _hits)}", level="warning")
                except Exception:
                    pass
            if _verdicts:
                _mode = await _mod.get_mode(account_id, channel)
                if _mode == "shadow" and any(v.is_shadow for v in _verdicts):
                    try:
                        from app.moderation_journal import journal_shadow
                        for v in _verdicts:
                            if v.is_shadow:
                                await journal_shadow(
                                    account_id, channel, author,
                                    category=v.category, severity=v.severity,
                                    rule_name=v.rule_name, action=v.rule_action or "timeout",
                                    duration_sec=v.duration_sec,
                                    message_excerpt=text[:200],
                                    detail=f"[SHADOW] Теневой вердикт ({v.rule_action or 'timeout'}) — без наказания в Twitch",
                                )
                        await log_per_bot(account_id, channel, "system",
                                          f"👻 [SHADOW] Теневое нарушение: {author} ({_verdicts[0].category}) — без наказания в Twitch",
                                          level="info")
                        await self._modfeed_moderation(account_id, channel, author, _verdicts,
                                                       executed=False, nickname=nickname or "")
                    except Exception as exc:
                        logger.warning("shadow moderation error: %s", exc)
                if _mode == "full" and any(v.action in ("block", "timeout", "ban") for v in _verdicts):
                    # §3.4 + Q01-C2: реальное наказание (таймаут с duration из вердикта
                    # или бан навсегда с предохранителем защищённых), иначе fallback до block.
                    _punish = [v for v in _verdicts if v.action in ("timeout", "ban")]
                    if _punish:
                        _tok = self._account_token.get(account_id, "")
                        for v in _punish:
                            await _mod.maybe_punish(
                                account_id, channel, author, v,
                                token=_tok, bot_nickname=nickname or "", role=role,
                            )
                    try:
                        await log_per_bot(account_id, channel, "system",
                                          f"Модерация full: игнорирую {author} ({_verdicts[0].category})", level="info")
                    except Exception:
                        pass
                    # §R2: нарушение и действия модератора — всплывашками в mod-feed
                    await self._modfeed_moderation(account_id, channel, author, _verdicts,
                                                   executed=True, nickname=nickname or "")
                    # Q01-C2: сообщение с отложенным «баном навсегда» (защищённый зритель)
                    # тоже не получает ответ бота — финальное решение владельца (DEC-OWNER-017).
                    return  # бот не отвечает на block/timeout/ban-сообщения
                if _mode in ("replace", "full") and any(v.action == "replace" for v in _verdicts):
                    _masked = next((v.masked_text for v in _verdicts if v.masked_text), None)
                    if _masked:
                        text = _masked  # дальше бот и контекст видят замаскированный текст
                # log_only: вердикты уже в журнале — сообщение обрабатывается как обычно
        except Exception as exc:
            logger.warning("moderation engine error: %s", exc)

        # v10.4.5: multi-bot ролёвка — определяем friendly ботов заранее,
        # чтобы они НЕ попадали под ignore_other_bots ниже.
        multi_bot_enabled = bool(settings.get("multi_bot_chat_enabled"))
        is_friendly = False
        friendly_tracker = None
        if multi_bot_enabled:
            friendly_tracker = self._get_friendly_tracker(account_id, channel, own_nick=nickname or "")
            is_friendly = is_friendly_bot(author, friendly_tracker.friendly_nicks)
            if is_friendly:
                friendly_tracker.observe(author, text)

        # v10.4.4: anti-detection — не отвечаем другим ботам в чате.
        # Исключение: friendly-боты (если включён multi_bot ролёвка) — обрабатываем дальше.
        if settings.get("anti_detection_enabled") and settings.get("ignore_other_bots"):
            if looks_like_bot(author, text) and not is_friendly:
                await ai_log(
                    "antidet_bot",
                    f"Похоже {author} — другой бот, игнорирую",
                    account_id,
                    channel,
                )
                try:
                    await log_per_bot(account_id, channel, "chat", f"Ігнорую бота {author}", level="info")
                except Exception:
                    pass
                return

        # v10.4.5: mood engine — кормим трекер sentiment-ом сообщения.
        if settings.get("mood_engine_enabled"):
            try:
                tr = self._get_mood_tracker(account_id, channel)
                tr.feed(text)
            except Exception as exc:
                logger.debug("mood feed error: %s", exc)

        # v10.4.7 Wave 4.2: кормим thread-tracker (для conversation threads).
        if settings.get("threads_enabled"):
            try:
                tt = self._get_thread_tracker(account_id, channel)
                tt.feed(author or "?", text, is_bot_response=False)
            except Exception as exc:
                logger.debug("threads feed error: %s", exc)

        # v10.4.7 Wave 4.3: отмечаем активность чата для proactive-cooldown.
        if settings.get("proactive_questions_enabled"):
            try:
                pt = self._get_proactive_tracker(account_id, channel)
                pt.mark_chat()
            except Exception as exc:
                logger.debug("proactive mark_chat error: %s", exc)

        # v10.4.7 Wave 4.6: кормим live-profile (только сообщения не от ботов).
        if settings.get("live_mimicry_enabled"):
            try:
                # bot-нравленые ники из friendly + own_nick
                own = (nickname or "").lower()
                if author and author.lower() != own:
                    col = self._get_live_profile(account_id, channel)
                    col.feed(text)
            except Exception as exc:
                logger.debug("live_mimicry feed error: %s", exc)

        # v10.4.7 Wave 4.7 / PLAN §9h: replay recording — пишем входящее сообщение
        # в текущую сессию. Гейт — наличие активной сессии (запись начата
        # вручную или автозаписью при старте бота).
        # E (REWORK_PLAN): дедуп — N ботов в одном канале получают одно и то же
        # сообщение; пишем chat_in один раз на (sid, author, text) в окне 60 сек.
        try:
            sid = self._replay_sessions.get((int(account_id), (channel or "").lower()))
            if sid:
                if not hasattr(self, "_replay_dedup"):
                    self._replay_dedup: dict[tuple, float] = {}
                import time as _time
                dedup_key = (sid, author, text)
                now = _time.time()
                self._replay_dedup = {k: t for k, t in self._replay_dedup.items() if now - t < 60}
                if dedup_key in self._replay_dedup:
                    raise LookupError("replay dedup")  # уже записано другим ботом этой сессии
                self._replay_dedup[dedup_key] = now
                await _replay.add_event(sid, "chat_in", {"author": author, "text": text})
        except LookupError:
            pass
        except Exception as exc:
            logger.debug("replay add_event error: %s", exc)

        # Track 6.6: exact !tts ingress. Twitch badges не дают доступ сами по себе;
        # grant проверяется по стабильному user-id в scoped console backend.
        try:
            from app.moderator_console_routes import handle_chat_tts_command
            tags = getattr(message, "tags", None) or {}
            chatter = getattr(message, "chatter", None) or getattr(message, "author", None)
            twitch_user_id = str(getattr(chatter, "id", "") or tags.get("user-id", ""))
            message_id = str(tags.get("id", "") or getattr(message, "id", ""))
            chat_tts = await handle_chat_tts_command(
                account_id, channel, twitch_user_id=twitch_user_id,
                twitch_login=author, message_id=message_id, message=text,
            )
            if chat_tts.get("handled"):
                return
        except Exception as exc:
            logger.debug("moderator !tts hook failed (non-fatal): %s", exc)

        # v11: Режим спостереження — бот пише в БД, але НЕ генерує AI-відповіді.
        # Всі підсистеми (mood, threads, memory, streamer_profile) продовжують працювати.
        if settings.get("observation_only"):
            await ai_log("observation", f"[Режим спостереження] {author}: {text}", account_id, channel)
            try:
                await log_per_bot(account_id, channel, "chat",
                                f"[спостереження] {author}: {text}", level="debug")
            except Exception:
                pass
            return

        # Canadian mode: вимкнути юмор, емоції, сарказм
        if settings.get("canadian_mode"):
            # Форсуємо серйозний, не емоційний стиль
            settings["humor_level"] = 0
            settings["sarcasm_level"] = 0
            settings["darkness_level"] = 0
            settings["crudeness_level"] = 0
            settings["adult_humor"] = 0
            settings["seriousness"] = 100

        # v11: Тихий аналіз — аналізує чат (mood, threads, stats) без відповідей.
        if settings.get("silent_analysis"):
            await ai_log("silent_analysis", f"[Тихий аналіз] {author}: {text}", account_id, channel)
            try:
                await log_per_bot(account_id, channel, "chat",
                                f"[тихий аналіз] {author}: {text}", level="debug")
            except Exception:
                pass
            return

        # Фильтр слов
        if await self._has_banned_words(account_id, text, channel):
            await ai_log("wordfilter", f"Сообщение от {author} содержит запрещённое слово, игнорирую", account_id, channel)
            return

        # Feature 7: Anti-spam (per-user cooldown / caps / links / repeat)
        as_settings = self._get_antispam_settings(account_id)
        if as_settings.enabled:
            skip, reason = anti_spam.should_skip(account_id, channel, author, text, as_settings)
            if skip:
                await ai_log("antispam", f"Пропускаю {author}: {reason}", account_id, channel)
                try:
                    await log_per_bot(account_id, channel, "chat", f"Anti-spam: {author} — {reason}", level="info")
                except Exception:
                    pass
                return

        # v8 Feature 7: Банные темы на входящем сообщении
        if settings.get("use_banned_topics"):
            try:
                hit = await check_banned_topics_db(account_id, text)
                if hit:
                    await ai_log("banned_topic", f"Сообщение от {author} затрагивает бан-тему: {hit.pattern}", account_id, channel)
                    if hit.mode == "fallback" and hit.fallback:
                        await self.send_fn(account_id, channel, hit.fallback)
                        self._mark_replied(account_id, channel)
                    return
            except Exception as exc:
                logger.warning("banned_topics check error: %s", exc)

        # PLAN §9l: провокации в спорах (bait + «добивание»). Контур запускается
        # после observation_only / silent_analysis / word_filter / anti-spam —
        # их решения имеют приоритет. True = сообщение обработано контуром.
        try:
            if await self._conflict_flow(account_id, channel, nickname, author, text, settings):
                return
        except Exception as exc:
            logger.debug("conflict provocation error: %s", exc)

        # v13 §6.1 WIDGETS_PLAN: Chat Reader — озвучка чату.
        # Два незалежні режими:
        #   1) "по команді" (наприклад !read <текст>) — озвучує обрізаний текст;
        #   2) "все підряд" (read_all=1) — озвучує КОЖНЕ повідомлення (після антиспаму).
        # Виклик через ``app.widgets.read_chat_message`` (lazy import щоб уникнути
        # циркулярного імпорту server→chat_analyzer→server).
        try:
            from app.widgets import (
                _get_chat_reader_settings, read_chat_message, _badges_to_role,
            )
            import re as _re
            cr_settings = await _get_chat_reader_settings(account_id)
            if cr_settings.get("enabled"):
                # Зібрати Twitch-badges з message-об'єкта (twitchio Chatter.tags).
                cr_badges: list[str] = []
                try:
                    chatter = getattr(message, "chatter", None)
                    if chatter is not None and getattr(chatter, "badges", None):
                        cr_badges = [b.name for b in chatter.badges if getattr(b, "name", None)]
                    elif hasattr(message, "tags") and message.tags:
                        raw = (message.tags or {}).get("badges", "")
                        if raw:
                            cr_badges = [b.split("/")[0] for b in raw.split(",") if b]
                except Exception:
                    cr_badges = []

                # Режим "по команді": текст починається з налаштованої команди.
                cmd = (cr_settings.get("command") or "!read").strip().lower()
                cmd_pattern = _re.compile(rf"^{_re.escape(cmd)}\s+(.+)$", _re.IGNORECASE | _re.DOTALL)
                cmd_match = cmd_pattern.match(text)
                if cmd_match:
                    cmd_payload = cmd_match.group(1).strip()
                    if cmd_payload:
                        await read_chat_message(
                            account_id, channel, author, cmd_payload,
                            role=_badges_to_role(cr_badges), badges=cr_badges,
                            trigger="command",
                        )
                # Режим "все підряд": read_all=1 + min_role перевірка всередині.
                elif cr_settings.get("read_all") and text.strip():
                    await read_chat_message(
                        account_id, channel, author, text,
                        role=_badges_to_role(cr_badges), badges=cr_badges,
                        trigger="all",
                    )
        except Exception as exc:
            logger.debug("chat-reader hook failed (non-fatal): %s", exc)

        # v10.5: Song Request — точная команда !sr <название>.
        sr_match = re.match(r"^!sr(?:\s+(.*))?$", text.strip(), re.IGNORECASE | re.DOTALL)
        if sr_match:
            song_title = (sr_match.group(1) or "").strip()
            try:
                from app.widgets import add_song_request
                result = await add_song_request(
                    song_title, author, channel, account_id=account_id,
                )
                if result.get("ok"):
                    await ai_log("song_request", f"🎵 {author} запросил: {song_title}", account_id, channel)
                    await self.send_fn(account_id, channel, f"🎵 Добавлено в очередь: {song_title}")
                elif result.get("error") == "queue_full":
                    await self.send_fn(account_id, channel, f"@{author} Очередь полна!")
                elif result.get("error") == "user_limit":
                    await self.send_fn(account_id, channel,
                                       f"@{author} Не больше {result.get('limit')} треков в очереди — дождись своей очереди!")
                elif result.get("error") == "cooldown":
                    await self.send_fn(account_id, channel,
                                       f"@{author} !sr будет доступен через {result.get('retry_after', 30)} сек.")
                elif result.get("error") in {
                    "empty_request", "request_too_long", "control_characters",
                    "unsafe_url", "duplicate_request",
                }:
                    await self.send_fn(account_id, channel, f"@{author} Запрос отклонён: {result['error']}")
            except Exception as exc:
                logger.warning("song_request error: %s", exc)
            return

        # §11.2 WIDGETS_PLAN: !np <название|youtube-ссылка> / !np clear —
        # автозаполнение виджета «Сейчас играет» (стример/модер).
        if text.strip().lower().startswith("!np"):
            try:
                from app.widgets import _badges_to_role, handle_now_playing_command
                np_badges: list[str] = []
                try:
                    chatter = getattr(message, "chatter", None)
                    if chatter is not None and getattr(chatter, "badges", None):
                        np_badges = [b.name for b in chatter.badges if getattr(b, "name", None)]
                    elif hasattr(message, "tags") and message.tags:
                        raw = (message.tags or {}).get("badges", "")
                        if raw:
                            np_badges = [b.split("/")[0] for b in raw.split(",") if b]
                except Exception:
                    np_badges = []
                np_result = await handle_now_playing_command(
                    text.strip(), author, account_id, channel,
                    role=_badges_to_role(np_badges),
                )
                if np_result.get("error") == "usage":
                    await self.send_fn(account_id, channel,
                                       "Использование: !np <название/ссылка> или !np clear")
            except Exception as exc:
                logger.debug("!np hook failed (non-fatal): %s", exc)
            return

        # §11.3 WIDGETS_PLAN: биндинги виджетов — chat_command → действие
        # над виджетом (counter/goals/sub_goal/countdown/...). Роли проверяются
        # внутри биндинга (binding.role). Возврата нет — не глотаем остальной флоу.
        try:
            from app.widgets import _badges_to_role
            from app.widget_bindings import handle_chat_command as _bindings_cmd
            bind_badges: list[str] = []
            try:
                chatter = getattr(message, "chatter", None)
                if chatter is not None and getattr(chatter, "badges", None):
                    bind_badges = [b.name for b in chatter.badges if getattr(b, "name", None)]
                elif hasattr(message, "tags") and message.tags:
                    raw = (message.tags or {}).get("badges", "")
                    if raw:
                        bind_badges = [b.split("/")[0] for b in raw.split(",") if b]
            except Exception:
                bind_badges = []
            await _bindings_cmd(text, author, account_id, channel,
                                role=_badges_to_role(bind_badges))
        except Exception as exc:
            logger.debug("widget-bindings hook failed (non-fatal): %s", exc)

        # v10.4.4: smart-trigger — реактивная активация бота.
        # Каждое сообщение обновляет детекторы (даже когда smart_trigger выключен —
        # это безопасно, лишь пустые dict-ы наполняются). Триггер форсирует
        # генерацию ответа в обход cooldown / classifier.
        self._spike_detector.on_message(channel)
        self._silence_tracker.on_chat_message(channel)

        # Emote Humanizer: быстрая реакция на хайп/спайк в чате смайликом без LLM
        if settings.get("emote_humanizer_enabled"):
            if self._spike_detector.detect(channel):
                if await self._try_emote_humanizer(account_id, channel, nickname):
                    return

        if settings.get("smart_trigger_enabled"):
            trigger_reason = self._check_smart_triggers(account_id, channel, author, text, settings)
            if trigger_reason:
                if trigger_reason == "chat_spike" and settings.get("emote_humanizer_enabled"):
                    if await self._try_emote_humanizer(account_id, channel, nickname):
                        return
                await ai_log(
                    "smart_trigger",
                    f"Smart-trigger '{trigger_reason}' от {author}",
                    account_id,
                    channel,
                )
                try:
                    await log_per_bot(account_id, channel, "trigger", f"Smart-trigger '{trigger_reason}' від {author}")
                except Exception:
                    pass
                await self._generate_and_send(
                    account_id, channel, nickname, author, text,
                    is_mention=False,
                    extra_context=f"Сработал smart-trigger: {trigger_reason}.",
                )
                return

        # Триггеры
        trigger = await self._check_triggers(account_id, text, channel=channel)
        if trigger:
            if self._is_on_cooldown(account_id, channel):
                return
            await ai_log("trigger", f"Триггер '{trigger['keyword']}' от {author}: {text}", account_id, channel)
            try:
                await log_per_bot(account_id, channel, "trigger", f"Триггер '{trigger['keyword']}' від {author}: {text}")
            except Exception:
                pass
            if trigger["use_ai"]:
                await self._generate_and_send(account_id, channel, nickname, author, text, is_mention=False, extra_context=f"Сработал триггер на ключевое слово '{trigger['keyword']}'.")
            elif trigger["response"]:
                reply = trigger["response"]
                if settings.get("silent_mode"):
                    await ai_log("silent", f"[Тихий режим] Триггер в #{channel}: {reply}", account_id, channel)
                else:
                    await ai_log("send", f"Отправляю (триггер) в #{channel}: {reply}", account_id, channel)
                    ok = await self.send_fn(account_id, channel, reply)
                    if ok:
                        self._mark_replied(account_id, channel)
                        anti_spam.mark_replied(account_id, channel, author)
                        self._add_to_buffer(account_id, channel, nickname, reply)
                        # v11: TTS для тригерної відповіді
                        try:
                            from app.tts_engine import get_tts_engine
                            await get_tts_engine().speak(account_id, channel, reply, emotion="neutral")
                        except Exception:
                            pass
            return

        # Упоминания
        is_mention = nickname.lower() in text.lower()
        # §7.1 §9: toggle «Отвечать на @упоминания» (bot_attention_config; дефолт — analyzer settings)
        mention_ok = settings["reply_to_mentions"]
        try:
            db = await get_db()
            try:
                cur = await db.execute(
                    "SELECT reply_to_mentions FROM bot_attention_config WHERE account_id = ?",
                    (account_id,),
                )
                row = await cur.fetchone()
                if row and row["reply_to_mentions"] is not None:
                    mention_ok = bool(row["reply_to_mentions"])
            finally:
                await db.close()
        except Exception:
            pass
        if is_mention and mention_ok:
            if self._is_on_cooldown(account_id, channel):
                await ai_log("cooldown", f"Кулдаун, пропускаю упоминание от {author}", account_id, channel)
                return
            await self._generate_and_send(account_id, channel, nickname, author, text, is_mention=True)
            return

        # v10.4.5: multi-bot ролёвка — если сообщение от friendly бота,
        # планируем отложенный ответ с реалистичной задержкой 15-40 сек.
        # §R5-хвост: болтают между собой только chatter-роли (модератор/
        # voice/lurker в дружеской переписке не участвуют).
        if is_friendly and friendly_tracker is not None:
            try:
                fr_role, _ = await self._account_role(account_id)
            except Exception:
                fr_role = "chatter"
            if fr_role == "chatter" and not self._is_on_cooldown(account_id, channel) and friendly_tracker.decide(author, text):
                delay = friendly_tracker.get_delay_seconds()
                friendly_tracker.mark_replied(author)

                async def _delayed_reply():
                    await asyncio.sleep(delay)
                    try:
                        await self._generate_and_send(
                            account_id, channel, nickname, author, text,
                            is_mention=False,
                            extra_context=f"Отвечаешь дружественному боту @{author} в чате.",
                        )
                    except Exception as exc:
                        logger.debug("multi_bot delayed reply error: %s", exc)

                await ai_log(
                    "multi_bot_reply",
                    f"Запланирован ответ {author} через {delay:.1f}s",
                    account_id, channel,
                )
                asyncio.create_task(_delayed_reply())
                return

        # v8 Feature 5: Pre-classifier — решает стоит ли отвечать на обычное сообщение
        if settings.get("use_pre_classifier"):
            try:
                decision = await classify_message_db(
                    account_id,
                    channel,
                    text,
                    bot_nickname=nickname,
                    require_mention=False,
                    min_confidence=float(settings.get("classifier_min_confidence", 0.4) or 0.4),
                    chat_gap_threshold=float(settings.get("classifier_chat_gap_sec", 30) or 30),
                )
                if not decision.should_reply:
                    # Тихо выходим — classifier решил не реагировать
                    return
                else:
                    await ai_log("classifier_pass", f"conf={decision.confidence} reason={decision.reason}", account_id, channel)
                    if not self._is_on_cooldown(account_id, channel):
                        await self._generate_and_send(account_id, channel, nickname, author, text, is_mention=False)
            except Exception as exc:
                logger.warning("pre_classifier error: %s", exc)

    async def start_auto_chat(self, account_id: int, channel: str, nickname: str) -> None:
        key = self._buffer_key(account_id, channel)
        if key in self._auto_tasks and not self._auto_tasks[key].done():
            return
        self._auto_tasks[key] = asyncio.create_task(self._auto_chat_loop(account_id, channel, nickname))

    async def check_dead_air(self, account_id: int, channel: str, nickname: str = "", force: bool = False) -> bool:
        """Smart Anti-Dead-Air: детектор затишья эфира per-bot per-channel.

        Если в канале тишина >= anti_dead_air_minutes (или force=True от Режиссёра),
        бот сам инициирует открытый вопрос стримеру/чату по игре или теме стрима, снимая неловкую паузу.
        """
        settings = self.get_settings(account_id)
        if not settings.get("enabled", True):
            return False

        if not force:
            if not settings.get("anti_dead_air_enabled", False):
                return False
            if settings.get("observation_only") or settings.get("silent_mode"):
                return False
            if self.is_paused()[0]:
                return False

        ch_lower = (channel or "").lstrip("#").lower()
        key = (account_id, ch_lower)
        now = time.time()

        last_act = self._channel_last_activity.get(key)
        if last_act is None:
            # Первый контакт с каналом — начинаем отсчёт
            self._channel_last_activity[key] = now
            if not force:
                return False

        threshold_sec = max(60, int(settings.get("anti_dead_air_minutes", 3) or 3) * 60)
        cooldown_sec = max(60, int(settings.get("anti_dead_air_cooldown_min", 10) or 10) * 60)

        if not force:
            # Проверяем канальный кулдаун (чтобы боты не галдели хором)
            last_channel_dead_air = self._channel_dead_air_channel_cooldown.get(ch_lower, 0.0)
            if (now - last_channel_dead_air) < cooldown_sec:
                return False

            # Проверяем кулдаун после прошлого срабатывания бота
            last_dead_air = self._channel_last_dead_air.get(key, 0.0)
            if (now - last_dead_air) < cooldown_sec:
                return False

            elapsed = now - last_act
            if elapsed < threshold_sec:
                return False

            # Проверяем стандартный кулдаун бота
            if self._is_on_cooldown(account_id, channel):
                return False
        else:
            elapsed = now - (last_act or now)

        # Тишина обнаружена или вызвана принудительно Режиссёром! Фиксируем время срабатывания
        mins_silent = max(1, int(elapsed // 60))
        self._channel_dead_air_channel_cooldown[ch_lower] = now
        self._channel_last_dead_air[key] = now
        self._channel_last_activity[key] = now

        custom_prompt = (settings.get("anti_dead_air_prompt") or "").strip()
        if custom_prompt:
            extra = f"Smart Anti-Dead-Air (тишина {mins_silent} мин): {custom_prompt}"
        elif force:
            extra = (
                "Режиссёр или стример нажал быстрый хоткей оживления чата. "
                "Задай короткий, естественный открытый вопрос стримеру или зрителям по происходящему на экране или текущей игре, "
                "чтобы разогреть диалог. До 15 слов, живо и ненавязчиво."
            )
        else:
            extra = (
                f"В чате долгое затишье ({mins_silent} мин без сообщений, стример молчит). "
                "Задай короткий, естественный открытый вопрос стримеру или зрителям по происходящему на экране или текущей игре, "
                "чтобы оживить диалог. До 15 слов, не будь навязчивым."
            )

        tag = "director_revive" if force else "dead_air"
        await ai_log(tag, f"⏱️ Smart Anti-Dead-Air: {'принудительный вызов Режиссёра' if force else f'тишина #{channel} ({mins_silent} мин)'}. Оживляем чат...", account_id, channel)
        try:
            await log_per_bot(account_id, channel, "trigger",
                              f"⏱️ Smart Anti-Dead-Air: {'вызов Режиссёра' if force else f'тишина {mins_silent} мин'}. Оживляем чат вопросом...", level="info")
        except Exception:
            pass

        return await self._generate_and_send(
            account_id, channel, nickname, "", "",
            is_mention=False,
            extra_context=extra,
            force=force,
        )

    async def _try_emote_humanizer(self, account_id: int, channel: str, nickname: str) -> bool:
        """Emote Humanizer: быстрая реакция смайликом на волну хайпа/смеха в чате без LLM."""
        if self.is_paused()[0]:
            return False
        settings = self.get_settings(account_id)
        if not settings.get("emote_humanizer_enabled", False):
            return False
        if settings.get("observation_only") or settings.get("silent_mode"):
            return False

        ch_lower = (channel or "").lstrip("#").lower()
        key = (account_id, ch_lower)
        now = time.time()

        # Кулдаун между эмоут-реакциями бота
        cooldown_sec = float(settings.get("emote_humanizer_cooldown", 25) or 25)
        last_reaction = self._last_emote_humanizer.get(key, 0.0)
        if (now - last_reaction) < cooldown_sec:
            return False

        # Шанс срабатывания (по умолчанию 75%)
        chance = int(settings.get("emote_humanizer_chance", 75) or 75)
        if random.randint(1, 100) > chance:
            return False

        # Анализируем буфер чата
        buf_key = self._buffer_key(account_id, channel)
        recent = self._chat_buffer.get(buf_key, [])[-10:]
        if len(recent) < 2:
            return False

        from app.highlights import DEFAULT_REACTION_TOKENS, _RE_TOKEN
        from app.channel_emotes import get_cached_channel_emotes

        # Считаем частоту токенов реакций в последних сообщениях
        token_counts: dict[str, int] = {}
        original_casing: dict[str, str] = {}
        reaction_set = set(DEFAULT_REACTION_TOKENS)
        try:
            for ce in get_cached_channel_emotes(channel):
                reaction_set.add(ce.lower())
                original_casing.setdefault(ce.lower(), ce)
        except Exception:
            pass

        for m in recent:
            txt = m.get("text", "")
            words = _RE_TOKEN.findall(txt)
            for w in words:
                w_lower = w.lower()
                if w_lower in reaction_set:
                    token_counts[w_lower] = token_counts.get(w_lower, 0) + 1
                    if w_lower not in original_casing:
                        original_casing[w_lower] = w

        if not token_counts:
            noise_msgs = sum(1 for m in recent if _is_noise_message(m.get("text", "")))
            if noise_msgs < max(2, len(recent) * 0.5):
                return False
            chosen = "KEKW"
        else:
            top_lower = max(token_counts.items(), key=lambda x: x[1])[0]
            chosen = original_casing.get(top_lower, top_lower.upper())

        roll = random.random()
        if roll < 0.70:
            reply_text = chosen
        elif roll < 0.90:
            reply_text = f"{chosen} {chosen}"
        else:
            reply_text = f"{chosen}!"

        self._last_emote_humanizer[key] = now

        await ai_log("emote_humanizer", f"🎉 Emote Humanizer: реакция на хайп -> '{reply_text}'", account_id, channel)
        try:
            await log_per_bot(account_id, channel, "trigger",
                              f"🎉 Emote Humanizer: реакция на хайп '{reply_text}'", level="info")
        except Exception:
            pass

        # Небольшая естественная задержка (0.3 - 1.2 сек)
        delay = random.uniform(0.3, 1.2)
        await asyncio.sleep(delay)

        try:
            ok = await self.send_fn(account_id, channel, reply_text)
            if ok:
                self._mark_replied(account_id, channel)
                self._add_to_buffer(account_id, channel, nickname, reply_text)
                return True
            return False
        except Exception as exc:
            logger.warning("emote humanizer send error: %s", exc)
            return False

    async def _process_batched_messages(self, account_id: int, channel: str, nickname: str) -> None:
        """v11: Обробка батчу повідомлень через Attention Filter."""
        try:
            from app.attention_filter import get_batch_buffer, get_attention_filter
            buf = get_batch_buffer()
            af = get_attention_filter()
            settings = self.get_settings(account_id)

            batch = buf.get_batch(account_id, channel)
            if not batch:
                return

            # Перевіряємо cooldown
            if self._is_on_cooldown(account_id, channel):
                return

            # Отримуємо config уваги
            config = {
                "attention_mode": "everyone",
                "ignore_noise": 1,
                "min_messages_to_respond": settings.get("min_messages_to_respond", 2),
                "max_replies_per_minute": 3,
            }
            try:
                db = await get_db()
                try:
                    cur = await db.execute(
                        "SELECT * FROM bot_attention_config WHERE account_id = ?",
                        (account_id,),
                    )
                    row = await cur.fetchone()
                    if row:
                        config.update(dict(row))
                finally:
                    await db.close()
            except Exception:
                pass

            # Отримуємо ввімкнених юзерів для custom mode
            enabled_users = None
            if config.get("attention_mode") == "custom":
                try:
                    db = await get_db()
                    try:
                        cur = await db.execute(
                            "SELECT username FROM chat_users WHERE account_id = ? AND channel = ? AND enabled = 1",
                            (account_id, channel),
                        )
                        rows = await cur.fetchall()
                        enabled_users = {r["username"].lower() for r in rows}
                    finally:
                        await db.close()
                except Exception:
                    pass

            # Застосовуємо фільтр уваги
            streamer_nick = channel.lower().lstrip("#")
            filtered = af.apply_filter(batch, config, enabled_users, streamer_nick)

            # Перевіряємо мінімальну кількість повідомлень
            if len(filtered) < int(config.get("min_messages_to_respond", 2) or 1):
                return

            # Перевіряємо чи можемо відповідати
            if not af.can_reply(account_id, config):
                return

            # Будуємо контекст для AI
            context = af.build_batch_context(filtered)

            # Генеруємо відповідь
            await ai_log("batch", f"Батч з {len(filtered)} повідомлень у #{channel}", account_id, channel)
            await self._generate_and_send(
                account_id, channel, nickname, "", "",
                is_mention=False,
                extra_context=f"Контекст батчу:\n{context}",
            )

            # Позначаємо відповідь
            cooldown = float(config.get("cooldown_after_reply_sec", 30.0))
            af.mark_replied(account_id, channel, cooldown)

        except Exception as exc:
            logger.warning("_process_batched_messages error: %s", exc)

    async def _auto_chat_loop(self, account_id: int, channel: str, nickname: str) -> None:
        while True:
            settings = self.get_settings(account_id)
            # v10.4.3: если активен raid-режим — крутимся даже при выключенных
            # enabled / auto_chat, и используем сокращённый интервал.
            raid_active = self.is_raid_active(account_id, channel)
            if not raid_active:
                if not settings["enabled"] or not settings["auto_chat"]:
                    # v10.4.3: если raid_active НЕ активен и сам канал давно не нужен —
                    # выходим из цикла чтобы освободить задачу.
                    await asyncio.sleep(5)
                    if not self.is_raid_active(account_id, channel):
                        continue

            if raid_active:
                # Быстрый интервал во время raid: 30..60s с джиттером — заметнее активность.
                interval = max(15, int(settings.get("auto_chat_interval", 60) or 60) // 2)
            else:
                interval = settings["auto_chat_interval"]
            wait = interval * (0.8 + random.random() * 0.4)
            await asyncio.sleep(wait)

            settings = self.get_settings(account_id)
            raid_active = self.is_raid_active(account_id, channel)
            if not raid_active and (not settings["enabled"] or not settings["auto_chat"]):
                continue
            if self._is_on_cooldown(account_id, channel):
                continue

            context = self._get_chat_context(account_id, channel)
            if not context:
                await ai_log("auto_chat", "Буфер чата пуст, жду сообщений...", account_id, channel)
                continue

            # Если в буфере только эмоут-спам — пропускаем итерацию (не дёргаем API без темы).
            key = self._buffer_key(account_id, channel)
            recent = self._chat_buffer.get(key, [])[-12:]
            substantive = [m for m in recent if not _is_noise_message(m["text"])]
            if not substantive:
                await ai_log(
                    "auto_chat",
                    f"В чате только эмодзи/реакции ({len(recent)} сообщ.) — пропускаю авто-сообщение",
                    account_id, channel,
                )
                continue

            await self._generate_and_send(account_id, channel, nickname, "", "", is_mention=False)

    # ---------- PLAN §9l: провокации в спорах (bait + «добивание») ----------

    async def _conflict_flow(self, account_id: int, channel: str, nickname: str,
                             author: str, text: str, settings: dict) -> bool:
        """PLAN §9l (решение владельца 28.08.2026 — полная версия).

        Фаза 1 (bait): конфликтное сообщение с шансом, зависящим от интенсивности,
        → провокационный вопрос-подначка. Фаза 2: ответ того же чатера в окне
        WINDOW_SEC → «добивание». Выключено по умолчанию; вызывается после
        observation_only/silent_analysis/word_filter/anti-spam guardrails.
        """
        from app.conflict_provocation import get_conflict_provocation
        # D (REWORK_PLAN): глобальный мастер-выключатель провокаций (Настройки);
        # off = приглушает per-bot ВКЛ. По умолчанию глобально разрешено.
        try:
            from app.database import get_setting_bool
            if not await get_setting_bool("provocations_master_enabled", default=True):
                return False
        except Exception:
            pass
        cp = get_conflict_provocation()
        # Фаза 2 первична: ответ на bait не должен сам стать новым bait-ом.
        if cp.check_escalation(account_id, channel, author):
            extra = cp.escalation_instruction(author, text, settings)
            await self._generate_and_send(account_id, channel, nickname, author, text,
                                          is_mention=True, extra_context=extra)
            try:
                await log_per_bot(account_id, channel, "trigger",
                                  f"§9l добивание спора → {author}", level="info")
            except Exception:
                pass
            return True
        try:
            from app.sentiment import score as _sentiment_score
            negative = _sentiment_score(text or "")[1] > 0.3
        except Exception:
            negative = False
        if cp.check_bait(account_id, channel, author, settings, negative):
            extra = cp.bait_instruction(author, text, settings)
            await self._generate_and_send(account_id, channel, nickname, author, text,
                                          is_mention=True, extra_context=extra)
            cp.mark_bait(account_id, channel, author)
            try:
                await log_per_bot(account_id, channel, "trigger",
                                  f"§9l bait-вопрос → {author}", level="info")
            except Exception:
                pass
            return True
        return False

    # ---------- PLAN §6: креативность (temperature) → эмоции TTS/персоны ----------

    def _pick_reply_emotion(self, account_id: int, channel: str, settings: dict) -> str:
        """Решение владельца 28.08.2026: temperature влияет ТОЛЬКО на разнообразие
        эмоций персоны/TTS (не на эмодзи в тексте).

        - < 0.45 — сдержанный бот: почти всегда neutral;
        - 0.45–0.65 — эмоция по mood engine (как раньше);
        - > 0.65 — живой бот: полный набор эмоций, чаще меняется.
        """
        try:
            temperature = float(settings.get("temperature") or 0.4)
        except (TypeError, ValueError):
            temperature = 0.4
        mood_emotion = "neutral"
        if settings.get("mood_engine_enabled"):
            try:
                tr = self._get_mood_tracker(account_id, channel)
                mood_label = tr.label()
                mood_map = {"positive": "happy", "toxic": "angry", "sad": "sad", "wild": "surprised"}
                mood_emotion = mood_map.get(mood_label, "neutral")
            except Exception as exc:
                logger.debug("mood emotion error: %s", exc)
        if temperature < 0.45:
            return mood_emotion if random.random() < 0.25 else "neutral"
        if temperature > 0.65:
            full_set = ["happy", "angry", "sad", "surprised", "neutral"]
            if mood_emotion != "neutral":
                return mood_emotion if random.random() < 0.7 else random.choice(full_set)
            return random.choice(full_set)
        return mood_emotion

    async def _account_role(self, account_id: int) -> tuple[str, dict]:
        """§R1: (роль, role_config) аккаунта с кэшем 60с."""
        import time as _time
        from app.bot_roles import DEFAULT_ROLE, load_role_config
        cached = self._role_cache.get(account_id)
        now = _time.monotonic()
        if cached and now - cached[0] < 60.0:
            return cached[1], cached[2]
        role, cfg = DEFAULT_ROLE, {}
        try:
            from app.database import get_db
            db = await get_db()
            try:
                cur = await db.execute(
                    "SELECT bot_role, role_config_json FROM accounts WHERE id = ?",
                    (account_id,),
                )
                row = await cur.fetchone()
            finally:
                await db.close()
            if row:
                role = (row["bot_role"] or DEFAULT_ROLE).strip() or DEFAULT_ROLE
                cfg = load_role_config(row["role_config_json"], role)
        except Exception as exc:
            logger.debug("role load error: %s", exc)
        self._role_cache[account_id] = (now, role, cfg)
        return role, cfg

    def invalidate_role_cache(self, account_id: int | None = None) -> None:
        """Сброс кэша роли (вызвать после смены роли/конфига в role_routes)."""
        if account_id is None:
            self._role_cache.clear()
        else:
            self._role_cache.pop(account_id, None)

    async def _modfeed_moderation(self, account_id: int, channel: str, author: str,
                                  verdicts: list, *, executed: bool, nickname: str = "") -> None:
        """§R2/§6.1: события модерации бота-модератора — всплывашками в mod-feed.

        Роль модератора + confirm_mode=confirm → НАМЕРЕНИЕ (ждёт одобрения);
        auto → действие уже исполнено. Чат анонсами не трогаем (announce_in_chat
        выключен по умолчанию). Без роли модератора ничего не публикуем.
        """
        try:
            role, cfg = await self._account_role(account_id)
            if role != "moderator":
                return
            from app.mod_feed_routes import publish_event
            from app.mod_feed_i18n import caption
            v = next((x for x in verdicts if x.action in ("timeout", "block")), verdicts[0])
            shown = getattr(v, "masked_text", None) or "сработал словарь/правило"
            shown_localization = {} if getattr(v, "masked_text", None) else {"text": caption("mod-feed.caption.rule")}
            if executed:
                publish_event(account_id, channel, "violation", user=author,
                              text=shown, severity=v.severity, action="таймаут/блок применён",
                              localization={**shown_localization, "action": caption("mod-feed.caption.applied")})
                publish_event(account_id, channel, "action", user=author,
                              text=f"модерация: {v.category}",
                              action=f"категория: {v.category} · строгость {v.severity}",
                              localization={"text": caption("mod-feed.caption.moderation", category=v.category),
                                            "action": caption("mod-feed.caption.category_severity", category=v.category, severity=v.severity)})
                # §R2-хвост: TTS-дублирование действий модератора (опция роли).
                if cfg.get("tts_announce"):
                    try:
                        announcement = f"{author}: {v.category}"
                        from app.tts_voice_policy import authorize_tts
                        decision = await authorize_tts(
                            account_id, channel, "moderation_announcement",
                            actor_role="bot", actor_id=str(account_id), text=announcement,
                        )
                        if decision["ok"]:
                            from app.tts_engine import get_tts_engine
                            await get_tts_engine().speak(
                                account_id, channel, announcement, emotion="neutral",
                                provider_override=decision.get("provider_override", ""),
                                voice_override=decision.get("voice_override", ""))
                    except Exception as exc:
                        logger.debug("tts_announce error: %s", exc)
                return
            if cfg.get("confirm_mode") == "confirm":
                minutes = int(cfg.get("ladder_t1_min", 1) or 1)
                token = self._account_token.get(account_id, "")

                async def _do():
                    from app import moderation as _mod
                    return await _mod._execute_helix_timeout(
                        account_id, channel, author, v.category, v.severity,
                        v.rule_name, token, nickname or "",
                    )
                publish_event(account_id, channel, "intent", user=author,
                              text=f"предлагаю таймаут {minutes} мин ({v.category})",
                              localization={"text": caption("mod-feed.caption.timeout_proposal", minutes=minutes, category=v.category)},
                              severity=v.severity, intent={
                                  "kind": "timeout", "minutes": minutes,
                                  "user": author, "category": v.category,
                                  "_executor": _do,
                              })
            else:
                publish_event(account_id, channel, "violation", user=author,
                              text=shown, severity=v.severity, action="требует решения",
                              localization={**shown_localization, "action": caption("mod-feed.caption.decision_required")})
        except Exception as exc:
            logger.debug("modfeed moderation publish error: %s", exc)

    async def _role_reply_gate(self, account_id: int, is_mention: bool = False) -> tuple[bool, str]:
        """§R1: гейт «может ли бот этой роли ответить в чат» ДО генерации/send.

        lurker — молчит (только прямое @упоминание при mention_reply=true);
        director — никогда не пишет: его account only observes and plans;
        moderator — chat_activity: silent/moderation_only молчат, chatter болтает;
        voice_companion — пишет как обычный бот; его исходящие реплики также озвучиваются;
        chatter — разрешено (регресс). Кулдауны поверх гейта не затрагиваются.
        """
        role, cfg = await self._account_role(account_id)
        if role == "director":
            return False, "director account never chats"
        if role == "lurker":
            if is_mention and cfg.get("mention_reply"):
                return True, ""
            return False, "lurker молчит (mention_reply=off)" if not is_mention \
                else "lurker молчит (mention_reply=false)"
        if role == "moderator":
            activity = cfg.get("chat_activity", "chatter")
            if activity in ("silent", "moderation_only"):
                return False, f"moderator chat_activity={activity}"
            return True, ""
        if role == "voice_companion":
            return True, ""
        return True, ""

    async def _generate_and_send(self, account_id: int, channel: str, nickname: str, author: str, text: str, is_mention: bool, extra_context: str = "", force: bool = False) -> bool:
        # Глобальная пауза ботов (Режиссёр / хоткеи / Stream Deck)
        if not force:
            paused, rem = self.is_paused()
            if paused:
                await ai_log("director_pause", f"🤫 Глобальная пауза активна ({rem}с) — ответ пропущен", account_id, channel)
                return False

        # §R1 PLAN_SESSION_ROLES: гейт по роли — читается ДО send и до любой
        # генерации; кулдауны и guard действуют только поверх разрешённого ответа.
        try:
            allowed, gate_reason = await self._role_reply_gate(account_id, is_mention)
            if not allowed:
                await ai_log("role_gate", f"Молчу: {gate_reason}", account_id, channel)
                return False
        except Exception as exc:
            logger.debug("role gate error: %s", exc)
        # §7.1 §9: «Не перебивать стримера» — не отвечаем N сек после его реплики.
        # Прямые @упоминания бота это не перебивание — пропускаем guard.
        try:
            wait_sec = int(self.get_settings(account_id).get("dont_interrupt_streamer_sec") or 0)
            if wait_sec > 0 and not is_mention:
                last = self._last_streamer_msg.get((account_id, channel.lower()), 0.0)
                since = time.time() - last
                if since < wait_sec:
                    await ai_log("interrupt_guard",
                                 f"Стример писал {int(since)}с назад — молчу {wait_sec}с (не перебиваю)",
                                 account_id, channel)
                    return False
        except Exception as exc:
            logger.debug("interrupt guard error: %s", exc)

        # PLAN §2.1: merge с per-channel overrides (характер/активность/контекст/TTS).
        settings = await self._merged_settings(account_id, channel, self.get_settings(account_id))

        # AI-BUDGET AB-3: «Чат AI-анализ» выключен — платная модель чат не
        # читает и не генерирует ответы. Сырой лог чата уже записан в chat_log
        # (bot_manager._log), от этого переключателя он не зависит.
        if not settings.get("attention_chat_ai", True):
            await ai_log("attention", f"[Чат AI вимкнено] генерация пропущена в #{channel}", account_id, channel)
            return False

        # v10.4: контекст из чата собирается только если включён source «💬 чат».
        # При выключенном источнике бот опирается исключительно на стрим/стримера —
        # это полезно когда чат «тихий» / шумный, а нужен ответ по тому, что происходит на стриме.
        if settings.get("context_source_chat", True):
            context = await self._get_chat_context_async(account_id, channel)
        else:
            context = ""

        # v10.4: контекст со стрима — последнее vision-описание + транскрипция аудио.
        # Стучимся в stream_vision-менеджер только если pull источника включён.
        stream_ctx_text = ""
        if settings.get("context_source_stream") and settings.get("influence_observations", True):
            obs = _sv.get_last_observation(account_id, channel, max_age_sec=180)
            if obs:
                parts = []
                if obs.get("description"):
                    parts.append(f"Что бот сейчас видит на стриме: {obs['description']}")
                if obs.get("transcript"):
                    parts.append(f"Что бот сейчас слышит на стриме: {obs['transcript']}")
                # v16 BRAIN_PLAN §2: 3-5 последних реплик стримера (Whisper-транскрипт)
                try:
                    recent_lines = _sv.get_recent_streamer_lines(
                        account_id, channel, limit=5, max_age_sec=600,
                    )
                    if recent_lines:
                        lines_str = " | ".join(
                            f"[{int(float(l.get('at') or 0)) % 86400 // 3600:02d}:{int(float(l.get('at') or 0)) % 3600 // 60:02d}] {l.get('text','')}"
                            for l in recent_lines
                        )
                        parts.append(f"Последние реплики стримера: {lines_str}")
                except Exception:
                    pass
                if parts:
                    stream_ctx_text = "[Контекст стрима]\n" + "\n".join(parts)
                    await ai_log("ctx_stream", stream_ctx_text, account_id, channel)

        # Feature 4 / v10.4: контекст канала (текущая игра / название стрима)
        # Источники-аналоги: legacy `use_channel_context` и новый `context_source_streamer`.
        channel_ctx_text = ""
        helix_info: dict = {}
        if settings.get("use_channel_context") or settings.get("context_source_streamer") or settings.get("game_vocab_enabled"):
            token = self._account_token.get(account_id, "")
            if token:
                try:
                    info = await get_channel_info(channel, token)
                    helix_info = info or {}
                    channel_ctx_text = format_channel_context(helix_info)
                    if channel_ctx_text:
                        await ai_log("ctx_channel", channel_ctx_text, account_id, channel)
                except Exception:
                    pass

        # v10.4.5: per-game vocabulary switcher — добавляем игровой словарь
        # на основе Helix `game_name` (или forced категории из настроек).
        game_vocab_block = ""
        if settings.get("game_vocab_enabled"):
            try:
                forced = (settings.get("game_vocab_force_category") or "").strip()
                if forced:
                    category = forced
                else:
                    game_name = (helix_info.get("game_name") or "").strip()
                    category = match_game_category(game_name) if game_name else ""
                    if not category and helix_info.get("title"):
                        category = match_via_text(helix_info.get("title", ""))
                if category:
                    game_vocab_block = format_vocab_block(
                        category,
                        max_words=int(settings.get("game_vocab_max_words", 8) or 8),
                    )
                    if game_vocab_block:
                        await ai_log("ctx_game_vocab", f"Game vocab category={category}", account_id, channel)
            except Exception as exc:
                logger.debug("game_vocab error: %s", exc)

        # Feature 5: память про юзера (только если есть автор и память включена)
        memory_text = ""
        memory_facts: list = []
        if settings.get("use_long_term_memory") and author:
            try:
                mem = await user_memory.get_user_memory(account_id, author, structured=True)
                memory_text = user_memory.format_memory_for_prompt(mem)
                if mem:
                    memory_facts = [f.get("fact") if isinstance(f, dict) else f for f in (mem.get("facts") or [])]
                if memory_text:
                    await ai_log("ctx_memory", memory_text, account_id, channel)
            except Exception:
                pass

        # v12: контекст останніх повідомлень користувача
        user_history_block = ""
        if author and settings.get("use_long_term_memory"):
            try:
                history = await user_memory.get_message_history(account_id, channel, author, limit=5)
                if history:
                    user_history_block = user_memory.format_history_for_prompt(history, author)
                    if user_history_block:
                        await ai_log("ctx_user_history", f"Історія {author}: {len(history)} повідомлень", account_id, channel)
            except Exception:
                pass

        # v8 Feature 1: Конверсационная память (channel context + user-bot pairs из chat_log)
        conv_block = ""
        if settings.get("use_conversation_memory"):
            try:
                conv_block = await build_full_conversation_context(
                    account_id, channel, author,
                    max_channel=max(1, min(50, int(settings.get("context_channel_msgs", 10) or 10))),
                    max_pairs=max(0, min(20, int(settings.get("context_user_pairs", 3) or 3))),
                )
                if conv_block:
                    await ai_log("ctx_conv", f"Конверсационный контекст: {len(conv_block)} символов", account_id, channel)
            except Exception as exc:
                logger.warning("conv_memory error: %s", exc)

        # v8 Feature 11: streamer KB RAG
        kb_block = ""
        if settings.get("use_kb"):
            try:
                kb_entries = await retrieve_kb_for_query(
                    account_id, text or "", top_k=max(1, min(10, int(settings.get("kb_top_k", 3) or 3)))
                )
                kb_block = format_kb_block(kb_entries)
                if kb_block:
                    await ai_log("ctx_kb", f"KB hits: {len(kb_entries)}", account_id, channel)
            except Exception as exc:
                logger.warning("kb retrieval error: %s", exc)

        # v8 Feature 6: few-shot примеры стиля стримера
        few_shot_block = ""
        if settings.get("use_few_shot"):
            try:
                examples = await pick_style_examples(
                    account_id, channel=channel,
                    count=max(1, min(10, int(settings.get("few_shot_count", 4) or 4))),
                    # BRAIN_PLAN §3: top-K по косинусной близости темы чата
                    query=(text or context or "")[:300],
                )
                few_shot_block = format_few_shot_block(examples)
            except Exception as exc:
                logger.warning("few_shot error: %s", exc)

        # v10.2: мини-суммаризация — чтобы AI «знал» тему перед ответом.
        topic_summary = ""
        if settings.get("use_topic_summary") and context and not is_mention:
            try:
                topic_summary = await self.ai.generate_text(
                    prompt=(
                        "Суммаризируй одним предложением (до 50 слов), о чём СЕЙЧАС "
                        "говорят в Twitch-чате по этим сообщениям. Если темы нет — напиши «тема не определена».\n\n"
                        f"{context}"
                    ),
                    system="Ты аналитик чата. Вывод — одно предложение.",
                    account_id=account_id,
                    channel=channel,
                    temperature=0.2,
                )
                topic_summary = (topic_summary or "").strip()
                if topic_summary:
                    await ai_log("ctx_topic", f"Тема чата: {topic_summary}", account_id, channel)
            except Exception as exc:
                logger.warning("topic_summary error: %s", exc)

        # v10.2: эмоциональный детектор → тон ответа.
        mood_hint = ""
        if settings.get("use_mood_detector") and context:
            mood_hint = self._detect_mood(account_id, channel)
            if mood_hint:
                await ai_log("ctx_mood", f"Настроение чата: {mood_hint}", account_id, channel)

        topic_line = f"\n[Тема чата: {topic_summary}]" if topic_summary else ""
        mood_line = f"\n[Настроение чата: {mood_hint}]" if mood_hint else ""
        stream_block = f"\n\n{stream_ctx_text}" if stream_ctx_text else ""

        if is_mention:
            prompt = (
                f"Тебя упомянул пользователь {author} в Twitch-чате канала #{channel}.\n"
                f"Его сообщение (отвечай именно на него): «{text}»\n\n"
                f"{context}{topic_line}{mood_line}{stream_block}\n\n"
                "Дай короткий конкретный ответ ему (10-15 слов), на русском, "
                "по сути его сообщения, без общих фраз. Только текст ответа."
            )
            await ai_log("mention", f"@{nickname} упомянут пользователем {author}: {text}", account_id, channel)
        elif extra_context:
            prompt = (
                f"Ты сидишь в Twitch-чате канала #{channel}.\n\n"
                f"{context}{topic_line}{mood_line}{stream_block}\n\n"
                f"Задача: {extra_context}\n"
                "Напиши ОДНУ короткую естественную реплику (до 15 слов) на русском. "
                "Только текст реплики."
            )
            n_lines = len(context.splitlines()) if context else 0
            await ai_log("auto_chat", f"Ответ с контекстом задачи в #{channel} на основе {n_lines} сообщений: {extra_context[:60]}", account_id, channel)
        else:
            prompt = (
                f"Ты сидишь в Twitch-чате канала #{channel} и читаешь чат.\n\n"
                f"{context}{topic_line}{mood_line}{stream_block}\n\n"
                "Задача: написать ОДНУ короткую реплику (10-15 слов) ровно по теме. "
                "Учти настроение чата — если весело, реагируй ярче; если токсично, промолчи. "
                "Не задавай вопросов в пустоту. Если темы нет — верни пустую строку. "
                "Только текст реплики."
            )
            n_lines = len(context.splitlines()) if context else 0
            await ai_log("auto_chat", f"Авто-ответ в #{channel} на основе {n_lines} сообщений", account_id, channel)

        system = settings.get("system_prompt", "")
        active_variant_id: int | None = None

        # A/B prompt variants are account-scoped and independent of removed response patterns.
        if settings.get("use_ab_variants"):
            try:
                variant = await pick_variant_for_account(account_id)
                if variant and variant.get("system_prompt"):
                    system = variant["system_prompt"]
                    active_variant_id = int(variant["id"])
                    await ai_log("variant", f"Выбран вариант {variant.get('label')} (id={active_variant_id})", account_id, channel)
            except Exception as exc:
                logger.warning("variant pick error: %s", exc)

        # PROMPT-BASE PB-1/PB-2: общая база запреток для ВСЕХ ботов. Порядок
        # сборки system prompt: база → персона/личный промпт → правила подсистем.
        # База идёт ПЕРВОЙ, поэтому при конфликте содержания личный промпт бота
        # сильнее (идёт позже), но база остаётся жёстким минимумом.
        try:
            # Q18 (DEC-OWNER-004): запретные темы per-канал (+ пресет Twitch).
            prompt_base_block = await self._load_prompt_base_block(channel)
        except Exception as exc:
            logger.debug("prompt base block error: %s", exc)
            prompt_base_block = ""
        if prompt_base_block:
            system = f"{prompt_base_block}\n\n{system}".strip() if system else prompt_base_block

        try:
            # Разрешённые темы и поведение per-канал (+ пресет Twitch).
            allowed_topics_block = await self._load_allowed_topics_block(channel)
        except Exception as exc:
            logger.debug("allowed topics block error: %s", exc)
            allowed_topics_block = ""
        if allowed_topics_block:
            system = f"{system}\n\n{allowed_topics_block}".strip() if system else allowed_topics_block


        # v10.4.4: bio/persona блок (структурированная биография бота).
        persona_block = ""
        if settings.get("use_persona"):
            try:
                persona_block = await self._load_persona_block(account_id, channel)
                if persona_block:
                    await ai_log("ctx_persona", f"Persona-блок: {len(persona_block)} символов", account_id, channel)
            except Exception as exc:
                logger.warning("persona load error: %s", exc)

        # P8-C2: cross-bot shared user_facts удалены по вердикту владельца —
        # факты живут только per-bot в user_memory (общие мигрировали к ботам).

        # v10.4.5: multi-bot friendly chat — добавляем контекст из недавних friendly bot сообщений.
        friendly_block = ""
        if settings.get("multi_bot_chat_enabled"):
            try:
                ftr = self._get_friendly_tracker(account_id, channel, own_nick=nickname or "")
                friendly_block = ftr.context_block(max_messages=4)
            except Exception:
                friendly_block = ""

        # v10.4.7 Wave 4.2: conversation threads — добавляем контекст актуального треда.
        thread_block = ""
        if settings.get("threads_enabled"):
            try:
                tt = self._get_thread_tracker(account_id, channel)
                thr = tt.find_thread_for(text or "")
                if thr is not None:
                    max_msgs = int(settings.get("threads_max_messages_in_prompt", 6) or 6)
                    thread_block = format_thread_context(thr, max_messages=max_msgs)
                    if thread_block:
                        await ai_log("ctx_thread", f"thread={thr.thread_id} msgs={thr.n_messages}", account_id, channel)
            except Exception as exc:
                logger.debug("threads error: %s", exc)

        # v10.4.7 Wave 4.6: live-detection mimicry — подстраиваем стиль под профиль чата.
        mimicry_block = ""
        if settings.get("live_mimicry_enabled"):
            try:
                col = self._get_live_profile(account_id, channel)
                profile = col.compute()
                mimicry_block = mimicry_hint_block(profile)
                if mimicry_block:
                    await ai_log("ctx_mimicry", f"profile samples={profile.samples}", account_id, channel)
            except Exception as exc:
                logger.debug("live_mimicry error: %s", exc)

        # §5 PLAN_FEEDBACK_2908: профиль стримера (channel → fallback глобальный)
        streamer_profile_block = ""
        try:
            streamer_profile_block = await self._load_streamer_profile_block(account_id, channel)
            if streamer_profile_block:
                await ai_log("ctx_streamer_profile", f"streamer profile: {len(streamer_profile_block)} символов", account_id, channel)
        except Exception as exc:
            logger.debug("streamer profile block error: %s", exc)

        # C3: channel-scoped corrections learned through bot_intel affect replies.
        corrections_block = ""
        try:
            from app.routes_bot_intel import get_corrections_context
            corrections_block = get_corrections_context(account_id, channel)
            if corrections_block:
                await ai_log("ctx_corrections", "learned corrections added", account_id, channel)
        except Exception as exc:
            logger.debug("corrections context error: %s", exc)

        voice_capability_block = ""
        try:
            from app.voice_control import configured_capability_block
            voice_capability_block = await configured_capability_block(account_id, channel)
        except Exception as exc:
            logger.debug("voice capability block error: %s", exc)

        # Дополняем system всеми блоками
        # v16 BRAIN_PLAN §5: streamer lore (только approved)
        lore_block = ""
        if settings.get("streamer_lore_enabled", True):
            try:
                lore_rows = await streamer_lore.list_approved(account_id, channel, limit=10)
                lore_block = streamer_lore.format_lore_for_prompt(lore_rows)
                if lore_block:
                    await ai_log("ctx_lore", f"lore facts: {len(lore_rows)}", account_id, channel)
            except Exception as exc:
                logger.debug("lore block error: %s", exc)

        # v16 BRAIN_PLAN §4: live summary (последние 30-мин digest'ы)
        live_summary_block = ""
        if settings.get("summarizer_live_enabled", False):
            try:
                live_summary_block = await summarizer.get_live_digest(account_id, channel)
                if live_summary_block:
                    await ai_log("ctx_live_summary", "live summary added", account_id, channel)
            except Exception as exc:
                logger.debug("live summary error: %s", exc)

        # v16 BRAIN_PLAN §7: personality shift (временный mood)
        shift_block = ""
        try:
            shift_block = personality_shift.shift_manager.get_hint(account_id, channel)
        except Exception:
            shift_block = ""

        # §R4 PLAN_SESSION_ROLES: стиль болтуна (пресет/копирка/самообучение)
        chatter_style = ""
        try:
            _role, _rcfg = await self._account_role(account_id)
            if _role == "chatter" and settings.get("influence_mimicry", True):
                from app.bot_roles import chatter_style_block
                chatter_style = chatter_style_block(_rcfg)
                if chatter_style:
                    await ai_log("ctx_chatter_style", f"style block: {len(chatter_style)} симв", account_id, channel)
        except Exception as exc:
            logger.debug("chatter style error: %s", exc)

        extras = [s for s in (
            persona_block,
            channel_ctx_text,
            game_vocab_block,
            memory_text,
            user_history_block,
            streamer_profile_block,
            corrections_block,
            voice_capability_block,
            lore_block,
            live_summary_block,
            thread_block,
            mimicry_block,
            shift_block,
            conv_block,
            kb_block,
            few_shot_block,
            friendly_block,
            chatter_style,
        ) if s]
        if extras:
            system = (system + "\n\n" + "\n\n".join(extras)).strip()

        # Понижаем температуру по умолчанию — ответы чётче и в тему.
        temperature = settings.get("temperature")
        try:
            temperature = float(temperature) if temperature is not None else 0.4
        except (TypeError, ValueError):
            temperature = 0.4

        # v10.4.5: mood engine — корректируем temperature на основе настроения.
        if settings.get("mood_engine_enabled"):
            try:
                tr = self._get_mood_tracker(account_id, channel)
                if tr.is_throttled():
                    await ai_log(
                        "mood_throttle",
                        f"Mood={tr.mood:+.2f} ({tr.label()}) → self-throttle (skip)",
                        account_id, channel,
                    )
                    return False
                span = float(settings.get("mood_temperature_span", 0.3) or 0.3)
                old_t = temperature
                temperature = mood_to_temperature(tr.mood, base=temperature, span=span)
                if abs(temperature - old_t) > 0.01:
                    await ai_log(
                        "mood_temp",
                        f"Mood={tr.mood:+.2f} ({tr.label()}) → temperature {old_t:.2f} → {temperature:.2f}",
                        account_id, channel,
                    )
            except Exception as exc:
                logger.debug("mood adjust error: %s", exc)
        # v10.4.4: batched-gen — если включено, кооперируемся с другими
        # ботами на этом канале и делаем один запрос вместо N. Иначе обычный путь.
        if settings.get("batched_gen_enabled"):
            try:
                self._batched_gen.enabled = True
                self._batched_gen.wait_ms = int(settings.get("batched_gen_wait_ms", 300) or 300)
                self._batched_gen.max_batch = int(settings.get("batched_gen_max_batch", 4) or 4)
            except (TypeError, ValueError):
                pass

            async def _single(p: str, s: str) -> str:
                return await self.ai.generate_text(
                    p, system=s, account_id=account_id, channel=channel,
                    temperature=temperature,
                )

            async def _batch(p: str, s: str, n: int) -> str:
                return await self.ai.generate_text(
                    p, system=s, account_id=account_id, channel=channel,
                    temperature=temperature,
                )

            style_hint = (settings.get("system_prompt", "") or "")[:80] or "обычный зритель"
            reply = await self._batched_gen.request(
                channel.lower().lstrip("#"),
                prompt, system, style_hint,
                single_gen=_single, batch_gen=_batch,
            )
        else:
            reply = await self.ai.generate_text(
                prompt, system=system, account_id=account_id, channel=channel,
                temperature=temperature,
            )
        if not reply:
            return False

        reply = reply.strip().strip('"').strip("'")
        # Если AI решил что нечего сказать (вернул пустую строку или одно слово-реакцию) — молчим.
        if not reply or _is_noise_message(reply):
            await ai_log("skip", f"AI решил промолчать (контента нет): «{reply}»", account_id, channel)
            return False

        # v8 Feature 9: Hallucination guard
        if settings.get("use_hallucination_guard"):
            try:
                history_text = conv_block or context or ""
                check = check_hallucination(reply, user_facts=memory_facts, user_history_text=history_text, strict=True)
                if not check.safe:
                    await ai_log("hallucination", f"Обнаружены фразы: {check.matches}", account_id, channel)
                    reply = check.cleaned_text
                    if not reply.strip():
                        return False
            except Exception as exc:
                logger.warning("hallucination guard error: %s", exc)

        # v8 Feature 7: Проверяем бан-темы в ответе
        if settings.get("use_banned_topics"):
            try:
                hit = await check_banned_topics_db(account_id, reply)
                if hit:
                    await ai_log("banned_topic_out", f"Ответ был в бан-теме: {hit.pattern}", account_id, channel)
                    if hit.mode == "fallback" and hit.fallback:
                        reply = hit.fallback
                    else:
                        return False
            except Exception:
                pass

        reply = await self._filter_reply(account_id, reply, channel)

        # v14 MODERATION_PLAN §3: модерация ответов бота через движок
        # (правила + built-in). Заблокированный ответ → бот молчит, событие в лог.
        try:
            from app import moderation as _mod
            _out = await _mod.check_outgoing(account_id, channel, reply, source="bot_out")
            if not _out.ok:
                await ai_log(
                    "moderation_out",
                    f"Ответ бота заблокирован модерацией ({_mod.summarize(_out.verdicts)}): {reply[:120]}",
                    account_id, channel,
                )
                try:
                    await log_per_bot(account_id, channel, "system",
                                      f"Модерация заблокировала ответ бота ({_out.verdicts[0].category})", level="warning")
                except Exception:
                    pass
                return False  # заглушка не отправляется — бот просто молчит
            reply = _out.text
        except Exception as exc:
            logger.warning("moderation outgoing error: %s", exc)

        # v8 Feature 10: Output filter (heuristic)
        if settings.get("use_output_filter"):
            try:
                report = filter_output_heuristic(
                    reply,
                    max_length=450,
                    forbid_links=bool(settings.get("block_links", False)),
                )
                if not report.safe:
                    await ai_log("output_filter", f"Ответ отфильтрован: {report.reasons}", account_id, channel)
                    if not report.suggested:
                        return False
                reply = report.suggested or reply
            except Exception as exc:
                logger.warning("output filter error: %s", exc)

        length_mode = str(settings.get("response_length", "short") or "short").lower()
        max_words = {"short": 15, "medium": 35, "long": 80}.get(length_mode, 15)
        words = reply.split()
        if len(words) > max_words:
            reply = " ".join(words[:max_words]).rstrip(".,!?;:") + "..."

        # v8 Feature 8: Cooldown per-topic
        if settings.get("use_topic_cooldown"):
            try:
                hit = await check_topic_cooldown(
                    account_id, channel, reply,
                    window_sec=int(settings.get("topic_cooldown_sec", 60) or 60),
                    min_shared=int(settings.get("topic_min_shared", 2) or 2),
                )
                if hit:
                    await ai_log("topic_cooldown", f"Тема совпадает с недавней ({hit['topic']}), пропускаю", account_id, channel)
                    return False
            except Exception as exc:
                logger.warning("topic cooldown error: %s", exc)

        # v10.4.4: anti-detection — self-similarity check
        if settings.get("anti_detection_enabled") and settings.get("self_similarity_check"):
            try:
                window = int(settings.get("self_similarity_window", 30) or 30)
                threshold = float(settings.get("self_similarity_threshold", 0.55) or 0.55)
                recent_bot_msgs = self._recent_bot_messages(account_id, channel, nickname, window)
                sim = compute_self_similarity(reply, recent_bot_msgs)
                if sim >= threshold:
                    await ai_log(
                        "antidet_similar",
                        f"Ответ слишком похож на недавние ({sim:.2f} ≥ {threshold}), скипаю: {reply[:80]}",
                        account_id,
                        channel,
                    )
                    return False
            except Exception as exc:
                logger.warning("self_similarity check error: %s", exc)

        # v10.4.4: anti-detection — опечатки (только если явно включено)
        if settings.get("anti_detection_enabled") and settings.get("humanize_typos"):
            try:
                rate = float(settings.get("humanize_typos_rate", 0.05) or 0.05)
                reply = apply_typo(reply, TypoConfig(rate=rate))
            except Exception as exc:
                logger.warning("typo simulation error: %s", exc)

        # Тихий режим — AI думает, но не отправляет
        if settings.get("silent_mode"):
            await ai_log("silent", f"[Тихий режим] Не отправляю в #{channel}: {reply}", account_id, channel)
            return False

        # v10.4.4: anti-detection — гауссова задержка «бот печатает».
        if settings.get("anti_detection_enabled") and settings.get("humanize_delay"):
            try:
                delay = humanized_delay_seconds(
                    reply,
                    base=float(settings.get("humanize_delay_base", 1.2) or 1.2),
                    per_char=float(settings.get("humanize_delay_per_char", 0.04) or 0.04),
                    sigma=float(settings.get("humanize_delay_sigma", 0.35) or 0.35),
                    cap=float(settings.get("humanize_delay_cap", 8.0) or 8.0),
                )
                await asyncio.sleep(delay)
            except Exception as exc:
                logger.warning("humanize delay error: %s", exc)

        await ai_log("send", f"Отправляю в #{channel}: {reply}", account_id, channel)
        # v11: логування AI відповіді
        try:
            await log_per_bot(account_id, channel, "ai", f"AI відповідь: {reply[:200]}",
                            details={"author": author, "text_trigger": (text or "")[:100], "reply": reply[:200]})
        except Exception:
            pass
        ok = await self.send_fn(account_id, channel, reply)
        if ok:
            self._mark_replied(account_id, channel)
            if author:
                anti_spam.mark_replied(account_id, channel, author)
            self._add_to_buffer(account_id, channel, nickname, reply)
            # PLAN §9h: ответ бота в replay-сессию (для последующего воспроизведения).
            try:
                _sid = self._replay_sessions.get((int(account_id), (channel or "").lower()))
                if _sid:
                    await _replay.add_event(_sid, "bot_out", {"text": reply, "reply_to": author})
            except Exception as exc:
                logger.debug("replay bot_out error: %s", exc)
            # v12: зберігаємо відповідь бота в історію користувача
            try:
                await user_memory.add_message_history(account_id, channel, author or nickname, reply, is_bot=True)
            except Exception:
                pass
            # v11: TTS — озвучуємо відповідь бота через OBS
            try:
                # PLAN §2.1: per-channel override tts_mute — глушим озвучку в этом канале.
                # §7.1 §9: tts_reply_percent — «не озвучивать каждое сообщение».
                # Task 6: Временное глушение озвучки (Cinematic / TTS Mute) — чат-боты продолжают писать.
                from app.tts_mute_state import is_tts_muted
                if not is_tts_muted(channel)[0] and not settings.get("tts_mute") and await self._tts_should_speak(account_id, channel):
                    from app.tts_voice_policy import authorize_tts
                    bot_role, _ = await self._account_role(account_id)
                    source = "voice_companion_reply" if bot_role == "voice_companion" else "bot_reply"
                    decision = await authorize_tts(
                        account_id, channel, source,
                        actor_role="bot", actor_id=str(account_id), text=reply,
                    )
                    if decision["ok"]:
                        from app.tts_engine import get_tts_engine
                        tts = get_tts_engine()
                        # PLAN §6: эмоция из mood engine + разнообразие от temperature
                        emotion = self._pick_reply_emotion(account_id, channel, settings)
                        await tts.speak(
                            account_id, channel, reply, emotion=emotion,
                            provider_override=decision.get("provider_override", ""),
                            voice_override=decision.get("voice_override", ""),
                        )
            except Exception as exc:
                logger.debug("tts speak error: %s", exc)
            # v10.4.7 Wave 4.2: feed thread-tracker нашим ответом (для bot_interventions).
            try:
                if settings.get("threads_enabled"):
                    tt = self._get_thread_tracker(account_id, channel)
                    tt.feed(nickname or "bot", reply, is_bot_response=True)
            except Exception as exc:
                logger.debug("threads feed bot-out error: %s", exc)
            # v10.4.7 Wave 4.7: записываем в replay.
            try:
                await self.record_replay_event(account_id, channel, "bot_out", {"text": reply, "author": nickname})
            except Exception as exc:
                logger.debug("replay bot_out error: %s", exc)
            # v8: записываем тему ответа + bump variant counter
            if settings.get("use_topic_cooldown"):
                try:
                    await record_bot_topic(account_id, channel, reply)
                except Exception:
                    pass
            if active_variant_id:
                try:
                    await increment_variant_count(account_id, active_variant_id)
                except Exception:
                    pass
            # v10.5: push to chat-highlight widget (auto-mode).
            try:
                from app.widgets import push_chat_highlight
                await push_chat_highlight(
                    reply, author=nickname, kind="ai",
                    account_id=account_id, channel=channel,
                )
            except Exception:
                pass
            return True
        return False
