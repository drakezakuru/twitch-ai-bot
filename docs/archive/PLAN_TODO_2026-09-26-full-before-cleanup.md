# PLAN_TODO — единственный активный план (ревизия 13.09.2026)

> Предыдущая версия плана целиком (с полным журналом приёмки Режиссёра и всеми деталями
> пунктов) — [docs/archive/PLAN_TODO_2026-09-13-full-before-rewrite.md](docs/archive/PLAN_TODO_2026-09-13-full-before-rewrite.md).
> Закрытые этапы прошлых недель — в `docs/archive/PLAN_TODO_2026-09-12-evening.md` и
> `docs/archive/PLAN_DONE_2026-09.md`.

## Статусы

У каждого пункта стоит один статус:

- ✅ — готово и принято, не переделывать
- 🔲 — не начато
- ⏳ — начато, осталась часть
- ⏸ — ждёт владельца (агент не исполняет сам)

Правила работы — [AGENTS.md](AGENTS.md): один пункт = один коммит, профильные тесты зелёные
до коммита, общие файлы править точечно, production `data/bot.db` не трогать. Решения
владельца — [docs/DECISIONS.md](docs/DECISIONS.md) (в плане только ID: `DEC-OWNER-…`).

### Как вести пункт (соглашение от 13.09)

- **Подпункты = отдельные коммиты.** Части `(а)/(б)`, `E1…E4`, `F1…F4` (Q07, Q08, Q15, Q16)
  закрываются каждая своим коммитом со своими тестами. Статус ✅ ставится только когда закрыты
  все части; до этого — ⏳ с перечислением готового в строке пункта.
- **Что значит S/M/L.** S — один коммит в одной подсистеме. M — 2–4 коммита. L — 5+ коммитов
  или несколько подсистем: такой пункт перед стартом разбивается на подпункты прямо здесь.
  Если пункт на деле больше оценки — не растягивать коммит, а разбить (`Q01a`, `Q01b`) и сказать
  владельцу.
- **След закрытия.** Принятый пункт из плана не удаляется: статус ✅ + строка
  `Принято: <дата> · коммит <hash> · тесты <имена> — зелёные`. Это единственная защита от
  «работа пропала» (AGENTS.md §6) и от переделки уже принятого.
- **Миграция схемы/скоупа — сначала бэкап** (AGENTS.md §3):
  `sqlite3 data/bot.db "PRAGMA wal_checkpoint(TRUNCATE);" && cp data/bot.db data/backups/pre-<пункт>-<дата>.db`
  (только чтение, БД не меняет). Сама миграция — через `<фича>.ensure_schema()`/`init_db()`,
  legacy-строки помечаем, не удаляем.
- **Проверить, кто ещё зовёт функцию, прежде чем вырезать раздел.** В этом проекте три JS-файла
  «Мозга» содержат обще-панельные символы — конкретные мины перечислены в Q17 и Q19.

## Итог одним взглядом (на 14.09.2026)

Готово: панель целиком (боты/каналы, виджеты, Режиссёр, Мозг-база запреток, bugfix-пакет
12.09), модераторский сайт MOD-00…23, живая приёмка Режиссёра на машине владельца 11–12.09
(replay, реальные источники, Twitch send).

**Вся инженерная очередь Q01–Q34 закрыта** (последними: Q29 `ac06a56`, Q30 `fbc7d2d`,
Q32 `620c525`, Q31 `68ac666`, Q34a–c `fe710ce`/`aba0bc4`/`c2bb258`). Остались только
живые проверки — ⏸ агент не исполняет:

1. **⏸ Живые проверки владельца:** Q01 (модерация — после переавторизации токенов),
   Q07б (пассивная проверка ботов), Q12/Q27 (browser-проверка карточек/хоткеев — по
   необходимости), Q13 (реактивный блюр в browser/OBS), Q29–Q30 (статус AI и ревью
   live-реакций в панели на живом канале), **Q34** (создать/применить пачку, проверить
   разброс входов и «Свернуть»), DIR-LIVE-10 (OBS/CEF + TTS/audio), MOD-24 (приёмка
   модераторского сайта), DEF-06-рантайм.
2. **⏸ Переавторизация токенов** — блокирует часть живых проверок выше.
3. **DEF-01** ✅ закрыт 13.09 (аудио-цикл Whisper вынесен в отдельный проект, `81808f3`).
4. **✅ Q40** (владелец, 26.09) — страница Режиссёра с вкладками каналов, дизайны
   Пульт/Кокпит, режим «ИИ / Ручной» per канал. ⏸ Живая проверка отправки с подключённым ботом.
5. **⏳ Q41** — общий редизайн панели в стиле «Пульт» (Q41a общий слой готов).

**Состояние на 14.09:** закрыты всё из интервью 13.09 — Q29 (DEF-04), Q30 (CAND-01),
Q31 (OPTIONAL-05), Q32 (OPTIONAL-10), а также Q27/Q28 (биндинги v2 и дизайн, `DEC-OWNER-017`)
и Q12/Q13 (инженерные части). Единственные ⏳-пункты (Q01, Q07, Q12, Q13, Q27) ждут только
живых проверок владельца — инженерных остатков в очереди нет. Перед стартом перечитать файл
с диска и `git log --oneline -10`.

### Рекомендуемый порядок очереди

1. **Блок модерации:** Q01 → Q02 → Q03 → Q04 (строгая цепочка зависимостей) → **Q26**
   (журнал наказаний, очередь подтверждения, список защищённых — растёт из Q01).
2. **Взятые дефекты (`DEC-OWNER-013`):** DEF-06 (UA-строки) → DEF-02 (лог ошибок провайдера)
   → DEF-03 (`test_connection` для `custom:*`).
3. **Мелкие без зависимостей, в любой момент:** Q06, Q14, Q24.
4. **Q05 (инвентаризация настроек)** — ✅ закрыта 13.09: вердикты подтверждены владельцем
   (`DEC-OWNER-016`, строка 11 изменена — «общая/своя» vision); открываются Q09, Q10, Q15,
   Q16, Q18; когда все три донора (Q09, Q17, Q18) закрыты — Q19. Q17 уже закрыт —
   осталось Q09 и Q18.
5. **Q08** открывает Q20, Q21, Q22, Q23.
6. **Остальные по зависимостям:** Q07, Q12, Q13, Q25. **Биндинги v2:** ✅ Q27 — инженерная
   часть готова 14.09 (живая проверка ⏸); далее **Q28** (решения владельца —
   `DEC-OWNER-017`; Q27 заменяет UI-часть закрытого Q11).
   **Новые из интервью 13.09 (по каждому отложенному):** после Q13 — Q29 (DEF-04),
   Q30 (CAND-01), Q32 (экспорт/импорт базы Режиссёра), Q31 (полиш панели) —
   ✅ все четыре закрыты 14.09 (`ac06a56`/`fbc7d2d`/`620c525`/`68ac666`).
7. **В самом конце:** DEF-01 (аудио-цикл Whisper — отдельный проект, `DEC-OWNER-013`) — ✅
   закрыт 13.09 (коммит `81808f3`, след закрытия — в реестре дефектов DIRECTOR-LIVE).

---

# Очередь Q01–Q33

Формат каждого пункта: **что делаем** (суть одним предложением) · **готово когда** (что увидит
владелец) · **агенту** (файлы · тесты · миграция · зависимости). Карта модулей —
[FILE_ZONES.md](FILE_ZONES.md). Архитектурный принцип — `DEC-OWNER-002`: у каждого бота своё,
у каждого канала своё, ничего не пересекается; исключения помечены явно.

### ⏸ Q01 · Расширенные действия правил модерации · M (инженерно готово; живая проверка ⏸)

- **Принято (инженерная часть): 13.09 · коммиты `bd3b036`, `e100366`, `8b8bd1b`, `d5ae1a3`,
  `3abf078` · тесты `tests/test_moderation_action_ext.py` (83), `tests/test_moderation.py`,
  `tests/test_moderation_category_policy.py`, `tests/test_moderation_base_rules.py`,
  `tests/moderation_rules_ui.test.js` — зелёные. Осталась только живая проверка «бан 1 день
  реально банит» после переавторизации токенов владельцем (`DEC-OPS-001`, см. «Ждём владельца»).**

- **Что делаем:** у правила выбирается конкретное действие — «по тяжести / маскировать /
  блокировать / таймаут 10 мин / 1 час / 1 день / 1 неделя / 2 недели (1209600 с) / бан
  навсегда»; движок применяет его. Сейчас в `app/twitch_helix.py` есть только `timeout_user`
  (POST `/moderation/bans` с `duration`) — нужен `ban_user`.
  **Поправка 13.09:** в прежней редакции пункта бан описан как «через DELETE» — это неверно:
  `DELETE /moderation/bans` у Helix — это «Unban User», он **разбанивает**. Бан навсегда = тот же
  `POST /moderation/bans`, но без поля `duration` в `data` (контракт — ниже).
- **Готово когда:** владелец ставит правилу «бан 1 день» — бот реально банит через Twitch.
- **⚠️ Предусловие, найденное 13.09 (без него пункт не закроется вживую):** скоупа
  `moderator:manage:banned_users` нет в `DEFAULT_SCOPES` (`app/twitch_oauth.py:26`) и вообще нет
  в репозитории, а именно он нужен для бана/таймаута. Значит текущие токены ботов его не имеют
  и любой бан/таймаут вернёт 401/403. Порядок работ: (1) добавить скоуп в `DEFAULT_SCOPES`,
  (2) показать в панели у бота честный статус «нет скоупа для модерации» (по образцу
  `app/stream_tools_routes.py:43` и `app/stream_intents.py:27`), (3) живая переавторизация
  токенов — это уже шаг владельца (`DEC-OPS-001`). Заодно поправить docstring `timeout_user`
  (`app/twitch_helix.py:263`): он называет не тот скоуп (`moderator:manage:chat_settings`).
- **Контракт Helix «Ban User»** (сверено с `dev.twitch.tv/docs/api/reference` 13.09):
  `broadcaster_id` и `moderator_id` — **query**-параметры, в теле `data` только `user_id`,
  `duration`, `reason` (≤500 символов, иначе 400). Нет `duration` → бан навсегда (в ответе
  `end_time: null`); есть → таймаут, минимум 1 с, максимум 1209600 с. Движок обязан обрабатывать
  коды: **400** «user is already banned» (таймаут можно перевести в бан, наоборот — только через
  unban), **401** (`moderator_id` ≠ владелец токена), **403** (`moderator_id` не модератор канала),
  **409** (конфликт смены ban-состояния — доки прямо велят повторить запрос), **429** (лимит
  на канал в минуту). Альтернатива user-токену — app access token, но тогда нужны оба скоупа:
  `moderator:manage:banned_users` **и** `user:bot`.
- **Контракт наказания (`DEC-OWNER-014`, решение владельца 13.09):**
  - «бан навсегда» **никогда** не применяется к (1) модераторам и редакторам канала — защита
    автоматическая, независимо от списков, и (2) зрителям из ручного **списка защищённых**
    этого канала (per-канал, свой у каждого; общего списка нет).
  - Защита действует **только** против вечного бана: таймауты любой длины (1 день, 2 недели)
    применяются к защищённым как настроено, без подтверждения.
  - Если правило с «баном навсегда» сработало на защищённом — наказание **не применяется
    вообще**, случай уходит в **очередь подтверждения**. Пока решения нет, сообщение **не
    удаляется, не маскируется, таймаут не даётся** (осознанный выбор владельца). Движок обязан
    при этом записать случай в журнал: кто, когда, какое правило, почему не применено.
  - Нерешённый случай закрывается сам через **30 дней** с пометкой «не подтверждено, закрыт по
    сроку»; запись в журнале остаётся.
  - Сам журнал, очередь подтверждения, список защищённых и кнопка «Разбанить» — это **Q26**,
    а не Q01. Q01 отвечает за выбор действия в правиле, движок применения и Helix-контракт.
- **Агенту:** `app/moderation.py`, `app/routes_modpanel.py`, `app/database.py` (колонка
  `action_ext` в `moderation_rules`, CREATE TABLE — строка 594), `app/twitch_helix.py`
  (`timeout_user` — строка 252; `ban_user` — тот же POST без `duration`; скоуп — см.
  предусловие выше), `app/twitch_oauth.py` (`DEFAULT_SCOPES`, строка 26),
  `static/app/08_providers_moderation.js`
  · тесты `tests/test_moderation.py`, `tests/test_twitch_oauth.py` + новый
  `tests/test_moderation_action_ext.py` (parse action_ext, все таймауты, ban через Helix-мок,
  скоуп `moderator:manage:banned_users` в `DEFAULT_SCOPES`) · миграция: `action_ext` с default NULL,
  NULL = прежняя лестница warn→t1→t2→ban, существующие правила не переписываются;
  **бэкап `data/bot.db` до добавления колонки** (см. «Как вести пункт») · зависит: —.
- **Ход работ — шаг A+B готов (13.09, коммит `bd3b036`):** скоуп `moderator:manage:banned_users`
  добавлен в `DEFAULT_SCOPES`; в `app/twitch_helix.py` появились `ban_user` (POST без `duration`),
  `unban_user` (DELETE, 204 = успех, 400 «not banned» = `user_not_banned`) и общие
  `_post_ban`/`_resolve_ban_ids`; границы `duration` 1…1209600 проверяются локально, без запроса
  к Twitch; docstring `timeout_user` исправлен на верный скоуп. Константы `BAN_SCOPE`,
  `BAN_MIN_DURATION`, `BAN_MAX_DURATION`.
- **Ход работ — шаг C готов (13.09, коммит `e100366`):** колонка `moderation_rules.action_ext`
  (миграция `_add_column_if_missing` в `app/database.py`, NULL = прежнее поведение, существующие
  правила не переписаны); в `app/moderation.py` — `ACTION_EXT_TIMEOUTS`, `ACTION_EXT_CHOICES`,
  `parse_action_ext()`, `resolve_rule_action()`, у `Verdict` поля `action_ext`/`duration_sec`,
  `_apply_mode_policy()` понимает `ban` (без `can_timeout` деградирует в `block`, в `log_only` —
  в `log`), `check_message()` и `check_outgoing()` применяют явное действие; API
  (`app/routes_modpanel.py`) валидирует `action_ext` в create/update/import и отдаёт его в списке
  правил. Бэкап БД сделан: `data/backups/pre-Q01-action_ext-2026-09-13.db`.
  Тесты: `tests/test_moderation_action_ext.py` — 66 зелёных; смежные (`test_moderation`,
  `test_eventsub_chat_subscription`, `test_s5_db_isolation`) — 117 зелёных.
- **Ход работ — шаг C2 НАЧАТ, остановлен на константах (13.09, коммит `8b8bd1b`).**
  В `app/moderation.py` уже есть: `DEFAULT_TIMEOUT_SEC = 600`, `PUNISH_ACTIONS = ("timeout","ban")`,
  `PROTECTED_ROLES` (streamer/broadcaster/mod/moderator/editor/staff/admin — **без** vip и
  subscriber: они защищены только если владелец вписал их руками), статусы `PUNISH_APPLIED` /
  `PUNISH_DEFERRED` / `PUNISH_SKIPPED`. **Поведение движка пока не изменилось** — константы никто
  не использует, все тесты зелёные.
  **Точка возобновления C2 (сделать ровно это, порядок такой):**
  1. `_ensure_extra_schema()`: добавить в `moderation_pending` колонки `requested_action TEXT
     DEFAULT 'timeout'`, `duration_sec INTEGER DEFAULT 600`, `role TEXT DEFAULT ''` (через
     `ALTER TABLE ... ADD COLUMN` в try/except, как там уже сделано для `accounts.timeout_policy`);
     создать таблицу `moderation_protected (id, account_id, channel, username, note, created_at,
     UNIQUE(account_id, channel, username))` + индекс `(account_id, channel)`.
  2. Функции списка защищённых: `list_protected`, `add_protected`, `remove_protected`,
     `is_protected(account_id, channel, username, role)` — роль из `PROTECTED_ROLES` ИЛИ строка
     в `moderation_protected` (сравнение в нижнем регистре, channel нормализован: lower + без `#`).
  3. `_execute_helix_punishment(...)`: `action == "ban"` → `twitch_helix.ban_user`, иначе →
     `timeout_user` с `duration_sec` **из вердикта** (сейчас `_execute_helix_timeout` жёстко
     шлёт 600 с — это надо заменить, иначе выбранный в UI «таймаут 1 день» выполнится как
     10 минут).
  4. `create_pending_timeout(..., requested_action="timeout", duration_sec=600, role="")` —
     расширить сигнатуру дефолтами, старые вызовы не ломаются.
  5. Новая `maybe_punish(account_id, channel, username, verdict, token, bot_nickname, role)` →
     возвращает строку-статус (`applied`/`deferred`/`skipped`): если `action == "ban"` и
     `is_protected(...)` → **наказание не применяется вообще**, случай пишется в
     `moderation_pending` с `requested_action='ban'` + запись в `log_event` (source
     `punishment_recommend`), возвращается `deferred`. `maybe_timeout` оставить как есть
     (её зовут существующие тесты) — пусть делегирует в `maybe_punish`.
  6. `record_timeout_decision()`: выполнять **запрошенное** действие из строки очереди
     (`requested_action`, `duration_sec`), а не всегда таймаут 600 с.
  7. `app/chat_analyzer.py:1320-1332` — единственный боевой вызов: условие `any(v.action in
     ("block","timeout"))` расширить на `"ban"`, вместо `maybe_timeout` звать `maybe_punish` и
     передавать `role` (он уже есть в этой области видимости, строка 1286-1288).
- **⚠️ Открытый вопрос C2 (нужен ответ владельца, см. «Решения владельца»):** когда «бан
  навсегда» отложен в очередь (защищённый зритель), бот сейчас **не отвечает** на это сообщение —
  так работает ветка `block/timeout` в `chat_analyzer.py`. Варианты: (а) оставить как есть —
  наказания нет, но и ответа бота нет; (б) позволить боту ответить как на обычное сообщение.
  Ваше «ничего не делать до решения» было про наказание и про сообщение в чате, а не про ответ
  бота — поэтому без подтверждения выбираю (а) и помечаю это место в коде.
