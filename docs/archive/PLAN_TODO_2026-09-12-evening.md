# PLAN_TODO — единственный активный план (ревизия 12.09.2026)

> Прежний план (завершённые аудиты, MODSITE, OPTIONAL-03…10, gates, история) —
> целиком в [docs/archive/PLAN_TODO_2026-09-12.md](docs/archive/PLAN_TODO_2026-09-12.md).

## Как работать

- Работать в текущей ветке, которую выдало окружение; не переключаться на устаревшие ветки из истории.
- Каждый пункт — маленький commit, focused tests и `git diff --check`.
- Для Hoplite каждый завершённый пункт после зелёных проверок публикуется в текущую разрешённую
  GitHub-ветку; следующий пункт начинается только после подтверждённой публикации.
- Не использовать production DB/credentials.
- Не запускать полный pytest, browser, OBS/CEF и реальные provider/ML calls без отдельного разрешения.
- Исключение для OPS-01: разрешён официальный Ollama image pull и только version/startup/health,
  без model pull и inference.
- Финальная browser/OBS-приёмка запускается только после явного **«поехали»**.
- Public OBS URLs, compatibility APIs и legacy DB rows не удалять молча.

---


# Текущая работа

## CLEANUP-01 — исключён из текущей работы ⏸ (`DEC-CLEANUP-002`)

Владелец выбрал UI-01 вместо cleanup. Оставшиеся пункты ниже не выполнять без нового
явного запроса; файлы и legacy data сохраняются. Уже завершённое не откатывается.

При отдельном разрешении: два caller/reference поиска → owning focused test → отдельный commit.

- [x] `get-pip.py` — vendored pip bootstrap без repository callers удалён; canonical setup использует
  `python -m pip`/dependency manifests.
- [ ] `shot_mascot.png`.
- [ ] `templates/index_v10_backup.html`.
- [ ] `templates/obs_tts_widget.html`; `/obs/tts` остаётся canonical route.
- [ ] `start_v12.sh`; canonical launcher `start.sh --no-browser`.
- [ ] `scripts/p5_split_app_js.py`.
- [ ] `scripts/p5_split_routes.py`.
- [ ] `scripts/migrate_legacy_data.py` → recovery-only archive после backup warning и
  idempotence/collision fixture.
- [x] Panel review JSON + renderer + historical output перенесены одной связкой в
  `docs/archive/panel-review-2026-09-01/`.

Legacy DB rows автоматически не удалять. Destructive cleanup только owner-invoked dry-run+backup.

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

## WIDGETS-UI — каталог виджетов: группы, превью, биндинг и настройки на карточке (план 12.09, ✅ выполнен)

Запрос владельца: страница виджетов слишком длинная, превью обрезаны, биндинг — «общая штука»,
настроек на карточке нет. Порядок исполнения: шаги 1→2→3→4, после каждого — тесты + коммит.

- [x] Шаг 1 (`357e652`). Превью целиком: в каждой из 13 рукописных карточек и в карточках
  каталога — «🔍 Увеличить» (лайтбокс `waWidgetZoom` в реальных пропорциях из `WIDGET_OBS_SIZES`,
  масштаб под экран) и «↗ В новой вкладке» (прямая ссылка `widgetOutputUrl`).
- [x] Шаг 2 (`8e2f4f2`). Группы-папки: 7 `<details>`-групп (basics, donations, tts_sound,
  automation, overlays, extras, catalog), по умолчанию все свёрнуты, состояние в localStorage
  (`widgetsGroupsOpen`), счётчик карточек; `loading=lazy` сохранён; субатон перенесён в «Донаты».
- [x] Шаг 3 (`39de17b`). Биндинг в карточке: общий билдер `waBindingBuilder` переносится в
  модал `waBindingModal` и возвращается на место при закрытии; логика match/action/fields и
  scope сохранена; кнопка только у виджетов с binding-контрактом.
