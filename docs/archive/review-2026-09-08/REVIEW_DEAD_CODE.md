# REVIEW_DEAD_CODE — B: broken, unsafe и неработающий код

> Срез 05.09.2026. Это findings полного ревью, а не разрешение на несовместимые изменения.
> Поля `test` и `rollback` обязательны; порядок исправления — в `REVIEW_EXECUTION_PLAN.md`.

## P0/P1

| ID | Sev / confidence / owner | Evidence и воспроизведение | Контракт и исправление | Test / rollback |
|---|---|---|---|---|
| SEC-B01 | P0 / high / security | `app/security.py:113-123`: auth включается только при наличии обеих env-переменных, иначе запрос разрешён. `app/routes.py:2604-2608` выдаёт backup с `.env`, `app/backup.py:82-86` кладёт его без маскирования. | Панель и backup/restore должны fail-closed вне явного loopback-only local режима; secret export — только opt-in. | Matrix no-env/partial/full auth; backup без секретов. Rollback: `PANEL_ALLOW_INSECURE_LOCAL=1`, принимаемый только на loopback. |
| SEC-B02 ✅ | P1 / high / widgets-security | Исправлено: legacy/scoped webhook требует constant-time global/scoped secret и стабильный `event_id`; пустая конфигурация и id-less ingress не мутируют state. | Additive persistent receipts атомарно дедуплицируют `account + normalized channel + source + event_id`; provider reconnect/restart не повторяет известные ID. | Empty/invalid/valid global/scoped secret, replay, cross-scope, retry и provider restart tests. Rollback: совместимый URL сохраняется configuration-required без mutation. |
| DATA-B03 ✅ | P1 / high / database | Исправлено: startup migration не выполняет destructive cleanup и сохраняет legacy tables/rows до отдельного owner-approved migration. | Additive-only R-ДАН2 соблюдён; автоматических `DROP TABLE` больше нет. | Init legacy DB с rows подтверждает сохранность. Rollback не нужен. |
| CORE-B01 ✅ | P1 / high / engagement | Исправлено: response window фильтруется по exact `account_id + channel`, поэтому одноимённый канал другого account не влияет на метрики. | Scope сохранён в aggregation query. | Два account на одном channel; B не влияет на A. Rollback: query-only revert. |
| CORE-B02 ✅ | P1 / high / AI quality | Исправлено: row update/delete, feedback и prompt variant counters проверяют `id + account_id`; foreign IDs дают 404/false до side effects. | Account ownership обязателен во всех mutation paths. | DB/API two-account negative tests. Rollback: совместимые list/create не меняются. |
| CORE-B03 ✅ | P1 / high / learning | Исправлено: suggestion lookup/apply/reject/revert используют account из URL и отклоняют foreign IDs. | Scope всех suggestion mutations по URL account. | Cross-account apply/reject/revert fail. Rollback: route/query commit. |
| W-B01 ✅ | P1 / high / widgets | Исправлено: `/widget/moderator-media` зарегистрирован в `PROTECTED_WIDGET_OUTPUTS`, а data manifest фиксирует exact scope и rotated-token boundary. Канонический reusable preview намеренно не создаётся. | Protected moderator output exception; URL и owner-generated Browser Source сохранены. | `test_w7_preview_contracts` + token/route test в `test_moderator_media_routes.py`. |
| W-B02 ✅ | P1 / high / beep/widget bus | Исправлено: beep guard вызывает canonical `duck_start(source=..., reason=...)` и `duck_end(source=...)`; тест исполняет настоящий widget bus вместо permissive fake signature. | Canonical bus signature сохранена без legacy adapter. | Real bus duck start/end lifecycle. Rollback: изолированный caller commit. |
| UI-B01 ✅ | P1 / high / widgets-frontend | Исправлено: API возвращает только `has_lastfm_api_key`, password input остаётся write-only, load не рендерит даже неожиданное raw поле, save очищает value, пустой PUT сохраняет прежний key. | API round-trip + offline production-JS behavior + password DOM contract. Rollback: status+masked response, никогда raw secret. |
| UI-B02 | P1 / high / frontend-security | `app/routes.py:2503`: legacy `/obs-widget` вставляет author через unsafe `innerHTML`; message экранируется неполно. | Создавать text nodes / применять единый HTML escape для author и message. | Browser WS payload с `</span><img onerror>` не создаёт nodes. Rollback: сохраняется URL/payload shape. |
| RT-B01 ✅ | P1 / high / runtime | Исправлено: lifespan хранит, cancel и await все loop handles; EventSub producer останавливается перед drain event/raid tasks; donation parent в `finally` останавливает goal-sync и platform children. Всё завершается до bot shutdown/`close_db`. | Все task handles имеют одного владельца; disabled donation integration отменяется сразу. | `test_runtime_task_lifecycle.py`; rollback — cancellation-only. |

