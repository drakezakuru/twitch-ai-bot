# План реализации 39 виджетов

> Источник состава: `app/widget_inventory.py` — ровно 39 публичных контрактов. Исследование и каталог решений уже выполнены в `docs/RESEARCH_WIDGETS.md`; этот документ описывает **будущую реализацию**, а не выдаёт заполненный каталог за готовый код.

## 1. Границы и неизменяемые контракты

### Уже сделано (не implementation wave)

- собран канонический реестр `WIDGET_INVENTORY`, карточки, примеры и research-вердикты;
- для 39 карточек определены `route`, `folder`, `preview_url`, `preview_mode`;
- сохранён W7-контракт тёмного iframe и `?preview=1`, настроена совместимость смысловых биндингов;
- focused-тесты каталога/маршрутов уже существуют. Это каркас и исследование, но **не** визуальная и продуктовая переделка виджетов.

### Общее правило будущей реализации

1. Публичные URL из `WIDGET_INVENTORY`, параметры URL и текущие JSON-формы API сохраняются. Старые OBS Browser Source не требуют перенастройки.
2. `MERGE` означает общую внутреннюю реализацию, а не немедленное удаление карточки или URL. Старые URL остаются адаптерами/алиасами минимум на один релизный цикл; удаление возможно только отдельным решением владельца.
3. `BORROW` означает только заимствование UX-паттерна из research: код, API, данные, права и биндинги остаются нашими.
4. Миграции БД — только additive/idempotent с чтением старых строк. Переименование/удаление таблиц и полей в этих waves не планируется.
5. Каждый изменённый HTML сохраняет тёмное прозрачное/безопасное состояние, `color-scheme`, `?preview=1`, корректный empty/error state и работу через `widgets/_shared/widget-bus-client.js`, где он уже используется.
6. После каждого wave — только перечисленные focused-тесты и отдельный коммит. **Полный `pytest` и запуск панели/OBS/browser gate не выполнять, если владелец позже явно не попросит.** Живые browser/OBS-пункты остаются отложенной приёмкой, а не условием документационного этапа.

## 2. Решения владельца, таксономия и проверка повторяющихся controls

### Уже принятые продуктовые решения

- **TTS family — ДА:** `tts`, `tts-bot`, `chat-reader` получают общую очередь/transport, но сохраняют три режима, настройки, карточки и URL.
- **Event widgets — ДА:** `latest-event-card` и `recent-events` используют общую модель события, но остаются отдельными card/list-представлениями и URL.
- **Characters — ДА:** `mascot` и `anime-runner` делят renderer/assets, но сохраняют reactive/runner-режимы, карточки и URL.
- **Emoji — решение не принято:** назначение и варианты удаления/слияния объяснены в [`OPEN_QUESTIONS.md`](OPEN_QUESTIONS.md); до ответа оба URL не удалять.

### Категории и подкатегории канонических 39

| Категория | Подкатегория | Канонические widgets |
|---|---|---|
| Аудио и речь | TTS/голос | `tts`, `tts-bot`, `chat-reader`, `tts-chat-overlay`, `voice-changer` |
| Аудио и речь | Музыка/медиа | `now-playing`, `song-request`, `media-share`, `soundboard` |
| Цели и время | Цели/деньги | `goals`, `sub-goal`, `donation-challenge`, `top-donator-alltime`, `top-donator-month`, `top-donator-day` |
| Цели и время | Таймеры/счётчики | `counter`, `combo-counter`, `countdown`, `subathon-timer`, `uptime` |
| Чат и вовлечение | Сообщения/активность | `chat-highlight`, `hype-meter`, `typing-indicator`, `emoji-chat`, `emoji-leaderboard` |
| Чат и вовлечение | Интерактив | `chat-roulette`, `poll-overlay` |
| События канала | Ленты/карточки | `follower-ticker`, `latest-event-card`, `recent-events`, `schedule` |
| Оформление | Сцена/идентика | `animated-bg`, `lower-third` |
| Оформление | Персонажи | `mascot`, `anime-runner` |
| Безопасность и производство | Защита/модерация | `blur-guard`, `blur-guard-v2`, `mod-feed` |
| Безопасность и производство | Twitch production | `clip-moments` |

