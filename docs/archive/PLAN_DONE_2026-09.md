# Архив завершённых планов (вынесено из PLAN_TODO 12.09.2026)

> Содержимое сохранено как есть; статусы и решения актуальны на момент завершения.
> Активная работа — только в [PLAN_TODO.md](../../PLAN_TODO.md).

## DONE-ACCESS — localhost без пароля ✅

- [x] `68bdd2c`: default bind `127.0.0.1`, local owner/API/WebSocket без Basic-auth.
- [x] Network bind требует полную auth-пару + `TOKEN_ENCRYPTION_KEY`.
- [x] Owner/control routers получили общий access policy; public outputs оставлены отдельными.
- [x] Data-free `/healthz`; focused gate 64 passed, 1 Docker skip.

## OAUTH-01 — авто-refresh по умолчанию и статусы токенов (`DEC-OAUTH-001`) ✅

**Зачем:** фоновый refresh существует, но выключен и невидим в панели; вручную вставленные
токены продлевать невозможно — нужен честный статус.

- [x] Включить `auto_refresh_tokens` по умолчанию.
- [x] Статусы токена значками на карточке бота: живой / истекает / истёк / не продлевается /
  неизвестно (без чисел и дат); проверка по запросу из базы или короткокэшированный
  validate (`DEC-OAUTH-002`).
- [x] Настраиваемый порог «истекает», default 7 дней (`DEC-OAUTH-003`).
- [x] Неудачный refresh — тихий повтор в следующем цикле, без выключения бота и без
  отдельного значка; красный статус только при реальном истечении (`DEC-OAUTH-004`).
- [x] Мягкое пояснение «токен не будет продлеваться автоматически» при вставке токена
  без refresh_token; без блокировки (`DEC-OAUTH-005`).
- [x] Кнопка «Обновить» на боте с refresh_token (existing endpoint).
- [x] Тесты на `token_refresh_loop` и refresh endpoints.

**Gate:** focused oauth/credential tests, `tests/test_security.py`, panel behavior tests.

## BULK-01 — массовые операции боты × каналы (`DEC-BULK-001`) ✅

**Зачем:** масштабирование без ручного перебора по одному боту.

- [x] Массовое добавление каналов выбранным ботам (bulk-bar списка ботов) и добавление
  ботов к каналу из новой вкладки «Каналы» (`DEC-BULK-004`).
- [x] Вкладка «Каналы»: список используемых каналов, у каждого — сколько ботов добавлено
  и кто реально подключён (`DEC-BULK-004`).
- [x] Idempotent: существующие связки не дублируются.
- [x] Per-item отчёт: успешно / пропущено (уже есть) / ошибка (причина); частичный сбой
  не прерывает остальные; отчёт скачивается CSV + текстом (`DEC-BULK-005`, `DEC-BULK-006`),
  в audit log — только сводка операции (`DEC-BULK-006`).
- [x] Кнопка «Добавить и проверить»: добавление сразу переходит в проверку (`DEC-BULK-005`);
  все новые строки — RU/EN/UA (`DEC-UI-003`).

**Gate:** two-account/channel isolation matrix, idempotency, partial failure tests.

## CHECK-01 — проверка ботов на тестовом канале (`DEC-BULK-002`) ✅

**Зачем:** после массовых операций убедиться, что боты реально работают.

- [x] Пассивная проверка выбранных ботов: validate токена, IRC join, подтверждение чтения
  (получено хотя бы одно сообщение за окно ~30–60 сек, иначе «не подтверждено» —
  `DEC-BULK-007`).
- [x] Контрольное сообщение — по очереди с интервалом ~2–3 сек (`DEC-BULK-003`), текст
  редактируемый при запуске, default «✅ проверка связи [ник]» (`DEC-BULK-008`);
  отклонение Twitch — честная ошибка в per-item отчёте.
- [x] Тестовый канал выбирается в момент запуска; без хардкода и без постоянного полигона.

**Gate:** fake-QA проверка без реального Twitch; реальный чат — только после owner «поехали»
по `R-ПР4`.

## LOG-01 — правдивый статус токена Chat Logger (`DEC-LOG-001`) ✅

**Зачем:** баг — любая сетевая ошибка показывается как «🔴 Токен истёк · 0 дн.» и кэшируется
на 10 минут.

- [x] `expired` — только подтверждённый 401 от validate.
- [x] Сетевая ошибка/не-200-не-401 — состояние «не удалось проверить» с `expires_in_days: null`.
- [x] Не кэшировать негативный результат validate.
- [x] Убрать завышение `round(days)` (ceiling вместо round).

**Gate:** `tests/test_p8_chat_logger.py` + новый тест состояния `unknown`.

## OPS-01 — immutable Ollama image (`DEC-OPS-002`) ✅

**Зачем:** `ollama/ollama:latest` непредсказуемо меняется.

- [x] Выбрать официальный version tag после разрешённого image pull.
- [x] Проверить только image version/startup/health; модель не скачивать, inference не выполнять.
- [x] Зафиксировать exact tag + digest в compose/config.
- [x] Добавить test, запрещающий `latest` и digest-less image.
- [x] Проверить, что без Docker панель работает, а Ollama AI показывает paused status.

**Не входит сейчас:** удобный model-pull UI и расширенное Docker-management — OPTIONAL-06.

## WIDGET-01 — Widget Bus по Twitch-каналу (`DEC-BUS-001`) ✅

**Зачем:** global bus может смешать data/media разных каналов.

- [x] Добавить canonical channel identity в payload, publishers, subscriptions и listeners одним этапом.
- [x] Event/data widget URLs требуют `channel=<login|Twitch ID>`; decorative widgets не блокируются.
- [x] Числовой value сначала ищется как exact login, затем как ID.
- [x] Missing/unknown/disabled channel показывает локализованную diagnostic card.
- [x] Старый data URL без channel fail-closed и не получает global events.
- [x] Rename login временно сопоставляется по stable Twitch ID с warning обновить OBS URL.
- [x] Одно Twitch chat/event ID публикуется один раз независимо от числа bot accounts.
- [x] Manual TTS/sound/media event требует выбранный channel; broadcast-all не добавлять.

**Gate:** two-channel WS/media/chat tests, reconnect/idempotency, missing/disabled/rename matrix.

## WIDGET-02 — moderator-media target contract (`DEC-WIDGET-001`, `DEC-BACKUP-001`) ✅

**Result:** protected output остаётся вне public inventory; per-channel plaintext local token работает
с masked UI, reveal/copy 30 seconds, manual rotation, immediate revoke и backup/restore старого URL.

- [x] Спроектировать additive migration hash-only → plaintext target без выдуманного восстановления
  старого raw token: существующим hash-only scopes потребуется явная rotation.
- [x] Reveal/copy только local owner; auto-hide через 30 seconds.
- [x] Safe preview без рабочего token.
- [x] Backup/restore сохраняет raw token и старые URL без отдельного warning (`DEC-BACKUP-002`).

**Gate:** route/token/rotation/reveal timer/backup tests; public protected URL сохраняется.

## DONATION-01 — channel-scoped integrations и secrets (`DEC-DONATION-001`, `DEC-DONATION-002`)

- [x] DonatePay, DonateX и DonationAlerts могут работать одновременно, каждый в exact channel scope.
- [x] У каждого provider: toggle, masked/write-only access token, status, reconnect и last success.
- [x] External token: Fernet при наличии key; local plaintext только с warning.
- [x] Persistent dedup: `channel + provider + event_id` через reconnect/restart.
- [x] Donation меняет только scoped goals/subathon/events/widgets.
- [x] Backup сохраняет scoped secrets без отдельного warning по `DEC-BACKUP-002`.
- [x] Local bridge: exact channel token, loopback/same-origin mutations, reveal/copy 30 seconds,
  rotation с немедленным revoke и migration legacy `webhook_token`.

**Gate:** fake providers, two-channel isolation, reconnect/status, duplicate/restart, masked API.

## API-01 — единый error contract (`DEC-API-001`, `DEC-API-002`)

- [x] Новый JSON: `{"ok":false,"error":{"code":"...","params":{...}}}`.
- [x] UI переводит stable code+params RU/EN/UA; unknown code использует safe RU fallback.
- [x] Internal exception/traceback не возвращается клиенту.
- [x] Текущая compatibility version понимает legacy `200+ok:false` и HTTP 4xx.
- [x] Граница выбрана: v13 compatibility; начиная с v14.0 только HTTP 4xx (`DEC-API-003`).
- [x] Доказать отсутствие callers `PUT /api/accounts/{id}/role`, затем удалить endpoint отдельно.
- [x] Пустой `GET .../tts-config` возвращает effective defaults + `configured:false`, без DB write.

