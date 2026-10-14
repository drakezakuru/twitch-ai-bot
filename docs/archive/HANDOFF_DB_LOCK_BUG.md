# HANDOFF — Баг «database is locked» + накопление aiosqlite-коннектов в тестах (31.08.2026)

> Прочитай сначала AGENTS.md. Работаем прямо в `twitch-ai-bot/` (main), worktree-папок нет.
> Все изменения ниже уже в рабочем дереве, часть заскейджена/закоммичена — см. git log.

## Что уже сделано в этой сессии (зелёное, можно не трогать)

1. **P0 мерж** — `session/roles` (R1–R5 + §R3) смержен в main: коммит `133d595`.
2. **P1 UI §R3** — карточка «🛠 Стрим-инструменты» в модераторской вкладке бота:
   - `templates/partials/bots.html` — карточка после «Автомодерация»:
     режимы off/suggest/auto на каждый инструмент (category/ai_category/title/
     slow/follower/emote_only/unique), кнопка propose вручную (title/category),
     история действий (GET /api/stream-intents/history).
   - `static/app.js` — секция «PLAN_REMAINING P1: §R3 стрим-инструменты (UI)»
     (перед BRAIN_PLAN): loadStreamTools/saveStreamToolMode/proposeStreamAction/
     proposeStreamTitle/proposeStreamCategory/loadStreamToolsHistory + i18n ru/en/ua.
     Хук loadStreamTools(id) добавлен в loadBotModeration.
     Сохранение режимов идёт через role-config API (stream_tool_modes в moderator config).
   - Заодно добавлены 4 отсутствующих i18n-ключа (btn.download, settings.panel_log_tail,
     settings.panel_log_tail_hint, widgets.preset_applied) — чинит
     test_plan_v13_features::test_all_active_template_and_javascript_i18n_keys.
3. **widgets/blur-guard-v2/index.html** — добавлен пролог `_WIDGET_API_BASE`
   (чинит test_widget_api_base).
4. **FILE_ZONES.md** — `PLAN_CURRENT.md` → `plans-archive/PLAN_CURRENT.md`,
   добавлен `PLAN_REMAINING.md` (чинит test_plan_file_zones).
5. **DEADLOCK ФИКС (главное)** — тесты вешались НАВСЕГДА на teardown tmp_db
   (42-й тест test_brain_modules, stack: conftest.py → loop.run_until_complete(
   _shared_db.close()) → selectors.select навечно).
   Причина: cross-loop async close() aiosqlite 0.22.1: воркер-поток соединения
   уже мёртв, future никогда не резолвится; `wait_for` не спасает, потому что в
   `close()` в finally есть ещё один `await future` на stop().
   Фикс в `tests/conftest.py`: `_sync_hard_close()` — синхронное закрытие:
   `shared_db._connection.close()` (sqlite3), `_running=False`, poison-pill
   `_noop_stop` → sentinel в `_tx` очередь, `thread.join(3)`. Ноль зависаний.
6. **app/database.py**: module-level `_init_lock = asyncio.Lock()` привязывался
   к loop первого теста → RuntimeError «bound to a different event loop».
   Заменено на `_get_init_lock()` — пересоздание лока при смене event loop.
   В init_db и _ensure_shared добавлен `PRAGMA busy_timeout=5000`.
7. **app/widget_bus.py** — та же правка для `_lock` (`_get_lock()`).

Состояние полного прогона: **1290 passed, 3 failed, 0 hung, ~188s**
(было: навсегда висло на 42-м тесте + 7 failed).

## ОСТАВШАЯСЯ ПРОБЛЕМА — передай Клоду как есть

**Симптом:** flaky `sqlite3.OperationalError: database is locked` в 1–3 тестах
из tests/test_raid_follow.py (какие именно — меняется от прогона к прогону;
падают внутри `await init_db()` на `PRAGMA journal_mode=WAL` либо на первых
INSERT; при этом busy_timeout=5000 уже стоит и НЕ спасает).

