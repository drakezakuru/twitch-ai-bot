# Модераторский сайт: сборка и развёртывание

> Документация отдельного сайта, не готовая реализация.
> [Начало](README.md) · [Спецификация](SPECIFICATION.md) · [Исполнение](IMPLEMENTATION.md) ·
> [Приёмка](ACCEPTANCE.md) · [Развёртывание](DEPLOYMENT.md).
> Активный статус: [PLAN_TODO.md](../PLAN_TODO.md), раздел MODSITE.

## 16. Deployment, наблюдаемость и восстановление

### 16.1. Предлагаемые настройки

```text
MODERATOR_SITE_ENABLED=false
MODERATOR_SITE_PUBLIC_ORIGIN=<approved HTTPS origin>
MODERATOR_SITE_DIST_DIR=<absolute dist path>
MODERATOR_SITE_BRIDGE_TRANSPORT=unix
MODERATOR_SITE_BRIDGE_SOCKET=<private socket path>
MODERATOR_SITE_BRIDGE_SECRET_FILE=<restricted secret file>
MODERATOR_SITE_TRUSTED_PROXY_IPS=<explicit allowlist>
MODERATOR_SITE_SESSION_TTL_MINUTES=55
```

Это новые предложенные env names, не уже существующая конфигурация.
Frontend `VITE_*` не содержит secrets: такие значения попадают в public bundle.
Только public API base/build version допустимы в frontend config.
Gateway secret не совпадает с OBS token или PANEL_AUTH_PASS.
Точный public origin нужен также для owner invite generation.

### 16.2. Reverse proxy checklist

- TLS обслуживает только согласованный moderator hostname.
- Upstream: отдельный gateway.
- Нет location fallback на owner API.
- Нет проброса `/frames`, `/docs`, `/openapi.json` owner приложения.
- Host validation включён и в proxy, и в gateway.
- Trusted proxy IPs заданы явно.
- Body limits согласованы с uploads.
- Timeouts не создают бесконечные pending requests.
- SSE buffering настроен отдельно.
- Access logs не содержат invite fragments/tokens/cookies.
- HSTS включается только после рабочей HTTPS конфигурации.

### 16.3. Headers

- `Cache-Control: no-store` для sessions/context/commands/private previews.
- Static hashed assets могут иметь immutable cache.
Release содержит prebuilt frontend; Node не нужен для обычного запуска панели.
Проверить лицензии dependencies и отдельно выбрать public sourcemap policy.
Editor/Studio lazy chunk; ориентир auth/shell до 250 KiB compressed JS проверяется измерением,
не является SLA и не оправдывает ухудшение accessibility.
- `Content-Security-Policy` без `unsafe-eval` и случайных external origins.
- `frame-ancestors 'none'` для самого moderator site.
- `X-Content-Type-Options: nosniff`.
- `Referrer-Policy: no-referrer`.
- Ограниченный Permissions-Policy без камеры/микрофона по умолчанию.
- Cross-origin policy проверяется на реальных используемых previews.

Site CSP и OBS output CSP не смешивать.
Добавление Twitch Embed потребует отдельного точечного CSP решения.

### 16.4. Health и readiness

Public health отвечает только о жизни gateway, без каналов и secrets.
Private readiness показывает доступность bridge, schema и dispatcher.
Moderator context показывает только разрешённый scope readiness.
Output heartbeat отдельно от readiness API.
Сохранённый флаг enabled не считается доказательством живого dispatcher.

Метрики:

- Cue admission/deny по safe reason.
- Queue depth и oldest age.
- Dispatch latency.
- Unknown outcomes.
- Output heartbeat age.
- Stop operation duration и неподтверждённые targets.
- Upload processing failures.
- Login rate limit hits.

Не помещать user tokens, TTS plaintext или уникальные raw payloads в metric labels.

### 16.5. Backup

Текущий `app/backup.py` включает DB, optional `.env` и `data/bots`.
Это сохраняет DB credentials/metadata, но не доказывает восстановление внешних media/sound файлов.
Новый backup должен включать явно перечисленные feature artifact roots.

Manifest:

- Backup format version.
- Schema version.
- Artifact ID.
- Relative safe path.
- Byte size.
- Checksum.
- Required/optional status.

Использовать согласованный SQLite snapshot, а не несогласованные копии меняющихся DB/WAL файлов.
Не включать temp/cache/quarantine как approved artifacts автоматически.
Missing/corrupt restored artifact получает unavailable state, не playable metadata.
На restore проверять path traversal, symlinks, archive bombs и свободное место.
Сначала validation в staging, затем управляемая замена.
Не открывать сайт до окончания восстановления.
Не восстанавливать browser sessions как действующий удалённый доступ.
Не выполнять исторические pending cues автоматически.
Существующие protected OBS tokens сохранять согласно действующему backup решению.
Экспорт/импорт остаётся local owner-only, без нового обязательного warning вопреки принятому решению.

### 16.6. Rollback

1. Отключить public moderator ingress.
2. Включить Stop для новых site commands.
3. Остановить gateway и dispatcher новой версии.
4. Сохранить логи и безопасный migration/command status.
5. Вернуть предыдущую совместимую сборку и runtime.
6. Не удалять новые таблицы автоматически.
7. Проверить старую owner panel и console.
8. Не replay неоднозначные действия после возврата.

Rollback схемы через destructive SQL не является обычным этапом.
Нужна backward-compatible additive migration.