**Gate:** API matrix + production frontend behavior tests + no-write GET fixture.

## MEDIA-01 — YouTube disclosure и truthful states (`DEC-MEDIA-001`)

- [x] Media Share сохраняет YouTube IFrame API.
- [x] При первом использовании one-time warning; acknowledgement хранится в panel settings.
- [x] Кнопка позволяет показать предупреждение снова.
- [x] Offline/embed/autoplay/reconnect failures показываются честно и не зависают.
- [x] Документировать external provider/privacy/provenance.

**Gate:** offline/error/reconnect Node behavior + settings round-trip.

---

## UI-01 — обязательный baseline (`DEC-WIDGET-002`, `DEC-UI-001`, `DEC-UI-002`)

- [x] Панель canonical dark; persisted light также приводит к dark, включая ранний boot.
- [x] Widget theme влияет только на preview/output; параметры темы виджета не меняют панель.
- [x] Формы панели, каталог виджетов и их опции получили RU/EN/UA; отсутствующий перевод
  выбранного языка использует RU, неизвестный ключ не показывается пользователю.
- [x] Legacy dynamic renderers памяти, lore/learning, сводок, модерации, логов и timeout approvals
  получили переводимые leaf labels, статусы и доступные имена без сброса черновиков.
- [x] Все 32 active widget documents получают общий UI locale runtime; 30 текстовых outputs
  используют RU/EN/UA, два декоративных output не содержат UI-текста. Copy/design/preview/instruction
  URLs передают `ui_lang`, не меняя speech `lang` у `/obs/tts`.
- [x] Loading/empty/error, event/emotion captions, demo text и существующие controls активных widgets
  локализованы; saved titles/messages остаются данными. Missing locale/key использует RU fallback.
- [x] Служебные подписи действий модератора в панели и OBS `mod-feed` переведены на RU/EN/UA.
  Producers передают allowlisted `localization.text/action` с проверенными параметрами; legacy `text/action`,
  сообщения, transcript и пользовательские значения сохранены. Неизвестная metadata оставляет исходный текст.
  Переключение языка обновляет только caption leaves, не черновики. Объявления в Twitch-чат не добавлены;
  исполнение действий, approvals и optional TTS не изменены. Python/Node producer-consumer gates покрывают
  fallback, escaping, сохранение текста и отсутствие новых отправок в чат.
- [x] Проверены обслуживаемые старые/retired compatibility pages вне active inventory: пять retired
  заглушек, `/obs-widget`, aliases Blur Guard/top-donator и protected moderator-media. Служебный UI/metadata
  используют RU/EN/UA с RU fallback; пользовательские данные и speech `lang` не переводятся.
  Все файлы и URL сохранены. Необслуживаемые backup-шаблоны проверены по callers и оставлены без изменений;
  browser/OBS-приёмка и универсальная проверка всех public URLs не объявляются завершёнными.
  Focused compatibility/preview tests: 39 passed; executable Node compatibility tests: 56 passed.
- [x] Controls панели имеют localized accessible names/labels; итоговый offline DOM-проход
  не нашёл безымянных inputs/selects/textareas/switches. Динамические контролы обновляются локально.
- [x] Modal: dialog semantics, initial focus, Tab trap, Escape, return focus; общие helpers
  используются также в onboarding, OAuth, Media Share и инструкции OBS.
- [x] Runtime status/error regions панели используют `aria-live`; сообщения об ошибках
  остаются доступны при открытой модалке.
- [x] Content max-width 1500 px; таблицы/editor имеют локальные keyboard-accessible scroll surfaces.
- [x] Переключение языка не перезагружает форму и не удаляет вложенные inputs; enabled role toggles
  правильно отображаются и сохраняются.

**Gate до «поехали»:** focused UI/role/API/widget/doc pytest: **407 passed, 4 skipped**;
Node production behavior gate: **178 passed** (часть Node-проверок также запускается pytest wrappers).
Offline jsdom-проверка полного Jinja-render: 23 classic scripts, RU/EN/UA, сохранение черновиков,
modal keyboard, role toggle render/save/keyboard; безымянных form controls и JS errors нет.
Сервер, настоящий browser/OBS и реальные provider calls не запускались.
**Gate после «поехали»:** fake browser RU/EN/UA/mobile/computed styles/keyboard; пока pending.

---

## ACCEPT-01 — финальная приёмка ✅ (12.09: все пункты закрыты; TTS — задокументированное device-ограничение + голосовой трек отложен как не-MVP)

**Выполнено 11–12.09 на машине владельца:** fake→живой browser RU/EN/UA + mobile + keyboard
(0 безымянных контролов из 974); data URL with channel + diagnostic without channel; каталог —
46 тёмных iframe; панель Режиссёра визуально (тёмная, честные бейджи источников); Twitch send
3/≤5 вживую (см. DIR-LIVE-10); reconnect/sleep через restart-recovery и source-loss циклы.

**Остаток (при живом OBS, владелец):** OBS/CEF visual composition выборочных виджетов,
TTS/audio single output, Soundboard и Blur Guard в реальном OBS; protected moderator-media в OBS.

#### ACCEPT-01 OBS/audio — состояние на 12.09 (сессия прервана по контексту, продолжить отсюда)

**Окружение:** OBS запущен (flatpak 32.1.1, obs-websocket 5.7.3, порт 4455). Пароль:
`data/live-acceptance/obs_ws_password`. Мини-клиент: `data/live-acceptance/obs.py` (сцену/источники
создаёт; особенности: rpcVersion брать из Hello (=1), salt/challenge приходят раздельными полями,
`BrowserHWAccel=false` в global.ini обязателен — иначе CEF рендерит чёрным). Панель приёмки:
`data/live-acceptance/start.sh` (порт 8100), боты подключены, промпт v2 активирован на обоих каналах.

**Проверено вживую:** сцена Accept01 (6 browser-источников: goals, now-playing, soundboard с токеном,
blur-guard-v2, tts-chat-overlay, panel-root) — **композит рендерится** (доказательство — кадры из
записи OBS: `data/live-acceptance/shots/grid-frame.png`, `record-frame.png`); честные состояния:
goals «Цели недоступны (HTTP 400)» (test_channel не бродкастер токена — Helix отказ), soundboard без
канала — diagnostic-карточка, с токеном — загружен; blur-guard-v2 — карточка настройки.

**Инструментальная особенность:** `GetSourceScreenshot` возвращает чёрный кадр для browser-источников
на этой сборке — визуальные доказательства снимать ТОЛЬКО через StartRecord → StopRecord →
`ffmpeg -ss 3 -i rec.mp4 -frames:v 1 frame.png`. Аудио-проверка — `ffmpeg -af volumedetect`.

**Найдено и исправлено:** `5b9473c` — play/stop/audio роуты soundboard падали NameError → вечный
500 (в live Play никогда не работал); после фикса play возвращает ok. 23 soundboard-теста зелёные
(+ новый роут-регресс).

**НЕ решено (следующий шаг):** события play/tts-test возвращают ok, но в записи OBS **тишина**
(max_volume −91 дБ). Гипотезы по порядку: (1) страница soundboard в CEF не переподключилась к шине
после рестартов панели — проверить кадром записи В момент play (страница должна показывать playing
индикатор; до этого ловили сырой JSON forbidden в документе страницы — после токен-URL не
перепроверено); (2) аудио browser-источника не маршрутизируется в микс OBS (проверить
GetInputList/GetInputVolumeMeter 4455-клиентом, включён ли source в аудиомиксе); (3) TTS-оверлей:
`/api/accounts/1/tts-last` → `{ok:true,has:false}` — озвучка не создалась; выяснить, какой движок
использует tts-test на этой машине и что пишет tts_engine (в CEF на Linux speechSynthesis может
не иметь голосов — тогда честный вывод: TTS-голос в OBS CEF недоступен на этом устройстве,
записать в план как device-ограничение). Для продолжения: запустить
`data/live-acceptance/start.sh`, OBS уже настроен, дальше по гипотезам 1→2→3.

#### ACCEPT-01 OBS/audio — итоги 12.09 (сессия 2: гипотезы 1→3 закрыты) ✅/🔶

**Soundboard audio в реальном OBS — РАБОТАЕТ** (доказательство: запись OBS во время play,
max_volume −21 дБ; кадр `data/live-acceptance/shots/sb-audio-frame.png` — тост «Играет трек #1»,
бейдж «Подключено»). Было ДВЕ причины тишины, обе не в шине виджетов:

