# HANDOFF-RESEARCH — результаты read-only исследования (09.09.2026)

> Продолжение `HANDOFF_NEXT_SESSION.md` (п.1 его порядка работ выполнен; после записи
> решений владельца в DECISIONS.md и PLAN_TODO.md предыдущий handoff удалён — история
> в git и `docs/archive/`).
> Ветка `audit/c010-behavior-tests`, только локальная работа. Этот документ — факты для
> интервью владельца и записи решений. После записи DEC-* можно удалить вместе с
> `HANDOFF_NEXT_SESSION.md`.

## 1. Роль lurker — минимум настроек

Файлы: `app/bot_roles.py`, `app/role_routes.py`, `static/app/06_roles.js`,
`static/app/03_bots.js`, `tests/test_bot_roles.py`, `tests/test_roles_runtime.py`.

- Роли: chatter, moderator, voice_companion, lurker (`bot_roles.py:16`).
- **Lurker-конфиг уже минимальный: ровно одно поле `mention_reply` (default false)**
  — `bot_roles.py:80–86`. Исторические collect-поля (collect_users/lore/observations,
  memory_limit, auto_cleanup) удалены ранее (C6), тест `test_bot_roles.py:119–129`
  запрещает их возврат: `set(ROLE_DEFAULT_CONFIGS["lurker"]) == {"mention_reply"}`.
- Валидатор молча отбрасывает неизвестные ключи (`bot_roles.py:116–150`), т.е. в API
  lurker-конфигом можно задать только `mention_reply`.
- Runtime-гейт: lurker молчит всегда, кроме прямого @ при `mention_reply=true`
  (`chat_analyzer.py:2085–2100`); гейт стоит до генерации/отправки.
- **Обнаружено несоответствие UI:** единственный lurker-контрол спрятан.
  `ROLE_TAB_VISIBILITY` скрывает вкладки brain-x/identity/moderation/voice/memory
  (`03_bots.js:407–412`), а `relocateRoleConfig` не находит для lurker слота и прячет
  всю role-форму (`03_bots.js:419–429`). Настроить `mention_reply` можно только API.
- **Устаревшее описание роли:** `role.desc.lurker` (`06_roles.js:37–41`) обещает
  «копит память о зрителях, lore, базу знаний для других ботов» — collect-функций
  больше нет. Тест `test_p8_c8_roles_2_0.py` требует наличие desc, но не этот текст.
- Для lurker в панели остаются видимыми общие вкладки/блоки (Behavior/quick settings,
  flow/advanced) — кандидаты на скрытие при «урезании».

## 2. Папки: текущая структура

Файлы: `app/bot_dirs.py`, `app/runtime_paths.py`, `app/qa_profile.py`,
`app/per_bot_logging.py`, `tests/test_bot_dirs_isolation.py`.

- Per-bot папки: `data/bots/{account_id}_{safe_nickname}/` с подпапками
  `config.json, prompts/, memory/, voice/, logs/, exports/` (`bot_dirs.py:41–84`).
  БД (`data/bot.db`) остаётся source of truth; папки — файловое зеркало
  persona/memory/логов, создаётся при старте бота (`routes.py:1015–1018`).
- Per-bot логи: `logs/<ник>/bot.log|chat.log` — вне data/ (`per_bot_logging.py`).
- Роль в имени папки и группировке НЕ участвует; группировка в панели — CSS-класс
  `role-lurker` на карточке (`03_bots.js:51`), секции/фильтра по роли нет.
- «Отдельная папка для lurkers» может значить: (а) filesystem-группировка по роли,
  (б) отдельная секция/фильтр/вкладка списка ботов в панели, (в) ничего нового —
  у каждого бота уже своя папка. Владелец должен выбрать — не угадывать.

## 3. OAuth: авто-обновление сессий

Файлы: `app/server.py:219–278`, `app/routes_token_refresh.py`, `app/twitch_helix.py:65–86`,
`app/routes_device_code.py`, `app/twitch_credentials.py`, `app/database.py:680–682`,
`app/security.py`, `static/app.js`.

- Модель: `accounts.token` (user access), `accounts.refresh_token` (default ''),
  `accounts.token_expires_at` (unix-сек, default 0); оба секрета через Fernet.
  Client id/secret — в settings (`twitch_credentials.py`), нужны для refresh.
- **Авто-refresh уже существует, но невидим:** настройка `auto_refresh_tokens`
  (default off, `routes_token_refresh.py:51–59`), фоновый цикл каждые 10 минут
  (`server.py:219–278`) обновляет аккаунты с непустым `refresh_token`, когда срок
  истекает < 30 минут; ротация refresh_token учитывается. Ручной endpoint
  `POST /api/accounts/{id}/refresh-token`.
- **Панель не показывает ничего из этого:** grep по `/refresh-token`,
  `/api/settings/auto-refresh`, `has_refresh_token` в `static/` пуст
  (остатки UI только в index_v10_backup.html). Статусов valid/expired у ботов в UI нет.
- `token_expires_at` заполняется только device-flow (`routes_device_code.py:79–98`)
  и refresh-циклом. При ручной вставке токена (`routes.py:198–219`) — навсегда 0.
