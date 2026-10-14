# REVIEW_MASTER_PLAN — полное ревью проекта (мастер-план)

> **Что это.** Единый управляющий план тотального ревью репозитория `twitch-ai-bot`.
> Его задача — методично перепроверить **весь** код и файлы на: (1) мусор, (2) нерабочий/
> неиспользуемый код, (3) сомнительный/спорный код, (4) подтверждённый рабочий и нужный код.
> На выходе мастер-план порождает **четыре классификационных под-плана** + отдельный трек по виджетам.
>
> **Статус 05.09.2026:** ✅ audit/classification pass выполнен; coverage и восемь выходных
> документов созданы. Исправления и owner-gated DELETE/MERGE решения продолжаются по
> `REVIEW_EXECUTION_PLAN.md`. Запись без ссылки на конкретный файл/символ и воспроизводимого
> доказательства остаётся гипотезой, а не выводом.
> **Правила проекта:** [`docs/PRODUCT_RULES.md`](PRODUCT_RULES.md), зоны — [`../FILE_ZONES.md`](../FILE_ZONES.md),
> активный продуктовый план — [`../PLAN_TODO.md`](../PLAN_TODO.md). Ревью НИЧЕГО не удаляет само:
> каждое удаление — отдельный коммит + профильные тесты + подтверждение владельца. Главный gate:
> **каждый tracked-файл и каждая публичная функция должны попасть в реестр покрытия ровно один раз**.

---

## 0. Масштаб и критерий абсолютного покрытия (снимок 05.09.2026)

| Область | Объём | Заметка |
|---|---|---|
| Весь репозиторий | **555 tracked-файлов** | denominator после добавления review-артефактов |
| `app/*.py` | **143 модуля** | backend, integrations, storage, runtime |
| Фронтенд | **18 JS-файлов** в `static/`, **14 templates** | DOM, API wiring, i18n, auth/error states |
| Виджеты | **32 active contracts/folders + 5 retired + 1 alias** | проверить routes/cards/previews/legacy URL |
| Тесты | **224** `tests/test_*.py` | качество тестов проверяется отдельно от наличия |
| Документация | **65 tracked-файлов** в `docs/` | active truth, archive, stale links, decisions |
| Корень | **20 tracked-файлов** | entrypoints, Compose/Docker, manifests, vendor artifacts |

Перед первым этапом числа переснимаются и записываются в `docs/REVIEW_COVERAGE.md`; snapshot выше не
заменяет живой инвентарь. Ревью завершено только если одновременно выполнено:

- [x] 100% `git ls-files` имеют owner/domain, тип, назначение и один вердикт A/B/C/D;
- [x] 100% Python modules/public symbols получили path/symbol verdict; HTTP/WS routes, JS entrypoints/listeners/fetches,
      templates, DB tables/columns, scripts и widget contracts связаны с потребителем или finding;
- [x] сумма A+B+C+D равна denominator, нет `unreviewed` и дублей;
- [x] все P0/P1 findings имеют отдельную задачу; каждый DELETE/MERGE требует решения владельца;
- [ ] coverage пересчитан после каждого удаления/переноса, чтобы работа не «исчезла» из реестра.

---

## 1. Методология и стандарт доказательства

Каждый объект проходит **восемь независимых проверок**, результат заносится в coverage-реестр и
один из под-планов §3–§6.

1. **Инвентарь:** путь, тип, domain/owner, entrypoint, runtime-профиль, данные и внешние зависимости.
2. **Статическая достижимость:** import/call graph; router inclusion; route ↔ fetch/form; template ↔ selector;
   event producer ↔ consumer; startup ↔ shutdown; CLI/script ↔ documented caller.
3. **Динамическая работоспособность:** focused test, import/compile, fake API/emulator, browser runtime,
   empty/error/reconnect/restart. «Тест существует» не равно «функция работает».
4. **Контракт и данные:** request/response/WS schema, account+channel scope, idempotency, migration,
   FK/index/retention/backup/restore, legacy URL/row compatibility.
5. **Безопасность и приватность:** auth/roles, mutation exposure, SSRF/path traversal/XSS,
   secret masking, token scope, webhook verification, logs/exports, unsafe defaults.
6. **Надёжность:** timeout/retry/backoff, duplicate events, stale sockets/tasks, cancellation, locks,
   process restart, partial failure, rate limits, cleanup and observability.
