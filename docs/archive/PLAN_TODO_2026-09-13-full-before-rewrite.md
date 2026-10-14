# PLAN_TODO — единственный активный план (ревизия 12.09.2026, ночь)

> Прошлые планы целиком в архиве:
> [docs/archive/PLAN_TODO_2026-09-12-evening.md](docs/archive/PLAN_TODO_2026-09-12-evening.md)
> (история DIR-LIVE, WIDGETS-UI, BC, AI-BUDGET, PROMPT-BASE, BUGS-LOG, HANDOFF),
> [docs/archive/PLAN_TODO_2026-09-12.md](docs/archive/PLAN_TODO_2026-09-12.md) и
> [docs/archive/PLAN_DONE_2026-09.md](docs/archive/PLAN_DONE_2026-09.md) (закрытые этапы).
> Решения владельца — в [docs/DECISIONS.md](docs/DECISIONS.md); в плане остаются только ID
> с расшифровкой в журнале.

## Как работать

- **Одна папка, одна ветка, один план** (`DEC-OWNER-001`): работа в `twitch-ai-bot/`,
  параллельные агентские сессии и ветки `session/*` отменены. Папки `session-*/` вне проекта —
  исторические копии: не удалять и не редактировать.
- Каждый пункт = маленький коммит; зелёные owning-тесты перед коммитом; `git diff --check`.
- Тесты — только профильные: `~/.local/bin/pytest tests/test_<модуль>.py -q` (полный suite
  ~20 минут и тянет torch — только по явному «поехали» владельца, `DEC-OPS-001`).
- Production БД `data/bot.db` не трогать без явного запроса владельца; тесты работают в tmp-БД.
- **Миграция обязательна** для любого пункта, меняющего схему или скоуп: сначала бэкап
  `data/bot.db`, затем `<фича>.ensure_schema()` точечным вызовом из `init_db`. Legacy-строки
  читаются и помечаются, не удаляются; owning-тест обязан показать, что старая строка работает.
- Токены/ключи — только в память процесса или шифрованную БД, в git не класть
  (шифрование на реальной панели осознанно не включаем — `DEC-OWNER-007`).
- Не запускать browser/OBS/реальные provider-вызовы без отдельного разрешения владельца
  (исключение — когда владелец сам дал ключ/токен и попросил проверить).
- Не удалять молча public URLs, legacy DB rows и чужую работу.
- Панель: `bash start_bg.sh --skip-install`, лог `/tmp/server_v12.log`, адрес
  `http://127.0.0.1:8000`. После правки Python-кода панель **перезапускать**: в работающем
  процессе остаётся старый код (именно так «не работала» смена ролей в D1).

## Формат пункта (обязателен для каждого)

Пункт не считается готовым к исполнению без пяти строк:

- **Готово когда** — проверяемый критерий приёмки: что увидит владелец, а не «сделано».
- **Файлы** — реальные пути (карта: [FILE_ZONES.md](FILE_ZONES.md)).
- **Тесты** — owning-тесты, которые запускаются перед коммитом.
- **Миграция** — что происходит со старыми строками/настройками (или «нет»).
- **Зависит от** — ID пунктов и решений, без которых начинать нельзя (или «—»).

Размер: **S** — до часа, **M** — часть дня, **L** — день и больше (дробить на коммиты).

## Что уже готово (не переделывать)

Кратко; доказательства и коммиты — в архивных планах:

- Панель целиком: боты/каналы (CRUD каналов, пер-виджетные каналы, перенос каналов между
  ботами), виджеты (группы, превью-лайтбокс, биндинги, настройки с карточки), Режиссёр
  (offline-инженерия DIR-LIVE-00…09 + live-приёмка 11–12.09, Twitch send принят вживую на
  another_channel), Мозг (общая база запреток PB-1/2), переключатели внимания бота AB-1…3
  (vision/hearing/chat_ai), эмодзи-декор исходящих (PB-3), bugfix-пакет 12.09 (BUG-1…BUG-6,
  Стоп, смена роли, дубль-эмодзи).
- Боты в реальной панели: streamer_director (режиссёр, id=3), streamer_lurker (lurker, id=4), канал test_channel,
  провайдер `custom:demo_provider` + `gpt-5.6-luna` (проверен вживую, 2.1 c). test_bot (id=1) выключен
  и остаётся выключенным (`DEC-OWNER-009`).
- Модераторский сайт: MOD-00…MOD-22 инженерно закрыты, MOD-23 browser-приёмка на fake backend
  пройдена 11.09; остаток — MOD-24 (раздел MODSITE ниже).

---

# Очередь — одна сквозная

«Партии» запросов 12.09 (2, 3, 4) — исторические метки, не отдельные очереди: все их пункты
сведены в один список. Прежние ID (A1…H6, M1…M4, I1, B1, C0…C7, D1…D2, E1…E4, F1…F4, G1…G8)
сохранены в заголовках, чтобы старые ссылки и коммиты находились.

Принцип всех партий — **«просто и понятно»**: каждая настройка объясняется одним предложением;
если для понимания нужен абзац — переделываем. Архитектурный принцип — `DEC-OWNER-002`:
**у каждого бота своё, у каждого канала своё, ничего не пересекается.**

### Q01 · M1 — Расширенные действия правил модерации · M

- Готово когда: у правила выбирается действие «по тяжести / маскировать / блокировать /
  таймаут 10 мин / 1 час / 1 день / 1 неделя / 2 недели (1209600 с) / бан навсегда», движок
  реально его применяет, а бан уходит в Helix (сейчас в `app/twitch_helix.py` есть только
  `timeout_user` через POST `/moderation/bans` — нужен `ban_user` через DELETE).
- Файлы: `app/moderation.py`, `app/routes_modpanel.py`, `app/database.py` (колонка `action_ext`
  в `moderation_rules`), `app/twitch_helix.py`, `static/app/08_providers_moderation.js`.
- Тесты: `tests/test_moderation.py` + новый `tests/test_moderation_action_ext.py`
  (parse action_ext, таймауты всех длительностей, ban через Helix-мок).
- Миграция: `action_ext` добавляется с default NULL; NULL = прежнее поведение лестницы
  (warn→t1→t2→ban). Существующие строки правил не переписываются.
- Зависит от: —

### Q02 · M2 — Политика по категориям в роли модератора · M

- Готово когда: в настройках роли «модератор» видна таблица «категория → действие»
  (insult/hate/threat/sexual/spam), она применяется в `check_message` поверх severity,
  владелец её правит сам.
- Файлы: `app/moderation.py`, `app/bot_roles.py`, `app/database.py` (`category_policy`),
  `static/app/08_providers_moderation.js`, `static/app/06_roles.js`.
- Тесты: `tests/test_moderation.py`, `tests/test_bot_roles.py`, `tests/test_roles_style.py`,
  `tests/test_p8_c8_roles_2_0.py`.
