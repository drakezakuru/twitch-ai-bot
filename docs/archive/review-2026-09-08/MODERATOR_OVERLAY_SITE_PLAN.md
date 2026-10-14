# Moderator Overlay Site — отдельный future-план

> Статус: концепт на будущее, не входит в текущий Track 6.
> Решение владельца 05.09.2026: moderator должен видеть стрим в web-интерфейсе,
> размещать GIF/картинки/короткие видео поверх кадра и запускать звуки.

## 1. Цель

Сделать защищённый сайт `mod.<домен>` с визуальным редактором поверх превью стрима.
Moderator видит кадр трансляции, перетаскивает media cue в нужное место, меняет
размер и запускает его в отдельный OBS Browser Source. В этой же console остаются
TTS и approved Soundboard.

Это не публикация полной owner-панели и не полный удалённый пульт OBS. Moderator
получает только явно выданные действия конкретного Twitch account/channel.

## 2. Пользовательский сценарий

1. Owner создаёт moderator-доступ и отдельно разрешает `play_media`, `play_sound`,
   `send_tts`, `upload_media` и/или `manage_media`.
2. Moderator открывает `mod.<домен>`, входит через Twitch и выбирает разрешённый канал.
3. В центре видит превью стрима формата 16:9 с safe areas; справа — approved GIF,
   картинки, короткие видео и звуки, поиск и избранное.
4. Moderator перетаскивает media на превью, двигает, масштабирует и при необходимости
   задаёт длительность. Координаты сохраняются нормализованно (`0..1`), поэтому
   одинаково работают для 720p, 1080p и других размеров OBS canvas.
5. Кнопка `Показать` создаёт scoped cue. OBS Browser Source получает его по WSS,
   показывает в указанном месте и подтверждает `queued/playing/finished/rejected`.
6. `Stop`, `Clear queue` и owner kill switch сразу скрывают media и останавливают звук.

На телефоне вместо точного drag-and-drop допускается tap-to-place и готовые зоны:
левый/правый верх, центр, левый/правый низ и fullscreen.

## 2A. Полный каталог экранов и функций

Ниже перечислен целевой продукт целиком. Метка **MVP** означает первый полезный релиз,
**Later** — отдельную фазу после живой проверки MVP. Ни одна Later-функция не должна
задерживать безопасный вход, scoped media cue и аварийный Stop.

### 2A.1. Вход, приглашение и профиль moderator-а

| Функция | Поведение | Релиз |
|---|---|---|
| Twitch Login | OAuth/PKCE; backend получает стабильный Twitch user ID, login и avatar, но не публикует access token в браузер | MVP |
| Invite | Owner создаёт одноразовое/срочное приглашение для конкретного Twitch user ID и channel | MVP |
| Pending access | Пользователь без grant видит запрос доступа, а не существование чужих каналов/медиа | MVP |
| Channel switch | Показывает только каналы из grants; последний выбор сохраняется в личных preferences | MVP |
| Session list | Moderator видит свои активные устройства и может завершить их | Later |
| Profile | Avatar/login, язык RU/EN/UA, compact/comfortable layout, reduced motion и personal defaults | MVP |
| Logout | Завершает server session и очищает browser state без удаления grants/favorites | MVP |

### 2A.2. Главный экран

- Верхняя строка: выбранный channel, live/offline, состояние bot backend, OBS stage,
  Soundboard и preview bridge, latency/reconnect и кнопка смены языка.
- Большие вкладки: `Эфир`, `Медиа`, `Звуки`, `TTS`, `Очередь`, `История`.
  Вкладка скрывается, если соответствующее permission не выдано.
- Personal quick deck: до 12 закреплённых GIF/звуков/голосов; порядок moderator
  меняет drag-and-drop, но это не меняет owner library.
- Owner announcement: короткое сообщение/правила текущего стрима; moderator не редактирует.
- Красный статус при потере связи. Нажатие во время reconnect не создаёт скрытых
  повторных событий; команда либо получает server ID, либо явно считается неотправленной.

### 2A.3. Экран «Эфир»: preview и размещение

