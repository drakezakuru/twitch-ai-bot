# Модераторский сайт

Здесь находится весь комплект проектной документации отдельного сайта модераторов.
**Сайт ещё не реализован.** HTML/JS/Python, упомянутые в деревьях и примерах, являются будущими файлами.

Основой выбран независимый подробный план, сверенный с текущим backend. Из дополнительных материалов
включены только проверенные улучшения: asset versions, восстановление login после потерянного ответа,
output-instance lifecycle и проверки гонок. Это один вариант, а не две склеенные спецификации.

## С чего начать

| Документ | Что находится внутри |
|---|---|
| [SPECIFICATION.md](SPECIFICATION.md) | Продукт, дизайн, дерево файлов, функции, API, права, редактор, queues, существующий код и его ограничения |
| [IMPLEMENTATION.md](IMPLEMENTATION.md) | 25 этапов MOD-00…MOD-24: зависимости, изменения, focused gates и безопасные границы commits |
| [ACCEPTANCE.md](ACCEPTANCE.md) | Команды тестирования, security/race matrix, критерии готовности и browser/OBS gates |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Конфигурация, HTTPS/proxy, packaging, наблюдаемость, backup/restore и rollback |
| [CONTRACT_INVENTORY.md](CONTRACT_INVENTORY.md) | Default-deny guard: инвентарь owner-маршрутов и allowlist MOD-03 |

Активный статус проекта остаётся в [PLAN_TODO.md](../PLAN_TODO.md), раздел MODSITE.
Подробные инструкции редактируются в этой папке, а не копируются в корневой план.
Решение о собственной площадке и расположении документации: [DEC-MODSITE-001](../docs/DECISIONS.md#dec-modsite-001-отдельный-модераторский-сайт-и-его-документация).

## Карта файлов: что где живёт

| Место | Содержимое | Почему не в этой папке |
|---|---|---|
| `moderator-site/` | фронтенд (`index.html`, `src/`, `package.json`, `vite.config.ts`, lock) и вся проектная документация | — |
| `app/moderator_site_bridge.py` | закрытый bridge внутри процесса панели | работает с БД/хелперами панели; путь задан в MOD-03 |
| `app/moderator_site_contract.py` | инвентарь маршрутов + default-deny guard | проверяет живой `app.server` |
| `app/moderator_site_schema.py` | `ms_*` таблицы (revisions, outbox, stop state) | точечный вызов из `init_db` (правило AGENTS) |
| `app/moderator_site_identity.py` | login-транзакции и cookie-сессии | панельный компонент |
| `app/moderator_site_permissions.py` | grants/scoпы, owner revoke (MOD-07) | панельный компонент |
| `app/moderator_site_library.py` | read-only проекция библиотеки, DTO без путей/токенов (MOD-09) | панельный компонент |
| `app/moderator_site_uploads.py` | upload quarantine, checksum, bounded processor (MOD-10) | панельный компонент |
| `app/moderator_site_cues.py` | cue admission: fingerprint, bounds, stop check, audit (MOD-13) | панельный компонент |
| `app/moderator_site_media.py` | media dispatcher: current-command lifecycle, per-cue placement (MOD-14) | панельный компонент |
| `app/moderator_site_sound.py` | soundboard adapter: correlation/dedup/stop scope (MOD-15) | панельный компонент |
| `app/moderator_site_tts.py` | TTS adapter: voice policy, cancellable late-result (MOD-16) | панельный компонент |
| `app/moderator_site_outputs.py` | executor lease + output evidence (MOD-17) | панельный компонент |
| `moderator-site/src/design/tokens.ts`, `src/i18n.ts` | design tokens, i18n RU/EN/UA (MOD-08) | фронтенд — здесь |
| `moderator-site/src/editor/geometry.ts`, `src/editor/editorState.ts` | pure geometry, editor state (MOD-11/12) | фронтенд — здесь |
| `gateway/` (`main.py`, `routes.py`, `bridge_client.py`, `security.py`) | отдельный ASGI-процесс | не импортирует `app.server`; путь задан в MOD-03 |
| `tests/test_moderator_site_*.py` | gate-тесты (contract/gateway/schema/identity/security/permissions/library/uploads/cues/media/sound/tts/outputs) | конвенция репо: тесты в `tests/` |
| `docs/specs/MODERATOR_SITE.md` | исходная спека | DEC-MODSITE-001 |

Frontend и документация — исключительно здесь; backend осознанно разделён на «панельный»
(`app/`) и «отдельный процесс» (`gateway/`), чтобы gateway не импортировал `app.server`.

## Выбранный проектный baseline

- Отдельный frontend и собственный дизайн в `moderator-site/`, без owner panel CSS/JS.
- Vite + TypeScript и небольшие DOM-компоненты как основной вариант этого плана.
- Отдельный moderator gateway и закрытый typed bridge к существующему локальному runtime.
- Существующие approved libraries, Soundboard и TTS переиспользуются, второй audio engine не создаётся.
- Owner API не публикуется через wildcard proxy на localhost.
- Серверные sessions, exact grants, CSRF и audit проверяются backend, не только интерфейсом.
- `accepted/dispatched` не означает подтверждённое воспроизведение в OBS.

Стек, IPC и численные defaults являются инженерным предложением, а не уже реализованной системой
или подтверждёнными владельцем параметрами публичного развёртывания. Альтернативы не создаются
параллельно: при смене baseline синхронно меняются дерево, API, этапы и тесты.

## Что исправлено в проектных контрактах

- Stop доступен и при неизвестном результате playback; поздний ACK не отменяет остановку.
- Disable/re-enable grant не оживляет старые invites, login attempts и queued commands.
- Restore не возвращает старые browser sessions и не запускает историческую очередь.
- Версия материала фиксируется в cue и повторно проверяется перед исполнением.
- Старый media `complete` не обходит новый lease/ACK protocol.
- File/DB rollback, resource bounds, Unicode length и реальные renderer tests определены явно.

## Что не входит в этот commit

- Реализация frontend/backend сайта.
- Установка frontend packages или запуск dev server.
- Изменение действующих console/OBS URLs или перенос runtime/data.
- Открытие портов, tunnel, DNS/TLS или платных сервисов.
- Реальный Twitch, provider, browser, OBS и audio acceptance.

Первый шаг будущего исполнителя: MOD-00/MOD-01, затем один fake end-to-end сценарий.
Разрешение сохранить документацию в GitHub не означает разрешения начать runtime-разработку.
