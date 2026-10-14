# REVIEW_EXECUTION_PLAN — dependency-ordered backlog

> Audit baseline завершает классификацию, но runtime-код меняется только маленькими отдельными
> коммитами. Public OBS URLs, legacy rows/columns и compatibility payloads не удаляются молча.

| Step | Findings / dependency | Change | Focused gate | Rollback |
|---|---|---|---|---|
| E00 | reports | Зафиксировать восемь review-документов, coverage denominator и owner decisions. | generator idempotence, link audit, file-zone test | docs-only revert |
| E01 ✅ | SEC-B01, OPS-B01, C-001 | Fail-closed panel/backup, `.dockerignore`; plaintext credential storage только при loopback-only запуске с явным startup/UI warning. | security/launcher/backup/container-context tests | local-only plaintext; no secret export |
| E02 ✅ | SEC-B02 | Require verified donation ingress secret and stable webhook event ID; legacy URL остаётся configuration-required. | global/scoped secret + persistent replay/cross-scope/provider restart tests | retain URL, disable mutation |
| E03 ✅ | DATA-B03 | Startup больше не удаляет legacy tables/rows; cleanup остаётся отдельным owner-approved migration. | legacy DB init fixture | no destructive rollback |
| E04 ✅ | CORE-B01 | Engagement считает реакции в exact account+channel scope. | `tests/test_engagement.py` + two-account case | query revert |
| E05 ✅ | CORE-B02, CORE-B03 | AI-quality, prompt counters и learning mutations требуют matching account ownership. | two-account DB/API negative matrix | per-module commits |
| E05a ✅ | Snippet ownership | Update/delete требуют matching `account_id`; panel использует scoped URL, legacy URL без scope fail-closed. | two-account API negative matrix + legacy compatibility scope | retain legacy URL with mandatory query scope |
| E06 ✅ | UI-B01 | Last.fm secret write-only/masked, password field, empty means keep. | widget source API + production-JS behavior + DOM tests | masked compatibility response |
| E07 | UI-B02 | Safe DOM rendering legacy `/obs-widget`. | browser/JS XSS payload test | preserve URL/schema |
| E08 ✅ | W-B02 | Beep guard использует canonical widget-bus `source` signature; real bus test проверяет duck lifecycle. | real bus duck lifecycle | adapter commit |
| E09 ✅ | RT-B01, RT-B02 | Task ownership/shutdown и truthful EventSub status/retry исправлены. | lifespan pending-task test; reconnect suite | cancellation/status commits |
| E09a ✅ | C-002 | Device Code poll только для локально начатой pending-сессии; terminal/token-success consume session. | unknown code no-provider-call; terminal/success lifecycle tests | retain start/poll URL and payloads |
| E09b ✅ | C-004 | Нормализовать role enum fields и nested stream-tool modes к canonical values/defaults. | invalid enum matrix + role API/runtime tests | retain role JSON/default compatibility |
| E09c ✅ | C-005 | Удалять завершённые BatchBuffer timer handles без race с replacement timer. | same-channel fire/drain/reuse test | retain callback/cancel API |
| E09d ✅ | EventSub chat | `channel.chat.message` получает обязательный bot `user_id`; toggle chat-флага пересобирает subscriptions, не выключая основной EventSub. | fake Helix payload + disable/restart API tests | retain flag/endpoint and non-chat subscriptions |
| E09e ✅ | EventSub reconnect | При `session_reconnect` старый socket продолжает принимать notifications до welcome нового socket; migrated subscriptions не создаются повторно. | concurrent old/new fake socket + cross-handoff dedup | fallback retry keeps old socket alive |
| E09f ✅ | C-009 Python graph | Добавить universal Python 3.10+ core lock; launchers, Docker, dev и ML extras переиспользуют exact graph. | clean 3.10/3.11 installs + `pip check` + manifest guard | direct ranges remain in `requirements.txt`; regenerate/revert lock independently |
| E10 ✅ | W-B01 | Владелец подтвердил protected per-channel output для moderator-media вне public inventory; plaintext token masked/reveal-30s, manual rotation, immediate revoke, safe preview. | `test_w7_preview_contracts` + token/preview/backup tests | protected exception, URL intact |
| E11 🔶 | W-B03 | Владелец выбрал channel-scoped Widget Bus: payload/subscribers/listeners менять атомарно; data widgets fail-closed без `channel`, decorative widgets не блокировать. | two-channel WS/media/chat dedup + missing/disabled/renamed channel tests | local rollback restores documented global bus |
| E12 🔶 | UI-B03..06, C-013 | Owner contract: panel canonical dark, widget theme только в preview, RU/EN/UA с RU fallback, full dialog/keyboard/focus/aria accessibility и content width 1400–1600. | focused DOM/Node/static tests; fake browser RU/EN/UA/mobile только после «поехали» | per-surface commit |
| E13 | test-contract list | После доказательства runtime invariants обновить stale tests и APP_JS_MAP; reuse i18n keys. | перечисленные пять files зелёные | restore stronger invariant |
| E13a ✅ | stale widget guards | Проверять post-loader layout/assets и shared selected-chat `?api=` behavior вместо исходных byte/literal markers. | widget folder/API-base/scale-position suites | preserve loader and shared-core invariants |
| E13b ✅ | C-015 | Синхронизировать widget README с canonical inventory/sizes и compatibility/protected contracts. | exact README-registry equality + route existence | registry remains source of truth |
| E13c ✅ | C-016 | Проверить dynamic/compatibility purpose и удалить 13 single-reference helpers без callers. | focused owning-module suites + residual symbol grep | restore individual helper only with caller/contract |
| E13d ✅ | C-010 Poll/Prediction | Заменить JS source-marker assertions offline VM behavior tests: limits, commas, scope, seconds conversion и cancel confirmation. | Node VM executes production functions + template/i18n contracts | restore static guard only for non-runtime markup |
| E13e ✅ | C-010 Attention config | Заменить panel symbol marker offline VM behavior tests: scoped load/save, full payload, trimming/clamps и no-account guard. | Node VM executes production `loadBotAttention`/`saveBotAttention`; backend round-trip remains separate | retain template/i18n static contracts only |
| E13f ✅ | C-010 Widget admin forms | Заменить `wa2LoadAll` symbol marker offline VM behavior tests: scoped lower-third/roulette payloads, parsing, preview refresh, session/recent actions и absent-card guard. | Node VM executes production §24 panel functions; endpoint/template contracts remain separate | retain non-runtime markup inventory only |
| E13g ✅ | C-010 Last.fm source form | Заменить source-marker assertions offline VM behavior tests: raw secret не рендерится, save отправляет введённый key один раз и очищает password input, absent-card guard. | Node VM executes production `waNpSourceLoad`/`waNpSourceSave`; backend round-trip отдельно доказывает empty-means-keep | retain password input markup contract |
| E13h ✅ | C-010 dirty-state guard | Исполнить реальное beforeunload, cancel/accept внутренней навигации, bindDirtyWatch idempotence и save/clear lifecycle. | Node VM executes production `markDirty`/`confirmDirty`/`bindDirtyWatch`, `closeBotSettings`, `showSection`; i18n ×3 остаётся static contract | restore only the replaced source-marker tests |
| E13i ✅ | C-010 Analytics state | Исполнить full analytics init-chain и success/empty/error states без вечной «Загрузка...». | Node VM executes production `showSection`, `loadAnalytics`, logs, heatmap, chat24h и feedback loaders; markup/i18n остаются static contracts | restore only the replaced source-marker tests |
| E13j ✅ | C-010 Stream Tools visibility | Исполнить moderator/non-moderator/failure branches: мёртвая форма и история скрыты при `ok=false`, возвращаются при `ok=true`. | Node VM executes production `loadStreamTools`; ids/CSS остаются static contracts | restore only the replaced source-marker tests |
| E13k ✅ | C-010 custom AI providers | Исполнить refresh/stale-selection/create/edit/validation/failure/cache lifecycle в global и per-bot AI selects. | Node VM executes production custom-provider functions; settings-card markup остаётся static contract | restore only the replaced source-marker tests |
| E13l ✅ | C-010 OBS instruction modal | Исполнить open/replace/backdrop-close, canonical URL/size/defaults, slug params и escaping. | Node VM executes production `showWidgetInstr`; registry-driven button/i18n ×3 остаются static contracts | restore only the replaced source-marker tests |
| E14 ✅ | OPS-B02/03, DOC-B01 | Startup no-browser, canonical logs и browser-smoke exit codes синхронизированы с документацией. | subprocess/runtime/docs contract tests | per-file revert |
| E15 🔶 | A/C decisions | Owner answers recorded: delete seven artifacts after caller proof; archive review generator bundle and recovery migration; legacy DB data never auto-delete. Выполнять по одному. | grep + профильный focused test + coverage regenerate | one delete/archive commit each |
| E16 ⏸ | final acceptance | Full critical fake-browser RU/EN/UA/mobile + real OBS/CEF/widget/audio/device gate выбран, но запуск заблокирован до явного owner «поехали». | no JS/HTTP/toast errors; coverage 100% | reopen finding |

## Owner decisions — статус 08.09

1. ✅ Moderator media: отдельный protected per-channel output, не public inventory widget.
2. ✅ Public sub-goal/counter mutation: loopback-only compatibility (C-003).
3. 🔶 Widget Bus: channel scope (не account scope); реализация pending единым payload/listener step.
4. ✅ Plaintext credential storage: документированный local-only режим с warning.
5. 🔶 Cleanup: owner выбрал DELETE A-001..A-006 и route-split часть A-007 после caller proof;
   review JSON+generator — ARCHIVE together; legacy migration script — recovery-only archive.
6. Полная запись решений и новых product contracts: `OWNER_DECISIONS_2026-09-08.md`; оставшиеся
   вопросы — `PLAN_TODO.md` Track 8Q.