| Элемент | Функции |
|---|---|
| Preview canvas | Twitch Embed, blank/test canvas либо разрешённый OBS screenshot preview; aspect ratio и canvas resolution берутся из channel preset |
| Масштаб просмотра | `Вписать`, 50%, 75%, 100%; масштаб UI не меняет итоговые координаты OBS |
| Safe areas | Включаемые guides для камеры, чата, титров и game HUD; owner создаёт/блокирует зоны |
| Grid/snapping | Сетка, привязка к краям/центру/guides и временное отключение привязки |
| Media layer | Drag, resize с сохранением пропорций, rotate в разрешённом диапазоне и presets размера |
| Position presets | Верх/центр/низ × лево/центр/право, fullscreen, last used и owner presets |
| Layer order | Только безопасные слоты `background`, `normal`, `foreground`; произвольный z-index не принимается |
| Duration | Owner min/max; moderator выбирает из presets либо разрешённый диапазон |
| Transition | Approved `fade`, `pop`, `slide`, `none`; скорость ограничена owner policy |
| Fit | `contain`, `cover`, `original`; renderer не растягивает медиа скрыто |
| Local preview | Проигрывает анимацию только внутри editor, без создания live cue и без звука в OBS |
| Show | Отправляет cue после server-side проверки scope/permissions/layout/media status |
| Replace/Queue | `В очередь` доступно с `play_media`; `Заменить текущее` требует отдельного `replace_media` |
| Stop | Останавливает свой текущий cue; `Stop all` требует `clear_queue` |

Editor всегда показывает рамку выбранного элемента и итоговые `x/y/width` в процентах.
Для touch нужны крупные handles, pinch-to-resize и кнопка «Вернуть последнее положение».
Keyboard: стрелки двигают на один шаг, Shift+стрелка — крупный шаг, Delete только
убирает черновой слой и никогда не удаляет media из библиотеки.

### 2A.4. Экран «Медиа»

- Карточки GIF/WebP/PNG/WebM/MP4: thumbnail, имя, tags, duration, размер, владелец,
  approved/draft/quarantine/disabled и наличие audio track.
- Search по имени/tags, фильтры типа/избранного/recent, сортировка owner order/name/recent.
- `Предпросмотр` не отправляет cue. Видео в library preview muted по умолчанию;
  live audio у media запрещено, пока owner отдельно не включил `allow_media_audio`.
- `На сцену` открывает media в editor с последней личной позицией; quick-play использует
  locked owner preset и не обходится без server validation.
- Favorite/unfavorite и personal last position не изменяют shared metadata.
- Moderator с `upload_media` загружает файл в draft/quarantine, задаёт безопасное имя/tags
  и видит причину rejection. Publish/delete/rename shared media требуют `manage_media`.
- Owner может задать expiry, канал, максимальную длительность показа, cooldown,
  допустимые transitions/slots и запрет fullscreen для каждого media item.
- Disabled/deleted media исчезает из новых действий; уже выданный ID не должен запускаться.

### 2A.5. Экран «Звуки»

- Approved Soundboard library: имя, категория, duration, owner volume cap, cooldown,
  favorite, recent и индикатор `playing/queued`.
- `Preview в наушниках` играет файл только в браузере moderator-а и требует отдельного
  явного нажатия; `В эфир` отправляет track ID существующему OBS Soundboard.
- Quick buttons не принимают URL или filename — только канонический track ID.
- Политика owner: `replace`, `queue` или ограниченное смешивание; MVP использует `replace`.
- Personal favorite/order и горячие клавиши работают только при открытой console;
  глобальные OS hotkeys в этот future-проект не входят.
- `Stop own`, `Stop all` и `Clear sound queue` проверяют разные permissions.
- Upload/rename/delete используют общую media permission model, но отдельные audio limits.

### 2A.6. Экран «TTS»

- Поле текста с live-счётчиком длины, blacklist feedback до отправки и понятной
  причиной server rejection. Пустой/пробельный текст запрещён.
- Approved voice catalog: язык/provider label, safety/license label, preview,
  personal favorites и personal default; raw provider ID moderator не вводит.
- Per-message voice, разрешённые emotion/speed/volume в owner limits и reset к default.
- `Предпрослушать` играет локальный preview; `Отправить` создаёт scoped TTS queue item.
- Moderator видит свою очередь и может отменить только собственный pending item.
  `cancel_any_tts` выдаётся отдельно.