1. **Пустой `moderator_console_sound_approvals`** (баг-находка, оставлена как осознанное
   поведение гейта): `POST /api/widgets/soundboard/play/{id}` возвращает ok и события уходят,
   но публичный роут выдачи аудио `/api/widgets/public/soundboard/tracks/{id}` в scoped-режиме
   требует approval-строку (account+channel+track, enabled=1) — без неё 404, и страница виджета
   честно показывает «Трек #1 недоступен» (кадр `shots/sb-unapproved-404-frame.png`). Несостыковка
   «play ok ↔ fetch 404» задокументирована; для прод-инстансов: перед play трек должен быть
   одобрен в мод-консоли (PUT `/api/moderator-console/admin/sounds/accounts/{a}/channels/{c}/tracks/{t}`).
   В приёмке трек 1 одобрен для (1, test_channel).
2. **OBS-сторона:** browser-источники, созданные через websocket `CreateInput`, не получают
   дефолт `reroute_audio: true` («Control audio via OBS») — CEF-аудио никуда не
   маршрутизируется; плюс у Desktop Audio в профиле стоял `push-to-talk: true` без привязанной
   кнопки → источник навсегда заглушен (в WS `inputMuted:false`, обманчиво). Исправлено:
   `SetInputSettings overlay:true` c `reroute_audio: true` для всех 9 browser-источников сцены;
   PTT выключен в `basic/scenes/Untitled.json` (бэкап `Untitled.json.bak-audio-fix`), OBS
   перезапущен. ⚠️ reroute_audio живёт в памяти OBS до его штатного выхода — при kill-рестарте
   применить заново (скрипт: SetInputSettings по списку GetSceneItemList). GetInputVolumeMeter и
   GetRecordSettings в этой сборке OBS отсутствуют (code 204), метр недоступен — аудио-контроль
   только через StartRecord→`ffmpeg -af volumedetect`. file:// URL в browser-источниках этой
   сборки не рендерятся — только http (панель). paplay-системный путь после фикса PTT тоже
   слышен в записи (−21 дБ) — весь аудиотракт OBS живой.

**TTS — device-ограничение подтверждено доказательством:** `speechSynthesis.getVoices()` внутри
CEF этой сборки возвращает **0 голосов** (кадр `shots/tts-voices-0.png`, probe-страница).
tts-test ok:true, событие tts уходит (tts-last `has:false` — bot_logs 'tts' пишется только при
ошибках провайдера; пусто = ошибок нет), но озвучивать некому: провайдер машины web_speech,
piper в venv не установлен, elevenlabs без ключа. **Вердикт: TTS-голос в OBS CEF на этом
устройстве недоступен** — записано как device-ограничение. Попытка оживления web_speech через
проброс `libspeechd.so.2` + `xdg-run/speech-dispatcher` в песочницу OBS (flatpak override +
LD_LIBRARY_PATH) провалилась: voices:0 — **CEF obs-browser собран без speech-dispatcher
интеграции вообще**, dlopen не выполняется; web_speech в OBS на Linux нежизнеспособен независимо
от системы. Override откатан, probe-источники из сцены удалены (и из Untitled.json на диске).

**Голосовой трек отложен владельцем 12.09 (не MVP):** «на скорости не заморачивайся, стримить
буду не с этого устройства». Установлены и проверены f5-tts 1.1.22 + omnivoice 0.2.1 (синтез
работает, звук чистый; скорость на Deck CPU: F5 warm 255 с/фразу, OmniVoice ~170 с — живой чат
не обслуживают, на целевой машине перемерить). Лицензии: омнивойс ✅ (веса подтверждены
владельцем 10.09), F5/Silero ⛔ CC-NC, piper ✅ MIT, edge-tts ⚠️ серая зона. Полный гайд,
чек-лист переноса на целевую машину и заметки по интеграции (адаптер `OmniVoiceProvider` под
актуальный API pip-пакета, `reroute_audio`-косяк websocket-источников) — в
[`voice-live/README.md`](../../voice-live/README.md); панели запуска — `~/Desktop/Омнивойс/`.
Для ACCEPT-01 TTS остаётся честное device-ограничение (см. выше); виджет сцены
`tts-chat-overlay` по дизайну НЕ играет звук (только лента текста); за «single output»
отвечает источник `/widget/tts-bot` (`tts_audio_output` пуста = играют все) — подключить при
возвращении к голосовому треку.

#### ACCEPT-01 protected moderator-media в OBS — принято 12.09 ✅

- **Баг найден и исправлен (коммит вместе с этим):** `TemplateResponse` в старом сигнатурном
  стиле падал на starlette 1.6.0 (`TypeError: unhashable type: 'dict'`) — OBS-виджет
  `/widget/moderator-media` и safe-preview отдавали **500 с сырым JSON прямо в browser-source**
  (кадр был зафиксирован). Исправлены 3 места: `moderator_media_routes.py` (виджет + preview)
  и `moderator_console_routes.py` (страница мод-консоли, сломана той же правкой starlette —
  живьём её до этого не открывали). Тесты: `tests/test_moderator_media_routes.py` +
  `test_moderator_console_access.py` — 25 passed.
- **Live-проверка в реальном OBS** (сцена Accept01, источник `moderator-media`, URL с токеном,
  `reroute_audio: true`): токен-гейтинг честный — неверный токен 403, без токена 422,
  валидный 200; кий загруженного approved-видео **играет в композите на камеру**
  (`shots/mm-cue-playing.png`), виджет сам завершает команду через `public/complete`
  (6 завершений за сессию, все через API, без ручных записей); kill-switch через
  owner-control API — кий убирается, экран чистый, ничего зависшего
  (`shots/mm-kill-switch-blank.png`); после снятия kill-switch очередь продолжает работу.
  Тестовое approved-медиа (mm_test.mp4, 4 с) и источник в сцене оставлены как часть приёмки.
- **Ops-инцидент, зафиксирован как правило:** приёмочная база дважды расходилась мирями
  (панель стартует вторым инстансом до полного выключения первого → уходящий процесс удаляет
  общий `-wal/-shm`, второй остаётся на отвязанных инодах) и один раз ловила порчу индекса
  (`moderator_media_commands`, вылечена REINDEX; причина — прямые sqlite3-записи при живой
  панели). **Правило приёмки: панель — строго один инстанс; любые записи в базу — только
  через API панели; sqlite3 CLI — только при выключенной панели.** `PRAGMA integrity_check`
  перед стартом приёмки — теперь обязательный шаг.

**ACCEPT-01 закрыт:** fake→живой browser RU/EN/UA/mobile/keyboard, каталог, панель Режиссёра,
Twitch send, OBS/CEF-композит, soundboard-audio (−21 дБ в записи), protected moderator-media.
TTS — device-ограничение (voices:0 в CEF OBS) + отложенный голосовой трек ([`voice-live/`](../../voice-live/README.md)).

**Бейлайн починен (12.09, коммит 81227ce):** полный прогон **2578 passed, 5 skipped, 0 failed**
(~18 мин). Что было: снапшот e9e2067 вернул удалённое и потерял новое. Исправлено по решениям
владельца, без выдумок: удалены 6 выведенных из эксплуатации виджетов (решения 2A) и get-pip.py
(CLEANUP-01); 16 планов/дублей снапшота переехали в docs/archive (содержимое сохранено, включая
различающиеся версии — *.root-snapshot.md); ACTIVE_DOCS = 22 (+ omnivoice×3, voice-live,
CONTRACT_INVENTORY, specs/DIRECTOR, указатель specs/MODERATOR_SITE); test_shared_user_facts
урезан до выживших хелперов (DB-API покрыт test_p8_c2_per_bot_memory); db_hygiene переведён на
политику 06.09 «legacy-таблицы сохраняются до owner-миграции»; ms_* ensure_schema подключены к
init_db (MOD-13..17 таблицы создавались, но никогда не вызывались); добавлены переводы
RU/EN/UA для director.*/modsite.* (перенесены из 21_panel_labels.js в свои чанки — реестр
дополнений только для panel.*); token_refresh-тесты явно выключают глобальный Fernet-кэш
(полный прогон включает шифрование — token сохранялся как enc::…); base.html отсортирован по
порядку чанков; эвристика аудита больше не считает тело однострочной function-декларации
top-level кодом. Чистка легаси-дублей i18n (58 пар в исключениях) — остаётся отдельным шагом.

**Итого по ACCEPT-01 OBS/audio:** soundboard/браузер-аудио в реальном OBS принято; TTS —
честное device-ограничение с зафиксированным путём разблокировки (piper). Остался
опциональный пункт «protected moderator-media в OBS» (см. выше). До закрытия остатка проект не
считается real-OBS/production accepted.

---


---

# DIRECTOR-LIVE — выполненная инженерная часть (12.09: DIR-LIVE-00…09 закрыты)

## DIRECTOR-LIVE — обязательная подготовка Режиссёра к live-релизу (`DEC-DIRECTOR-010`)