- Миграция: `category_policy` хранится в настройках роли; при отсутствии — поведение как сейчас.
- Зависит от: Q01 (единый формат действия).

### Q03 · M3 — База правил модерации: per-канал + пресет Twitch · M

- Готово когда: у канала есть редактируемый список правил модерации; есть базовый пресет
  запретов Twitch, из которого канал стартует; правила применяются **только** ботам с ролью
  «модератор»; порядок применения — пресет/база канала, затем per-бот правила.
- Файлы: `app/moderation.py`, `app/moderation_routes.py`, `app/moderation_dicts/`,
  `app/database.py`, `static/app/08_providers_moderation.js`, `templates/partials/channels.html`.
- Тесты: новый `tests/test_moderation_base_rules.py` (пресет только для модераторов,
  per-бот правила переопределяют базу, не-модератор не наказывает).
- Миграция: глобальная таблица `moderation_base_rules` **не создаётся** — модель per-канал
  + пресет по `DEC-OWNER-004`. Существующие per-бот `moderation_rules` остаются как есть.
- Зависит от: Q01, Q02, `DEC-OWNER-004`.

### Q04 · M4 — Сквозной UI-тест редактора модерации · S

- Готово когда: jsdom-тест открывает редактор правил и категорий и проверяет parse `action_ext`,
  category override, применение базы только модераторам и ban через Helix-мок.
- Файлы: новый `tests/moderation_rules_ui.test.js`, `static/app/08_providers_moderation.js`.
- Тесты: `node tests/moderation_rules_ui.test.js` + тесты Q01–Q03.
- Миграция: нет.
- Зависит от: Q01–Q03.

### Q05 · I1 — Инвентаризация глобальных настроек · M

- Готово когда: в этом плане есть таблица «настройка → где хранится → вердикт (удалить /
  к боту / к каналу / остаётся глобальной по исключению)», владелец подтвердил вердикты,
  а Q09/Q10/Q15/Q16/Q18 ссылаются на неё.
- Файлы: `PLAN_TODO.md` (таблица), `app/database.py` (`get_setting`/`set_setting`, таблица
  `settings`), `templates/partials/settings.html`, `static/app/04_chat_settings.js`,
  `static/app/12_dashboard_extras.js`.
- Тесты: `tests/test_provider_settings_api.py`, `tests/test_p1_custom_providers.py`;
  ссылки в этом файле проверить вручную: `python3 scripts/check_md_links.py`.
- Миграция: на этапе инвентаризации — нет; перенос значений делается в пунктах-исполнителях.
- Зависит от: `DEC-OWNER-002` (что вообще может остаться глобальным).

### Q06 · C3 — Убрать блок ручных команд виджетов · S

- Готово когда: в «Виджетах» нет блока «Все команды изменения виджетов во время эфира собраны
  здесь» (⭐ Sub-цель / 🔔 Счётчики / ⏳ Countdown) — `templates/partials/widgets.html:20-22`;
  сами виджеты и их карточки остаются нетронутыми.
- Файлы: `templates/partials/widgets.html`, `static/app/07_widgets.js`,
  `static/app/21_panel_labels.js`, `static/app/24_dynamic_i18n.js`, `static/app.js`
  (i18n-словари RU/EN/UA — точечно).
- Тесты: `tests/test_widgets_ui_cards.py`, `tests/widget_admin_forms_ui.test.js`,
  `tests/test_o7_widget_admin_forms.py`; grep остаточных ссылок
  `waSubDelta`/`waCounterManualList`/`waCdAction`.
- Миграция: нет (убирается только UI-блок, данные виджетов не трогаются).
- Зависит от: —

### Q07 · A2 + A4 — Добавление ботов к каналу: проверка без сообщения + диагностика · M

- Готово когда: (а) в диалоге добавления есть чекбокс «контрольное сообщение», по умолчанию
  ВЫКЛ, а проверка без него = OAuth-валидация токена + IRC join канала; (б) отказ добавления
  ботов к каналу воспроизведён на test_channel (streamer_lurker/streamer_director), найден, починен, и владельцу
  сообщено, что именно было сломано.
- Файлы: `app/bot_check.py`, `app/bot_check_routes.py`, `app/bulk_channels_routes.py`,
  `static/app/19_channels_bulk.js`.
- Тесты: `tests/test_bot_check.py`, `tests/test_bot_check_routes.py`,
  `tests/test_bot_check_ui.py`, `tests/test_bulk_channels.py`, `tests/test_bulk_channels_ui.py`.
- Миграция: нет; изменение дефолта (чекбокс ВЫКЛ) зафиксировано `DEC-OWNER-011`.
- Зависит от: `DEC-OWNER-011`, `DEC-BULK-005`, `DEC-BULK-008`; живая часть — разрешения
  владельца на реальный IRC (`DEC-OPS-001`).

### Q08 · A1 + A3 + BC-2 — Фильтры ботов, «выбрать всех» по ролям, массовая смена канала · L

- Готово когда: (а) в «Ботах» один список без принудительной секции «👀 Луркеры», есть фильтры
  по роли (болтуны/люркеры/модераторы/режиссёры) и по каналу, они запоминаются в localStorage,
  а «только модераторов» и «боты на test_channel» достижимы в два клика; (б) в диалоге добавления
  боты сгруппированы по ролям и у группы есть кнопка «выбрать всех»; (в) массовая смена канала
  для нескольких ботов работает.
- Файлы: `static/app/03_bots.js`, `static/app/05_bots_tabs.js`, `static/app/19_channels_bulk.js`,
  `templates/partials/bots.html`, `app/bulk_channels_routes.py`, `app/bot_roles.py`.
- Тесты: `tests/test_bot_roles.py`, `tests/role_visibility_ui.test.js`,
  `tests/panel_lurker_ui.test.js`, `tests/test_bulk_channels.py`, `tests/test_bulk_channels_ui.py`.
- Миграция: сохранённые в localStorage старые ключи вида не ломают список (чтение с дефолтом).
- Зависит от: `DEC-OWNER-010` (отменяет секцию «Lurkers» из `DEC-LURKER-002`),
  `DEC-OWNER-006`, `DEC-LURKER-001`.

### Q09 · B1 + G1 + G2 + G3 — Карточка канала: инфо о стримере, lore, сводки · L

- Готово когда: карточка канала в секции «Каналы» открывает редактор инфо о стримере (bio,
  игры, стиль, любит/не любит), фактов lore и настроек сводок «как прошёл стрим»
  (вкл/выкл/язык/период); вписанное видно в превью/профиле этого канала, у другого канала —
  своё; источник данных один, а в «Мозге» эти редакторы исчезают.
