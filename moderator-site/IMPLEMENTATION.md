# Модераторский сайт: порядок реализации

> Документация отдельного сайта, не готовая реализация.
> [Начало](README.md) · [Спецификация](SPECIFICATION.md) · [Исполнение](IMPLEMENTATION.md) ·
> [Приёмка](ACCEPTANCE.md) · [Развёртывание](DEPLOYMENT.md).
> Активный статус: [PLAN_TODO.md](../PLAN_TODO.md), раздел MODSITE.

## 14. Пошаговая реализация

Этапы ниже являются порядком будущей работы.
В репозитории их активные задачи должны находиться только в `PLAN_TODO.md`.
Каждый завершённый этап: focused tests, `git diff --check`, маленький commit в разрешённой ветке.
Если этап разрастается, разделить на проверяемые подэтапы, не коммитить незавершённый гигантский diff.

### MOD-00. Зафиксировать требования

Результат: выбор собственного сайта и отдельной папки записан без изменения старой истории.
Файлы: существующие DECISIONS/spec/PLAN.
Уточнить deployment, audio arbitration, право moderator Stop и retention.
Остальное использовать как предложенные defaults, не выдуманные ответы владельца.
Gate: docs tests и отсутствие второго активного checklist.

### MOD-01. Contract inventory и threat model

Результат: список existing/reused/new routes и таблица запрещённых remote surfaces.
Проверить все owner/admin/WS/frames/token/backup routes, не только console prefix.
Описать browser → gateway → bridge → runtime trust boundaries.
Выделить domain helpers из route code там, где иначе импортируется `app.server`.
Gate: тест remote app route manifest на default-deny.

### MOD-02. Scaffold отдельного frontend

Файлы: `moderator-site/package.json`, configs, `index.html`, `src/main.ts`.
Добавить scripts: `dev`, `build`, `typecheck`, `test:unit`, `test:components`, `test:e2e`.
Зафиксировать package lock и поддерживаемую Node версию в setup документации.
Не добавлять runtime calls в стартовый экран.
Gate: build/typecheck/unit smoke; в bundle нет panel CSS/JS или secrets.

### MOD-03. Отдельный gateway и закрытый bridge

Файлы: `gateway/main.py`, `routes.py`, `bridge_client.py`, `app/moderator_site_bridge.py`.
Создать отдельный ASGI app с явными methods и paths.
Не импортировать `app.server` из gateway.
Настроить UDS либо отдельный authenticated loopback listener.
Gate: denied owner routes, no wildcard forwarding, service credential checks.

### MOD-04. Schema и транзакционные primitives

Файлы: schema/models и точечный вызов из database init.
Добавить idempotent tables/indexes, revisions, outbox и stop state.
Проверить запуск миграций дважды и на legacy fixtures.
Gate: чтение старых данных сохраняется, GET не создаёт defaults.

### MOD-05. Login transaction и cookie session

Файлы: identity/sessions + auth routes.
Переиспользовать Twitch device adapter без передачи access token в JS.
Добавить nonce binding, expiry, cancellation, rate limits и grant version.
Gate: wrong user, wrong browser, duplicate exchange, expired invite, cookie flags.

### MOD-06. CSRF, origin, proxy trust

Файлы: gateway middleware/config и bridge auth dependency.
Exact origin validation и server-bound CSRF для всех browser mutations.
Host allowlist, trusted proxy list, request size/timeout bounds.
Gate: spoofed headers, Origin null, missing CSRF, encoded paths, wrong methods.

### MOD-07. Context, logout и permissions

Файлы: service/permissions, frontend session/workspace stores.
Добавить live enabled scope checks и logout.
Развести upload-only UI и play permissions.
Добавить owner session/invite revoke без публичной выдачи admin прав.
Gate: two-account/two-channel/two-user matrix и revoke во время открытой страницы.

### MOD-08. Design system и shell

Файлы: tokens/layout/components/i18n, header/pages.
Реализовать desktop/tablet/mobile структуру на fake data.
Создать buttons/dialogs/toasts/empty states с lifecycle.
Gate: keyboard/component tests, все новые строки RU/EN/UA.
Реальная browser visual acceptance пока pending.

### MOD-09. Read-only библиотеки

Файлы: API library adapters, grid/cards/preview, library store.
Добавить pagination, search, favorites и approved projection с dimensions.
Исключить tokens/paths из DTO.
Gate: чужой ID, unapproved item, empty/search/error, preview cleanup.

### MOD-10. Upload quarantine и owner review

Файлы: uploads service/schema/API и upload dialog.
Добавить bounded processor, checksums, safe thumbnails и recovery state.
Owner approval остаётся в локальной панели.
Gate: malformed files, oversized/decode bomb fixtures, DB failure, upload-only actor.

### MOD-11. Pure geometry и editor state

Файлы: geometry/constraints/presets/history.
Реализовать normalized coordinates, aspect ratio и unit conversions.
Gate: property/edge tests до DOM drag implementation.
Не менять existing output placement в этом этапе.

### MOD-12. Editor UI