**Приоритет:** обязательная незавершённая задача, не optional и не «после основного проекта».
**Цель:** довести всю [спецификацию Режиссёра](docs/specs/DIRECTOR.md) до подтверждённого live-контракта,
а не считать наличие scheduler/replay достаточным доказательством готовности.

**Границы текущего запроса:** сейчас утверждается и детализируется план, реализация не запускается.
При выполнении инженерных этапов используются isolated SQLite, fake clock/providers/sources/sender и Node DOM/VM.
Полный suite, запуск панели, browser/OBS, реальный Twitch send, внешние AI calls, model download и ML/device
проверки не разрешены этим изменением приоритета. Последний live gate остаётся обязательным, но ждёт
отдельного явного разрешения; невозможность запустить его не превращает задачу обратно в optional.

### Уже реализовано, сохранить без регрессий

- [x] Runtime foundation: versioned plan/schema, channel-scoped scheduler, worker assignment/revocation,
  source-health и lifecycle механизмы. Полноту относительно спецификации повторно подтвердить в DIR-LIVE-00/06/07.
- [x] `DEC-DIRECTOR-009`: server-owned synthetic replay через выбранные provider/model, strict schema/safety
  validation, durable proof для exact prompt/config/effective endpoint и явное подтверждение просмотренного
  `replay_run_id`. Клиентская metadata и устаревшие/concurrent результаты не активируют промпт.
- [x] Suggest: preview/edit/approve-as-example/reject без Twitch send; channel-scoped идемпотентное решение,
  маскирование известных usernames без учёта регистра, отдельные JSON examples и контекст последних пяти
  approvals. Это не полное хранение исходных кадров/транскриптов обучающего момента.
- [x] `DEC-BOTS-004`: role-filtered настройки, отдельная Director-панель, RU/EN/UA, сохранение черновиков
  и защита от поздних ответов другого channel.
- [x] Есть регистрация metadata session artifacts, scoped manifest и подтверждаемое удаление evidence.
  Регистрация metadata сама по себе не доказывает запись файлов, quotas, retention, export или recovery.

**Исходное доказательство:** отдельный Director/provider/UI прогон — 106 passed; объединённый focused-прогон
переводов, Director, ролей, API и документации — 309 passed, 10 warnings (включая Node wrappers).
Реальные модели/источники, browser/OBS и production-приёмка этим результатом не покрыты.

### DIR-LIVE-00 — сверка всей спецификации с реализацией

**Зависимости:** нет. **Точки входа:** `app/director.py`, `app/director_plan.py`, `app/director_review.py`,
`app/director_routes.py`, `static/app/20_director.js`, `templates/partials/director.html`, профильные tests.

- [x] Сопоставить каждый контракт разделов 1–13 спецификации с production caller, UI/API и executable test.
  Учитывать supersedes в `DEC-DIRECTOR-008`/`009`, не возвращать отправку из Suggest или общую кнопку Emergency.
- [x] Прямо в этом разделе плана зафиксировать матрицу «требование → код → тест → пробел → этап DIR-LIVE».
  Различать реализовано/частично/отсутствует/не проверено на реальном устройстве; не подменять отсутствие
  runtime-пути наличием таблицы, helper или тестового fake.
- [x] Проверить также prompt diff/rollback/deletion, fake moment library, templates/chant/copypasta,
  prioritization/partial execution, manual Raid/End и session summary. Найденные пробелы добавить к этапам ниже,
  а не молча выкинуть из объёма live-релиза. Не создавать второй TODO или параллельный план.
- [x] Поддерживать матрицу актуальной: после закрытия каждого этапа обновлять статусы строк и снимать
  добавленные находки из списков DIR-LIVE-01…08. Этапы DIR-LIVE-01…08 закрыты 11.09 — матрица
  актуальна на эту дату, незакрытых находок из 01–08 не осталось.

**Готово, когда:** у каждого требования есть доказательство либо конкретный незакрытый подпункт; нет
неразобранных «вроде сделано» и утверждений, что весь Director готов по одному replay-тесту.

#### Матрица сверки (10.09.2026, обновлена 11.09)

Легенда: ✅ реализовано с offline-доказательством; 🟡 частично; ❌ отсутствует. Любой ✅/🟡 — только
offline-доказательство: реальная модель/источник/Twitch/устройство принимаются только в DIR-LIVE-10
(для них этап = 10). Точки входа: `app/director.py`, `app/director_plan.py`, `app/director_review.py`,
`app/director_routes.py`, `static/app/20_director.js`, `templates/partials/director.html`.