- Файлы: `templates/partials/channels.html`, `static/app/19_channels_bulk.js`,
  `app/streamer_profile.py`, `app/routes_streamer_profile.py`, `app/routes_global_profile.py`,
  `app/streamer_lore.py`, `app/summarizer.py`, `app/routes_ai_summary.py`,
  `templates/partials/brain.html`, `static/app/09_brain_p3.js`, `static/app/11_brain_v16.js`.
- Тесты: `tests/test_brain_channel_scope.py`, `tests/test_ai_summary.py`,
  `tests/test_channel_admin.py`, новый `tests/test_channel_card_profile_ui.py`.
- Миграция: данные уже per-channel — `streamer_profile` (account_id, channel), `streamer_lore`
  (channel + скоуп `*`), `summarizer` (account_id, channel; `channel=''` — legacy). Скоуп
  «все каналы» убирается из UI, но строки `*`/`''` продолжают читаться как fallback и не
  удаляются.
- Зависит от: Q05, `DEC-OWNER-002`.

### Q10 · C0 + C1 — Channel-first скоуп виджетов, `widget_scope_required` невидима · L

- Готово когда: в «Виджетах» сверху один селектор канала; всё ниже (превью, настройки, OBS-URL)
  показывает данные этого канала; без выбранного канала — демо-данные, а не ошибка; строка
  `widget_scope_required` не показывается пользователю ни в одном месте; пер-виджетный override
  остаётся редким исключением, а не основой.
- Файлы: `static/app/07_widgets.js` (`waWidgetStateUrl`, строка ~65 — бросает исключение,
  которое тостится), `static/app/13_widgets_session.js`, `templates/partials/widgets.html`,
  `app/widget_channel_scope.py`, `app/widgets.py` (строки 1907, 5934),
  `app/soundboard_routes.py` (41), `app/soundboard_library.py` (295, 325).
- Тесты: `tests/test_widget_channel_scope.py`, `tests/test_widget_binding_scope_ui.py`,
  `tests/widget_scope_override.test.js`, `tests/test_widget_preview_coverage.py`,
  `tests/test_p0_widget_migrations.py`, `tests/test_widget_public_smoke.py`.
- Миграция: per (бот × канал) настройки в БД остаются основой; существующие override-значения
  в localStorage читаются как раньше; демо-режим в БД не пишет.
- Зависит от: Q05, `DEC-OWNER-002`.

### Q11 · C2 + D2 — Биндинги с нуля · L

- Готово когда: правило читается как «КОГДА (команда/событие/хоткей) → ТОГДА (действие
  конкретного виджета)»; бот подставляется автоматически (модератор-бот этого канала), ручной
  выбор появляется только при двух и более модераторах; у каждого виджета в списке только
  свойственные ему действия; у виджета без биндингов в UI нет ни одного упоминания биндингов;
  старый общий билдер заменён.
- Файлы: `app/widget_bindings.py` (`validate_binding_contract`, `run_binding`,
  `_active_bindings`), `app/widget_bus.py`, `static/app/07_widgets.js`,
  `templates/partials/widgets.html`, `widgets/` (манифесты действий виджетов).
- Тесты: `tests/test_widget_bindings.py`, `tests/test_widget_binding_scope_ui.py`,
  `tests/test_q7_bindings_placement.py`, `tests/test_w6_semantic_bindings.py`,
  `tests/test_s3_hotkey_bindings.py`, `tests/test_roles_hotkeys.py`.
- Миграция: старые биндинги не удаляются — помечаются legacy и читаются новым движком;
  бэкап `data/bot.db` перед изменением схемы; owning-тест на чтение legacy-строки.
- Зависит от: Q10 (скоуп канала), Q05.
- Оговорка: «с нуля» — это новый модуль/билдер, а не перезапись общих файлов: `static/app.js`
  и `app/routes.py` правятся точечно (AGENTS.md §4).

### Q12 · C4 + C7 — Полные карточки виджетов, ничего не спрятано в «прочих» · M

- Готово когда: у каждого виджета полная карточка с рабочим превью (никаких столбцов, в которые
  превью не влезает); где реально не влезает — раскрытие на весь экран или отдельная
  проработанная страница виджета; «Прочие виджеты» ничего не прячут — карточки наравне
  с остальными.
- Файлы: `templates/partials/widgets.html`, `static/app/07_widgets.js`,
  `static/app/21_panel_labels.js`, `static/app.css`.
- Тесты: `tests/test_widgets_ui_cards.py`, `tests/test_widget_preview_coverage.py`,
  `tests/widget_admin_forms_ui.test.js`, `tests/test_widget_theme_cohort_cards.py`,
  `tests/test_widget_extra_widgets.py`.
- Миграция: нет.
- Зависит от: Q06, Q10.

### Q13 · C5 — blur-guard: простая настройка и живая проверка · M

- Готово когда: настройка читается как «Защита: вкл/выкл · Чувствительность · Длительность
  блюра · Своя картинка», остальное спрятано в «Дополнительно»; вживую подтверждено, что
  реактивный блюр срабатывает, либо зафиксировано, почему нет и что именно починено.
- Файлы: `app/blur_guard.py`, `app/blur_guard_routes.py`, `app/obs_blur.py`,
  `widgets/blur-guard-v2/`, `static/app/07_widgets.js`.
- Тесты: `tests/test_widget_blur_guard.py` + новый UI-тест упрощённой формы настроек.
- Миграция: существующие значения настроек отображаются в новых полях через маппинг
  и не сбрасываются.
- Зависит от: Q10; живая часть — разрешения владельца на browser/OBS (`DEC-OPS-001`).

### Q14 · C6 — anime-runner: поднять историю git · S

- Готово когда: либо потерянные настройки найдены в истории (снапшот `e9e2067` и ранее)
  и восстановлены, либо пункт закрыт честным «не восстановить» с перечислением проверенного.
- Файлы: `widgets/anime-runner/`, история git (`git log --all -- widgets/anime-runner`).
- Тесты: `tests/test_widgets_folder.py`, `tests/test_widget_js_syntax.py`.
- Миграция: нет; восстановление только из истории, без перезаписи текущего состояния.
- Зависит от: —

### Q15 · E1–E4 — Провайдеры и модели per-бот · L

- Готово когда: (E1) поля «Общая Vision-модель» в Настройках нет; (E2) у провайдера один список
  моделей с пометкой типа (чат/vision), модели не дублируются между провайдерами — каждая
  уникальна за своим провайдером; (E3) у бота выпадающие списки «чат-модель» и «vision-модель»
  наполняются из моделей его провайдера, ручной ввод строкой убран; (E4) автодобавления Ollama
  в per-бот настройки нет, локальный fallback выключен по умолчанию и включается вручную
  per-бот («резерв: локальная Ollama»), circuit breaker остаётся как защита.