- **Ход работ — шаг C2 готов (13.09, коммит см. `git log`).** В `app/moderation.py`:
  `moderation_pending` получил колонки `requested_action`/`duration_sec`/`role` (ленивая миграция
  ALTER TABLE), создана таблица `moderation_protected` (UNIQUE(account_id, channel, username)) +
  индекс; функции `list_protected`/`add_protected`/`remove_protected`/`is_protected`
  (роль из `PROTECTED_ROLES` ИЛИ ручной список, сравнение в нижнем регистре, канал нормализован);
  `_execute_helix_punishment()` — ban через `twitch_helix.ban_user`, таймаут с `duration_sec`
  из вердикта (жёсткий 600 заменён), `_execute_helix_timeout` оставлен как обёртка;
  `create_pending_timeout(..., requested_action, duration_sec, role)` — расширен с дефолтами;
  `maybe_punish()` возвращает `applied`/`deferred`/`skipped`, предохранитель «бана навсегда»
  срабатывает до политики: защищённый (роль ИЛИ список) → наказание не применяется вообще,
  случай в `moderation_pending` с `requested_action='ban'` + запись в журнал (source
  `punishment_recommend`); `record_timeout_decision()` исполняет запрошенное действие из строки
  очереди; `maybe_timeout` делегирует в `maybe_punish`. В `app/chat_analyzer.py` — условие
  расширено на `ban`, зовётся `maybe_punish` с `role` (шаг 7); место открытого вопроса Q01-C2
  помечено комментарием (вариант (а) по умолчанию). В `app/database.py` — CHECK `source`
  `moderation_events` расширен значениями `timeout_recommend`/`punishment_recommend`
  (миграция перестройкой по образцу `_migrate_bot_logs_fallback_category`; найдено: старый CHECK
  молча резал записи рекомендаций). Бэкап БД: `data/backups/pre-Q01-C2-2026-09-13.db`.
  Тесты: `tests/test_moderation_action_ext.py` — 83 зелёных (17 новых C2); смежные
  (`test_moderation`, `test_eventsub_chat_subscription`, `test_s5_db_isolation`,
  `test_p7_f4_fixes`, `test_qa_profile`, `test_chat_noise`) — зелёные.
- **Ход работ — шаг D готов (13.09, коммит см. `git log`).** В `templates/partials/bots.html`
  в форме правила появился селект «Наказание (явное)» — 9 опций, значения ровно ключи
  `ACTION_EXT_CHOICES`; в `static/app/08_providers_moderation.js` — константа
  `MOD_RULE_ACTION_EXT` + `initModerationRuleForm()` (заполняет селект, если пуст),
  `addModerationRule`/`importModerationRules` отправляют `action_ext`, список правил показывает
  выбранное действие бейджем. i18n RU/EN/UA — точечно в `static/app/21_panel_labels.js`
  (ключи `panel.mod.action_ext`, `panel.mod.ext_*`; фактическое место словарей — этот файл,
  а не app.js, как было в старой формулировке шага). Инженерная часть Q01 готова:
  живая проверка «бан 1 день реально банит» — после переавторизации токенов
  (`DEC-OPS-001`, см. «Ждём владельца» → Q01-скоуп). jsdom-тест редактора — Q04.
- **Находка для Q26 (13.09):** в `app/moderation.py` **уже есть** очередь подтверждения —
  `timeout_policy` (auto/ask/learn), `maybe_timeout`, `list_pending_timeouts`,
  `record_timeout_decision`, таблица `moderation_pending` со статусами
  pending/approved/rejected/executed. Очередь для «бана навсегда» строится на ней (шаг C2 выше),
  а не параллельно. Роуты очереди — `app/moderation_routes.py:30,53,75`.

### ✅ Q02 · Политика по категориям в роли «модератор» · M

- **Что делаем:** в настройках роли «модератор» — таблица «категория → действие»
  (insult/hate/threat/sexual/spam), применяется в `check_message` поверх severity.
- **Готово когда:** владелец сам правит таблицу в настройках роли, и она реально работает.
- **Агенту:** `app/moderation.py`, `app/bot_roles.py`, `app/database.py` (`category_policy`),
  `static/app/08_providers_moderation.js`, `static/app/06_roles.js` · тесты `tests/test_moderation.py`,
  `tests/test_bot_roles.py`, `tests/test_roles_style.py`, `tests/test_p8_c8_roles_2_0.py` ·
  миграция: `category_policy` в настройках роли; нет значения — поведение как сейчас.
  **Уточнение 13.09:** конфиг роли лежит JSON-блобом в `accounts.role_config_json`
  (`app/bot_roles.py:191`), т.е. схема БД не меняется и бэкап не обязателен; но у блока есть
  жёсткий лимит 32 КБ (`app/bot_roles.py:152`) — таблица «категория → действие» должна в него
  влезать, а owning-тест обязан покрыть случай «конфиг упёрся в лимит» · зависит: Q01.
- **Принято: 13.09 · коммиты `d5ae1a3` (движок-основа Q01), Q02-коммит см. `git log` ·
  тесты `tests/test_moderation_category_policy.py` (10), `tests/test_bot_roles.py` (+6,
  включая owning-тест 32 КБ-лимита), смежные `test_moderation`, `test_moderation_action_ext`,
  `test_roles_style`, `test_p8_c8_roles_2_0` — зелёные.**
  Реализация: в `app/bot_roles.py` — дефолт `category_policy: {}` в конфиге модератора,
  whitelist-ключи `insult/hate/threat/sexual/spam`, значения нормализуются в канонические
  ключи `ACTION_EXT_CHOICES` через `normalize_action_ext` (мусор → `''` = лестница), чужие
  категории отбрасываются; для не-модераторских ролей ключ отбрасывается. В
  `app/moderation.py` — `get_category_policy()` (TTL-кэш, читает `role_config_json`) и
  применение поверх severity в `check_message` для кастомных правил и встроенных словарей;
  приоритет: явный `action_ext` правила > политика роли > лестница; режимы деградируют
  как обычно. В `static/app/06_roles.js` — таблица из 5 селектов в форме роли модератора
  (новый тип поля `catpolicy`), пустое значение не сохраняется; i18n RU/EN/UA.
  Схема БД не менялась (JSON-блоб), отдельный бэкап не требовался.

### ✅ Q03 · База правил модерации: per-канал + пресет Twitch · M

- **Что делаем:** у канала — свой редактируемый список правил; есть базовый пресет запретов
  Twitch, из которого канал стартует; правила применяются **только** ботам с ролью
  «модератор»; порядок: пресет/база канала, затем per-бот правила.
- **Готово когда:** канал со свежим пресетом наказывает по нему, а не-модератор бот — нет.
- **Агенту:** `app/moderation.py`, `app/moderation_routes.py`, `app/moderation_dicts/`,
  `app/database.py`, `static/app/08_providers_moderation.js`, `templates/partials/channels.html` ·
  тесты: новый `tests/test_moderation_base_rules.py` (пресет только модераторам, per-бот
  переопределяет базу, не-модератор не наказывает) · миграция: глобальной таблицы
  `moderation_base_rules` **не создавать** — модель per-канал + пресет по `DEC-OWNER-004` ·
  зависит: Q01, Q02, `DEC-OWNER-004`.
- **Принято: 13.09 · коммит см. `git log` · тесты `tests/test_moderation_base_rules.py` (10) —
  зелёные; смежные `test_moderation*`, `test_bot_roles`, `test_qa_profile`, `test_s5_db_isolation`,
  `test_eventsub_chat_subscription` (192 суммарно) — зелёные.**
  Реализация: новая per-канальная таблица `moderation_channel_rules` UNIQUE(channel, pattern)
  (не глобальная, `DEC-OWNER-004` соблюдён); DDL модерации собран в один источник
  `database.ensure_moderation_schema()` (зовут `init_db` и ленивая `_ensure_extra_schema` —
  guard-тест `test_s5_db_isolation` запрещает CREATE-дубли между файлами); пресет
  `app/moderation_dicts/preset_twitch.json` + идемпотентный засев `POST
  /api/moderation/base-rules/seed`; CRUD-эндпоинты `/api/moderation/base-rules…` и
  `GET /api/moderation/twitch-preset` в `routes_modpanel.py`; движок применяет базу в
  `check_message` только ботам с ролью «модератор» (`get_bot_role`), база идёт перед per-бот
  правилами, per-бот правило с тем же паттерном переопределяет базу (дубли из базы убираются);
  UI — модалка «База правил» в карточке канала (`channels.html` + JS в
  `08_providers_moderation.js`, кнопка в `19_channels_bulk.js`), i18n RU/EN/UA в `app.js`.
  Бэкап БД: `data/backups/pre-Q03-2026-09-13.db`.

### ✅ Q04 · Сквозной UI-тест редактора модерации · S

- **Что делаем:** jsdom-тест открывает редактор правил и категорий и проверяет parse
  `action_ext`, category override, применение базы только модераторам, ban через Helix-мок.
- **Готово когда:** `node tests/moderation_rules_ui.test.js` зелёный.
- **Агенту:** новый `tests/moderation_rules_ui.test.js`, `static/app/08_providers_moderation.js` ·
  тесты: он же + тесты Q01–Q03 · миграция: нет · зависит: Q01–Q03.
- **Принято: 13.09 · коммит см. `git log` · тесты `tests/moderation_rules_ui.test.js` (9) —
  зелёные; тесты Q01–Q03 повторно прогнаны — зелёные.**
  Разделение труда: UI-часть (паритет ключей `action_ext` UI ↔ `ACTION_EXT_CHOICES` бэкенда,
  селекты шаблонов, инициализация, отправка `action_ext` в add/import, бейдж действия,
  модалка базы правил канала, catpolicy-таблица роли) — в node-тесте; движковая часть
  (parse action_ext, category override, база только модераторам, ban через Helix-мок) —
  в Python-сьютов Q01–Q03 (`test_moderation_action_ext`, `test_moderation_category_policy`,
  `test_moderation_base_rules`), node-тест проверяет их наличие и якорные тесты.

### ✅ Q05 · Инвентаризация глобальных настроек · M

- **Принято: 13.09 · решение владельца `DEC-OWNER-016` (docs/DECISIONS.md, диалог).**
  Вердикты таблицы ниже подтверждены с правками: строка 11 изменена — общая vision-модель
  **остаётся** в Настройках как базовая, у бота выбор «общая (по умолчанию) / своя»; строка 12
  (smart-routing) и строка 16 (replay_auto_record) — **к боту**; живые проверки отложены
  владельцем («позже»). Открыты Q09 → Q10 → Q18 → Q19 и Q15, Q16, далее Q11, Q12, Q13.

- **Что делаем:** составить таблицу «настройка → где хранится → вердикт (удалить / к боту /
  к каналу / остаётся глобальной по исключению)» для всего, что лежит в `settings`
  (`get_setting`/`set_setting`), и показать владельцу.
- **Готово когда:** таблица в этом плане, владелец подтвердил вердикты, а Q09/Q10/Q15/Q16/Q18
  на неё ссылаются.
- **Агенту:** `PLAN_TODO.md` (таблица), `app/database.py`, `templates/partials/settings.html`,
  `static/app/04_chat_settings.js`, `static/app/12_dashboard_extras.js` · тесты
  `tests/test_provider_settings_api.py`, `tests/test_p1_custom_providers.py`; ссылки проверить
  `python3 scripts/check_md_links.py` · миграция: на этом этапе нет, переносят пункты-исполнители ·
  зависит: `DEC-OWNER-002`.
- **Ход работ — агентская часть готова (13.09, коммит см. `git log`).** Состав источника:
  все вызовы `get_setting`/`set_setting`/`get_setting_bool` по `app/` + прямые
  `SELECT … FROM settings` + фактические ключи в рабочей БД (read-only SELECT). Динамические
  семейства (`ai_*`, `widget_design_*`, `chat_overlay_display_*`) показаны одним пунктом.
  **Вердикты — предложения агента; владелец подтверждает/правит, до подтверждения ничего не
  переносится.**

  | # | Ключ (семейство) | Что это · где живёт | Вердикт (предложение) |
  |---|---|---|---|
  | 1 | `twitch_client_id`, `twitch_client_secret` | Helix-креды панели (`twitch_credentials.py`) | остаётся глобальной — инфраструктура, одна пара на панель |
  | 2 | `offline_mode` | офлайн-режим (`server.py:865`, `bootstrap.py:137`) | остаётся глобальной — инфраструктура |
  | 3 | `autoconnect` | автозапуск ботов при старте панели (`routes.py:2494`) | остаётся глобальной — запуск панели |
  | 4 | `auto_refresh_tokens` | авто-обновление токенов (`DEC-OAUTH-001`, `server.py:229`) | остаётся глобальной — уже решено `DEC-OAUTH-001` |
  | 5 | `token_expiry_warning_days` | порог значка «истекает» (`DEC-OAUTH-003`) | остаётся глобальной — уже решено `DEC-OAUTH-003` |
  | 6 | `huggingface_token` | HF-токен ML (`stream_vision.py`, `routes.py:981`) | остаётся глобальной — ML opt-in, одна учётка |
  | 7 | `onboarding_completed`, `onboarding_dismissed` | онбординг панели (`routes_user_history.py`) | остаётся глобальной — UI-состояние владельца (искл. 1 `DEC-OWNER-002`) |
  | 8 | `media_share_youtube_disclosure_acknowledged` | согласие на дисклеймер YouTube (`media_share_routes.py`) | остаётся глобальной — уже решено `DEC-MEDIA-001` |
  | 9 | `shared_facts_migrated_to_per_bot` | технический маркер миграции (`shared_user_facts.py`) | остаётся (маркер, не настройка) |
  | 10 | `ai_provider`, `ai_<провайдер>_{key,chat,vision,base,host}` | провайдеры/модели/ключи (`routes.py:1365`, читается `LIKE 'ai_%'`) | **к боту (Q15)**: провайдер и модели per-бот; глобальные `ai_*` — источник переноса, после — legacy |
  | 11 | `global_vision_override` (в памяти `ai_service` + `globalVisionModel` в Настройках) | глобальная vision-модель | **удалить (Q15 E1)**: поле из Настроек убрать, у бота — своя vision-модель |
  | 12 | `ai_smart_routing_*` (6 ключей) | smart-routing чат-моделей | **к боту** — роутинг per-бот (⚠️ нет прямого Q-пункта; владелец решает) |
  | 13 | `tts_elevenlabs_api_key` (+`elevenlabs_api_key`), `tts_clone_engine`, `tts_xtts_model`, `tts_xtts_device` | TTS-провайдер и движок (`tts_engine.py`, `routes_tts_duck.py`, `routes_tts_config.py`) | **к боту (Q16 F3)**: TTS полностью per-бот; глобальные значения — fallback до переноса, затем legacy |
  | 14 | `provocations_master_enabled` | главный рубильник провокаций (`chat_analyzer.py:1941`) | **удалить (Q16 F1)**: вкл/выкл только у бота во вкладке «Характер» |
  | 15 | `beep_pipeline` | beep-конвейер (`beep_pipeline.py:81`) | **к боту-модератору (Q25, `DEC-OWNER-005`)** |
  | 16 | `replay_auto_record` | автозапись replay-сессий (`bot_manager.py:160`) | **к боту** — запись его сессий (⚠️ владелец решает) |
  | 17 | `clip_threshold_multiplier`, `clip_window_sec`, `clip_cooldown_sec` | пороги клип-моментов; уже per-bot override + глобальный fallback (`routes_clip.py`) | **к боту**: убрать глобальный fallback и глобальный слой из UI |
  | 18 | `engagement_window_sec`, `engagement_breakthrough_min` | пороги вовлечённости (`engagement.py`) | **к боту** — поведение бота |
  | 19 | `prompt_base` | общая база запреток «Мозга» (`routes_prompt_base.py`, `chat_prompt_blocks.py`) | **в пресет (Q18, `DEC-OWNER-004`)**: текущий текст становится стартовым содержимым пресета Twitch, глобальный редактор убирается |
  | 20 | `chat_overlay_trusted_users` | доверенные логины чат-оверлея (`chat_overlay_routes.py`) | **к каналу** — оверлей channel-scoped (`DEC-BUS-001`); уточняет Q10 |
  | 21 | `chat_overlay_display_<slug>` | display-настройки по виджетам | остаётся per-виджет; финальный скоуп канала — Q10 |
  | 22 | `widget_design_<widget>` | дизайн-настройки по виджетам (`widgets.py:5018`) | остаётся per-виджет; финальный скоуп канала — Q10 |

  Ключи, которых нет в БД, но которые видит Настройки: `globalVisionModel` (шаблон строка 24),
  рубильники Q16 (провокации 120-122, TTS 136, routing map 179-181, TTS output 262-263),
  модалка media-share (`12_dashboard_extras.js:56-65`) — покрываются строками 11/13/14.
  **После подтверждения вердиктов** открываются Q09, Q10, Q15, Q16, Q18 (см. порядок очереди).

### ✅ Q06 · Убрать блок ручных команд виджетов · S

- **Принято: 13.09 · коммит `032ab95` · тесты `tests/test_w5_manual_controls.py` (tombstone, 4),
  `tests/test_panel_labels.py` (133), `tests/test_widgets_ui_cards.py`,
  `tests/test_o7_widget_admin_forms.py`, `tests/widget_admin_forms_ui.test.js` — зелёные.**
  Карточка «Ручное управление» (Sub-цель/Счётчики/Countdown) удалена вместе с функциями
  waSubDelta/waSubReset/waLoadCounters/waCounterDelta/waCounterReset/waCdAction и i18n-ключами
  (RU/EN/UA); карточки самих виджетов не тронуты; R-ВИД3 в `docs/PRODUCT_RULES.md`
  синхронизирован с решением владельца. Миграции нет (только UI).

- **Что делаем:** удалить блок «Все команды изменения виджетов во время эфира собраны здесь»
  (⭐ Sub-цель / 🔔 Счётчики / ⏳ Countdown) — `templates/partials/widgets.html:20-22`.
- **Готово когда:** блока нет, сами виджеты и их карточки не тронуты.
- **Агенту:** `templates/partials/widgets.html`, `static/app/07_widgets.js`,
  `static/app/21_panel_labels.js`, `static/app/24_dynamic_i18n.js`, `static/app.js` (i18n RU/EN/UA
  точечно) · тесты `tests/test_widgets_ui_cards.py`, `tests/widget_admin_forms_ui.test.js`,
  `tests/test_o7_widget_admin_forms.py`; grep остатков `waSubDelta`/`waCounterManualList`/`waCdAction` ·
  миграция: нет (только UI, данные не трогаются) · зависит: —.