| § | Требование | Код (production) | Тест | Статус | Этап |
| --- | --- | --- | --- | --- | --- |
| 1 | Director не пишет сам; отправка только через lurker workers | `save_config` (director_must_be_enabled_channel_director), claim в `_dispatch_due` (`bot_role='lurker'`) | test_director_scheduler | ✅ | 10 |
| 2 | Один active Director на channel | unique index `director_one_open_session` + check в `start()` | test_director_config | ✅ | — |
| 2 | Workers — owner multi-select enabled lurkers канала, без auto-add | `_assert_workers`, `save_config` | test_director_scheduler | ✅ | — |
| 2 | Role change/disable/remove мгновенно отзывает worker, отменяет unsent | `revoke_worker` + callers в `role_routes.py`/`routes.py` | test_worker_role_revocation_cancels_unsent_message, test_director_revocation_shares_bulk_delete_transaction | ✅ | — |
| 2 | Lurker не вызывает AI, исполняет только validated plan | planner существует только в scheduler | test_director_scheduler | ✅ | — |
| 2 | Own bot вне viewer activity/language/hype/copypasta | `snapshot()` помечает own_bot, исключает из viewers и viewer_activity | test_director_runtime + test_director_sources (own_bot не в viewer_activity) | ✅ | 07 |
| 2 | Запрет URL/`!commands`/code/`@mentions`/secrets у workers | `_URL_RE`/`_COMMAND_RE`/`_CODE_RE`/`_MENTION_RE`/`_SECRET_RE` + `validate_plan` | test_hard_text_filters_reject_only_unsafe_group | ✅ | 10 |
| 3 | Dedup channel chat | `snapshot()` дедуплицирует (author,text) по всему окну выборки | test_snapshot_carries_stream_events_owner_commands_and_dedup | ✅ | 07 |
| 3 | Twitch events follow/sub/donation/reward/raid в контексте | реализовано в snapshot (07) | — | ✅ | 07 |
| 3 | Stream Vision как live source | `vision_manager.get_last_observation`; wiring `install_production_adapters` (server.py) | test_director_runtime | ✅ | 10 |
| 3 | Full speech transcript по session | реализовано transcript_append (02) | — | ✅ | 02 |
| 3 | Title/category/tags/duration | реализовано stream-контекст из Helix (07) | — | ✅ | 07 |
| 3 | Vision stale 45s / speech 15s, настраиваемые | `validate_config` + `SourceHealthHub.status` | test_director_config | ✅ | 07 |
| 3 | Потеря source → pause, запрет plans, отмена unsent | `_tick` → `transition(pause)` + cancel + audit `source_loss` | test_director_scheduler | ✅ | 06 |
| 3 | Тишина/статичный кадр healthy при свежем heartbeat | report по свежей observation-записи (heartbeat), пустые тексты healthy | test_director_sources (snap2-silent) | ✅ | 07 |
| 3 | Auto-resume возможен после 15s стабильности | `resume` требует `stable(15)` (ручной) | test_director_scheduler | ✅ | 06 |
| 3 | Raid/End по речи только verified owner voice | реализовано owner_speech_commands (07) | — | ✅ | 07 |
| 4 | Все config-параметры в legal-диапазонах | `validate_config`, `DEFAULT_CONFIG` | test_default_config_is_valid_and_safe, test_config_rejects_illegal_or_overlapping_values | ✅ | — |
| 4 | Cloud: только короткие окна + compact session summary, без raw audio/screenshots | `session_summary()` в контексте плана: state/started_at/message_states/recent_sent, без media | test_session_summary_is_compact_without_media | ✅ | 07 |
| 4 | Максимум один analysis одновременно | `_analysis_lock` + interval guard | test_director_scheduler | ✅ | — |
| 4 | High-priority wake + coalesce сигналов | реализовано priority_cooldown_sec (07) | — | ✅ | 07 |
| 4 | Нет automatic provider fallback | explicit provider only | test_custom_failure_never_tries_cloud_or_another_model | ✅ | — |
| 4 | Consecutive AI errors → pause | `_run_analysis` счётчик → `transition(pause)` + cancel | test_director_scheduler | ✅ | 06 |
| 4 | Восстановление после AI-error pause требует valid dry-run (§4) | реализовано ai_pause_requires_dry_run (06) | — | ✅ | 06 |
| 5 | Live только owner button; отказ с точными причинами | `start()` → `sources_unhealthy:<list>` | test_start_requires_all_live_sources_and_never_enables_send | ✅ | — |
| 5 | Минимум 30s rolling context | warming + warm-anchor plan record | test_director_scheduler | ✅ | 06 |
| 5 | Реакции на start/raid/end/win/loss/donation/chat waves | Manual Raid/End + приоритет (06); win/loss/donation/chat waves через событийный контекст и moments (07) | — | ✅ | 06/07 |
| 5 | Offline → запрет plans; grace 0–300 default 60; reconnect vs finalize | `handle_stream_lifecycle` + `_offline_lifecycle`: reconnect в grace → auto-resume, истечение → finalize | test_offline_grace_reconnect_and_finalization | ✅ | 06 |
| 5 | Incoming raid создаётся только из точного Twitch event | реализовано verified EventSub hook (06/07) | — | ✅ | 06 |
| 5 | Manual Raid/End: preview + confirmation; Raid не вызывает Twitch raid API | реализовано manual_plan_preview/confirm (06) | — | ✅ | 06 |
| 5 | Manual End закрывает только Director session, с финальной реакцией | реализовано finalize после TTL-хвоста (06) | — | ✅ | 06 |
| 5 | Confirmed Stop без финальной реакции; unsent отменяется | `transition(stop)` cancel + UI confirm | test_lifecycle_rejects_invalid_transitions | ✅ | — |
| 5 | При завершении transcript и audit закрываются | `closed_at` сессии при stop и offline-finalization; transcript закрывается idempotentно | test_offline_grace_reconnect_and_finalization + test_director_transcript | ✅ | 02 |
| 6 | Join delay 0–30 мин независимая, молча | `start()` uniform(0,1800) на worker | test_director_scheduler | ✅ | 06 |
| 6 | Reconnect после failure без повторной join-delay | reconcile сохраняет исходный join_at; тест покрывает reconnect-ветку | test_join_now_idempotent_and_reconnect_keeps_delay | ✅ | 06 |
| 6 | Статусы scheduled/connecting/online/error + «Зайти сейчас» для scheduled | `get_status` + `join_now` route + UI кнопка | test_director_frontend_uses_route_and_response_contracts, test_director_scheduler | ✅ | — |
| 6 | Disabled/connecting/online без второго connect | `_claim_join` guard `state='scheduled'` | test_director_scheduler | ✅ | 06 |
| 6 | Offline/end отменяет pending joins | `transition(stop/emergency)`, `stream_offline` и finalize revoke scheduled joins | test_worker_conflicts_and_ttl_expiry + test_offline_grace_reconnect_and_finalization | ✅ | 06 |
| 6 | 0 доступных workers → skipped, позже не воспроизводится | `validate_plan` → `no_available_workers`; plan persist один раз | test_backend_random_allocation_is_exact_and_deterministic_by_group | ✅ | — |
| 7 | absolute/percentage defaults | `DEFAULT_CONFIG`/`DEFAULT_PERCENTAGE_RANGES` | test_default_config_is_valid_and_safe | ✅ | — |
| 7 | Диапазоны возрастают, не пересекаются (shared boundary — решение владельца) | `validate_config` | test_config_rejects_illegal_or_overlapping_values | ✅ | — |
| 7 | Ноль = deliberate silence | schema + system prompt («A zero reaction is valid») | test_director_plan | ✅ | 10 |
| 7 | Процент ≥1; largest remainder по text-группам | `calculate_reaction_count`, `_largest_remainder` | test_percentage_and_absolute_target_counts_follow_owner_ranges, test_backend_random_allocation_is_exact_and_deterministic_by_group | ✅ | — |
| 7 | Расчёт только из immutable snapshot; поздний connect не пересчитывает | `_available_workers` | test_director_scheduler | ✅ | — |
| 7 | Timing defaults + legal + TTL ≥ max delay | `validate_config` | test_director_config | ✅ | — |
| 7 | Live требует valid ranges/workers/sources/active tested prompt | полный gate в `start()` | test_start_requires_all_live_sources_and_never_enables_send, test_prompt_versions_require_test_before_activation_and_audit_is_scoped | ✅ | — |
| 8 | Обязательные поля plan + template/example references | `DIRECTOR_PLAN_JSON_SCHEMA`, `validate_plan` | test_director_plan, test_replay_validates_unused_schema_fields | ✅ | — |
| 8 | Strict JSON; одна repair attempt только для неразбираемого | `extract_strict_plan_json`, `parse_provider_plan` | test_strict_json_rejects_prose_fences_and_trailing_content, test_only_unparseable_provider_response_can_use_one_repair_attempt | ✅ | 10 |
| 8 | Assignment modes; worker не в двух text-группах одного plan | `validate_plan` used_ids | test_backend_random_allocation_is_exact_and_deterministic_by_group, test_ai_assigned_rejects_unavailable_and_duplicate_workers_without_replacement | ✅ | — |
| 8 | Обычный text максимум 120 символов | `MAX_MESSAGE_CHARS` | test_text_longer_than_120_is_rejected | ✅ | — |
| 8 | Diverse similarity off/normal/strict | config `diverse_similarity` (default normal): normal отклоняет точные дубликаты, strict — и near-duplicates (≥0.85); chant-фразы исключены | test_diverse_similarity_modes_gate_duplicates | ✅ | 06 |
| 8 | Chant dictionary; AI-фраза только на session; owner approval делает permanent | `director_chants` + API (add/approve/delete): owner — permanent, AI — только session до approval | test_chant_dictionary_session_vs_permanent | ✅ | 06 |
| 8 | Copypasta: channel toggle default off; exact copy; repeat = новый validated plan | config `copypasta_enabled` (default off): дословный текст чата отклоняется при off; повтор всегда через полный validate план | test_copypasta_needs_channel_toggle | ✅ | 06 |
| 8 | Optional templates per-item exact/placeholders/adaptable | `director_templates` + API; `template_id` в individual_messages: exact/placeholder/adaptable режимы | test_templates_per_item_modes | ✅ | 06 |
| 8 | Twitch reject/slow/duplicate не обходится другим account/текстом | retry/обход отсутствуют; честный error state | test_live_plan_is_immutable_idempotent_and_emergency_fenced | ✅ | 06 |
| 9 | Параллельные plans; один worker не в двух plans одновременно | busy-пул глобален (все сессии/каналы), занятый worker исключается из снапшота | test_cross_plan_busy_worker_is_global | ✅ | 06 |
| 9 | Invalid части отбрасываются, valid исполняются, partial status с planned/valid/rejected | `PlanValidationResult` + audit details | test_scope_schema_and_timing_mismatches_fail_closed_without_repair | ✅ | — |
| 9 | Ошибка одного worker не останавливает остальных | per-message result | test_director_scheduler | ✅ | — |
| 9 | Retry только same account и до TTL | failed send возвращается в pending на тот же account (bound к message) до исходного TTL, после — error | test_send_failure_retries_same_account_until_ttl | ✅ | 06 |
| 9 | Plan/group/message ID исполняется максимум один раз | unique message id + atomic claim + duplicate plan check | test_live_plan_is_immutable_idempotent_and_emergency_fenced | ✅ | 06 |
| 9 | Channel TTS одна последовательная audio queue | общий `audio_queue` вне Director | — | ✅ | — |
| 10 | training/suggest/live; Twitch send только в live | `submit_response` mode check | test_state_mode_mismatch_does_not_queue_suggest_as_live, test_suggest_review_is_scoped_durable_idempotent_and_never_sends | ✅ | — |
| 11 | System/schema/safety prompt не редактируется owner field | фиксированный system prompt, owner prefs как данные | test_director_provider | ✅ | — |
| 11 | Версии prompt до ручного удаления; diff/activate/rollback | DELETE /prompts/{id}: soft-delete через `retired_at` (prompt_text=''), diff endpoint есть | test_director_training (delete) + routes | ✅ | 08 |
| 11 | Обязательный server-owned replay на exact provider/model; claim/lease; proof fingerprint | `director_review.replay_prompt` | test_server_replay_exact_provider_and_quality_gate, test_replay_claim_blocks_duplicates_and_stale_completion, test_provider_endpoint_change_invalidates_replay_proof | ✅ | 10 |
| 11 | Активация требует quality_confirmed + просмотренный replay_run_id | `activate_prompt` | test_quality_confirmation_is_bound_to_the_report_reviewed | ✅ | — |
| 11 | Active/last-working нельзя удалить без замены | `prompt_active_protected` / `prompt_last_working_protected` в delete_prompt_version (+ i18n) | test_director_training | ✅ | 08 |
| 11 | Built-in versioned fake moment library (сценарии §11), без AI на первом старте | реализовано BUILTIN_MOMENTS v1 в контексте (04/07) | — | ✅ | 07 |
| 11 | Optional AI-generated текстовые fake moments | `generate_fake_moments()` через провайдера: text-only, safe-фильтр, в контексте плана `ai_fake_moments` | endpoint + контекст-тест | ✅ | 07 |
| 11 | Example approve/edit/reject; rejected = negative example | `review_suggestion` пишет kind='negative'; `rejected_examples_negative` в контексте плана | test_plan_context_carries_moments_and_negative_examples | ✅ | 07 |
| 11 | Новая session: только built-in + owner-approved examples/config/prompt | `active_prompt` proof + последние 5 examples в контексте | test_approved_examples_enter_production_context_not_twitch | ✅ | — |
| 12 | Full transcript по sessions; 5 GB warning / 20 GB hard limit, live продолжается | реализовано (02) | — | ✅ | 02 |
| 12 | Incremental transcript append следует reserve/commit-контракту хранилища | `transcript_append`: pending-резервация до записи, `_reserve_quota` на коммите, `_revert_append` при сбое; `close_transcript` финализирует pending после крэша | test_append_disk_full_reverts_bytes_and_reservation, test_append_commit_rechecks_bucket_quota, test_crash_between_write_and_commit_is_recoverable | ✅ | — |
| 12 | Session export ZIP: TXT+JSON transcript + audit + все frames, real usernames | реализовано export_session (05) | — | ✅ | 05 |
| 12 | Frames default off; retention 90d/10GB на channel; pin/unpin hard limit 5GB | реализовано (03) | — | ✅ | 03 |
| 12 | Approved examples hard limit 10 GB; блокировка approvals | `EXAMPLE_LIMIT_BYTES` в `review_suggestion` | test_suggest_reject_and_unsafe_or_over_quota_approval | ✅ | — |
| 12 | Example переживает удаление session; маскирование Viewer-N без учёта регистра | `_anonymize` | test_username_case_variants_are_masked_in_examples, test_session_evidence_manifest_is_channel_scoped_and_requires_confirmation | ✅ | — |
| 12 | Session deletion: состав + «УДАЛИТЬ»; без delete-all; audit остаётся | `session_storage_manifest` + `delete_session_evidence` (API; UI отсутствует) | test_session_evidence_manifest_is_channel_scoped_and_requires_confirmation | ✅ | 08 |
| 12 | Raw rejected без маскирования, без отдельного warning перед backup/export | по спеке отдельный writer не требуется: raw rejected в plan payload (DB/backup), kind `rejected_evidence` в manifest-классификации | test_director_storage | ✅ | 02 |
| 12 | Synthetic training text-only | replay-кейсы текстовые | test_director_review | ✅ | — |
| 12 | Backup/restore Director DB и feature-owned assets | реализовано в app/backup.py (05) | — | ✅ | 05 |
| 13 | Audit: sources/level/accounts/text groups/delays/TTL/validation и send статусы | plan-audit несёт sources/reaction_level/delays/TTL/accounts/groups; send-audit — статусы | test_plan_audit_details_carry_level_and_sources | ✅ | 06 |
| 13 | Hidden chain-of-thought не сохраняется | CoT в audit/payload нет | — | ✅ | — |
| 13 | Emergency только во вкладке Director; hotkey optional, default нет | одна кнопка в `director.html`, отсутствует в `base.html` | test_director_frontend_uses_route_and_response_contracts | ✅ | — |
| 13 | Emergency: paused + отмена unsent + запрет plans; Resume manual после 15s health + valid dry-run | `emergency_stop_all`/`transition(emergency)` + fence + `emergency_dry_run` | test_emergency_fence_cancels_jobs_and_blocks_resume_after_restart, test_global_emergency_route_fences_every_active_channel_and_audits | ✅ | 06 |
| 13 | Панель предлагает last working prompt после Emergency | реализовано подсказкой в storage-панели (08/09) | — | ✅ | 08 |
| 13 | Обычная Pause замораживает хвост до исходного TTL | `tail_frozen_at`: expiry не тикает в паузе, resume сдвигает due/expires на длительность паузы | test_pause_freezes_tail_until_original_ttl | ✅ | 06 |
| 13 | Settings read-only в live; dirty drafts | `settings_locked` при running session + общий dirty guard | test_config_schema_is_additive_and_save_is_versioned | ✅ | — |
| 13 | После restart: session paused, unsent отменён, автоматического live нет | `recover_after_restart` при `scheduler.start()` | test_emergency_fence_cancels_jobs_and_blocks_resume_after_restart | ✅ | 06 |