7. **Продукт/UI:** пользовательский путь, отсутствие placebo/dead controls, RU/EN/UA,
   dark theme, keyboard/mobile/accessibility, preview и OBS readability.
8. **Ценность/стоимость:** соответствие `PRODUCT_RULES`/решениям owner, overlap, dependency/license
   burden, maintenance cost и измеримая польза.

### 1.1. Что считается доказательством

- **Сильное:** runtime trace/focused test, воспроизводимый browser/API сценарий, DB query до/после.
- **Среднее:** однозначный import/call/route graph плюс контрактный тест соседнего уровня.
- **Слабое:** grep, имя файла, комментарий, старый plan или единственный self-test — только повод проверить.
- Для «не используется» обязательны минимум два независимых поиска: symbol/route/event/data writer-reader;
  dynamic imports, decorators, Jinja strings и compatibility entrypoints проверяются вручную.
- Каждый finding получает `ID`, `severity P0–P3`, `confidence high/medium/low`, owner, evidence,
  affected contracts, proposed action, test plan и rollback. Нельзя удалять по одному grep.

> **Границы:** audit-коммиты меняют только review-документы. Исправления идут позже отдельными
> маленькими коммитами. Production tokens/DB/provider calls запрещены; runtime — только fake `local`.
> Полный suite не заменяет focused tests и запускается только по отдельному решению владельца.

---

## 2. Нулевая фаза: инвентарь до любых вердиктов

Сначала создаётся `docs/REVIEW_COVERAGE.md`, без решений об удалении. В нём отдельные таблицы:

- tracked paths: все 546 файлов, включая docs/assets/vendor/config/tests;
- backend symbols/routes/tasks and DB tables: producer, consumers, tests, scope;
- routes разделяются на `panel`, `public OBS`, `external ingress/webhook`, `callback`, `admin`,
  `compatibility`, `retired placeholder`: отсутствие panel `fetch()` само по себе не означает dead code;
- frontend/templates: entrypoint, selectors, API/events, i18n keys;
- widget contracts: inventory/folder/card/preview/public route/data/bindings/legacy aliases;
- dependencies/integrations: declaration, import/use site, license, offline seam, secret scopes;
- test map: test → production behavior; отдельно tests без production target и code без tests.

Начальные **кандидаты**, а не готовые выводы: `get-pip.py`, `templates/index_v10_backup.html`,
split/migration/render scripts, архивные docs, generated assets/caches, orphan media и compatibility
wrappers. Для каждого сначала доказать provenance, caller, retention/legal reason и rollback.

---

## 3. ПОД-ПЛАН A — МУСОР (файлы/артефакты, не участвующие в работе)

**Цель:** файлы, которые можно удалить/заархивировать без влияния на код и тесты.
**Как наполняется:** §2 + сканирование на: `*_backup*`, `*_v10*`, `*.bak`, дубли корень↔archive,
разовые скрипты миграций уже выполненных, пустые/`.gitkeep`-заглушки, осиротевшие ассеты виджетов.
**Формат записи:** `ID | path/glob | provenance | bytes | почему мусор | evidence | references |
runtime/data impact | archive/delete | rollback | owner decision`.
**Проверки перед вердиктом:** grep ссылок по всему дереву (кроме `get-pip.py`/`docs/archive`), запуск
`tests/test_plan_file_zones.py` если трогаем файлы из зон.

Разделы для наполнения:
- [ ] A1. Корневые и `docs/archive` дубли, stale snapshots и битые ссылки — без предположения, что archive = мусор.
- [ ] A2. Бэкап-файлы шаблонов/кода (`index_v10_backup.html`, любые `*_backup`).
- [ ] A3. Разовые/выполненные скрипты (`scripts/migrate_legacy_data.py`, `scripts/p5_split_*`,
      `scripts/panel_review_render.py`) — проверить, не нужны ли повторно.
- [ ] A4. Вендорные артефакты (`get-pip.py`).
- [ ] A5. Осиротевшие widget/media assets, generated screenshots/logs/cache, пустые dirs и `.gitkeep`.
- [ ] A6. Неиспользуемые dependencies, Docker layers, env keys, Compose services и platform scripts.
- [ ] A7. Тестовые fixtures/data, случайно tracked secrets/binaries и файлы без license/provenance.

---

## 4. ПОД-ПЛАН B — НЕРАБОЧИЙ / НЕИСПОЛЬЗУЕМЫЙ КОД