Файлы: stage/selection/pointer/keyboard/inspector.
Реализовать один asset, handles, numeric controls, safe area, local undo.
Gate: pointer cancel, resize window, keyboard-only, zoom/layout invariants.
Отправки в runtime ещё нет.

### MOD-13. Durable cue admission

Файлы: cues/service/quota/outbox.
Создать новый POST contract и payload fingerprint.
Добавить bounds, policy revision, scope stop check и atomic audit.
Gate: concurrent duplicate, changed payload, queue full, revoked grant race.

### MOD-14. Media dispatcher и placement adapter

Файлы: dispatcher/media routes/OBS media template.
Новая per-cue placement не перезаписывает scope-wide legacy config.
Перевести media output на explicit current command lifecycle для new protocol.
Старый URL продолжает работать по compatibility contract.
Gate: enqueue/claim/expire/replace и renderer fake ACK tests.

### MOD-15. Sound adapter

Файлы: moderator sound routes/library и Soundboard renderer.
Повторно использовать библиотеку и existing dispatch path.
Добавить command correlation, dedup и safe status.
Gate: sound scope, restart ambiguity, stop scope и отсутствие double dispatch.

### MOD-16. TTS adapter

Файлы: voice policy, audio queue, dispatcher и TTS composer.
Убрать двойное quota/admission при адаптации старого пути.
Добавить correlation и cancellable late-result handling.
Gate: voice restrictions, unicode length, provider fake failure, stop during synthesis.
ML/models/cloud calls не требуются.

### MOD-17. Output evidence и executor lease

Файлы: outputs/events, media/sound/TTS renderer adapters.
Добавить limited ACK capability, generation и sequence validation.
Разделить observers и active executor.
Gate: two sources, stale generation, duplicate/out-of-order ACK, heartbeat loss.
Статус не называется реальным OBS acceptance.

### MOD-18. Cancel, Stop и owner kill switch

Файлы: cue transitions, output controls, admin routes и маленький owner UI block.
Развести cancel own, stop lane, persistent kill и revoke.
Добавить scope generation и блокировку late results.
Gate: restart после Stop, failure одного output, соседний канал не остановлен.

### MOD-19. Queue/history и SSE

Файлы: queue store/drawer/items/history page, events client.
Реализовать actor-filtered projection и snapshot/resume protocol.
Не раскрывать чужой TTS через общую очередь без права.
Gate: reconnect gaps, stale revision, session downgrade, long list pagination.

### MOD-20. Recovery и backup

Файлы: recovery, backup и focused fixtures.
Добавить media/sound artifacts в согласованный manifest.
После restore не восстанавливать активные browser sessions и не replay queued actions автоматически.
Существующие protected media URL tokens сохраняются по действующему решению.
Gate: restore на пустое временное хранилище, checksums, missing/corrupt artifact.

### MOD-21. Security и нагрузочные границы

Тестировать полноценное ASGI wiring без реального production listener.
Perimeter tests очищают QA bypass env и отдельно моделируют loopback/remote peer.
HTTP error tests используют production middleware, renderer tests исполняют actual renderer code,
а не упрощённую замену. Fake clocks/providers не подменяют проверяемый production algorithm.
Проверить path confusion, ownership, request bounds, rate limits, safe errors.
Измерить fake 100/1000-item library и burst admission, не использовать production DB.
Gate: bounded memory/tasks/queues, absence of secret data в responses/logs/build.

### MOD-22. Deployment runbook

Файлы: deploy examples, existing README/spec sections.
Добавить environment checks, service user, TLS, headers, health/readiness, rollback.
Public ingress по умолчанию disabled.
Owner invite link использует настроенный moderator public origin, не `location.origin` панели.
Gate: конфигурация не публикует owner port, readiness честный, invalid config fail-closed.

### MOD-23. Browser acceptance после разрешения

Только после явного разрешения владельца на browser run.
Fake backend/fixtures, никаких Twitch/provider/OBS действий автоматически.
Проверить RU/EN/UA, touch/desktop, computed layout, focus, uploads и retry.
Gate: список реальных browser evidence и оставшихся дефектов.

### MOD-24. Twitch/OBS/device acceptance после разрешения

Отдельно согласовать реальный канал, устройства и разрешённые side effects.
Проверить invite login, media placement, Soundboard, TTS, reconnect и Emergency Stop.
Проверить duplicate Browser Sources и соседний scope.
Gate: подтверждённые результаты на целевой системе, без выдачи fake tests за production.

### 14.1. Критический порядок зависимостей

```text
00 → 01 → 03 → 04 → 05 → 06 → 07
     └→ 02 → 08 → 09 → 11 → 12
                  └→ 10
04 + 07 → 13 → 14 / 15 / 16 → 17 → 18 → 19
10 + 18 + 19 → 20 → 21 → 22 → 23 → 24
```

Допустим параллельный design/frontend на fixtures и backend auth.
Нельзя параллельно менять общие schema/dispatcher без одного владельца контракта.
Красивый UI не является основанием пропустить MOD-03/06/18/20.