### ⏳ Q07 · Добавление ботов к каналу: проверка без сообщения + диагностика · M (живая часть ⏸)

- **Ход работ — шаг (а) готов (13.09, коммит `8fe7570`):** чекбокс «Отправлять контрольное
  сообщение» в обеих модалках (добавление `bulkChannelsModal` и проверка `botCheckModal`)
  по умолчанию ВЫКЛ, поле блокируется; `run_bot_check(send_message=False)` = OAuth-валидация +
  IRC join + чтение чата без записи в чат (успех только при реальном сообщении за окно,
  `DEC-BULK-007`); флаг проброшен через `bot-checks` и `bulk/channels` роуты. Тесты:
  `tests/test_bot_check.py` (+1 пассивный, send-тесты помечены send_message=True),
  `tests/test_bulk_channels_ui.py` (+1), смежные зелёные.
  **Осталось:** шаг (б) — живой прогон на test_channel (реальный IRC, `DEC-OPS-001`, ⏸).

- **Что делаем:** (а) чекбокс «контрольное сообщение» в диалоге добавления, по умолчанию ВЫКЛ;
  проверка без него = OAuth-валидация токена + IRC join канала; (б) воспроизвести на test_channel
  отказ добавления streamer_lurker/streamer_director, починить и сообщить владельцу, что было сломано.
- **Готово когда:** добавление без контрольного сообщения работает; живой прогон на test_channel
  прошёл.
- **Агенту:** `app/bot_check.py`, `app/bot_check_routes.py`, `app/bulk_channels_routes.py`,
  `static/app/19_channels_bulk.js` · тесты `tests/test_bot_check.py`, `tests/test_bot_check_routes.py`,
  `tests/test_bot_check_ui.py`, `tests/test_bulk_channels.py`, `tests/test_bulk_channels_ui.py` ·
  миграция: нет; дефолт чекбокса ВЫКЛ зафиксирован `DEC-OWNER-011` · зависит: `DEC-OWNER-011`,
  `DEC-BULK-005`, `DEC-BULK-008`; живая часть — разрешение владельца на реальный IRC (`DEC-OPS-001`).

### ✅ Q08 · Фильтры ботов, «выбрать всех» по ролям, массовая смена канала · L

- **Принято: 13.09 · коммиты `3021e16` (а), `e2520ce` (б), `115c15c` (в) · тесты
  `tests/bots_filters_ui.test.js` (7), `tests/panel_lurker_ui.test.js` (tombstone+2),
  `tests/test_bulk_channels.py` (+5), `tests/test_bulk_channels_ui.py` (+2), смежные
  `role_visibility_ui`, `panel_token_status_ui`, `test_bot_roles`, `test_panel_labels` — зелёные.**
  (а) один список без секции «Луркеры» + фильтры роль/канал в localStorage (несуществующий
  канал сбрасывается); (б) в диалоге «канал → добавить ботов» группировка по ролям с «выбрать
  всех»; (в) `POST /api/bulk/change-channel` (replace снимает прежние привязки, не удаляя
  каналы; per-item отчёт changed/added/skipped/errors; job-инфраструктура и аудит как у
  bulk-add; join подключённого бота) + кнопка «🔁 Сменить канал» в bulk-bar с модалом.
  i18n RU/EN/UA; миграция: старых ключей фильтров не было — читаются с дефолтом.

- **Что делаем:** (а) один список ботов без принудительной секции «👀 Луркеры», фильтры по
  роли (болтуны/люркеры/модераторы/режиссёры) и по каналу, запоминаются в localStorage;
  (б) в диалоге добавления боты сгруппированы по ролям с кнопкой «выбрать всех» у группы;
  (в) массовая смена канала для нескольких ботов.
- **Готово когда:** «только модераторов» и «боты на test_channel» — в два клика; массовая смена
  канала работает.
- **Агенту:** `static/app/03_bots.js`, `static/app/05_bots_tabs.js`, `static/app/19_channels_bulk.js`,
  `templates/partials/bots.html`, `app/bulk_channels_routes.py`, `app/bot_roles.py` · тесты
  `tests/test_bot_roles.py`, `tests/role_visibility_ui.test.js`, `tests/panel_lurker_ui.test.js`,
  `tests/test_bulk_channels.py`, `tests/test_bulk_channels_ui.py` · миграция: старые ключи
  localStorage читаются с дефолтом · зависит: `DEC-OWNER-010`, `DEC-OWNER-006`, `DEC-LURKER-001`.

### ✅ Q09 · Карточка канала: инфо о стримере, lore, сводки · L

- **Принято: 13.09 · коммиты `fcc7b2d` (Q09a), `8f2f1f2` (Q09b), `6ab092e` (Q09c), `3cfa6ee`
  (Q09d) · тесты `tests/test_channel_card_profile_ui.py` (6), `tests/test_panel_labels.py`
  (133, переведён на ccp/cp-контролы channels.html), `tests/test_brain_channel_scope.py`,
  `tests/test_summarizer_per_channel.py`, `tests/test_w4_profile_per_channel.py`,
  `tests/test_p2_channel_isolation.py`, `tests/test_ai_summary.py`, node
  `tests/channel_moderation_ui.test.js` — зелёные.** В карточке канала — модалка «Профиль
  канала»: профиль+фото стримера per-channel (переиспользован прежний per-channel API —
  источник данных один, скоуп `*`/`''` из UI не приходит), lore факты per (бот×канал)
  с подтверждением, live-сводки вкл/выкл/язык per-канал с честным статусом
  «override канала / наследуется от бота». Из «Мозга» редакторы убраны (остался браузер
  прогонов — прогон это действие, не редактор); 9 осиротевших i18n-ключей удалены
  (RU/EN/UA). Уточнение скоупа: «период» — форма ручного прогона, осталась в «Мозге».

- **Что делаем:** в карточке канала — редакторы инфо о стримере (bio, игры, стиль,
  любит/не любит), фактов lore и настроек сводок «как прошёл стрим» (вкл/выкл/язык/период);
  эти же редакторы из «Мозга» убираются.
- **Готово когда:** вписанное видно у этого канала, у другого — своё; источник данных один.
- **Агенту:** `templates/partials/channels.html`, `static/app/19_channels_bulk.js`,
  `app/streamer_profile.py`, `app/routes_streamer_profile.py`, `app/routes_global_profile.py`,
  `app/streamer_lore.py`, `app/summarizer.py`, `app/routes_ai_summary.py`,
  `templates/partials/brain.html`, `static/app/09_brain_p3.js`, `static/app/11_brain_v16.js` ·
  тесты `tests/test_brain_channel_scope.py`, `tests/test_ai_summary.py`,
  `tests/test_channel_admin.py`, новый `tests/test_channel_card_profile_ui.py` · миграция:
  данные уже per-channel (`streamer_profile`, `streamer_lore`, `summarizer`); скоуп `*`/`''`
  из UI убирается, но строки читаются как fallback и не удаляются · зависит: Q05 ✅
  (`DEC-OWNER-002`).
- **Разбивка при старте (13.09):** **Q09a** — модалка «Профиль канала» (каркас + бот-селектор
  по образцу `channelModerationModal` Q26) и редактор «Инфо о стримере» на существующем
  per-channel API `/api/streamer-profile?channel=#…` — переиспользуются префиксные функции
  `loadGlobalStreamerProfile('ccp')`/`save…`/`upload…` (источник данных один); кнопка в
  карточке канала; тест `tests/test_channel_card_profile_ui.py`. **Q09b** — секция «Lore»:
  список/добавление/подтверждение/удаление фактов per (бот×канал) через существующий
  `/api/accounts/{acc}/lore`; функции пишутся в `19_channels_bulk.js` — общие brain-файлы
  (мина Q17) не трогаем. **Q09c** — секция «Сводки»: live вкл/выкл/язык per-канал
  (override через `/api/accounts/{acc}/summarizer/settings`) с честным статусом
  «override канала / наследуется от бота»; **уточнение скоупа:** «период» — это период
  ручного прогона (datetime-форма), она остаётся браузером прогонов в «Мозге» — прогоны
  это действие, а не редактор данных. **Q09d** — из «Мозга» убираются карточки «Lore» и
  «Профиль стримера» и блок live-настроек сводок; функции JS не удаляются (зовутся из
  новой модалки), `loadBrainAll` чистится от их загрузки; следы закрытия всех подпунктов.

### ✅ Q10 · Channel-first скоуп виджетов, `widget_scope_required` невидима · L

- **Принято: 13.09 · коммиты `17248a6` (Q10a), `685cce1` (Q10b), `515f32c` (Q10c) · тесты
  `tests/test_q10_widget_channel_scope_ui.py` (4), `tests/test_widget_binding_scope_ui.py`
  (устаревшее ожидание counters снято — контролы удалены в Q06/R-ВИД3),
  `tests/test_widget_channel_scope.py`, `tests/test_widget_public_smoke.py`,
  `tests/test_p0_widget_migrations.py`, node `tests/widget_scope_override.test.js` (8) —
  зелёные.** В шапке «Виджетов» один селектор канала (`waChannelScope`, данные из
  `/api/channel-overview`, account_id — первый подключённый бот канала), выбор в localStorage
  `widgetChannelScope`; определена `waBindingScope()` (раньше не существовала); per-widget
  override сильнее. Без канала — демо: GET не дёргает сеть, превью и OBS-URL получают
  `?preview=1`, копирование даёт публичный URL, записи честно просят выбрать канал;
  `widget_scope_required` нигде не показывается (owning-тест: ровно один внутренний throw,
  все вызовы за demo-фоллбеками). Бэкенд-точки 400 остаются контрактом API, из UI
  недостижимы; демо-контент списков — честные пустые состояния.

- **Что делаем:** в «Виджетах» сверху один селектор канала; всё ниже (превью, настройки,
  OBS-URL) показывает данные этого канала; без канала — демо-данные, а не ошибка; строка
  `widget_scope_required` нигде не показывается пользователю.
- **Готово когда:** открыл Виджеты → выбрал канал → всё про него; без канала — демо.
- **Агенту:** `static/app/07_widgets.js` (`waWidgetStateUrl`, ~строка 65 — бросает исключение,
  которое тостится), `static/app/13_widgets_session.js`, `templates/partials/widgets.html`,
  `app/widget_channel_scope.py`, `app/widgets.py` (1907, 5934), `app/soundboard_routes.py` (41),
  `app/soundboard_library.py` (295, 325) · тесты `tests/test_widget_channel_scope.py`,
  `tests/test_widget_binding_scope_ui.py`, `tests/widget_scope_override.test.js`,
  `tests/test_widget_preview_coverage.py`, `tests/test_p0_widget_migrations.py`,
  `tests/test_widget_public_smoke.py` · миграция: per (бот × канал) настройки в БД остаются
  основой; localStorage-override читается как раньше; демо-режим в БД не пишет ·
  зависит: Q05 ✅, `DEC-OWNER-002`.
- **Разбивка при старте (13.09, разведка):** `waBindingScope()` сейчас **не определена** —
  действуют только per-widget localStorage-override, при их отсутствии
  `waWidgetStateUrl` бросает `widget_scope_required` (07_widgets.js:65), и он тостится
  через `_waHint`. **Q10a** — channel-first скоуп: селектор канала `waChannelScope` в шапке
  «Виджетов» (данные из `/api/channel-overview`), выбор хранится в localStorage
  `widgetChannelScope` как `account_id:channel` (account_id — первый подключённый бот
  канала); определяется `waBindingScope()`; per-widget override сильнее селектора; смена
  канала перезагружает admin-формы и скоуп-превью. **Q10b** — демо без канала: state-запросы
  не дёргаются, превью получают `?preview=1` (middleware уже пропускает preview),
  `widget_scope_required` не показывается; бэкенд: точки 400 (widgets.py 5934/5952/5977/
  5990/6809/6816, soundboard 41/295/325) проверяются на demo/read-only поведение, БД не
  пишется. **Q10c** — приёмка: grep-аудит «widget_scope_required нигде не показывается»,
  owning-тесты селектора/демо/бэкенда, след закрытия.

### ✅ Q11 · Биндинги с нуля · L (⚠️ 13.09 вечер: владелец отверг общий модальный билдер и охват «только 8 виджетов» — переделка в Q27, `DEC-OWNER-017`)

- **Разведка (13.09):** бэкенд уже контрактный и хорошо покрыт: `BINDING_CONTRACT` (v1,
  sources chat_command/eventsub/hotkey, роли, виджеты goals/sub_goal/countdown/now_playing/
  lower_third/soundboard/moderation), `validate_binding_contract`, `run_binding`,
  `handle_chat_command`/`handle_hotkey`/`handle_eventsub_event`, `apply_preset` —
  `tests/test_widget_bindings.py` (~25 тестов, включая legacy-чтение `counter` и
  unsafe-legacy-отклонение). Значит Q11 — преимущественно UI: старый общий билдер
  (`widgets.html` ~505–600, секция `bindings.title` + JS `waBind*` в `07_widgets.js`,
  скоуп `waBindingScope()` из Q10a) заменяется, а не бэкенд.
- **Принято: 13.09 · коммиты Q11a `f4e5b50`, Q11b `8ad9f45`, Q11c (см. `git log`) · тесты
  `tests/test_q11_builder_ui.py` (5), `test_widget_binding_scope_ui.py`, `test_panel_labels.py`,
  `test_widget_bindings.py` (25, включая legacy-чтение `counter` и отклонение unsafe-legacy),
  `test_w6_semantic_bindings.py`, `test_s3_hotkey_bindings.py`, `test_q7_bindings_placement.py`,
  node `donation_bridge_token_ui.test.js`, `panel_accessibility.test.js`,
  `widget_scope_override.test.js` — зелёные (86 python по binding-сьютам).**
  Q11a: ручные селекты бота/канала удалены — скоуп билдера = общий channel-first скоуп
  «Виджетов», авто-строка «Правило работает у бота X на канале #Y»; `/api/channel-overview`
  отдаёт роли, модератор-бот подставляется сам, ручной выбор — только при ≥2 модераторах.
  Q11b: плашка `panel.catalog.no_binding` и ключ удалены — у виджета без binding_slug ни
  одного упоминания биндингов. Q11c: grep-аудит остатков чист; миграция БД не требовалась —
  таблица `widget_bindings` уже per-scope, legacy-строки читает существующий движок (тесты
  `test_run_binding_counter_and_goals`, `test_runtime_rejects_legacy_viewer_binding` и др.).
  «Старый общий билдер заменён» в части ручного скоупа: КОГДА→ТОГДА-форма сохранена как
  модальный билдер, открываемый из карточек виджетов (waWidgetBindingAdd), без ручного
  выбора бота.

- **Q11a — новый билдер «КОГДА → ТОГДА»:** двухпанельная форма: слева «КОГДА»
  (источник: команда / событие Twitch / хоткей → поле match, для eventsub — селект из
  `BINDING_CONTRACT.sources.eventsub.matches`; роль), справа «ТОГДА» (виджет → действие →
  значение; динамическое действие soundboard `play_track:N`). Бот подставляется
  автоматически — модератор-бот канала из `waBindingScope()`; ручной выбор бота появляется
  только при двух и более модераторах канала (честный селект, подсказка почему). Кнопки
  «Настроить правило» у виджетов (`waWidgetBindingAdd('<slug>')`) открывают новый билдер
  с предвыбранным виджетом. Файлы: `templates/partials/widgets.html`,
  `static/app/07_widgets.js`, `static/app/21_panel_labels.js` (i18n RU/EN/UA) · тест: новый
  `tests/test_q11_builder_ui.py` + jsdom-тест контракта формы.
- **Q11b — никаких упоминаний биндингов у виджетов без них:** grep-аудит шаблонов/JS;
  строка-плашка «Биндинги: для этого контракта смысловые действия не объявлены»
  (`panel.catalog.no_binding`) у виджетов без `binding_slug` убирается целиком (не
  переформулируется); owning-тест «у виджета без binding_slug нет слова „биндинг“».
- **Q11c — приёмка:** старый билдер удалён (grep остатков `bindings.intro`/`waBind*`),
  прогон всех binding-сьютов (`test_widget_bindings`, `test_w6_semantic_bindings`,
  `test_s3_hotkey_bindings`, `test_q7_bindings_placement`, `test_widget_binding_scope_ui`),
  след закрытия. Миграция БД не нужна (таблица `widget_bindings` уже per-scope, legacy-строки
  читает существующий движок — тесты есть).

- **Что делаем (исходная формулировка):** правило читается как «КОГДА (команда/событие/хоткей) → ТОГДА (действие
  конкретного виджета)»; бот подставляется автоматически (модератор-бот канала), ручной выбор
  только при двух и более модераторах; у виджета без биндингов в UI нет ни одного упоминания
  биндингов; старый общий билдер заменён.
- **Готово когда:** владелец собирает правило за минуту, не выбирая бота вручную.
- **Агенту:** `app/widget_bindings.py` (`validate_binding_contract`, `run_binding`,
  `_active_bindings`), `app/widget_bus.py`, `static/app/07_widgets.js`,
  `templates/partials/widgets.html`, `widgets/` (манифесты действий) · тесты
  `tests/test_widget_bindings.py`, `tests/test_widget_binding_scope_ui.py`,
  `tests/test_q7_bindings_placement.py`, `tests/test_w6_semantic_bindings.py`,
  `tests/test_s3_hotkey_bindings.py`, `tests/test_roles_hotkeys.py` · миграция: старые биндинги
  помечаются legacy и читаются новым движком; бэкап `data/bot.db`; owning-тест на чтение
  legacy-строки · зависит: Q10, Q05. **Оговорка:** «с нуля» = новый модуль/билдер, а не
  перезапись общих файлов (`static/app.js`, `app/routes.py` — точечно, AGENTS.md §4).

### ⏳ Q12 · Полные карточки виджетов, ничего не спрятано в «прочих» · M (инженерная часть готова 14.09; визуальная browser-проверка — ⏸ владельцу при необходимости)

