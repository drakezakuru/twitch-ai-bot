# Contract inventory и threat model (MOD-01)

> Снимок на 10.09.2026, ревизия `6c119ab3`. Обновлять при каждом изменении route surface.

## Существующие маршруты приложения (owner panel, `app/server.py`)

Всего **684 route-объекта**, из них 1 websocket. Крупные категории (method × префикс):

| Категория | Счётчик | Поверхность |
|---|---|---|
| `GET/POST/PUT/DELETE api/widgets` | 65+49+28+9 | виджеты/конфиги |
| `GET/POST/PUT/DELETE api/accounts` | 63+59+24+16 | **боты + OAuth токены** |
| `api/director` | 13 GET + 18 POST + 2 PUT + 5 DELETE | **owner control plane** |
| `GET widget/*` | 41 | публичные OBS-виджеты |
| `api/moderator-console`, `api/moderator-media` | 8/8/6, 7/7/3 | существующие moderator-сурфейсы (reuse-кандидаты) |
| `api/tts*`, `api/voice-*` | ~15 | TTS/клоны голоса |
| `api/backup`, `api/import` | 1+1 | **бэкапы владельца** |
| `GET frames`, `GET obs/*`, `GET static` | 5 | медиа/статика |
| прочее | ~250 | стрим, чат, безопасность, статистика |

Полный machine-readable манифест: `app/moderator_site_contract.py::build_app_route_manifest`
(генерируется из живого FastAPI-приложения, не копируется руками).

## Классификация для moderator-site

- **Existing/reused (через закрытый bridge, не wildcard):** moderator-console и moderator-media
  чтение (queue/soundboard/TTS статусы) — будут выбраны явно в MOD-03+ по одному endpoint'у.
- **New:** только маршруты под префиксом `/moderator-site/**` на отдельном gateway.
- **Forbidden (никогда не проксируются):** accounts/twitch-oauth/token-status (токены), backup/import,
  custom-providers (ключи провайдеров), security, maintenance, director (owner control), voice-clone*,
  frames (raw-медиа), ws. Список в `FORBIDDEN_REMOTE_PREFIXES`, guard-тест —
  `tests/test_moderator_site_contract.py`.

## Trust boundaries

```
Browser (moderator, отдельный Vite+TS фронт)
   ↓ HTTPS, отдельная auth сессия модератора (не owner cookie)
Gateway (отдельный ASGI app, явные methods/paths)
   ↓ authenticated loopback / UDS, сервисный credential
Bridge (app/moderator_site_bridge.py, MOD-03)
   ↓ in-process вызовы domain helpers (без импорта app.server)
Runtime (панель: БД, TTS queue, widgets)
```

Правила: gateway не импортирует `app.server`; bridge принимает только явные typed-запросы;
`accepted/dispatched` ≠ подтверждённое воспроизведение в OBS; Stop работает и при неизвестном
результате playback.

## Gate MOD-01

`tests/test_moderator_site_contract.py` (4 теста): манифест живой (>400 маршрутов), default-deny
выполняется, запрещённые категории реально существуют, ни один owner-маршрут не доступен удалённо.
Allowlist пуст до MOD-03 — весь сурфейс закрыт по умолчанию.

## Реализация MOD-03 (10.09)

- `app/moderator_site_bridge.py` — bridge в панельном процессе: fail-closed по
  `MODERATOR_BRIDGE_TOKEN` (без токена не отвечает вовсе), surface = `BRIDGE_ENDPOINTS`
  (пока только `GET /bridge/health`), всё остальное 404, никакого wildcard.
- `gateway/main.py` — отдельный ASGI-процесс: fail-closed по `MODERATOR_SITE_TOKEN`
  (browser→gateway credential), проксирует только `GATEWAY_ROUTES`, остальное 404.
- `gateway/bridge_client.py` — сервисный hop gateway→panel (`MODERATOR_BRIDGE_BASE_URL`,
  loopback), токен только на этом hop; без токена — 503 fail-closed.
- `gateway/routes.py` — явный реестр (method, gateway_path, bridge_path) + валидация
  против `FORBIDDEN_REMOTE_PREFIXES` и коллизий с owner-маршрутами.
- Тесты: `tests/test_moderator_site_gateway.py` (4): fail-closed, no-wildcard с обеих
  сторон, credential checks, контракт реестра.

## Реализация MOD-06 (10.09)

- `gateway/security.py`: exact host allowlist (`MODERATOR_SITE_ALLOWED_HOSTS`), exact origin
  validation для browser mutations (`MODERATOR_SITE_ALLOWED_ORIGINS`; Origin "null" никогда
  не валиден), server-bound CSRF double-submit (ms_csrf cookie = HMAC от session cookie,
  заголовок `X-Moderator-CSRF` обязателен для session mutations), trusted proxy handling
  (X-Forwarded-For игнорируется без доверенного списка), body bound 256 KiB.
- `gateway/main.py` middleware: host/size до роутинга; origin/CSRF после default-deny
  (unmapped пути остаются 404 и не раскрывают, что требуется сессия).
- Gate-тесты `tests/test_moderator_site_security.py` (6): spoofed Host/Origin, Origin null,
  missing/wrong CSRF, encoded paths, wrong methods, spoofed XFF, size bound.
- Bridge auth dependency: fail-closed токен уже в MOD-03; body bound применяется на hop'е
  gateway→bridge клиентским таймаутом и 413-гейтом.
