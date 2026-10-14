# Архитектура и постоянные контракты

> Этот документ объясняет устройство текущей системы. Он не является планом.
> Что делать дальше: [`PLAN_TODO.md`](../PLAN_TODO.md). Почему выбран контракт:
> [`DECISIONS.md`](DECISIONS.md).

## 1. Границы системы

Панель — локальное FastAPI-приложение владельца. Она управляет несколькими Twitch bot accounts,
их каналами, AI/TTS, moderation и OBS Browser Source widgets.

Основные слои:

- `run.py` — поддерживаемый launcher и effective bind;
- `app/server.py` — lifecycle и подключение routers;
- `app/routes.py` + `app/*_routes.py` — owner API, public outputs и token-protected surfaces;
- `app/database.py` и feature schema modules — SQLite source of truth;
- `app/bot_manager.py` / `app/chat_analyzer.py` — Twitch runtime и message processing;
- `app/ai_service.py` — provider/model selection;
- `app/widget_bus.py` — runtime events для OBS widgets;
- `static/` + `templates/` — owner panel;
- `widgets/` — OBS outputs и shared browser cores.

## 2. Доступ

### Локальный режим

- Default bind: `127.0.0.1`.
- Прямой loopback-клиент открывает owner panel/API/WebSocket без пароля.
- Public OBS URLs доступны только согласно своему route/token contract.
- Plaintext credential storage разрешён только в loopback/fake-QA mode и сопровождается warning.

### Сетевой режим

Non-loopback bind разрешён только при наличии:

- `PANEL_AUTH_USER`;
- `PANEL_AUTH_PASS`;
- `TOKEN_ENCRYPTION_KEY`.

Basic auth без HTTPS не является transport encryption; внешний reverse proxy/TLS требует отдельного
эксплуатационного решения. Partial network config не открывает сервер наружу.

### Router classes

Каждый HTTP/WebSocket surface относится к одной категории:

1. owner/control — общий panel access policy;
2. public OBS output — read-only или capability-token contract;
3. moderator session — Twitch-verified short-lived session/grants;
4. local compatibility ingress — direct loopback + scoped token/idempotency.

Новый router нельзя подключать без явной категории.

### HTTP error contract

- v13 принимает legacy `200 + {ok:false}` и новый HTTP 4xx envelope
  `{"ok":false,"error":{"code":"...","params":{...}}}`.
- `code` стабилен и технический, `params` содержит только безопасные JSON primitives; панель переводит
  известные codes на RU/EN/UA, а неизвестные показывает как generic safe error.
- Validation, route errors и uncaught exceptions проходят через общие handlers. Raw exception text и
  traceback остаются только в server logs; клиент получает `internal_error`.
- Active bot role и её validated config атомарно сохраняются через `PUT .../role-config`; удалённый
  legacy `PUT .../role` callers не имел.
- Пустой per-bot TTS config GET возвращает effective global TTS values вместе с per-bot defaults,
  `configured:false` и не создаёт row.

## 3. Scope и идентичность

- Bot settings и ownership используют stable `account_id`.
- Stream/runtime data привязываются к normalized Twitch channel; где доступен Twitch channel ID, он
  является стабильной внутренней идентичностью.
- User permissions используют stable Twitch user ID, не display name/badge.
- Новые multi-channel contracts не выбирают «первый enabled account/channel» как fallback.
- Legacy rows/URLs остаются отдельными compatibility surfaces, а не неявным fallback для новых paths.

## 4. База и миграции

- SQLite и существующие settings APIs остаются source of truth.
- Schema evolution additive: `CREATE TABLE IF NOT EXISTS`, additive columns/tables и idempotent migration.
- Startup не удаляет legacy tables/rows.
- Destructive cleanup запускается только владельцем после dry-run report и backup.
- Read API не должен создавать DB rows только ради effective defaults.
- Mutation ownership проверяется в SQL/feature layer по exact account/channel scope.

## 5. Секреты и backups

- Twitch/provider access tokens шифруются Fernet, если задан `TOKEN_ENCRYPTION_KEY`.
- В local-only mode plaintext допустим с видимым предупреждением.
- UI не возвращает raw access tokens; secret inputs masked/write-only, если решение владельца не задаёт
  explicit reveal contract.
- Backup содержит scoped donation/moderator tokens и raw Director evidence для полного restore.
  По `DEC-BACKUP-002` отдельный warning/confirmation перед export не показывается; import остаётся local-only.
  Backup zip включает `data/director/**` (per-file cap); restore валидирует пути и восстанавливает
  содержимое/размеры/hashes, а не только manifest.
- Cache/temp никогда не является source of truth и не восстанавливается как конфигурация.

## 6. Twitch message pipeline