Итог (ревизия DIR-LIVE-10, финал): 88 строк контрактов — 88 ✅ / 0 🟡 / 0 ❌. Владелец одобрил включение опциональных фич (10.09): diverse similarity, chant dictionary, copypasta toggle, per-item templates, AI fake moments — реализованы и покрыты тестами.
добавлены находками в списки этих этапов. Ключевые находки: production transcript/frame writers отсутствуют
(metadata-only API без callers), Twitch events/title/category/duration не доходят до snapshot, план-типы
start/raid/end и Manual Raid/End отсутствуют, templates/chant/copypasta/diverse/fake-moment library
отсутствуют, prompt diff/deletion и export/backup Director отсутствуют, resume после AI-error pause не
требует dry-run (расхождение §4/§13), cross-plan worker конфликты не отслеживаются.

### DIR-LIVE-01 — единый контракт хранения и восстановление

**Зависимости:** DIR-LIVE-00. **Точки входа:** schema/artifact helpers в `app/director.py`, `app/director_review.py`.

- [x] Уточнить additive schema для channel/session/asset ownership, размера, hash, времени записи, pin,
  references и состояния записи/удаления. Существующие session/prompt/example rows и пути сохранить.
- [x] Разделить session evidence, pinned frames, approved training assets и audit. Metadata/hash не должны
  превращаться в скрытое второе хранилище raw transcript/frames; ссылки не могут выходить в другой channel.
- [x] Реализовать безопасную запись файлов и согласование с БД: temporary file → final asset → manifest,
  обработку disk-full/cancel/crash и повторное восстановление без потерянных references или двойного учёта.
- [x] Зафиксировать единицы и точные byte thresholds всех лимитов; учёт брать из реальных файлов/записи,
  а не доверять переданному клиентом `size_bytes`. Конкурентные writers не должны превышать quota.
- [x] Ограничить файловые операции Director-owned directories; traversal/symlink, чужой session/channel,
  повреждённые manifest и orphan assets обрабатывать без удаления посторонних/legacy данных.
- [x] При подключении инкрементальных writers DIR-LIVE-02/03 согласовать их append-запись с
  reserve/commit-контрактом — сделано 11.09: `transcript_append` резервирует pending-строку артефакта
  до записи байтов, перепроверяет квоту бакета реальным размером файла на коммите (`_reserve_quota`)
  и честно откатывает байты и резервацию при OS/quota-сбое (`_revert_append`, используя соединение
  коммит-фазы — director-соединения не shared, чужой коннект дедлокится до busy_timeout);
  frames уже идут через `write_session_asset`; `close_transcript` доводит строку, оставшуюся
  pending после крэша, до committed. Тесты: disk-full revert, commit-time quota re-check,
  crash-before-commit recovery через `reconcile_session_storage`; попутно починена изоляция
  singleton `director.health` в test_director_runtime.

**Готово, когда:** migration/restart/partial-write/disk-full/concurrent-quota/two-channel тесты проходят
на временных файлах; migration не удаляет данные, recovery идемпотентен.

### DIR-LIVE-02 — полные транскрипты сессий

**Зависимости:** DIR-LIVE-01. **Контракт:** `DEC-DIRECTOR-006`, спецификация §3/12.

- [x] Подключить реальный production writer к speech source: полный transcript по session с порядком,
  timestamps/source IDs и дедупликацией после reconnect; короткое окно AI не выдавать за полный transcript.
- [x] Сделать warning при 5 GB и hard recording limit 20 GB с честным статусом в API/UI. После лимита
  остановить накопление полной истории, но продолжить свежий speech context и live при healthy source.
- [x] Закрывать запись при End/Stop/offline finalization, восстанавливать корректное состояние после restart;
  тишина не должна давать ложную ошибку transcriber heartbeat.
- [x] Не переносить чужой transcript между channels/sessions и не писать дословную речь в audit.
- [x] Подключить compact current-session summary для cloud-запросов (§4); сверка DIR-LIVE-00: полный
  transcript-writer отсутствовал, speech в snapshot ограничен последним фрагментом ≤1000 символов.
- [x] Закрывать transcript также на offline-finalization (истечение grace без reconnect) — реализовано
  (`close_transcript` в `_offline_lifecycle` + `closed_at` сессии); отображение recording/warning/limit
  статуса в панели — DIR-LIVE-08.

