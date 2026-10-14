# CONTEXT — актуальный контекст проекта (03.09.2026)

> ЕДИНСТВЕННЫЙ контекстный файл (03.09: в него влит хендофф ночной сессии переработки).
> Всё историческое — `docs/archive/`. Живой план: `PLAN_NEW.md` (старый `PLAN.md` — история).

## Что это за проект

Twitch AI Bot — панель управления ИИ-ботами для Twitch (болтуны, модераторы,
voice-companion, lurker). FastAPI + SQLite (`data/bot.db`, aiosqlite,
WAL) + веб-панель (`static/app.js` + чанки `static/app/*.js`, шаблоны) + OBS-виджеты (`/widget/*`, `/obs/*`).

Компоненты:
- **Роли ботов** (`accounts.bot_role`: chatter/moderator/voice_companion/lurker)
  + per-role конфиги `accounts.role_config_json` → `app/bot_roles.py`,
  `app/role_routes.py`. Вкладки панели перестраиваются по роли (8 групп, Роль — в Обзоре).
- **Мозг/промпт**: сборка system prompt — `app/chat_analyzer.py` ~2430–2570,
  карта — `docs/BRAIN_PER_BOT_MAP.md`; экран «Мозг бота» — `app/brain_preview.py`.
- **Характер и влияния**: персона (`bot_persona.py`, use_persona ВКЛ по умолчанию),
  гейты `influence_*` + мастер провокаций, персист `analyzer_settings` в БД.
- **Чат и виджеты**: Twitch-чат pipeline + TTS-озвучка ответов в стрим (W2);
  реестр виджетов `app/widget_inventory.py` (39 шт), смысловые биндинги, privacy-режим.
- **Модерация**: гейты по роли, хоткеи, TTS-дублирование, таймаут-политика; mod-feed + `/widget/mod-feed`.

## Структура репозитория

```
twitch-ai-bot-v10/
├── AGENTS.md              # правила параллельной работы (читать ДО работы)
├── data/                  # общие данные вне репо
└── twitch-ai-bot/         # ГЛАВНЫЙ git-репозиторий (ветка main)
    ├── CONTEXT.md         # этот файл
    ├── PLAN_NEW.md        # единый живой план (всё недоделанное)
    ├── PLAN.md            # старый план (история)
    ├── FILE_ZONES.md      # зоны файлов/сессий (проверяется автотестом!)
    ├── FEATURE_OWNERSHIP.md
    ├── docs/archive/      # ВСЕ старые планы/ченджлоги/аудиты/хэндоффы
    ├── app/               # FastAPI-бэкенд (роуты — `app/*_routes.py` + include в server.py)
    ├── static/ templates/ # панель
    ├── widgets/           # OBS-оверлеи
    ├── tests/             # pytest (~1480; полный — см. PLAN_NEW.md §5) + _db_registry.py
    └── scripts/           # разовые скрипты
```

Живая сессионная ветка: `session/voicestudio` (НЕ трогать, проект отложен).
Остальные worktree-папки удалены 03.09 (слиты в main), ветки целы.

## Решения владельца (НЕ менять без него)

1. **Удаления бэкенда — только по подтверждению** (PLAN_NEW.md §3: C1/C2/C7 — удалять,
   C3 — мб реализовать, C4–C6 ждут решения).
2. **use_persona = ВКЛ по умолчанию** (характер влияет сразу).
3. **Разговор с ботом = чат канала Twitch + TTS** (W2; старая микрофон/Whisper-модалка убрана;
   Whisper/beep pipeline остаётся для блюра слов/наград — Q9).
4. **session-voicestudio НЕ трогаем.**
5. Голос/TTS — только voice_companion (`tts_reply_percent` — существующий, второго нет);
   глобальные настройки = только дефолты/ключи; lurker — минимум.
6. Пресеты поведения удалены — только пресеты Характера. Паттерны UI убран (бэк = C7, отдельно).
7. Профиль стримера и attitude — строго per-channel, глобальный scope убрать (W4-UI, Q11).

## Состояние (03.09) — коротко

- W-серия слита в main (W2–W10 + W11); точечные W-тесты 22 passed; полный pytest и browser
  gate — pending (PLAN_NEW.md §1/§5).
- P5-сплиты: app.js → чанки `static/app/*.js` (карта — `docs/APP_JS_MAP.md`, новые маркеры
  `// ── ...` добавлять в APPENDIX, иначе падает `test_p3_app_js_map`); routes.py → `app/*_routes.py`.
- ⚠️ **OpenRouter-ключ в Настройках был невалиден** (401/404 на `openrouter/owl-alpha`,
  найдено 03.09 ночью) — если боты молчат, проверить ключ/модель в Настройках → AI.
- Известные хвосты: `loadStreamerMood`/`loadMoodFeed` — мёртвые определения без вызовов
  ($-гварды); `15_feedback_2908.js` пресеты Характера НЕ удалять (общий эндпоинт);
  никакой кириллицы внутри `onclick`; перед живой проверкой — рестарт `python3 run.py`.

## Запуск панели / окружение

- Запуск (владелец стартует ботов только через панель): `python3 run.py`
  из папки репо (или `start.sh`). Панель: http://localhost:8000 (порт/хост —
  в run.py; .env.example — переменные окружения, Twitch-токены — через
  OAuth-вход в панели).
- Тесты не требуют живого Twitch/OBS — всё мокается; для реальной проверки
  нужен живой OBS/Twitch (владелец).

## Git-workflow

- Работаем ПРЯМО в main (сессионных папок нет, кроме voicestudio).
- Коммит после каждого завершённого шага (тесты зелёные → commit),
  формат: короткая тема с префиксом (fix/docs/feat/§-метка), как в git log.
- НЕ делать: push без владельца, stash, checkout/restore/reset чужих файлов,
  правки чужих зон (FILE_ZONES.md).

## Тесты — критически важные факты (инфра стабилизирована 31.08)

- Тесты: `~/.local/bin/pytest tests/ -q` из папки репо. `tmp_db` — autouse-фикстура: КАЖДЫЙ
  тест получает свой `tmp_path/data/bot.db` (никто не пишет в реальную базу).
- **Реестр коннектов `tests/_db_registry.py`**: патчит `aiosqlite.connect`
  ДО импорта app.*; в teardown закрывает ВСЕ коннекты В ИХ worker-потоках.
  НИКОГДА не звать `raw.close()` из чужого потока (вечное зависание); только сброс `conn._connection`.
- `app/database.py::_get_init_lock` / `app/widget_bus.py::_get_lock` —
  asyncio.Lock пересоздаётся при смене event loop.
- i18n: новые тексты сразу ru/en/ua (ключ `t('...')` должен встречаться ≥3
  раз в `static/app.js`, иначе падает test_plan_v13_features).
- Helix: `app/twitch_helix.py`; токены через `chat_analyzer._account_token`;
  каналы нормализуются `lstrip('#').lower()`.
- Новые эндпоинты — отдельный `app/*_routes.py` + одна строка include_router
  в `app/server.py`.
- **не импортировать `app.server` на уровне модуля теста** (переимпорты
  через sys.modules.pop + reimport ломают синглтоны).