- Не продлеваются: токены без refresh_token (типично для twitchtokengenerator —
  сайт, который панель сама рекомендует), токены при отсутствии client secret,
  токен Chat Logger (plaintext в `data/chatlogger.sqlite3`, колонки refresh_token нет).
- Refresh-on-401 (при неудачном логине IRC) отсутствует.

## 4. Баг Chat Logger: неправдивая длительность токена

Файлы: `app/chat_logger_routes.py:142–195`, `static/app.js:1983–1985, 2109–2150`,
`tests/test_p8_chat_logger.py:127–176`.

- Статус считается через Twitch `/oauth2/validate` (`validate_token`, кэш 10 мин).
- **Причина лжи:** `validate_token` инициализирует результат без ключа `error`
  (`chat_logger_routes.py:151`), ветки исключений/non-200 его не выставляют
  (`:159–167`). Различение «истёк» vs «не смогли проверить» в `token_status`
  (`:188`) мёртвое → **сетевая ошибка/5xx/429 показывается как «🔴 Токен истёк»
  с 0 дней**. Негатив кэшируется на 10 минут.
- Мелочи: `round(days)` завышает остаток; в unknown отдаётся `0` вместо `null`.
- Тест покрывает valid/expiring/expired, но не `unknown` (`test_p8_chat_logger.py:148–149`).
- Правдивый контракт: `expired` — только подтверждённый 401; `unknown` +
  `expires_in_days: null` при сетевом сбое; не кэшировать негатив; без обещаний
  авто-обновления (токен логгера непродляемый в принципе).

## 5. Массовые операции: боты × каналы

Файлы: `app/routes.py:159–693, 280–315, 1132–1171`, `app/routes_engagement.py:174,216`,
`static/app/03_bots.js:25, 54, 84–155, 1170–1186`, `templates/partials/bots.html:8`.

- Есть: выделение нескольких ботов чекбоксами (`_selectedBots`), bulk-bar со
  старт/стоп/удалить; `POST /api/bulk/delete`; `start_all`/`stop_all`.
- Добавление канала — только per-account: `POST /api/accounts/{id}/channels`
  (INSERT OR IGNORE, unique(account_id, channel_name)) и runtime `join`.
- **Bulk «каналы → многим ботам» и «боты → каналу» отсутствуют** как API, так и UI.
  Канал не является сущностью первого класса в UI (списка каналов нет).
- Статусы: БД хранит только `enabled`; runtime-статусы
  connecting/online/error/offline + `last_error` в `bot_manager.BotInstance`
  (`bot_manager.py:19–34`, `382–399`), классификация `oauth_expired`/`network_error`/
  `twitch_error` (`:297–307`). Панель показывает бейдж и причину
  (`02_dashboard.js:79–108`). Фильтр в UI только «подключено/отключено»
  (`03_bots.js:157–168`); фильтров error/expired/disabled нет, статуса
  «expired» как класса фильтра не существует (есть `last_error` и `token_expires_at`).

## 6. Проверка «бот реально работает» / тестовый стрим

Файлы: `app/stream_tools_routes.py:295–377, 612–670`, `app/routes.py:1132–1171`,
`app/bot_manager.py:102–108, 382–399`, `app/qa_profile.py`, `scripts/run_qa_panel.py`,
`tests/test_track6_chatbot_acceptance.py`.

- Пассивные проверки уже есть: `check-connection` (Helix /users с токеном),
  `scope-check` (validate + сверка scopes), runtime-статус IRC-подключения
  (`state: online` после `event_ready`), health-события в WS.
- `POST /api/accounts/{id}/join` реально заходит в чат канала (read-only присутствие,
  без сообщений) — де-факто «IRC join test» через start+status.
- Офлайн-инфраструктура: QA-профиль (3 фейковых бота+канала, сид-сообщения,
  sentinel-токены, без внешних вызовов), фейковые TwitchIO-сообщения + `_FakeAI`
  в acceptance-тестах, `run_qa_panel.py`.
- Чего нет: end-to-end «бот написал контрольное сообщение в тестовый чат» — это
  единственный путь с реальной записью в чат (нужен scope `chat:edit` и решение
  владельца о реальном канале).

## Вопросы для интервью (все уточняются, не угадываются)

1. «Отдельная папка lurkers» = секция/фильтр в панели, вкладка, filesystem-группа или
   «уже есть per-bot папки — достаточно»?
2. Что показывать lurker-карточке: вернуть видимость `mention_reply`, скрыть общие
   вкладки, обновить устаревшее описание роли?
3. Авто-refresh: включить default? показать статусы/кнопку в панели? что показывать
   ботам без refresh_token (честный «не продлевается» статус)?
4. Bulk-операции: какие направления (боты→каналы, канал→боты), поведение при частичных
   ошибках (per-item results), идемпотентность.
5. Тестовый стрим: пассивная проверка (join+статус+validate) достаточна или нужен
   контрольный пост в чат (реальный канал/свой канал, scope chat:edit)?
6. Chat Logger: подтверждён правдивый контракт (unknown ≠ expired)?