- Файлы: `templates/partials/settings.html` (строка 24 — `globalVisionModel`),
  `static/app/04_chat_settings.js` (328, 330, 869 — `global_vision_override`),
  `app/ai_service.py`, `app/local_fallback.py`, `app/database.py`, `static/app/05_bots_tabs.js`.
- Тесты: `tests/panel_custom_providers.test.js`, `tests/test_p1_custom_providers.py`,
  `tests/test_provider_settings_api.py`, `tests/test_providers_direct.py`,
  `tests/test_p8_c10_custom_providers_merged.py`, `tests/test_director_provider_matrix.py`.
- Миграция: значение `global_vision_override` не удаляется молча — до переноса читается как
  fallback, после переноса в per-бот помечается legacy; бэкап БД; owning-тест «бот без своей
  vision-модели берёт прежнее глобальное значение, после переноса — своё».
- Зависит от: Q05.

### Q16 · F1–F4 — Убрать глобальные рубильники Настроек · M

- Готово когда: (F1) главного рубильника провокаций в Настройках нет — вкл/выкл только у бота
  во вкладке «Характер», без «OFF приглушает»; (F2) вместо помпезной модалки media-share —
  одна короткая строка-подсказка прямо в форме медиа-шары; (F3) глобального TTS-раздела
  в Настройках нет, TTS полностью per-бот (провайдер/голос/события); (F4) «Модератор TTS
  консоль» видна только в настройках бота с ролью «модератор».
- Файлы: `templates/partials/settings.html` (120-122 провокации, 136 TTS-глобально,
  179-181 routing map, 262-263 TTS output), `static/app/12_dashboard_extras.js` (56-65),
  `static/app/04_chat_settings.js`, `app/conflict_provocation.py`, `app/routes_tts_config.py`,
  `app/tts_routing_routes.py`, `app/moderator_console_routes.py`, `static/app/05_bots_tabs.js`,
  `static/app/06_roles.js`.
- Тесты: `tests/test_p6_tts_chat.py`, `tests/test_s6_tts_per_bot.py`,
  `tests/test_tts_duck_settings.py`, `tests/test_o2_tts_status.py`,
  `tests/media_share_disclosure_ui.test.js`, `tests/test_moderator_console_access.py`,
  `tests/role_visibility_ui.test.js`.
- Миграция: сохранённые глобальные значения (provocations master, глобальный TTS) читаются
  как fallback при первом открытии настроек бота, затем помечаются legacy; не удаляются.
  «TTS-моменты в OBS» осознанно отложены владельцем — в план не возвращать без запроса.
- Зависит от: Q05, `DEC-OWNER-002`.

### Q17 · G4 + G5 + G6 — Память о зрителях, предложения по улучшению, KB — per-бот · M

- Готово когда: «Что бот запомнил о зрителях» и «Предложения по улучшению» (фидбек 👍/👎,
  learning) видны во вкладке бота, причём память показывается только если у бота память
  включена; из «Мозга» оба раздела убраны; у KB убран глобальный импорт/экспорт JSON из
  «Мозга», а per-бот вкладка «Knowledge base + Mimicry» и поиск по KB остались.
- Файлы: `static/app/14_brain_memory.js`, `static/app/15_feedback_2908.js`,
  `static/app/05_bots_tabs.js` (строка 779 — KB-вкладка), `app/user_memory.py`,
  `app/routes_user_memory.py`, `app/routes_ai_feedback.py`, `app/learning.py`,
  `app/ai_quality.py` (`score_kb_entry`), `app/routes_ai_quality.py`,
  `templates/partials/brain.html` (строка 153 — KB импорт/экспорт).
- Тесты: `tests/test_p3_memory_scope.py`, `tests/test_ai_feedback.py`, `tests/test_ai_quality.py`,
  `tests/test_ai_quality_api.py`, `tests/test_ai_quality_db.py`, `tests/test_brain_modules.py`,
  `tests/test_s9k_feedback_categories.py`.
- Миграция: строки `streamer_kb` (сейчас 0) и записи памяти/фидбека не удаляются — меняются
  только точки входа в UI.
- Зависит от: `DEC-OWNER-003`.

### Q18 · G7 — Запретки: per-канал плюс базовый пресет Twitch · M

- Готово когда: у каждого канала свой редактируемый список запретных тем; есть базовый пресет
  запретов Twitch, из которого канал стартует и который владелец правит; глобального редактора
  запреток в «Мозге» нет.
- Файлы: `app/routes_prompt_base.py`, `app/chat_prompt_blocks.py`, `app/chat_analyzer.py`,
  `app/brain_preview.py`, `templates/partials/channels.html`, `templates/partials/brain.html`,
  `static/app/11_brain_v16.js`, `static/app/19_channels_bulk.js`.
- Тесты: `tests/test_prompt_base.py`, `tests/test_brain_preview.py`,
  `tests/test_brain_channel_scope.py`, `tests/test_c3_corrections_context.py`.
- Миграция: существующие общие запретки становятся содержимым пресета (не теряются);
  per-канал списки создаются пустыми с наследованием пресета; бэкап `data/bot.db`.
- Зависит от: Q09 (карточка канала как место редактора), `DEC-OWNER-004`.

### Q19 · G8 — Убрать вкладку «Мозг» · S

- Готово когда: пункта «Мозг» нет в навигации; все его разделы переехали (Q09, Q17, Q18);
  у владельца нет ни одной причины открывать «Мозг»; grep по `templates/` и `static/` не даёт
  живых ссылок на удалённую вкладку.
- Файлы: `templates/base.html`, `templates/partials/brain.html`, `static/app/09_brain_p3.js`,
  `static/app/11_brain_v16.js`, `static/app/14_brain_memory.js`,
  `static/app/15_feedback_2908.js`, `static/app/24_dynamic_i18n.js`.
- Тесты: `tests/test_brain_modules.py`, `tests/test_brain_preview.py`,
  `tests/test_brain_channel_scope.py`, `tests/panel_dynamic_i18n.test.js`,
  `tests/panel_accessibility.test.js`.
- Миграция: API/роуты «Мозга» остаются — их читают каналы и боты; убирается только вкладка.
  Данные не удаляются.
- Зависит от: Q09, Q17, Q18. **Точка невозврата:** только после проверки всех трёх.

### Q20 · H2 — Композер чата: бот и канал у кнопки «Отправить» · M

- Готово когда: выбрать бота и канал и отправить — одна связка кликов прямо у кнопки
  «Отправить» (сейчас бот в стороне); селектор канала с поиском и группировкой по ботам,
  видно, на каком боте какой канал.
- Файлы: `templates/partials/chat.html`, `static/app/18_dm_chat.js`,
  `static/app/04_chat_settings.js`, `app/dm_chat.py`, `app/multi_bot_chat.py`.