1. Bot accounts получают Twitch events/messages.
2. Channel message ID дедуплицируется для общей widget/event проекции.
3. Сообщение сохраняется в channel-scoped chat log/context.
4. Role/attention/noise/cooldown определяют, может ли конкретный AI-бот рассмотреть ответ.
5. AI generation использует account/channel prompt, memory и provider settings.
6. Outgoing moderation проверяет сгенерированный текст до send.
7. Успешный ответ публикуется в Twitch и нужные widget/TTS paths.

Упоминание/Reply разрешает ответ, но не гарантирует его. Moderator и voice companion имеют отдельные
role-trigger exceptions из `DEC-BOTS-001`.

## 7. AI и prompts

- Global provider settings применяются только без account override.
- Custom providers входят в те же global/per-bot selects.
- Ollama может быть primary provider; её недоступность не включает cloud автоматически.
- Prompt состоит из стабильной system policy и scoped blocks: role/persona, channel/streamer context,
  corrections, memory, current chat/stream context и capability boundaries.
- Secret values и raw internal exceptions не добавляются в prompts.
- ML-heavy Vision/speech/clone функции — explicit experimental opt-in.
- Director имеет отдельный server-owned replay/quality gate для конкретных prompt, config и effective
  provider/model endpoint. Suggest сохраняет одобренные примеры и не отправляет сообщения; подробный
  реализованный API и его ограничения — в [`specs/DIRECTOR.md`](specs/DIRECTOR.md#15-реализованный-review-workflow-dec-director-009).

## 8. TTS и audio

- Общий transport/queue переиспользуется режимами `tts`, `tts-bot`, `chat-reader` и
  `tts-chat-overlay`.
- Channel audio воспроизводится последовательно: два голоса не звучат одновременно.
- Policy определяет source, role/user grants, approved voice aliases, cooldown и output device.
- Public audio read/output routes не получают owner mutation permissions.
- Необратимое audio действие не изображается как undoable state mutation.

## 9. Widgets

### Canonical inventory

`app/widget_inventory.py` является machine-readable source of truth для active, retired, alias,
legacy-param и protected output routes. `widgets/README.md` — user-facing projection.

У active widget есть:

- stable slug/route;
- OBS width/height/layout;
- preview URL/mode;
- empty/loading/error behavior;
- dark host/background contract;
- binding/source metadata, если он интерактивный.

Public OBS URLs нельзя удалять молча. Retired/alias/legacy behavior описывается в registry.

### Data ownership

- Config и persisted state: SQLite/API.
- Approved media artifacts: feature-owned directories под `data/`.
- Browser memory/WebSocket cache: ephemeral.
- Widget directory не хранит secrets, SQLite copies или replacement config snapshots.
- File write: temporary upload → validation → atomic rename → DB reference; при DB failure новый
  file/reference откатывается.
- Orphan cleanup удаляет только доказанно неиспользуемые artifacts.

### Media Share и внешний YouTube player

- Media Share получает текущий элемент из channel-scoped модерируемой Song Request queue, а YouTube
  IFrame API загружается только в реальном OBS output, не в безопасном panel preview.
- Перед первым копированием/подключением output панель показывает RU/EN/UA предупреждение; факт
  подтверждения хранится глобально в `settings` и может быть сброшен из Настроек.
- В YouTube уходят video ID/request metadata и обычные browser/OBS network данные. Доступность,
  embed и autoplay определяются YouTube, браузером и OBS, а не локальной панелью.
- Queue/API offline, IFrame load/embed/autoplay failures и Widget Bus reconnect имеют отдельные
  видимые состояния. Provider error показывается до перехода к следующему элементу; reconnect
  использует один retry timer и игнорирует события устаревшего WebSocket.
- Источник запроса и модерация остаются в Song Request audit; успешная позиция queue не считается
  доказательством фактического воспроизведения во внешнем player.

### Widget Bus contract

Реализованный контракт `DEC-BUS-001`:

- scope — Twitch channel;
- event/data widget URL обязательно содержит `channel`;
- decorative widgets не требуют channel;
- unknown/disabled/missing channel показывает локализованную диагностику;
- один stable event/message ID исполняется один раз независимо от количества bot accounts;
- panel observer без параметра `channel` видит общий поток, а widget subscription с пустым/невалидным
  параметром закрывается fail-closed;
- stable Twitch ID и текущий login разрешаются в legacy storage scope без удаления старых строк.

### Protected moderator output

`/widget/moderator-media` находится вне reusable inventory. Новые per-channel tokens хранятся plaintext
локально вместе с compatibility hash: это позволяет masked/reveal-30s UI и полный restore старого URL.
Legacy hash-only rows продолжают валидировать известный владельцу URL, но требуют ручной rotation для
reveal. Secret actions и backup/restore доступны только loopback owner; safe preview не получает token и
не читает protected runtime state.

## 10. Widget bindings

Одна каноническая форма объясняет binding как:

1. где работает;
2. когда срабатывает;
3. что делает.

- Binding scope всегда explicit account + normalized channel.
- Action выбирается из allowlist.
- User-supplied identifiers/aliases нормализуются и валидируются.
- Backend повторно проверяет permissions и target scope.
- Compatibility URLs/actions не дают cross-channel fallback.

## 11. Donations

- DonatePay, DonateX и DonationAlerts имеют отдельные loops, write-only tokens, status/reconnect и
  persistent last success в exact `(account_id, normalized channel)` scope.
- Provider tokens хранятся через Fernet при наличии `TOKEN_ENCRYPTION_KEY`; loopback plaintext mode
  честно показывается в панели. Обычный API возвращает только mask/status.
- Provider event превращается в canonical donation event один раз по
  `(account_id, channel, provider, stable event_id)`; receipt сохраняется через reconnect/restart.
- Donation event обновляет только scoped top-donator, goals/challenges, subathon и event widgets.
- Local webhook — optional loopback bridge, не публичный интернет webhook. Он требует exact scope и
  отдельный per-channel token; reveal/copy скрываются через 30 секунд, rotation сразу отзывает старый.
- Provider failure не останавливает остальные providers/widgets; status и reconnect честные.

## 12. Moderator console

- Owner admin управляет grants и invite/session lifecycle из localhost panel.
- Moderator проходит Twitch verification и получает short-lived scoped session.
- Permission не выводится только из moderator/VIP/sub badge; используется exact granted Twitch user ID.
- Media/sound/TTS permissions независимы.
- Owner имеет audit и emergency stop.
- Moderator session/token routes не наследуют owner panel privileges.

## 13. Privacy

- Глобального «privacy mode», который скрывает UI, но оставляет backend side effects, нет.
- Sensitive inputs остаются password fields и masked API contracts.
- Blur Guard — отдельный OBS protection feature, не замена storage/access policy.
- Stream Vision frames/transcripts подчиняются feature retention settings.
- Cloud AI получает только данные, явно предусмотренные выбранным feature/provider contract.

## 14. UI, i18n и accessibility

- Панель canonical dark; widget theme видна только в preview/output.
- RU/EN/UA покрывают все user-visible controls/status/errors; fallback — русский.
- Technical codes/logs не переводятся; UI переводит stable error code+params.
- Modal keyboard contract: dialog semantics, initial focus, Tab trap, Escape, return focus.
- Dynamic status/error regions используют `aria-live`.
- Shared panel dialog lifecycle находится в `static/app/22_panel_accessibility.js`; feature close
  callbacks сохраняют собственную очистку OAuth/Media Share/onboarding. Background inert и focus
  восстанавливаются при закрытии, включая вложенные диалоги.
- Widget UI locale передаётся в copy/preview URL как `ui_lang=ru|en|ua`; `uk` также принимается.
  Без `ui_lang` сохраняется legacy `lang` для widget UI, кроме `/obs/tts`: там `lang` всегда означает
  язык речи, а UI по умолчанию русский. Неизвестная locale использует RU.
- `widgets/_shared/i18n.js` загружается перед output scripts через `_widget_html`. Widget dictionaries
  локальны своему output; перевод использует выбранный язык → RU → безопасный текст без technical key.
  В HTML украинский обозначается `lang=uk`. Scope diagnostics используют тот же приоритет URL locale.
- Названия, сообщения и подписи, заданные владельцем/зрителями, не переводятся. Пустой незаданный
  заголовок получает client-localized default; сохранённый текст, даже совпадающий с RU default,
  сохраняется без изменений.

## 15. Lifecycle и observability

- Каждая background task имеет одного владельца и cancel/await path.
- Reconnect не создаёт duplicate subscriptions/events.
- Status отражает реально живую task/connection, а не только сохранённую настройку.
- Audit log хранит actor, scope, action, result и safe details без secrets.
- `/healthz` — публичный data-free process liveness; feature readiness показывается отдельными statuses.

## 16. Источники дальнейших требований

- Active work: [`PLAN_TODO.md`](../PLAN_TODO.md).
- Owner choices: [`DECISIONS.md`](DECISIONS.md).
- Director: [`specs/DIRECTOR.md`](specs/DIRECTOR.md).
- Future moderator site: [`specs/MODERATOR_SITE.md`](archive/docs_specs_MODERATOR_SITE.md).
- Widget inventory: [`../widgets/README.md`](../widgets/README.md) и `app/widget_inventory.py`.