**Цель:** код, который не вызывается, не подключён, падает или является плацебо (пишет, но никто не читает).
Завершённые исторические находки из `PLAN_TODO.md ТРЕК 1` повторно не выдаются за текущие дефекты;
они используются как шаблоны доказательства writer-without-reader/placebo/dead route.
**Как расширяем на весь код:**
- [ ] B1. Роуты без вызова из UI: для каждого `@router` в `app/*routes*.py` найти `fetch`/ссылку в
      `static/`+`templates/`, OBS, Twitch/provider callback и documented external caller; сначала
      назначить route class из §2, затем составлять список действительно неподключённых endpoints.
- [ ] B2. Функции без вызывающих (кроме тестов): grep каждого публичного `def` по `app/`; отсеять API-хендлеры.
- [ ] B3. Импорты/модули без потребителей: модуль в `app/`, который никто не импортирует и не роутит.
- [ ] B4. `app.js`-секции, чьи кнопки/события отсутствуют в шаблонах.
- [ ] B5. Виджеты без данных/биндинга (preview пустой, событие не приходит) — «нерабочий виджет = баг» (PRODUCT_RULES).
- [ ] B6. Тесты, которые тестируют только сами себя (единственный вызывающий мёртвой функции — тест).
- [ ] B7. Writer-without-reader/read-without-writer: DB columns, settings, env vars, cache keys, events.
- [ ] B8. Неподключённые startup/shutdown tasks, reconnect loops, exception branches и cleanup.
- [ ] B9. Код, который reachable, но всегда падает/возвращает фиктивный success или нарушает auth/scope.
- [ ] B10. Несовпадения публичных API/WS payload с UI/виджетом и legacy compatibility regressions.
**Формат:** `docs/REVIEW_DEAD_CODE.md`: `ID | symbol/path | kind | reachability evidence |
runtime evidence | data/contracts | severity/confidence | fix/delete plan | focused tests | rollback`.
**Правило:** каждый пункт = отдельный коммит; сначала код → потом его тесты → grep остаточных ссылок.

---

## 5. ПОД-ПЛАН C — СОМНИТЕЛЬНЫЙ / СПОРНЫЙ КОД (нужно решение)

**Цель:** код, который технически работает, но польза/нужность под вопросом — решает владелец, не агент.
Кандидаты (наполняется в ходе ревью):
- [ ] C1. Working feature без подтверждённого owner-value или понятного пользовательского пути.
- [ ] C2. Дублирующие реализации (`mood` vs `mood_engine`, `blur-guard` vs `blur-guard-v2`,
      `tts` vs `tts-bot`, три `top-donator-*`) — оставить одну/смёржить/оставить как есть?
- [ ] C3. MERGE-кандидаты виджетов из `RESEARCH_WIDGETS.md` (`mascot`↔`anime-runner`, emoji 34/35).
- [ ] C4. Тяжёлые модули с внешними зависимостями без тестов (`stream_vision`, `voice_clone`,
      `diarization`) — рабочие ли в проде, стоит ли поддерживать.
- [ ] C5. Экспериментальные фичи из `app/` без места в `PLAN_TODO.md`/`PRODUCT_RULES.md`.
- [ ] C6. Слишком сложные abstraction/fallback/cache, premature optimization, broad exception handling.
- [ ] C7. Privacy/security/operational trade-off, который нельзя менять без product decision.
- [ ] C8. Dependencies/providers с высокой стоимостью, неизвестной лицензией или слабой offline test seam.
**Формат:** `docs/REVIEW_QUESTIONABLE.md`: `ID | feature | current behavior/evidence | почему спорно |
usage/cost/risk | варианты keep/merge/delete/redesign | recommendation | owner question`.
Открытые вопросы дублируются в [`docs/OPEN_QUESTIONS.md`](OPEN_QUESTIONS.md) (правило вопросов — PRODUCT_RULES §4).

---

## 6. ПОД-ПЛАН D — РАБОЧИЙ И НУЖНЫЙ КОД (подтверждённое ядро)

