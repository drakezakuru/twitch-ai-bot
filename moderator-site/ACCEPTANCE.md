# Модераторский сайт: тесты и приёмка

> Документация отдельного сайта, не готовая реализация.
> [Начало](README.md) · [Спецификация](SPECIFICATION.md) · [Исполнение](IMPLEMENTATION.md) ·
> [Приёмка](ACCEPTANCE.md) · [Развёртывание](DEPLOYMENT.md).
> Активный статус: [PLAN_TODO.md](../PLAN_TODO.md), раздел MODSITE.

## 15. Тесты и команды исполнителю

### 15.1. Что проверять существующими focused tests

Ниже команды для будущего исполнителя, в этой работе они не запускались.
Запускать из корня репозитория с установленными dev dependencies.

```bash
python -m pytest tests/test_moderator_console_access.py -q
python -m pytest tests/test_moderator_media_routes.py -q
python -m pytest tests/test_moderator_sound_routes.py -q
python -m pytest tests/test_soundboard_library.py tests/test_w9_soundboard.py -q
python -m pytest tests/test_tts_voice_policy.py tests/test_tts_output_routes.py -q
python -m pytest tests/test_security.py -q
python3 scripts/check_md_links.py    # ссылки в документах (тестов на md-файлы нет, DEC-OWNER-012)
git diff --check
```

Выбирать только группы затронутого этапа.
Не запускать полный `pytest tests/` без отдельного запроса.
Если test import требует отсутствующий optional runtime, разбирать dependency boundary.
Не устанавливать ради frontend теста torch/whisper и не делать model pull.

### 15.2. Новые backend test files

- `tests/test_moderator_site_gateway.py`.
- `tests/test_moderator_site_sessions.py`.
- `tests/test_moderator_site_permissions.py`.
- `tests/test_moderator_site_csrf.py`.
- `tests/test_moderator_site_scope.py`.
- `tests/test_moderator_site_cues.py`.
- `tests/test_moderator_site_dispatcher.py`.
- `tests/test_moderator_site_outputs.py`.
- `tests/test_moderator_site_stop.py`.
- `tests/test_moderator_site_uploads.py`.
- `tests/test_moderator_site_recovery.py`.

### 15.3. Минимальная adversarial matrix

| Ситуация | Ожидаемый результат |
|---|---|
| Запрос owner API через gateway | Не маршрутизируется |
| Basic owner credentials на gateway | Не расширяют права |
| Spoofed forwarded headers | Не превращают пользователя в localhost owner |
| Чужой media/sound/command ID | 404/deny без данных |
| Отсутствует CSRF | Никакого side effect |
| Session отозвана при открытой вкладке | Следующая операция запрещена |
| Grant снова enabled | Старые cancelled invites не оживают |
| Account/channel выключен | Auth и dispatch запрещены |
| Два parallel POST одного intent | Одна запись, один dispatch intent |
| Тот же ключ, другой payload | 409 |
| Ответ потерян после admission | Lookup находит исходную команду |
| Crash после dispatch | Unknown, не auto replay |
| Stop во время synthesis | Поздний результат не звучит |
| Два output renderers | Один executor либо явный degraded mode |
| ACK от старой generation | Не меняет live state |
| Файл слишком тяжёлый после decode | Validation failure |
| Ошибка БД после file staging | Нет published orphan artifact |
| Restore backup | Файлы сверены, session не оживает, queue не replay |

### 15.4. Frontend команды после создания scripts

```bash
npm --prefix moderator-site ci
npm --prefix moderator-site run typecheck
npm --prefix moderator-site run test:unit
npm --prefix moderator-site run test:components
npm --prefix moderator-site run build
```

E2E запускается только после разрешения browser gate:

```bash
npm --prefix moderator-site run test:e2e
```

`test:e2e` по умолчанию работает на fixtures, не на реальном канале.
Не делать runtime acceptance частью обычного build script.
Не выдавать static string/grep tests за проверку пользовательского действия.

## 19. Критерии приёмки

### 19.1. Можно назвать отдельным сайтом, когда

- Весь frontend находится в `moderator-site/`.
- Есть отдельная сборка и собственный design system.
- Нет зависимости от panel DOM/CSS/JS.
- Основной экран построен вокруг сцены и команд.
- Moderator browser не имеет owner API доступа.
- Отдельное приложение можно выключить без поломки owner panel.

### 19.2. Можно включать remote pilot, когда

- Gate isolation/CSRF/session/revoke пройден.
- Upload processing ограничен и quarantine работает.
- Quota/idempotency/restart сценарии проверены.
- Owner Stop блокирует новое исполнение и честно сообщает о неподтверждённых outputs.
- Backup действительно восстанавливает referenced artifacts.
- Домены, TLS, proxy trust и private bridge настроены явно.
- Browser/OBS проверки имеют фактические результаты или функциональность выключена.

