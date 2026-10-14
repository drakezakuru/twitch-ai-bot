# CHANGELOG v11.0

> **Дата:** 2026-08-26
> **База:** v10.5 + інкременти v10.4.x

## Мета релізу

Перетворити бота з «розумного чаттера» в керовану AI-платформу: персистентна пам'ять, керований характер, TTS через OBS, масштабований UI та надійний батчинг.

---

## 🗄️ Блок 1: Нова БД стримера + пам'ять ботів

### Нові таблиці (16 штук)

| Таблиця | Призначення |
|---------|-------------|
| `streamer_profile` | Факти про стримера: вік, інтереси, ігри, стиль, що любить/не любить |
| `streamer_face` | Фото обличчя стримера (base64) для візіон-моделей |
| `streamer_events` | Хроніка подій: дати стримів, рейди, донати, важливі моменти |
| `streamer_stats` | Агрегована статистика: онлайн/офлайн, глядачі, топ-чатери |
| `bot_conversation_history` | Персистентна пам'ять: кожне повідомлення + відповідь з таймстемпом |
| `bot_streamer_affinity` | Рівень прив'язаності бота до стрімера/чату |
| `channel_overrides` | Per-channel перезаписи параметрів бота (humor, sarcasm, adult) |
| `voice_speakers` | Розпізнані голоси на стримі: стример, модер, глядач |
| `raid_context_log` | Збережений контекст raid-сесій |
| `shared_chatter_facts` | Спільні факти про користувачів між ботами |

### Новий модуль: `app/streamer_profile.py`

- `get_streamer_profile()` / `upsert_streamer_profile()` — CRUD профілю
- `auto_update_profile()` — авто-заповнення через LLM + Helix
- `get_streamer_face()` / `upsert_streamer_face()` / `delete_streamer_face()` — CRUD фото

### API

| Метод | Шлях | Опис |
|-------|------|------|
| `GET` | `/api/accounts/{id}/streamer-profile` | Отримати профіль стримера |
| `PUT` | `/api/accounts/{id}/streamer-profile` | Оновити профіль |
| `GET` | `/api/accounts/{id}/streamer-face?include=0/1` | Отримати фото обличчя |
| `POST` | `/api/accounts/{id}/streamer-face` | Завантажити фото (multipart) |
| `DELETE` | `/api/accounts/{id}/streamer-face` | Видалити фото |

---

## 🎭 Блок 2: Розширена персона + «режим людини»

### Розширення `BotPersona` (нові поля)

| Поле | Тип | Default | Опис |
|------|-----|---------|------|
| `humor_level` | int 0-100 | 50 | Рівень гумору |
| `darkness_level` | int 0-100 | 10 | Чорний гумор |
| `crudeness_level` | int 0-100 | 0 | Пошлість, мати |
| `seriousness` | int 0-100 | 50 | Серйозність |
| `sarcasm_level` | int 0-100 | 30 | Сарказм |
| `emotionality` | int 0-100 | 50 | Емоційність |
| `adult_humor` | int 0-100 | 0 | Дорослий гумор |
| `contact_level` | int 0-100 | 50 | Прив'язаність до стрімера |
| `chat_affinity` | int 0-100 | 50 | Прив'язаність до чату |
| `dynamic_personality` | bool | false | Сам змінює параметри під ситуацію |
| `mood_influence` | int 0-100 | 0 | Вплив настрою чату |
| `asterisk_emotes` | bool | false | *обиженно смотрит* |
| `observation_only` | bool | false | Тільки спостерігає, не пише |
| `bounds` | dict | {} | Кордони для динаміки per-метрика |
| `*_enabled` (7 штук) | bool | true | Тогл «AI вирішує» для кожної метрики |

### Нові функції

- `clamp()` — обмежує значення в межах bounds
- `copy()` — глибока копія
- `format_extended_persona_for_prompt()` — розширений блок з рівнями характеру
- `apply_dynamic_persona()` — динамічна адаптація під настроение чату (EMA)

### Маппінг настрою → дельти

| Настрій | Гумор | Сарказм | Adult | Емоційність | Серйозність |
|---------|-------|---------|-------|-------------|-------------|
| 😊 Positive | +20 | +10 | +15 | +20 | -10 |
| 😠 Toxic | -30 | -20 | -40 | -30 | +20 |
| 😢 Sad | -10 | -10 | -20 | +10 | +10 |
| 🔥 Wild | +30 | +20 | +30 | +30 | -20 |

### Новий модуль: `app/bot_presets.py`

7 готових пресетів: Новачок, Друг, Тролль, Мудрець, Токсик, Спокійний, Дикий + AI-генерація за описом.

### API

| Метод | Шлях | Опис |
|-------|------|------|
| `GET` | `/api/persona-presets` | Список пресетів |
| `POST` | `/api/accounts/{id}/persona/apply-preset` | Застосувати пресет |
| `POST` | `/api/accounts/{id}/generate-persona` | AI-генерація персони |
| `POST` | `/api/accounts/{id}/personality-shift` | Тимчасовий shift (+10 humor на 5 хв) |