**Цель:** зафиксировать, что реально работает, используется и нужно — чтобы это НЕ трогали при чистке.
**Критерий включения:** доказана достижимость и owner-value, есть runtime evidence, проверены
failure/security/data contracts и назван focused regression guard. Просто импорт или зелёный unit-test недостаточны.
- [ ] D1. Ядро бота: `bot_manager`, `ai_service`, `chat_analyzer`, `multi_bot_chat`, `tts_engine` — с ссылкой на зелёные тесты.
- [ ] D2. Панель/роутинг: `server.py`, `routes.py` + активные `*_routes.py` (только те, чьи эндпоинты дергаются из UI).
- [ ] D3. Данные/память: `database.py`, `user_memory`, `shared_user_facts`, `summarizer` (per-channel).
- [ ] D4. Рабочие виджеты: из текущих 32 active contracts — те, у кого живой preview + данные,
      а также намеренные compatibility/retired URL как отдельные защищаемые контракты.
- [ ] D5. Инфраструктура: `bootstrap`, `instance_lock`, `backup`, `maintenance`, `run.py`.
- [ ] D6. Security/data boundaries: auth, secrets, migrations, backup/restore, exact scope и audit logs.
- [ ] D7. Tests/tooling/docs, которые реально защищают production contract и onboarding.
**Формат:** `docs/REVIEW_KEEP.md`: `ID | module/feature | purpose | consumers | runtime evidence |
failure/security/data guarantees | tests | dependencies | owner-value | protected contracts`.

---

## 7. Трек виджетов (ревью + сурсы аналогов)

База уже есть: [`docs/RESEARCH_WIDGETS.md`](RESEARCH_WIDGETS.md) (источники R0.1–R0.6 + таблица contracts)
вердиктов) и [`docs/WIDGET_IMPLEMENTATION_PLAN.md`](WIDGET_IMPLEMENTATION_PLAN.md) (waves 0–7).
Ревью-трек **не переписывает** их, а перепроверяет и дополняет сурсами:
- [ ] W-R1. Сверить живой denominator: 32 active folders/contracts, 5 retired и 1 alias ↔ panel cards,
      admin/public/OBS routes, previews, tests и 3 legacy top-donator URL. Сейчас ожидается 41
      публичный address contract; любое расхождение после живого пересчёта — finding.
- [ ] W-R2. Для каждого виджета: живой ли `preview_url`, тёмный ли, есть ли данные и биндинг
      (иначе → под-план B «нерабочий виджет = баг»).
- [ ] W-R3. Для **каждого** active/retired/alias contract добавить source card: конкретный URL,
      владелец/продукт, дата доступа, feature compared, что заимствуем, что не заимствуем, license,
      privacy/data model и применимость к CEF/OBS Browser Source.
- [ ] W-R4. Дубли/MERGE-кандидаты → под-план C (`mascot`/`anime-runner`, emoji 34/35, три `top-donator`).
- [ ] W-R5. Итог по каждому виджету: KEEP / MERGE / DELETE / доделать, с acceptance-критерием из
      `WIDGET_IMPLEMENTATION_PLAN.md`.
- [ ] W-R6. Runtime matrix: loading/representative/empty/error/reconnect/reload; 1920×1080, 1280×720,
      mobile panel preview; transparent OBS background, device-pixel ratio, long RU/EN/UA text.
- [ ] W-R7. Event/data matrix: producer, dedup/order, account+channel scope, stale state, restart,
      WebSocket/HTTP fallback, multi-Browser-Source duplication, audio autoplay and cleanup.
- [ ] W-R8. Control matrix: form → saved setting → live update; semantic binding whitelist; hotkey/
      command/reward permissions; no dead or duplicate controls.
- [ ] W-R9. Visual/accessibility comparison: hierarchy, contrast, safe areas, animation duration,
      reduced motion, font fallback, clipping and readability over light/dark gameplay.

Минимальный реестр authoritative sources (проверить доступность и зафиксировать дату доступа):

- OBS Browser Source/CEF: https://github.com/obsproject/obs-browser/ и https://obsproject.com/kb/browser-source;
- StreamElements Custom Widget: https://docs.streamelements.com/overlays/custom-widget;
- Twitch Polls/EventSub: https://dev.twitch.tv/docs/api/polls/ и
  https://dev.twitch.tv/docs/eventsub/eventsub-subscription-types/;
- Streamlabs widgets: https://streamlabs.com/content-hub/support/alerts-and-widgets;
- Streamer.bot actions: https://docs.streamer.bot/guide/core/actions;
- Sound Alerts/Mix It Up — конкретные queue/cooldown/permission docs, не marketing homepage.

Коммерческие galleries (OWN3D/Nerd or Die) — только визуальный benchmark. GitHub-пример допустим
только после фиксации commit/tag и LICENSE; текущий `adkostka/spotify-obs-overlay` считать
непроверенным до отдельной проверки. Чужой код, assets и CSS не копируются.