- **Принято (инженерная часть): 14.09 · коммиты Q12a+Q12b `a2935c6` (перенос атомарен:
  карточка «Прочие виджеты — контент» пустела ровно на переносе), Q12c — след в этой строке ·
  тесты `tests/test_q12_widget_forms.py` (4: формы в своих карточках каталога, id уникальны,
  в extras форм нет, ключи вычищены), `test_widgets_ui_cards.py`, `test_widget_extra_widgets.py`,
  `test_widget_theme_cohort_cards.py`, `test_panel_labels.py` + node
  `widget_admin_forms_ui.test.js` — зелёные.** Формы 7 виджетов — свёрнутые
  `<details class="wa-card-admin-form">` внутри своих карточек каталога (решение владельца:
  раскрышка, не модалка); id/контролы не переименованы (мина `wa2LoadAll`/тестов соблюдена);
  в «Прочее и гайды» остались только гайды; осиротевшие i18n-ключи вычищены
  (`panel.extra.title/hint` ×3), новый `panel.extra.content_form` RU/EN/UA.
  Визуальная проверка карточек (превью/zoom) — ⏸ владельцу (`DEC-OPS-001`).

- **Разведка (13.09):** каталог (`widget_inventory`, 32 виджета) рендерит полные карточки
  с превью-iframe (27 статических iframe + 1 в catalog-loop) — базовая полнота есть.
  Разрыв в другом: у 7 виджетов формы настроек живут отдельно от карточек — в группе
  «🧩 Прочее и гайды» (`wa2Form-lower-third`, `wa2Form-mascot`, `wa2Form-anime-runner`,
  `wa2Form-chat-roulette`, `wa2Form-latest-event-card`, `wa2Form-uptime`,
  `wa2Form-recent-events`), а карточки с превью этих виджетов — в других группах каталога.
  Механизм «раскрыть на весь экран» уже есть — кнопка «🔍 Увеличить» (`waWidgetZoom`) у
  каждой карточки.
- **Q12a — формы к карточкам:** админ-формы из «Прочего» переносятся в карточку
  соответствующего виджета в каталоге, свёрнутыми в `<details>` внутри карточки.
  **Решено владельцем 13.09 вечером (интервью): именно раскрышка в карточке, не модалка.**
  Контролы и их id не переименовывать (мина: JS
  `wa2LoadAll`/`13_widgets_session` и тесты завязаны на id) — меняется только
  контейнер в шаблоне. Файлы: `templates/partials/widgets.html`,
  `static/app/13_widgets_session.js` (только если порядок инициализации сломается) ·
  тесты: `test_widgets_ui_cards.py`, `widget_admin_forms_ui.test.js`,
  `test_widget_theme_cohort_cards.py`, обновить якоря, завязанные на позицию форм.
- **Q12b — «Прочее и гайды» чистит:** в группе остаются только гайды/документация
  (grep-аудит: форм `wa2Form-*` в группе нет); owning-тест «в extras нет форм с id
  wa2Form-*». i18n-ключ позиции форм не трогать без необходимости.
- **Q12c — приёмка:** визуальная проверка карточек (превью открывается, zoom работает) —
  browser-шаг (`DEC-OPS-001`, ⏸ владельцу при необходимости); след закрытия.

- **Что делаем (исходная формулировка):** у каждого виджета полная карточка с рабочим превью; где не влезает —
  раскрытие на весь экран или отдельная страница виджета; «Прочие виджеты» ничего не прячут.
- **Готово когда:** нет карточек со сломанным/невлезающим превью и скрытых виджетов.
- **Агенту:** `templates/partials/widgets.html`, `static/app/07_widgets.js`,
  `static/app/21_panel_labels.js`, `static/app.css` · тесты `tests/test_widgets_ui_cards.py`,
  `tests/test_widget_preview_coverage.py`, `tests/widget_admin_forms_ui.test.js`,
  `tests/test_widget_theme_cohort_cards.py`, `tests/test_widget_extra_widgets.py` ·
  миграция: нет · зависит: Q06, Q10.

### ⏳ Q13 · blur-guard: простая настройка и живая проверка · M (инженерная часть готова 14.09; живая проверка блюра — ⏸ владельцу)

- **Принято (инженерная часть): 14.09 · коммит `6141618` · тесты `tests/test_q13_blur_guard_ui.py`
  (4: primary-ряд, «Дополнительно», ни один контрол не потерян/переименован, i18n ×3),
  `test_widget_blur_guard.py`, `test_panel_labels.py` — зелёные.** Форма: primary-ряд
  «Защита вкл/выкл · Чувствительность · Длительность блюра · Режим (своя картинка/OBS-фильтр)»,
  остальное — в `<details id="waBgAdvanced">` «Дополнительно». Модель настроек
  (`blur_guard_settings`) и id контролов не менялись — существующие значения не сбрасываются,
  миграция данных не потребовалась. Живая проверка реактивного блюра (browser/OBS) — ⏸
  владельцу (`DEC-OPS-001`); пункт закроется после неё.

- **Разведка (13.09):** Q10 уже дал честный демо-режим карточек виджетов; форма blur-guard
  живёт в настройках виджета (admin-форма в `widgets.html`/`07_widgets.js`), статус —
  `app/blur_guard_routes.py`. При старте: перечитать модель настроек
  (`app/blur_guard.py`: поля чувствительности/длительности/своей картинки) и разложить
  форму на «Защита: вкл/выкл · Чувствительность · Длительность блюра · Своя картинка» +
  `<details>` «Дополнительно» для остального; существующие значения маппить, не сбрасывать
  (миграция значений, не схемы). Живая проверка блюра — ⏸ владельцу (browser/OBS,
  `DEC-OPS-001`).

- **Что делаем (исходная формулировка):** настройка читается как «Защита: вкл/выкл · Чувствительность · Длительность
  блюра · Своя картинка», остальное в «Дополнительно»; вживую подтвердить срабатывание
  реактивного блюра (или зафиксировать, почему нет и что починено).
- **Готово когда:** форма простая; блюр подтверждён вживую.
- **Агенту:** `app/blur_guard.py`, `app/blur_guard_routes.py`, `app/obs_blur.py`,
  `widgets/blur-guard-v2/`, `static/app/07_widgets.js` · тесты `tests/test_widget_blur_guard.py`
  + новый UI-тест упрощённой формы · миграция: существующие значения маппятся в новые поля,
  не сбрасываются · зависит: Q10; живая часть — browser/OBS (`DEC-OPS-001`).

### ⏳ Q27 · Биндинги v2: правила живут в карточке виджета, у всех 32 · XL (решения — `DEC-OWNER-017`; инженерная часть готова 14.09, живая проверка хоткея/правила в браузере — ⏸ владельцу)

- **Принято (инженерная часть): 14.09 · коммиты Q27a `8154a82` (14.09, из Q27a-записи ниже),
  Q27b `d369c5c`, Q27c `40171e1`, Q27d — след в этой строке · тесты: binding-сьюты
  `test_widget_bindings`, `test_w6_semantic_bindings`, `test_s3_hotkey_bindings`,
  `test_q7_bindings_placement`, `test_widget_binding_scope_ui`, `test_q27a_contract_v2`,
  `test_q27b_rules_sections` (6), `test_q11_builder_ui`, `test_w7_preview_contracts`,
  `test_widgets_ui_cards`, `test_panel_labels`, `test_widget_js_syntax` + node
  `widget_rules_section_ui.test.js` (4), `widget_scope_override`, `panel_dynamic_i18n`,
  `panel_accessibility`, `moderation_rules_ui`, `widget_admin_forms_ui` — зелёные.
  Осталось: живая проверка правила/хоткея в браузере (`DEC-OPS-001`, ⏸).**

- **Разведка (13.09, после Q11):** кнопка «🔗 Настроить правило» (`waWidgetBindingAdd`) у
  ВСЕХ карточек открывает одну общую модалку с селектом виджета (`waBindWidget`,
  `static/app/13_widgets_session.js:439`) — владелец это отверг. Рядом живёт и общий список
  правил (`waBindingsList`). Правила умеют только 8 виджетов из `BINDING_CONTRACT` (goals,
  sub_goal, countdown, now_playing, lower_third, soundboard, moderation), остальные 24 —
  никак. Сочетания клавиш уже поддержаны движком: фронтенд `waHotkeyComboFromEvent`
  собирает `ctrl+shift+x` (`static/app/15_feedback_2908.js:419`), бэкенд `handle_hotkey`
  матчит нормализованную строку (`app/widget_bindings.py:359`) — проблема только в UX.
  Схема БД `widget_bindings` per-scope уже годится, миграции схемы не требуется.
- **Решения владельца:** `DEC-OWNER-017` — правила в карточке, несколько правил на виджет,
  без общей модалки/таблицы; все 32 виджета с осмысленными действиями; хоткеи — панель
  открыта (фон. вкладка ок); порядок Q27 → Q28.
- **Q27a — контракт v2: осмысленные действия для остальных виджетов:** ✅ **принято 14.09**
  (бэкап `data/backups/pre-Q27a-2026-09-14.db`). `BINDING_CONTRACT` version → 2; новая
  партия: **mascot** (preset), **uptime** (start/stop сессии стрима), **subathon_timer**
  (start/stop/extend), **donation_challenge** (add_funds к активному сбору; без активного —
  честная `no_active_challenge`), **song_request** (skip/clear), **chat_highlight**
  (highlight текстом, видимый независимо от auto-гейта), **chat_roulette** (spin),
  **recent_events** (clear, со сбросом TTL-кэша ленты — OBS видит очистку сразу),
  **blur_guard_v2** (blur_on/blur_off через blur_guard_routes, недоступность OBS →
  `blur_unavailable`). `WIDGET_BINDING_SLUGS` дополнен 9 slug'ами; i18n RU/EN/UA —
  `13_widgets_session.js` + `15_feedback_2908.js`. Owning-тест Q7 обновлён: «без фейковых
  биндингов» осталось только для media-share и clip-moments (осмысленных действий пока нет);
  legacy v1-строки (`counter`) читаются движком (тест в `test_q27a_contract_v2.py`).
  **Тесты:** `test_q27a_contract_v2.py` (6) + полные binding-сьюты 225 python +
  смежные widget-сьюты + jsdom — зелёные. Попутный фикс: `recent_events_clear` сбрасывает
  `_RECENT_EVENTS_PUBLIC_CACHE` (`app/widgets.py`).
- **Q27b — секция «⚡ Правила» в карточке виджета:** ✅ **готово 14.09 (коммит `d369c5c`).**
  У каждого виджета с действиями — блок прямо в карточке (`details.wa-widget-rules`
  с `data-rules-slug`): список его правил (тумблер вкл/выкл, ✕ удалить, источник + match +
  действие) из общего кэша `window._waBindingsCache` и inline-форма «КОГДА → ТОГДА»
  (виджет уже выбран — селекта нет; источник команда/событие/хоткей; кнопка
  «⌨ Нажать сочетание» пишет хоткей в форму своей карточки). `waWidgetBindingAdd(slug,
  prefillAction)` открывает секцию карточки и скроллит к ней вместо модалки; привязка
  трека Soundboard (`waSoundboardBind`) идёт в секцию карточки с предзаполненным
  `play_track:<id>`. i18n RU/EN/UA (`bindings.rules_section`, `bindings.press_keys`);
  секции добавлены и в статические карточки (goals/sub_goal/now_playing/countdown/
  soundboard), и в карточки каталога.
- **Q27c — снос общей модалки и общего списка:** ✅ **готово 14.09 (коммит `40171e1`).**
  Карточка «Автоматизация виджетов» (`waBindingsCard`: общий список `waBindingsList`,
  селект `waBindWidget`, авто-строка, бот-пикер, пресет-селект `waBindPreset`, билдер
  `waBindingBuilder`) удалена вместе с `waBindingModal*`/`waBindingAdd`/
  `waBindingPresetApply`/`waBindingFieldsSync`/`waBindingActionsSync`/
  `waBindingScopeLoad`/`waBindingBotPickChanged`; `waBindingsLoad` стал лёгким загрузчиком
  кэша (списки рендерят секции карточек); авто-строка — `waRulesAutoLine` в каждой секции
  (выбор бота при нескольких модераторах — селектор канала в шапке, Q10a); datalist
  событий сохранён; осиротевшие i18n-ключи (19×3) и CSS старого билдера вычищены.
  Grep-аудит остатков чист; owning-тест «в панели нет общего списка правил и селекта
  виджета в форме правил» — в `test_q11_builder_ui.py::test_q27c_general_builder_is_gone`.
- **Q27d — приёмка:** ✅ **готово 14.09 (след в строке «Принято» выше):** все binding-сьюты
  (python 153 + node 8-мьют) зелёные; живая проверка хоткея/правила в браузере — ⏸
  владельцу (`DEC-OPS-001`). Миграция БД не требовалась (`widget_bindings` per-scope).
- **Зависимости:** Q10 ✅, Q11 ✅ (заменяет его UI-часть); для 7 виджетов из «Прочего»
  секция правил кладётся в карточку после/вместе с Q12a (формы уже в карточках).

### ✅ Q28 · Дизайн виджетов: брендовая палитра, готовые темы, живое превью · M (решения — `DEC-OWNER-017`; зависит от Q27b)

- **Принято: 14.09 · коммит `d65eada` (Q28a–d одним коммитом — подсистема едина:
  палитра→пипетка→темы работают через один механизм) · тесты `tests/test_widget_brand_palette.py`
  (5: дефолт, нормализация hex/лимит 10, per-канальная изоляция, отклонение мусора, роут в
  server.py), `tests/test_q28_brand_palette_ui.py` (6: редактор в шапке, полоски во всех 32
  карточках каталога + статических, живое перекрашивание через accent/bg, валидация hex в
  appearance.js, темы одним кликом, i18n RU/EN/UA) + смежные widget/panel-сьюты — зелёные.**
  Реализация: `app/widget_brand_routes.py` (GET/PUT `/api/widgets/brand-palette`,
  settings-kv `widget_brand_palette:<channel>` по `DEC-OWNER-002`, ≤10 hex, при отсутствии
  своей — стартовый набор); редактор палитры в шапке «Виджетов»; полоска в каждой карточке:
  свотчи канала + пипетка (свой цвет) + темы «Неон/Минимал/Градиент/Сброс» одним кликом
  (accent+bg+opacity); живое перекрашивание превью — `widgets/_shared/appearance.js` читает
  валидированные URL-параметры `accent`/`bg` (CSS-переменные `--w-accent`/
  `--widget-theme-accent`/`--w-bg`/`--widget-theme-surface`), OBS URL в карточке обновляется
  вместе с превью; дизайн-виджетам (tts/chat-reader) цвет сохраняется в `widget_design_*`
  через `waDesignSave`. Существующие `widget_design_*` не сбрасывались; browser-приёмка —
  ⏸ владельцу при необходимости (`DEC-OPS-001`).

- **Что делаем:** общая «брендовая» палитра акцентов per-канал (по `DEC-OWNER-002`; сами
  `widget_design_*` остаются per-виджет по `DEC-OWNER-016`) + свой цвет пипеткой в каждой
  карточке + живое перекрашивание превью в карточке сразу при выборе цвета + готовые темы
  (пресеты дизайна: акцент/фон/прозрачность одним кликом, например неон/минимал/градиент).
- **Разбивка (при старте):** Q28a — редактор брендовой палитры (per-канал) и доступ к её
  цветам из карточек; Q28b — палитра + пипетка + мгновенное перекрашивание превью;
  Q28c — готовые темы одним кликом; Q28d — приёмка (browser ⏸ владельцу при
  необходимости, `DEC-OPS-001`).
- **Готово когда:** владелец выбирает цвет из палитры или пипеткой в карточке виджета —
  превью перекрашивается сразу; тема применяется одним кликом.
- **Агенту:** `templates/partials/widgets.html`, `static/app/07_widgets.js`,
  `static/app/13_widgets_session.js`, `static/app/21_panel_labels.js`, `static/app.css`,
  design-роуты виджетов (`widget_design_*`) · тесты `test_panel_labels.py`,
  `test_widgets_ui_cards.py`, новый owning-тест палитры/тем · миграция: нет (новые
  настройки, существующие `widget_design_*` не сбрасывать) · зависит: Q27b (карточки уже
  содержат правила).

### ✅ Q29 · DEF-04: честный трёхсостоянийный AI-статус · S (взято владельцем 13.09, `DEC-OWNER-017` п.14)

- **Принято (инженерная часть): 14.09 · коммит `ac06a56` · тесты `tests/test_q29_ai_status.py`
  (5) + обновлён якорь `test_director_contracts.py` — зелёные.** `app/director.py`: чистый
  хелпер `_ai_health_state` (working / pause / error; «ошибка» только при паузе по ai_errors —
  реальной ошибке провайдера, `last_error` из DEF-02 подтягивается из `director_audit`);
  `get_status` отдаёт `ai_state` + `ai_last_error`, `health.ai` остался bool (обратная
  совместимость). Фронт `renderDirectorHealth`: AI-бейдж трёх состояний (working=готов,
  pause=«пауза между планами», error=ошибка с `last_error` в tooltip), i18n
  `director.status_pause` RU/EN/UA. Живая проверка статуса в панели — ⏸ владельцу.

- **Что делаем:** индикатор AI на `/status` перестаёт мигать «нет» в паузах между планами
  Режиссёра: состояния «AI работает / пауза между планами / ошибка» (последнее — только
  при реальной ошибке провайдера, см. `last_error` из DEF-02).
- **Готово когда:** в паузе между планами статус НЕ показывает «AI: нет» как ошибку.
- **Агенту:** `app/director.py` (статус-поводок), `app/routes.py` (`/status`),
  фронт статуса · тесты: новый тест трёх состояний + смежные director-сьюты · миграция: нет ·
  зависит: — (DEF-02 ✅ даёт `last_error`).

### ✅ Q30 · CAND-01: ревью live-реакций Режиссёра · M (взято владельцем 13.09, `DEC-OWNER-017` п.17)

- **Принято (инженерная часть): 14.09 · коммит `fbc7d2d` · тесты новый
  `tests/test_director_live_reactions.py` (3) + якоря в `director_review_ui.test.js` (2),
  director-сьюты зелёные.** `app/director_review.py`: `list_live_reactions` (live-планы
  с реально отправленными сообщениями `director_messages state='sent'` + LEFT JOIN
  `director_suggestion_reviews` для статуса решения) и `review_live_reaction` (только
  отправленные тексты, клиентские обязаны точно совпадать; пример через
  `_anonymize(bounded_context(...))`; записи в существующие `director_suggestion_reviews`
  (PK channel+plan_id) и `director_examples` positive/negative; лимит
  `EXAMPLE_LIMIT_BYTES` как у suggest; идемпотентный повтор, смена решения отклонена;
  миграция не потребовалась). Роуты GET `/reactions/live`,
  POST `/reactions/live/{plan_id}/approve|reject`. Фронт: секция «Отправленные вживую»
  рядом с `directorSuggestions`, `directorDecideReaction` (тексты не редактируются),
  i18n RU/EN/UA. Проверка владельцем в панели на живом канале — ⏸.

