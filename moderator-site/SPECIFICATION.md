# Модераторский сайт: техническая спецификация

## Навигация

- [Продукт и сценарии](#1-какой-продукт-получится).
- [Архитектура и границы доступа](#2-архитектурное-решение).
- [Структура файлов](#3-структура-файлов).
- [Дизайн](#4-дизайн-рабочая-сцена-а-не-админка).
- [Экраны](#5-страницы-и-сценарии).
- [Редактор положения](#6-редактор-положения).
- [Авторизация и права](#7-авторизация-и-права).
- [Новый API](#8-новый-api-сайта).
- [Очередь и исполнение](#9-очередь-и-исполнение).
- [Output telemetry и Stop](#10-output-telemetry-и-stop).
- [Медиа, звук и TTS](#11-медиа-звук-и-tts-конкретные-доработки).
- [Хранилище и события](#12-хранилище-миграции-и-события).
- [Frontend-функции](#13-frontend-функции-и-управление-состоянием).
- [Существующий API](#17-карта-существующего-api-для-переноса).
- [Проверенные дефекты](#18-проверенные-дефекты-которые-нельзя-переносить).
- [Этапы реализации](IMPLEMENTATION.md), [приёмка](ACCEPTANCE.md), [развёртывание](DEPLOYMENT.md).

## 0. Статус и границы документа

Это техническая спецификация отдельного сайта. Реализация ещё не начата.
Документ основан на независимом плане и проверке текущего кода; дополнительные материалы
использованы только после проверки конкретных контрактов, не как готовая истина.
[Начало](README.md) · [Исполнение](IMPLEMENTATION.md) · [Приёмка](ACCEPTANCE.md) ·
[Развёртывание](DEPLOYMENT.md).

Запрос владельца:

- Свой отдельный сайт для модераторов.
- Физически отдельная папка `moderator-site/`.
- Собственный интерфейс, не уменьшенная копия панели владельца.
- Подробный план файлов, функций, API, дизайна, тестирования и запуска.
- На этом этапе только документация.

Проверенная рабочая копия:

- Репозиторий проекта.
- Ветка при проверке: `main`.
- Дополнительная спецификация описывала другую рабочую копию.
- Факты о реализации сверены с доступным кодом, новые решения помечены как проектные.
- Перед исполнением каждого этапа повторно проверить owning modules в текущем состоянии кода.

Обозначения:

- **Сейчас**: найдено в проверенном коде.
- **Новое**: необходимо реализовать по этому проекту.
- **Предлагается**: технический default, который ещё не является решением владельца.
- **Gate**: условие перехода к следующему этапу.
- **Pending**: проверка ещё не выполнена.

Все новые имена файлов, функции, типы, маршруты и настройки ниже являются проектом.
Фрагменты кода объясняют контракт, а не заменяют готовую реализацию.

Документ не создаёт второй активный план внутри репозитория.
При старте разработки активный этап отмечается в существующем `PLAN_TODO.md`, без копирования recipe.
Постоянные требования находятся в `moderator-site/SPECIFICATION.md`.
Старый `docs/specs/MODERATOR_SITE.md` сохраняется как указатель, без второй копии требований.
Исторические решения не переписываются.
Выбор собственного сайта закреплён в `DEC-MODSITE-001`; own/service/hybrid не переоткрывается.
Вся специальная документация сайта находится в `moderator-site/`.
Корневой `PLAN_TODO.md` хранит активный статус, а `IMPLEMENTATION.md` подробный порядок исполнения.
Разрешение на планирование не означает разрешение на production deployment или OBS-приёмку.

## 1. Какой продукт получится

### 1.1. Основной сценарий

Модератор открывает приглашение владельца.
Входит через Twitch под своим аккаунтом.
Получает доступ только к конкретному разрешённому пространству канала.
Видит рабочую сцену, библиотеку и ленту команд.
Выбирает картинку, GIF, короткое видео, звук или разрешённый голос.
Для медиа настраивает положение в безопасном предпросмотре.
Отправляет одну команду в очередь.
Видит отдельно принятие команды и подтверждения проигрывателя.
Может отменить ещё не выполненную свою команду, если право разрешено.
Владелец сохраняет возможность заблокировать новые команды и остановить вывод.

### 1.2. Что отличает сайт от панели

- Главный объект интерфейса: сцена и подготовленная команда, а не настройки ботов.
- Главный переход: «подготовить → проверить → отправить → увидеть результат».
- Вместо административного sidebar: компактная верхняя навигация.
- Вместо таблицы аккаунтов: библиотека материалов и рабочая область.
- Вместо десятков форм: контекстный инспектор выбранного материала.
- Вместо глобальных статусов системы: состояние этого канала и его выводов.
- Вместо owner-настроек: только выданные действия.
- Отдельные CSS, JS, сборка, HTML entrypoint и тесты интерфейса.
- Никакого импорта `static/app.css` или `static/app.js`.
- Никакой зависимости от DOM, глобальных переменных или навигации панели.

### 1.3. Состав первой полноценной версии

1. Вход по приглашению через Twitch.
2. Серверная сессия и завершение сессии.
3. Exact-scoped права и отзыв доступа.
4. Медиа-библиотека с поиском и избранным.
5. Загрузка медиа на проверку владельцу.
6. Редактор положения одного медиаэлемента.
7. Звуковая библиотека с локальным прослушиванием.
8. TTS только через разрешённые voice aliases.
9. Единая лента команд с раздельными исполнительными дорожками.
10. Отмена ещё не запущенных команд.
11. Честные статусы соединения, отправки и проигрывания.
12. Owner Emergency Stop и отзыв прав.
13. RU/EN/UA, keyboard navigation и mobile layout.
14. Безопасный удалённый вход без публикации owner API.
15. Восстановление конфигурации и файлов после backup.

### 1.4. Что не входит в первую версию

- Управление аккаунтами ботов.
- Редактирование AI providers и API-ключей.
- Выдача прав другим модераторам из сайта.
- Просмотр owner-токенов и OBS-паролей.
- Произвольные URL, HTML, JavaScript или внешние iframe в материалах.
- Управление сценами через OBS WebSocket.
- Конструктор полноценных OBS-сцен с несколькими слоями.
- Генерация картинок, клонирование голоса или установка ML-моделей.
- YouTube/Song Request autoplay.
- Бан/таймаут/удаление сообщений Twitch как новая подсистема.
- Объявления о действиях модератора в Twitch-чат.
- Облачный сервис с множеством независимых владельцев и биллингом.

## 2. Архитектурное решение

### 2.1. Рекомендуемый baseline

Frontend: Vite + TypeScript, без React в первой версии.
UI: обычные DOM-компоненты с явным lifecycle и небольшими stores.
Backend: существующие Python/FastAPI/SQLite и новые узкие feature modules.
Удалённая поверхность: отдельное FastAPI gateway-приложение.
Исполнение: существующий локальный runtime владельца.
Обмен gateway с runtime: отдельный закрытый bridge с фиксированными операциями.

Почему этот вариант:

- Новый сайт действительно отделён от старого frontend.
- TypeScript фиксирует DTO и состояния редактора.
- Не требуется переписывать owner panel.
- Можно повторно использовать библиотеки и исполнительные механизмы.
- Внешний сервер не должен проксировать owner application целиком.
- Есть проверяемая граница между удалённым вводом и локальным исполнением.

Выбор Vite/TypeScript является предложением, не обнаруженным свойством репозитория.
Точные версии зависимостей фиксируются lockfile во время первого этапа.
Не использовать неопределённые `latest` в deployment.

### 2.2. Схема процессов

```text
Браузер модератора
    │ HTTPS, HttpOnly cookie, CSRF
    ▼
Reverse proxy / TLS
    │ только отдельный gateway
    ▼
moderator-site/gateway
    ├── dist: отдельный frontend
    ├── /api/mod-site/v1: browser API
    └── allowlist bridge client
             │ UDS или отдельный защищённый loopback listener
             ▼
    app/moderator_site_bridge.py
             │ moderator-session auth, без owner bypass
             ▼
    domain services + SQLite
             │ durable commands / outbox
             ▼
    local dispatcher
       ├── existing moderator media output
       ├── existing Soundboard
       └── existing TTS audio transport
```

Отдельно остаётся существующая локальная панель владельца.
Её passwordless loopback-поведение не меняется.
Её HTTP-приложение не становится upstream для wildcard-прокси сайта.

### 2.3. Почему недостаточно проксировать `/api/*`

Сейчас owner policy разрешает прямой loopback-доступ без пароля.
Reverse proxy на той же машине может выглядеть для backend как loopback-клиент.
Если проксировать owner приложение целиком, remote request может попасть в owner routes.
CORS эту проблему не решает.
Скрытая кнопка или отсутствие ссылки эту проблему не решают.
Раздельный CSS эту проблему не решает.

Запрещённый дизайн:

```text
Интернет → /api/* → существующий app.server:app
```

Разрешённый дизайн:

```text
Интернет → отдельный gateway → фиксированный moderator bridge
```

Bridge никогда не подключает owner routers.
Bridge никогда не вызывает `_owner_auth_dependency` для moderator request.
Bridge требует moderator session даже от localhost для всех authenticated операций.
Исключение: фиксированный pre-auth allowlist `begin_login`, `poll_login`, `login_status`,
`complete_login` и `reconcile_login_delivery`. Эти операции требуют bridge credential,
валидный browser transaction/nonce, origin/CSRF proof для mutations и отдельные rate limits.
При первом `begin_login` проверяется bootstrap nonce и invite; session ещё не существует.
Pre-auth операции не дают доступ к context/library/cues и не принимают identity из client body.
Внутри core после provider verification создаётся session, затем gateway выставляет HttpOnly cookie.
Bridge не принимает имя Python-функции, произвольный URL или SQL из запроса.

### 2.4. Где живут данные

- SQLite остаётся единственным источником прав, команд, статусов и настроек.
- Основная БД открывается локальным core, не удалённым браузером.
- Gateway не получает прямой доступ к `bot.db` и owner `.env`.
- Approved media остаются в существующем feature storage.
- Upload stream передаётся через ограниченный bridge в карантин.
- Gateway не хранит копию библиотеки как второй source of truth.
- `moderator-site/dist/` содержит только публичную сборку.
- Browser storage содержит язык и несекретные предпочтения интерфейса.
- Сессии не хранятся в localStorage/sessionStorage.
- Черновик TTS по умолчанию живёт в памяти вкладки.

### 2.5. Linux и Windows

Для co-hosted Linux рекомендуется Unix domain socket.
Socket принадлежит service user и недоступен посторонним локальным пользователям.
Gateway аутентифицируется отдельным bridge credential.
Moderator session проверяется дополнительно для authenticated операций; credential не заменяет
actor identity. Для login действует только pre-auth allowlist из §2.3.

Для Windows предлагается отдельный loopback TCP listener.
Он запускает только bridge ASGI app, не owner app.
Он требует bridge credential и соответствующий operation class proof из §2.3:
session для authenticated вызовов, transaction/nonce proof для разрешённого pre-auth login.
Firewall запрещает внешний доступ к этому listener.
Адрес и порт выбираются конфигурацией, не вшиваются в frontend.

Поддержку Windows необходимо проверить отдельно на целевой системе.
Если выбрать другой IPC, сохранить те же auth и allowlist-контракты.

### 2.6. Если сайт должен жить на VPS

План выше предполагает gateway рядом с локальным runtime и доступный HTTPS ingress.
Если машина за CGNAT или нельзя открыть входящий маршрут, потребуется иной deployment.
Для такого случая: отдельный outbound relay от локальной машины к gateway.
Relay не входит скрыто в базовую оценку.
Он требует pairing, scoped credentials, bounded backlog, reconnect и revocation.
Нельзя заменить relay публичным туннелем на owner port.
До настройки внешнего доступа владелец выбирает хостинг и домен.
Реальное доменное имя в этом документе не выдумывается.

## 3. Структура файлов

### 3.1. Отдельная папка сайта

Ниже дерево будущих файлов, не перечень уже созданного кода.

```text
moderator-site/
  README.md
  SPECIFICATION.md
  IMPLEMENTATION.md
  ACCEPTANCE.md
  DEPLOYMENT.md
  package.json
  package-lock.json
  tsconfig.json
  vite.config.ts
  vitest.config.ts
  playwright.config.ts
  index.html
  .env.example
  src/
    main.ts
    app.ts
    router.ts
    config.ts
    api/
      client.ts
      contracts.ts
      errors.ts
      auth.ts
      context.ts
      library.ts
      uploads.ts
      cues.ts
      events.ts
      preferences.ts
    state/
      store.ts
      session-store.ts
      workspace-store.ts
      library-store.ts
      draft-store.ts
      queue-store.ts
      connection-store.ts
    pages/
      login-page.ts
      workspace-page.ts
      library-page.ts
      history-page.ts
      access-denied-page.ts
    components/
      site-header.ts
      workspace-tabs.ts
      connection-badge.ts
      library-grid.ts
      asset-card.ts
      asset-preview.ts
      search-field.ts
      filter-chips.ts
      cue-composer.ts
      media-inspector.ts
      sound-composer.ts
      tts-composer.ts
      voice-picker.ts
      queue-drawer.ts
      queue-item.ts
      output-status.ts
      upload-dialog.ts
      confirm-dialog.ts
      toast-region.ts
      empty-state.ts
      error-state.ts
      skeleton.ts
    editor/
      geometry.ts
      constraints.ts
      stage.ts
      selection.ts
      pointer-controller.ts
      keyboard-controller.ts
      history.ts
      placement-presets.ts
    i18n/
      index.ts
      ru.ts
      en.ts
      ua.ts
    styles/
      tokens.css
      reset.css
      base.css
      layout.css
      components.css
      editor.css
      motion.css
      responsive.css
    utils/
      lifecycle.ts
      ids.ts
      format.ts
      debounce.ts
      safe-dom.ts
  public/
    favicon.svg
  tests/
    unit/
      geometry.test.ts
      constraints.test.ts
      errors.test.ts
      i18n.test.ts
      queue-reducer.test.ts
      idempotency.test.ts
    components/
      login.test.ts
      composer.test.ts
      editor-keyboard.test.ts
      library.test.ts
      uploads.test.ts
      lifecycle.test.ts
    e2e/
      login.spec.ts
      workspace.spec.ts
      permissions.spec.ts
      mobile.spec.ts
      reconnect.spec.ts
      accessibility.spec.ts
    fixtures/
      api.ts
      media.ts
      events.ts
  gateway/
    __init__.py
    main.py
    config.py
    routes.py
    middleware.py
    bridge_client.py
    errors.py
  deploy/
    reverse-proxy.conf.example
    gateway.service.example
    moderator-site.env.example
```

Не добавлять второй активный checklist или незарегистрированные markdown-файлы.
Пять документов этой папки зарегистрированы в проверке active documentation.
Инструкции сайта редактировать здесь; корневые документы сохраняют навигацию и общие правила.
Корневая папка `moderator-site/` разрешена именно запросом владельца.
Новые одноразовые CLI-файлы в корне проекта не создавать.

### 3.2. Новые backend feature modules

```text
app/
  moderator_site_schema.py
  moderator_site_models.py
  moderator_site_identity.py
  moderator_site_sessions.py
  moderator_site_permissions.py
  moderator_site_bridge.py
  moderator_site_service.py
  moderator_site_cues.py
  moderator_site_dispatcher.py
  moderator_site_outputs.py
  moderator_site_events.py
  moderator_site_uploads.py
  moderator_site_recovery.py
  moderator_site_admin_routes.py
```

Это разделение по ответственности, а не требование сразу создать пустые файлы.
Маленькие смежные модули можно объединить до роста сложности.
`moderator_site_service.py` вызывает domain-функции, не HTTP endpoint через самопрокси.

### 3.3. Существующие файлы: только адресные изменения

- `app/server.py`: lifecycle bridge и dispatcher, подключение owner admin router.
- `app/database.py`: вызов нового `ensure_schema()`.
- `app/moderator_console_routes.py`: выделение повторно используемой бизнес-логики при необходимости.
- `app/moderator_media_routes.py`: размещение и адаптер нового cue lifecycle.
- `app/moderator_sound_routes.py`: адаптер, telemetry и stop scope.
- `app/audio_queue.py`: correlation, cancellation и наблюдаемость без второй TTS-очереди.
- `app/tts_voice_policy.py`: повторная авторизация перед исполнением.
- `app/backup.py`: включение feature artifacts и безопасное восстановление.
- `templates/obs_moderator_media.html`: нормализованное размещение и ограниченные ACK.
- `widgets/soundboard/index.html`: корреляция команд и подтверждение browser playback.
- Существующие TTS outputs: correlation и cancel по действующему output contract.
- Owner frontend: минимальные controls выдачи прав, upload approval и Stop.
- `PLAN_TODO.md`: единственный активный список этапов.
- `docs/DECISIONS.md`: подтверждённые новые решения.
- `docs/ARCHITECTURE.md`: контракты после фактической реализации.
- `moderator-site/SPECIFICATION.md`: канонические требования продукта.
- `docs/specs/MODERATOR_SITE.md`: только совместимый указатель на папку сайта.
- `FILE_ZONES.md`: новые реальные зоны после появления файлов.

Старые console/public URLs и файлы не удалять.
Перенос старой логики должен иметь compatibility tests.
Новый сайт можно отключить, не лишая владельца старой панели.

## 4. Дизайн: рабочая сцена, а не админка

### 4.1. Визуальное направление

Рабочее описание: тёмная студия для подготовки и запуска материалов.
Спокойный графитовый фон, крупная сцена, контрастные действия.
Без KPI-карточек, графиков CPU, списков ботов и таблиц настроек.
Акцент используется для выбора и основного действия, не для каждой рамки.
Красный зарезервирован для Stop, опасных действий и подтверждённой ошибки.

### 4.2. Предлагаемые design tokens

```css
:root {
  color-scheme: dark;
  --ms-bg: #101217;
  --ms-surface: #191d25;
  --ms-surface-raised: #222836;
  --ms-border: #394354;
  --ms-text: #f3f5f8;
  --ms-text-muted: #adb8c9;
  --ms-accent: #b2a4ff;
  --ms-on-accent: #171226;
  --ms-success: #70dfb0;
  --ms-warning: #ffd185;
  --ms-danger: #ff919d;
  --ms-focus: #d4cbff;
  --ms-radius-sm: 8px;
  --ms-radius-md: 14px;
  --ms-radius-lg: 20px;
  --ms-space-1: 4px;
  --ms-space-2: 8px;
  --ms-space-3: 12px;
  --ms-space-4: 16px;
  --ms-space-6: 24px;
  --ms-space-8: 32px;
}
```

Палитра является начальным предложением.
Контраст каждой фактической пары проверить инструментально.
Не объявлять WCAG compliance только по значениям токенов.

### 4.3. Типографика и плотность

- Системный sans-serif без обязательной загрузки внешнего шрифта.
- Основной текст: 15–16 px.
- Вторичный текст: не меньше 13 px.
- Заголовок страницы: 24–30 px.
- Числовые координаты: tabular numerals.
- Интерлиньяж основного текста: около 1.45.
- Кнопки и touch targets: минимум 44×44 px на touch layout.
- Слишком длинные названия: ellipsis и доступный полный текст.
- Ошибки и важные подписи не обрезаются.

### 4.4. Desktop layout

```text
┌──────────────────────────────────────────────────────────────────┐
│ Лого  Канал · ваш доступ        Соединение   RU EN UA    Профиль │
├──────────────────────────────────────────────────────────────────┤
│ Сцена       Библиотека       История                              │
├────────────────────┬───────────────────────────┬─────────────────┤
│ Медиа / Звук / TTS │ Тестовый холст 16:9       │ Инспектор       │
│ Поиск              │                           │ Положение       │
│ Тип · Избранное    │      выбранный GIF        │ Размер          │
│                    │                           │ Длительность    │
│ Карточки материалов│                           │ Режим отправки  │
│                    │                           │ [В очередь]     │
├────────────────────┴───────────────────────────┴─────────────────┤
│ Очередь: текущая команда · ожидающие · состояние выводов          │
└──────────────────────────────────────────────────────────────────┘
```

Ширины как starting point:

- Общий max-width: 1600 px.
- Библиотека: 280–320 px.
- Инспектор: 280–320 px.
- Центральная сцена: всё оставшееся пространство.
- Межколоночный gap: 16–24 px.
- На меньшей ширине инспектор становится drawer.
- Высота сцены ограничивается viewport, а не бесконечно растёт от библиотеки.

### 4.5. Tablet layout

- Верхний header остаётся компактным.
- Сцена занимает всю основную ширину.
- Библиотека открывается нижней или боковой панелью.
- Инспектор открывается по выбранному элементу.
- В каждый момент не больше одного overlay drawer.
- Закрытие drawer возвращает focus в кнопку открытия.
- Очередь показывает текущий элемент и число ожидающих.

### 4.6. Mobile layout

- Один вертикальный поток.
- Сцена сверху, переключатель «Медиа / Звук / TTS» ниже.
- Библиотека в bottom sheet с собственным scroll.
- Numeric controls важнее точного drag на маленьком экране.
- Главная кнопка отправки закреплена в нижней зоне composer.
- Учесть `env(safe-area-inset-bottom)`.
- Не блокировать обычный scroll всей страницы ради drag.
- Drag запускается только на объекте или handle.
- Кнопка Stop не соседствует вплотную с «Отправить».
- 320 px ширины проверяется без горизонтального скролла страницы.

### 4.7. Общие состояния компонентов

Каждый data-компонент проектируется сразу в состояниях:

1. Загрузка.
2. Данные получены.
3. Пустая библиотека.
4. Ничего не найдено по фильтру.
5. Право отсутствует.
6. Сессия истекла.
7. Runtime недоступен.
8. Сеть временно потеряна.
9. Запрос отклонён сервером.
10. Операция отправлена, итог ещё неизвестен.

Пустая библиотека не должна выглядеть как ошибка сервера.
Потеря связи не должна стирать локальный черновик.
Обновление прав не должно молча заменять активный канал.

### 4.8. Motion

- Hover/focus transitions: ориентировочно 120–160 ms.
- Drawer: не больше 180–220 ms.
- Никаких бесконечных пульсаций вокруг кнопки отправки.
- `prefers-reduced-motion` отключает декоративные перемещения.
- Во время drag координаты обновляются через animation frame.
- Layout не пересчитывает всю библиотеку на каждом pointer move.
- Skeleton не должен выглядеть как настоящая миниатюра.

## 5. Страницы и сценарии

### 5.1. Вход

Экран показывает:

- Назначение сайта.
- Безопасный статус приглашения без раскрытия внутренних account IDs.
- Кнопку входа через Twitch.
- При Device Flow: user code, разрешённую verification ссылку и состояние ожидания.
- Понятные ошибки истёкшего приглашения и другого Twitch аккаунта.
- RU/EN/UA до входа.
- Отсутствие owner-навигации даже в HTML.

Порядок:

1. Прочитать invite из fragment.
2. Скопировать invite в память текущей страницы.
3. Удалить fragment через `history.replaceState` до внешних ресурсов.
4. Начать серверную login transaction.
5. Получить публичные данные подтверждения, не raw provider device secret.
6. Опросить только свою transaction с установленным server interval.
7. Завершить verified transaction отдельным POST и получить HttpOnly session cookie.
8. Загрузить context.
9. Открыть разрешённую рабочую область.

Provider success подтверждает identity transaction, но сам по себе не выдаёт session в JSON.
Cookie устанавливает отдельный `POST /auth/complete` с transaction ID, browser nonce и pre-auth CSRF.
Read-only `GET /auth/status/{transaction_id}` не потребляет invite и не создаёт session.
При потерянном ответе сначала проверить `GET /session`: Set-Cookie мог уже дойти.
Если cookie не дошла, bounded completion retry меняет secret той же неподтверждённой session,
инвалидируя предыдущий hash; он не создаёт вторую session и не потребляет invite снова.
Первая authenticated операция закрывает retry window. Wrong browser/expired nonce/revoked grant
не могут восстановить session. Нужны concurrent/lost-header/lost-body HTTP tests.

При provider `slow_down` увеличить интервал.
При expiry прекратить poll, а не создавать бесконечную рекурсию.
При уходе со страницы отменить timers и requests.
При нескольких кликах не создавать конкурирующие login attempts.

### 5.2. Рабочая сцена

- Текущий канал всегда виден в header.
- В MVP одна session привязана к одному workspace.
- Выбор другого workspace не происходит через ручной `account_id` в JSON.
- При поддержке нескольких grants scope меняется только серверной операцией.
- Сцена показывает локальную композицию, не «живой OBS».
- Подпись «Тестовый холст» остаётся видна постоянно.
- Локальный preview не отправляет cue.
- Сохранённая позиция меняется только в черновике до отправки.
- После успешного enqueue элемент можно оставить на холсте для следующей команды.

### 5.3. Библиотека

Вкладки:

- Медиа.
- Звуки.
- Голоса в TTS composer, не в общем каталоге файлов.

Фильтры:

- Поиск по безопасному имени.
- Тип материала.
- Избранное.
- Для upload автора: отдельный статус «На проверке».

Карточка:

- Миниатюра или waveform placeholder.
- Название.
- Тип.
- Длительность, если определена проверкой.
- Размеры для visual media.
- Избранное.
- «Предпросмотр».
- «Выбрать».

Клик по карточке не запускает материал в эфир.
Двойной клик не запускает материал в эфир.
Enter на кнопке выбора только выбирает.
Загрузка миниатюр не загружает все исходные видео целиком.
Неодобренные чужие материалы не раскрываются.

### 5.4. История

- По умолчанию показывает собственные команды модератора.
- Общая история требует отдельного разрешения.
- Сортировка: от новых к старым.
- Пагинация cursor-based.
- Фильтры: тип, состояние, временной диапазон.
- Детали: actor, материал/alias, время, status, безопасная причина ошибки.
- Не возвращать raw provider errors, file paths, tokens и чужие TTS-тексты без права.
- «Повторить» создаёт новый draft и новый idempotency key.
- «Повторить» не является автоматическим повторным воспроизведением.

### 5.5. Загрузка

- Выбрать один файл.
- Показать имя, размер, тип и правила.
- Попросить подтверждение права использовать материал.
- Client checks помогают UX, но не заменяют server validation.
- Показать progress передачи отдельно от server processing.
- Закрытие окна во время передачи предлагает отмену.
- После принятия: «Ожидает проверки владельцем».
- Не показывать материал в approved library до одобрения.
- Ошибка проверки имеет stable code и понятное описание.
- Повтор не должен создавать несколько одинаковых upload jobs из-за потерянного ответа.

## 6. Редактор положения

### 6.1. Ограничение первой версии

Одна команда содержит один visual asset и одну область размещения.
Полноценный многослойный редактор не строится.
Rotation, timeline, keyframes и collaborative editing отложены.

### 6.2. Координаты

```ts
export type NormalizedPlacement = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type StageSize = {
  width: number;
  height: number;
};

export type PixelRect = {
  x: number;
  y: number;
  width: number;
  height: number;
};
```

`x/y` задают верхний левый угол контейнера относительно всей сцены.
`width/height` задают долю ширины/высоты сцены.
Числа конечные, не `NaN` и не `Infinity`.
Границы: `0 ≤ x,y < 1`, `0 < width,height ≤ 1`.
Дополнительно: `x + width ≤ 1`, `y + height ≤ 1`.
Server validation использует те же правила.
Для сохранения aspect ratio учитывать aspect ratio самой сцены.
Нельзя приравнивать `width / height` в нормализованных единицах к ratio пикселей.

### 6.3. Базовая математика

```ts
export function toPixels(
  placement: NormalizedPlacement,
  stage: StageSize,
): PixelRect {
  return {
    x: placement.x * stage.width,
    y: placement.y * stage.height,
    width: placement.width * stage.width,
    height: placement.height * stage.height,
  };
}

export function toNormalized(
  rect: PixelRect,
  stage: StageSize,
): NormalizedPlacement {
  if (stage.width <= 0 || stage.height <= 0) {
    throw new Error('stage_size_invalid');
  }
  return {
    x: rect.x / stage.width,
    y: rect.y / stage.height,
    width: rect.width / stage.width,
    height: rect.height / stage.height,
  };
}
```

Нужны отдельные функции:

- `validatePlacement(value)` возвращает field errors.
- `clampPlacement(value, limits)` ограничивает локальный drag.
- `fitAssetIntoStage(assetSize, stageSize, maxFraction)` создаёт default.
- `resizeKeepingAspect(rect, handle, delta, ratio, bounds)` меняет размер.
- `moveWithinBounds(rect, delta, bounds)` перемещает объект.
- `snapToGuides(rect, guides, threshold)` добавляется после baseline.
- `placementEquals(a, b, epsilon)` предотвращает шумные updates.

Backend не должен молча clamp злонамеренный POST.
Некорректный запрос отклоняется с field error.
Локальный drag можно clamp для удобства.

### 6.4. Aspect ratio

Из исходного файла берутся проверенные `width` и `height`.
Если размеры неизвестны, UI не угадывает ratio.
Материал либо получает безопасный контейнер, либо блокируется до обработки.
Для изображения используется `object-fit: contain`.
Для видео также `contain`, без скрытого crop.
Предлагаемый MVP: aspect lock включён по умолчанию.
Unlock ratio не требуется до отдельного запроса.

### 6.5. Drag

1. На pointerdown зафиксировать исходный rect и pointer coordinates.
2. Вызвать pointer capture.
3. Считать delta относительно актуального stage bounding rect.
4. Обновлять только selected asset и inspector values.
5. На pointerup выполнить одну запись в undo history.
6. На pointercancel вернуть исходный rect либо явно завершить безопасно.
7. На destroy убрать handlers и capture.

Не хранить mouse/touch отдельными расходящимися реализациями.
При resize окна заново измерить сцену, сохранив normalized state.
Не менять source of truth на CSS `left/top`.

### 6.6. Keyboard

- Tab переводит focus между сценой, handles и inspector.
- Arrow перемещает на малый шаг.
- Shift+Arrow перемещает на увеличенный шаг.
- Размер шага вычисляется из virtual canvas, а не monitor DPI.
- Escape отменяет текущий drag.
- Undo/redo работает только для локального placement draft.
- Undo никогда не отменяет уже начавшееся audio действие.
- Numeric inputs доступны без drag.

### 6.7. Presets

Предлагаемые presets:

- Центр.
- Верхний левый угол.
- Верхний правый угол.
- Нижний левый угол.
- Нижний правый угол.
- По ширине с сохранением пропорций.

Preset меняет только черновик.
Safe area отображается пунктиром.
Начальное предложение safe area: 5% от границ.
Это визуальная рекомендация, не обещание совпадения со сценой владельца.

### 6.8. Preview

- Default: локальный тёмный test canvas 16:9.
- Фон показывает шахматную прозрачность без белой вспышки.
- Редактор не получает protected output token.
- Preview file загружается через session-scoped API.
- Object URLs освобождаются при смене, logout и destroy.
- Audio preview запускается только явным пользовательским действием.
- Video preview по умолчанию muted.
- Закрытие preview останавливает media element.
- Никакой публикации preview в Widget Bus.

Опциональный Twitch Embed рассматривается после MVP.
Он требует отдельного privacy текста, реального hostname и проверки правил embed.
OBS screenshot bridge остаётся отдельным проектом с явным разрешением.

## 7. Авторизация и права

### 7.1. Что уже можно использовать

Сейчас в `app/moderator_console_routes.py` есть:

- `save_grant(account_id, channel, data)`.
- `list_grants(account_id, channel)`.
- `create_invite(account_id, channel, twitch_user_id, ttl_minutes=15)`.
- `validate_invite(invite_token)`.
- `exchange_invite(invite_token, twitch_access_token)`.
- `authenticate_session(token, permission='')`.
- `get_moderator_context(session)`.
- `save_moderator_preferences(session, data)`.
- `send_moderator_tts(session, data)`.
- `list_moderator_tts_commands(session)`.

Grant привязан к account, normalized channel и stable Twitch user ID.
Текущие независимые permissions: `send_tts`, `play_media`, `play_sound`, `upload_media`.
Invite хранится как hash, одноразовое использование защищено транзакцией.
Default invite TTL: 15 минут, допустимое окно сейчас 1–60 минут.
Session хранится как hash и имеет фиксированный TTL 55 минут.
Disable grant отзывает его текущие sessions.
Permissions перечитываются при authentication.

Эти свойства сохраняются, но не переносятся в gateway через импорт owner application.

### 7.2. Чего сейчас не хватает

- Logout текущей сессии.
- Управления отдельными устройствами/сессиями.
- Безусловной отмены invite при отзыве grant.
- Проверки enabled account/channel при каждом session request.
- Полного channel rename contract для grant/session таблиц.
- Cookie/CSRF boundary для независимого сайта.
- Durable/shared login transaction для нескольких workers.
- Явной политики Twitch-side token revoke.
- Ограничения unauthenticated login ingress.

Сейчас неиспользованное приглашение может снова стать пригодным после disable/enable grant до expiry.
Новый lifecycle должен исключить такое восстановление доступа.

### 7.3. Browser session contract

Предлагаемая cookie:

```text
Name: __Host-moderator_session
Secure: true
HttpOnly: true
Path: /
Domain: отсутствует
SameSite: Lax
Lifetime: не дольше серверной session
```

В production нет fallback к insecure cookie.
Локальная HTTP fake-среда использует отдельную явно тестовую конфигурацию.
Она не может случайно активироваться при публичном hostname.

Session token:

- Криптографически случайный.
- Непрозрачный для frontend.
- Хранится как hash в core.
- Не попадает в JSON, логи и browser storage.
- Меняется после успешного login.
- Привязан к выбранному scope и grant version.
- Проверяется заново при каждой mutation.
- Не продлевается бесконечно от SSE heartbeat.

Baseline: сохранить максимальное окно 55 минут без silent indefinite refresh.
Дополнительно не превышать подтверждённый срок provider identity/token, если он известен.
Проверить актуальные требования Twitch при реализации login adapter.
Twitch revocation не обещается мгновенным без отдельной перепроверки provider.
Локальный owner revoke должен действовать независимо от доступности Twitch.

### 7.4. CSRF и origin

Для browser mutations обязательны:

1. Валидная server session или pre-auth browser transaction.
2. Точное совпадение Origin с настроенным public origin.
3. CSRF token, связанный с сессией/transaction.
4. Разрешённый HTTP method и Content-Type.
5. Ограничение body size.

Отклонять `Origin: null` и неожиданные origins.
Не использовать permissive «если Origin отсутствует, значит всё хорошо» для browser mutations.
SameSite является дополнительной защитой, не заменой CSRF.
GET/HEAD не выполняют commands, approvals, revoke или logout.
Login start также защищается от login CSRF.
Для machine bridge отдельный credential contract, не ослабление browser policy.

Frontend и browser API обслуживаются с одного origin.
Production CORS по умолчанию не включается.
При действительно необходимом втором origin используется точный allowlist.
`Access-Control-Allow-Origin: *` с credentials не допускается.

### 7.5. Новые функции identity/session

```python
async def begin_login(invite_token, browser_nonce): ...
async def poll_login(transaction_id, browser_nonce): ...
async def complete_login(transaction_id, browser_nonce, csrf_proof): ...
async def reconcile_login_delivery(transaction_id, browser_nonce): ...
async def authenticate_browser_session(raw_session): ...
async def revoke_session(session_id, actor): ...
async def revoke_subject_sessions(scope, twitch_user_id, actor): ...
async def cancel_invite(invite_id, actor): ...
async def invalidate_scope_sessions(scope, reason): ...
async def gc_expired_login_transactions(now): ...
```

`complete_login` читает verified provider identity только из серверной transaction,
не принимает её от браузера. `reconcile_login_delivery` ограничен nonce/TTL и delivery state.
`complete_login` атомарно:

- Проверяет live invite и ожидаемого Twitch пользователя.
- Проверяет provider application binding, когда provider возвращает эти сведения.
- Повторно проверяет account/channel/grant.
- Сравнивает grant version.
- Отмечает invite использованным.
- Создаёт session.
- Записывает structured audit.
- Возвращает raw session только доверенному gateway для Set-Cookie.

Не включать старый raw-token `POST /api/moderator-console/session` во внешний allowlist.

### 7.6. Матрица прав

| Действие | Требуемое право | Scope |
|---|---|---|
| Читать approved media | `play_media` | Текущий workspace |
| Preview approved media | `play_media` | Текущий workspace |
| Отправить media cue | `play_media` | Текущий workspace |
| Загрузить на проверку | `upload_media` | Текущий workspace |
| Читать свои pending uploads | `upload_media` | Workspace + actor |
| Читать/прослушать sound | `play_sound` | Текущий workspace |
| Отправить sound cue | `play_sound` | Текущий workspace |
| Отправить TTS | `send_tts` + enabled policy | Текущий workspace |
| Читать свою историю | Действующая session | Workspace + actor |
| Cancel своей queued cue | Новое `cancel_own_cues` | Workspace + actor |
| Смотреть общую очередь | Новое `view_channel_queue` | Текущий workspace |
| Stop активных outputs | Новое `stop_output` | Текущий workspace |
| Replace активного media | Новое `replace_media` | Текущий workspace |
| Управлять grants | Owner-only | Локальная панель |
| Одобрять загрузки | Owner-only | Локальная панель |
| Emergency Stop/resume | Owner-only | Выбранный scope |

Новые права по умолчанию не выдаются существующим grants.
Upload-only пользователь получает отдельный рабочий экран загрузок.
Ему не требуется `play_media`, чтобы увидеть свой upload status.
Скрытие кнопок дополняет backend check, но не заменяет его.
Moderator `stop_output` не является owner persistent kill switch.

### 7.7. Revoke и disabled scope

При disable grant:

- Увеличить grant version.
- Отозвать все sessions grant.
- Отменить ещё не использованные invites grant.
- Закрыть его event subscriptions.
- По предлагаемому baseline отменить его ещё не dispatched cues.
- Уже выполняющийся вывод остановить только явным Stop либо отдельно выбранной политикой.

При disable account/channel:

- Не разрешать новые sessions.
- Немедленно блокировать новые requests и dispatch.
- Отменять queued work этого scope.
- Не подставлять соседний enabled account.

При channel rename:

- Использовать canonical stable Twitch channel identity, когда подтверждена.
- Выполнить additive mapping старых normalized logins.
- Не смешивать одинаковый login разных account scopes.
- Legacy rows не мигрировать по эвристике «первый похожий канал».

## 8. Новый API сайта

### 8.1. Общие правила

Все маршруты этого раздела **новые**.
Prefix: `/api/mod-site/v1`.
Browser не вызывает owner API и старые moderator endpoints напрямую.
Gateway реализует фиксированную карту операций, не общий reverse proxy.
Body models запрещают неизвестные поля, где нет специально расширяемого объекта.
Scope берётся из session.
В body команды нет `account_id`, `channel`, actor или output token.

### 8.2. Login и context

| Method | Path | Вход | Результат |
|---|---|---|---|
| GET | `/auth/bootstrap` | Нет | Pre-auth CSRF + browser nonce cookie |
| POST | `/auth/start` | `invite_token` | Transaction + public device data |
| POST | `/auth/poll` | `transaction_id` | Pending/denied/expired/identity_verified |
| GET | `/auth/status/{transaction_id}` | Browser transaction | Read-only safe status |
| POST | `/auth/complete` | Transaction + nonce/CSRF | Consume invite, Set-Cookie |
| POST | `/auth/logout` | Нет | Revoke session, clear cookies |
| GET | `/context` | Session | Actor, scope label, capabilities, limits |
| GET | `/session` | Session | Safe session status, expiry |
| PUT | `/preferences` | Allowlisted preferences | Сохранённые preferences |

`/auth/bootstrap` не создаёт authenticated grant/session.
Transient nonce выдаётся с no-store и ограничением частоты.
После login pre-auth nonce/CSRF заменяются session-bound значениями.

### 8.3. Context DTO

```ts
export type ModeratorContext = {
  ok: true;
  actor: {
    twitchUserId: string;
    displayName: string;
  };
  workspace: {
    id: string;
    channelLabel: string;
    revision: number;
  };
  session: {
    expiresAt: string;
  };
  permissions: string[];
  capabilities: {
    media: boolean;
    sound: boolean;
    tts: boolean;
    placement: boolean;
    cancelOwn: boolean;
    outputTelemetry: boolean;
  };
  limits: {
    ttsMaxLength: number;
    mediaMaxBytes: number;
    queueMaxPending: number;
  };
  policyRevision: number;
  csrfToken: string;
};
```

Capabilities описывают фактически доступные backend/output возможности.
Они не заменяют permissions.
Если telemetry не реализована для output, UI получает `false`.
Отсутствующая policy не превращается в permissive default.

### 8.4. Library и uploads

| Method | Path | Вход | Результат |
|---|---|---|---|
| GET | `/library/media` | `q`, `kind`, `favorite`, `cursor`, `limit` | Approved page |
| GET | `/library/sounds` | `q`, `favorite`, `cursor`, `limit` | Approved page |
| GET | `/library/media/{id}/preview` | Session | Scoped binary |
| GET | `/library/sounds/{id}/preview` | Session | Scoped binary |
| PUT | `/favorites/media/{id}` | `favorite`, `expected_revision` | Updated state |
| PUT | `/favorites/sounds/{id}` | `favorite`, `expected_revision` | Updated state |
| POST | `/uploads/media` | Multipart file + upload intent key | Quarantine job |
| GET | `/uploads` | Own cursor | Собственные jobs |
| GET | `/uploads/{id}` | Own ID | Processing/approval status |

Для видео определить `Range` contract, если preview использует streaming.
Проверять auth и scope также на range request.
Не отдавать произвольные byte ranges без лимитов.
Pending preview, если нужен, доступен только автору/owner после безопасной обработки.

### 8.5. Cue routes

| Method | Path | Вход | Результат |
|---|---|---|---|
| POST | `/cues` | Typed cue + idempotency header | 202 и Cue DTO |
| GET | `/cues` | own/channel view, cursor | Разрешённая история/очередь |
| GET | `/cues/{id}` | Opaque ID | Текущее состояние |
| GET | `/cues/by-intent/{key}` | Own intent key | Найденная команда/404 |
| POST | `/cues/{id}/cancel` | `expected_revision` | Cancel result |
| POST | `/controls/stop` | `target`, control intent key | Stop operation |
| GET | `/outputs/status` | Session | Safe readiness/evidence |
| GET | `/events` | Last-Event-ID | Scoped SSE |

SSE не принимает control messages.
WebSocket для браузера модератора не нужен в первом варианте.
Существующий owner `/ws` не публикуется через gateway.

### 8.6. Discriminated cue request

```ts
export type CreateCueRequest =
  | {
      kind: 'media';
      mediaId: string;
      mediaVersion: number;
      placement: NormalizedPlacement;
      durationMs: number;
      mode: 'queue' | 'replace';
      expectedPolicyRevision: number;
    }
  | {
      kind: 'sound';
      trackId: string;
      expectedPolicyRevision: number;
    }
  | {
      kind: 'tts';
      text: string;
      voiceAlias?: string;
      expectedPolicyRevision: number;
    };
```

Library projection возвращает artifact version; media cue сохраняет выбранную версию.
Она проверяется при admission и непосредственно перед dispatch вместе с approval.
Изменение материала не подменяет содержимое уже принятой команды.
Параметры громкости sound не добавлять без server policy bounds.
Raw provider voice ID не принимается.
`replace` требует отдельного права и подтверждённой поддержки cancel renderer.
Если поддержка не готова, capability false и route отклоняет режим.

Пример нового запроса:

```http
POST /api/mod-site/v1/cues
Content-Type: application/json
X-CSRF-Token: <session-bound-csrf>
Idempotency-Key: <stable-action-intent>

{
  "kind": "media",
  "mediaId": "42",
  "mediaVersion": 1,
  "placement": {
    "x": 0.1,
    "y": 0.1,
    "width": 0.25,
    "height": 0.25
  },
  "durationMs": 5000,
  "mode": "queue",
  "expectedPolicyRevision": 7
}
```

Это пример формы, не реальные IDs или готовый curl для production.

### 8.7. Ошибки

```json
{
  "ok": false,
  "error": {
    "code": "queue_full",
    "params": {
      "limit": 20
    }
  },
  "request_id": "opaque-request-id"
}
```

Предлагаемые codes:

- `session_expired`.
- `session_revoked`.
- `invite_expired`.
- `identity_mismatch`.
- `permission_denied`.
- `scope_disabled`.
- `policy_disabled`.
- `policy_changed`.
- `asset_not_found`.
- `asset_not_approved`.
- `placement_invalid`.
- `media_validation_failed`.
- `upload_too_large`.
- `quota_exceeded`.
- `queue_full`.
- `idempotency_conflict`.
- `revision_conflict`.
- `runtime_unavailable`.
- `output_unavailable`.
- `stop_pending`.
- `internal_error`.

HTTP statuses:

- 400: malformed request.
- 401: отсутствующая/невалидная/истёкшая session.
- 403: право или policy запрещает действие.
- 404: ресурс отсутствует или чужой scope.
- 409: version/idempotency/state conflict.
- 413: body/file size.
- 415: неподдерживаемый тип.
- 422: validation fields.
- 429: quota с Retry-After.
- 503: runtime/зависимость не готовы.

Не превращать все 403 в generic error до client translation.
Нынешние общие handlers могут терять detail-строку и возвращать generic status code.
Для нового API нужны typed exceptions с сохранением allowlisted semantic code.
Legacy routes сохраняют свой compatibility contract.

## 9. Очередь и исполнение

### 9.1. Не путать ленту команд и очередь проигрывателя

Сайт показывает одну ленту команд.
Внутри сохраняются разные исполнительные пути:

- Visual media.
- Soundboard.
- TTS через существующий audio transport.

Новая durable очередь описывает намерения и lifecycle.
Она не является вторым TTS/audio engine.
Одновременное visual media и audio разрешается только явной policy.
Несколько TTS не должны накладываться.
Поведение sound вместе с TTS должно быть выбрано до соответствующего этапа.
Рекомендуется общий channel audio admission arbiter с использованием существующих outputs.
Video в MVP muted, чтобы не создать третью конкурирующую audio дорожку.

### 9.2. Тип состояния команды

```ts
export type CueState =
  | 'queued'
  | 'preparing'
  | 'ready'
  | 'dispatched'
  | 'started'
  | 'completed'
  | 'cancel_requested'
  | 'cancelled'
  | 'failed'
  | 'expired'
  | 'unknown';

export type Cue = {
  id: string;
  kind: 'media' | 'sound' | 'tts';
  state: CueState;
  revision: number;
  createdAt: string;
  expiresAt: string;
  actorLabel: string;
  resultCode?: string;
  evidence: {
    level: 'server' | 'renderer' | 'none';
    observedAt?: string;
  };
};
```

`queued`: записано намерение, проигрыватель ещё ничего не подтвердил.
`preparing`: идёт разрешённая подготовка, например TTS synthesis.
`ready`: материал подготовлен и может быть передан output.
`dispatched`: команда передана исполнителю.
`started`: renderer подтвердил начало.
`completed`: renderer подтвердил завершение.
`unknown`: исполнение могло произойти, достоверного итога нет.

Успешный HTTP enqueue никогда не становится `started` автоматически.
Истечение расчётной длительности не является `completed` без evidence.

### 9.3. State transitions

```text
queued → preparing → ready → dispatched → started → completed
   │          │         │          │          │
   ├→ cancelled         │          ├→ unknown │
   ├→ expired           │          └→ failed  ├→ failed
   └→ failed            └→ cancelled          └→ cancel_requested
                                                   │
                                                   ├→ cancelled
                                                   └→ unknown
```

Для media/sound без подготовки разрешён переход `queued → ready`.
Из terminal state нельзя снова сделать queued той же командой.
Повтор пользователя создаёт новую команду с новым intent key.
Поздний ACK не должен оживлять cancelled/expired cue.
Некоторые поздние evidence можно сохранить отдельно без смены terminal state.

### 9.4. Idempotency

Ключ принадлежит одному пользовательскому намерению.
Он создаётся перед первым POST и сохраняется до однозначного результата.
При timeout использовать тот же ключ.
При ручном «создать ещё одну команду» создавать новый ключ.

На сервере:

- Unique key: scope + stable actor ID + idempotency key.
- Canonical payload hash включает kind, asset/text, placement, mode и relevant policy revision.
- Same key + same payload возвращает исходную команду.
- Same key + different payload возвращает 409 `idempotency_conflict`.
- Повтор не списывает quota повторно.
- Пока результат неизвестен, frontend выполняет lookup by intent.
- Retention ключа не короче максимального retry/recovery окна.
- Уже начатое аудио не исполняется повторно автоматически после crash.

Гарантия: не более одной принятой команды на один intent в границах retention.
Exactly-once фактическое воспроизведение в браузере не обещается.
Сеть и падение renderer могут сделать итог неопределённым.

### 9.5. Транзакционный admission

```python
async def create_cue(session, request, intent_key):
    payload = validate_request(request)
    fingerprint = canonical_payload_hash(payload)
    async with immediate_transaction() as tx:
        actor = await require_live_scope_and_grant(tx, session)
        existing = await find_intent(tx, actor, intent_key)
        if existing:
            return require_same_fingerprint(existing, fingerprint)
        await require_permission(tx, actor, payload)
        await require_enabled_policy(tx, actor, payload)
        await require_not_stopped(tx, actor.scope)
        await require_approved_asset_or_voice(tx, actor, payload)
        await reserve_quota(tx, actor, payload)
        cue = await insert_cue(tx, actor, payload, intent_key, fingerprint)
        await append_audit(tx, cue, 'cue_admitted')
        await append_outbox(tx, cue, 'dispatch_requested')
    return cue
```

Пример не содержит сетевых provider calls внутри SQLite transaction.
До implement нужно определить типы, error handling и bounded lock timeout.
Проверки, зависящие от live policy, повторяются перед dispatch.

### 9.6. Dispatcher

Функции:

- `claim_next_cue(scope, lane, worker_id, now)`.
- `prepare_cue(cue)`.
- `dispatch_media(cue)`.
- `dispatch_sound(cue)`.
- `dispatch_tts(cue)`.
- `renew_lease(cue_id, worker_id)`.
- `record_dispatch_result(cue_id, result)`.
- `recover_expired_leases(now)`.
- `cancel_pending_for_scope(scope, reason)`.

Начальный deployment: один dispatcher owner на runtime.
Не запускать dispatcher в каждом gateway worker.
Claim выполняется атомарным SQL state/revision update.
Lease нужен на случай падения процесса.
Перед side effect проверить lease, stop generation, expiry, asset version/approval и current grant.
Grant enabled/permissions update атомарно увеличивает monotonic revision; она сохраняется в cue.
Disable/re-enable не оживляет старую queued cue. Logout/expiry исходной session блокирует
ещё не dispatched work этой session, но не отменяет уже совершённый effect.
После каждого await, способного задержаться, повторить критическую stop/version проверку.

### 9.7. Restart и crash windows

- Crash до commit admission: команды нет.
- Crash после admission до dispatch: команда восстанавливается из БД.
- Crash во время подготовки: безопасная подготовка может повториться по policy.
- Crash после dispatch без ACK: состояние `unknown`, не auto replay.
- Crash после confirmed start: не повторять команду.
- Expired cue после downtime: пометить expired, не запускать старое в эфир.
- Owner kill switch переживает restart.
- Cancelled cues после restart не оживают.
- Quota и command identity не сбрасываются при gateway restart.

### 9.8. TTL и лимиты

Предлагаемые начальные defaults, не текущие лимиты backend:

| Параметр | Предложение | Почему |
|---|---|---|
| Pending cues на workspace | 20 | Ограничить stale backlog |
| Pending cues на actor | 5 | Один пользователь не забивает очередь |
| Cue TTL | 120 секунд | Не запускать сильно устаревшие действия |
| Event reconnect backoff | 1–30 секунд с jitter | Не создавать reconnect storm |
| Renderer heartbeat | 5 секунд | Быстро видеть потерю связи |
| Stale threshold | 15 секунд | Несколько пропущенных heartbeat |
| Начальный media размер на сцене | До 25–35% | Не перекрывать всё автоматически |

Окончательные значения берутся из server context/policy.
Существующие policy limits не повышаются без подтверждения.
Rate limit имеет общий durable backend, не JS таймер.
Login, uploads, previews и cues имеют раздельные бюджеты.

## 10. Output telemetry и Stop

### 10.1. Уровни достоверности

| Уровень | Что известно | Допустимая подпись |
|---|---|---|
| DB commit | Команда сохранена | «В очереди» |
| Dispatch | Исполнитель получил команду/событие | «Передано проигрывателю» |
| Browser start event | Media element начал playback | «Проигрыватель сообщил о запуске» |
| Browser ended event | Media element завершил playback | «Проигрыватель сообщил о завершении» |
| Manual OBS acceptance | Проверен итог на целевом устройстве | Только запись приёмки |

Browser ACK не доказывает, что источник видим в live OBS-сцене.
Audio `playing` не доказывает, что зрители услышали звук.
Нельзя показывать универсальный зелёный «В эфире» по одному heartbeat.

### 10.2. Новый output event contract

```json
{
  "cue_id": "opaque-cue-id",
  "dispatch_id": "opaque-dispatch-id",
  "output_id": "paired-output-id",
  "lease_generation": 4,
  "sequence": 12,
  "event": "started",
  "position_ms": 0
}
```

Сервер добавляет received timestamp самостоятельно.
Client clock не управляет ordering, TTL или grants.
ACK capability отдельная от moderator session и owner token.
Renderer-only API `/api/moderator-output/v1` не публикуется в browser moderator allowlist:

| Method/path | Назначение |
|---|---|
| POST `/sessions` | Register paired output instance + capability version |
| POST `/sessions/{id}/heartbeat` | Renew bounded lease |
| POST `/sessions/{id}/evidence` | Correlated started/ended/failed/stopped evidence |
| DELETE `/sessions/{id}` | Закрыть instance без rotation owner token |

Instance хранит scope/output binding, token reference, generation и lease expiry.
Owner pairing задаёт ограниченную ACK authority; existing read token не расширяется молча.
Read token существующего protected output не расширяется молча до control permissions.
ACK разрешает только отчёт по assigned command/output.
Запретить ACK чужого scope, старой generation, неизвестной команды и невозможного перехода.
Ошибки ACK не должны раскрывать материалы соседнего канала.

### 10.3. Несколько открытых Browser Sources

Нужно выбрать один активный executor на output lane/scope.
Иначе два одинаковых источника могут воспроизводить одну команду дважды.
Предлагается короткая output lease с fencing generation.
Observer outputs могут показывать диагностику, но не исполнять cue.
Старая lease после reconnect не может подтвердить новую команду.
Автоматический failover не должен replay уже dispatched аудио.
Если renderer не поддерживает fencing, использовать честный degraded mode.

### 10.4. Разные операции остановки

`Cancel own queued cue`:

- Не запускавшаяся своя команда становится cancelled.
- Не влияет на текущий playback.
- Требует actor ownership и permission.

`Stop output`:

- Запрашивает остановку текущего target lane.
- Не отключает grants.
- Не блокирует будущие команды постоянно.
- Итог может быть accepted/unverified.

`Owner Emergency Stop`:

1. Атомарно включить persistent stopped state.
2. Увеличить scope stop generation.
3. Запретить новые admissions.
4. Отменить queued/preparing work по scope.
5. Послать cancel активным поддерживаемым outputs.
6. Отдельно записать состояние каждого output.
7. Показать владельцу confirmed и unconfirmed результаты.
8. Не делать auto resume после reconnect/restart.

`Revoke access`:

- Отзывает session/grant.
- Не притворяется физической остановкой уже проигрываемого медиа.

### 10.5. Реализация Stop

Новые функции:

```python
async def request_emergency_stop(scope, actor, intent_key): ...
async def stop_media_lane(scope, generation): ...
async def stop_sound_lane(scope, generation): ...
async def stop_tts_lane(scope, generation): ...
async def aggregate_stop_evidence(operation_id): ...
async def resume_scope(scope, actor, expected_revision): ...
```

Stop доступен из dispatched/started/unknown, а не только при подтверждённом playback.
В preparing/ready он ставит cancellation marker до следующего side effect.
Безопасный повтор Stop сохраняет identity stop operation и не создаёт play command.
Late ACK не отменяет marker. Unknown outcome не является причиной прятать кнопку Stop.
Owner Stop не должен ждать занятой обычными cues очереди.
Если durable запись не удалась, всё равно попытаться остановить активный вывод.
Но показать ошибку сохранения блокировки и не обещать restart safety.
Частичная остановка не превращается в общий success.
Resume не перезапускает отменённые команды.
Модератор не получает право Resume owner kill switch.

### 10.6. Audio cancellation

`AudioQueue.clear()` сейчас не является scoped emergency stop.
Нужен явный cancel текущего элемента по correlation/scope, а не только очистка списка.
Синтезатор и playback transport должны иметь cancellation path.
Если provider нельзя прервать, прекращается доставка его позднего результата.
Поздний audio result сравнивает stop generation перед публикацией.
В соседнем канале playback продолжается.
Новый сайт не создаёт отдельный скрытый audio element для stream output.
Локальный preview является отдельным пользовательским прослушиванием, не output lane.

## 11. Медиа, звук и TTS: конкретные доработки

### 11.1. Медиа: текущий baseline

В `app/moderator_media_routes.py` сейчас:

- Изображения: PNG, GIF, WebP.
- Максимальный размер изображения: 8 MiB.
- Видео: MP4, WebM.
- Максимальный размер видео: 20 MiB.
- Максимальная проверяемая длительность: 15 секунд.
- Изображения проверяются через Pillow, размеры ограничены 3840×2160.
- Видео проверяется через signature и ffprobe duration.
- Video width/height в текущем upload записываются как нули.
- Moderator upload создаёт `approved=false`.
- Owner upload сразу approved.
- Media cue принимает ID и idempotency key, но не normalized placement.
- Position сейчас scope-wide: preset, width percent, duration и fade.

Эти лимиты не увеличиваются в первой версии автоматически.
Нужны measured limits на целевой машине, а не только размер загрузки.

### 11.2. Новый upload pipeline

```text
request stream
  → ingress size limit
  → quarantine temp file
  → signature/type validation
  → bounded decode/probe
  → metadata extraction
  → safe thumbnail
  → database upload record
  → owner review
  → approved library
```

Функции:

- `receive_quarantined_upload(stream, scope, actor, limits)`.
- `inspect_image(path, limits)`.
- `inspect_video(path, limits)`.
- `create_safe_thumbnail(path, metadata)`.
- `finalize_upload_record(tx, artifact, metadata)`.
- `approve_upload(upload_id, owner, expected_revision)`.
- `reject_upload(upload_id, owner, reason_code)`.
- `cleanup_unreferenced_artifact(artifact_id)`.

Дополнительные ограничения:

- Проверять decoded dimensions и pixel budget.
- Ограничить число кадров и суммарную decoded animation cost.
- Проверить codec/profile и реальные video dimensions.
- ffprobe/decoder запускать с timeout и resource limits.
- Не выполнять shell-команды из filename.
- Не передавать внешнюю сеть media processor.
- SVG/HTML/JS и archives не принимать как visual media.
- Metadata пользовательского файла не считать доверенной.
- Если ffprobe отсутствует, видео недоступно с понятной ошибкой.
- Не подменять отсутствие проверки автоматическим approval.

### 11.3. Файл и транзакция

SQLite commit и filesystem rename не являются одной транзакцией.
Поэтому нужен recovery-aware протокол:

1. Записать temp artifact со случайным internal name.
2. Проверить и вычислить checksum.
3. Зарегистрировать staging reference.
4. Выполнить atomic rename в пределах одного filesystem.
5. Завершить DB record.
6. При ошибке откатить новый artifact или оставить recoverable staging state.
7. Startup reconciler разбирает только собственные staging records.

Не удалять существующий файл, совпавший по пользовательскому имени.
Хранить path отдельно от display name.
Не использовать channel text напрямую как путь.
Orphan cleanup требует доказательства отсутствия DB references.
Не выполнять общий destructive cleanup в рамках сайта.

### 11.4. Approval lifecycle

Предлагаемые upload states:

```text
receiving → processing → pending_review → approved
     │          │              └→ rejected
     └→ failed  └→ failed
```

Approval относится к конкретной версии artifact.
Замена байтов под approved ID запрещена.
Изменение файла создаёт новую версию и требует повторной проверки.
Unapprove блокирует новые cues и отменяет ещё не dispatched cues этого материала.
Активный playback обрабатывается явным Stop policy.
В audit остаётся кто загрузил, кто проверил и checksum.
Foreign keys не удаляют audit cascade вместе с asset; tombstone сохраняет историческую подпись,
но не разрешает playback удалённого/недоступного материала.

### 11.5. Sound

Использовать существующую approved Soundboard library.
Сайт не принимает произвольный audio URL.
Moderator sound upload не добавляется автоматически: текущего `upload_media` недостаточно для этого нового продукта.
Local preview подписан как «Прослушать здесь».
Команда в эфир подписана отдельно: «Отправить звук».
Audio preview имеет собственный stop и прекращается при закрытии.
Cooldown и volume policy проверяются сервером.
Sound dispatch получает command correlation ID.
Stop действует только на exact output scope.

### 11.6. TTS

Использовать `send_moderator_tts`/voice policy как источник действующих ограничений.
При рефакторинге выделить admission/dispatch, не вызвать старый enqueue дважды.
Если новый ledger уже принял cue, adapter должен использовать тот же stable command identity.
Два независимых quota reservation для одного действия запрещены.

Frontend функции:

- `loadApprovedVoices()`.
- `selectVoice(alias)`.
- `validateTtsDraft(text, policy)`.
- `countTtsLength(text)`.
- `submitTtsIntent(draft, intentKey)`.
- `renderTtsPolicyWarning(policy)`.

Длина текста должна считаться одинаково клиентом и Python backend.
JavaScript `.length` считает UTF-16 code units, Python length отличается для части символов.
Контракт явно выбирает правило и тестирует emoji/комбинируемые символы.
Без backend approval нельзя передать raw voice/provider/model.
При `allow_voice_choice=false` UI объясняет выбранный владельцем голос.
Пустой approved voice list блокирует отправку, не выбирает случайный голос.
TTS текст не публикуется в Twitch-чат как побочный эффект сайта.

## 12. Хранилище, миграции и события

### 12.1. Предлагаемые новые таблицы

| Таблица | Назначение | Ключевой инвариант |
|---|---|---|
| `moderator_site_login_transactions` | Login binding/expiry | Одна browser-bound transaction |
| `moderator_site_sessions` | Cookie session metadata | Hash token, grant version, revoked |
| `moderator_site_cues` | Durable commands | Unique scope+actor+intent |
| `moderator_site_outbox` | Задания dispatcher/events | Atomic с admission |
| `moderator_site_output_leases` | Единственный исполнитель | Scope+lane+generation |
| `moderator_site_output_events` | Renderer evidence | Dedup dispatch+output+sequence |
| `moderator_site_scope_state` | Stop/policy revision | Persistent generation |
| `moderator_site_quota` | Shared reservation/window | Atomic scoped limits |
| `moderator_site_upload_jobs` | Processing/approval | Scope+actor+artifact version |
| `moderator_site_audit` | Structured security/action audit | Immutable event identity |

Перед миграцией решить, какие lifecycle поля безопасно добавить к существующим tables.
Не дублировать grants: текущая grant identity остаётся общей.
Если используются новые site sessions, старые console sessions не удаляются.
Feature schema добавляется через `ensure_schema()` и idempotent migrations.
GET context не создаёт default rows.
Новая версия schema не делает старые owner routes неработоспособными.

### 12.2. Основные поля cue

- `id`: opaque command identity.
- `account_id`: действующий owner scope.
- `canonical_channel_id`: подтверждённая channel identity либо явная compatibility mapping.
- `channel`: совместимый normalized storage label.
- `twitch_user_id`: stable actor ID.
- `session_id`: audit reference, не raw token.
- `kind`.
- `payload_json`.
- `payload_hash`.
- `idempotency_key`.
- `status`.
- `revision`.
- `policy_revision`.
- `stop_generation`.
- `created_at`, `expires_at`, `updated_at`.
- `dispatch_id`, `lease_owner`, `lease_expires_at`.
- `result_code`.

Индексы проектируются по реальным access paths:

- Scope + status + created_at + id.
- Scope + actor + created_at + id.
- Unique scope + actor + idempotency_key.
- Outbox status + next_attempt_at.
- Session token_hash.
- Upload scope + actor + status.

### 12.3. Audit

Structured audit содержит:

- Event ID и timestamp.
- Stable actor ID или owner identity.
- Scope.
- Session reference.
- Request/cue/dispatch reference.
- Action.
- Allow/deny/result code.
- Allowlisted safe details.

Существующий общий `log_action` best-effort и использует текстовые details.
Новый command admission должен атомарно записывать свой audit/outbox.
При отказе БД новые side effects не отправляются.
Дубликат request фиксируется без повторного playback.
Login denials ограничиваются и агрегируются, чтобы audit не стал DoS-целью.
TTS plaintext не требуется для каждого audit event.
Tokens, invite fragments, cookies, Authorization, raw filesystem paths и provider secrets
редактируются из логов. Default telemetry локальная, bounded, без внешнего analytics SDK.
Полный TTS текст доступен только actor/owner по явной visibility policy, не общей event ленте.
Retention по умолчанию предложить отдельно и подтвердить до production.

### 12.4. SSE

Events:

- `context.updated`.
- `session.revoked`.
- `library.updated`.
- `upload.updated`.
- `cue.updated`.
- `output.updated`.
- `scope.stopped`.
- `resync.required`.

Каждое событие содержит monotonic sequence в разрешённом scope.
Resume использует Last-Event-ID.
При пропуске retention окна сервер требует полный snapshot.
Snapshot и cursor должны иметь согласованную границу, чтобы не потерять update между ними.
Payload фильтруется по actor permissions так же, как GET.
Grant downgrade закрывает поток или меняет projection без утечки чужих данных.
Proxy не буферизует SSE бесконечно.

## 13. Frontend: функции и управление состоянием

### 13.1. Component lifecycle

```ts
export type MountedComponent = {
  element: HTMLElement;
  destroy(): void;
};

export function createWorkspacePage(
  services: AppServices,
): MountedComponent {
  const scope = createLifecycleScope();
  const element = document.createElement('main');
  // В реализации подписки, listeners и requests принадлежат scope.
  return {
    element,
    destroy() {
      scope.dispose();
      element.remove();
    },
  };
}
```

Нужны `AbortController`, disposer для subscriptions и единый timer owner.
Destroy снимает pointer handlers, ResizeObserver, media preview, listeners и SSE.
Переход между страницами не накапливает повторные poll loops.
Компонент не вызывает global document queries для чужого subtree.
Server data вставляется через `textContent`, не raw `innerHTML`.

### 13.2. API client

`request<T>(path, options)`:

1. Принимает только относительный allowlisted API path.
2. Добавляет credentials same-origin.
3. Для mutation добавляет CSRF header.
4. Добавляет request correlation и intent key при наличии.
5. Не ставит JSON Content-Type на FormData.
6. Поддерживает timeout и AbortSignal.
7. Проверяет HTTP status и structured body.
8. Превращает error в typed `ApiError`.
9. На 401 инициирует session-expired flow.
10. Не повторяет POST автоматически с новым ключом.

`parseApiError(response, body)` не создаёт `[object Object]`.
Unknown code переводится в safe generic message с request ID.
Raw server traceback не показывается пользователю.

### 13.3. Stores

`session-store`:

- Safe actor/context, expiry, auth phase.
- Не хранит raw session token.

`workspace-store`:

- Scope label, capabilities, policy revision.
- Не выбирает scope по случайному первому элементу массива.

`draft-store`:

- Selected asset, placement, text, voice alias.
- Dirty state и current intent.
- Смена языка не сбрасывает draft.

`queue-store`:

- Command map, ordered IDs, revision, last cursor.
- Duplicate SSE events игнорируются.
- Старый revision не перезаписывает новое состояние.

`connection-store`:

- HTTP reachability отдельно от runtime readiness и output heartbeat.
- Offline не называется «Токен истёк».

### 13.4. Submit flow

```text
validate draft
  → allocate intent once
  → disable duplicate submit
  → POST cue
  → accepted: retain command ID
  → timeout: lookup same intent
  → definitive rejection: show reason
  → explicit new action: allocate new intent
```

После timeout UI пишет «Результат пока неизвестен», а не «Не отправлено».
Содержимое draft не очищается до принятого решения.
Keyboard shortcut отправки не активен в любом input без явного контекста.
Тап по disabled submit ничего не делает.
Смена policy между загрузкой и POST даёт actionable conflict.

### 13.5. Локализация

Словари: `ru.ts`, `en.ts`, `ua.ts` с одинаковым набором ключей.
HTML lang для украинского: `uk`, UI preference может сохранять existing key `ua`.
Fallback: русский, затем безопасный текст, не technical key.
Все button labels, tooltips, aria labels и empty/error states переводятся.
Названия файлов и пользовательские TTS-тексты не переводятся.
`Intl` используется для дат, времени и размеров файлов.
Переключение языка не remount всей страницы и не теряет focus/draft.

## 17. Карта существующего API для переноса

Этот раздел описывает **проверенный baseline**, а не новые browser routes.
Он нужен, чтобы исполнитель не переписал уже готовые библиотеки и grant logic.
Scope, response projection и semantic errors адаптируются через service layer.
Ни один prefix ниже не должен целиком публиковаться внешним proxy.

### 17.1. Console и identity

Prefix `C = /api/moderator-console`.
Owner scope prefix `A = C/admin/accounts/{account_id}/channels/{channel}`.

| Existing method/path | Existing функция | Использование в проекте |
|---|---|---|
| PUT `A/grants/{twitch_user_id}` | `api_save_grant` → `save_grant` | Owner выдача прав |
| GET `A/grants` | `api_list_grants` → `list_grants` | Owner список доступа |
| POST `A/grants/{twitch_user_id}/invite` | `api_create_invite` → `create_invite` | Owner invite generation |
| POST `C/session` | `api_exchange_invite` | Не выставлять в remote allowlist |
| POST `C/twitch-device` | `api_start_twitch_device` | Основа нового login adapter |
| POST `C/twitch-device/poll` | `api_poll_twitch_device` | Основа transaction polling |
| GET `C/me` | `api_session_me` | Источник safe session projection |
| GET `C/context` | `api_moderator_context` | Основа нового context DTO |
| PUT `C/preferences` | `api_moderator_preferences` | Approved voice preferences |
| POST `C/tts` | `api_moderator_tts` | Разделить admission/dispatch при адаптации |
| GET `C/tts/commands` | `api_moderator_tts_commands` | Legacy own history |

Текущий media config PUT подставляет defaults для пропущенных fields.
Новый PATCH нельзя реализовать передачей partial body в этот PUT: требуется сохранение untouched fields.
Текущий `/context` возвращает permissions, approved voice aliases/labels, policy и preferences.
Он не возвращает moderator raw provider voice IDs.
Текущий `/tts/commands` ограничен последними 50 командами actor.
Текущий frontend использует bearer из sessionStorage, а не HttpOnly session.
Текущий `/moderator-console` загружает общий panel CSS.

### 17.2. Media

Prefix `M = /api/moderator-media`.
Owner scope prefix `MA = M/admin/{account_id}/{channel}`.

| Existing method/path | Вход / результат | Ограничение |
|---|---|---|
| GET `M/library` | Approved `items` с favorite | Нет dimensions в moderator DTO |
| POST `M/library` | Multipart `file` → pending item | `upload_media` |
| PUT `M/favorites` | `media_ids` → replaced IDs | До 100, exact approved scope |
| GET `M/library/{media_id}/preview` | Scoped binary | `play_media`, no-store |
| POST `M/cues` | `media_id`, `idempotency_key` | Нет per-cue placement |
| GET/POST `MA/library` | Owner inventory/upload | Owner upload сразу approved |
| PUT `MA/library/{media_id}` | `approved` | Exact-scoped approval |
| PUT `MA/config` | queue policy + preset/width/duration/fade | Общий mutable config |
| POST `MA/control` | stop/clear/kill_switch | Только media subsystem |
| GET `MA/token` | Mask/status | Не для moderator browser |
| POST `MA/token` | Rotation, raw token + URL | Local owner only |
| POST `MA/token/reveal` | Existing token + URL | Local owner only |

Current media limits: cooldown 2 секунды, максимум 20 commands/min на actor/scope.
Сохранённые commands участвуют в DB-based quota.
Same key не сравнивает payload fingerprint.
Current replace очищает старые queued commands, но не реализует безопасную renderer cancellation.

Protected output:

- `/widget/moderator-media`.
- `/api/moderator-media/public/state`.
- `/api/moderator-media/public/file/{media_id}`.
- `/api/moderator-media/public/complete`.

Current `complete` переводит scoped queued command в completed без проверки renderer evidence.
Новые v2 site cues нельзя завершать через старый compatibility `complete`.
Нужны protocol version/partition и один владелец dispatch каждого command.
Legacy polling не должен одновременно потреблять новые leased cues.
Это обязательный compatibility gate MOD-14/17.

### 17.3. Sound

Prefix `S = /api/moderator-console/sounds`.
Owner prefix `SA = /api/moderator-console/admin/sounds/accounts/{account_id}/channels/{channel}`.

| Existing method/path | Вход / результат | Ограничение |
|---|---|---|
| GET `S` | Approved items | `play_sound` |
| POST `S/play` | `track_id`, `idempotency_key` | Admission journal + WS dispatch |
| POST `S/stop` | accepted, telemetry unverified | Не persistent kill switch |
| PUT `S/favorites` | `track_ids` | Полная замена actor favorites |
| GET `S/{track_id}/preview` | Scoped binary | Approved file |
| GET `SA` | Tracks, policy, OBS configured | Owner only |
| PUT `SA/tracks/{track_id}` | `enabled` | Scoped approval |
| PUT `SA/policy` | enabled, cooldown, max/min | Owner policy |
| POST `SA/obs-token` | widget URL | Hash-only sound token |

Existing core функции:

- `play_moderator_sound(session, data)`.
- `stop_moderator_sound(session)`.
- `soundboard_library.store_uploads(files)`.
- `soundboard_library.play_track(...)`.
- `soundboard_library.stop_playback(...)`.

Owner Soundboard tracks глобальные; approvals scoped.
Legacy unscoped audio-read совместимость не становится private scoped library автоматически.
Не объявлять такую библиотеку хранилищем конфиденциальных файлов.

### 17.4. TTS и channel audio

Existing source policy: `twitch_moderator_message`.
Default policy limits: 5 секунд cooldown, 5 requests/min, 300 символов.
Policy API допускает конфигурируемые ограничения в собственных bounds.
Runtime quota сейчас in-memory.
Moderator source запрещает permissive legacy fallback при отсутствии explicit policy.

Existing `AudioQueue` является in-memory dispatcher/accounting, не durable playback FIFO.
Синтез и браузерное воспроизведение имеют дополнительные собственные очереди.
`accepted` может появиться без фактического вывода при suppressed engine failure/disabled state.
Текущий output source selection не является lease и не исключает две копии одного source.

Runtime audio arbitration должен быть по canonical Twitch channel.
Account scope сохраняется для ownership и permissions.
Два account одного Twitch channel не должны создать две независимые конкурирующие audio lanes.
Если legacy producer обходит arbiter, нельзя включать capability гарантированного single-output.
В таком deployment показывать ограниченную поддержку до интеграции всех relevant producers.

## 18. Проверенные дефекты, которые нельзя переносить

### P0: перед любым внешним доступом

1. **Wildcard proxy может открыть owner routes через loopback policy.**
   Исправление: отдельный gateway/bridge route table, MOD-01/03/06.
2. **Нет полноценной cookie/CSRF/session lifecycle границы.**
   Исправление: MOD-05/06/07, без bearer в JS storage.
3. **Нет общего persistent Emergency Stop для всех cue types.**
   Исправление: MOD-18 и проверенные cancel hooks outputs.

### P1: перед полноценным включением media/audio

4. **Media renderer использует mutable global `shown` в старых timers.**
   При replace старый callback может завершить новую команду.
   Исправление: immutable cue/dispatch ID, отмена timers/listeners, pause video и generation checks.
   Stale poll не восстанавливает stopped content; valid `fade_ms=0` не подменяется default через `||`.
   Fetch failure получает отдельный error state вместо видимости здорового старого output.
5. **Media `cue:null` после обычного Stop/clear не очищает текущий DOM.**
   Исправление: explicit stop state и renderer cancellation, не только DB update.
6. **Media timeout может записать completed без успешной загрузки файла.**
   Исправление: separate received/started/ended/error evidence.
7. **Moderator sound обходит `soundboard_library.play_track`.**
   Теряются общие file existence, track cooldown и volume checks.
   Исправление: один sound service для owner/moderator/binding с разной admission policy.
8. **Media final file не откатывается при DB write failure.**
   Исправление: staging protocol и recovery-aware rollback, MOD-10.
9. **Backup не включает moderator-media и Soundboard artifacts.**
   Исправление: versioned manifest и round-trip restore, MOD-20.
10. **Sound/TTS pending journals могут зависнуть после crash.**
    Исправление: outbox, lease recovery и unknown outcome, MOD-13/15/16.

### P2: до UI acceptance

11. **`mcStopSound` обращается к отсутствующему `mcStatus` и `mcT`.**
    Не копировать обработчик: новый component test проверяет status target и translator.
12. **Новый HTTP error object может превратиться в `[object Object]`.**
    Исправление: typed parser и semantic error codes.
13. **Повторный клик после timeout получает новый UUID.**
    Исправление: stable intent lifecycle и lookup.
14. **Upload-only право блокируется tab gating по `play_media`.**
    Исправление: отдельный uploads view.
15. **Legacy console молча проглатывает poll failures и показывает stale context.**
    Исправление: session/reconnect state machine.

Это findings из чтения кода, не результаты выполненного browser reproduction.
Не исправлять посторонние подсистемы и cleanup заодно с этими этапами.

## 20. Источники и граница проверки

Перманентные ссылки ниже относятся к проверенному commit, а не будущим изменениям.

- [Правила работы и ограничение тестов](AGENTS.md#L5-L63).
- [Продуктовые требования: UI, i18n, безопасность, приёмка](docs/PRODUCT_RULES.md#L49-L100).
- [Архитектура: owner и moderator access boundary](docs/ARCHITECTURE.md#L24-L84).
- [Действующая спецификация будущего moderator site](docs/specs/MODERATOR_SITE.md).
- [Текущий optional статус проекта и acceptance gate](PLAN_TODO.md#L229-L269).
- [Identity/grants/invites/session implementation](app/moderator_console_routes.py#L156-L489).
- [TTS command reservation и admission](app/moderator_console_routes.py#L512-L633).
- [Console frontend и текущий Stop handler](static/moderator-console.js#L135-L232).
- [Media storage, validation и очередь](app/moderator_media_routes.py#L126-L264).
- [Media APIs и protected output](app/moderator_media_routes.py#L341-L541).
- [Текущий media renderer](templates/obs_moderator_media.html#L1-L8).
- [Moderator sound reservation/dispatch/Stop](app/moderator_sound_routes.py#L211-L333).
- [Soundboard file/volume/cooldown service](app/soundboard_library.py#L288-L329).
- [AudioQueue implementation](app/audio_queue.py#L52-L153).
- [TTS browser queue](widgets/_shared/tts-core.js#L110-L194).
- [Backup implementation](app/backup.py#L48-L202).
- [Документация: запрет второго активного checklist](tests/test_docs.py#L16-L73) — исторический снапшот: сам тест `tests/test_docs.py` удалён 13.09.2026 (`DEC-OWNER-012`), правило «один активный чеклист» осталось соглашением в `PLAN_TODO.md`.

Прочитаны также профильные tests для identity/media/sound/TTS/security.
Они использовались как описание проверяемых контрактов, не как результаты нового прогона.

В этой работе:

- Реализация сайта не выполнялась.
- Runtime-код сайта не реализован; изменяются документация и её проверки.
- Runtime/browser/OBS tests не запускались; документационные проверки выполняются отдельно при публикации.
- Сервер/browser/OBS не запускались.
- Внешние Twitch/provider/ML вызовы не выполнялись.
- Production deployment не выполнялся.
- Дополнительные материалы проверены по конкретным контрактам.
- Этот комплект является одним согласованным вариантом, не двумя конкурирующими планами.

**Первый реальный шаг исполнителя:** MOD-00 и MOD-01, затем scaffold/граница доступа.
Не начинать с публикации старой localhost панели и не выдавать её за отдельный безопасный сайт.