- [x] Шаг 4 (`3e972f6`). Настройки на карточке: у 7 виджетов с формой в «Прочих виджетах»
  кнопка «⚙ Настройки» открывает ту же форму в модале `waWidgetSettings` (узел переносится и
  возвращается, дублей форм нет).
- Файлы: templates/partials/widgets.html, static/app.css, static/app/07_widgets.js,
  static/app/13_widgets_session.js; переводы RU/EN/UA для новых кнопок.
- Gate: `tests/test_widgets_ui_cards.py` (owning, шаги 1–4), panel-audit / preview-coverage /
  q7-bindings / panel-labels / panel-accessibility — зелёные.
- Побочно закрыт **BUG-5** (`f8371ae`): карточка «Moderator-site: kill switch и доступы»
  перенесена внутрь `section-settings` (была вне секции → видна внизу каждой страницы).

## BOT-CHANNEL-UI — привязки ботов ↔ каналы + тестовые боты в реальной панели (запрос 12.09; BC-1/2/4 ✅ 12.09, BC-3 ⏳)

- [x] BC-1 (`2a8b974`). Смена канала у существующего бота: кнопка «Сменить канал» на карточке
  бота → модал со списком привязок (переименовать/удалить), выпадающий список каналов других
  ботов (перенос через PATCH /api/channels/{id} {account_id}) и создание нового канала.
- [x] BC-2 (`2a8b974`). Добавление канала боту из карточки бота (тот же модал); массовое
  действие «Сменить канал» в списке ботов НЕ делано — владелец не подтвердил массовость.
- [x] BC-4 (`b0192bc` backend + `2a8b974` UI). Полный CRUD каналов: создание (модал в секции
  «Каналы»), переименование (PATCH /api/channels/{id} с переносом channel-данных 20+ таблиц,
  конфликт UNIQUE → fail-closed `channel_data_conflict`, force — по подтверждению), удаление
  (GET /api/channels/{id}/dependencies → без force отказ `channel_has_dependencies`, force —
  с удалением зависимых строк), channel-overview отдаёт binding_id.
  Owning-тесты: tests/test_channel_admin.py (API), tests/test_bot_channel_ui.py (панель).
- [ ] BC-3. Перенести тестовых ботов из приёмочной панели (data/live-acceptance, инстанс
  DIR-LIVE) в реальную панель. ВАЖНО: у панелей РАЗНЫЕ TOKEN_ENCRYPTION_KEY — прямое
  копирование строк БД даст нешифруемые токены; нужен перенос с расшифровкой ключом приёмки
  и шифрованием ключом реальной панели (или повторный OAuth-логин ботов в реальной панели).
  ⏳ Требует участия владельца (ключи/OAuth), в песочнице не выполнимо.
- Примечание: история чата/статистика «пустые после тестов» — это НЕ баг: приёмка работала
  в изолированном data-root (DIR-LIVE-10), реальная панель не трогалась намеренно.

## AI-BUDGET — переключатели внимания бота (запрос 12.09, ✅ выполнен: AB-1…AB-3)

У каждого бота есть настройка «на что обращать внимание» — переключатели ИСТОЧНИКОВ
анализа. Платный AI тратится только на включённые источники:

- [x] AB-1 (`03c9d53` + `7987cb5`). Переключатели внимания на боте — карточка
  «🎯 Источники внимания (платный AI)» в общей вкладке настроек бота (рядом с
  «Быстрыми настройками», где observation_only): **Стрим Vision**
  (attention_vision), **Стрим слух** (attention_hearing), **Чат AI-анализ**
  (attention_chat_ai); хранение — analyzer_settings аккаунта (дефолт всех
  трёх = вкл, поведение существующих ботов не меняется); под карточкой
  зарезервировано место под будущие источники (события/донаты — текст-заглушка).