- **Что делаем:** в очереди ревью Режиссёра появляется вкладка «Отправленные вживую»:
  live-реакции (не suggest-планы) можно одобрить как позитивный пример или отклонить как
  негативный для обучения.
- **Готово когда:** владелец в панели отклоняет отправленную вживую реакцию, и она попадает
  в негативные примеры базы обучения канала.
- **Агенту:** `app/director.py` (реестр live-реакций, очередь ревью), `app/routes.py`,
  фронт Режиссёра (`static/app/20_director.js`) · тесты: director-сьюты + новый тест
  отклонения live-реакции · миграция: пометка source у записей ревью, legacy-строки —
  suggest как раньше · зависит: —.

### ✅ Q31 · Полиш самой панели (OPTIONAL-05) · M (взято владельцем 13.09, `DEC-OWNER-017` п.19; после Q13)

- **Принято: 14.09 · коммит `68ac666` · тесты `test_panel_labels.py`,
  `test_panel_accessibility.py`, `test_moderator_console_access.py` — 150 зелёных.**
  `static/app.css`: Q31-слой микровзаимодействий только CSS (шаблоны/id не тронуты):
  нажатие кнопок и честные disabled-состояния, cursor+hover для `details>summary`,
  подсветка строк таблиц, плавная прокрутка строго под
  `prefers-reduced-motion: no-preference`. Попутно закрыты два до-существующих отказа
  accessibility-гейтов (приехали со снапшотом Q20-эпохи): литеральные i18n-ключи — пропуск
  динамических префиксов на `_` (`panel.mod.ext_*`), shared-lifecycle — разрешён ровно один
  валидный ad-hoc Escape-обработчик (поповер пикера канала чата).

- **Что делаем:** визуальный полиш панельного UI вне виджетов (анимации, переходы,
  отступы) сверх обязательного dark/i18n/accessibility baseline; часть по виджетам уже
  покрывает Q28.
- **Готово когда:** панель не выглядит сырой на переходах/состояниях, без поломки
  accessibility.
- **Агенту:** `static/app.css`, точечно шаблоны · тесты: `test_panel_labels.py`,
  accessibility-тесты · миграция: нет · зависит: Q13.

### ✅ Q32 · Экспорт/импорт базы обучения Режиссёра (OPTIONAL-10 переформулирован) · M (взято владельцем 13.09, `DEC-OWNER-017` п.22)

- **Принято: 14.09 · коммит `620c525` · тесты новый `tests/test_director_training_io.py`
  (3) + якорь в `director_review_ui.test.js` — зелёные.** `app/director_review.py`:
  `export_training` (поканальный документ `director-training-export/v1`: промпты-тексты,
  примеры с payload, owner-чанты, шаблоны; server-owned replay-доказательства не
  экспортируются) и `import_training` (явный `confirm` обязателен; без `replace` дубликаты
  по content_hash/payload_hash/точному тексту пропускаются, с `replace` — строки канала и
  файлы примеров удаляются; импортированные версии промпта стартуют непроверенными —
  нужен свежий replay перед активацией; лимиты `EXAMPLE_LIMIT_BYTES` и
  `TRAINING_IMPORT_LIMITS`; `_assert_editable` блокирует при живой сессии). Роуты
  GET `/training/export`, POST `/training/import`. Фронт: кнопка экспорта + импорт файла
  с галкой замены в карточке промптов, i18n RU/EN/UA. Миграция не потребовалась.
  Перенос базы между каналами файлом владелец при желании проверяет в панели (⏸).

- **Что делаем:** вместо переноса базы между каналами — экспорт базы обучения канала
  (промпты, approved/rejected примеры, чанты, шаблоны) в файл и импорт из файла
  (с подтверждением и без затирания существующего без явного выбора владельца).
- **Готово когда:** владелец скачивает базу канала файлом и загружает её в другой канал.
- **Агенту:** `app/director.py` (`director_*` таблицы, поканальные по `DEC-OWNER-002`),
  `app/routes.py`, карточка канала · тесты: новый тест экспорт→импорт roundtrip на другой
  скоуп · миграция: нет · зависит: —.

### ✅ Q33 · Массовое добавление люркеров по токенам · S (принято 13.09, `DEC-OWNER-018`)

- **Принято: 13.09 (поздний вечер).** Кнопка «📥 Массово люркеры» в шапке «Ботов»: textarea
  (токен в строке, `oauth:`-префикс опционален), общий канал и общий прокси опционально.
  Ники берутся из Twitch (`/oauth2/validate` → login), битые/дубли пропускаются с отчётом,
  добавленные — включённые люркеры (`enabled=1`, `bot_role='lurker'`), при канале —
  сразу привязаны к нему. Лимит 200 токенов за раз.
  Эндпоинт `POST /api/accounts/bulk-lurkers` (`app/routes.py`); UI — `bots.html` +
  `03_bots.js` + i18n RU/EN/UA (Object.assign в `03_bots.js`, с guard'ом `typeof LANGS` —
  файл грузится jsdom-тестами без LANGS). Массовое перекидывание ботов на каналы — уже
  было (Q08 `bulk/channels`, `bulk/change-channel`).
- **Тесты:** новый `tests/test_bulk_lurkers_add.py` (3: добавление с каналом/прокси,
  отчёт по invalid/duplicate_nickname/duplicate_token/duplicate_batch, валидация ввода)
  + `test_panel_labels.py`, `test_actor_revert_cmdk.py`, `test_bulk_channels.py` и
  8 jsdom-сьютов на `03_bots.js` — зелёные.
- **Агенту:** `app/routes.py` (точечно), `templates/partials/bots.html` (кнопка + модалка),
  `static/app/03_bots.js` · миграция: нет · зависит: —.

### ✅ Q34 · «Пачка ботов»: кнопка стрима + распределённый заход · M (взято владельцем 14.09, `DEC-OWNER-019`)

- **Принято (инженерная часть): 15.09 · Q34a `fe710ce`, Q34b `aba0bc4`, Q34c `c2bb258` ·
  тесты `tests/test_bot_packs.py` (6), новый `tests/test_bot_pack_joins.py` (3),
  `tests/test_bot_packs_ui.py` + `bot_packs_ui.test.js`, panel_labels/accessibility/bulk-
  сьюты — 160 зелёных.** Q34a: `app/bot_packs.py`, таблицы `bot_packs` /
  `bot_pack_members` (+ `state_json`) и CRUD API `GET/POST /api/packs`,
  `PUT/DELETE /api/packs/{id}`; кнопка «📦 ➕ Создать пачку», модалка лёгкого выбора
  (чекбоксы ботов, поиск/роли/все-снять, канал каждого бота select-ом), карточка списка,
  редактирование/удаление. Q34b: «▶ Начать стрим»/«⏹ Свернуть», снимок enabled+каналов
  до пачки и точный откат; опция «и каналы»; старт использует тот же `bot_manager` путь,
  что ручное включение. Q34c: долговечная очередь `bot_pack_joins`, окно с равномерными
  слотами+jitter, progress/cancel в панели, восстановление воркера в lifespan после рестарта;
  окно 0 оставляет мгновенный вход. Перед первым запуском на реальной БД — бэкап по
  AGENTS.md §3; живая проверка владельцем (пачка, входы, collapse) — ⏸.

- **Что делаем:** система именованных **пачек** для старта/финиша стрима одной кнопкой.
  Пачка = снимок набора ботов (кто входит + привязка к каналам). Кнопка **«▶ Начать стрим
  по пачке»**: включает ботов пачки (чужие включённые боты не трогаются), привязывает к
  каналам пачки и запускает **распределённый заход** — окно «в течение N минут», боты
  входят с разбросом (равномерно-случайным), не залпом (friendly к anti-detection;
  задержка для одного бота — частный случай окна). Кнопка **«⏹ Свернуть стрим»** —
  массовое отключение ботов пачки (и, опционально, выключение привязанных каналов этой
  пачки). Снимок «как было до пачки» для отката без сюрпризов.
- **Готово когда:** владелец сохраняет текущий набор как пачку, по кнопке «Начать стрим»
  боты заходят в заданном окне по одному, «Свернуть» гасит пачку.
- **Разбивка (по конвенции M):** Q34a — модель+CRUD: таблицы `bot_packs` /
  `bot_pack_members` через `ensure_schema` (перед первым запуском — бэкап `data/bot.db`
  по AGENTS.md §3), API `GET/POST /api/packs`, `PUT/DELETE /api/packs/{id}`, кнопка
  **«➕ Создать пачку»** с модалкой простого выбора: полный список ботов чекбоксами
  (ник + роль + текущий канал), поиск по нику, «выбрать всех/снять всех», фильтр по роли;
  канал захода выбирается select-ом у каждого отмеченного бота (или «без канала»); имя
  пачки и окно захода (минуты) в той же форме.
  Редактирование пачки — та же модалка из карточки пачки (переименовать, добавить/убрать
  ботов и каналы, поменять окно; применение пачки при редактировании не запускается);
  Q34b — применение: `POST /api/packs/{id}/apply` (enable+привязка каналов+снимок прежнего
  состояния), `POST /api/packs/{id}/collapse` (массовое отключение), кнопки в карточке
  пачки, чекбокс «и каналы»; Q34c — распределённый заход: очередь захода с окном N минут
  (отмена/перепланирование), progress «кто зашёл / кто ждёт» в панели.
- **Агенту:** `app/bot_manager.py` (автоподключение при toggle — использовать, не
  дублировать; новое — планировщик заходов), `app/packs_routes.py` (новый) или точечно
  `app/routes.py`, `static/app/03_bots.js` + `templates/partials/bots.html`, i18n
  RU/EN/UA · тесты: новый сьют пачек (apply/collapse roundtrip, окно захода, отмена) +
  `test_bulk_channels.py`, panel_labels · миграция: новые таблицы, legacy не трогаем ·
  зависит: — (использует Q33/Q08 массовые примитивы).

### ✅ Q40 · Ручной или ИИ-Режиссёр · M (решение владельца 26.09; переоткрывает Q21)

- **Q40a ✅ принято инженерно 26.09 · тесты `director_page_ui.test.js` (новый, 3),
  `role_visibility_ui`, `director_review_ui`, `director_storage_ui`, `test_director_contracts`,
  `test_panel_labels`, `test_panel_theme_layout` (nav) — зелёные.** Паршал `director.html`
  (`section-director`), кнопка «🎬 Режиссёр» в меню; панель перенесена из `bots.html` целиком
  (все ID и контракты сохранены); слева/сверху — вкладка на каждый канал (статус сессии,
  lurkers онлайн/всего, стрелки на клавиатуре); `openDirectorPanel()`/`showSection('director')`
  открывают страницу. Два дизайна страницы по выбору владельца — **Пульт** (rail каналов слева)
  и **Кокпит** (карточки каналов сверху, градиенты): Настройки → «🎬 Дизайн Режиссёра»,
  выбор в `localStorage.directorSkin`. Попутно: `.section-header::after` ломал выравнивание
  кнопок во всех шапках разделов, двойная иконка 🔄 у «Обновить».
- **Q40b ✅ принято инженерно 26.09 · тесты `tests/test_director_manual.py` (новый, 6),
  `director_page_ui.test.js` (+2), director-сьюты — зелёные; живая проверка на QA-копии:
  запрет ссылки, отправка до слоя Twitch (`bot_not_connected` у офлайн-бота), журнал.**
  `app/director_manual.py`: `director_control_modes` (mode+emergency_fence) и
  `director_manual_messages`; API `GET /api/director/control-modes`,
  `PUT /api/director/{ch}/control-mode`, `POST|GET /api/director/{ch}/operator/send|messages`,
  `POST …/operator/unfence`; `director.start` → `director_manual_mode`, `emergency_stop_all`
  ставит fence; статус канала отдаёт `control_mode`/`manual_fenced`.
- **Q40b (описание).** Во вкладке канала переключатель **ИИ / Ручной**
  (per канал):
  1. **ИИ** — текущий Режиссёр без изменений (подрежимы Live / Suggest / Training в конфиге);
  2. **Ручной** — AI-сессия канала не стартует; оператор пишет текст, видит предпросмотр,
     явно выбирает аккаунт-отправителя из enabled lurkers канала и жмёт «Отправить»
     (кнопка/Enter). Отправка: те же запреты текста, что у планов (URL/`!commands`/
     `@mentions`/code), outgoing moderation, отдельный emergency-fence (общая «Экстренная
     остановка» блокирует и ручной режим до явного снятия). Таймеров, ротации отправителя
     и случайных задержек нет; журнал ручных отправок во вкладке.
  Переключение при живой AI-сессии запрещено (`settings_locked`).
- **Готово когда:** владелец открывает «🎬 Режиссёр», выбирает вкладку канала, ставит
  «Ручной» — пишет фразу, выбирает бота, отправляет, сообщение уходит от этого аккаунта и
  видно в журнале; ставит «ИИ» — Start запускает прежний автоматический Режиссёр.
- **Агенту (Q40b):** новый `app/director_manual.py` (таблицы через `ensure_schema`, хук одной
  строкой в `init_db`; `emergency_stop_all` ставит fence), роуты в `app/director_routes.py`,
  `director.start` отказывает в manual, фронт — секция в `20_director.js` + разметка в
  `director.html`, i18n RU/EN/UA · тесты: новый `tests/test_director_manual.py`,
  `director_page_ui.test.js` · миграция: только новые таблицы, default = ИИ (прежнее
  поведение); бэкап `data/bot.db` у владельца перед первым запуском.

### ⏳ Q41 · Общий редизайн панели в стиле «Пульт» · L (решение владельца 26.09)

- **Q41a ✅ 26.09 — общий слой стиля.** В конце `static/app.css` блок «Пульт» под
  `:root[data-panel-theme="dark"]`: зелёный акцент с тёмным текстом на заливке, плоские
  карточки с тонкой рамкой, моноширинные заголовки карточек, меню с полосой слева, кнопки
  6px, danger — контурная, вкладки бота — подчёркиванием. База `--bg/--text` не менялась
  (закреплена тестом). Починено: шапки разделов с фильтрами (Боты) сжимали кнопки
  в столбик — теперь перенос строки. Тесты темы/вёрстки — без новых падений.
- **Дальше (по разделу за коммит, со скриншотами):** Q41b Обзор (дубли подписей KPI),
  Q41c Боты/карточка бота, Q41d Каналы, Q41e Чат, Q41f Виджеты, Q41g Настройки/Статистика/
  Чат-логгер; затем чистка правил и планов (`PLAN_TODO` в архив, короткий активный план).

### ✅ Q14 · anime-runner: поднять историю git · S

- **Принято: 13.09 · коммит `21330a6` · тесты `tests/test_q14_anime_runner_settings.py` (4),
  `tests/test_widgets_folder.py`, `tests/test_widget_js_syntax.py`, `tests/test_panel_labels.py`
  — зелёные.** История поднята (`5305e4e` → `e9e2067`): файл виджета не терялся (текущий равен
  `e9e2067`), эволюция — только улучшения (тема/i18n). Потеря была в панельной форме Wave-6:
  7 полей вместо 20. Восстановлены ушки/перчатки/кроссовки/шорты, узор футболки, режим и точки
  маршрута (JSON), шанс паузы, idle, период случайного маршрута; бэкенд и виджет не тронуты.

- **Что делаем:** либо восстановить потерянные настройки из истории (снапшот `e9e2067` и ранее),
  либо честно закрыть «не восстановить» с перечислением проверенного.
- **Готово когда:** настройки найдены и восстановлены ИЛИ закрыто честным «нет».
- **Агенту:** `widgets/anime-runner/`, `git log --all -- widgets/anime-runner` · тесты
  `tests/test_widgets_folder.py`, `tests/test_widget_js_syntax.py` · миграция: нет;
  восстановление только из истории, без перезаписи текущего состояния · зависит: —.

### ✅ Q15 · Провайдеры и модели per-бот · L (скоуп изменён владельцем — `DEC-OWNER-016`)

- **Готово Q15a (13.09, коммит `dc50db6`):** селектор «Общая (по умолчанию) / Своя» в карточке
  бота (`botAIVisionMode`, пустой `ai_vision_model_override` = общая), поле «Общая Vision-модель»
  в Настройках осталось с честным описанием базы, dead-код live-настроек удалён из
  `14_brain_memory.js`, i18n-бейлайн учитывает динамические префиксы. Тесты
  `tests/test_q15_vision_mode_ui.py` (3) + panel_labels + plan_v13 — зелёные.
- **Готово Q15b (13.09, коммит см. `git log`):** E2 — у кастом-провайдера один редактор списка
  моделей `cpModelsEditor` с типом на модель (чат/vision/оба, кнопка «＋ Модель») вместо двух
  textarea; дубли имён схлопываются (первое написание, типы объединяются), модель «в обоих
  списках» больше не вписывается дважды; хранение `models`+`vision_models` и API-контракт не
  менялись. E3 — у бота при `custom:*`-провайдере чат-модель и vision-модель («своя») —
  дропдауны из списков его провайдера (пустое значение = «по умолчанию (первая модель
  провайдера)»), ручной ввод строкой остался только для встроенных провайдеров; смена
  провайдера сбрасывает выбор; контракт Q15a сохранён. i18n RU/EN/UA (новые `cp.add_model`,
  `cp.type_*`, `bot.model_default`, `bot.vision_default`; осиротевшие `cp.models_ph`,
  `cp.vision_models_ph`, `cp.vision_models_hint`, `panel.chat_models`, `panel.vision_models`
  удалены). Тесты: новые `tests/test_q15_provider_models_ui.py` (5) +
  `tests/q15_provider_models_ui.test.js` (2); обновлены `panel_custom_providers.test.js`,
  `test_p1_custom_providers.py`, `test_panel_labels.py`, `panel_dynamic_i18n.test.js`,
  `test_p1_bot_page_cards.py` — все зелёные (171 python + node).
  **Осталось:** Q15c (E4 — Ollama без автодобавления, fallback per-бот), Q15d (E5 — smart-routing
  per-бот).
