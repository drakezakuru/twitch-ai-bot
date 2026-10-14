# FEATURE AUDIT — 02.09.2026 (доки vs код)

> ⚠️ **ИСТОРИЧЕСКИЙ / SUPERSEDED СНИМОК.** Этот аудит отражает состояние на 02.09.2026 и не является текущим backlog или гарантией состояния кода. Активный план: [`../PLAN.md`](../PLAN.md); решения продукта: [`PRODUCT_RULES.md`](PRODUCT_RULES.md); архив переработки: [`archive/PLAN_REWORK_2026-09-03.md`](archive/PLAN_REWORK_2026-09-03.md).

Проверка заявленных в планах функций против реально работающего кода.
Статусы: ✅ работает · 🔶 частично · ❌ только в доках · ☠️ мёртвое (есть, но не работает/никто не вызывает).
Источник: обход app/*.py, static/app/*.js, templates/, tests/ + grep-аудит.

## Сводная таблица

| Фича из доков | Статус | Где / что не так |
|---|---|---|
| Авто-модерация (словари, правила, timeout-policy) | ✅ | app/moderation.py, moderation_dicts.py, routes_modpanel.py |
| mod-feed (OBS + панель), стрим-инструменты | ✅ | app/mod_feed_routes.py, stream_tools_routes.py; публикация только для роли moderator (chat_analyzer.py:2029) |
| TTS-движок + виджеты озвучки | ✅ | tts_engine.py (WebSpeech/Piper/XTTS/F5/ElevenLabs), widgets/tts-*, routes_tts_config.py, voice-клоны Piper |
| Replay (запись/просмотр сессий) | 🔶 | replay_debug.py работает, автозапись включена (bot_manager.py:135) — НО сессия создаётся на каждого бота отдельно → один стрим с N ботами = N дублей чата. Нет реального «воспроизведения» в runtime |
| Stream Vision (кадры, Whisper, диаризация, observations) | ✅ | stream_vision.py, diarization.py; vision→chat, last_observation в промпт |
| Настроение стримера (mood, §9e «вычисляется из Whisper») | ☠️ | Трекер streamer_mood.py есть, но единственная точка кормления POST /api/streamer-mood/feed (routes_wave4.py:20) не вызывается НИЧЕМ. Карточки всегда показывают дефолт «chill 100%». В доках заявлено автообновление из Stream Vision — его нет |
| Отношение к стримеру (attitude, 7 тонов) | ✅ | streamer_attitude.py, блок в промпте chat_prompt_blocks.py:62 |
| Привязанность (affinity §8) | 🔶 | Слайдеры contact_level/chat_affinity (персона) и bot_streamer_affinity в промпт НЕ попадают: format_extended_persona_for_prompt (bot_persona.py:304) мёртвый. Авто per-user affinity (affinity_rules.py) работает и пишет БД, журнал /affinity/history без UI |
| Динамическая личность (apply_dynamic_persona) | ☠️ | bot_persona.py:333 — ноль вызовов. Тумблер «Динамічна особистість» в UI ни на что не влияет |
| Копирка чатера (mimic, 3 источника) | ✅ | role_routes.py:215 (chat_log + logs.ivr.fi + чат-логгер), live_mimicry.py, learned_pool |
| Обучение по стриму (предложения, learning) | ✅ | learning.py, роуты routes_snippets.py:559+, UI 11_brain_v16.js |
| Общение с ботом без стрима | ❌ | Есть только песочница-предпросмотр (role_routes.py:315 role-sandbox, один ответ без памяти). Полноценного чата нет — запланировано (DM-чат) |
| Voice companion (TTS-собеседник стримера) | 🔶 | Роль, дефолты, TTS есть; речевого пайплайна «транскрипт → реплика → TTS» нет — on_speech живёт только в вердикте песочницы (role_routes.py:367) |
| Паттерны (готовые system_prompt) | 🔶 | Работают, но применяется всегда «первый по id» (chat_analyzer.py:2325 ORDER BY id LIMIT 1). «Выбор произвольного паттерна» из описания UI не существует |
| Пресеты поведения vs пресеты характера | ☠️ (дубль) | Два независимых набора с одинаковыми именами: JS BEHAVIOR_PRESETS (03_bots.js:885, UA-лейблы, пишут персону) и Python bot_presets.PRESETS (значения не совпадают). Свои пресеты — один эндпоинт /behavior-presets, два дублирующих UI |
| Channel overrides | ✅ | routes_overrides.py, применяются в _merged_settings (chat_analyzer.py:179) и при рейдах |
| Настройки анализатора (auto_chat/тихий/кулдаун/провокации) | ☠️ (нестабильно) | chat_analyzer._settings — in-memory dict, НЕТ персиста в БД: все эти настройки слетают при рестарте панели. Плюс 3 дублирующих UI: Быстрые настройки, «Анализатор чата» в Характере, каналы |
| «Только наблюдает» (observation_only) | ☠️ (рассинхрон) | 3 несвязанных хранилища: колонка accounts.observation_only (пишут кнопка карточки/quick — routes.py:227, рантайм НЕ читает), persona_json (не читается гейтом), in-memory analyzer settings (читается гейтом chat_analyzer.py:1420, UI туда не пишет). Реально работает только per-channel override |
| «Использовать характер бота» (use_persona) | ✅ (но выкл по умолч.) | Гейт chat_analyzer.py:2354; дефолт False → Характер по умолчанию НЕ влияет на бота |
| Провокации в спорах | ✅ (но настройки слетают) | conflict_provocation.py, гейт в рантайме chat_analyzer.py:1483; ключи хранятся в in-memory analyzer settings → сброс при рестарте. Глобального выключателя нет |
| Lurker-поля роли (collect_users/collect_lore/observations/interval/mem_limit/cleanup_days) | ☠️ | bot_roles.py:80 хранятся, читателей нет (grep: только UI/дефолты). Lore/наблюдения собираются независимо от роли |
| Память per-user, KB, lore, summarizer | ✅ | user_memory.py (per-bot после P8-C2), routes_ai_quality.py, streamer_lore.py, summarizer.py |
| Чат-логгер (внешние каналы) | ✅ | scripts/chatlogger/, вкладка в панели, 3-й источник для копирки |
| Виджеты (38 шт, OBS, WS) | ✅ | widgets/, app/widgets.py, widget_bus.py, P8-B превью/пресеты |
| Custom AI-провайдеры (навечно) | ✅ (не очевидно) | БД custom_providers, CRUD routes.py:1350-1420, карточка в Настройках (08_providers_moderation.js), подставляются в селект бота как «🧩 имя». Проблема — незаметность рядом с «Custom (разовый URL)» |
| Standalone (бот без панели) | ✅ | standalone.py, bootstrap.py, bot_dirs.py |
| VoiceStudio | 🔶 (отложен) | Код только на ветке session/voicestudio (8 коммитов: провайдер, панель, 18 тестов). Владельцем отложен 02.09. VOICESTUDIO_PLAN.md в main отсутствует (битая ссылка в PLAN.md:4,196) |

## Мёртвый бэкенд (кандидаты на удаление — только по отдельному подтверждению, см. BACKEND_CLEANUP_PLAN.md)

1. POST /api/streamer-mood/feed — 0 вызывающих (routes_wave4.py:20)
2. POST /api/bot/pacing/tick — pacing не подключён в chat_analyzer (routes_bot_intel.py:102)
3. /api/bot/corrections/learn|context|permanent — в рантайме не используются (routes_bot_intel.py)
4. POST /api/accounts/{id}/personality-shift — остался без UI (routes_persona_presets.py:141)
5. apply_dynamic_persona (bot_persona.py:333) — ноль вызовов
6. Lurker-поля bot_roles.py:80-85 — хранятся, не читаются
7. format_extended_persona_for_prompt — мёртвый СЕЙЧАС, но подключается в этапе 2 плана переработки (не удалять)

## Дрейф доков

- PLAN.md:4 и :196 ссылаются на VOICESTUDIO_PLAN.md — файла в main нет (живёт на ветке session/voicestudio).
- PLAN.md §9e (mood автообновление) и §9f (pacing/corrections «✅ подключены») — не соответствуют коду.
- FEATURE_OWNERSHIP.md — синхронизировать после выполнения плана переработки (этап 9).

Покрытие тестами: 1444 passed (02.09), включая аудит-тесты test_p7_panel_audit (JS-API ↔ бэкенд, пустой allowlist) — направление JS→бэк чистое, «мёртвых» вызовов из UI нет.
