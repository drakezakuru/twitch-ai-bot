"""SQLite база данных для хранения аккаунтов, каналов и настроек AI.

Singleton-коннекшен (S): один коннект на всё приложение, закрывается на shutdown.
Это ускоряет горячие пути (chat-analyzer открывает БД на каждое сообщение).
"""

import asyncio
import hashlib
import os
import shutil
import sqlite3
from datetime import datetime

import aiosqlite
import json
import logging
from pathlib import Path

from app import bot_roles
from app.runtime_paths import DB_PATH, PROJECT_ROOT

logger = logging.getLogger(__name__)

# Singleton state
_shared_db: aiosqlite.Connection | None = None
# asyncio.Lock привязывается к event loop, на котором впервые использована.
# Тесты создают свежий loop на каждый тест, поэтому лок пересоздаётся при смене
# loop (см. PLAN_REMAINING P1: flaky _init_lock is bound to a different loop).
_init_lock: asyncio.Lock | None = None
_init_lock_loop: asyncio.AbstractEventLoop | None = None


async def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout=5000")
        await db.execute("PRAGMA journal_mode=WAL")
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nickname TEXT NOT NULL UNIQUE,
                token TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                channel_name TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                auto_analyze INTEGER DEFAULT 0,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
                UNIQUE(account_id, channel_name)
            );

            CREATE TABLE IF NOT EXISTS chat_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER,
                channel TEXT NOT NULL,
                author TEXT NOT NULL,
                message TEXT NOT NULL,
                is_bot INTEGER DEFAULT 0,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            -- v10.2: 👍/👎 фидбэк на ответы AI
            CREATE TABLE IF NOT EXISTS ai_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL DEFAULT '',
                event_type TEXT NOT NULL DEFAULT 'send',
                message TEXT NOT NULL,
                rating INTEGER NOT NULL DEFAULT 0,  -- +1 = 👍, -1 = 👎
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS triggers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                keyword TEXT NOT NULL,
                response TEXT NOT NULL DEFAULT '',
                use_ai INTEGER DEFAULT 1,
                enabled INTEGER DEFAULT 1,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS banlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
                UNIQUE(account_id, username)
            );

            CREATE TABLE IF NOT EXISTS quick_phrases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                phrase TEXT NOT NULL,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS snippets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                name TEXT NOT NULL DEFAULT 'unnamed',
                text TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS word_filter (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                word TEXT NOT NULL,
                action TEXT NOT NULL DEFAULT 'block',
                channel TEXT DEFAULT '',
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS event_responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                response TEXT NOT NULL DEFAULT '',
                use_ai INTEGER DEFAULT 0,
                chance INTEGER DEFAULT 100,
                enabled INTEGER DEFAULT 1,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS action_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT '',
                actor TEXT NOT NULL DEFAULT '',
                revert_payload TEXT NOT NULL DEFAULT '',
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS personas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                system_prompt TEXT NOT NULL DEFAULT '',
                is_active INTEGER DEFAULT 0,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS scheduled_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                message TEXT NOT NULL,
                min_interval INTEGER NOT NULL DEFAULT 5,
                max_interval INTEGER NOT NULL DEFAULT 30,
                use_ai INTEGER DEFAULT 0,
                ai_prompt TEXT NOT NULL DEFAULT '',
                enabled INTEGER DEFAULT 1,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );

            -- Feature 5: долговременная память per-user
            CREATE TABLE IF NOT EXISTS user_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                facts TEXT NOT NULL DEFAULT '[]',
                msg_count INTEGER NOT NULL DEFAULT 0,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
                UNIQUE(account_id, username)
            );

            -- v8 Feature 11: streamer knowledge base (RAG)
            CREATE TABLE IF NOT EXISTS streamer_kb (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                topic TEXT NOT NULL,
                content TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '',
                priority INTEGER NOT NULL DEFAULT 5,
                enabled INTEGER NOT NULL DEFAULT 1,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );

            -- v8 Feature 6: few-shot style examples (стример помечает свои сообщения)
            CREATE TABLE IF NOT EXISTS style_examples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL DEFAULT '',
                message TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );

            -- v8 Feature 7: запрещённые темы (per-account)
            CREATE TABLE IF NOT EXISTS banned_topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                pattern TEXT NOT NULL,
                fallback TEXT NOT NULL DEFAULT '',
                mode TEXT NOT NULL DEFAULT 'silent',
                enabled INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );

            -- A/B варианты системного промпта, независимые от удалённых response patterns
            CREATE TABLE IF NOT EXISTS prompt_variants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                label TEXT NOT NULL DEFAULT 'A',
                system_prompt TEXT NOT NULL DEFAULT '',
                weight INTEGER NOT NULL DEFAULT 50,
                count INTEGER NOT NULL DEFAULT 0,
                likes INTEGER NOT NULL DEFAULT 0,
                dislikes INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );

            -- v8 Feature 2: лайки на ответы бота
            CREATE TABLE IF NOT EXISTS bot_response_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_log_id INTEGER NOT NULL,
                prompt_variant_id INTEGER,
                feedback INTEGER NOT NULL,
                source TEXT NOT NULL DEFAULT 'panel',
                note TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- v8 Feature 8: лог тем bot-ответов для cooldown per-topic
            CREATE TABLE IF NOT EXISTS bot_topic_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                topic TEXT NOT NULL,
                full_text TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- v10.3 4B: engagement-метрики на каждый ответ бота
            CREATE TABLE IF NOT EXISTS bot_engagement (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_log_id INTEGER NOT NULL UNIQUE,
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL DEFAULT '',
                support INTEGER NOT NULL DEFAULT 0,
                mentions INTEGER NOT NULL DEFAULT 0,
                replies INTEGER NOT NULL DEFAULT 0,
                breakthrough INTEGER NOT NULL DEFAULT 0,
                computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chat_log_id) REFERENCES chat_log(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_streamer_kb_account ON streamer_kb(account_id);
            CREATE INDEX IF NOT EXISTS idx_style_examples_account ON style_examples(account_id);
            CREATE INDEX IF NOT EXISTS idx_banned_topics_account ON banned_topics(account_id, enabled);
            CREATE INDEX IF NOT EXISTS idx_prompt_variants_account ON prompt_variants(account_id, enabled);
            CREATE INDEX IF NOT EXISTS idx_bot_response_feedback_log ON bot_response_feedback(chat_log_id);
            CREATE INDEX IF NOT EXISTS idx_bot_topic_log_chan ON bot_topic_log(account_id, channel, created_at);
            CREATE INDEX IF NOT EXISTS idx_chat_log_author ON chat_log(account_id, channel, author, timestamp);
            CREATE INDEX IF NOT EXISTS idx_bot_engagement_account ON bot_engagement(account_id, channel, computed_at);

            -- ========== v11: НОВІ ТАБЛИЦІ ==========

            -- Блок 1: Профіль стримера (1 row per account)
            CREATE TABLE IF NOT EXISTS streamer_profile (
                account_id   INTEGER NOT NULL DEFAULT 0,
                channel      TEXT NOT NULL DEFAULT '',  -- §5: '' = глобальный профиль
                age          INTEGER DEFAULT 0,
                gender       TEXT DEFAULT '',
                location     TEXT DEFAULT '',
                occupation   TEXT DEFAULT '',
                bio          TEXT DEFAULT '',
                interests    TEXT DEFAULT '[]',   -- JSON array
                favorite_games TEXT DEFAULT '[]', -- JSON array
                streaming_style TEXT DEFAULT '',  -- educational / entertaining / competitive
                likes        TEXT DEFAULT '[]',
                dislikes     TEXT DEFAULT '[]',
                auto_updated INTEGER DEFAULT 1,
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (account_id, channel)
                -- §5: FK на accounts убран — account_id=0 = панельный слой
                -- (глобальные/per-channel профили из карточки «Настройки»)
            );

            -- Блок 1: Фото обличчя стримера (base64)
            CREATE TABLE IF NOT EXISTS streamer_face (
                account_id INTEGER NOT NULL DEFAULT 0,
                channel    TEXT NOT NULL DEFAULT '',  -- §5: '' = глобальное фото
                face_image_base64 TEXT NOT NULL DEFAULT '',
                mime_type  TEXT NOT NULL DEFAULT 'image/jpeg',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (account_id, channel)
                -- §5: FK на accounts убран — account_id=0 = панельный слой
                -- (глобальные/per-channel профили из карточки «Настройки»)
            );

            -- Блок 1: Персистентна пам'ять розмов бота
            CREATE TABLE IF NOT EXISTS bot_conversation_history (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                channel    TEXT NOT NULL,
                role       TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
                author     TEXT NOT NULL DEFAULT '',
                content    TEXT NOT NULL,
                metadata_json TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_bch_acc_chan_time ON bot_conversation_history(account_id, channel, created_at);
            CREATE INDEX IF NOT EXISTS idx_bch_role ON bot_conversation_history(role);

            -- Блок 1: Прив'язаність бота до стримера/чату
            CREATE TABLE IF NOT EXISTS bot_streamer_affinity (
                account_id   INTEGER PRIMARY KEY,
                contact_level INTEGER DEFAULT 50 CHECK(contact_level BETWEEN 0 AND 100),
                chat_affinity INTEGER DEFAULT 50 CHECK(chat_affinity BETWEEN 0 AND 100),
                auto_adjust  INTEGER DEFAULT 0,
                updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );

            -- Блок 1: Per-channel перезаписи параметрів бота
            CREATE TABLE IF NOT EXISTS channel_overrides (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id     INTEGER NOT NULL,
                channel        TEXT NOT NULL,
                overrides_json TEXT NOT NULL DEFAULT '{}',
                enabled        INTEGER DEFAULT 1,
                updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
                UNIQUE(account_id, channel)
            );
            CREATE INDEX IF NOT EXISTS idx_ch_ov_acc ON channel_overrides(account_id, enabled);

            -- v15: affinity is scoped to bot/channel/user. Empty values mean
            -- the account-level streamer/chat fallback used by old clients.
            CREATE TABLE IF NOT EXISTS bot_affinity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL DEFAULT '',
                username TEXT NOT NULL DEFAULT '',
                contact_level INTEGER NOT NULL DEFAULT 50 CHECK(contact_level BETWEEN 0 AND 100),
                chat_affinity INTEGER NOT NULL DEFAULT 50 CHECK(chat_affinity BETWEEN 0 AND 100),
                auto_adjust INTEGER NOT NULL DEFAULT 0,
                manual_lock INTEGER NOT NULL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
                UNIQUE(account_id, channel, username)
            );
            CREATE INDEX IF NOT EXISTS idx_bot_affinity_scope ON bot_affinity(account_id, channel, username);
            CREATE TABLE IF NOT EXISTS bot_affinity_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL DEFAULT '',
                username TEXT NOT NULL DEFAULT '',
                contact_level INTEGER NOT NULL,
                chat_affinity INTEGER NOT NULL,
                auto_adjust INTEGER NOT NULL DEFAULT 0,
                manual_lock INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'manual',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_bot_affinity_history_scope ON bot_affinity_history(account_id, channel, username, created_at);

            -- Блок 1: Контекст raid-сесій
            -- §5 аудит 30.08: streamer_events/streamer_stats/voice_speakers/
            -- raid_context_log/shared_chatter_facts — мёртвые (0 обращений),
            -- удалены; DROP для старых БД — в конце init_db.

            -- Блок 1: Спільні факти про користувачів між ботами

            -- Блок 7: Конфіг уваги бота (Attention Filter + Batching)
            CREATE TABLE IF NOT EXISTS bot_attention_config (
                account_id INTEGER PRIMARY KEY,
                attention_mode TEXT NOT NULL DEFAULT 'everyone'
                    CHECK(attention_mode IN ('everyone','streamer_only','chat_only','streamer_and_chat','custom')),
                batch_window_sec REAL DEFAULT 5.0,
                batch_max_size   INTEGER DEFAULT 5,
                min_messages_to_respond INTEGER DEFAULT 2,
                ignore_noise INTEGER DEFAULT 1,
                cooldown_after_reply_sec REAL DEFAULT 30.0,
                max_replies_per_minute INTEGER DEFAULT 3,
                -- §7.1 §9 PLAN_FEEDBACK_2908: не перебивать стримера + не озвучивать всё
                dont_interrupt_streamer_sec INTEGER DEFAULT 0,
                tts_reply_percent INTEGER DEFAULT 100,
                reply_to_mentions INTEGER DEFAULT 1,
                -- О6 PLAN.md: ключевые слова (отдельный тумблер + список)
                reply_to_keywords INTEGER DEFAULT 0,
                reply_keywords TEXT DEFAULT '',
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );

            -- Блок 7: Користувачі чату (авто-заповнюється)
            CREATE TABLE IF NOT EXISTS chat_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                username TEXT NOT NULL,
                role TEXT DEFAULT 'viewer' CHECK(role IN ('viewer','mod','vip','subscriber','streamer')),
                enabled INTEGER DEFAULT 1,
                message_count INTEGER DEFAULT 0,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(account_id, channel, username)
            );
            CREATE INDEX IF NOT EXISTS idx_chat_users_enabled ON chat_users(account_id, channel, enabled);
            CREATE INDEX IF NOT EXISTS idx_chat_users_last_seen ON chat_users(account_id, channel, last_seen);

            -- Блок 8: Логи per-bot
            CREATE TABLE IF NOT EXISTS bot_logs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                channel    TEXT NOT NULL DEFAULT '',
                level      TEXT NOT NULL CHECK(level IN ('debug','info','warning','error')),
                category   TEXT NOT NULL CHECK(category IN ('chat','ai','tts','trigger','event','system')),
                message    TEXT NOT NULL,
                details    TEXT NOT NULL DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_bot_logs_acc_time ON bot_logs(account_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_bot_logs_level ON bot_logs(level);
            CREATE INDEX IF NOT EXISTS idx_bot_logs_category ON bot_logs(category);

            -- Блок 3: Глобальні TTS настройки
            CREATE TABLE IF NOT EXISTS tts_settings (
                id INTEGER PRIMARY KEY CHECK(id=1),
                provider TEXT DEFAULT 'web_speech' CHECK(provider IN ('web_speech','piper','elevenlabs')),
                voice     TEXT DEFAULT '',
                speed     REAL DEFAULT 1.0,
                volume    REAL DEFAULT 1.0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- Блок 3: Per-bot TTS конфіг
            CREATE TABLE IF NOT EXISTS tts_bot_config (
                account_id INTEGER PRIMARY KEY,
                provider TEXT DEFAULT '' CHECK(provider IN ('','web_speech','piper','elevenlabs','xtts')),
                voice     TEXT DEFAULT '',
                emotion_preset TEXT DEFAULT 'neutral',
                volume    REAL DEFAULT 1.0,
                enabled   INTEGER DEFAULT 0,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );

            -- Блок 3: Голосові пресети
            CREATE TABLE IF NOT EXISTS tts_voice_presets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                voice_id TEXT NOT NULL,
                label    TEXT NOT NULL,
                lang     TEXT DEFAULT 'ru',
                emotion  TEXT DEFAULT 'neutral',
                UNIQUE(provider, voice_id)
            );

            -- Блок 3: Voice clones (локальні + хмарні)
            CREATE TABLE IF NOT EXISTS voice_clones (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL UNIQUE,
                provider   TEXT NOT NULL CHECK(provider IN ('elevenlabs','xtts','piper','playht','external')),
                voice_id   TEXT DEFAULT '',
                api_key_ref TEXT DEFAULT '',
                external_api_url TEXT DEFAULT '',
                sample_path TEXT DEFAULT '',
                config_path TEXT DEFAULT '',
                source_url TEXT DEFAULT '',
                lang       TEXT DEFAULT 'ru',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                uploaded_by TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_voice_clones_provider ON voice_clones(provider);

            CREATE TABLE IF NOT EXISTS custom_behavior_presets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                values_json TEXT NOT NULL DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
                UNIQUE(account_id, name)
            );
            CREATE INDEX IF NOT EXISTS idx_custom_presets_account ON custom_behavior_presets(account_id);

            -- v12: найденные моменты для клипов (§9g Clip Detector)
            CREATE TABLE IF NOT EXISTS clip_moments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL DEFAULT '',
                rate REAL DEFAULT 0,
                avg_rate REAL DEFAULT 0,
                clip_url TEXT DEFAULT '',
                timestamp TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_clip_moments_acc ON clip_moments(account_id, created_at);

            -- v12 §25.4: Именованные кастомные AI-провайдеры (base_url + ключ + список моделей)
            CREATE TABLE IF NOT EXISTS custom_providers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                base_url TEXT NOT NULL DEFAULT '',
                api_key TEXT NOT NULL DEFAULT '',
                models TEXT NOT NULL DEFAULT '[]',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- v12: Memory per-user — останні N повідомлень користувача (контекст для AI)
            CREATE TABLE IF NOT EXISTS user_message_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                username TEXT NOT NULL,
                message TEXT NOT NULL,
                is_bot INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_umh_acc_chan_user ON user_message_history(account_id, channel, username, created_at);

            -- v16 BRAIN_PLAN §4: Stream Summarizer — прогоны стрима
            CREATE TABLE IF NOT EXISTS summarizer_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                run_date TEXT NOT NULL,                 -- YYYY-MM-DD
                period_start TIMESTAMP NOT NULL,
                period_end   TIMESTAMP NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'running', 'done', 'failed', 'cancelled')),
                lang TEXT NOT NULL DEFAULT 'ru',
                summary_md TEXT NOT NULL DEFAULT '',
                events_json TEXT NOT NULL DEFAULT '[]',
                funny_json  TEXT NOT NULL DEFAULT '[]',
                chat_json   TEXT NOT NULL DEFAULT '[]',
                lore_json   TEXT NOT NULL DEFAULT '[]',
                progress_sec INTEGER NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                finished_at TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
                UNIQUE(account_id, channel, run_date)
            );
            CREATE INDEX IF NOT EXISTS idx_sumr_scope ON summarizer_runs(account_id, channel, run_date);

            -- v16 BRAIN_PLAN §4: чекпоинты (по 30-мин окнам) для resumable прогонов
            CREATE TABLE IF NOT EXISTS summarizer_checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                window_start TIMESTAMP NOT NULL,
                window_end   TIMESTAMP NOT NULL,
                digest TEXT NOT NULL DEFAULT '',
                n_messages INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (run_id) REFERENCES summarizer_runs(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_sumcp_run ON summarizer_checkpoints(run_id, window_start);

            -- v16 BRAIN_PLAN §4: live-сводки (каждые 30 мин)
            CREATE TABLE IF NOT EXISTS summarizer_live (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                window_start TIMESTAMP NOT NULL,
                window_end   TIMESTAMP NOT NULL,
                digest TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_sumlive_scope ON summarizer_live(account_id, channel, window_start);

            -- ========== v14 MODERATION_PLAN §1: модерация чата ==========

            -- Правила модерации (per-account; channel '' = все каналы).
            -- Кастомные правила из этой таблицы имеют приоритет над встроенными
            -- словарями из app/moderation_dicts/.
            CREATE TABLE IF NOT EXISTS moderation_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT 'custom'
                    CHECK(category IN ('custom','insult','hate','threat','sexual','spam','links','caps','repeat')),
                pattern TEXT NOT NULL,
                action TEXT NOT NULL DEFAULT 'block'
                    CHECK(action IN ('replace','block','timeout','log')),
                severity INTEGER NOT NULL DEFAULT 3 CHECK(severity BETWEEN 1 AND 5),
                enabled INTEGER NOT NULL DEFAULT 1,
                lang TEXT NOT NULL DEFAULT '',
                -- роли чата, к которым правило НЕ применяется ('streamer,mod,vip'; '' = ко всем)
                exempt_roles TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_mod_rules_acc ON moderation_rules(account_id, enabled);

            -- Журнал нарушений: всё, что поймал движок (входящий чат, ответы бота,
            -- ручные отправки, EventSub). Угрозы пишутся всегда, даже при action=block.
            CREATE TABLE IF NOT EXISTS moderation_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL DEFAULT '',
                username TEXT NOT NULL DEFAULT '',
                rule_id INTEGER,
                rule_name TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                severity INTEGER NOT NULL DEFAULT 0,
                action_taken TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'chat_in'
                    CHECK(source IN ('chat_in','bot_out','api_send','eventsub','antispam',
                                     'timeout_recommend','punishment_recommend')),
                message_excerpt TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_mod_events_acc_time ON moderation_events(account_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_mod_events_user ON moderation_events(account_id, username, created_at);

            -- Q03 (DEC-OWNER-004): база правил модерации per-канал + пресет Twitch.
            -- НЕ глобальная таблица: ключ — channel (login, lower, без '#'); применяется
            -- движком только ботам с ролью «модератор». UNIQUE даёт идемпотентный засев
            -- пресета (INSERT OR IGNORE).
            CREATE TABLE IF NOT EXISTS moderation_channel_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel TEXT NOT NULL,
                pattern TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'custom',
                action TEXT NOT NULL DEFAULT 'block'
                    CHECK(action IN ('replace','block','timeout','log')),
                severity INTEGER NOT NULL DEFAULT 3 CHECK(severity BETWEEN 1 AND 5),
                action_ext TEXT,
                enabled INTEGER DEFAULT 1,
                name TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(channel, pattern)
            );
            CREATE INDEX IF NOT EXISTS idx_mod_channel_rules ON moderation_channel_rules(channel, enabled);
        """)
        await db.commit()

        # Copy legacy account-scoped affinity once into the new global scope.
        # Existing values remain authoritative for old clients and routes.
        await db.execute(
            "INSERT OR IGNORE INTO bot_affinity "
            "(account_id, contact_level, chat_affinity, auto_adjust) "
            "SELECT account_id, contact_level, chat_affinity, auto_adjust "
            "FROM bot_streamer_affinity"
        )
        await db.commit()

        # ---------- Миграции для существующих БД ----------
        # PLAN_FEEDBACK_3008 §9: снапшот БД ПЕРЕД миграциями (P0-страховка):
        # WAL-чекпоинт + копия в data/backups/ + проверка копии (quick_check).
        # Дедуп по sha256 — при каждом рестарте без изменений схемы копия не
        # создаётся заново. Большие миграции (§2 summarizer, §6 roles) вызывают
        # backup_before_migration(..., required=True) сами, со своим label.
        await backup_before_migration("pre-migration", db=db)
        # OPS_PLAN §3: категория 'fallback' в bot_logs — иначе событие fallback
        # (OpenRouter 429/5xx → Ollama) отвергается CHECK-констрейнтом и панель
        # его никогда не видит. SQLite нельзя расширить CHECK без пересоздания.
        await _migrate_bot_logs_fallback_category(db)
        # Q01/Q03: ленивая схема модерации — единый источник DDL (см. функцию ниже)
        await ensure_moderation_schema(db)
        # Q26 (DEC-OWNER-014): журнал наказаний — одной строкой, как в соглашении плана
        from app.moderation_journal import ensure_schema as _journal_schema
        await _journal_schema()
        # C7: response patterns удалены; полезные A/B-варианты переносим на account scope.
        await _migrate_response_patterns_to_prompt_variants(db)
        # PLAN_FEEDBACK_2908 §5: профиль/фото стримера могут быть per-channel
        # (PK account_id+channel). Старые строки становятся глобальными ('').
        await _migrate_streamer_channel(db)
        # §5: база знаний стримера и примеры реплик (mimicry) — тоже per-channel.
        await _add_column_if_missing(db, "streamer_kb", "channel", "TEXT DEFAULT ''")
        await _add_column_if_missing(db, "style_examples", "channel", "TEXT DEFAULT ''")
        # §7.1 §9: «не перебивать стримера» и «не озвучивать каждый ответ»
        await _add_column_if_missing(db, "bot_attention_config", "dont_interrupt_streamer_sec", "INTEGER DEFAULT 0")
        await _add_column_if_missing(db, "bot_attention_config", "tts_reply_percent", "INTEGER DEFAULT 100")
        await _add_column_if_missing(db, "bot_attention_config", "reply_to_mentions", "INTEGER DEFAULT 1")
        # О6 PLAN.md: ключевые слова
        await _add_column_if_missing(db, "bot_attention_config", "reply_to_keywords", "INTEGER DEFAULT 0")
        await _add_column_if_missing(db, "bot_attention_config", "reply_keywords", "TEXT DEFAULT ''")
        # §12.2: провайдер 'xtts' в tts_bot_config (иначе per-bot клоны недостижимы)
        await _migrate_tts_bot_config_xtts(db)
        # REWORK F+ (03.09, вопрос владельца про vision у кастом-провайдеров):
        # отдельный список Vision-моделей у именованных провайдеров
        await _add_column_if_missing(db, "custom_providers", "vision_models", "TEXT DEFAULT '[]'")
        # §7.1 §9k: расширенные категории AI-feedback (длинный/токсичный/не в стиле…)
        await _add_column_if_missing(db, "ai_feedback", "category", "TEXT DEFAULT ''")
        # Feature 2: refresh_token / token_expires_at в accounts
        await _add_column_if_missing(db, "accounts", "refresh_token", "TEXT DEFAULT ''")
        await _add_column_if_missing(db, "accounts", "token_expires_at", "INTEGER DEFAULT 0")
        # v12 P0 §10: триггеры — привязка к каналу, счётчик срабатываний, последний запуск
        await _add_column_if_missing(db, "triggers", "channel", "TEXT DEFAULT ''")
        # PLAN §2.1: word_filter — привязка слова к каналу ('' = все каналы)
        await _add_column_if_missing(db, "word_filter", "channel", "TEXT DEFAULT ''")
        await _add_column_if_missing(db, "triggers", "fires", "INTEGER DEFAULT 0")
        await _add_column_if_missing(db, "triggers", "last_fired_at", "TEXT")
        # Feature 6: proxy на уровне аккаунта
        await _add_column_if_missing(db, "accounts", "proxy", "TEXT DEFAULT ''")
        # Feature 3: per-account флаг EventSub
        await _add_column_if_missing(db, "accounts", "eventsub_enabled", "INTEGER DEFAULT 0")
        # v9 AP: Sentiment timeline — чистая колонка sentiment в chat_log (-1/0/+1)
        await _add_column_if_missing(db, "chat_log", "sentiment", "INTEGER DEFAULT 0")
        # Stream Vision: per-channel флаг захвата кадров/аудио со стрима
        await _add_column_if_missing(db, "channels", "stream_vision_enabled", "INTEGER DEFAULT 0")
        await _add_column_if_missing(db, "channels", "twitch_channel_id", "TEXT DEFAULT ''")
        await _add_column_if_missing(db, "channels", "twitch_channel_login", "TEXT DEFAULT ''")
        # v10.4.3: per-account AI override (что бы боты не толкались в одну модель).
        # Если пусто — используется глобальный AIService config.
        await _add_column_if_missing(db, "accounts", "ai_provider_override", "TEXT DEFAULT ''")
        await _add_column_if_missing(db, "accounts", "ai_chat_model_override", "TEXT DEFAULT ''")
        await _add_column_if_missing(db, "accounts", "ai_vision_model_override", "TEXT DEFAULT ''")
        await _add_column_if_missing(db, "accounts", "openrouter_api_key_override", "TEXT DEFAULT ''")
        # v10.4.3+: универсальный override-ключ (используется для любого провайдера: Gemini/OpenAI/Anthropic/OpenRouter).
        # ``openrouter_api_key_override`` оставлен для backward-compat.
        await _add_column_if_missing(db, "accounts", "ai_api_key_override", "TEXT DEFAULT ''")
        # v10.4.3: follow-raid + раскрытие времени активности на новом канале.
        await _add_column_if_missing(db, "accounts", "raid_follow_enabled", "INTEGER DEFAULT 0")
        await _add_column_if_missing(db, "accounts", "raid_follow_active_min", "INTEGER DEFAULT 10")
        await _add_column_if_missing(db, "accounts", "raid_follow_active_max", "INTEGER DEFAULT 60")
        await _add_column_if_missing(db, "accounts", "raid_follow_part_after", "INTEGER DEFAULT 1")
        # v10.4.4: bio/persona — структурированная биография бота (JSON-сериализация BotPersona).
        await _add_column_if_missing(db, "accounts", "persona_json", "TEXT DEFAULT ''")
        # v11: Режим спостереження — бот пише в БД, але НЕ в чат
        await _add_column_if_missing(db, "accounts", "observation_only", "INTEGER DEFAULT 0")
        # v11: Тихий аналіз — аналізує чат без відповідей
        await _add_column_if_missing(db, "accounts", "silent_analysis", "INTEGER DEFAULT 0")
        # v11: Зберігати всі повідомлення каналу в chat_log
        await _add_column_if_missing(db, "accounts", "log_all_messages", "INTEGER DEFAULT 1")
        # PLAN_FEEDBACK_3008 §6: роли ботов (chatter|moderator|voice_companion|lurker).
        # §9: снапшот с required=True — без бэкапа схему не меняем.
        await backup_before_migration("roles-accounts", db=db, required=True)
        await _add_column_if_missing(db, "accounts", "bot_role", f"TEXT DEFAULT '{bot_roles.DEFAULT_ROLE}'")
        await _add_column_if_missing(db, "accounts", "role_config_json", "TEXT DEFAULT '{}'")
        # Legacy tables remain intact. Destructive cleanup requires a separate,
        # owner-approved migration after retention and restore are verified.
        # v10.3 5: расширение action_log — кто сделал + payload для отката
        await _add_column_if_missing(db, "action_log", "actor", "TEXT DEFAULT ''")
        await _add_column_if_missing(db, "action_log", "revert_payload", "TEXT DEFAULT ''")
        # v10.4.4 (Style fine-tune): rating + source + trigger_msg в style_examples.
        # rating: -1 = «не так писать», 0 = нейтральный (черновик), +1 = «вот так круто».
        # source: 'manual' / 'auto_bot' / 'rated' / 'imported'.
        # trigger_msg: что спровоцировало этот ответ (нужно для JSONL-экспорта в fine-tune).
        await _add_column_if_missing(db, "style_examples", "rating", "INTEGER DEFAULT 0")
        await _add_column_if_missing(db, "style_examples", "source", "TEXT DEFAULT 'manual'")
        await _add_column_if_missing(db, "style_examples", "trigger_msg", "TEXT DEFAULT ''")
        # v12: кастомний AI провайдер
        await _add_column_if_missing(db, "accounts", "custom_ai_base_url", "TEXT DEFAULT ''")
        # Q15c (E4): резерв «локальная Ollama» — включается вручную per-бот
        await _add_column_if_missing(db, "accounts", "ai_local_fallback", "INTEGER DEFAULT 0")
        # Q15d (E5): smart-routing чат-моделей per-бот (JSON: enabled/threshold/
        # simple_provider/simple_model/complex_provider/complex_model; пусто = глобальный)
        await _add_column_if_missing(db, "accounts", "ai_smart_routing_json", "TEXT DEFAULT ''")
        # Q16 F5: автозапись replay-сессий per-бот; NULL = наследовать глобальный
        # replay_auto_record (legacy-fallback), 0/1 — явный выбор бота
        await _add_column_if_missing(db, "accounts", "replay_auto_record", "INTEGER")
        await _add_column_if_missing(db, "accounts", "custom_ai_api_key", "TEXT DEFAULT ''")
        # v12: TTS per-bot speed
        await _add_column_if_missing(db, "tts_bot_config", "speed", "REAL DEFAULT 1.0")
        # v13 §2 WIDGETS_PLAN: колір віджета TTS-бота (default gold #FFD700)
        # та емодзі-іконка для tts-bot overlay.
        await _add_column_if_missing(db, "tts_bot_config", "widget_color", "TEXT DEFAULT '#FFD700'")
        await _add_column_if_missing(db, "tts_bot_config", "widget_emoji", "TEXT DEFAULT '🎙️'")
        # v13 §8 WIDGETS_PLAN: емодзі-обгортка TTS-повідомлень.
        await _add_column_if_missing(db, "tts_bot_config", "emoji_prefix", "TEXT DEFAULT ''")
        await _add_column_if_missing(db, "tts_bot_config", "emoji_suffix", "TEXT DEFAULT ''")
        # ---------- v14 MODERATION_PLAN: режимы и настройки модерации ----------
        # Режим работы движка: off / log_only / replace / full (§1).
        await _add_column_if_missing(db, "accounts", "moderation_mode", "TEXT DEFAULT 'off'")
        # §3.4: может ли бот таймаутить через Helix (по умолчанию OFF).
        await _add_column_if_missing(db, "accounts", "moderation_can_timeout", "INTEGER DEFAULT 0")
        # §2: пороги антиспама зрителей.
        await _add_column_if_missing(db, "accounts", "antispam_viewer_enabled", "INTEGER DEFAULT 0")
        await _add_column_if_missing(db, "accounts", "antispam_caps_pct", "INTEGER DEFAULT 70")
        await _add_column_if_missing(db, "accounts", "antispam_repeat_count", "INTEGER DEFAULT 3")
        await _add_column_if_missing(db, "accounts", "antispam_links", "INTEGER DEFAULT 1")
        await _add_column_if_missing(db, "accounts", "antispam_emote_pct", "INTEGER DEFAULT 80")
        await _add_column_if_missing(db, "accounts", "antispam_exempt_roles", "TEXT DEFAULT 'streamer,mod,vip'")
        # §3: EventSub-хук message-событий (если включены).
        await _add_column_if_missing(db, "accounts", "eventsub_chat_messages", "INTEGER DEFAULT 0")
        # Q01 (DEC-OWNER-013): конкретное действие правила вместо лестницы по severity.
        # NULL/'' = прежнее поведение (action + severity); существующие правила не переписываются.
        # В колонку action нельзя добавить 'ban' — там CHECK-ограничение, поэтому действие
        # хранится отдельно и перекрывает action только когда задано явно.
        await _add_column_if_missing(db, "moderation_rules", "action_ext", "TEXT")
        await db.commit()

        # v10.4.5/v10.4.6 (widgets): таблицы виджетов. Идемпотентно (CREATE IF NOT EXISTS).
        # spotify_creds оставляем для back-compat — если кто уже завёл,
        # пусть лежит, новых обращений к ней не будет (Now Playing manual).
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS stream_goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                done INTEGER DEFAULT 0,
                sort_order INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS sub_goal (
                id INTEGER PRIMARY KEY,
                target INTEGER DEFAULT 50,
                current INTEGER DEFAULT 0,
                theme TEXT DEFAULT 'tree',
                title TEXT DEFAULT '',
                last_event_at TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS now_playing (
                id INTEGER PRIMARY KEY,
                kind TEXT DEFAULT 'music',
                text TEXT DEFAULT '',
                subtext TEXT DEFAULT '',
                icon_url TEXT DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS schedule_blocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_time TEXT NOT NULL,
                title TEXT NOT NULL,
                emoji TEXT DEFAULT '',
                sort_order INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS widget_titles (
                widget TEXT PRIMARY KEY,
                title TEXT DEFAULT ''
            );
            -- v10.4.7: counters (death/streak/whatever).
            CREATE TABLE IF NOT EXISTS counters (
                key TEXT PRIMARY KEY,
                label TEXT DEFAULT '',
                value INTEGER DEFAULT 0,
                animation TEXT DEFAULT 'minimal',
                color TEXT DEFAULT '',
                emoji TEXT DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            -- v10.4.7: stream_session (для REC + uptime виджета).
            CREATE TABLE IF NOT EXISTS stream_session (
                id INTEGER PRIMARY KEY,
                start_time TIMESTAMP,
                is_live INTEGER DEFAULT 0
            );
            -- v10.4.7: recent_events (follow/sub/cheer/raid → ticker, mascot).
            CREATE TABLE IF NOT EXISTS recent_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                username TEXT DEFAULT '',
                amount INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            -- v10.4.7: lower_third (singleton).
            CREATE TABLE IF NOT EXISTS lower_third (
                id INTEGER PRIMARY KEY,
                name TEXT DEFAULT '',
                tagline TEXT DEFAULT '',
                social TEXT DEFAULT '',
                avatar_url TEXT DEFAULT '',
                theme TEXT DEFAULT 'minimal',
                visible INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            -- v10.4.7: mascot_state (singleton; настройка маскота).
            CREATE TABLE IF NOT EXISTS mascot_state (
                id INTEGER PRIMARY KEY,
                preset TEXT DEFAULT 'blob',
                custom_url TEXT DEFAULT '',
                idle_timeout_sec INTEGER DEFAULT 300,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            -- v10.5: chat_highlight (OBS-виджет последнего ответа AI / выделенного сообщения).
            CREATE TABLE IF NOT EXISTS chat_highlight (
                id INTEGER PRIMARY KEY,
                text TEXT DEFAULT '',
                author TEXT DEFAULT '',
                kind TEXT DEFAULT 'ai',
                theme TEXT DEFAULT 'glow',
                visible INTEGER DEFAULT 1,
                auto_mode INTEGER DEFAULT 1,
                display_sec INTEGER DEFAULT 15,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            -- v10.5: chat_roulette (случайный зритель из чата).
            CREATE TABLE IF NOT EXISTS chat_roulette (
                id INTEGER PRIMARY KEY,
                winner TEXT DEFAULT '',
                participants TEXT DEFAULT '[]',
                theme TEXT DEFAULT 'wheel',
                spin_duration_sec INTEGER DEFAULT 5,
                auto_interval_min INTEGER DEFAULT 0,
                visible INTEGER DEFAULT 1,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            -- v10.5: combo_counter (комбо одинаковых сообщений).
            CREATE TABLE IF NOT EXISTS combo_counter (
                id INTEGER PRIMARY KEY,
                word TEXT DEFAULT '',
                combo_count INTEGER DEFAULT 0,
                min_combo INTEGER DEFAULT 5,
                theme TEXT DEFAULT 'fire',
                visible INTEGER DEFAULT 1,
                decay_sec INTEGER DEFAULT 10,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            -- v10.5: song_request_queue (очередь запросов песен).
            CREATE TABLE IF NOT EXISTS song_request_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                requested_by TEXT NOT NULL DEFAULT '',
                channel TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'queued',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_sr_status ON song_request_queue(status, created_at);
            -- v10.5: song_request_settings (настройки виджета).
            CREATE TABLE IF NOT EXISTS song_request_settings (
                id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 1,
                max_queue INTEGER DEFAULT 50,
                theme TEXT DEFAULT 'neon',
                visible INTEGER DEFAULT 1,
                show_count INTEGER DEFAULT 4,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            -- v10.4.8: anime_runner_state (бегущий анимешный аватар).
            -- v10.4.9: добавлены кошачьи ушки/перчатки/кроссовки/шорты + path-mode + path_points.
            CREATE TABLE IF NOT EXISTS anime_runner_state (
                id INTEGER PRIMARY KEY,
                hair_color TEXT DEFAULT '#f5f5f5',
                outfit_color TEXT DEFAULT '#3a4',
                accent_color TEXT DEFAULT '#ffaa44',
                eye_color TEXT DEFAULT '#3a8fff',
                corner TEXT DEFAULT 'br',
                speed TEXT DEFAULT 'normal',
                size TEXT DEFAULT 'M',
                pause_chance REAL DEFAULT 0.15,
                idle_timeout_sec INTEGER DEFAULT 300,
                ears_enabled INTEGER DEFAULT 1,
                ears_color TEXT DEFAULT '#222',
                ears_inner_color TEXT DEFAULT '#ff7eb9',
                gloves_enabled INTEGER DEFAULT 0,
                gloves_color TEXT DEFAULT '#ffffff',
                shoes_color TEXT DEFAULT '#ffffff',
                shirt_pattern TEXT DEFAULT 'palm',
                shorts_color TEXT DEFAULT '',
                path_mode TEXT DEFAULT 'lane',
                path_points TEXT DEFAULT '[]',
                random_period_sec INTEGER DEFAULT 90,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        # v10.4.9: ALTER TABLE для существующих v10.4.8 баз.
        for _col, _type, _default in (
            ("ears_enabled", "INTEGER", "1"),
            ("ears_color", "TEXT", "'#222'"),
            ("ears_inner_color", "TEXT", "'#ff7eb9'"),
            ("gloves_enabled", "INTEGER", "0"),
            ("gloves_color", "TEXT", "'#ffffff'"),
            ("shoes_color", "TEXT", "'#ffffff'"),
            ("shirt_pattern", "TEXT", "'palm'"),
            ("shorts_color", "TEXT", "''"),
            ("path_mode", "TEXT", "'lane'"),
            ("path_points", "TEXT", "'[]'"),
            ("random_period_sec", "INTEGER", "90"),
        ):
            try:
                await db.execute(
                    f"ALTER TABLE anime_runner_state ADD COLUMN "
                    f"{_col} {_type} DEFAULT {_default}"
                )
            except Exception:
                pass  # column exists already
        for _col, _type, _default in (
            ("sample_duration_sec", "REAL", "0"),
            ("status", "TEXT", "'ready'"),
        ):
            try:
                await db.execute(
                    f"ALTER TABLE voice_clones ADD COLUMN {_col} {_type} DEFAULT {_default}"
                )
            except Exception:
                pass
        await db.execute(
            "INSERT OR IGNORE INTO sub_goal (id, target, current, theme, title) "
            "VALUES (1, 50, 0, 'tree', 'Цель: 50 сабов')"
        )
        await db.execute(
            "INSERT OR IGNORE INTO now_playing (id, kind, text) VALUES (1, 'music', '')"
        )
        for _w, _t in (
            ("goals", "Цели на стрим"),
            ("now-playing", "Сейчас"),
            ("sub-goal", "Цель: 50 сабов"),
            ("schedule", "Расписание"),
            ("animated-bg", ""),
            ("counter-death", "Смертей"),
            ("counter-streak", "🔥 Streak"),
            ("uptime", ""),
            ("follower-ticker", ""),
            ("lower-third", ""),
            ("mascot", ""),
            ("anime-runner", ""),
            ("chat-highlight", "💬 AI в чате"),
            ("chat-roulette", "🎰 Рулетка"),
            ("combo-counter", "🔥 Комбо"),
            ("song-request", "🎵 Песни"),
        ):
            await db.execute(
                "INSERT OR IGNORE INTO widget_titles (widget, title) VALUES (?, ?)",
                (_w, _t),
            )
        # v10.4.7 seeds.
        await db.execute(
            "INSERT OR IGNORE INTO counters (key, label, animation, emoji, color) "
            "VALUES ('death', 'Смертей', 'skull', '💀', '#ff4444')"
        )
        await db.execute(
            "INSERT OR IGNORE INTO counters (key, label, animation, emoji, color) "
            "VALUES ('streak', 'Streak', 'fire', '🔥', '#ffaa00')"
        )
        await db.execute(
            "INSERT OR IGNORE INTO stream_session (id, is_live) VALUES (1, 0)"
        )
        await db.execute(
            "INSERT OR IGNORE INTO lower_third (id, name, tagline, social, theme, visible) "
            "VALUES (1, '', '', '', 'minimal', 0)"
        )
        await db.execute(
            "INSERT OR IGNORE INTO mascot_state (id, preset, idle_timeout_sec) "
            "VALUES (1, 'blob', 300)"
        )
        # v10.5 seeds.
        await db.execute(
            "INSERT OR IGNORE INTO chat_highlight "
            "(id, text, author, kind, theme, visible, auto_mode, display_sec) "
            "VALUES (1, '', '', 'ai', 'glow', 1, 1, 15)"
        )
        await db.execute(
            "INSERT OR IGNORE INTO chat_roulette "
            "(id, winner, participants, theme, spin_duration_sec, auto_interval_min, visible) "
            "VALUES (1, '', '[]', 'wheel', 5, 0, 1)"
        )
        await db.execute(
            "INSERT OR IGNORE INTO combo_counter "
            "(id, word, combo_count, min_combo, theme, visible, decay_sec) "
            "VALUES (1, '', 0, 5, 'fire', 1, 10)"
        )
        await db.execute(
            "INSERT OR IGNORE INTO song_request_settings "
            "(id, enabled, max_queue, theme, visible, show_count) "
            "VALUES (1, 1, 50, 'neon', 1, 4)"
        )
        # v10.4.8 seeds.
        await db.execute(
            "INSERT OR IGNORE INTO anime_runner_state "
            "(id, hair_color, outfit_color, accent_color, eye_color, "
            "corner, speed, size, pause_chance, idle_timeout_sec) "
            "VALUES (1, '#f5f5f5', '#3a4', '#ffaa44', '#3a8fff', "
            "'br', 'normal', 'M', 0.15, 300)"
        )
        # v11 seeds: TTS global settings
        await db.execute(
            "INSERT OR IGNORE INTO tts_settings (id, provider, voice, speed, volume) "
            "VALUES (1, 'web_speech', '', 1.0, 1.0)"
        )
        # v11 seeds: дефолтні голосові пресети
        for _prov, _vid, _label, _lang in (
            ("piper", "ru_RU-irina-medium", "Irina (RU)", "ru"),
            ("piper", "ru_RU-ruslan-medium", "Ruslan (RU)", "ru"),
            ("piper", "en_US-lessac-medium", "Lessac (EN)", "en"),
            ("elevenlabs", "21m00Tcm4TlvDq8ikWAM", "Rachel (EN)", "en"),
            ("elevenlabs", "ErXwobaYiN019PkySvjV", "Adam (EN)", "en"),
            ("elevenlabs", "pNInz6obpgDQGcFmaJgB", "Antoni (EN)", "en"),
        ):
            await db.execute(
                "INSERT OR IGNORE INTO tts_voice_presets (provider, voice_id, label, lang) "
                "VALUES (?, ?, ?, ?)",
                (_prov, _vid, _label, _lang),
            )
        await db.commit()

        # PLAN_FEEDBACK_2908 P0: схема виджетов (17 таблиц + ALTER-миграции
        # stream_goals.percent / song_request_settings.cooldown_sec и др.)
        # обязана накатываться на старте панели, а не при обращении к роутам.
        # Ленивый импорт — widgets.py импортирует database (избегаем цикла).
        from app.widgets import ensure_widgets_schema  # noqa: E402
        await ensure_widgets_schema()

        from app.voice_control import ensure_schema as ensure_voice_control_schema  # noqa: E402
        await ensure_voice_control_schema()

        from app.tts_voice_policy import ensure_schema as ensure_tts_voice_policy_schema  # noqa: E402
        await ensure_tts_voice_policy_schema(db)

        from app.moderator_console_routes import ensure_schema as ensure_moderator_console_schema  # noqa: E402
        await ensure_moderator_console_schema(db)

        # Q34 (DEC-OWNER-019): пачки ботов — две новые таблицы, legacy не трогаем.
        from app.bot_packs import ensure_schema as ensure_bot_packs_schema  # noqa: E402
        await ensure_bot_packs_schema(db)

        from app.moderator_media_routes import ensure_schema as ensure_moderator_media_schema  # noqa: E402
        await ensure_moderator_media_schema(db)

        from app.moderator_sound_routes import ensure_schema as ensure_moderator_sound_schema  # noqa: E402
        await ensure_moderator_sound_schema(db)
        from app.tts_output_routes import ensure_schema as ensure_tts_output_schema  # noqa: E402
        await ensure_tts_output_schema(db)
        from app.song_request_service import ensure_schema as ensure_song_request_schema  # noqa: E402
        await ensure_song_request_schema(db)
        from app.director import ensure_schema as ensure_director_schema  # noqa: E402
        await ensure_director_schema(db)
        from app.director_manual import ensure_schema as ensure_director_manual_schema  # noqa: E402
        await ensure_director_manual_schema(db)
        # Владелец 27.09 (вечер): календарь недели — каналы/пачки/TTS-моменты одной сеткой
        from app.weekly_schedule import ensure_schema as ensure_weekly_schedule_schema  # noqa: E402
        await ensure_weekly_schedule_schema(db)

        # MOD-04 (moderator-site): idempotent ms_* tables (outbox, stop state, revisions).
        from app.moderator_site_schema import ensure_schema as ensure_moderator_site_schema  # noqa: E402
        await ensure_moderator_site_schema(db)
        from app.moderator_site_identity import ensure_schema as ensure_moderator_site_identity  # noqa: E402
        await ensure_moderator_site_identity(db)
        # MOD-13..17: ms_* таблицы функциональных модулей — все ensure идемпотентны.
        from app.moderator_site_permissions import ensure_schema as _ms_permissions  # noqa: E402
        await _ms_permissions(db)
        from app.moderator_site_library import ensure_schema as _ms_library  # noqa: E402
        await _ms_library(db)
        from app.moderator_site_uploads import ensure_schema as _ms_uploads  # noqa: E402
        await _ms_uploads(db)
        from app.moderator_site_cues import ensure_schema as _ms_cues  # noqa: E402
        await _ms_cues(db)
        from app.moderator_site_media import ensure_schema as _ms_media  # noqa: E402
        await _ms_media(db)
        from app.moderator_site_sound import ensure_schema as _ms_sound  # noqa: E402
        await _ms_sound(db)
        from app.moderator_site_tts import ensure_schema as _ms_tts  # noqa: E402
        await _ms_tts(db)
        from app.moderator_site_outputs import ensure_schema as _ms_outputs  # noqa: E402
        await _ms_outputs(db)
        from app.moderator_site_queue import ensure_schema as _ms_queue  # noqa: E402
        await _ms_queue(db)
        from app.moderator_site_controls import ensure_schema as _ms_controls  # noqa: E402
        await _ms_controls(db)
        from app.bot_fleet import ensure_schema as _bot_fleet_schema  # noqa: E402
        await _bot_fleet_schema(db)
        from app.proxy_pool import ensure_schema as _proxy_pool_schema  # noqa: E402
        await _proxy_pool_schema(db)

        # P8-C2: разовый переезд общей памяти → per-bot user_memory (идемпотентно).
        from app.shared_user_facts import migrate_shared_facts_once  # noqa: E402
        await migrate_shared_facts_once(db)

    logger.info("База данных инициализирована: %s", DB_PATH)


async def _migrate_streamer_channel(db: aiosqlite.Connection) -> None:
    """PLAN_FEEDBACK_2908 §5: streamer_profile/streamer_face — per-channel.

    Старые таблицы (PK account_id) пересоздаются с PK (account_id, channel);
    существующие строки становятся глобальными (channel=''). Идемпотентно."""
    cur = await db.execute("PRAGMA table_info(streamer_profile)")
    cols = [r[1] for r in await cur.fetchall()]
    if "channel" not in cols:
        await db.execute("""
            CREATE TABLE streamer_profile_new (
                account_id INTEGER NOT NULL DEFAULT 0,
                channel TEXT NOT NULL DEFAULT '',
                age INTEGER DEFAULT 0,
                gender TEXT DEFAULT '',
                location TEXT DEFAULT '',
                occupation TEXT DEFAULT '',
                bio TEXT DEFAULT '',
                interests TEXT DEFAULT '[]',
                favorite_games TEXT DEFAULT '[]',
                streaming_style TEXT DEFAULT '',
                likes TEXT DEFAULT '[]',
                dislikes TEXT DEFAULT '[]',
                auto_updated INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (account_id, channel)
            )""")
        await db.execute("""
            INSERT INTO streamer_profile_new
                (account_id, channel, age, gender, location, occupation, bio,
                 interests, favorite_games, streaming_style, likes, dislikes,
                 auto_updated, created_at, updated_at)
            SELECT account_id, '', age, gender, location, occupation, bio,
                 interests, favorite_games, streaming_style, likes, dislikes,
                 auto_updated, created_at, updated_at
            FROM streamer_profile""")
        await db.execute("DROP TABLE streamer_profile")
        await db.execute("ALTER TABLE streamer_profile_new RENAME TO streamer_profile")
        logger.info("Миграция §5: streamer_profile переведён на PK (account_id, channel)")

    cur = await db.execute("PRAGMA table_info(streamer_face)")
    cols = [r[1] for r in await cur.fetchall()]
    if "channel" not in cols:
        await db.execute("""
            CREATE TABLE streamer_face_new (
                account_id INTEGER NOT NULL DEFAULT 0,
                channel TEXT NOT NULL DEFAULT '',
                face_image_base64 TEXT NOT NULL DEFAULT '',
                mime_type TEXT NOT NULL DEFAULT 'image/jpeg',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (account_id, channel)
            )""")
        await db.execute("""
            INSERT INTO streamer_face_new
                (account_id, channel, face_image_base64, mime_type, updated_at)
            SELECT account_id, '', face_image_base64, mime_type, updated_at
            FROM streamer_face""")
        await db.execute("DROP TABLE streamer_face")
        await db.execute("ALTER TABLE streamer_face_new RENAME TO streamer_face")
        logger.info("Миграция §5: streamer_face переведён на PK (account_id, channel)")

    # W4: copy legacy global profiles into configured channels without ever
    # replacing an existing channel-specific profile. Retaining the legacy row
    # is intentional rollback compatibility; runtime no longer resolves it.
    await db.execute("""
        INSERT OR IGNORE INTO streamer_profile
            (account_id, channel, age, gender, location, occupation, bio,
             interests, favorite_games, streaming_style, likes, dislikes,
             auto_updated, created_at, updated_at)
        SELECT p.account_id, '#' || lower(trim(c.channel_name)), p.age, p.gender,
               p.location, p.occupation, p.bio, p.interests, p.favorite_games,
               p.streaming_style, p.likes, p.dislikes, p.auto_updated,
               p.created_at, p.updated_at
        FROM streamer_profile p JOIN channels c
          ON (p.account_id = 0 OR c.account_id = p.account_id)
        WHERE p.channel = '' AND trim(c.channel_name) != ''
    """)
    await db.commit()


async def _migrate_tts_bot_config_xtts(db: aiosqlite.Connection) -> None:
    """§12.2: расширить CHECK provider в tts_bot_config на 'xtts'.

    SQLite не расширяет CHECK без пересоздания; идемпотентно по sql в
    sqlite_master (у свежих БД 'xtts' уже в CHECK)."""
    cur = await db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='tts_bot_config'"
    )
    row = await cur.fetchone()
    if not row or "'xtts'" in (row[0] or ""):
        return
    await db.execute("""
        CREATE TABLE tts_bot_config_new (
            account_id INTEGER PRIMARY KEY,
            provider TEXT DEFAULT '' CHECK(provider IN ('','web_speech','piper','elevenlabs','xtts')),
            voice     TEXT DEFAULT '',
            emotion_preset TEXT DEFAULT 'neutral',
            volume    REAL DEFAULT 1.0,
            speed     REAL DEFAULT 1.0,
            emoji_prefix TEXT DEFAULT '',
            emoji_suffix TEXT DEFAULT '',
            enabled   INTEGER DEFAULT 0,
            FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
        )""")
    await db.execute("""
        INSERT OR IGNORE INTO tts_bot_config_new
            (account_id, provider, voice, emotion_preset, volume, speed,
             emoji_prefix, emoji_suffix, enabled)
        SELECT account_id, provider, voice, emotion_preset, volume, speed,
             emoji_prefix, emoji_suffix, enabled
        FROM tts_bot_config""")
    await db.execute("DROP TABLE tts_bot_config")
    await db.execute("ALTER TABLE tts_bot_config_new RENAME TO tts_bot_config")
    logger.info("Миграция §12.2: tts_bot_config.provider допускает 'xtts'")


async def _add_column_if_missing(db: aiosqlite.Connection, table: str, column: str, defn: str) -> None:
    cursor = await db.execute(f"PRAGMA table_info({table})")
    rows = await cursor.fetchall()
    cols = [r[1] for r in rows]
    if column not in cols:
        try:
            await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {defn}")
            logger.info("Миграция: %s.%s добавлен", table, column)
        except Exception as exc:
            logger.warning("Не удалось добавить %s.%s: %s", table, column, exc)


def migration_backup_keep() -> int:
    """Сколько предмиграционных снапшотов хранить (§9)."""
    try:
        return max(1, int(os.getenv("MIGRATION_BACKUP_KEEP", "10")))
    except ValueError:
        return 10


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_backup_copy(path: Path) -> bool:
    """«Проверка восстановления» (§9): копия открывается, quick_check ok, таблицы на месте."""
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = con.execute("PRAGMA quick_check").fetchone()
            if not row or row[0] != "ok":
                return False
            row = con.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()
            return bool(row) and row[0] >= 1
        finally:
            con.close()
    except Exception:
        return False


async def backup_before_migration(
    label: str = "pre-migration",
    *,
    db: aiosqlite.Connection | None = None,
    required: bool = False,
    force: bool = False,
) -> Path | None:
    """PLAN_FEEDBACK_3008 §9: снапшот data/bot.db ПЕРЕД миграцией.

    Кладёт `bot.db.<label>-<timestamp>.db` в `data/backups/` рядом с zip-бэкапами:
    - WAL-чекпоинт → консистентная копия (модные при миграциях потери не страшны);
    - «проверка восстановления»: копия открывается read-only, quick_check ok,
      таблицы на месте — иначе битый файл удаляется, а не лежит «псевдобэкапом»;
    - дедуп по sha256: одинаковая БД при каждом рестарте НЕ копируется заново;
    - ротация: MIGRATION_BACKUP_KEEP последних снапшотов (дефолт 10).

    required=True — бросить RuntimeError, если снапшот не удался: большие
    миграции (§2 summarizer per-channel, §6 roles) обязаны стопориться до
    изменения схемы, а не «ехать по живому» без страховки.
    Возвращает путь снапшота или None (нет файла / свежая пустая БД / дедуп / отказ).
    """
    if not DB_PATH.exists() or DB_PATH.stat().st_size == 0:
        return None  # свежая установка — миграционный снапшот не нужен
    try:
        backup_dir = DB_PATH.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        hash_file = backup_dir / ".pre_migration_last_hash"
        digest = _sha256_file(DB_PATH)
        if not force and hash_file.exists() and hash_file.read_text().strip() == digest:
            return None
        if db is not None:
            try:
                await db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception as exc:
                logger.debug("wal_checkpoint перед снапшотом не удался: %s", exc)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        dest = backup_dir / f"bot.db.{label}-{stamp}.db"
        shutil.copy2(DB_PATH, dest)
        if not _verify_backup_copy(dest):
            dest.unlink(missing_ok=True)
            raise RuntimeError(f"копия не прошла проверку: {dest.name}")
        hash_file.write_text(digest)
        keep = migration_backup_keep()
        files = sorted(backup_dir.glob("bot.db.*.db"))
        for old in files[:-keep] if len(files) > keep else []:
            try:
                old.unlink()
            except Exception:
                pass
        logger.info(
            "Миграция-бэкап: %s (%.1f КБ), quick_check ok", dest.name, dest.stat().st_size / 1024
        )
        return dest
    except Exception as exc:
        logger.error("Бэкап перед миграцией (%s) не удался: %s", label, exc)
        if required:
            raise RuntimeError(f"Снапшот БД перед миграцией ({label}) не удался: {exc}") from exc
        return None


async def _migrate_response_patterns_to_prompt_variants(db: aiosqlite.Connection) -> None:
    """Preserve quality A/B data, then remove the obsolete response-pattern schema."""
    cur = await db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='patterns'")
    has_patterns = await cur.fetchone()
    cur = await db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pattern_variants'")
    has_legacy_variants = await cur.fetchone()
    if has_patterns and has_legacy_variants:
        await db.execute(
            "INSERT OR IGNORE INTO prompt_variants "
            "(id, account_id, label, system_prompt, weight, count, likes, dislikes, enabled, created_at) "
            "SELECT v.id, p.account_id, v.label, v.system_prompt, v.weight, v.count, v.likes, v.dislikes, v.enabled, v.created_at "
            "FROM pattern_variants v JOIN patterns p ON p.id = v.pattern_id"
        )
    # Feedback is still useful even when it is not attributed to an A/B variant.
    cols = {row[1] for row in await (await db.execute("PRAGMA table_info(bot_response_feedback)")).fetchall()}
    if "pattern_variant_id" in cols and "prompt_variant_id" not in cols:
        await db.execute("ALTER TABLE bot_response_feedback RENAME COLUMN pattern_variant_id TO prompt_variant_id")
    await db.execute("DROP TABLE IF EXISTS pattern_variants")
    await db.execute("DROP TABLE IF EXISTS patterns")
    await db.commit()


async def _migrate_bot_logs_fallback_category(db: aiosqlite.Connection) -> None:
    """OPS_PLAN §3: расширить CHECK category в bot_logs значением 'fallback'.

    Пересоздаёт таблицу, только если старый CHECK ещё не содержит 'fallback'.
    """
    cursor = await db.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'bot_logs'"
    )
    row = await cursor.fetchone()
    if not row or not row[0]:
        return  # таблицы ещё нет — создастся уже с новой CHECK
    if "'fallback'" in row[0] or '"fallback"' in row[0]:
        return
    logger.info("Миграция bot_logs: добавляю категорию 'fallback' (пересоздание таблицы)")
    await db.execute("PRAGMA foreign_keys = OFF")
    try:
        await db.executescript("""
            CREATE TABLE bot_logs_migrate (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                channel    TEXT NOT NULL DEFAULT '',
                level      TEXT NOT NULL CHECK(level IN ('debug','info','warning','error')),
                category   TEXT NOT NULL CHECK(category IN ('chat','ai','tts','trigger','event','system','fallback')),
                message    TEXT NOT NULL,
                details    TEXT NOT NULL DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );
            INSERT INTO bot_logs_migrate (id, account_id, channel, level, category, message, details, created_at)
                SELECT id, account_id, channel, level, category, message, details, created_at FROM bot_logs;
            DROP TABLE bot_logs;
            ALTER TABLE bot_logs_migrate RENAME TO bot_logs;
            CREATE INDEX IF NOT EXISTS idx_bot_logs_acc_time ON bot_logs(account_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_bot_logs_level ON bot_logs(level);
            CREATE INDEX IF NOT EXISTS idx_bot_logs_category ON bot_logs(category);
        """)
        await db.commit()
    except Exception as exc:
        logger.warning("Миграция bot_logs (fallback category) не удалась: %s", exc)
    finally:
        await db.execute("PRAGMA foreign_keys = ON")
async def ensure_moderation_schema(db: aiosqlite.Connection) -> None:
    """Q01/Q03: схема модерации — ЕДИНСТВЕННЫЙ источник DDL.

    Зовётся из init_db() и из ленивой moderation._ensure_extra_schema(). Дублировать
    CREATE-таблицы в app/moderation.py нельзя: guard-тест test_s5_db_isolation
    ловит пары CREATE между файлами (P0-паттерн «кто первый создал, тот и прав»).
    Идемпотентно: IF NOT EXISTS + ALTER в try/except (колонка уже есть).
    """
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS moderation_pending (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            channel TEXT DEFAULT '',
            username TEXT DEFAULT '',
            category TEXT DEFAULT '',
            severity INTEGER DEFAULT 3,
            rule_name TEXT DEFAULT '',
            message_excerpt TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now')),
            decided_at TEXT,
            requested_action TEXT DEFAULT 'timeout',
            duration_sec INTEGER DEFAULT 600,
            role TEXT DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_mod_pending_acc ON moderation_pending(account_id, status);
        CREATE TABLE IF NOT EXISTS moderation_learn (
            account_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            approved INTEGER DEFAULT 0,
            rejected INTEGER DEFAULT 0,
            PRIMARY KEY (account_id, category)
        );
        CREATE TABLE IF NOT EXISTS moderation_protected (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            channel TEXT NOT NULL DEFAULT '',
            username TEXT NOT NULL,
            note TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(account_id, channel, username)
        );
        CREATE INDEX IF NOT EXISTS idx_mod_protected_acc ON moderation_protected(account_id, channel);
        CREATE TABLE IF NOT EXISTS moderation_channel_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT NOT NULL,
            pattern TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'custom',
            action TEXT NOT NULL DEFAULT 'block'
                CHECK(action IN ('replace','block','timeout','log')),
            severity INTEGER NOT NULL DEFAULT 3 CHECK(severity BETWEEN 1 AND 5),
            action_ext TEXT,
            enabled INTEGER DEFAULT 1,
            name TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(channel, pattern)
        );
        CREATE INDEX IF NOT EXISTS idx_mod_channel_rules ON moderation_channel_rules(channel, enabled);
    """)
    try:
        await db.execute("ALTER TABLE accounts ADD COLUMN timeout_policy TEXT DEFAULT 'auto'")
    except Exception:
        pass  # колонка уже есть
    try:
        await db.execute("ALTER TABLE accounts ADD COLUMN moderation_escalation_enabled INTEGER DEFAULT 1")
    except Exception:
        pass  # колонка уже есть
    # Q01-C2: старые БД создали moderation_pending до появления этих колонок
    for col_sql in (
        "ALTER TABLE moderation_pending ADD COLUMN requested_action TEXT DEFAULT 'timeout'",
        "ALTER TABLE moderation_pending ADD COLUMN duration_sec INTEGER DEFAULT 600",
        "ALTER TABLE moderation_pending ADD COLUMN role TEXT DEFAULT ''",
    ):
        try:
            await db.execute(col_sql)
        except Exception:
            pass  # колонка уже есть
    await db.commit()


async def _migrate_moderation_events_recommend_sources(db: aiosqlite.Connection) -> None:
    """Q01-C2 (DEC-OWNER-014): расширить CHECK source в moderation_events
    значениями 'timeout_recommend' и 'punishment_recommend'.

    Старый CHECK их резал — записи рекомендаций таймаута молча терялись (log_event
    глотает отказы вставки). Пересоздаёт таблицу, только если CHECK ещё старый."""
    cursor = await db.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'moderation_events'"
    )
    row = await cursor.fetchone()
    if not row or not row[0]:
        return  # таблицы ещё нет — создастся уже с новой CHECK
    if "timeout_recommend" in row[0] and "punishment_recommend" in row[0]:
        return
    logger.info("Миграция moderation_events: добавляю источники рекомендаций наказаний (пересоздание таблицы)")
    await db.execute("PRAGMA foreign_keys = OFF")
    try:
        await db.executescript("""
            CREATE TABLE moderation_events_migrate (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL DEFAULT '',
                username TEXT NOT NULL DEFAULT '',
                rule_id INTEGER,
                rule_name TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                severity INTEGER NOT NULL DEFAULT 0,
                action_taken TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'chat_in'
                    CHECK(source IN ('chat_in','bot_out','api_send','eventsub','antispam',
                                     'timeout_recommend','punishment_recommend')),
                message_excerpt TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );
            INSERT INTO moderation_events_migrate
                (id, account_id, channel, username, rule_id, rule_name, category, severity,
                 action_taken, source, message_excerpt, created_at)
                SELECT id, account_id, channel, username, rule_id, rule_name, category, severity,
                       action_taken, source, message_excerpt, created_at FROM moderation_events;
            DROP TABLE moderation_events;
            ALTER TABLE moderation_events_migrate RENAME TO moderation_events;
            CREATE INDEX IF NOT EXISTS idx_mod_events_acc_time ON moderation_events(account_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_mod_events_user ON moderation_events(account_id, username, created_at);
        """)
        await db.commit()
    except Exception as exc:
        logger.warning("Миграция moderation_events (recommend sources) не удалась: %s", exc)
    finally:
        await db.execute("PRAGMA foreign_keys = ON")


class _DBProxy:
    """Обёртка над aiosqlite.Connection с no-op close().

    Позволяет вызывать `await db.close()` в существующем коде, но реальное
    соединение не закрывается — оно живёт всё время процесса (см. close_db).
    """

    __slots__ = ("_real",)

    def __init__(self, real: aiosqlite.Connection):
        object.__setattr__(self, "_real", real)

    async def close(self) -> None:  # no-op
        return None

    def __getattr__(self, name):
        return getattr(self._real, name)

    def __setattr__(self, name, value):
        setattr(self._real, name, value)


async def _get_init_lock() -> asyncio.Lock:
    """Возвращает _init_lock, пересоздавая его при смене event loop.

    asyncio.Lock жёстко привязывается к loop первого использования; лок,
    оставшийся от закрытого loop теста, никогда не освободится — безопаснее
    создать новый (в проде один loop, пересоздания не происходит).
    """
    global _init_lock, _init_lock_loop
    loop = asyncio.get_running_loop()
    if _init_lock is None or _init_lock_loop is not loop:
        _init_lock = asyncio.Lock()
        _init_lock_loop = loop
    return _init_lock


async def _ensure_shared() -> aiosqlite.Connection:
    global _shared_db
    if _shared_db is not None:
        return _shared_db
    async with await _get_init_lock():
        if _shared_db is None:
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            db = await aiosqlite.connect(DB_PATH)
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA busy_timeout=5000")
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute("PRAGMA synchronous=NORMAL")
            _shared_db = db
            logger.info("DB shared connection opened: %s", DB_PATH)
    return _shared_db


async def get_db() -> "_DBProxy":
    """Вернуть прокси на singleton-коннект.

    Существующий код может вызывать `await db.close()` без побочных эффектов.
    """
    real = await _ensure_shared()
    return _DBProxy(real)


# Таблицы-«дети» без FK: при удалении бота остаются мусорные строки
# (§5 аудит 30.08). chat_log/chat_users/user_memory/streamer_profile/
# streamer_face НЕ трогаем — кросс-ботовая память и глобальный профиль
# переживают удаление бота намеренно.
ACCOUNT_CHILD_TABLES = (
    "bot_corrections", "stream_reports", "clip_moments",
    "moderation_learn", "moderation_pending", "streamer_notes",
    "replay_sessions", "bot_topic_log",
)


async def cleanup_account_children(db: aiosqlite.Connection, account_id: int) -> int:
    """Удалить записи удалённого бота из таблиц без FK. Возвращает число строк."""
    removed = 0
    for table in ACCOUNT_CHILD_TABLES:
        try:
            cur = await db.execute(f"DELETE FROM {table} WHERE account_id = ?", (account_id,))
            removed += cur.rowcount or 0
        except Exception as exc:
            logger.debug("cleanup %s: %s", table, exc)
    return removed


async def close_db() -> None:
    """Закрыть shared-коннект (вызывается в lifespan shutdown)."""
    global _shared_db
    if _shared_db is not None:
        try:
            await _shared_db.close()
        finally:
            _shared_db = None
            logger.info("DB shared connection closed")


# ---------- Helpers для настроек ----------

async def get_setting(key: str, default: str = "") -> str:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row["value"] if row else default
    finally:
        await db.close()


async def set_setting(key: str, value: str) -> None:
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
        await db.commit()
    finally:
        await db.close()


async def get_setting_bool(key: str, default: bool = False) -> bool:
    val = await get_setting(key, "1" if default else "0")
    return val == "1"