- [x] AB-2 (`03c9d53`, тест `test_raw_chat_log_written_with_chat_ai_off`).
  Сырой лог чата пишется ВСЕГДА: chat_log пишет `bot_manager._log → log_message`
  ДО chat-анализатора и от переключателей не зависит.
- [x] AB-3 (`03c9d53`). Отключённый источник = 0 запросов платной модели:
  chat-AI — гейт вверху `ChatAnalyzer._generate_and_send` (единственная точка
  `self.ai.generate_text` чат-ответов, вкл. батчи/авто-чат/провокации);
  vision — `_capture_frame` не качает кадр и не дёргает модель; слух —
  `_capture_audio` не захватывает аудио/транскрипт; beep-конвейер —
  `BeepPipeline.start` отказом `attention_hearing_disabled`, если у
  бота-владельца (cfg.account_id) слух выключен. Гейт читается на каждый
  тик/вызов — переключение действует сразу, без рестарта.
- Owning-тесты: tests/test_attention_budget.py (13 тестов); смежные
  test_moderation/test_roles_runtime/test_s7_reply_settings/test_voice_control/
  test_stream_vision_v102/test_chat_v102 + panel-labels/a11y/audit — зелёные.

Решение владельца 12.09: **AB-4 (лимиты запросов в минуту + бюджет-потолок
с авто-паузой) из плана убран** — не делать без нового явного запроса.

- [ ] BC-3. Перенести тестовых ботов из приёмочной панели (data/live-acceptance, инстанс
  DIR-LIVE) в реальную панель. ВАЖНО: у панелей РАЗНЫЕ TOKEN_ENCRYPTION_KEY — прямое
  копирование строк БД даст нешифруемые токены; нужен перенос с расшифровкой ключом приёмки
  и шифрованием ключом реальной панели (или повторный OAuth-логин ботов в реальной панели).
- Примечание: история чата/статистика «пустые после тестов» — это НЕ баг: приёмка работала
  в изолированном data-root (DIR-LIVE-10), реальная панель не трогалась намеренно.

## BUGS-LOG — диагнозы из логов панели 12.09 (исходная фиксация; исполнение — в разделе ниже)

Лог: основная панель, канал alekzz03 (вечер 12.09). Исходные диагнозы:

- BUG-1 (главный): массовые `400 widget_scope_required/widget_scope_not_found` на ВСЕХ
  scoped widget-API при `account_id=1&channel=alekzz03` — /api/widgets/{goals,sub-goal,
  now-playing,counters,countdown,donation-challenges,donation-integration,donation-bridge,
  subathon,song-request,lower-third,mascot,chat-roulette}, /api/widgets/public/recent-events,
  /api/widgets/public/mascot, POST /api/widgets/sub-goal/increment. При этом `/widget/*`
  страницы с теми же параметрами = 200. Скоуп канала не резолвится (channels/enabled?) —
  виджеты в превью пустые. Проверить наличие enabled-канала alekzz03 у аккаунта 1 и почему
  фронтенд шлёт нерезолвимый скоуп.
- BUG-2: poll-шторм — /api/widgets/public/recent-events дёргается параллельными
  iframe-превью каждые 0.5–2 с с cache-buster `t=` (десятки запросов/сек суммарно). После
  WIDGETS-UI шага 2 (ленивые группы) стихнет частично; рассмотреть общий poll-интервал/WS.
- BUG-3: `/favicon.ico` → 404 (косметика).
- [x] BUG-5 (исправлен `f8371ae` вместе с WIDGETS-UI): карточка «Moderator-site: kill switch и доступы»
  видна ВНИЗУ КАЖДОЙ страницы панели — стояла ПОСЛЕ закрывающего </section>; перенесена внутрь
  section-settings.