**Факт из диагностики (gc.get_objects() срез перед падением):**
в процессе живут ДЕСЯТКИ брошенных `aiosqlite.Connection`, у которых
`_connection` (sqlite3.Connection) всё ещё ОТКРЫТ. Каждый следующий тест
создаёт новый tmp_path/bot.db, но старые открытые sqlite3-коннекты остаются
в памяти (gc их не собирает — на них ссылаются замыкания/круги), и несколько
из них указывают на ФАЙЛ предыдущих tmp-баз, а как минимум один — может
держать CURRENT файл. SQLite не даёт понять какой (PRAGMA database_list из
чужого потока кидает "SQLite objects created in a thread can only be used in
that same thread").

**Кто это создаёт (гипотеза, проверяема):**
`tests/conftest.py::_sync_hard_close` закрывает ТОЛЬКО `database._shared_db`,
но в кодовой базе есть места, которые создают СВОИ aiosqlite-коннекты мимо
синглтона, и они живут дольше теста. Кандидаты, которые стоит проверить:
- `app/server.py` импортируется тестами заново (`_reload_server` в
  test_raid_follow / pop из sys.modules) — при реимпорте модульный код может
  стартовать фоновые задачи/коннекты, привязанные к loop УМЕРШЕГО теста
  (событийный цикл закрыт, а worker-поток коннекта жив и держит файл).
- `tests/test_typing_indicator.py::test_typing_indicator_broadcasts_event`
  и `..._no_chatter` — создают `ca.ChatAnalyzer(...)` singleton и зовут
  `init_db()` БЕЗ фикстуры tmp_db (monkeypatch-only) → пишут в РЕАЛЬНЫЙ
  data/bot.db репо, плюс оставляют коннект.
- `app/backup.py`, `app/standalone.py` — `database.close_db()`.
- Пересоздание `_init_lock` при смене loop (моя правка) может оставить
  «осиротевший» поток _ensure_shared, если смена loop происходит, пока
  старый _ensure_shared ещё ждёт lock (гонка при быстрой смене loopов).

**Что попробовать Клоду (по убыванию вероятности):**
1. В `_sync_hard_close` дополнительно: пройтись по gc.get_objects(), найти
   ВСЕ aiosqlite.Connection с `_connection is not None`, из них выбрать те,
   чей файл == tmp_path/bot.db (сопоставить по `PRAGMA database_list` нельзя
   из чужого потока; вместо этого вести реестр: monkeypatch
   `aiosqlite.connect` в fixture, регистрировать каждый созданный коннект и
   закрывать их ВСЕ синхронно в teardown — это надёжный общий фикс).
2. Проверить гипотезу: `pytest tests/test_typing_indicator.py
   tests/test_raid_follow.py` — вместе ли падает; если да, чинить
   typing-тесты (дать им tmp_db).
3. `kill -9` воркер-потоков нельзя; но можно в conftest finalizer:
   `for t in threading.enumerate(): if t is not threading.main_thread()
   and t.name.startswith...` — не убивать, а дождаться только СВОИХ.
4. Быстрый костыль, если время жмёт: в tmp_db teardown после
   _sync_hard_close подождать `time.sleep(0.05)` и повторить попытку
   открытия в init_db (retry x3 по 100ms на OperationalError locked) —
   маскирует, но стабилизирует прогон.

## Команды

```bash
cd ~/Desktop/боты/twitch-ai-bot-v10/twitch-ai-bot
# один прогон raid_follow (флакует):
~/.local/bin/pytest tests/test_raid_follow.py -q -p no:cacheprovider
# полный:
nohup ~/.local/bin/pytest tests/ -q -p no:cacheprovider > /tmp/opencode/full.log 2>&1 &
```

## Что осталось после фикса (по PLAN_REMAINING.md)

- P1 финальный полный зелёный pytest → коммит.
- P2: сверить §3 (Каналы/Twitch) с §S5; FEATURE_OWNERSHIP.md/FILE_ZONES.md
  под новые модули (stream_intents, stream_intent_routes, mod_feed_routes,
  bot_roles, role_routes, per_bot_logging, log_routes, beep_guard,
  stream_tools_routes); аудит «белых» полей; мини-примеры «Прочих виджетов».
- P3: PLAN_PANEL_REWORK.md (Мозг 2.0 per-bot, аудит всех менюшек, UX-стандарт).