> Static review не может дать KEEP-вердикт виджету: обязательны fake `local` panel preview,
> public/OBS URL и browser runtime. Финальный визуальный gate в реальной OBS остаётся за владельцем.

---

## 8. Порядок исполнения

1. **Freeze + inventory:** зафиксировать base SHA и denominator, создать coverage tables; никаких вердиктов.
2. **Infrastructure/data/security:** entrypoints, setup/run, env/secrets, DB/migrations, auth, backup/restore.
3. **Backend domains:** accounts/channels → bot/chat/AI/memory → moderation → TTS/audio → events/donations → analytics.
4. **Frontend contract pass:** каждый template/selector/event/fetch/i18n key сопоставить backend contract.
5. **Widget pass:** W-R1–W-R9 по одному contract; source research и runtime evidence в том же шаге.
6. **Tests/tooling/docs/dependencies:** false-green tests, missing tests, scripts, Docker/Compose, archives/licenses.
7. **Cross-cutting failure pass:** restart, concurrency, dedup, timeouts, offline, invalid data, multi-account isolation.
8. **Classification reconciliation:** заполнить A/B/C/D, устранить `unreviewed`/duplicates, owner-вопросы — в OPEN_QUESTIONS.
9. **Execution backlog:** findings разбить на маленькие dependency-ordered commits; сначала P0/P1 defects,
   затем safe trash/dead code, только после owner decision — questionable/merge/delete.

## 9. Инварианты (не нарушать)

- Ревью само по себе НЕ удаляет и НЕ правит рабочий код; оно только классифицирует и предлагает.
- Один файл может содержать несколько symbol-level вердиктов, но path-level итог обязан быть один;
  mixed-файл получает D/C и отдельные B findings на символы, а не искусственное удаление файла.
- Каждое удаление — отдельный маленький коммит, только профильные focused-тесты, grep остаточных ссылок.
- Тесты не ослабляем; при падении чиним причину, а не тест.
- БД-схему/таблицы на этапе ревью не трогаем (только роуты/модули/UI-хвосты — как в `PLAN_TODO.md ТРЕК 1`).
- Production credentials/calls запрещены; integration evidence строится на fake profile/stubs/emulators.
- Нельзя считать code dead только потому, что он compatibility, plugin callback или вызывается строкой.
- Полный `pytest` — только по явному «поехали» владельца; focused tests обязательны на каждый finding.
- Чужие сессионные зоны (`FILE_ZONES.md`) правит только владелец файла зоны.

## 10. Артефакты на выходе

При исполнении мастер-план порождает:

1. `docs/REVIEW_COVERAGE.md` — полный denominator и доказательство 100% покрытия.
2. `docs/REVIEW_TRASH.md` — A: файлы/артефакты, безопасные кандидаты на delete/archive.
3. `docs/REVIEW_DEAD_CODE.md` — B: broken/dead/placebo/unsafe code с воспроизведением.
4. `docs/REVIEW_QUESTIONABLE.md` — C: working, но спорное; варианты и вопросы владельцу.
5. `docs/REVIEW_KEEP.md` — D: подтверждённое рабочее ядро и защищаемые контракты.
6. `docs/REVIEW_WIDGETS.md` + дополнения `RESEARCH_WIDGETS.md` — contract/runtime/source matrix.
7. `docs/REVIEW_RUNTIME.md` — дата, environment/profile, browser/OBS/manual evidence и ограничения.
8. `docs/REVIEW_EXECUTION_PLAN.md` — dependency-ordered backlog исправлений после решений owner.

## 11. Definition of Done всего ревью

- [ ] coverage gate 100%, counts воспроизводятся командами и совпадают между таблицами;
- [ ] каждый B finding воспроизводится, каждый D item имеет runtime evidence, каждый C item имеет вопрос;
- [ ] widget matrix покрывает все active/retired/alias routes и источники с лицензиями;
- [ ] P0/P1 не спрятаны среди cleanup; public API/OBS/DB compatibility перечислена явно;
- [ ] owner утвердил DELETE/MERGE решения; до этого код не удалён;
- [ ] execution plan содержит шаг, focused tests, grep, migration/rollback и размер риска;
- [ ] после исполнения отдельным циклом пересняты coverage, fake browser/runtime и документация.