- BUG-6: Beep-фильтр мата (звук): владелец — «не работает». Настройки (источник/буфер,
  sink bot_beep_out, пип 1000 Гц, сегмент 5 с) сохраняются, но конвейер не пипает. Диагностика:
  whisper не установлен → заявлен pass-through (пипов и не должно быть); проверить, создаётся
  ли sink, корректен ли pulse_source и запущен ли pipeline. Отдельно вопрос РАЗМЕЩЕНИЯ: сейчас
  кнопка в разделе «Боты» → настройка во вкладке «Чат»; владелец считает, что это должно быть
  либо виджетом, либо фичей модераторского бота — решить при исполнении.
- BUG-4: AI-провайдер недоступен — connect_tcp.failed localhost:11434 (Ollama не запущен),
  при включённом fallback панель регулярно стучится и ловит ConnectError.

## PROMPT-BASE — общая база запреток + декор сообщений без токенов (запрос 12.09, ✅ выполнен `42239b5`)

- [x] PB-1. Общая база в «Мозге»: карточка «🚫 Общая база запреток (все боты)»
  вверху вкладки — единый список запреток/правил, пишется один раз (одна
  запретка на строку, «#» = комментарий). Хранение: settings-kv ключ
  `prompt_base` (лимит 8000 симв.), API: GET/PUT `/api/prompt-base`
  (`app/routes_prompt_base.py`).
- [x] PB-2. Порядок сборки system prompt задокументирован и реализован:
  **база → персона/личный промпт бота → правила подсистем**. База инжектится
  в `_generate_and_send` ПЕРВОЙ (после A/B-варианта, до персона-блока), поэтому
  при конфликте содержания личный промпт сильнее (идёт позже), но база —
  жёсткий минимум. База видна и в brain-preview (`prompt_base_chars`).
- [x] PB-3. Декор исходящих сообщений НА УРОВНЕ ПАНЕЛИ (0 токенов): на боте
  поля «Эмодзи в начало/в конец» (в Быстрых настройках, `outgoing_emoji_prefix/
  suffix` в analyzer-настройках); применение — `BotManager._decorate_outgoing`
  в `send_message_detailed` перед отправкой в Twitch (лимит 500 считается по
  декорированному тексту). Команды («!») не декорируются; пусто = no-op;
  идемпотентно.
- Owning-тесты: tests/test_prompt_base.py (9); смежные brain-preview/chat — зелёные.

## BUGS-LOG — баги из логов панели 12.09 (исполнено 12.09 `54c0880` по запросу владельца)

- [x] BUG-2 (poll-шторм): TTL-кэш публичного `/api/widgets/public/recent-events`
  (успех 3 c / ошибка 1 c — 400-е тоже кэшируются, шторм отказов срезан) +
  iframe-превью recent-events опрашивают раз в 15 c вместо 5 c.
- [x] BUG-3 (favicon): сгенерирован `static/favicon.ico` (16×16), роут
  `/favicon.ico` в server.py, `<link rel="icon">` в base.html.
- [x] BUG-4 (Ollama connect_tcp.failed): circuit breaker локального fallback
  в AIService — после 3 неудач подряд вызовы Ollama пропускаются 5 минут
  (один warning вместо потока), успех сбрасывает счётчик. Проверка статуса в
  панели (`ollama_status`) не гейтится.
- [x] BUG-6 (beep «не работает»): главная причина — воркер конвейера
  ИГНОРИРОВАЛ настройки beep-фильтра из БД (beep_settings: enabled/
  sensitivity/custom_words/per-channel) и работал только на дефолтном словаре.
  Теперь воркер раз в 60 c перечитывает настройки, уважает enabled и
  per-channel флаги, передаёт словарь/чувствительность. Плюс честный
  `whisper_state` (unknown/unavailable/ready) в статусе. ВАЖНО: без
  установленных whisper (`pip install openai-whisper`) пипов быть не может —
  pass-through заявляется честно в UI; на машине владельца whisper нужно
  поставить. РАЗМЕЩЕНИЕ (виджет vs фича модератора) — не менялось: настройка
  осталась во вкладке «Чат».
- [x] BUG-1 (widget_scope_required на alekzz03, acc=1): точную причину в живой
  БД проверить нельзя из песочницы (точная причина — в живой таблице channels),
  но обе половины контракта починены: (а) фронт больше не предлагает каналы
  выключенного бота (в селекте ботов выключенные помечены ⏸, их каналы не
  подставляются — именно они давали нерезолвимый скоуп); (б) сервер кэширует
  400 widget_scope_* на 1 c — шторм отказов прекращён. Проверить вживую: у
  аккаунта 1 канал alekzz03 должен быть enabled (таблица channels), либо
  выбрать этот канал у бота, которому он реально принадлежит.
- Owning-тесты: tests/test_bugs_log.py (9: кэш успеха/ошибки, favicon,
  breaker open/reset/skip, beep status/settings).

# Необязательно / потом

Неактуальные на 12.09 идеи (MODSITE-доки, OPTIONAL-03…10, внешние gates) — в архиве:
[docs/archive/PLAN_TODO_2026-09-12.md](docs/archive/PLAN_TODO_2026-09-12.md). Возвращать
только по явному запросу владельца.

---

# HANDOFF — контекст для следующей сессии (12.09, вечер: AI-BUDGET + PROMPT-BASE + BUGS-LOG)

## Сделано за сессию (коммиты на main, тесты зелёные)

- `03c9d53`/`7987cb5` AI-BUDGET AB-1…3: переключатели внимания (vision/hearing/chat_ai)
  + гейты 0 платных запросов; `8ebe88e`/`9a077c3` план (AB-4 убран по решению владельца).
- `42239b5` PROMPT-BASE PB-1/2/3: общая база запреток в «Мозге» (settings-kv
  `prompt_base`, GET/PUT `/api/prompt-base`), порядок сборки system prompt
  база→персона→правила (инжекция в `_generate_and_send` + brain-preview),
  эмодзи-декор исходящих (`BotManager._decorate_outgoing` в `send_message_detailed`,
  поля в Быстрых настройках бота). Owning-тест `tests/test_prompt_base.py` (9).
- `2a1061c` WIDGET-SCOPE: пер-виджетный канал — селектор на карточке виджета,
  override в localStorage, действует на превью/лайтбокс/OBS-URL/настройки
  (waWidgetStateUrl извлекает family из пути). Owning-тест
  `tests/widget_scope_override.test.js` (8).
- `54c0880` BUGS-LOG (по явному запросу владельца «все что осталось чини»):
  BUG-2 TTL-кэш recent-events (3 c/1 c) + превью-поллинг 15 c; BUG-3 favicon
  (static/favicon.ico + роут + link); BUG-4 circuit breaker Ollama-fallback
  (3 неудачи → пауза 5 мин, успех сбрасывает); BUG-6 воркер beep-конвейера
  читает beep_settings (enabled/sensitivity/custom_words/channels) + честный
  whisper_state; BUG-1 фронт не подставляет каналы выключенного бота (⏸ в
  селекте). Owning-тест `tests/test_bugs_log.py` (9).

## Что осталось (приоритет)

1. **Живая проверка на машине владельца**: BUG-1 — РЕШЕНО ВЖИВУЮ 12.09: единственный
   бот панели test_bot (id=1) был enabled=0 → скоуп account_id=1 не резолвился.
   Владелец решает: включить test_bot (если нужен) или пользоваться новыми ботами;
   BUG-6 — установить whisper (`pip install openai-whisper`), иначе beep честно
   работает в pass-through; проверить, что после фиксов 400-шторм в логах прекратился.
2. **Открытые вопросы владельцу**: массовое «Сменить канал» (BC-2 «массово?»);
   размещение beep-настройки (виджет vs модератор) — не менялось.
3. Director-конфиг для test_channel в реальной панели (режиссёр streamer_director + lurker
   streamer_lurker) — создать через UI «Режиссёр» при необходимости (провайдер и роли
   уже в панели).

## WIDGET-SCOPE — пер-виджетный канал (запрос 12.09, ✅ выполнен `2a1061c`)

Запрос владельца: «надо чтобы я в виджетах отдельно канал ставил» — один общий
селектор бота/канала на все виджеты недостаточен.

- [x] На карточке каждого виджета (в тулбаре превью) — селектор «Канал этого
  виджета»: по умолчанию «канал из общего выбора», можно выбрать любую пару
  (бот · канал) из включённых ботов. Выбор сохраняется в localStorage
  (`widgetScopeOverrides`, ключ = family виджета) и переживает перезагрузку.
- [x] Override действует на ВСЁ, что связано с этим виджетом: превью-iframe,
  лайтбокс «🔍 Увеличить», «↗ В новой вкладке» (теперь со скоупом, с фолбэком
  на публичный URL), OBS-URL (top-donator, design-URL), и настройки виджета —
  все они идут через `waWidgetStateUrl`/`wstateapi`, который сам извлекает
  family из пути ('/widget/goals' или '/api/widgets/goals[|public/…]') и
  подставляет override вместо общего скоупа.
- [x] Протухший override (бот/канал удалён) честно забывается, селект
  возвращается на «общий выбор».
- Owning-тест: tests/widget_scope_override.test.js (8: family-экстракция,
  fallback, приоритет override, public-пути, невалидные значения, нормализация
  «#», пустой скоуп). test_widgets_ui_cards.py обновлён под waWidgetBestUrl.

## BC-3 — перенос тестовых ботов в реальную панель (✅ выполнен 12.09)

Владелец предоставил свежие токены и ключ провайдера (переданы только в память
процесса / шифрованную БД, в git не попали):

- Токены опознаны через Twitch OAuth validate: `streamer_director` (режиссёр, полный
  набор скоупов chat:edit/read + channel:*) и `streamer_lurker` (lurker, chat:read/edit).
- Реальная панель (data/bot.db): создан аккаунт **streamer_director** (id=3, enabled,
  роль chatter), аккаунт **streamer_lurker** (id=4, enabled, роль lurker,
  observation_only=1), обоим добавлен канал **test_channel** (enabled, vision выкл
  по умолчанию — включается владельцем в UI).
- Провайдер **demo_provider** (custom_providers id=1): base `https://api.demo_provider.ru/v1`,
  модели chat+vision `gpt-5.6-luna`, enabled. Проверен живым вызовом
  `generate_text_with` — ok, ответ за 2.1 c.
- Живая проверка панели (run.py, порт 8000, ~1 мин): оба бота подключились к
  IRC — `[streamer_director] Подключён к: test_channel`, `[streamer_lurker] Подключён к: test_channel`,
  0 реконнектов. Инстанс остановлен; панель запускается владельцем как обычно.
- Примечание: TOKEN_ENCRYPTION_KEY у реальной панели не настроен — токены
  лежат как раньше (loopback-only политика); настройка ключа — отдельное
  решение владельца.

## Технические заметки

- Правки `static/app.js` — точечные (i18n-словари RU/EN/UA в трёх блоках ~240/385/528).
- `tests/test_channel_admin.py`: схему создаёт `init_db()` в `_client()`; FK требует
  явного создания аккаунта (`_ensure_account`), chat_log имеет колонку `author`, не `username`.
- panel-labels резал регион widgets по маркеру `<!-- Решение владельца 31.08` — после
  переноса субатона конечный маркер заменён на `<details ... data-widget-group="catalog">`.
- beep-тестам нужна схема beep_settings: `await beep_guard.ensure_schema()`.
- Circuit breaker AIService: `_fallback_healthy/_note_fallback_result`, порог/кулдаун —
  `FALLBACK_FAIL_THRESHOLD`/`FALLBACK_FAIL_COOLDOWN`.
- Узнать состояние сессии: `git log --oneline -8` в twitch-ai-bot/ и этот файл.