**Готово, когда:** fake speech/reconnect/restart и уменьшенные тестовые quotas доказывают порядок, dedup,
предупреждение, остановку записи без остановки live context и правильный состав TXT/JSON для экспорта.

### DIR-LIVE-03 — live frames, retention и закреплённые кадры

**Зависимости:** DIR-LIVE-01. **Контракт:** `DEC-DIRECTOR-006`, спецификация §12.

- [x] Подключить frame writer только после явного включения хранения; default off не создаёт скрытый архив
  кадров. Vision text/health должны работать независимо от сохранения изображений.
- [x] Реализовать retention live frames: 90 дней либо 10 GB на channel, что наступит раньше; очистка
  обрабатывает только свои завершённые assets и не гоняется с writer/export/approval/deletion.
- [x] Реализовать pin/unpin с отдельным hard limit 5 GB без auto-delete; на границе лимита возвращать
  локализованный отказ, не молча снимать pin и не вытеснять ранее закреплённое.
- [x] Проверить ссылочную целостность: approved example не зависит от удаляемого live frame; manifest,
  счётчики и реальные файлы согласованы после retention, сбоя процесса и повторного запуска.
- [x] Перевод stable-кода `pinned_storage_full` и UI pin/unpin/retention-статусы — сделано 10.09
  (c947067: ru/en/ua + коды защиты промптов);
  production frame reader использует default-раскладку `data/stream_vision_frames` (env `FRAMES_DIR`
  меняет её) — сверить на реальных кадрах в DIR-LIVE-10.

**Готово, когда:** fake clock/малые quota fixtures покрывают age/size boundaries, pin, два channel,
конкурентную запись/экспорт и сохранность approved assets без модели, камеры или OBS.

### DIR-LIVE-04 — обучающие материалы, templates и prompt lifecycle

**Зависимости:** DIR-LIVE-01/02/03 и матрица DIR-LIVE-00. **Контракт:** спецификация §8/11/12.

- [x] Довести approved example от текущего ограниченного JSON до отдельной копии всего предусмотренного
  момента: необходимые chat/speech/vision/assets, source references, размеры и hash. Удаление исходной
  session не удаляет approved material; лимит 10 GB учитывает и JSON, и принадлежащие примеру файлы.
- [x] Маскировать usernames как стабильные `Viewer-N` внутри одного example, включая регистр и вложенный
  контекст; не заявлять универсальную анонимизацию. Raw evidence не отправлять провайдеру по ссылке автоматически.
- [x] Реализовать управление библиотекой: просмотр, редактирование, approve/reject, negative examples,
  удаление с размером/references и сохранением audit metadata/hash. Unsafe/rejected текст никогда не
  превращается в sendable plan; retries/concurrent approvals не дублируют assets и не обходят quota.
- [x] Довести builtin text-only moments до всех сценариев §11: game/video/talk, start/end, raid, pause,
  win/loss, donation, chat wave, silence. Никаких fake screenshots или AI calls при первом открытии.
- [x] По результатам сверки завершить diff/rollback/deletion prompt versions, защиту active/last-working,
  referenced metadata и replay gate после изменений: diff по версиям, rollback только через обычную
  активацию с валидным replay-proof (`prompt_replay_stale` без него), soft-delete с сохранением hash/metadata
  в audit (`prompt_active_protected`, `prompt_last_working_protected`).
- [x] Templates `exact/placeholders/adaptable`, session-only chants/copypasta и approval постоянных фраз —
  реализованы 10.09 (b1f3148: валидатор + API + тесты); UI библиотек (просмотр/редактирование) — остаётся
  отдельным пунктом для DIR-LIVE-08-фазы панели.

**Готово, когда:** tests доказывают независимость assets, полную quota, безопасные negative examples,
правильные context references и prompt rollback без обхода replay/quality confirmation; Suggest/training
по-прежнему не создают Twitch dispatch.

### DIR-LIVE-05 — экспорт, backup/restore и удаление

**Зависимости:** DIR-LIVE-02/03/04. **Точки входа:** Director routes/storage UI, `app/backup.py`.

- [x] Добавить scoped session ZIP export с TXT+JSON transcript, audit и всеми сохранёнными frames,
  включая pinned, с реальными usernames по `DEC-BACKUP-002`. Не добавлять отвергнутый owner warning
  и не маскировать export так же, как training example. Missing/corrupt files не скрывать за «успехом».
- [x] Экспортировать согласованный snapshot без загрузки многогигабайтного архива целиком в память;
  проверить отмену, disk-full, безопасные archive paths и запрет чтения чужого channel.
- [x] Довести backup/restore Director DB и feature-owned assets: round-trip восстановливает содержимое,
  scopes, references и размеры, а не только manifest. Секреты защищаются по общим backup-контрактам.
- [x] Удаление session показывает фактический состав и требует `УДАЛИТЬ`; удаляет transcript, live/pinned
  session frames и raw rejected evidence, но сохраняет approved copies и audit без raw содержимого.
- [x] Отдельное удаление approved example учитывает references. Конкурентные writer/export/approval,
  повторный запрос и crash посередине не оставляют ложного «удалено», dangling links или чужих удалений.
  Общую «удалить всё» и автоматический legacy cleanup не добавлять.
- [x] Подключить export/deletion к UI панели — закрыто: `static/app/25_director_storage.js`
  содержит Export ZIP (POST export + download-ссылка), поле подтверждения «УДАЛИТЬ» с
  disabled-кнопкой до точного ввода, RU/EN/UA лейблы и audit-хинт.
- [x] Подключить Director tables/assets к backup/restore; сверка DIR-LIVE-00: `app/backup.py` Director
  не покрывал, export ZIP отсутствовал полностью — закрыто на DIR-LIVE-05.

**Готово, когда:** export/restore/deletion round-trip и failure-injection tests сравнивают реальные файлы,
hashes, manifests и audit, включая two-channel изоляцию и переживающие session deletion approvals.

### DIR-LIVE-06 — полный lifecycle, scheduler и worker safety

**Зависимости:** DIR-LIVE-00/01; закрытие этапа после подключения writers DIR-LIVE-02/03.

- [x] Построить и покрыть fake-clock tests таблицу переходов off/warming/training/suggest/live/paused/
  emergency/stopped: кто инициирует переход, нужны ли health/dry-run/replay, что происходит с unsent/jobs/joins.
- [x] Подтвердить manual Start и 30 секунд накопления контекста; обычная Pause сохраняет хвост только до
  исходного TTL, Resume требует 15 секунд health, изменение config требует нового replay.
- [x] Довести offline grace 0–300 секунд (default 60): запрет plans сразу, pending joins отменяются,
  reconnect в пределах grace и финализация после grace дают разные проверенные результаты без старых reactions.
- [x] Проверить Manual Raid/End preview+confirmation, Stop без финальной реакции, закрытие transcript/audit
  и отсутствие остановки обычных bots/Twitch stream. Raid-кнопка не вызывает Twitch raid API.
- [x] Emergency мгновенно запрещает новые/ещё не отправленные задания; Resume только вручную после
  15 секунд health и valid dry-run. После restart нет auto-live и воспроизведения unsent хвоста.
- [x] Подтвердить initial join 0–30 минут, reconnect без повторной задержки, идемпотентное «Зайти сейчас»,
  revoke при role/disable/remove и отсутствие повторной отправки после reconnect/restart/неясного send outcome.
- [x] Довести оставшиеся findings §7–9: snapshot assignment, priority, partial plans без compensation,
  worker conflicts, TTL/rate/outgoing moderation и безопасные retry только тем же account. Уже отправленное
  сообщение не выдавать за отменяемое; Twitch reject не обходить другим account или переписыванием текста.
- [x] Расхождение §4/§13 (находка DIR-LIVE-00): resume после pause из-за AI-ошибок должен требовать valid
  dry-run; сейчас resume не различает причину pause.
- [x] Plan-типы start/raid/end и Manual Raid/End (находка DIR-LIVE-00): End с финальной реакцией,
  preview+confirmation, incoming raid только из Twitch event, высокий приоритет без отмены valid хвоста.
- [x] Templates/chant/copypasta/diverse similarity (§8, находка DIR-LIVE-00) — реализовано
  и закрыто в DIR-LIVE-08 (матрица 88/88, тесты `tests/test_director_plan.py`); строка
  оставалась открытой как ссылка — приведена в соответствие 11.09.
- [x] Cross-plan worker конфликты (находка DIR-LIVE-00): free-флаг сейчас берётся из bot_manager busy,
  конфликты параллельных plans не отслеживаются; reconnect без повторной join-delay и отмена scheduled
  joins при Stop не покрыты тестами.