- Exact `!tts` и web-console используют один allowlist/policy/audit, но web session
  не выдаёт дополнительных chat permissions.
- Обычный Twitch chat автоматически не озвучивается. Reward voice остаётся отдельной policy.

### 2A.7. Экран «Очередь»

- Единая timeline TTS/media/sound: thumbnail/type, actor, channel, created time,
  position, estimated duration и status `pending/playing/finished/canceled/rejected/expired`.
- По умолчанию moderator видит свои элементы и безопасный общий now-playing без текста
  чужой приватной TTS-заготовки. `view_full_queue` открывает полную очередь канала.
- Разрешённые действия: cancel own pending, move own within owner limits, retry rejected
  только после исправления причины; priority/reorder all/clear требуют отдельных grants.
- Finished/failed события не запускаются повторно после refresh/reconnect.
- Owner может заморозить приём новых действий, дождаться текущего или остановить всё.

### 2A.8. Экран «История» и audit

- Moderator видит собственные отправки и результат; owner — полный channel audit.
- Фильтры actor/type/result/time/media; раскрытие показывает layout/policy decision,
  но не OAuth token, OBS password, provider secret или сырой security header.
- Экспорт CSV/JSON доступен только owner/auditor permission и ограничен channel scope.
- Audit append-only для UI: moderator не удаляет и не редактирует события.
- Retention настраивает owner; удаление media не удаляет минимальную audit-ссылку/название.

### 2A.9. Owner-раздел доступа и политик

- Найти Twitch user по точному ID/login, подтвердить channel и выдать grant с expiry.
- Permission presets: `TTS only`, `Media operator`, `Sound operator`, `Full moderator deck`;
  owner видит раскрытый список прав перед сохранением.
- Отдельные grants: `send_tts`, `play_media`, `replace_media`, `play_sound`,
  `upload_media`, `manage_media`, `clear_queue`, `view_full_queue`, `manage_layout_presets`.
- Пер-пользовательские cooldown/лимиты не могут быть слабее абсолютного channel maximum.
- Мгновенный revoke завершает sessions, запрещает новые команды и отменяет pending items
  согласно owner policy; уже прозвучавший sound/TTS физически не откатывается.
- Channel kill switch, media-only mute, sound mute, TTS mute и maintenance mode.
- Управление canvas preset, safe areas, allowed transitions, durations, slots,
  upload policy, moderation queue и OBS overlay token rotation.

### 2A.10. Уведомления и ошибки

- Toast и inline status для accepted/queued/playing/rejected; зелёный `accepted` нельзя
  показывать как `played`, пока OBS runtime не подтвердил начало.
- Понятные причины: no permission, wrong channel, offline OBS, cooldown, queue full,
  media disabled, unsafe file, stale revision, duplicate command и expired session.
- Browser notifications опциональны только для queue failures/access revoke; без spam.
- Reconnect показывает время последнего успешного heartbeat и не скрывает offline состояние.

### 2A.11. Permission matrix

| Действие | Базовый moderator | Дополнительное право | Owner |
|---|---:|---|---:|
| Смотреть разрешённый channel preview | ✅ | — | ✅ |
| Добавлять approved GIF в очередь | ❌ | `play_media` | ✅ |
| Заменять текущую GIF | ❌ | `replace_media` | ✅ |
| Играть approved sound | ❌ | `play_sound` | ✅ |
| Отправлять TTS | ❌ | `send_tts` | ✅ |
| Загружать draft media | ❌ | `upload_media` | ✅ |
| Publish/rename/delete media | ❌ | `manage_media` | ✅ |
| Остановить собственное действие | При наличии play/send права | — | ✅ |
| Stop/Clear всей очереди | ❌ | `clear_queue` | ✅ |
| Менять safe areas/layout presets | ❌ | `manage_layout_presets` | ✅ |
| Видеть secrets/OBS password/owner settings | ❌ | Не выдаётся | Только локальный owner runtime |

### 2A.12. Responsive и accessibility

- Desktop: preview + library side-by-side; tablet: collapsible library; phone: preview,
  preset zones и bottom sheet вместо мелких drag handles.