- Тесты: `tests/test_multi_bot_chat.py` + новый `tests/chat_composer_ui.test.js`.
- Миграция: нет.
- Зависит от: Q08 (переиспользовать общий селектор «бот × канал»).

### Q21 · H3 — Панель Режиссёра внутри бота · M

- Готово когда: отдельной глобальной страницы Режиссёра нет — панель живёт внутри бота с ролью
  «режиссёр» (карточка/вкладка бота), при этом Start/Pause/Resume/Stop, Emergency Stop, Workers,
  конфигурация и storage-панель сохранены полностью.
- Файлы: `templates/partials/director.html`, `templates/partials/bots.html`,
  `static/app/20_director.js`, `static/app/25_director_storage.js`,
  `static/app/05_bots_tabs.js`, `app/director_routes.py`.
- Тесты: `tests/test_director_config.py`, `tests/test_director_storage.py`,
  `tests/test_director_lifecycle.py`, `tests/director_storage_ui.test.js`,
  `tests/director_review_ui.test.js`.
- Миграция: URL/роуты Режиссёра не удалять молча (на них могут быть закладки) — оставить
  редирект на карточку бота; storage/lifecycle контракты не меняются.
- Зависит от: Q08 (группировка ботов по ролям).

### Q22 · H4 — Плотная сетка карточек ботов · M

- Готово когда: в «Ботах» нет разрежённых строк с пустым местом — плотная сетка карточек,
  все действия карточки доступны без лишней прокрутки.
- Файлы: `templates/partials/bots.html`, `static/app/03_bots.js`, `static/app.css`.
- Тесты: `tests/panel_theme_layout.test.js`, `tests/role_visibility_ui.test.js`,
  `tests/panel_accessibility.test.js`.
- Миграция: нет.
- Зависит от: Q08 (фильтры и группировка — одна верстка, не две).

### Q23 · H5 — Сводка в «Обзоре» · M

- Готово когда: сверху «Обзора» видна сводка: сколько ботов, кто к какому каналу подключён,
  роли и живые подключения (мини-таблица или чипы со статусами).
- Файлы: `templates/partials/dashboard.html`, `static/app/02_dashboard.js`,
  `static/app/12_dashboard_extras.js`, `app/ab_dashboard.py`.
- Тесты: `tests/test_ab_dashboard.py`, `tests/panel_analytics_state.test.js` + новый
  `tests/dashboard_overview_ui.test.js`.
- Миграция: нет.
- Зависит от: Q08 (данные о ролях и подключениях берутся из той же модели).

### Q24 · H6 — Тумблер всплывашек (mod-feed и лайв-события) · S

- Готово когда: есть настройка «не показывать всплывашки», состояние хранится в localStorage,
  и попапы не выскакивают, когда она включена.
- Файлы: `static/app/12_dashboard_extras.js`, `app/mod_feed_routes.py`,
  `templates/partials/dashboard.html`, `static/app/24_dynamic_i18n.js`.
- Тесты: `tests/test_mod_feed.py`, `tests/mod_feed_i18n.test.js` + новый UI-тест тумблера.
- Миграция: нет.
- Зависит от: —. Это осознанное глобальное UI-предпочтение владельца —
  исключение 1 из `DEC-OWNER-002`.

### Q25 · H1 — Beep-настройка у бота-модератора · M

- Готово когда: настройка beep-конвейера убрана из вкладки «Чат» и появилась в настройках бота
  с ролью «модератор» (рядом с «Модератор TTS консоль» из Q16); состояние конвейера честно
  показывает работу или pass-through.
- Файлы: `app/beep_guard.py`, `app/beep_pipeline.py`, `templates/partials/chat.html`,
  `static/app/18_dm_chat.js`, `static/app/05_bots_tabs.js`, `app/moderator_console_routes.py`.
- Тесты: `tests/test_beep_guard.py` + новый UI-тест размещения (по образцу
  `tests/test_q7_bindings_placement.py`).
- Миграция: сохранённые `beep_settings` читаются как раньше (`beep_guard.ensure_schema()`);
  меняются только точка входа в UI и владелец настройки (бот-модератор).
- Зависит от: `DEC-OWNER-005`; живая проверка пипов — в разделе «Ждём владельца».

---

# Треки с живой приёмкой (вне очереди Q01…Q25)

## DIRECTOR-LIVE — остаток: DIR-LIVE-10 живая приёмка ⏸ (`DEC-DIRECTOR-010`)

Инженерная часть DIR-LIVE-00…09 закрыта полностью (таблицы и доказательства — в
[docs/archive/PLAN_DONE_2026-09.md](docs/archive/PLAN_DONE_2026-09.md), раздел DIRECTOR-LIVE).
Цель: [спецификация Режиссёра](docs/specs/DIRECTOR.md) до подтверждённого live-контракта;
требует отдельного разрешения владельца на Twitch send.

### DIR-LIVE-10 — обязательная живая приёмка и решение о релизе ⏸

**Зависимости:** DIR-LIVE-09 и отдельное явное разрешение владельца на конкретные внешние проверки.

- [ ] До запуска выбрать целевые provider/model/revision/endpoint и устройство, channels/test accounts,
  источники Vision/speech и разрешённый объём внешних calls/send. Не скачивать модели, не включать live
  и не использовать реальные приватные материалы только потому, что задача стала обязательной.
- [ ] Проверить выбранные Ollama/custom/cloud комбинации на настоящем replay и owner quality review;
  зафиксировать latency, timeout/error behavior и реально поддержанный output format. Не заявлять
  совместимость всех моделей по одному fake adapter или одному успешному ответу.
- [ ] Проверить настоящие source freshness/silence/static frame/loss/recovery, запись transcript/frames,
  limits, offline grace, restart, manual Pause/Stop/Emergency и отсутствие повторных отправок.
- [ ] После отдельного разрешения на Twitch send провести ограниченный live-сценарий с выбранными workers;
  заранее определить остановку и ожидаемый объём сообщений. Без разрешения использовать non-dispatching режим.
- [ ] Вместе с ACCEPT-01 пройти browser RU/EN/UA/mobile/keyboard и применимые OBS/audio сценарии без второго
  дублирующего acceptance плана. Проверить интерфейс хранения, approvals и emergency на целевом устройстве.
- [ ] Записать воспроизводимые результаты, точные проверенные версии, ограничения, найденные дефекты и
  решение release/no-go. Любой незакрытый blocker оставляет live-релиз pending.

#### DIR-LIVE-10 — прогресс приёмки в песочнице (10.09.2026)

**Реальный provider/model replay** (владелец предоставил ключи; вызовы через production-транспорт
`ProductionDirectorAdapter.generate_plan` → `ai_service.generate_text_with`, валидация
`validate_replay_response`: strict single-JSON + schema + hard-safety; скрипт
`scripts/director_live10_providers.py`, ключи только через env, в репозиторий не попадают):