---

## 🔊 Блок 3: Озвучування через OBS (TTS)

### 3 TTS-провайдери

| Провайдер | Ціна | Якість | Мови |
|-----------|------|--------|------|
| **Web Speech API** | Безкоштовно | Проста (браузер) | Багато |
| **Piper TTS** | Безкоштовно (локально) | Середня | RU/EN |
| **ElevenLabs API** | ~$5/міс | Висока | Багато |

Прогресивна деградація: ElevenLabs → Piper → Web Speech.

### Новий модуль: `app/tts_engine.py`

- `TTSEngine` — головний клас з маршрутизацією між провайдерами
- `WebSpeechProvider` / `PiperProvider` / `ElevenLabsProvider`
- `broadcast_tts_event()` — WebSocket подія для OBS Widget
- Емоції → параметри голосу (neutral, angry, sad, happy, surprised, fear)

### Таблиці

| Таблиця | Призначення |
|---------|-------------|
| `tts_settings` | Глобальні TTS настройки |
| `tts_bot_config` | Per-bot TTS конфіг |
| `tts_voice_presets` | Голосові пресети |
| `voice_clones` | Voice clones (ElevenLabs, XTTS, Piper) |

### OBS Widget

`templates/obs_tts_widget.html` — Browser Source для озвучки відповідей бота через WebSocket.

### API

| Метод | Шлях | Опис |
|-------|------|------|
| `GET` | `/api/tts/config` | Глобальний TTS конфіг |
| `PUT` | `/api/tts/config` | Оновити глобальний TTS |
| `GET` | `/api/accounts/{id}/tts-config` | Per-bot TTS конфіг |
| `PUT` | `/api/accounts/{id}/tts-config` | Оновити per-bot TTS |
| `GET` | `/api/tts/voices` | Список голосів/пресетів |
| `GET` | `/api/voice-clones` | Список клонів голосу |

---

## 🖥️ Блок 4: UI панелі

### Нові вкладки

- **📋 Логи ботів** — фільтри per-bot, per-level, per-category, експорт CSV/JSON
- **👁️ Спостереження** — тогли observation_only, silent_analysis, log_all_messages
- **🔊 TTS v11** — настройки глобального та per-bot TTS, прев'ю OBS Widget URL

### JavaScript функції

- `loadBotLogs()` / `cleanupBotLogs()` / `exportBotLogs()`
- `loadObservationSettings()` / `saveObservationSettings()`
- `loadTtsGlobalConfig()` / `saveTtsGlobalConfig()` / `loadTtsBotConfig()` / `saveTtsBotConfig()`

---

## 🤖 Блок 5: API/моделі per-bot + контекст

- Валідація AI провайдерів: `openrouter`, `ollama`, `gemini`, `openai`, `anthropic`
- Per-bot AI overrides вже існували з v10.4.3

---

## 👁️ Блок 6: Спостереження + «режим тихого бота»

### Нові настройки per-bot

| Налаштування | Default | Опис |
|--------------|---------|------|
| `observation_only` | false | Пише в БД, але НЕ в чат |
| `silent_analysis` | false | Аналізує чат без відповідей |
| `log_all_messages` | true | Зберігати всі повідомлення в chat_log |
| `raid_save_context` | false | Зберігати контекст рейду в пам'ять |
| `raid_apply_overrides` | false | Застосовувати per-channel overrides для рейду |
| `raid_exit_after_message` | 0 | Вийти через N сек після останнього повідомлення |
| `raid_exit_on_silence` | false | Вийти якщо тиша >N хвилин |

### Поведінка

- **observation_only**: mood_engine.feed ✅, thread_tracker.feed ✅, user_memory ✅, AI generate ❌, send ❌
- **silent_analysis**: все як observation_only + mood engine ✅, threads ✅
- **raid_save_context**: зберігає контекст рейду в `bot_conversation_history`
- **raid_apply_overrides**: застосовує per-channel overrides на час рейду

---

## ⚡ Блок 7: Фільтр уваги + батчинг

### Новий модуль: `app/attention_filter.py`

- `is_noise_message()` — евристика шумових повідомлень (+1, KEWWW, однолітерні)
- `BatchBuffer` — буфер для батчингу повідомлень per (account_id, channel)
- `AttentionFilter` — фільтр уваги з кулдаунами та лімітами

### Режими уваги

| Режим | Опис |
|-------|------|
| `everyone` | Реагує на всіх (поточна поведінка) |
| `streamer_only` | Тільки на повідомлення стримера |
| `chat_only` | Тільки на чат (не на стримера) |
| `streamer_and_chat` | На стримера + чат, ігнорує шум |
| `custom` | Вибирає конкретних юзерів зі списку `chat_users` |

### Таблиці

| Таблиця | Призначення |
|---------|-------------|
| `bot_attention_config` | Конфіг уваги per-bot |
| `chat_users` | Користувачі чату (авто-заповнюється) |