- Все действия доступны клавиатурой, focus видим, dialog удерживает focus корректно.
- ARIA labels/status live regions, достаточный contrast и режим reduced motion.
- RU/EN/UA переводятся одновременно; media user names/tags не машинно переводятся.
- Ошибка сети не очищает безопасный local draft текста/позиции, но draft не содержит tokens.

## 3. Как показывать стрим moderator-у

### Режим A — Twitch Embed (MVP для удалённого moderator)

- В фон редактора встраивается официальный Twitch player с `parent=mod.<домен>`.
- Player всегда muted, чтобы не создавать эхо; минимальный размер embed — 400×300.
- Это простой и дешёвый вариант, но Twitch stream имеет задержку. Позиция слоя точная
  относительно canvas, а момент происходящего moderator видит с обычной задержкой эфира.

Документация: https://dev.twitch.tv/docs/embed/video-and-clips/

### Режим B — OBS scene preview (точнее, отдельная фаза)

- Локальный bridge рядом с OBS периодически получает уменьшенный screenshot активной
  scene/composite и отправляет только preview-кадры на сайт, например 1–2 FPS.
- Пароль OBS WebSocket остаётся локально и никогда не передаётся browser/moderator-у.
- Preview выключается owner-ом, имеет ограничение bandwidth/FPS и не сохраняется сервером.
- Перед отправкой нужна privacy-проверка: приватные сцены и источники можно исключить.

Режим B точнее Twitch Embed и подходит до выхода в эфир, но требует локального bridge.
Первый релиз не должен обещать realtime-видео или заменять OBS Multiview.

## 4. OBS-архитектура

- Один новый Browser Source `/widget/moderator-stage`, прозрачный и размером с canvas.
- Отдельный scoped overlay token только на чтение cue stream; он не даёт доступ к API панели.
- Media renderer принимает только канонические server-side media IDs и typed layout:
  `x`, `y`, `width`, `rotation`, `duration_ms`, `fit`, `transition`, `z_slot`.
- Queue policy: `queue`, `replace_current` или owner-only `priority`; по умолчанию `queue`.
- Звуки исполняет существующий `/widget/soundboard`, чтобы не получить двойное аудио.
- Состояние cue восстанавливается безопасно после reconnect; истёкший cue повторно не играет.

## 5. Библиотека media

- Owner-approved GIF/WebP/PNG и короткие WebM/MP4; звуки MP3/WAV/OGG/WebM.
- Upload — только файл, без произвольного HTML/JS и без прямого external URL.
- Проверка magic bytes, реального decode, размеров кадра, duration, codec, file size,
  animated frame count и decompression-bomb limits до публикации в библиотеку.
- Preview не запускает звук в эфир. Moderator может иметь favorites и recent items.
- Upload moderator-а по отдельному праву попадает в quarantine/draft; автоматическая
  публикация разрешается только если owner явно включил trusted-upload для этого user.
- Файлы хранятся в scoped `data/widgets/moderator-stage/<account>/<channel>/media/`,
  metadata/permissions/audit — в SQLite. Secrets в media-root не хранятся.

## 6. Авторизация и безопасность сайта

- HTTPS обязателен; moderator входит через Twitch OAuth, сервер проверяет стабильный user ID.
- Session — короткоживущая secure/httpOnly/sameSite cookie; state/PKCE, CSRF-защита,
  rate limits и принудительный logout/revoke со стороны owner.
- Каждое действие повторно проверяет user, account, normalized channel, permission и media ID.
- Audit хранит actor, scope, действие, media, layout, результат и timestamp без OAuth tokens.
- Отдельные лимиты на пользователя/канал, защита duplicate click/idempotency и понятный cooldown.
- Полная owner-панель не публикуется под теми же правами. OBS WebSocket не открывается в интернет.

## 7. Свой сайт или готовый chatbot/overlay-сервис

Перед реализацией провести короткий технический spike и сравнить:

| Критерий | Своя console | StreamElements/готовый сервис | Streamer.bot/Speaker.bot |
|---|---|---|---|
| Twitch login и свои per-user permissions | Полный контроль | Зависит от dashboard roles | Обычно локальные permissions/actions |
| Превью своего стрима + drag placement | Реализуем точно под задачу | Overlay editor есть, moderator live-placement нужно доказать | Потребуется свой web UI/action layer |
| Единые TTS/GIF/Soundboard permissions | Один scoped backend | Несколько раздельных механизмов | Возможно через actions, но нужен wiring |
| Домен и branding | Полностью свои | Сервисные URL/аккаунт | Свой gateway всё равно нужен |
| Audit и cross-channel isolation | По нашим правилам | Зависит от сервиса | Нужно проектировать отдельно |
| Зависимость от внешней платформы | Нет | Есть | Зависимость от локального приложения |

Spike должен собрать работающий proof-of-concept, а не только сравнение описаний:

1. Moderator входит отдельным Twitch account.
2. Видит live preview и размещает одну GIF в произвольной точке.
3. Запускает approved звук, owner видит audit и может мгновенно остановить.
4. Moderator соседнего канала не видит библиотеку и не исполняет cue.
5. Проверяются стоимость, ограничения API, branding, экспорт данных и отказ сервиса.

Если готовое решение закрывает все пять пунктов без выдачи лишних прав, можно использовать
его и не писать дубликат. Если нет — предпочтителен собственный тонкий moderator site +
локальный OBS bridge, а не перенос всей текущей панели в интернет.

Референсы для spike:

- Twitch Embed: https://dev.twitch.tv/docs/embed/video-and-clips/
- StreamElements overlays: https://support.streamelements.com/hc/en-us/articles/10474479981074-Overlays-The-Complete-Guide-Gallery-OBS-Setup-Widgets-Alerts-Data
- StreamElements custom widgets: https://docs.streamelements.com/overlays/custom-widget
- OBS WebSocket: https://github.com/obsproject/obs-websocket

## 8. Этапы реализации

### F0. Decision spike

- Проверить готовые сервисы по пяти acceptance-сценариям выше.
- Зафиксировать build/integrate/hybrid, стоимость и ограничения; без результата F0 код не начинать.

### F1. Scoped identity и permissions

- Twitch OAuth/PKCE, sessions, owner grants, exact account/channel и audit.
- Fake OAuth/provider для тестов; production tokens и реальные user data в QA запрещены.

### F2. Media library и OBS stage

- Isolated storage, validation/quarantine, CRUD owner-а, approved library.
- Прозрачный Browser Source, queue/replace, transitions, reconnect и kill switch.

### F3. Visual placement editor

- Twitch Embed background, normalized drag/resize, presets, safe areas и responsive touch UX.
- Отдельно проверить 16:9, 21:9 и вертикальный canvas; preview не выдавать за OBS pixel-perfect.

### F4. Soundboard и TTS

- Подключить существующие очереди без второго audio output; favorites/defaults и cooldown.
- Единый status feedback и audit для TTS/media/sound.

### F5. Optional OBS preview bridge

- Password остаётся локально, preview scenes allowlist, low-FPS ephemeral transport и privacy gate.
- Потеря bridge не ломает overlay runtime и переключает editor на Twitch Embed/blank canvas.

### F6. Домен и эксплуатация

- HTTPS, reverse proxy/tunnel, WSS, backups/retention, healthcheck и revoke procedure.
- Owner runbook: DNS, OBS URL, moderator invite, emergency stop и полное отключение remote access.

## 9. Критерий готовности

- RU/EN/UA UI, тёмная тема, desktop/mobile и keyboard/touch accessibility.
- Fake-data tests для OAuth, scope, IDOR, CSRF, XSS, unsafe files, duplicate/reconnect и rate limit.
- Moderator не получает owner API, secrets, OBS password или данные соседнего channel/account.
- GIF появляется в выбранной позиции; sound играет ровно один раз; Stop/Clear работают немедленно.
- Есть живой panel preview и отдельная проверка реального OBS canvas владельцем.
- Публичные URL совместимы с OBS, но token можно отозвать без смены Twitch credentials.

## 10. Не входит в первый релиз

- Полный удалённый контроль сценами/источниками OBS.
- Передача moderator-у исходного OBS WebSocket password.
- Произвольные сайты, iframe, HTML, JavaScript или URL в media cue.
- Realtime WebRTC-копия OBS Program feed без отдельного privacy/infra решения.
- Автоматическая публикация любого moderator-upload без owner policy.
