# BRAIN_PER_BOT_MAP — карта источников «что влияет на бота»

> Обновлено 03.09.2026 по фактическому коду (было 31.08, устарело: rework B2/D/W-серия).
> Точка сборки: `app/chat_analyzer.py` ~2430–2570 (блок «Дополняем system всеми блоками»);
> гейты влияний — там же + `app/chat_prompt_blocks.py`. Порядок в таблице = порядок в промпте.
> База: `system` → `+extras` (всё непустое склеивается через `\n\n`).
> Read-only потребители тех же источников: `app/brain_preview.py` (`/api/brain-preview/{id}`,
> экран «Мозг бота») и `app/prompt_snapshot.py` (`data/bots/<ник>/prompts/`).

## Итоговый system prompt бота

```
[base: settings.system_prompt / patterns.system_prompt / A/B-вариант]
+ persona_block          (гейт use_persona, ВКЛ по умолчанию)
+ channel_ctx_text       (Twitch-контекст канала)
+ game_vocab_block       (словарь игры для vision-контекста)
+ memory_text            (факты о ЮЗЕРЕ, per-bot — shared facts УДАЛЕНЫ)
+ user_history_block     (последние сообщения юзера)
+ streamer_profile_block (профиль стримера, channel → global; W4: API уже per-channel)
+ lore_block             (lore стримера, только approved; гейт streamer_lore_enabled)
+ live_summary_block     (live-digest стрима за 30 мин; ВЫКЛ по умолчанию)
+ thread_block           (контекст треда разговора)
+ streamer_mood_block    (mood → style hint; C1-кандидат на удаление)
+ mimicry_block          (LIVE-профиль чата, НЕ top-K копирка)
+ shift_block            (personality shift — временный mood; ручной роут C4 мёртв, жив /shift/trigger)
+ conv_block             (полный контекст беседы)
+ kb_block               (KB по запросу)
+ few_shot_block         (style examples top-K)
+ friendly_block         (multi-bot дружеский чат — контекст соседей)
+ chatter_style          (только chatter + гейт influence_mimicry)
```

## Таблица источников

| Блок | Источник (файл/таблица) | Скоуп | Что даёт |
|---|---|---|---|
| base system | `analyzer_settings.system_prompt` → `patterns.system_prompt` → A/B `ai_prompt_variants` | per-bot | Главные инструкции бота (⚠️ patterns — C7: работает только первая строка) |
| persona_block | `_load_persona_block` (incl. extended persona) · **гейт `use_persona` (default True)** | per-bot | Характер: возраст, юмор, сарказм, привязанность, catchphrases (вкладка «Характер») |
| channel_ctx_text | Helix `/channels` (live) + `format_channel_context` | per-channel | Категория/название/статус стрима сейчас |
| game_vocab_block | game vocab-словарь + Helix категория | per-channel/global | Терминология игры для осмысленных реплик |
| memory_text | `user_memory` structured, **только per-bot** (shared facts удалены, P8-C2) | per-bot × per-user | Персональные факты о зрителе |
| user_history_block | `user_memory.get_message_history` (последние 5) | per-bot × per-channel × user | Что юзер писал недавно |
| streamer_profile_block | `get_streamer_profile_resolved` (channel → global fallback) | per-bot × per-channel | Кто стример: био, стиль, интересы, фото (vision) |
| lore_block | `streamer_lore.list_approved` (top-10) · гейт `streamer_lore_enabled` | per-bot × per-channel | Утверждённые факты-lore |
| live_summary_block | `summarizer.get_live_digest` · **ВЫКЛ по умолчанию** (`summarizer_live_enabled=false`) | per-bot × per-channel | О чём стрим за последние 30 мин |
| thread_block | `conversation_threads` · гейт `threads_enabled` | per-bot × per-channel | Активный разговор-тред и участники |
| streamer_mood_block | `style_hint_for_mood` · гейт `streamer_mood_enabled` + skip-when-silent | per-bot | Настроение стримера → сдвиг стиля (⚠️ C1: фейк-кандидат) |
| mimicry_block | live-профиль чата (`live_mimicry_enabled`) + `mimicry_hint_block` | per-bot × per-channel | Подстройка стиля под живой чат |
| shift_block | `personality_shift.shift_manager.get_hint` | per-bot × per-channel | Временное изменение характера |
| conv_block | `build_full_conversation_context` | per-bot × per-channel | Последние сообщения чата |
| kb_block | `ai_quality_db.retrieve_kb_for_query` | per-bot | Knowledge Base: статья по теме вопроса |
| few_shot_block | `ai_quality_db.pick_style_examples` (top-K, cosine) | per-bot × per-channel | Примеры «как бот должен звучать» |
| friendly_block | `multi_bot_chat` · гейт `multi_bot_chat_enabled` | per-channel | Что сказали другие боты |
| chatter_style | `bot_roles.chatter_style_block` · **только chatter + гейт `influence_mimicry`** | per-bot | Пресет/копирка/самообучение болтуна |

## Гейты влияний (карточка «Влияния» в Мозге + мастер в Настройках)
- `influence_mimicry` (def True) → chatter_style; `influence_observations` (def True) → stream-наблюдения в промпт (`context_source_stream`); `influence_learning` (def True) → авто-извлечение в память.
- `provocations_master_enabled` (def True, Настройки → Поведение) — глобально глушит per-bot провокации.
- Хранение: персист `analyzer_settings` в БД (B2), гидрируется в `bootstrap.start_account`; runtime-синк из PUT /api/accounts и PUT /persona.

## Скоупы (легенда)

- **per-bot** — своё у каждого бота (accounts.id).
- **per-channel** — своё на канал, обычно с fallback на общий.
- **GLOBAL** — общее для всех ботов панели (дизайн-токены; shared facts больше НЕ global — удалены).
- **per-bot × per-user** — своя память на каждого зрителя отдельно.

## Использование

- Экран «Мозг бота X» строит read-only сводку из этой таблицы: «Промпт/характер»
  (base+persona+chatter_style+shift), «Память» (memory+lore+KB+history), «Функции»
  (TTS/триггеры/модерация/виджеты), «Провайдер/модель» (ai_service settings).
- Промпт-инспектор показывает ИТОГОВЫЙ system prompt, собранный той же функцией, что и
  рантайм (блок extras) — а не отдельную копию логики.
- НОВАЯ логика сборки промпта должна жить в рантайме/`chat_prompt_blocks`, а не копироваться.