| Цель | Результат | Latency | Причина |
|---|---|---|---|
| openrouter `nex-agi/nex-n2.5-mini:free` | ❌ invalid_plan | 2.1–4.7 s | Нестабильный output: один прогон — валидный director-plan JSON, но обрезан на `max_tokens=300`; при 1000 — reasoning-текст вместо JSON |
| openrouter `nvidia/nemotron-3.5-lightning:free` | ❌ strict_json | 29–56 s | Reasoning-leak («Here's a thinking process…») вместо единственного JSON-объекта |
| openrouter `nvidia/nemotron-3-super-120b-a12b:free` | ❌ strict_json / 429 | 0.3–4.3 s | Reasoning-leak в plain text; частично упирался в free-tier 429 |
| custom AMD `…/radeon/api/v1` + `DeepSeek-V4-Flash-Vision-Exp` | ❌ HTTP 429 | 0.7–1.8 s | Endpoint OpenAI-совместим (совместный error-envelope), но `ip_rate_limit_exceeded` на каждый план-вызов |
| custom AMD `…/radeon/api/v1` + `Qwen3.8-Flash-Next` | ❌ HTTP 429 | 0.3–6.1 s | То же |
| custom `api.demo_provider.ru/v1` + `gpt-5.6-luna` | ✅ **replay valid** | 11.7 s | Полный проход: strict single-JSON + schema + hard-safety + timing/assignment — **первая подтверждённая модель** |

Зафиксировано behavior: 429 не крэшит транспорт — пустой ответ → `director_ai_request_failed`
(fail-closed); несуществующая модель — мгновенный отказ (<0.1 s); таймаут транспорта 180 s не
понадобился. **Подтверждённая связка: `custom:demo_provider` + `gpt-5.6-luna`** (owner quality review
качества реакций — на живом сценарии ниже).

**Живой источник (владелец предоставил токен и канал test_channel):**

- Бот `streamer_director` (observe-only, non-dispatching подтверждён кодом `observation_only`) подключён
  к реальному IRC: `connected:true, state:online, channels:["test_channel"]`, 0 реконнектов, без ошибок.
- Реальная чат-лента пишется в БД: **138 сообщений test_channel** за первые ~4 минуты подключения,
  свежесть последнего <2 мин (live IRC-поток подтверждён).
- Director-конфигурация реального канала создана через панель (`custom:demo_provider` из БД провайдеров,
  `gpt-5.6-luna`, mode=suggest, director-аккаунт = `streamer_director`).
- `POST /api/director/test_channel/start` → fail-closed `workers_must_be_enabled_channel_lurkers`:
  для живой сессии нужны **два** аккаунта — director-аккаунт и отдельный lurker-worker этого канала;
  с одним токеном это законное поведение (не скрытый успех). Запрошен второй lurker-токен.

Выполнено также на живом сервере (managed run, QA-профиль `local`, изолированная БД; production
`data/` не тронут):

- Панель отгружена и проверена на HTTP-уровне и в разметке: секция `section-director` присутствует
  полностью (Emergency Stop, Start live/Pause/Resume/Stop/«Проверить восстановление», Workers, текущий
  plan, Конфигурация с явным «Training и Suggest не отправляют в Twitch», отсутствие provider-fallback);
  storage-панель (`directorStoragePanel`) и prompt-контейнеры (`directorPromptCreate/Draft/Prompts`)
  на месте; i18n-словари RU/EN/UA для director.* полные в `static/app/20_director.js`.
- Director API на живом сервере: `GET /sessions` → `{ok:true, sessions:[]}` (изоляция каналов);
  `GET /status` → полный контракт с `configured:false` и `live_send_enabled:false` (send-гейт закрыт);
  `POST /pause` без сессии → `session_missing`; `POST /emergency_stop` без подтверждения → `invalid_action`;
  `POST /start` без конфига → `config_missing`; `PUT /config` без выбранных workers → fail-closed
  `invalid_workers` (в QA-профиле нет lurker-ботов — корректный отказ, не скрытый успех).
- Тесты UI (Node/jsdom): 21 test, 0 fail — `tests/director_storage_ui.test.js`.

Открытые blocker'ы (частично сняты 10.09):

1. ~~**Реальные provider/model replay**~~ — **закрыто**: `custom:demo_provider` + `gpt-5.6-luna` прошла
   полный replay (единственная подтверждённая из 6 проверенных); остальные — reasoning-leak/429.
2. **Настоящие источники** — частично закрыто 10.09: второй lurker-токен получен (`streamer_lurker`,
   `chat:read` подтверждён); live-инстанс поднят на изолированном data-root `/tmp/director-live10`
   (ephemeral `TOKEN_ENCRYPTION_KEY`, port 8100), QA-профиль возвращён к чистому сиду стражем
   `verify_profile` после инцидента прямого SQLite-доступа. Оба бота в ролях (`streamer_director`=director,
   `streamer_lurker`=lurker, observation_only), lurker `connected:true, state:online` в test_channel,
   0 реконнектов; конфиг сохранён (worker_ids=[streamer_lurker], director=streamer_director). 10.09 получены
   свежие director-токен `streamer_director` и ключ `demo_provider` (только в шифрованную БД live-инстанса,
   не в git). **Провайдер-контракт принят вживую**: промпт-цикл draft → replay → activate на
   реальной `gpt-5.6-luna` — v1 3/6 (silence-кейсы: группа с percentage 0), v2 2/6 (groups:[]
   запрещён схемой minItems:1), **v3 6/6 valid — полный replay suite passed** (правильная форма
   нулевой реакции: reaction_count=0 + одна группа percentage=100; delay_window из снапшота
   {1..20}; ttl=45); промпт v3 активирован двухфакторно (quality_confirmed + replay_run_id).
   Старт сессии → fail-closed `sources_unhealthy:vision,speech` — по спецификации (§sources:
   vision/speech обязательны, запуск без них отклоняется с точными причинами): в песочнице нет
   OBS-захвата стрима. Остаток blocker'а: полный живой цикл сессии (план на реальном чате +
   Suggest) — на машине владельца с живыми vision/speech источниками; в песочнице приёмка
   достигла максимума (провайдер/промпт/активация/гейты подтверждены вживую).
3. **Интерактивный browser-проход** (RU/EN/UA, mobile-вьюпорт, клавиатура) — интерактивный браузер в
   песочнице гибнет от in-guest memory guard при загрузке панели (суммарный RSS ≈ 1.3 GiB при лимите
   2 GiB; 10+ убийств Chrome); разметка/i18n/JS-тесты и API покрыты выше, клик-проход — на устройстве
   владельца.
4. **OBS/audio** — нет OBS в песочнице.
5. **Twitch send** — требует отдельного явного разрешения владельца (без него — non-dispatching режим).