## P2/P3

| ID | Sev / confidence | Evidence / defect | Action and verification |
|---|---|---|---|
| RT-B02 ✅ | P2 / high | Исправлено: client start возвращает readiness, manager хранит только task-backed client, status проверяет live task, stale client можно перезапустить. | Missing-config и stale-task restart закрыты focused tests; reconnect URL contract сохранён. |
| UI-B03 | P2 / high | `static/app.js:1804` и `static/app.css:35`: полноценная light theme против R-UI3. | Удалить/нейтрализовать toggle; persisted `light` всё равно даёт dark; browser test. |
| UI-B04 | P2 / high | Hardcoded visible RU в `static/app/13_widgets_session.js:585`, `11_brain_v16.js:110`, `08_providers_moderation.js:414`, `static/app.js:2174`, `templates/partials/widgets.html:564-595`. | Перевести через существующий i18n ×3; static + RU/EN/UA browser checks. |
| UI-B05 | P2 / medium | `templates/base.html:27-29`: observation modal без dialog semantics, focus trap, Escape и return focus. | Keyboard accessibility flow. |
| UI-B06 | P2 / high | `templates/partials/widgets.html:978-991`: registry cards рендерят RU strings без i18n и iframe contract не доказывает computed dark background. | Локализовать catalog fields ×3; computed-style browser matrix. |
| W-B03 🔶 | P2 / high | `app/widget_bus.py` и data-widget listeners пока global; владелец 08.09 выбрал channel scope (общий для bot accounts одного Twitch-канала), mandatory `channel` для event/data widgets и localhost-only bus. | Payload/subscriber/listeners менять атомарно; two-channel WS/media/chat-dedup + missing/disabled/rename tests. |
| OPS-B01 ✅ | P1 / high | Исправлено: versioned `.dockerignore` исключает `.env*` (кроме `.env.example`), Git/Hoplite state, virtualenv/cache, DB sidecars, logs, artifacts и runtime data. | Scratch-image behavior test подтверждает, что безопасный source и `.env.example` входят, а fake secrets/runtime data отсутствуют в фактическом Docker build output. |
| OPS-B02 ✅ | P2 / high | Исправлено: `run.py` уважает `TWITCH_BOT_NO_BROWSER` от `start.sh` и прямой `--no-browser`; browser thread не создаётся. | Launcher flag/env contract test. |
| OPS-B03 ✅ | P3 / high | Исправлено: runtime, сообщение об ошибке и README используют единый `logs/panel.log`. | Canonical log path test. |
| DOC-B01 ✅ | P3 / high | Исправлено: README документирует фактические exit codes smoke (`0` success, `1` panel failures, `2` missing Playwright/environment failure). | Runtime test симулирует отсутствие Playwright и связывает code 2 с README contract. |

## Test-contract failures (не чинить ослаблением продукта)

- `tests/test_widgets_folder.py`: 6 failures после sanctioned bounded-layout injection в
  `app/widgets.py:105`; route HTTP/runtime smoke проходит. Тест должен проверять invariant после
  отдельного подтверждения wrapper, а не byte-for-byte opening tag.
- `tests/test_widget_api_base.py`: `selected-chat` использует общий `ChatMessageCore.apiBase()` вместо
  literal `_WIDGET_API_BASE`; функциональный transport прошёл.
- `tests/test_p8_b_widgets.py::test_w1_zones_live_update`: static guard ожидает inline `always_zones`,
  хотя behavioral payload test проходит.
- `tests/test_p3_app_js_map.py`: `docs/APP_JS_MAP.md` не содержит новых section markers.
- `tests/test_p3_ux_standard.py`: 14 duplicate i18n values; использовать canonical keys, не allowlist.