### 19.3. Нельзя считать готовностью

- Просто перенесённый HTML в новую папку.
- Дизайн на скриншоте без auth boundary.
- `accepted` вместо playback evidence.
- Тест на строку `stop` вместо остановки текущего элемента.
- Token restore без media files.
- «Все тесты зелёные», если проверялся только fake admission.
- Старая отметка E16 без связи с текущим `ACCEPT-01`.
- План другой модели, оценённый только по размеру файла.

### 19.4. Что нужно только от владельца перед исполнением

Эти ответы не мешают подготовить план, но нужны до соответствующего дорогого этапа:

1. Где будет gateway: рядом с локальной панелью или на отдельном VPS.
2. Реальный домен/HTTPS ingress и ограничения сети.
3. Можно ли модераторам Stop/replace чужую текущую команду.
4. Как совмещать Soundboard и TTS: общий audio arbiter рекомендуется.
5. Срок хранения истории, TTS текстов и rejected uploads.
6. Разрешение на browser, затем реальный Twitch/OBS/device acceptance.

Остальные defaults в документе не считаются ответами владельца.


---

## 20. MOD-23 browser acceptance — fake backend (11.09.2026)

Выполнено на статическом fake backend (python http.server, dist/, порт 8123 loopback).
Никаких Twitch/provider/OBS действий не выполнялось. Модель НЕ инспектирует пиксели —
проверки по DOM-снапшотам и eval; скриншот приложен для владельца.

### 20.1. Реальные browser evidence

1. Стартовое RU: header «Модераторский сайт», nav (Библиотека/Загрузки/Озвучка/Саундборд),
   locale combobox RU — DOM-снапшот agent-browser.
2. Library approved-only: «Clip approved», «Drum roll» видны; «Quarantine clip» (pending) скрыт.
3. EN: «Moderator Site» после смены локали (bubbles change event).
4. UA: «Модераторський сайт | Бібліотека».
5. Upload (fake File через DataTransfer): toast «Файл надіслано на перевірку».
6. Focus порядок (Tab-эмуляция): nav-ссылки → locale-switch → upload-input → upload-retry.
7. Скриншот: `moderator-site/acceptance/mod23-ua.png`.

### 20.2. Дефекты, найденные и устранённые в прогоне

- locale-switch и upload-input не были подключены к рендеру (wire-up в `src/main.ts`
  добавлен: change-delegation на document, перерисовка shell).

### 20.3. Остатки MOD-23 (не проверено в этом прогоне)

- Touch/mobile viewport и computed layout по media-queries — эмуляция viewport не выполнялась.
- Retry-цикл upload при ошибке сети — требует mock-API (сейчас только локальный toast).

## 21. MOD-24 Twitch/OBS/device acceptance — ЖДЁТ ВЛАДЕЛЬЦА (не выполнялся)

Реальный канал, устройства и side effects не согласованы; в песочнице Twitch/OBS физически
недоступны. Чеклист целевой системы (исполнять только по отдельному «поехали»):

1. Invite login: ссылка от настроенного `public_origin`, обмен invite→session, cookie HttpOnly.
2. Media placement: per-cue placement в OBS через Browser Source; duplicate Browser Source — один current.
3. Soundboard: play/stop, correlation dedup, соседний скоуп не задет.
4. TTS: реальный провайдер, cancellable late-result, voice policy.
5. Reconnect: разрыв/восстановление между gateway и bridge, resume без двойной отдачи.
6. Emergency Stop: активация → все lanes остановлены → рестарт процесса → kill остаётся активен.


## 22. MOD-18 owner UI acceptance — 11.09.2026 (после «поехали»)

1. QA-панель запущена изолированно (`scripts/run_qa_panel.py --profile local --port 8000`,
   production БД не тронута) — HTTP 200, старт без ошибок.
2. Server-side разметка подтверждена: панель отдаёт подключённый
   `static/app/26_modsite_admin.js` и блок `#modsiteAdminBlock` (curl).
3. API-уровень: 3 теста admin routes зелёные (kill on/off блокирует admission,
   revoke bump'ает grant_version, неизвестный грант = 404).
4. Visual browser acceptance НЕ состоялся: Chrome песочницы деградировал — пустой DOM
   на любых страницах (включая moderator-site dist, рендерившийся ранее), процессы
   Chrome убиваются memory guard'ом (0.2 GiB RSS); `sandbox_restart` не сконфигурирован,
   platform issue отправлен. Перенесено: открыть панель → Settings → блок «Moderator-site:
   kill switch и доступы», нажать Включить/Выключить, проверить список грантов и revoke.