Проверка: таблица покрывает 39 slug ровно по одному разу. Полный пронумерованный owner survey с назначением и choices находится в [`OPEN_QUESTIONS.md`](OPEN_QUESTIONS.md#опрос-владельца-по-всем-39-виджетам).

### Почему владелец видел одинаковые Countdown / Sub-goal / третью карточку

Точная текущая структура `templates/partials/widgets.html` такова:

1. перед всеми настройками находится **один** контейнер `#widgetManualControls`;
2. в нём ровно три мини-карточки: **Sub-goal**, **Счётчики** (это третья названная владельцем карточка) и **Countdown**;
3. контейнер расположен **вне** Jinja-цикла `{% for widget in widget_inventory %}`; цикл 39 карточек начинается только у `#canonicalWidgetInventory`;
4. обработчики `waSubDelta(1)`, `waSubDelta(-1)`, `waSubReset()` и `waCdAction(start/stop/reset)` встречаются в текущем partial по одному разу; каталог добавляет лишь совместимую форму биндинга для шести контрактов, а не эти ручные controls.

Историческая причина путаницы: коммит `ff6c971` вынес ручные действия Sub-goal/Countdown из их настроечных карточек в общий верхний блок, а `914aeff` удалил legacy-маркеры `data-wa-presets` с пяти карточек, чтобы общий JS больше не декорировал каждую из них одинаковыми preset-кнопками. Поэтому по текущему source duplicate-control bug **уже удалён**; без запуска панели нельзя подтвердить, что владелец не видел старый bundle/cache или визуально «прилипший» общий блок.

**Конкретная будущая fix/verification task (код сейчас не менять):** сделать общий блок визуально отдельным от каталога и явно подписать «3 ручных инструмента: Sub-goal / Счётчики / Countdown»; добавить template/render regression test, который требует ровно один `#widgetManualControls`, один набор каждого action handler, нахождение блока вне `#canonicalWidgetInventory`/Jinja-loop и отсутствие этих controls внутри любой `.widget-guide-card`; при живом gate проверить clean reload без старого cache. Если повтор воспроизводится — чинить nesting/CSS/cache загрузки, не копировать controls по карточкам.

### Почему существуют два Blur Guard

- `blur-guard` (`/obs/blur-guard`) — legacy-оверлей: включает/выключает реактивное размытие всего кадра по событиям `blur_on`/`blur_off` и оставлен ради уже настроенных OBS URL.
- `blur-guard-v2` (`/obs/blur-guard-v2`) — актуальный расширенный оверлей: принимает те же reactive events, live `blur_config` и дополнительно держит постоянные зоны; именно его следует добавлять в новые OBS-сцены.
- Это не две обязательные Browser Source одновременно. Рекомендуемый outcome survey: **MERGE/alias legacy URL на v2**, сохранить старый URL как совместимый адаптер минимум релизный цикл, а в панели показывать одну карточку Blur Guard.

## 3. Порядок коммитов и waves

### Wave 0 — зафиксировать контракты до изменения кода

**Коммит:** `test(widgets): lock public widget compatibility contracts`.

- Снять machine-readable snapshot 39 `slug/route/folder/preview_url/preview_mode`; закрепить, что реестр, публичные роуты, папки и карточки панели совпадают.
- Добавить parametrized assertions для status/content-type, тёмного preview и сохранённых route aliases (`counter → counters`, `uptime → stream-session`, три top-donator URL → одна папка).
- Likely files: `app/widget_inventory.py` (только если нужен явный metadata contract), `tests/test_w7_preview_contracts.py`, `tests/test_widget_public_smoke.py`, `tests/test_widgets_folder.py`, `tests/test_widgets_cards_and_subathon.py`.
- Backend/API: без изменений. Migration/URL: без изменений.
- Focused tests: перечисленные четыре файла плюс `tests/test_widget_api_base.py`.
- Acceptance: тест падает при потере любого из 39 контрактов, изменении стабильного URL или белом/непредставительном preview.

---

### Wave 1 — KEEP: укрепить уникальные и уже цельные реализации (13)

| № | Виджет | Outcome | Реализация и likely components |
|---:|---|---|---|
| 1 | `animated-bg` | KEEP | Сохранить движок частиц; ограничить density/DPR, prefers-reduced-motion и безопасные presets. `widgets/animated-bg/index.html`, route replacement в `app/widgets.py`. |
| 2 | `counter` | KEEP | Крупное значение, pulse только при изменении, честный reset/large-number layout. `widgets/counters/index.html`, counter API/bindings в `app/widgets.py`, `app/widget_bindings.py`. |
| 3 | `uptime` | KEEP | Явные offline/live/loading состояния, моноширинное время без ложного тика. `widgets/stream-session/index.html`, session public API owner. |
| 4 | `combo-counter` | KEEP | Показ порога/серии только по реальным событиям, сброс без flash фиктивных данных. `widgets/combo-counter/index.html`, combo endpoints в `app/widgets.py`. |
| 5 | `countdown` | KEEP | Единая state machine start/stop/reset, устойчивость reload и stopwatch/countdown. `widgets/countdown/index.html`, countdown API, bindings. |
| 6 | `clip-moments` | KEEP | Empty/loading/permission error; не изображать созданный clip без Twitch permission. `widgets/clip-moments/index.html`, `app/routes_clip.py`, clip routes in `app/widgets.py`. |
| 7 | `voice-changer` | KEEP | Device/offline/active state без обещания hardware. `widgets/voice-changer/index.html`, существующий voice status API. |
| 8 | `typing-indicator` | KEEP | Debounced show/hide по реальному generation state, timeout после disconnect. `widgets/typing-indicator/index.html`, widget-bus event publisher. |
| 9 | `tts-chat-overlay` | KEEP | Сохранить `all/rewards/bot`, TTL/fade, representative preview без публикации demo в live. `widgets/tts-chat-overlay/index.html`, TTS chat endpoints/event bus. |
| 10 | `subathon-timer` | KEEP | Серверное время как источник истины; события sub/donation продлевают один раз; milestone pulse. `widgets/subathon-timer/index.html`, subathon API/hooks в `app/widgets.py`, `app/donation_integrations.py`. |
| 11 | `blur-guard` | KEEP | Без камеры — безопасное inactive preview; сохранить текущую защиту. `widgets/blur-guard/index.html`, `app/blur_guard_routes.py`. |
| 12 | `blur-guard-v2` | KEEP | Сохранить зоны и live `blur_config`; 1/50/100 визуально различимы без hardcoded blur. `widgets/blur-guard-v2/index.html`, blur routes/config publisher. |
| 13 | `mod-feed` | KEEP | Компактный empty/action/error feed на реальных moderation decisions. `widgets/mod-feed/index.html`, `app/mod_feed_routes.py`. |

**Backend/API compatibility:** не менять существующие response keys и semantics; новые display-поля только optional. Counter/countdown actions остаются совместимыми с `ALLOWED_ACTIONS`. Subathon hooks должны оставаться idempotent на уровне одного входного события.

**Migration/URL compatibility:** сохранить `/widget/animated-bg`, `/widget/counter`, `/widget/uptime`, `/widget/combo-counter`, `/widget/countdown`, `/widget/clip-moments`, `/widget/voice-changer`, `/widget/typing-indicator`, `/widget/tts-chat-overlay`, `/widget/subathon-timer`, `/obs/blur-guard`, `/obs/blur-guard-v2`, `/widget/mod-feed`; миграция БД не ожидается.

**Focused tests:** текущие `test_widget_public_smoke.py`, `test_widgets_folder.py`, `test_widget_bindings.py`, `test_widget_blur_guard.py`, `test_s93_clip_moments_widget.py`, `test_p6_tts_chat.py`, `test_widget_extra_widgets.py`; добавить/расширить parametrized empty/loading/error и countdown/subathon transition tests.

**Acceptance:** каждый виджет работает на старом URL и старой форме API; preview не зависит от live-данных; отсутствуют фиктивные success states; reduced-motion и reconnect не ломают отображение.

---

### Wave 2 — BORROW: применить research UX к нашим данным (14)

| № | Виджет | Outcome | Что заимствуем / что сохраняем / likely components |
|---:|---|---|---|
| 14 | `goals` | BORROW | Крупные цифры, progress и completion animation; сохранить goals CRUD и `add_percent/reset`. `widgets/goals/index.html`, goals API/bindings. |
| 15 | `now-playing` | BORROW | Artwork hierarchy, ellipsis/marquee policy; сохранить manual/Last.fm/MPRIS/`!np`. `widgets/now-playing/index.html`, now-playing settings/API. |
| 16 | `sub-goal` | BORROW | Milestone/progress polish; сохранить tree/reef/city themes и `increment/set/reset`. `widgets/sub-goal/index.html`, sub-goal API/EventSub hook. |
| 17 | `schedule` | BORROW | Карточки now/next и ясное empty state; сохранить schedule blocks API. `widgets/schedule/index.html`, schedule CRUD/public API. |
| 18 | `follower-ticker` | BORROW | Pause between items, bounded speed, enter/exit; сохранить channel event source. `widgets/follower-ticker/index.html`, recent-events public feed. |
| 19 | `lower-third` | BORROW | Safe areas, bounded long text, enter/exit; сохранить `set` binding и URL overrides. `widgets/lower-third/index.html`, lower-third API/binding. |
| 20 | `chat-highlight` | BORROW | Переносы, fade and empty state; сохранить наши chat events/mod choice. `widgets/chat-highlight/index.html`, highlight endpoints. |
| 21 | `chat-roulette` | BORROW | Wheel easing, deterministic finish, empty/insufficient viewers; сохранить viewers source. `widgets/chat-roulette/index.html`, roulette endpoints. |
| 22 | `song-request` | BORROW | Queue hierarchy и empty/rejected states; сохранить priority/cooldown/max-per-user API. `widgets/song-request/index.html`, song-request routes/settings. |
| 23 | `donation-challenge` | BORROW | Goal/milestone layout; сохранить multi-provider donation ingestion. `widgets/donation-challenge/index.html`, challenge API, `app/donation_integrations.py`. |
| 24 | `hype-meter` | BORROW | Smooth bounded meter; сохранить chat-activity calculation, ноль при пустом чате. `widgets/hype-meter/index.html`, hype public API. |
| 25 | `poll-overlay` | BORROW | 2–5 choices, percentages, closed result; сохранить Twitch/custom poll APIs и `!vote`. `widgets/poll-overlay/index.html`, `app/twitch_polls.py`, `app/predictions_polls.py`, poll routes in `app/widgets.py`. |
| 26 | `media-share` | BORROW | Queue/moderation/error states; сохранить действующие limits/approval policy и не autoplay битую ссылку. `widgets/media-share/index.html`, media admin/public endpoints. |
| 27 | `soundboard` | BORROW | Tiles, queue, volume/cooldown affordance; сохранить upload/list/play/broadcast и `play_track:<id>`. `widgets/soundboard/index.html`, soundboard API, widget bus, bindings, panel form. |

**Backend/API compatibility:** это visual/interaction refinement поверх текущих payloads. Не менять validation status (включая incompatible binding 400 и bad track 400/404). Новые UX-настройки, если нужны, добавлять optional с текущим поведением по умолчанию.

**Migration/URL compatibility:** все 14 URL сохраняются; старые DB rows целей, song requests, polls, challenges и soundboard tracks читаются без преобразования. Только additive migration допустима для действительно нового persisted setting.

**Focused tests:** `test_widget_goals_percent.py`, `test_widget_now_playing_sources.py`, `test_widget_song_request_ux.py`, `test_widget_donation_integrations.py`, `test_widget_extra_widgets.py`, `test_predictions_polls.py`, `test_widget_owner_decisions.py`, `test_widget_bindings.py`, `test_widgets_folder.py`, `test_widget_public_smoke.py`; добавить template-state tests 0/50/100, empty/long/error и soundboard reconnect/bad-id contract.

**Acceptance:** состояния из примеров реестра воспроизводимы детерминированно в preview; live использует только наши API; long/empty/error не ломают layout; существующие админ-формы и bindings продолжают управлять теми же сущностями.

---

### Wave 3 — MERGE: три top-donator URL на общей реализации (3)

| № | Виджет | Outcome | Реализация |
|---:|---|---|---|
| 28 | `top-donator-alltime` | MERGE/keep URL | Общий renderer/data adapter с `period=alltime`; сохранить title и public API периода. |
| 29 | `top-donator-month` | MERGE/keep URL | Тот же renderer с `period=month`; граница периода вычисляется backend как сейчас. |
| 30 | `top-donator-day` | MERGE/keep URL | Тот же renderer с `period=day`; сохранить daily semantics и empty state. |

Likely files: `widgets/top-donator/index.html`, top-donator routes/settings/cache in `app/widgets.py`, panel top-donator form, inventory tests.

**Backend/API compatibility:** сохранить три read endpoints `/api/widgets/public/top-donator/{alltime|month|day}`, settings titles and cache keys. Общий внутренний helper не должен менять amount/currency/null semantics.

**Migration/URL compatibility:** сохранить три `/widget/top-donator-*` URL и три карточки на текущем этапе; таблицы `donations` и `top_donator_settings` не менять.

**Focused tests:** расширить top-donator tests в `test_widget_donation_integrations.py`/`test_widget_public_smoke.py`; parametrized period isolation, empty state, title/theme override, old URLs.

**Acceptance:** один renderer без трёх расходящихся реализаций; каждый URL показывает только свой период; старые OBS URLs и настройки заголовков работают.

---

### Wave 4 — MERGE-кандидат: единое ядро событий, две проекции (2)

> Решение владельца принято: выполнять с общей моделью события, сохраняя обе проекции и URL.

| № | Виджет | Intended outcome | Реализация |
|---:|---|---|---|
| 31 | `latest-event-card` | MERGE внутреннего event model; keep card projection/URL | Последнее событие с type variation/filter; renderer может использовать общий event-normalizer. `widgets/latest-event-card/index.html`, settings/routes in `app/widgets.py`. |
| 32 | `recent-events` | MERGE внутреннего event model; keep list projection/URL | Лента до пяти событий с общей нормализацией/icons/enter-exit. `widgets/recent-events/index.html`, recent-events CRUD/public feed/hooks. |

**Backend/API compatibility:** canonical event shape вводить через adapter; существующие latest/recent payloads оставить доступными. Donation/EventSub producers продолжают писать один раз. Filter semantics latest card не переносить молча на list.

**Migration/URL compatibility:** обе таблицы/settings, `/widget/latest-event-card`, `/widget/recent-events` и public endpoints сохраняются; destructive migration не нужна.

**Focused tests:** event producer → обе проекции; follow/sub/donation type mapping; latest filter; recent limit/order; empty state; old URLs. База: `test_widget_donation_integrations.py`, `test_widget_public_smoke.py`, новые `test_widget_event_views.py`.

**Acceptance:** одно событие имеет одинаковые username/kind/amount/time в обеих проекциях, не дублируется producer-ом; обе визуальные задачи и URL сохранены.

---

### Wave 5 — MERGE-кандидат: TTS family с общим queue/status core (3)

> Решение владельца принято: выполнять с общей очередью/transport, сохраняя три режима, настройки и URL.

| № | Виджет | Intended outcome | Реализация |
|---:|---|---|---|
| 33 | `tts` | MERGE core; keep raw OBS URL | Базовая очередь озвучки `/obs/tts`; сохранить channel/voice behavior и минимальный raw overlay. `widgets/tts-raw/index.html`, `templates/obs_tts_widget.html`, route in `app/routes.py`, audio queue. |
| 34 | `tts-bot` | MERGE core; keep Golden Voice projection/config/URL | Использовать общий queue/status transport, но сохранить accent/icon/per-account config. `widgets/tts-bot/index.html`, tts-bot routes in `app/widgets.py`. |
| 35 | `chat-reader` | MERGE core; keep policy/settings/URL | Поставщик сообщений в общую очередь; сохранить enabled/read_all/command/min_role/provider/max_chars/cooldown. `widgets/chat-reader/index.html`, chat hook, chat-reader settings/API. |

**Backend/API compatibility:** не объединять разные политики в одну настройку. Общий интерфейс queue item должен адаптировать текущие payloads; `/api/widgets/tts-bot/config`, chat-reader settings и raw TTS channel/voice остаются совместимыми. Не создавать двойную озвучку при одном событии.

**Migration/URL compatibility:** `/obs/tts`, `/widget/tts-bot`, `/widget/chat-reader` сохраняются; per-account chat-reader and Golden Voice rows сохраняются. Additive queue metadata допустима без обязательной миграции старых данных.

**Focused tests:** `test_audio_queue.py`, `test_tts_bot_widget.py`, `test_chat_reader.py`, `test_widget_public_smoke.py`, TTS route tests; добавить exactly-once queue, policy isolation, reconnect, empty queue and legacy URL cases.

**Acceptance:** общий transport/queue без трёх копий reconnect logic; одна входная реплика озвучивается максимум один раз; Golden Voice и chat-reader настройки не теряются; все три URL остаются валидны.

---

### Wave 6 — MERGE-кандидат: общий character renderer, два режима (2)

> Решение владельца принято: выполнять с общим renderer, сохраняя reactive/runner-режимы и URL.

| № | Виджет | Intended outcome | Реализация |
|---:|---|---|---|
| 36 | `mascot` | MERGE renderer; keep reactive mode/URL | Idle/reaction state от recent events, preset/custom URL. `widgets/mascot/index.html`, mascot state/public API. |
| 37 | `anime-runner` | MERGE renderer; keep runner mode/URL | Loop/corner/speed/size/flip controls без event reaction. `widgets/anime-runner/index.html`, runner settings/public API. |

**Backend/API compatibility:** общий renderer принимает нормализованный presentation config, но adapters сохраняют разные mascot/runner payloads. Не добавлять mascot reactions в runner и наоборот без решения.

**Migration/URL compatibility:** оба URL и существующие settings остаются; destructive migration отсутствует.

**Focused tests:** mascot event reaction, custom URL sanitization, runner loop/config, old URL/query overrides, reduced-motion and preview. База: widget routes/folder/public smoke плюс новые `test_widget_characters.py`.

**Acceptance:** shared assets/animation primitives без дублирования; mascot остаётся реактивным, runner — циклическим; обе карточки/URL работают.

---

### Wave 7 — MERGE-кандидат: общая emoji-статистика, два представления (2)

> Выполнять после ответа на вопрос владельцу №4.

| № | Виджет | Intended outcome | Реализация |
|---:|---|---|---|
| 38 | `emoji-leaderboard` | MERGE data core; keep ranked view/URL | Ранги и empty state из агрегированной emoji statistics. `widgets/emoji-leaderboard/index.html`, emoji stats API/routes. |
| 39 | `emoji-chat` | MERGE data/event core; keep stream view/URL | Emoji-only live messages с enter/exit; не превращать в leaderboard. `widgets/emoji-chat/index.html`, chat hook/public API. |

**Backend/API compatibility:** единый normalizer/extractor эмодзи; leaderboard aggregation и live feed остаются разными read models. Существующая `emoji_stats` и текущие emoji-chat payloads сохраняются.

**Migration/URL compatibility:** `/widget/emoji-leaderboard`, `/widget/emoji-chat` и public endpoints сохраняются; текущая таблица `emoji_stats` читается как есть.

**Focused tests:** `test_widget_emoji_chat.py`, `test_widget_extra_widgets.py`, public smoke; добавить extractor parity, no-emoji empty state, rank order/ties, no duplicate count per message and old URLs.

**Acceptance:** один алгоритм распознавания эмодзи; live chat и daily ranking согласованы по входным сообщениям, но остаются отдельными представлениями.

## 4. Общий gate каждого implementation-коммита

- перечитать изменяемые файлы непосредственно перед точечными edits;
- не менять виджеты вне текущего wave;
- проверить inventory count = 39 и перечисление документа = 39 без дублей;
- запустить только focused-тесты wave + contracts Wave 0;
- обновить документацию только если фактический outcome отличается от плана;
- отдельный коммит после зелёных focused-тестов;
- не запускать полный `pytest`, панель, browser или OBS без нового явного запроса владельца.

## 5. Статус решений для merge waves

- **Wave 4 Event widgets — разрешён:** общий event model, две проекции и два URL.
- **Wave 5 TTS family — разрешён:** общая очередь/transport, три режима, настройки и URL.
- **Wave 6 Characters — разрешён:** общий renderer, два режима и URL.
- **Wave 7 Emoji — заблокирован:** владелец считает оба виджета, вероятно, ненужными; выбрать KEEP/DELETE/MERGE в вопросах 34–35 из [`OPEN_QUESTIONS.md`](OPEN_QUESTIONS.md#emoji).

Ни одно merge-решение само по себе не разрешает удалять публичный URL или данные: compatibility/delete выполняются отдельным явно согласованным этапом.