**Промежуточный вердикт:** blocker'ы 1–5 не закрыты → live-релиз остаётся **pending** до приёмки на
стороне владельца (п. 1–5 выше). Offline-инженерия 00–09 не переоценивается.

#### DIR-LIVE-10 — приёмка на машине владельца (11.09.2026, «поехали»)

**Инфраструктура:** изолированный live-инстанс на машине владельца (`TWITCH_BOT_DATA_DIR=/tmp/director-live10`,
ephemeral Fernet-ключ, порт 8100, вне git); реальные токены `streamer_director` (director) и `streamer_lurker`
(lurker, chat:read/edit) введены владельцем, провайдер `custom:demo_provider` (base/key только в шифрованной
БД инстанса). Stream Vision на test_channel + another_channel, Whisper base уже на устройстве, streamlink
8.5.0 в venv — ничего не скачивалось.

**Пройдено вживую:**

- **Replay:** 4 полных прогона по 6/6 valid на реальном `demo_provider + gpt-5.6-luna` через production
  транспорт (`~59s`/прогон); активация двухфакторна (quality_confirmed + replay_run_id), повтор
  replay при смене config fingerprint — честно потребован контрактом привязки.
- **Реальные источники:** vision описывает настоящие кадры another_channel (gpt-5.6-luna), Whisper
  транскрибирует реальную речь; IRC обоих ботов `connected:true, 0 реконнектов`.
- **Полный цикл сессии на another_channel (non-dispatching, `live_send_enabled:false`):** старт →
  warming → suggest; реальные планы каждые ~15s (серия `plan|valid`); suggest-очередь — 10 предложений
  с реакциями из реального чата; транскрипт пишет реальную речь с timestamps/source_id; evidence
  (frames + transcript jsonl) пишется в session-каталог по reserve/commit-контракту.
- **Отказоустойчивость:** отключение Stream Vision → автопауза `source_loss` ≤50s; включение →
  resume → warming → suggest, транскрипт продолжился; Emergency (глобальный kill-switch) → fence +
  отмена unsent; restart → recovery в paused, resume по обычному гейту стабильности.
- **ACCEPT-01 (browser-часть):** RU/EN/UA переключение без перезагрузки (UA полная, часть статусных
  строк Director — RU-fallback по контракту); mobile 390×844; 974 фокусируемых контрола, 0 без
  доступных имён; каталог виджетов — 46 iframe, все тёмные; Widget Bus: data-URL без channel →
  diagnostic fail-closed, с channel → 200; панель Режиссёра визуально тёмная с честными бейджами
  источников.

**Live-находки → исправлены в этой же сессии (149 director-тестов зелёные):**

1. `aa9dff3` — warming умирал `source_loss` по ai-stale (30s warm > 15s ai-freshness, heartbeat
   появляется только от первого плана); ai исключён из гейта в warming + пересеивается при
   warming→suggest.
2. `2905a84` — resume после source_loss блокировался `sources_not_stable` навсегда: в paused
   runtime ai-heartbeat невозможен; resume судит AI по верифицированному proof, stable() — по трём
   живым источникам (`SourceHealthHub.stable(sources=...)`).
3. `c879418` — emergency не попадал в тик-выборку (никакие heartbeats не обновлялись) + dry-run
   требовал ai-stable → recovery мёртвая петля; offline auto-resume и manual preview — та же
   семантика выровнена.
4. `abfbd28` — recovery-планировщик требовал RUNNING-сессию; `snapshot(allow_recovery)` принимает
   fenced/paused, `plan()` пробрасывает `request['recovery']`.
5. `e305187` — `recover_after_restart` снимает emergency_fence (рестарт — видимое владельцу
   прерывание; resume через обычный gate вместо недостижимого dry-run).

**Записанные дефекты (не блокируют suggest, требуют отдельного решения):**

- speech/vision cadence: аудио-цикл (streamlink+Whisper на CPU Steam Deck ≈ 45–90s) сериален с
  кадровой петлёй и блокирует её; `speech_stale_sec` в конфиге поднят до 120 (диапазон 1–300
  позволяет); рекомендация — вынести аудио в собственный таск и репортить heartbeat от audio-loop.
- текст ошибки провайдера глотается (`generate_plan` не-ok → без лога причины); `test_connection`
  не поддерживает `custom:*`; GET /status показывает ai:false между планами (15s freshness при
  15s интервале — display-артефакт); docs-registry тест падает из-за ~22 md из снимка 04–11.09
  (гигиена реестра); кнопка «Продовжити» переносится, часть Director-строк — RU-fallback в UA.

**Twitch send-сценарий — исполнен 12.09 (владелец подтвердил владение каналом another_channel
и разрешил send там; test_channel оставался offline всю приёмку):**

- конфиг another_channel → `mode=live` (fingerprint сменился → повторный replay 6/6 → активация);
- живая сессия на реальном стриме: warming → live, `live_send_enabled:true` после входа в live;
- **3 сообщения отправлено (бюджет ≤5 соблюдён)**, все `state='sent'` — Twitch принял без
  reject/slow/rate; каждый план → ровно одно сообщение (single output), `send_delay 1–5s`
  выдержан; Stop в 22:21:35 — pending=0, хвост чист; транскрипт закрыт по stop;
- конфиг возвращён в `mode=suggest` (replay 5/6 — `silence` поймал разовый `timing_mismatch`
  модели, повтор 6/6 → активация; гейт честно ловит недетерминизм модели).

**Остаток DIR-LIVE-10:** только OBS/CEF visual composition и TTS/audio single output — при живом
OBS (владелец). Отдельный test_channel-сценарий больше не требуется: Twitch send-транспорт принят вживую.

**Ночной прогон (12.09, по решению владельца):** suggest-сессия another_channel оставлена работать
на ночь (non-dispatching, токены владельца не жалко) — утром владелец разбирает очередь
(approve/reject → позитивные/негативные примеры; это и есть training-петля Director). Найден
пробел: **live-отправленные реакции нельзя отклонить в негативные примеры** (очередь ревью
содержит только suggest-планы) — кандидат в OPTIONAL вместе с переносом базы. Качество v1-реакций
владелец оценил как слабое («не очень») → итерация: промпт v2 (короче, конкретнее, без зачинок,
8 слов max) + `diverse_similarity=strict`; первая реакция v2 — «стример опять просит белку»
(владелец: «неплохо»). Подтверждено поведение: при 1 lurker массовых реакций нет — массовость
это группы percentage × число воркеров (chant разрешает дубликаты), для сотни люркеров включается
`reaction_mode=percentage`. Для приёмки OBS: obs-websocket включён в конфиге OBS владельца
(бэкап `global.ini.bak-accept01`, пароль в `/tmp/director-live10/obs_ws_password`, не в git) —
тесты (скриншоты рендера OBS, запись клипов для TTS/Soundboard через ffmpeg) выполняются агентом
без участия владельца, ему нужно только запустить OBS.

