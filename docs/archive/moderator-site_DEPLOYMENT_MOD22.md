# MOD-22 Deployment runbook (moderator-site)

Проверяемая валидация конфигурации — `app/moderator_site_deploy_config.py`
(тесты `tests/test_moderator_site_deploy_config.py`). Конфиг fail-closed:
любой отсутствующий ключ запрещает запуск публичного gateway.

## 1. Environment checks (до старта)

```bash
python -c "from app.moderator_site_deploy_config import validate_config; import json,sys; print(json.dumps(validate_config(json.load(open('deploy/config.json')))))"
```

Обязательные ключи: `public_origin` (только https://), `allowed_hosts`,
`tls_cert`, `tls_key`, `gateway_port`, `bridge_port`. Отсутствие любого из них —
отказ запуска (`config_invalid`), дефолтов нет.

## 2. Service user и права

- Отдельный системный пользователь `modsite`, без shell: `useradd -r -s /usr/sbin/nologin modsite`.
- Права только на: каталог gateway/бандла, sqlite-файл данных, `tls_key` (0400, владелец `modsite`).
- Owner panel (`run.py`, порт 8000) — не под этим пользователем и не в этой машине-сегменте; его порт **никогда не публикуется** (тест `test_owner_ports_never_published`).

## 3. TLS и заголовки

- TLS терминируется на public origin; gateway слушает только loopback-интерфейс или за локальным reverse-proxy с согласованным hostname.
- Минимальные заголовки reverse-proxy: `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `Content-Security-Policy` по ACCEPTANCE.md.

## 4. Health/readiness и rollback

- `/moderator-site/health` — liveness. Readiness — честный: gateway+bridge оба живы, иначе `ready:false` и origin не отдаётся (`health_readiness`).
- Rollback: остановить gateway → вернуть предыдущий бандл/код → поднять → проверить readiness. БД не мигается вниз (schema revisions append-only).

## 5. Public ingress

- По умолчанию **disabled**. Включается только явным `published_ports` с валидацией (порт bridge/панели в списке = конфигурация невалидна).
- Owner invite link строится ТОЛЬКО из настроенного `public_origin` (`invite_link()`), никогда из `location.origin` панели.

## Примеры

- `deploy/config.example.json` — минимальный валидный конфиг.
- `deploy/nginx-moderator-site.conf.example` — reverse-proxy с заголовками.