- **Готово Q15c (13.09, коммит см. `git log`):** E4 — локальный fallback на Ollama выключен по
  умолчанию (env `LOCAL_FALLBACK_ENABLED` остался глобальным аварийным рубильником, дефолт «0»);
  у бота в карточке AI тумблер «Резерв: локальная Ollama» (`botAILocalFallback`) — ручной opt-in
  per-бот; колонка `accounts.ai_local_fallback` (ленивая миграция, бэкап
  `data/backups/pre-Q15c-2026-09-13.db`), поле `AccountAIOverride.local_fallback`, проводка через
  GET/PUT `/api/accounts/{id}/ai-override` и загрузчики override (`server.py`, `bootstrap.py`);
  эффективный флаг — `ai_service._local_fallback_for(account_id)` (per-бот opt-in сильнее,
  env — канал для ботов без явного выбора); автопереключения на Ollama без флага больше нет,
  circuit breaker (BUG-4) и offline_mode не тронуты. i18n RU/EN/UA (`bot.fallback_ollama`,
  `bot.fallback_ollama_hint`). Тесты: новый `tests/test_q15_local_fallback.py` (4: дефолт,
  per-бот opt-in, запись не выбрасывается, API-roundtrip) — зелёные вместе с
  `test_p1_custom_providers`, `test_ops_reliability`, `test_wave4_integration`, panel-сьютами.
- **Готово Q15d (13.09, коммит см. `git log`):** E5 — smart-routing чат-моделей per-бот:
  колонка `accounts.ai_smart_routing_json` (JSON {enabled, threshold, simple_provider,
  simple_model, complex_provider, complex_model}; пусто = наследовать глобальные
  `ai_smart_routing_*`, которые остаются legacy-fallback; бэкап
  `data/backups/pre-Q15d-2026-09-13.db`); поле `AccountAIOverride.smart_routing`, проводка
  через GET/PUT ai-override (валидация: threshold clamp ≥50, провайдеры из whitelist или
  `custom:<имя>` с проверкой в БД, выключенный routing не сохраняется) и загрузчики
  `server.py`/`bootstrap.py`; рантайм: `_smart_routing_for(account_id)` — конфиг бота сильнее
  глобального; `_apply_smart_routing(..., cfg=)` и `_classify_complexity(..., threshold=)`
  принимают per-бот параметры, `custom:<имя>` разрешён как целевой провайдер; UI — details
  «🧭 Smart-routing (чат-модели)» в карточке бота (тумблер, порог, простой/сложный →
  провайдер+модель); i18n RU/EN/UA (7 ключей `bot.smart_routing_*`). Тесты: новый
  `tests/test_q15_smart_routing.py` (6) + существующий `test_smart_routing.py` (12) —
  зелёные вместе с panel-сьютами.
- **Принято (агентская часть): 13.09 · коммиты Q15a `dc50db6`, Q15b `9e05c49`, Q15c `fc3e4b8`,
  Q15d (см. `git log`) · тесты `test_q15_vision_mode_ui.py`, `test_q15_provider_models_ui.py`,
  `q15_provider_models_ui.test.js`, `test_q15_local_fallback.py`, `test_q15_smart_routing.py`,
  `test_smart_routing.py`, `test_p1_custom_providers.py`, `panel_custom_providers.test.js`,
  `test_panel_labels.py`, `panel_dynamic_i18n.test.js`, `panel_accessibility.test.js`,
  `test_p1_bot_page_cards.py` — зелёные. Живой осмотр панели владельцем — по общему порядку
  (`DEC-OPS-001`).**
- **Примечание к миграции Q05:12:** глобальные ключи `ai_smart_routing_*` читаются как
  fallback и не удаляются; после того как владелец задаст routing хотя бы одному боту,
  глобальные значения для ботов с собственным конфигом не используются.

- **Что делаем:** (E1-нов) «Общая Vision-модель» **остаётся** в Настройках как базовая общая
  vision-конфигурация — там же провайдер и модели настраиваются детально (все боты смотрят
  один стрим); у бота появляется выбор «**общая (по умолчанию) / своя**»; (E2) у провайдера
  один список моделей с пометкой типа (чат/vision), модели не дублируются между
  провайдерами; (E3) у бота выпадающие «чат-модель» и «vision-модель» (при выборе «своя»)
  наполняются из моделей его провайдера, ручной ввод строкой убран; (E4) автодобавления
  Ollama нет, локальный fallback выключен по умолчанию и включается вручную per-бот
  («резерв: локальная Ollama»), circuit breaker остаётся; (E5, `DEC-OWNER-016`) smart-routing
  чат-моделей (`ai_smart_routing_*`) переносится per-бот — отдельный подпункт.
- **Готово когда:** у бота свой провайдер/модели или честный выбор «общая»; роутинг per-бот.
- **Разбивка при старте (13.09, разведка):** рантайм-резолв уже даёт нужную семантику
  (`ai_service._resolve`: `ov.vision_model` → иначе общая `global_vision_override` → иначе
  дефолт провайдера), поэтому E1-нов — это явный UI-выбор и честные подписи, без смены
  контракта. **Q15a** — у бота селектор «Vision: общая (по умолчанию) / своя» (пустой
  `ai_vision_model_override` = «общая», контракт сохранён), поле «Общая Vision-модель» в
  Настройках остаётся с честным описанием «база для всех ботов с режимом „общая“».
  **Q15b** (E2/E3) — у кастом-провайдера один список моделей с пометкой «vision» (хранение
  `models`+`vision_models` сохраняется, UI объединяет), у бота чат/vision-поля наполняются
  списком его `custom:*`-провайдера. **Q15c** (E4) — Ollama: без автодобавления, локальный
  fallback выключен по умолчанию, per-бот тумблер «резерв: локальная Ollama», circuit
  breaker остаётся. **Q15d** (E5) — smart-routing per-бот (перенос `ai_smart_routing_*`).
- **Агенту:** `templates/partials/settings.html` (строка 24 — `globalVisionModel`),
  `static/app/04_chat_settings.js` (328, 330, 869 — `global_vision_override`),
  `app/ai_service.py`, `app/local_fallback.py`, `app/database.py`, `static/app/05_bots_tabs.js` ·
  тесты `tests/panel_custom_providers.test.js`, `tests/test_p1_custom_providers.py`,
  `tests/test_provider_settings_api.py`, `tests/test_providers_direct.py`,
  `tests/test_p8_c10_custom_providers_merged.py`, `tests/test_director_provider_matrix.py` ·
  миграция: глобальная vision-конфигурация **не удаляется** — остаётся базой по умолчанию
  (`DEC-OWNER-016`); `ai_smart_routing_*` до переноса читаются как fallback, после — legacy;
  бэкап БД; owning-тест «бот с выбором „своя“ и без своей модели получает прежнее глобальное
  значение; с выбором „общая“ — общую конфигурацию» · зависит: Q05 ✅ (`DEC-OWNER-016`).

### ✅ Q16 · Убрать глобальные рубильники Настроек · M

- **Принято: 13.09 · коммиты F1 `7137a8c`, F2 `c57a0cd`, F3 `7ad5cee`, F4 `3df8a62`, F5
  `04c3dba` · тесты `tests/test_q16_switches.py` (F1–F5 owning-тесты), `test_panel_labels.py`,
  `test_moderator_console_access.py`, `test_p8_c6_replay_default_on.py`, `test_p6_tts_chat.py`,
  `test_s6_tts_per_bot.py`, `test_o2_tts_status.py`, `media_share_disclosure_ui.test.js`,
  `panel_accessibility.test.js`, `panel_dirty_guard.test.js` — зелёные.**
  (F1) карточка и роуты `/api/settings/provocations-master` удалены; значение в settings не
  тронуто — `chat_analyzer` читает как legacy-fallback; вкл/выкл — `conflictEnabled` во вкладке
  «Характер». (F2) модалка Media Share убрана — постоянная подсказка `widgets.media_share_hint`
  в форме медиа-шары, кнопки работают напрямую, disclosure-роуты — legacy (DEC-MEDIA-001).
  (F3) карточка «TTS (глобально)» удалена, TTS полностью per-бот; карта «кто что озвучивает»
  переехала в TTS-карточку бота; `/api/tts/config` остался (онбординг, legacy-fallback).
  (F4) `moderatorTTSAdminCard` целиком в `botTab-moderation`, открывается из `loadBotModeration`
  со скоупом текущего бота. (F5) `replay_auto_record` — колонка `accounts.replay_auto_record`
  (NULL = глобальный fallback), API `/api/accounts/{id}/replay-settings`, тумблер в карточке
  «Запись сессий», `bot_manager` берёт выбор бота первым. Бэкапы: `pre-Q15c`/`pre-Q15d`/
  `pre-Q16-F5` (миграции F1–F4 схему БД не меняли). Починен до-существующий сбой
  `panel_dirty_guard` (стаб `setDirectorPanelVisible` из Q21).

- **Что делаем (исходная формулировка):** (F1) главного рубильника провокаций нет — вкл/выкл только у бота во вкладке
  «Характер», без «OFF приглушает»; (F2) вместо помпезной модалки media-share — одна
  строка-подсказка в форме медиа-шары; (F3) глобального TTS-раздела нет, TTS полностью
  per-бот (провайдер/голос/события); (F4) «Модератор TTS консоль» видна только у бота-модератора;
  (F5, `DEC-OWNER-016`) автозапись replay-сессий (`replay_auto_record`) — настройка бота,
  глобальный рубильник из Настроек убирается.
- **Готово когда:** в Настройках нет этих рубильников, всё работает per-бот.
- **Агенту:** `templates/partials/settings.html` (120-122 провокации, 136 TTS, 179-181 routing
  map, 262-263 TTS output), `static/app/12_dashboard_extras.js` (56-65),
  `static/app/04_chat_settings.js`, `app/conflict_provocation.py`, `app/routes_tts_config.py`,
  `app/tts_routing_routes.py`, `app/moderator_console_routes.py`, `static/app/05_bots_tabs.js`,
  `static/app/06_roles.js` · тесты `tests/test_p6_tts_chat.py`, `tests/test_s6_tts_per_bot.py`,
  `tests/test_tts_duck_settings.py`, `tests/test_o2_tts_status.py`,
  `tests/media_share_disclosure_ui.test.js`, `tests/test_moderator_console_access.py`,
  `tests/role_visibility_ui.test.js` · миграция: сохранённые глобальные значения читаются как
  fallback при первом открытии настроек бота, затем помечаются legacy; не удаляются.
  «TTS-моменты в OBS» отложены владельцем — в план не возвращать без запроса · зависит: Q05.

### ✅ Q17 · Память о зрителях, предложения по улучшению, KB — per-бот · M

- **Принято: 13.09 · коммит `41218ff` · тесты `tests/q17_bot_memory_ui.test.js` (5),
  `tests/panel_dynamic_i18n.test.js`, `tests/test_panel_labels.py`,
  `tests/test_p8_c7_learning_hint.py` (перенацелен на bots.html), смежные
  `test_brain_modules`, `test_brain_channel_scope`, `test_p3_memory_scope`,
  `test_ai_feedback`, `test_ai_quality*`, `test_s9k_feedback_categories`, `test_user_memory`
  — зелёные.** «Факты о зрителях» и «Обучение (предложения)» переехали из «Мозга» во вкладку
  бота (botTab-memory, аккаунт из `_currentBotId`); память видна только при включённой
  долгосрочной памяти — тумблер `use_long_term_memory` с честной подсказкой в выключенном
  состоянии; KB-импорт/экспорт удалён из «Мозга» целиком (`DEC-OWNER-003`), per-бот вкладка KB
  и поиск не тронуты; мина учтена — `15_feedback_2908.js` правился точечно, не перестраивался.

- **Что делаем:** «Что бот запомнил о зрителях» и «Предложения по улучшению» (фидбек 👍/👎,
  learning) переезжают во вкладку бота (память видна только если у бота память включена);
  из «Мозга» оба раздела убраны; у KB убран глобальный импорт/экспорт JSON из «Мозга»,
  per-бот вкладка «Knowledge base + Mimicry» и поиск по KB остаются.
- **Готово когда:** в «Мозге» этих разделов нет, во вкладке бота — есть.
- **Агенту:** `static/app/14_brain_memory.js`, `static/app/15_feedback_2908.js`,
  `static/app/05_bots_tabs.js` (строка 779 — KB-вкладка), `app/user_memory.py`,
  `app/routes_user_memory.py`, `app/routes_ai_feedback.py`, `app/learning.py`,
  `app/ai_quality.py` (`score_kb_entry`), `app/routes_ai_quality.py`,
  `templates/partials/brain.html` (строка 153 — KB импорт/экспорт) · тесты
  `tests/test_p3_memory_scope.py`, `tests/test_ai_feedback.py`, `tests/test_ai_quality.py`,
  `tests/test_ai_quality_api.py`, `tests/test_ai_quality_db.py`, `tests/test_brain_modules.py`,
  `tests/test_s9k_feedback_categories.py` · миграция: строки `streamer_kb` (сейчас 0) и записи
  памяти/фидбека не удаляются — меняются только точки входа в UI · зависит: `DEC-OWNER-003`.
- **⚠️ Мина (проверено grep-ом 13.09):** `static/app/15_feedback_2908.js` (885 строк) — это не
  «файл фидбека». В нём живут обще-панельные хелперы: `uiToggle` (~40 вхождений в
  `chat.html`, `bots.html`, `settings.html`, `widgets.html`, `brain.html`, `03_bots.js`,
  `06_roles.js`, `13_widgets_session.js`), `toggleCardCollapse`/`initCollapsibleCards`,
  захват хоткеев `waHotkeyCapture`/`waHotkeyComboFromEvent` (зовётся из
  `templates/partials/widgets.html`), виджетные `wa2*`, пресеты персоны и
  `loadGlobalStreamerProfile`. Разделы памяти/фидбека из него можно только вырезать точечно;
  удалять или переименовывать файл целиком — нельзя, ляжет вся панель.

### ✅ Q18 · Запретки: per-канал плюс базовый пресет Twitch · M

- **Принято: 13.09 · коммиты `b6c85c2` (Q18a бэкенд), `d454944` (Q18b UI) · тесты
  `tests/test_channel_bans.py` (5), `tests/test_prompt_base.py` (обновлён: «пусто по
  умолчанию» больше не существует — канал наследует пресет), `tests/test_channel_card_profile_ui.py`,
  `tests/test_brain_preview.py`, `tests/test_brain_channel_scope.py` — зелёные.** Пресет в
  settings-kv `banned_topics_preset` — сид из legacy `prompt_base` (миграция Q05:19, не
  теряются) иначе стартовый набор `moderation_dicts/banned_topics_twitch.json`; свой список
  канала `banned_topics:<channel>` с наследованием; рантайм `_load_prompt_base_block(channel)`
  — честный заголовок «канал #X / базовый пресет Twitch»; роуты `/api/bans/channel` и
  `/api/bans/preset` (пресет — единственное «общее», `DEC-OWNER-004`); редактор в модалке
  «Профиль канала», глобальный редактор из «Мозга» убран; схема БД не менялась.

- **Что делаем:** у каждого канала свой редактируемый список запретных тем; базовый пресет
  запретов Twitch, из которого канал стартует и который владелец правит; глобального
  редактора запреток в «Мозге» нет.
- **Готово когда:** запретки правятся в карточке канала, каждая канальная тема — на месте.
- **Агенту:** `app/routes_prompt_base.py`, `app/chat_prompt_blocks.py`, `app/chat_analyzer.py`,
  `app/brain_preview.py`, `templates/partials/channels.html`, `templates/partials/brain.html`,
  `static/app/11_brain_v16.js`, `static/app/19_channels_bulk.js` · тесты
  `tests/test_prompt_base.py`, `tests/test_brain_preview.py`,
  `tests/test_brain_channel_scope.py`, `tests/test_c3_corrections_context.py` · миграция:
  существующие общие запретки становятся содержимым пресета (не теряются); per-канал списки
  создаются пустыми с наследованием пресета; бэкап `data/bot.db` · зависит: Q09 ✅,
  `DEC-OWNER-004`.