### API

| Метод | Шлях | Опис |
|-------|------|------|
| `GET` | `/api/accounts/{id}/attention-config` | Конфіг уваги |
| `PUT` | `/api/accounts/{id}/attention-config` | Оновити конфіг |
| `GET` | `/api/accounts/{id}/chat-users` | Список юзерів чату |
| `PUT` | `/api/accounts/{id}/chat-users/{username}` | Toggle enabled |

### Інтеграція в chat_analyzer

- Якщо `batch_enabled = true`: повідомлення додаються в BatchBuffer, таймер запускає `_process_batched_messages()`
- `_process_batched_messages()` застосовує AttentionFilter, будує контекст, генерує одну відповідь на весь батч

---

## 📋 Блок 8: Розділення логів per-bot

### Новий модуль: `app/bot_logs.py`

- `log_per_bot()` — запис логу + WebSocket broadcast
- `get_bot_logs()` — отримання з фільтрами (level, category, channel, q, from, to)
- `cleanup_old_logs()` — видалення старих логів (> retention днів)
- `export_logs()` — експорт у CSV/JSON
- `get_log_stats()` — статистика per-bot

### Таблиця `bot_logs`

| Колонка | Тип | Опис |
|---------|-----|------|
| `account_id` | int | ID бота |
| `channel` | text | Канал |
| `level` | text | debug/info/warning/error |
| `category` | text | chat/ai/tts/trigger/event/system |
| `message` | text | Текст логу |
| `details` | text | JSON додаткові дані |

### Інтеграція в chat_analyzer

- `on_message`: вхідне повідомлення, бан-лист, anti-detection, anti-spam
- `_generate_and_send`: AI відповідь з details (author, trigger, reply)
- Триггери: звичайні та smart-trigger
- TTS: синтез з details (provider, emotion, voice)

### API

| Метод | Шлях | Опис |
|-------|------|------|
| `GET` | `/api/accounts/{id}/bot-logs` | Логи бота з фільтрами |
| `GET` | `/api/bot-logs` | Всі логи з фільтрами |
| `DELETE` | `/api/accounts/{id}/bot-logs` | Очистити старі логи |
| `GET` | `/api/accounts/{id}/bot-logs/export` | Експорт CSV/JSON |

---

## 📁 Блок 9: Структура папок per-bot

### Новий модуль: `app/bot_dirs.py`

```
data/bots/{account_id}_{nickname}/
├── config.json
├── prompts/
│   ├── system.txt
│   ├── personality.txt
│   ├── style_examples/
│   └── banned_topics.txt
├── memory/
│   ├── conversation.jsonl
│   ├── user_facts.json
│   └── streamer_profile.json
├── voice/
│   ├── voice_model.onnx
│   ├── voice_config.json
│   └── streamer_face.jpg
├── logs/
│   ├── bot.log
│   └── chat_history.jsonl
└── exports/
    ├── chat_export.csv
    └── stats.json
```

- `init_bot_dir()` — створення структури (ідемпотентно)
- `migrate_bot_dir()` — міграція з БД в per-bot папки
- `list_bot_files()` / `read_bot_file()` / `write_bot_file()` / `delete_bot_file()` — CRUD
- `export_bot_dir()` — ZIP-архів папки бота

---

## 🧪 Тести

### Новий файл: `tests/test_v11_modules.py` (32 тести)

- **TestBotPersonaExtended** (10): defaults, serialization, clamp, bounds, copy, is_empty, format_extended
- **TestDynamicPersona** (4): disabled, positive mood, toxic mood, mood deltas
- **TestNoiseFilter** (2): noise messages, not noise
- **TestAttentionFilter** (7): everyone/streamer_only/chat_only/custom modes, noise filter, cooldown, can_reply, build_context
- **TestBatchBuffer** (3): add/get, has_messages, different channels
- **TestBotPresets** (6): all exist, apply, nonexistent, list, values in range

### Фікс pre-existing багів

- **test_engagement.py**: `_ts()` конвертує в UTC (SQLite `datetime('now')` = UTC, Python `datetime.now()` = local)
- **test_diarization.py**: працює після встановлення `numpy` + `scipy`

### Результат: **846 passed, 0 failed** ✅

---

## 📦 Нові залежності (optional)

| Пакет | Для чого | Обов'язковий |
|-------|----------|-------------|
| `numpy` | Diarization, vision | Ні (optional) |
| `scipy` | Diarization | Ні (optional) |
| `piper-tts` | Локальний TTS | Ні (optional) |
| `elevenlabs` | ElevenLabs API | Ні (optional) |

---

## 📊 Статистика змін

| Метрика | Значення |
|---------|----------|
| Нові файли | 7 модулів + 1 widget + 1 тест |
| Змінені файли | 5 (database, bot_persona, chat_analyzer, routes, index.html) |
| Нові таблиці БД | 16 |
| Нові API endpoints | 15+ |
| Нові тести | 32 |
| Всього тестів | 846 (0 failing) |
