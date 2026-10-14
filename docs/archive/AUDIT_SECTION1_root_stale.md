# Раздел 1 — Аудит и контроль готовности

> Дата аудита: 2026-08-28
> Метод: статический разбор `app/routes.py` (269 REST routes), `app/widgets.py` (112 REST routes),
> `app/routes.py` websocket/HTML routes (2), итого **383 backend-маршрута**; кросс-сверка с
> фактическими вызовами `api()/fetch()/window.open()` в `static/app.js` (76 уникальных URL)
> и содержимым 6 активных partial-шаблонов (`templates/partials/*.html`, реально включаемых
> через `base.html`). Живой Playwright smoke-тест использован для двух найденных и
> исправленных в этой сессии критических JS/DOM-багов (см. PR #2).

## Как читать

- **Активный UI** — реально подключённый шаблон/JS-код, доступный обычному пользователю панели.
- **Только backend** — маршрут существует и (обычно) покрыт тестами, но не вызывается из активного UI.
- **Мёртвый код** — код существует, но не подключён никаким путём (ни роутом, ни UI).
- **README врёт** — README документирует маршрут/фичу, которых по факту нет в коде.

## Итоговая таблица

| # | Функция / раздел | Статус | Файлы (backend) | Файлы (UI) | API | Тест | Ручная проверка | Что осталось |
|---|---|---|---|---|---|---|---|---|
| 1 | Dashboard (KPI, боты, live-события) | ✅ Работает | `routes.py` (`/api/runtime/status`, `/api/bots/status`) | `dashboard.html` | `/api/runtime/status`, `/api/bots/status` | частично | ✅ (в этой сессии) | — |
| 2 | Bots — список/фильтр/сортировка/CRUD | ✅ Работает | `routes.py` (`/api/accounts*`) | `bots.html` | 10+ routes | ✅ | ✅ | клик по карточке/двойной клик — см. план §4 |
| 3 | Bots — вкладки: Обзор/Характер/AI+TTS/Каналы+триггеры/Память+знания/Доп. | ✅ **Исправлено в этой сессии** | `routes.py` | `bots.html`, `app.js` | множество | ✅ | ✅ (Playwright) | — |
| 3a | ↳ `loadKnowledge` (База знаний + Mimicry) | ✅ Исправлено (PR #2) | `/api/accounts/{id}/kb`, `/api/accounts/{id}/style-examples` | `bots.html` | ✅ | ✅ 875/875 | ✅ | — |
| 3b | ↳ DOM-структура табов (patterns/triggers/events/filters/memory/knowledge/snippets) | ✅ Исправлено в этой сессии (commit `abc8649`) | — | `bots.html` | — | node --check OK, HTML сбалансирован | статически проверено, live Playwright — частично (см. «Осталось») | live-переверификация Playwright скриншотом после перезапуска сервера |
| 3c | ↳ Вкладка **Patterns** (📋) | ✅ Теперь достижима (была мёртвая) | `renderPatternsList`, `createPattern`, `deletePattern` | `bots.html` | `/api/accounts/{id}/patterns`, `/api/patterns/{id}` | ✅ | не проверено вручную после фикса | ручной клик по «🧠 AI и TTS» → убедиться, что паттерны видно |
| 3d | ↳ Вкладка **Events** (🔔 Twitch events) | ✅ Теперь достижима (была мёртвая) | `loadBotEvents`, `renderEventsList`, `createEvent`, `deleteEvent` | `bots.html` | `/api/accounts/{id}/events`, `/api/events/{id}` | ✅ | не проверено вручную после фикса | ручной клик по «📡 Каналы и триггеры» → убедиться, что события видно |
| 4 | Chat (отправка сообщений, live-лог) | ✅ Работает | `/api/send`, `/ws` | `chat.html` | ✅ | ✅ | не проверялось в этой сессии | — |
| 5 | Analytics/Stats | ⚠️ Частично | `/api/stats/all`, `/api/stats/sentiment`, `/api/stats/wordcloud` используются; `/api/stats/chat`, `/api/stats/heatmap`, `/api/stats/trending`, `/api/accounts/{id}/stats` — **не вызываются из UI** | `analytics.html` | 3 из 7 stats-роутов задействованы | ✅ (backend) | нет | либо добавить heatmap/trending виджеты в UI, либо удалить мёртвые роуты |
| 6 | Settings — AI/TTS/Backup/Security/Theme | ✅ Работает | множество | `settings.html` | ✅ | ✅ | нет | — |
| 7 | Settings — OBS-виджеты (список URL) | ⚠️ **Только копирование ссылок** | 112 routes в `widgets.py` (admin CRUD для goals/countdown/schedule/song-request/donation-challenges/top-donators/sub-goal/counters/anime-runner/mascot/chat-roulette/combo-counter/lower-third/…) | `settings.html` (только `<code>`+«📋 Копировать») | **~100 из 112 admin/public widget-роутов не вызываются вообще нигде в `app.js`** | нет UI-теста | нет | **Большой пробел**: нет ни одной формы для того, чтобы **задать** цели, добавить донат в топ, настроить расписание, крутить sub-goal и т.д. — все эти CRUD API есть, но панель управления ими отсутствует полностью. Виджеты можно только *смотреть* готовыми URL, но нечем их наполнить контентом из панели. |
| 8 | Bot Files (папки per-bot: bot.json/persona.json/…) | ❌ **Мёртвый код** | `app/bot_dirs.py` (`list_bot_files`, `read_bot_file`, `write_bot_file`, `delete_bot_file`) — **ни разу не импортируются в `routes.py`**, роутов нет вообще | нет | ❌ нет ни одного HTTP-роута | нет | — | README документирует 5 несуществующих роутов (`GET/PUT/DELETE /api/accounts/:id/files/...`, `GET .../files/export`) — **README врёт**, нужно либо реализовать роуты, либо убрать раздел из README |
| 9 | Streamer Face (фото стримера для vision) | ❌ **Backend есть, UI нет** | `/api/accounts/{id}/streamer-face` (GET/POST/DELETE), реализовано в `streamer_profile.py` | нет ни одного элемента в `bots.html`/`settings.html` | 3 роута, полностью нерабочие с UI | есть тесты на backend | нет | **План обновлён**: добавить вкладку «👤 О стримере» с формой загрузки/превью/удаления фото — см. PLAN_ALL_IN_ONE.md §9a.2 |
| 10 | Streamer Profile | ⚠️ Backend есть (`/api/accounts/{id}/streamer-profile`), UI не вызывает | `streamer_profile.py` | нет | не вызывается из `app.js` | тесты есть | нет | **План обновлён**: форма профиля (возраст/пол/локация/био/интересы/игры/стиль) + привязка к каналу при мультиканальных ботах — см. PLAN_ALL_IN_ONE.md §9a.1 и §9.2 |
| 11 | Personality Shift (временный shift настроения) | ❌ Backend есть, UI нет | `/api/accounts/{id}/personality-shift` | нет | не вызывается | тесты есть (`test_wave*`) | нет | **Решено**: реализовать как лёгкую автономность бота (read-only индикатор + тумблер интенсивности, без ручной формы чисел) — см. `FEATURE_OWNERSHIP.md` §4, `PLAN_ALL_IN_ONE.md` §9b |
| 12 | Chat Users (per-user toggle enabled) | 🟨 Backend готов и подключён, UI ещё нет | `/api/accounts/{id}/chat-users[...]`, `chat_analyzer._upsert_chat_user`/`_is_chat_user_enabled` | нет | вызывается из `on_message` | `tests/test_chat_users.py` (8 тестов) | да | **Частично выполнено**: backend полностью реализован — таблица `chat_users` теперь реально заполняется (ранее не заполнялась никогда), toggle enabled/disabled реально блокирует ответы бота. Осталось: вкладка/список в UI (`bots.html`+`app.js`). См. `FEATURE_OWNERSHIP.md` §5, `PLAN_ALL_IN_ONE.md` §9c |
| 13 | Shared User Facts (общая память между ботами) | ❌ Backend есть, UI нет | `/api/shared-user-facts*` | нет | не вызывается | есть модульные тесты | нет | **Решено**: реализовать — см. `FEATURE_OWNERSHIP.md` §6, `PLAN_ALL_IN_ONE.md` §9d |
| 14 | Streamer Mood Feed | ❌ Backend есть, UI нет | `/api/streamer-mood/*` | нет | не вызывается | тесты есть (`test_wave*`) | нет | **Решено**: виджет (read-only) — см. `FEATURE_OWNERSHIP.md` §7, `PLAN_ALL_IN_ONE.md` §9e |
| 15 | Prompt Pool (ежедневные промпты) | ✅ Удалено | — (роуты/таблицы/вызов из chat_analyzer удалены) | нет | нет | тестов не было | да | **Выполнено**: код удалён — роуты из `routes.py`, таблицы `prompt_pool`/`prompt_pool_daily` из `database.py`, вызов `_get_daily_prompt` из `chat_analyzer.py`. См. `FEATURE_OWNERSHIP.md` §15, `PLAN_ALL_IN_ONE.md` §22 |
| 16 | Bot Conversation Threads/Corrections/Pacing | ❌ Backend есть (5-8 роутов), UI нет | `/api/bot/conversation/*`, `/api/bot/corrections/*`, `/api/bot/pacing/*` | нет | не вызывается | тесты есть | нет | **Решено**: подключить к `chat_analyzer.on_message` с ограниченным влиянием (мягкий контекст/вес, не переопределяет персону) — см. `FEATURE_OWNERSHIP.md` §8, `PLAN_ALL_IN_ONE.md` §9f |
| 17 | Clip Detector | ⚠️ Частично: `config`/`moments` могут дергаться из UI, `create-clip`/`message` — нет | `/api/bot/clip-detector/*` | не найдено явных вызовов | не проверено | тесты есть | нет | **Решено**: виджет обнаружения всплеска чата + кнопка ручного создания клипа (без автосоздания) — см. `FEATURE_OWNERSHIP.md` §9, `PLAN_ALL_IN_ONE.md` §9g |
| 18 | VOD RAG (индексация VOD, поиск) | ✅ Удалено | — (модуль `app/vod_rag.py`, роуты, вызов из chat_analyzer удалены) | нет | нет | тесты удалены (`test_vod_rag.py`, `test_vod_rag_module_imports`) | да | **Выполнено**: `app/vod_rag.py` удалён, роуты `/api/vod-rag/*` удалены из `routes.py`, вызов из `chat_analyzer._build_prompt` и `vod_rag_*` дефолты настроек удалены. См. `FEATURE_OWNERSHIP.md` §16, `PLAN_ALL_IN_ONE.md` §22 |
| 19 | Replay Sessions | ❌ Backend есть, UI нет | `/api/replay/sessions*` | нет | не вызывается | тесты есть (`test_wave4`) | нет | **Решено (владелец: «да, надо»)**: реализовать — см. `FEATURE_OWNERSHIP.md` §10, `PLAN_ALL_IN_ONE.md` §9h |
| 20 | Twitch OAuth flow (`start/poll/cancel`) | ⚠️ Не найдено вызовов в `app.js` | `/api/twitch-oauth/*` | не найдено | не вызывается | нет явных тестов в выборке | нет | **Решено**: реализовать — кнопка «Войти через Twitch» в форме добавления бота — см. `FEATURE_OWNERSHIP.md` §11, `PLAN_ALL_IN_ONE.md` §9i |
| 21 | Action Log (revert) | ⚠️ Не найдено вызовов | `/api/action-log*` | не найдено в partials | не вызывается | нет | нет | **Решено**: реализовать вкладку «Журнал действий» с revert и CSV export — см. `FEATURE_OWNERSHIP.md` §12, `PLAN_ALL_IN_ONE.md` §9j |
| 22 | Feedback / AI-feedback | ❌ Backend есть, UI нет | `/api/feedback*`, `/api/ai-feedback*` | нет | не вызывается | тесты есть | нет | **Решено**: реализовать 👍/👎 в живом логе + сводка в Analytics — см. `FEATURE_OWNERSHIP.md` §13, `PLAN_ALL_IN_ONE.md` §9k |
| 23 | Backup/Restore | ✅ Работает (не через `api()`, напрямую `fetch`/`window.open`) | `/api/backup/download`, `/api/backup/restore` | `settings.html` | ✅ | тесты есть | не проверялось в сессии | — |
| 24 | Analyzer presets apply | ⚠️ **README документирует несуществующий роут** | Реален только `GET /api/analyzer-presets`. `POST /api/accounts/:id/analyzer/apply-preset`-подобного роута **нет** в коде | не найдено вызовов apply | — | — | — | README §"Анализ чата (v10)" содержит вымышленный `POST /api/analyzer-presets/:name/apply` |
| 25 | index_v10_backup.html (старая монолитная панель, 756 КБ) | ❌ Мёртвый файл | — | `templates/index_v10_backup.html`, нигде не рендерится (`index.html` = `{% extends "base.html" %}`) | — | — | — | **Решено (владелец: «пускай будет, если чё посмотрим, но пока мёртвый код»)**: не удалять сейчас, явно зафиксировано как архивный справочник — см. `FEATURE_OWNERSHIP.md` §18, `PLAN_ALL_IN_ONE.md` §22. Пересмотреть после переноса функций §9b-9k/§23/§24 |
| 26 | Миграция БД (чистая vs существующая) | ✅ Проверено | `app/database.py`: `CREATE TABLE IF NOT EXISTS` + `_add_column_if_missing()` паттерн, идемпотентно | — | — | Каждый из 875 тестов создаёт БД с нуля через `init_db()` (`tests/conftest.py::tmp_db`) — путь «чистой БД» покрыт исчерпывающе. Путь «старая БД + новая колонка» покрыт частично через `_add_column_if_missing`, отдельного теста «взять реальную v10-базу и обновить» не найдено | не проверялось вручную | добавить (опционально) тест, который берёт снэпшот старой схемы и прогоняет `init_db()` поверх неё |

## Итоги по бэкенду

- **Всего backend-маршрутов**: 269 (`app/routes.py`) + 112 (`app/widgets.py`) + 2 (websocket/HTML) = **383**.
- **Вызывается из активного UI (`app.js`)**: 76 уникальных URL-паттернов.
- **Не вызывается из активного UI**: **~140 маршрутов** (ROUTES minus вызываемые), из них:
  - **99** всё ещё присутствуют в мёртвом `templates/index_v10_backup.html` — то есть UI для них когда-то существовал, но потерялся при переходе на текущую архитектуру `base.html` + `partials/*`;
  - **41** не встречаются вообще нигде во фронтенде — либо чисто внутренние (bot-runtime → bot-runtime API), либо реально orphaned фичи.
- Самый крупный пробел — **OBS-виджеты**: 112 backend-роутов, из которых панель использует всего пару (`downloadBackup`-подобных `fetch` не в счёт — виджеты вообще не имеют форм редактирования в `settings.html`/`widgets.html`, только кнопки «Скопировать URL»).

## Найденные и исправленные в ходе аудита баги (эта сессия + предыдущая)

1. **Критический**: `loadKnowledge` не была определена → `ReferenceError` при загрузке `app.js` → TDZ-поломка `_botTabLoaders` → не работало переключение ВСЕХ вкладок настроек бота, кроме первой. **Исправлено, PR #2.**
2. **Критический (визуальный)**: 6 диапазонов `.bot-tab` (`patterns`, `triggers`, `events`, `filters`, `memory`, `knowledge`, `snippets`) + дубль `voice-clones` находились физически ВНЕ `<section id="section-bots">`, из-за чего при показе одной из этих вкладок и последующем переходе на другой раздел (например, Dashboard) их содержимое оставалось видимым и «протекало» на другие страницы. **Исправлено в этой сессии** (commit `abc8649`): все блоки перенесены внутрь `#botSettingsPanel`.
3. **Средний**: вкладки `patterns` и `events` были полностью недостижимы (не входили ни в одну группу `BOT_TAB_GROUPS`), несмотря на полностью рабочий CRUD JS+backend. **Исправлено**: добавлены в `BOT_TAB_GROUPS.ai` и `.flow` соответственно.
4. **Средний**: `BOT_TAB_GROUPS.ai` ссылалась на несуществующий `botTab-ai` div (мёртвая ссылка). **Исправлено**: заменено на реальный `patterns`.
5. **Малый**: `botTab-knowledge` содержал 2 лишних закрывающих `</div>` (сломанная вложенность HTML). **Исправлено** при переносе блока.
6. **Документационный**: README документирует минимум 2 несуществующих API (`POST /api/accounts/:id/files/...` × 5 роутов, `POST /api/analyzer-presets/:name/apply`) и устаревшее число тестов (846 вместо фактических 875). **Требует правки README** (см. ниже).

## Что осталось сделать (не покрыто в этой сессии)

- [ ] Живая Playwright-переверификация DOM-фикса `bots.html` (после того, как сервер будет перезапущен и протестирован заново) — скриншот «до/после» повторной навигации Dashboard → Bots → Dashboard.
- [ ] Ручной клик-тест новых вкладок «Patterns» и «Events» в браузере.
- [x] Решить судьбу `templates/index_v10_backup.html` — **решено** (владелец: пускай будет как мёртвый код, не удаляем сейчас) — см. `FEATURE_OWNERSHIP.md` §18, `PLAN_ALL_IN_ONE.md` §22.
- [x] Решить судьбу orphaned backend-роутов (#8, #11-#22) — **решено поштучно**: полный реестр решений — `FEATURE_OWNERSHIP.md` (12 пунктов на реализацию, 2 как виджет, 2 на удаление). Осталось только сама реализация кода (см. `PLAN_ALL_IN_ONE.md` §9b-9k, §22-24).
- [ ] Реализовать `Bot Files` API (#8) — решено в `FEATURE_OWNERSHIP.md` §1, план в `PLAN_ALL_IN_ONE.md` §23. Сама реализация кода ещё не начата.
- [ ] Добавить в панель управление контентом OBS-виджетов (#7) — решено в `FEATURE_OWNERSHIP.md` §2, план в `PLAN_ALL_IN_ONE.md` §24. Сама реализация кода ещё не начата.
- [ ] Реализовать вкладку «О стримере» (профиль + фото, привязка к каналу при нескольких каналах на бота) — план детализирован в PLAN_ALL_IN_ONE.md §9a, §9.1–9.2 (пункты #9-10 этой таблицы).
- [ ] Реализовать недостающие stats-виджеты (#5: heatmap/trending/chat/per-bot) — решено в `FEATURE_OWNERSHIP.md` §14, план в `PLAN_ALL_IN_ONE.md` §17 (Stats).
- [x] Удалить мёртвый код Prompt Pool (#15) и VOD RAG (#18) — решено в `FEATURE_OWNERSHIP.md` §15/§16, план в `PLAN_ALL_IN_ONE.md` §22. Выполнено: код удалён, тесты пройдены (см. коммит по этой задаче).
- [ ] Обновить README: убрать несуществующие роуты, поправить число тестов (875), обновить архитектурную секцию (файл `templates/index.html` — не «12k+ строк», а `{% extends "base.html" %}` + 6 partials).