- [x] Дополнить audit-записи полями §13 (level/percentage, accounts, text groups, delays/TTL) вместо
  хранения их только в plan payload; закрытие transcript/audit при финализации.

**Готово, когда:** deterministic race/restart/fence/TTL/worker tests проходят с fake sender и clock;
никакая смена состояния, config, prompt или provider не допускает старый plan к новой live-session.

### DIR-LIVE-07 — источники и provider compatibility без сети

**Зависимости:** DIR-LIVE-00/06; storage integration DIR-LIVE-02/03.

- [x] Проследить production wiring chat/events/title/category/tags/duration, Vision и speech до snapshot.
  Own bots не входят в viewer activity/language/hype/copypasta; данные не пересекают channel scope.
- [x] Доказать свежесть source timestamps/heartbeat, а не время перечитывания старой DB row. Vision stale
  default 45 секунд, speech heartbeat 15 секунд; свежая тишина/статичный кадр healthy, реально пропавший
  source ставит pause и отменяет unsent. Recovery после 15 секунд без replay пропущенных moments.
- [x] Verified Twitch incoming raid и verified owner speech команды отличать от viewer/guest/unknown текста;
  stream lifecycle должен доходить из реального integration caller, не только ручного тестового helper.
- [x] Проверить max-one-analysis/coalescing/high-priority cooldown, consecutive AI failures и recovery
  с valid dry-run; автоматического provider/model fallback нет.
- [x] Offline contract fixtures закрыты: schema/repair/partial — `tests/test_director_plan.py`;
  transport-матрица timeout/auth/429/malformed через production `_run_analysis` + consecutive
  failures → pause ai_errors — `tests/test_director_provider_matrix.py` (5 тестов, 11.09).
  Полный матричный прогон на реальных транспортах остаётся приёмкой DIR-LIVE-10.
- [x] Сохранить proof для exact prompt/config/endpoint и quality confirmation; cloud request содержит только
  допустимые короткие окна/описания/summary, без raw screenshots/audio, секретов и скрытых сетевых переходов.
- [x] Production wiring отсутствующих источников (находка DIR-LIVE-00): Twitch events follow/sub/donation/
  reward/raid, title/category/tags/duration, дедуп chat, verified owner speech команды Raid/End.
- [x] High-priority wake/coalescing на `priority_cooldown_sec` (параметр валидируется, но не используется) и
  built-in versioned fake moment library по сценариям §11; rejected examples как negative context.

**Готово, когда:** fake integration/HTTP transport tests проходят через production adapter и source wiring,
а список неподтверждённых на реальных моделях комбинаций явно передан в DIR-LIVE-10.

### DIR-LIVE-08 — законченный owner UI/API

**Зависимости:** DIR-LIVE-02…07; UI можно выполнять по мере готовности backend-контрактов.

- [x] Добавить недостающие session list/details, storage usage/limits/pin, export/delete, example library,
  prompt diff/rollback/dependencies и source/lifecycle diagnostics в отдельную Director-панель.
- [x] Все mutations используют owner policy, exact channel/session, stable error envelope и retry guards;
  settings read-only в live, dirty drafts сохраняются, late responses не меняют чужой channel.
- [x] RU/EN/UA, dark UI, loading/empty/error/partial/quota statuses, keyboard/dialog lifecycle и `aria-live`.
  Показывать разные причины pause/offline/storage-limit/AI-error, а не одно неинформативное «не работает».
- [x] Emergency остаётся только во вкладке Director и owner-defined hotkey; не дублировать общую шапку.
  Suggest/training не получают кнопку Twitch send; новые controls не должны обещать несуществующий backend.
- [x] Prompt diff/rollback/deletion (находка DIR-LIVE-00): diff/delete/rollback-через-activate и manifest UI
  сделаны; `retired_at` выставляется удалением (защита active/last-working); owner hotkey Emergency, подсказка last-working
  prompt после Emergency и dependencies-граф остаются до DIR-LIVE-09.

**Готово, когда:** Node DOM/VM tests подтверждают реальные UI/API contracts, localizations, draft/role/channel
изоляцию и ошибки; визуальная browser/OBS-проверка честно остаётся в DIR-LIVE-10.

### DIR-LIVE-09 — итоговый offline engineering gate

**Зависимости:** DIR-LIVE-00…08.

- [x] Выполнить только профильные Director/roles/provider/backup/API Python tests, Node UI tests, docs/link
  checks и `git diff --check`; расширить existing suites, не заменять проверки константами из реализации.
- [x] Пройти матрицу two-channel, quotas, permissions, malformed/untrusted input, disk-full, timeout/cancel,
  concurrency, restart/recovery, export/restore и deletion с isolated DB/files, fake clocks и transports.
- [x] Зафиксировать конкретные commands/results/известные ограничения в этом плане; обновить фактические
  контракты в spec/architecture. Каждый завершённый инженерный шаг публиковать отдельным commit после его tests.
- [x] Проверить, что в DIR-LIVE-00 не осталось незакрытых требований реализации; всё, что требует реальных
  sources/models/device/browser, имеет отдельный проверяемый сценарий DIR-LIVE-10, а не отметку «готово».

**Итог gate (10.09.2026):** статус **«offline engineering complete, live acceptance pending»**.

- Команды/результаты: `pytest` (Director 15 файлов + `test_bot_roles` + `test_backup` + `test_api_error_contract`
  + `test_docs` + `test_plan_file_zones`) — **173 passed**; `node --test tests/director_review_ui.test.js
  tests/director_storage_ui.test.js` — **21 test, 0 fail**; `git diff --check` — чисто.
- Матрица: two-channel изоляция (`test_director_gate.py`, export/lifecycle тесты), quotas/disk-full
  (`test_director_storage/frames/export`), malformed/untrusted input (`test_director_plan/review`),
  timeout/cancel (`test_director_gate`), concurrency (`test_director_review_races`), restart/recovery
  (`test_director_gate`, runtime/transcript), export/restore round-trip (`test_director_export`).
- Известные ограничения (❌ матрицы): templates exact/placeholders/adaptable, chant dictionary,
  copypasta toggle, diverse similarity, AI-generated fake moments — опциональные фичи §8/§11, не
  включены без явного решения владельца; полный матричный прогон provider-транспортов — DIR-LIVE-10.
- Контракты спеки обновлены: §4 (priority wake), §5 (offline grace/resume-причины), §12 (export/backup/
  удаление/панель), §13 (audit-поля); `docs/ARCHITECTURE.md` §5 (backup `data/director/**`).
- [x] Построчная ревизия оставшихся 16 🟡-строк матрицы — выполнена в DIR-LIVE-10 (сверка с кодом +
  закрытие кодом/тестами: closed_at, reconnect/finalize, cross-plan, retry до TTL, dedup окна, own_bot,
  тишина healthy, compact session summary, prompt deletion/защита, negative examples, rejected_evidence
  по спеке, полные audit details, pause-freeze хвоста, i18n pinned_storage_full). Итог: 83 ✅ / 0 🟡 / 5 ❌.
  счётчиков по итогам DIR-LIVE-10.

**Готово, когда:** инженерные подпункты закрыты доказательствами и нет known blocker; разрешён статус
«offline engineering complete, live acceptance pending», но не «полностью готов к production».

### Уже реализовано, сохранить без регрессий

- [x] Runtime foundation: versioned plan/schema, channel-scoped scheduler, worker assignment/revocation,
  source-health и lifecycle механизмы. Полноту относительно спецификации повторно подтвердить в DIR-LIVE-00/06/07.
- [x] `DEC-DIRECTOR-009`: server-owned synthetic replay через выбранные provider/model, strict schema/safety
  validation, durable proof для exact prompt/config/effective endpoint и явное подтверждение просмотренного
  `replay_run_id`. Клиентская metadata и устаревшие/concurrent результаты не активируют промпт.
- [x] Suggest: preview/edit/approve-as-example/reject без Twitch send; channel-scoped идемпотентное решение,
  маскирование известных usernames без учёта регистра, отдельные JSON examples и контекст последних пяти
  approvals. Это не полное хранение исходных кадров/транскриптов обучающего момента.
- [x] `DEC-BOTS-004`: role-filtered настройки, отдельная Director-панель, RU/EN/UA, сохранение черновиков
  и защита от поздних ответов другого channel.
- [x] Есть регистрация metadata session artifacts, scoped manifest и подтверждаемое удаление evidence.
  Регистрация metadata сама по себе не доказывает запись файлов, quotas, retention, export или recovery.

**Исходное доказательство:** отдельный Director/provider/UI прогон — 106 passed; объединённый focused-прогон
переводов, Director, ролей, API и документации — 309 passed, 10 warnings (включая Node wrappers).
Реальные модели/источники, browser/OBS и production-приёмка этим результатом не покрыты.