**Общий критерий закрытия DIRECTOR-LIVE:** закрыты DIR-LIVE-00…10; полная спецификация сопоставлена с
реализацией и доказательствами, storage/lifecycle проверены, реальные модели/источники приняты в указанном
объёме. Готовые replay/Suggest или успешный offline прогон отдельно весь пункт не закрывают.

## MODSITE — отдельный модераторский сайт (`DEC-MODSITE-001`, `DEC-FUTURE-001`)

Документация и подробный порядок реализации — в [`moderator-site/`](moderator-site/README.md):
спецификация [`SPECIFICATION.md`](moderator-site/SPECIFICATION.md), 25 этапов MOD-00…MOD-24 в
[`moderator-site/IMPLEMENTATION.md`](moderator-site/IMPLEMENTATION.md), приёмка
[`ACCEPTANCE.md`](moderator-site/ACCEPTANCE.md), развёртывание
[`DEPLOYMENT.md`](moderator-site/DEPLOYMENT.md), инвентарь контракта
[`CONTRACT_INVENTORY.md`](moderator-site/CONTRACT_INVENTORY.md). Здесь — только активный статус,
чтобы не получился второй конкурирующий чеклист (`DEC-MODSITE-001`).

Статус на 12.09.2026: MOD-00…MOD-22 инженерно закрыты (83 профильных теста
`tests/test_moderator_site_*.py` зелёные), MOD-23 browser-приёмка пройдена на fake backend
11.09 (`moderator-site/ACCEPTANCE.md` §20), MOD-18 owner UI приёмка — 11.09 (§22).

- [ ] MOD-24 Twitch/OBS/device-приёмка — **ждёт владельца** (`moderator-site/ACCEPTANCE.md` §21):
      настоящие Twitch/OBS/устройство, только по явному разрешению (`DEC-OPS-001`).
- [ ] Публичный запуск сайта не разрешён documentation-only запросом: домен/hosting и
      browser/OBS/provider acceptance — отдельное решение владельца.

---

# Ждём владельца (блокеры, агент их не исполняет)

Панель 12.09 поднята: PID 281409, `http://127.0.0.1:8000`, лог `/tmp/server_v12.log`.
Whisper **уже установлен** в venv панели (`openai-whisper 20250625`, `torch 2.13.0`), ffmpeg
и pactl на месте, beep-sink `input.bot_beep_out` существует — установка не требуется
(прежняя пометка «нужен `pip install openai-whisper`» относилась к системному python,
а панель работает из `venv/bin/python`).

- [ ] **D1** — проверить смену роли: lurker → модератор применяется сразу и снимает
      «Только наблюдает» (фикс `3e0cdd3` в main; раньше мешал незапущенный рестарт).
- [ ] **Стоп** — кнопка Стоп у включённого бота больше не даёт «Ошибка: OK» (`3e0cdd3`).
- [ ] **H1** — beep-конвейер вживую: пипы реально слышны, статус в UI честный
      (не вечный pass-through). Перенос настройки — пункт Q25.
- [ ] **A4** — живой прогон добавления ботов к каналу test_channel (streamer_lurker/streamer_director):
      нужен реальный IRC, то есть разрешение владельца (`DEC-OPS-001`).
- [ ] **Q13/C5** — живая проверка реактивного блюра: нужен browser/OBS.
- [ ] **Q05/I1** — подтвердить вердикты инвентаризации глобальных настроек.

# Решения владельца: открытых вопросов нет

Ответы 12.09.2026 записаны в [docs/DECISIONS.md](docs/DECISIONS.md), раздел «Решения владельца
12.09.2026 (ночь)», с расшифровкой дословных формулировок:

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
- `DEC-OWNER-011` — контрольное сообщение при добавлении бота опционально, по умолчанию выключено
  (уточняет `DEC-BULK-005`, `DEC-BULK-008`).
- `DEC-OWNER-012` — тестов на md-файлы нет: `tests/test_docs.py`,
  `tests/test_moderator_site_docs.py`, `tests/test_plan_file_zones.py` удалены 13.09;
  `scripts/check_md_links.py` остался ручной командой.

Прежние «Открытые вопросы владельцу» 1–4 закрыты: массовая смена канала — `DEC-OWNER-006`,
размещение beep-настройки — `DEC-OWNER-005`, шифрование токенов — `DEC-OWNER-007`,
test_bot — `DEC-OWNER-009`.

# Необязательно / потом

Неактуальные на 12.09 идеи (OPTIONAL-03…10, внешние gates, статусы OmniVoice и voice-live,
`DEC-CLEANUP-002` — оставшийся cleanup не выполняем) — в архиве:
[docs/archive/PLAN_TODO_2026-09-12.md](docs/archive/PLAN_TODO_2026-09-12.md). Возвращать только
по явному запросу владельца.

# Справка

- Python-тесты: `~/.local/bin/pytest tests/test_<модуль>.py -q`; UI-тесты: `node tests/<имя>.test.js`.
  Схема БД в тестах создаётся `init_db()`; `chat_log` имеет колонку `author` (не username);
  beep-тестам нужна `beep_guard.ensure_schema()`.
- Тесты живут на системном python (`~/.local/bin/pytest`), панель — в `venv/`: пакеты в venv
  не видны тестам и наоборот.
- Правки `static/app.js` — точечные (i18n-словари RU/EN/UA в трёх блоках); новые эндпоинты —
  в своём `app/<фича>_routes.py` плюс one-line `include_router` в `app/server.py`.
- panel-labels режет регион widgets по маркеру `<!-- Решение владельца 31.08` → конечный маркер
  `<details ... data-widget-group="catalog">`.
- **Тестов на md-файлы в проекте нет** (`DEC-OWNER-012`, удалены 13.09): `tests/test_docs.py`,
  `tests/test_moderator_site_docs.py` и `tests/test_plan_file_zones.py` больше не существуют.
  Структуру плана, журнала решений и карты зон ничто автоматически не проверяет — значит при
  переписывании документа разделы нельзя терять молча: именно так 12.09 из плана пропали
  `## DIRECTOR-LIVE` (этап DIR-LIVE-10 с доказательствами приёмки) и `## MODSITE`, и их
  пришлось восстанавливать из архива и истории git.
- Обязательные разделы этого файла (соглашение, не тест): очередь Q…, `## DIRECTOR-LIVE`,
  `## MODSITE`, `# Ждём владельца`, `# Решения владельца`, `# Необязательно / потом`,
  `# Справка`.
- Ссылки и якоря в активных документах проверяются вручную: `python3 scripts/check_md_links.py`
  (реестр 22 файлов в `ACTIVE_DOCS`; новый `.md` вне `docs/archive/` добавляй туда же).
- Состояние: `git log --oneline -10` здесь же.