- **Разбивка при старте (13.09):** **Q18a** — бэкенд `app/channel_bans.py`: пресет в
  settings-kv `banned_topics_preset` (сид: legacy-текст `prompt_base`, если непуст, иначе
  стартовый набор `app/moderation_dicts/banned_topics_twitch.json`), свой список канала в
  `banned_topics:<channel>` (нет ключа → наследует пресет); роуты `/api/bans/channel`
  GET/PUT и `/api/bans/preset` GET/PUT; рантайм `_load_prompt_base_block(channel)` читает
  список канала → пресет (заголовок блока честный); формат текста прежний (одна запретка
  на строку, «#»-комментарии); схема БД не меняется — бэкап не требуется. **Q18b** — UI:
  карточка «Запретные темы канала» в модалке «Профиль канала» (+ редактор пресета —
  единственное «общее» по `DEC-OWNER-004`), глобальный редактор запреток из «Мозга»
  убирается; i18n RU/EN/UA; тесты обоих подпунктов.

### ✅ Q19 · Убрать вкладку «Мозг» · S

- **Принято: 13.09 · коммит `53202df` · тесты `tests/test_channel_card_profile_ui.py` (+Q19-блок),
  `tests/test_panel_labels.py`, `tests/test_brain_modules.py`, `tests/test_brain_channel_scope.py`,
  `tests/test_brain_preview.py`, node `tests/panel_dynamic_i18n.test.js` (переведён с мёртвой
  live-половины на живой контракт), `tests/panel_accessibility.test.js` — зелёные.** Nav-кнопка
  и include паршала удалены из `base.html`, `initBrain()` не зовётся, `'brain'` убран из валидных
  секций; браузер прогонов сводок переехал в модалку «Профиль канала» (реестр строка 104);
  мозг-файлы (09/11/14/15) сохранены — обслуживают ботов и виджетов (мины учтены); API и данные
  не удалялись.

- **Что делаем:** пункта «Мозг» нет в навигации; все разделы переехали (Q09, Q17, Q18);
  grep по `templates/` и `static/` не даёт живых ссылок на вкладку.
- **Готово когда:** у владельца нет ни одной причины открывать «Мозг».
- **Реестр разделов `templates/partials/brain.html`** (проверен 13.09 — 7 секций; у каждой должен
  быть новый дом **до** удаления вкладки, иначе данные станут недоступны из UI):

  | строка | раздел | куда переезжает |
  |---|---|---|
  | 14 | 🚫 Общая база запреток (PB-1/PB-2) | Q18 → карточка канала + пресет Twitch |
  | 24 | 📖 Lore стримера | Q09 → карточка канала |
  | 52 | 👤 Профиль стримера | Q09 → карточка канала |
  | 91 | 🎓 Обучение (предложения) | Q17 → вкладка бота |
  | 104 | 📝 Сводки стрима | Q09 → карточка канала |
  | 150 | 📚 KB — импорт/экспорт JSON | Q17 → убирается (per-бот KB-вкладка остаётся) |
  | 171 | 💾 Факты о зрителях (подтверждение) | Q17 → вкладка бота |

  Если к старту Q19 секций стало восемь — сначала решить, куда новая, и только потом убирать вкладку.
- **Живых ссылок на вкладку ровно 3** (проверено grep-ом 13.09): `templates/base.html:81`
  (nav-кнопка), `static/app.js:2105` (`if (name === 'brain') initBrain()`),
  `static/app/04_chat_settings.js:1057` (`'brain'` в списке валидных секций). Include паршала
  (`base.html:127`) и script-теги (`base.html:143-148`) не трогать, пока их функции нужны
  ботам и виджетам (см. мины ниже).
- **⚠️ Мины — эти «файлы Мозга» обслуживают не только Мозг:**
  - `static/app/09_brain_p3.js`: `showWidgetInstr` — кнопка «❓ Инструкция» у **каждого** виджета
    (`templates/partials/widgets.html:1039`); subathon-карточка; `loadBrainPreview` — зовётся из
    карточки бота (`templates/partials/bots.html:66`) и из `static/app/06_roles.js:553` (таб `brain-x`).
  - `static/app/11_brain_v16.js`: `loadBotOverviewExtras` (`static/app/03_bots.js:526`),
    `loadQuickBehavior` (`static/app/06_roles.js:334`), `saveQuickObservation` — тумблер
    «Только наблюдает» (`templates/partials/bots.html:126`, он же предмет проверки D1).
  - Вывод: оба файла правятся точечно и не удаляются; Q19 = убрать nav-пункт, паршал и
    `initBrain()`, а не «почистить brain-файлы».
- **Агенту:** `templates/base.html`, `templates/partials/brain.html`, `static/app/09_brain_p3.js`,
  `static/app/11_brain_v16.js`, `static/app/14_brain_memory.js`, `static/app/15_feedback_2908.js`,
  `static/app/24_dynamic_i18n.js` · тесты `tests/test_brain_modules.py`,
  `tests/test_brain_preview.py`, `tests/test_brain_channel_scope.py`,
  `tests/panel_dynamic_i18n.test.js`, `tests/panel_accessibility.test.js` · миграция: API/роуты
  «Мозга» остаются (их читают каналы и боты), убирается только вкладка; данные не удаляются ·
  зависит: Q09, Q17, Q18. **Точка невозврата:** только после проверки всех трёх.

### ✅ Q20 · Композер чата: бот и канал у кнопки «Отправить» · M

- **Принято: 13.09 · коммит `c7136c2` · тесты `tests/chat_composer_ui.test.js` (5),
  `tests/test_multi_bot_chat.py` (22), `tests/test_panel_labels.py`,
  `tests/panel_accessibility.test.js` — зелёные.** Селекторы бота и канала переехали из шапки
  в строку композера у кнопки «Отправить»; селектор канала — поисковый пикер с группировкой
  по ботам (hidden `#chatChannel` как держатель состояния — вся прежняя логика send/view
  сохранена), «Все каналы» внутри пикера, закрытие по клику мимо/Escape; i18n RU/EN/UA.

- **Что делаем:** выбор бота и канала — одна связка кликов прямо у кнопки «Отправить»
  (сейчас бот в стороне); селектор канала с поиском и группировкой по ботам.
- **Готово когда:** выбрал бота → канал → отправил, не уезжая по странице.
- **Агенту:** `templates/partials/chat.html`, `static/app/18_dm_chat.js`,
  `static/app/04_chat_settings.js`, `app/dm_chat.py`, `app/multi_bot_chat.py` · тесты
  `tests/test_multi_bot_chat.py` + новый `tests/chat_composer_ui.test.js` · миграция: нет ·
  зависит: Q08 (общий селектор «бот × канал»).

### ✅ Q21 · Панель Режиссёра внутри бота · M

- **Принято: 13.09 · коммит `e54cb9e` · тесты director-сьюты (66):
  `test_director_contracts`, `test_director_config`, `test_director_storage`,
  `test_director_lifecycle`, `test_director_provider_errors`, `director_storage_ui` (10),
  `director_review_ui` (13), `role_visibility_ui`, `test_panel_theme_layout` — зелёные.**
  Паршал `director.html` перенесён в `bots.html` (`directorBotPanel`, все ID и контракты
  storage/lifecycle сохранены); глобальная страница и nav-кнопка удалены; `openDirectorPanel(id)`
  открывает панель внутри карточки (прячет обычные вкладки и Старт/Разговор);
  `showSection('director')` редиректит на карточку бота (старые ссылки работают); без
  director-бота — честная подсказка; i18n `director.no_bot` RU/EN/UA; FILE_ZONES не менялся
  (запись только про app-файлы). URL/роуты API Режиссёра не удалялись.

- **Что делаем:** отдельной глобальной страницы Режиссёра нет — панель живёт внутри бота с
  ролью «режиссёр» (карточка/вкладка бота); Start/Pause/Resume/Stop, Emergency Stop, Workers,
  конфигурация и storage-панель сохранены полностью.
- **Готово когда:** всё управляется из карточки бота-режиссёра, ничего не потеряно.
- **Агенту:** `templates/partials/director.html`, `templates/partials/bots.html`,
  `static/app/20_director.js`, `static/app/25_director_storage.js`, `static/app/05_bots_tabs.js`,
  `app/director_routes.py` · тесты `tests/test_director_config.py`, `tests/test_director_storage.py`,
  `tests/test_director_lifecycle.py`, `tests/director_storage_ui.test.js`,
  `tests/director_review_ui.test.js` · миграция: URL/роуты Режиссёра не удалять молча —
  оставить редирект на карточку бота; storage/lifecycle контракты не менять · зависит: Q08.

### ✅ Q22 · Плотная сетка карточек ботов · M

- **Принято: 13.09 · коммит `151a72a` · тесты `tests/panel_theme_layout.test.js` (+1, 7),
  `tests/panel_lurker_ui.test.js`, `tests/panel_accessibility.test.js` — зелёные.** Выделенная
  сетка `.bots-grid` (колонки от 250px, зазор 12px, `align-items:start` — карточки по высоте
  контента без пустых провалов внутри ряда); компакт-режим и мобильная вёрстка не тронуты.

- **Что делаем:** в «Ботах» нет разрежённых строк с пустым местом — плотная сетка карточек,
  действия карточки доступны без лишней прокрутки.
- **Готово когда:** визуально плотно, ничего не уезжает.
- **Агенту:** `templates/partials/bots.html`, `static/app/03_bots.js`, `static/app.css` ·
  тесты `tests/panel_theme_layout.test.js`, `tests/role_visibility_ui.test.js`,
  `tests/panel_accessibility.test.js` · миграция: нет · зависит: Q08 (одна вёрстка с фильтрами).

### ✅ Q23 · Сводка в «Обзоре» · M

- **Принято: 13.09 · коммит `7f06d6b` · тесты `tests/dashboard_overview_ui.test.js` (5),
  `tests/test_ab_dashboard.py` (17), `tests/test_panel_labels.py`, `panel_analytics_state` —
  зелёные.** Сверху «Обзора» — карточка «Расклад»: чипы итогов (подключено N из M) и ролей,
  мини-таблица «канал → боты со статусами 🟢/⚫ → живые подключения»; обновляется при загрузке
  и живых health-событиях; данные уже на клиенте — бэкенд не менялся; i18n RU/EN/UA.

- **Что делаем:** сверху «Обзора» — сводка: сколько ботов, кто к какому каналу подключён,
  роли и живые подключения (мини-таблица или чипы со статусами).
- **Готово когда:** открыл Обзор и сразу виден весь расклад.
- **Агенту:** `templates/partials/dashboard.html`, `static/app/02_dashboard.js`,
  `static/app/12_dashboard_extras.js`, `app/ab_dashboard.py` · тесты `tests/test_ab_dashboard.py`,
  `tests/panel_analytics_state.test.js` + новый `tests/dashboard_overview_ui.test.js` ·
  миграция: нет · зависит: Q08 (роли и подключения из той же модели).

### ✅ Q24 · Тумблер всплывашек (mod-feed и лайв-события) · S

- **Принято: 13.09 · коммит `311bd0c` · тесты `tests/popups_toggle_ui.test.js` (6),
  `tests/test_mod_feed.py`, `tests/mod_feed_i18n.test.js`, `tests/test_panel_labels.py` —
  зелёные.** Тумблер «Не показывать всплывашки» в шапке Обзора; состояние в localStorage
  (`panelPopupsHidden`, по умолчанию показываются); гейтит плавающие карточки решений
  (moderation pending) и тосты live-событий (health_alert); inline-списки Обзора и журнала
  канала не тронуты; глобальное UI-предпочтение — исключение 1 из `DEC-OWNER-002`;
  `app/mod_feed_routes.py` не менялся (бэкенду не нужно).

- **Что делаем:** настройка «не показывать всплывашки», состояние в localStorage, попапы
  не выскакивают при включённой.
- **Готово когда:** включил — всплывашки исчезли.
- **Агенту:** `static/app/12_dashboard_extras.js`, `app/mod_feed_routes.py`,
  `templates/partials/dashboard.html`, `static/app/24_dynamic_i18n.js` · тесты
  `tests/test_mod_feed.py`, `tests/mod_feed_i18n.test.js` + новый UI-тест тумблера ·
  миграция: нет · зависит: —. Это осознанное глобальное UI-предпочтение владельца —
  исключение 1 из `DEC-OWNER-002`.

### ✅ Q25 · Beep-настройка у бота-модератора · M (живая проверка пипов — ⏸ «Ждём владельца»)

- **Принято (инженерная часть): 13.09 · коммит `c77040b` · тесты
  `tests/test_q25_beep_placement.py` (5), `tests/test_beep_guard.py`, `tests/test_p3_beep_pipeline.py`,
  `tests/test_panel_labels.py` — зелёные.** Карточка beep-конвейера переехала из вкладки «Чат»
  в botTab-moderation (рядом с пакетом модератора); загрузка статуса — в `loadBotModeration`,
  вход в «Чат» больше не тянет карточку; статус честный: «работает» или «pass-through (звук
  идёт без обработки)» на трёх языках; бэкенд `beep_pipeline`/`beep_settings` не менялся
  (`beep_settings` читаются как раньше, `beep_guard.ensure_schema()` без изменений).

- **Что делаем:** настройка beep-конвейера переезжает из вкладки «Чат» в настройки бота с
  ролью «модератор» (рядом с «Модератор TTS консоль» из Q16); состояние конвейера честно
  показывает работу или pass-through.
- **Готово когда:** настройка у бота-модератора, статус честный.
- **Агенту:** `app/beep_guard.py`, `app/beep_pipeline.py`, `templates/partials/chat.html`,
  `static/app/18_dm_chat.js`, `static/app/05_bots_tabs.js`, `app/moderator_console_routes.py` ·
  тесты `tests/test_beep_guard.py` + новый UI-тест размещения (по образцу
  `tests/test_q7_bindings_placement.py`) · миграция: `beep_settings` читаются как раньше
  (`beep_guard.ensure_schema()`); меняется точка входа в UI и владелец настройки ·
  зависит: `DEC-OWNER-005`; живая проверка пипов — в «Ждём владельца».

### ✅ Q26 · Журнал наказаний, очередь подтверждения, список защищённых · L

- **Принято: 13.09 · коммит см. `git log` · тесты `tests/test_moderation_journal.py` (9) +
  `tests/test_moderation_protected_list.py` (5) + `tests/channel_moderation_ui.test.js` (9) —
  зелёные; повторный прогон `test_moderation.py`, `test_moderation_action_ext.py`,
  `test_moderation_category_policy.py`, `test_moderation_base_rules.py`,
  `test_s5_db_isolation.py`, `test_panel_labels.py`, `panel_accessibility` — зелёные.**
  Реализация: новый `app/moderation_journal.py` (таблица `moderation_journal` со статусами
  applied/pending/cancelled/expired, `journal_applied`/`journal_pending`/
  `journal_resolve_by_pending`/`expire_stale_pending` — автозакрытие через 30 дней лениво при
  чтении; ensure_schema() одной строкой из `init_db()`; бэкап `data/backups/pre-Q26-2026-09-13.db`).
  Движок Q01 пишет журнал: применённое наказание → applied; защищённый бан и ask/learn-рекомендация
  → pending (наказание не применяется); решение владельца через существующую
  `record_timeout_decision` помечает запись applied/cancelled (дубль исключён:
  `write_journal=False` при исполнении из очереди). Новый
  `app/moderation_journal_routes.py` + one-line include в `server.py`: журнал/очередь/resolve,
  «Разбанить» через официальный `unban_user` (400 «not banned» → «уже не забанен», не ошибка),
  CRUD защищённых (per-бот × per-канал, auto_roles отдаются в UI). UI — модалка «Модерация» в
  карточке канала (`channels.html`): бот-селектор, очередь с «Забанить»/«Не наказывать», журнал
  со статусами, список защищённых (+добавить/убрать), разбан; JS в `19_channels_bulk.js`,
  i18n RU/EN/UA в `app.js`. «Не делать» соблюдено: без всплывашек, без модераторского сайта,
  без авто-отмены наказаний. Дважды пойманная и исправленная ошибка решения: journal_resolve
  вызывался только в ветке одобрения — отклонённые случаи оставались pending.

- **Что делаем:** в карточке канала — вкладка «Модерация»: (а) **журнал наказаний** (кто, когда,
  за что, какое действие, статус); (б) **очередь подтверждения** для случаев «бан навсегда» на
  защищённом зрителе, с решением «забанить / не наказывать»; (в) **список защищённых** этого
  канала (добавить/убрать имя вручную); (г) кнопка **«Разбанить»** → официальный Unban User.
  Модераторы и редакторы канала защищены автоматически, в список их вписывать не нужно.
- **Готово когда:** владелец видит в карточке канала все наказания бота, может одним нажатием
  разбанить и разобрать очередь; «бан навсегда» на защищённом не применяется, а лежит в очереди
  и ждёт решения.
- **Контракт (`DEC-OWNER-014`, интервью 13.09):**
  - защищённые = модераторы/редакторы канала (всегда, автоматически) + ручной список канала;
    список **per-канал**, общего на все каналы нет;
  - защита действует **только** против «бан навсегда»: таймауты любой длины применяются к
    защищённым как настроено, без подтверждения;
  - пока случай в очереди, бот **не удаляет и не маскирует сообщение и не даёт таймаут**
    (осознанный выбор владельца). **Цена, записана честно:** нарушение защищённого зрителя
    остаётся видимым в чате и в оверлее до решения владельца;
  - очередь и «Разбанить» — **только в панели и только у владельца**: без модераторского сайта,
    без всплывашек (не пересекаться с Q24), без автоматической отмены наказаний ботом;
  - нерешённый случай закрывается автоматически через **30 дней** с пометкой «не подтверждено,
    закрыт по сроку»; запись остаётся в журнале;
  - статусы записи журнала: применено / ждёт подтверждения / отменено владельцем / закрыто по сроку.
- **Что уже будет готово к старту Q26 (сделано в Q01, шаг C2):** таблица `moderation_protected`
  (per-канал список защищённых), функции `list_protected`/`add_protected`/`remove_protected`/
  `is_protected`, константа `PROTECTED_ROLES` (streamer/broadcaster/mod/moderator/editor/staff/admin;
  **vip и subscriber не входят** — они защищаются только ручным списком), колонки
  `requested_action`/`duration_sec`/`role` в `moderation_pending`, `maybe_punish()` со статусами
  `applied`/`deferred`/`skipped`. Значит Q26 = **журнал + UI** (вкладка «Модерация» в карточке
  канала, очередь с решением «забанить / не наказывать», редактор списка защищённых, кнопка
  «Разбанить» через `twitch_helix.unban_user`, автозакрытие случаев старше 30 дней), а не движок.
- **Агенту:** `app/moderation.py` (защиту и постановку в очередь делает движок из Q01 — здесь
  хранение и выдача; **очередь подтверждения уже существует** — `timeout_policy` auto/ask,
  `maybe_timeout`, `list_pending_timeouts`, `record_timeout_decision`: расширяем её, а не
  строим вторую), новый `app/moderation_journal.py` + новый `app/moderation_journal_routes.py`
  (one-line `include_router` в `app/server.py`), `app/twitch_helix.py` (новый `unban_user` —
  `DELETE /moderation/bans`, все три ID в **query**-параметрах, успех = 204, 400 «user is not
  banned» — показывать как «уже не забанен», а не как ошибку), `templates/partials/channels.html`,
  `static/app/19_channels_bulk.js`, `static/app/08_providers_moderation.js`, `static/app.js`
  (i18n RU/EN/UA точечно) · тесты: новые `tests/test_moderation_journal.py` (журнал, статусы,
  автозакрытие через 30 дней, автоматическая защита модератора, постановка в очередь без
  наказания), `tests/test_moderation_protected_list.py` (per-канал список, отсутствие общего,
  unban через Helix-мок), `tests/channel_moderation_ui.test.js` (jsdom: вкладка, очередь, кнопка
  «Разбанить») + повторный прогон `tests/test_moderation.py`, `tests/test_moderation_action_ext.py` ·
  миграция: новые таблицы через `moderation_journal.ensure_schema()` одной строкой из `init_db()`;
  legacy-строки не трогаем; **бэкап `data/bot.db`** до добавления таблиц · зависит: Q01, Q02,
  `DEC-OWNER-014`. **Не делать:** всплывашек о новых случаях, доступа к очереди с
  модераторского сайта, автоматической отмены наказаний.

---

# DIRECTOR-LIVE — статус ⏳

Инженерная часть DIR-LIVE-00…09 закрыта полностью. Живая приёмка DIR-LIVE-10 на машине
владельца 11–12.09 прошла в большом объёме; полный журнал с доказательствами — в архиве
([docs/archive/PLAN_TODO_2026-09-13-full-before-rewrite.md](docs/archive/PLAN_TODO_2026-09-13-full-before-rewrite.md),
раздел DIR-LIVE-10).

**Принято вживую:** replay 4×6/6 на `custom:demo_provider + gpt-5.6-luna` (единственная модель из 6
проверенных, промпт v3); реальные источники (vision по кадрам another_channel, Whisper, IRC обоих
ботов без реконнектов); полный цикл сессии warming→suggest; отказоустойчивость (source_loss →
автопауза → resume, Emergency → fence → recovery после рестарта); **Twitch send 12.09** — 3
сообщения отправлены и приняты, бюджет ≤5 соблюдён, Stop чистый, конфиг возвращён в suggest;
ACCEPT-01 browser-часть (RU/EN/UA, mobile, 974 контрола с доступными именами); ночной
training-прогон с разбором очереди suggest (промпт v2 принят владельцем: «неплохо»); 5 живых
дефектов починены в той же сессии (коммиты `aa9dff3`, `2905a84`, `c879418`, `abfbd28`,
`e305187`), 149 director-тестов зелёные.

**Реестр дефектов приёмки 11–12.09** (suggest не блокируют). **Вердикт владельца 13.09 —
`DEC-OWNER-013`:** DEF-06, DEF-02, DEF-03 взяты в работу и идут сразу после Q01–Q04 (в этом
порядке); DEF-01 взят, но встаёт в самый конец всей очереди; DEF-04, DEF-05 и CAND-01 отложены
без срока — в работу молча не брать.

| ID | Дефект | Статус | Указатели и примечание |
|---|---|---|---|
| DEF-01 | Аудио-цикл (Whisper на CPU, 45–90 с) сериален с кадровой петлёй | ✅ готово 13.09 | **Готово 13.09 (DEF-01a, коммит `81808f3`):** в `StreamVisionManager._loop` (`app/stream_vision.py`) захват аудио вынесен в отдельную задачу per (account, channel): тик запускает `_capture_audio` фоном и сразу планирует следующий интервал — кадры и цикл больше не ждут окончания Whisper; back-pressure — пока предыдущая аудио-задача в полёте, тик пропускается (задачи не копятся); `stop()` и отмена цикла дочищают аудио-задачу. **DEF-01b приёмка:** новые `tests/test_stream_vision_audio_task.py` (3: кадры не блокируются, back-pressure, stop отменяет) + смежные сьюты `test_stream_vision` (12), `test_stream_vision_v102`, `test_v104_realtime_context`, `test_stream_source_custom`, `test_attention_budget`, `test_v10_4_1_presets_lastobs` (55 суммарно) — зелёные; потребители наблюдений (`director.py:1201/1239/1377`, `chat_analyzer.py:1160/2184`, `routes.py:1769/1803`) только читают `_last_observation`, `_store_observation` не имеет `await` внутри — разнос аудио/кадров гонок не создаёт |
| DEF-02 | Ошибка провайдера глотается без лога | ✅ готово 13.09 | В `app/director.py` 14 блоков `except Exception`, большинство без лога (строки 473, 486, 1434, 1481, 1676, 1913, 2250, 2313, 2327, 2348, 2461, 2714). Фикс: лог + проброс ошибки в audit/status. **Готово 13.09:** `generate_plan` логирует тип И сообщение исключения провайдера (раньше только тип, `from None` рвал цепочку) и не-ok ответ — с payload `result.error`; пауза по ai_errors пишет `last_error` в audit; «глухие» except-блоки (коммит артефакта, abort_asset, reaction_level, source_refresher) получили логи причины. Тесты: новый `tests/test_director_provider_errors.py` (3) — зелёные; director-сьюты (78 суммарно) — зелёные |
| DEF-03 | `test_connection` не поддерживает `custom:*` | ✅ готово 13.09 | `app/ai_service.py:1100` — ветки по точным именам (`openrouter`/`gemini`/`openai`/`anthropic`/`custom`/`ollama`), для `custom:<имя>` fallthrough. Вызовы: `app/routes.py:1385`, `app/routes.py:1625`. Мешает проверять `custom:demo_provider` — провайдер, на котором принят Режиссёр. **Готово 13.09:** в `test_connection` добавлена ветка `custom:<имя>` — пинг первой chat-моделью именованного провайдера через `_openai_chat` (base_url/api_key из кэша `custom_providers`); отдельные ошибки для «not found» / «no base URL» / «no chat model» / пустого ответа; вызовы `routes.py` трогать не пришлось — чинится на уровне `ai_service`. Тесты: `tests/test_providers_direct.py` +4 — зелёные; смежные `test_provider_settings_api`, `test_p1_custom_providers` — зелёные (40 суммарно) |
| DEF-04 | `GET /status` показывает `ai:false` между планами | ✅ готово 14.09 | Закрыт пунктом **Q29** (коммит `ac06a56`): трёхсостоянийный статус «работает / пауза / ошибка» с `last_error` из audit; живая проверка — ⏸ |
| DEF-05 | Гигиена docs-registry (~22 md из снимка 04–11.09) | ⏸ отложен | Частично снят `DEC-OWNER-012`: md-тестов нет, `scripts/check_md_links.py` — ручная команда. Подтверждено владельцем 13.09 (`DEC-OWNER-017` п.15) |
| DEF-06 | Часть Director-строк — RU-fallback в UA | ⏳ статическая часть готова 13.09, рантайм-проверка ⏸ | Баг по R-UI1 (`docs/PRODUCT_RULES.md` §2), а не улучшение. **Диагностика 13.09:** статические словари полны — в `static/app/20_director.js` ru/en/ua совпадают по всем блокам (81/9/3/1/14/5 ключей), хардкода RU вне словарей нет; в `static/app/25_director_storage.js` хардкод «УДАЛИТЬ» на строках 80, 138, 141 — его видно и в EN, и в UA. Значит остальные случаи приходят из рантайма/данных: собрать их можно, открыв страницу Режиссёра в UA (browser-шаг — нужно «поехали» владельца, `DEC-OPS-001`) или подняв журнал приёмки в архиве. **Статическая часть готова 13.09:** хардкод «УДАЛИТЬ» в `25_director_storage.js` локализован — EN «Type DELETE», UA «Введіть ВИДАЛИТИ»; слово-подтверждение принимается на трёх языках (`_directorDeleteConfirm`), на бэкенд всегда уходит канонический sentinel «УДАЛИТЬ» (контракт `director.delete_session_evidence` не меняется). Тесты: `tests/director_storage_ui.test.js` — 10 зелёных, включая 3 новых DEF-06 |
| CAND-01 | Live-отправленные реакции нельзя отклонить в негативные примеры (очередь ревью содержит только suggest-планы) | ✅ готово 14.09 | Закрыт пунктом **Q30** (коммит `fbc7d2d`): секция «Отправленные вживую» с одобрением/отклонением, только реально отправленные тексты; проверка в панели — ⏸ |

- [ ] **Остаток DIR-LIVE-10 (⏸ ждёт владельца):** OBS/CEF visual composition и TTS/audio
      single output при живом OBS. obs-websocket уже включён в конфиге OBS владельца (бэкап
      `global.ini.bak-accept01`, пароль в `/tmp/director-live10/obs_ws_password`, не в git) —
      тесты (скриншоты рендера OBS, запись клипов для TTS/Soundboard через ffmpeg) агент
      выполняет сам, владельцу нужно только запустить OBS. Отдельный test_channel-сценарий больше
      не требуется: Twitch send-транспорт принят вживую 12.09.

Критерий закрытия DIRECTOR-LIVE: закрыт этот остаток; полная спецификация
([docs/specs/DIRECTOR.md](docs/specs/DIRECTOR.md)) сопоставлена с реализацией и
доказательствами.

# MODSITE — статус ⏸

MOD-00…22 инженерно закрыты (83 профильных теста `tests/test_moderator_site_*.py` зелёные),
MOD-23 browser-приёмка пройдена на fake backend 11.09 (`moderator-site/ACCEPTANCE.md` §20),
MOD-18 owner UI приёмка — 11.09 (§22). Полная документация — [`moderator-site/`](moderator-site/README.md).

- [ ] MOD-24 Twitch/OBS/device-приёмка — **ждёт владельца** (`moderator-site/ACCEPTANCE.md` §21):
      настоящие Twitch/OBS/устройство, только по явному разрешению (`DEC-OPS-001`).
- [ ] Публичный запуск сайта (домен/hosting) — отдельное решение владельца.

---

# Ждём владельца (агент не исполняет)

Панель 12.09 поднята: PID 281409, `http://127.0.0.1:8000`, лог `/tmp/server_v12.log`.
Whisper уже установлен в venv панели (`openai-whisper 20250625`, `torch 2.13.0`), ffmpeg и
pactl на месте, beep-sink `input.bot_beep_out` существует — установка не требуется.

- [ ] **DIR-LIVE-10** — запустить OBS для остатка приёмки (OBS/CEF + TTS/audio), см. выше.
- [ ] **DEF-01…DEF-06 / CAND-01** — решить по каждому: брать в работу, отложить или закрыть
      «не чиним» (таблица в разделе DIRECTOR-LIVE). Отдельно обратить внимание на **DEF-06** —
      это баг по R-UI1, а не улучшение.
- [ ] **MOD-24** — живая приёмка модераторского сайта (`moderator-site/ACCEPTANCE.md` §21).
- [ ] **D1** — проверить смену роли: lurker → модератор применяется сразу и снимает
      «Только наблюдает» (фикс `3e0cdd3`; раньше мешал незапущенный рестарт).
      Тумблер живёт в `templates/partials/bots.html:126` → `saveQuickObservation()` из
      `static/app/11_brain_v16.js` — см. мины в Q19.
- [ ] **Стоп** — кнопка Стоп у включённого бота больше не даёт «Ошибка: OK» (`3e0cdd3`).
- [ ] **H1** — beep-конвейер вживую: пипы реально слышны, статус в UI честный
      (не вечный pass-through). Инженерная часть — пункт **Q25**.
- [ ] **A4** — живой прогон добавления ботов к каналу test_channel (streamer_lurker/streamer_director):
      нужен реальный IRC (`DEC-OPS-001`). Инженерная часть — пункт **Q07(б)**.
- [ ] **Q13/C5** — живая проверка реактивного блюра: нужен browser/OBS. Инженерная часть — **Q13**.
- [x] **Q05** — ✅ вердикты подтверждены владельцем 13.09 (`DEC-OWNER-016`); записи о блокировке
      Q09/Q10/Q15/Q16/Q18 устарели — эти пункты исполнены или открыты по зависимостям.
- [ ] **Q01-скоуп** — переавторизовать токены ботов: скоуп `moderator:manage:banned_users`
      **уже добавлен в код** (коммит `bd3b036`), но существующие токены его не содержат, поэтому
      бан и таймаут вживую вернут 401/403, пока токены не перевыпущены (см. предусловие Q01).
      Панель перезапустить после этого обязательно — в работающем процессе старый код.
- [x] **Q01-C2** — ✅ решено 13.09 вечером (интервью, `DEC-OWNER-017`): бот **молчит** на
      сообщение нарушителя, пока случай защищённого в очереди подтверждения (вариант (а)
      подтверждён как финальный, не «по умолчанию до ответа»).

Правило: живой остаток пункта ведётся **только здесь**, в самой очереди — одна ссылка на этот
раздел. Иначе статус расходится в двух местах (так было с A4/Q07 и H1/Q25).

# Решения владельца

Ответы 12.09.2026 и интервью 13.09.2026 записаны в [docs/DECISIONS.md](docs/DECISIONS.md),
с расшифровкой дословных формулировок:

- `DEC-OWNER-001` — параллельные сессии отменены; одна папка, одна ветка, один план.
- `DEC-OWNER-002` — у бота своё, у канала своё; границы допустимого глобального.
- `DEC-OWNER-003` — база знаний остаётся per-бот, из «Мозга» убирается.
- `DEC-OWNER-004` — запретки per-канал плюс базовый пресет Twitch.
- `DEC-OWNER-005` — beep-настройка у бота-модератора.
- `DEC-OWNER-006` — массовая смена канала: делать, после фильтров A1.
- `DEC-OWNER-007` — шифрование токенов не настраиваем, loopback достаточно.
- `DEC-OWNER-008` — исторический стэш 28.08 сохранён патчем в архив и удалён.
- `DEC-OWNER-009` — test_bot (id=1) остаётся выключенным.
- `DEC-OWNER-010` — один список ботов с фильтрами вместо секции «Lurkers»
  (отменяет `DEC-LURKER-002`).
- `DEC-OWNER-011` — контрольное сообщение при добавлении бота опционально, по умолчанию
  выключено (уточняет `DEC-BULK-005`, `DEC-BULK-008`).
- `DEC-OWNER-012` — тестов на md-файлы нет: `tests/test_docs.py`,
  `tests/test_moderator_site_docs.py`, `tests/test_plan_file_zones.py` удалены 13.09;
  `scripts/check_md_links.py` остался ручной командой.
- `DEC-OWNER-013` — старт исполнения: блок модерации Q01→Q04, затем Q26; DEF-06, DEF-02, DEF-03
  взяты в работу (сразу после Q01–Q04), DEF-01 — в конец всей очереди; DEF-04, DEF-05, CAND-01
  отложены без срока (интервью 13.09).
- `DEC-OWNER-014` — «бан навсегда» только с предохранителем: защищённые = модераторы/редакторы
  (автоматически) + ручной per-канал список; защита только от вечного бана; срабатывание на
  защищённом → наказание не применяется, случай в очередь подтверждения, сообщение не
  удаляется; очередь и «Разбанить» — только у владельца в панели; нерешённый случай закрывается
  через 30 дней; журнал наказаний — вкладка «Модерация» в карточке канала (интервью 13.09).
- `DEC-OWNER-015` — скоуп `moderator:manage:banned_users` добавляется в `DEFAULT_SCOPES`, у бота
  появляется честный статус «нет прав модерации → переавторизовать»; переавторизация токенов —
  шаг владельца; до неё бан/таймаут помечены недоступными, а не падают молча. Там же — верный
  контракт Helix Ban User и поправка: `DELETE /moderation/bans` это Unban, а не бан (интервью 13.09).

## Открытые вопросы (агент не угадывает — ждёт ответа)

- ~~**Q01-C2, ответ бота на отложенное наказание.**~~ ✅ **Решено 13.09 вечером:** вариант (а)
  подтверждён владельцем — бот молчит, пока случай защищённого зрителя в очереди
  подтверждения (ни наказания, ни ответа; текущее поведение ветки `block/timeout` в
  `app/chat_analyzer.py` — финальное, записано в `DEC-OWNER-017`).
- ~~**Q05, вердикты инвентаризации**~~ — ✅ подтверждены 13.09 (`DEC-OWNER-016`).

_Открытых вопросов на 13.09 (вечер) не осталось._

# Необязательно / потом

Возвращать только по явному запросу владельца:

- OPTIONAL-03, OPTIONAL-04, OPTIONAL-06, OPTIONAL-09, внешние gates, статусы OmniVoice и
  voice-live, `DEC-CLEANUP-002` (оставшийся cleanup не выполняем) — в архиве
  [docs/archive/PLAN_TODO_2026-09-12.md](docs/archive/PLAN_TODO_2026-09-12.md).
  Статусы OPTIONAL-03…10 разобраны по одному с владельцем 13.09 (`DEC-OWNER-017` п.14–22):
  OPTIONAL-03/04/06/09 — отложены, OPTIONAL-07 — ⏸ (установка вручную владельцем),
  OPTIONAL-05 → **Q31**, OPTIONAL-10 → **Q32**, OPTIONAL-08 — ✅ закрыт как реализованный.
- **CAND-01** — 🔥 взято в работу → **Q30** (13.09, `DEC-OWNER-017` п.17).
- «TTS-моменты в OBS» — отложены владельцем, без запроса не возвращать.

# Справка

- Python-тесты: `~/.local/bin/pytest tests/test_<модуль>.py -q`; UI-тесты: `node tests/<имя>.test.js`.
  Схема БД в тестах создаётся `init_db()`; `chat_log` имеет колонку `author` (не username);
  beep-тестам нужна `beep_guard.ensure_schema()`.
- Тесты живут на системном python (`~/.local/bin/pytest`), панель — в `venv/`: пакеты в venv
  не видны тестам и наоборот. Полный suite ~20 минут и тянет torch — только по явному
  «поехали» владельца (`DEC-OPS-001`).
- Правки `static/app.js` — точечные (i18n-словари RU/EN/UA в трёх блоках); новые эндпоинты —
  в своём `app/<фича>_routes.py` плюс one-line `include_router` в `app/server.py`.
- После правки Python-кода панель перезапускать: в работающем процессе остаётся старый код
  (именно так «не работала» смена ролей в D1).
- panel-labels режет регион widgets по маркеру `<!-- Решение владельца 31.08` → конечный
  маркер `<details ... data-widget-group="catalog">`.
- **Тестов на md-файлы в проекте нет** (`DEC-OWNER-012`): структуру плана ничто автоматически
  не проверяет — при переписывании разделы нельзя терять молча (12.09 из плана так пропали
  `## DIRECTOR-LIVE` и `## MODSITE`, их восстанавливали из архива).
- Обязательные разделы этого файла (соглашение): `# Очередь Q01–Q33`, `# DIRECTOR-LIVE`,
  `# MODSITE`, `# Ждём владельца`, `# Решения владельца`, `# Необязательно / потом`,
  `# Справка`.
- Ссылки и якоря в активных документах проверяются вручную: `python3 scripts/check_md_links.py`
  (реестр 22 файлов в `ACTIVE_DOCS`; новый `.md` вне `docs/archive/` добавлять туда же).
- **Чеклист «ГОТОВО» — `docs/PRODUCT_RULES.md` §3**: пункт очереди не считается закрытым, пока
  не выполнены его пункты (focused-тесты, i18n на 3 языка по R-UI1, browser/OBS-приёмка или
  честно записанный pending, коммит). §4 того же файла — когда агент обязан спросить владельца,
  а не «сделать как понял».
- Реестр дефектов живой приёмки (DEF-01…DEF-06, CAND-01) живёт в разделе DIRECTOR-LIVE; новые
  дефекты добавлять туда же с очередным ID, а не прозой в абзац.
- Состояние: `git log --oneline -10` здесь же.
