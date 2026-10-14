# OWNER DECISIONS — 08.09.2026

> Каноническая запись ответов владельца после завершения C-010 behavior-test migration.
> Этот файл фиксирует продуктовые решения; исполняемый порядок находится в [`../PLAN_TODO.md`](../PLAN_TODO.md).
> Если здесь нет точного ответа, реализация не должна угадывать — вопрос остаётся в разделе
> «Неотвеченные вопросы» и в соответствующем пункте `PLAN_TODO.md`.

## 1. Режим работы и приёмка

- Работа продолжается **только локально**. GitHub, push и PR не являются частью текущего процесса.
- Изменения делаются маленькими rollback-friendly локальными коммитами.
- Полный `pytest` не запускать; использовать только focused suites.
- Основной QA-профиль: `QA_PROFILE_NAME=local`, `HOPLITE_PREVIEW_PROFILE=full-qa`.
- Production credentials/DB не использовать.
- Реальный browser/OBS/CEF acceptance запускать только после явного сообщения владельца **«поехали»**.
- Когда acceptance будет разрешён, нужен полный критический прогон:
  - fake browser RU/EN/UA и mobile;
  - новый URL с `channel`, ошибка без `channel`, compatibility URL;
  - reconnect;
  - TTS/audio single-output;
  - Soundboard;
  - Blur Guard;
  - protected moderator-media;
  - автоматический sweep остальных виджетов и выборочная визуальная проверка.

## 2. Закрытый C-010

C-010 behavior-test migration закрыта. Production-функции пяти последних поверхностей исполняются
в offline Node VM; source-marker assertions оставлены только для markup/template/i18n контрактов:

1. dirty-state guard: `beforeunload`, cancel/accept navigation, save/clear, idempotent binding;
2. Analytics: full init, success/empty/error без вечной «Загрузка...»;
3. Stream Tools: moderator/non-moderator/failure visibility;
4. custom providers в global/per-bot AI selects;
5. OBS instruction modal: open/replace/close, URL/size/defaults, params и escaping.

## 3. Moderator media

- `/widget/moderator-media` — **защищённый служебный output**, не обычный публичный виджет каталога.
- У него нет reusable public preview URL с рабочим token; панель может показывать безопасную demo-preview.
- Token отдельный для каждого Twitch-канала.
- URL содержит точный `channel` и token.
- Token хранится plaintext в локальной базе, но по умолчанию замаскирован в UI.
- После предупреждения token можно показать на 30 секунд или скопировать.
- Ротация только вручную.
- Старый token становится недействительным сразу после ротации.
- Новый URL в OBS владелец меняет вручную; панель заранее предупреждает об этом.

## 4. Widget Bus и OBS URL

### 4.1 Scope

- Widget Bus разделяется **по Twitch-каналам**, не по bot account.
- Несколько ботов одного канала публикуют данные в одну channel-scoped ленту.
- Одно Twitch chat message публикуется в общие виджеты канала один раз по стабильному message ID,
  даже если его получили несколько bot accounts.
- Ручной запуск TTS, звука, GIF/media или другого bus-события требует явно выбранного канала.
  Если канал не выбран, действие блокируется понятной локализованной ошибкой.
- Broadcast во все каналы не нужен.

### 4.2 Параметр channel

- Для event/data-driven OBS widgets параметр `channel` обязателен.
- Полностью декоративные widgets могут работать без него.
- Один параметр принимает оба формата:
  - `?channel=my_login`;
  - `?channel=123456789`.
- Чисто цифровое значение сначала ищется как точный настроенный login, затем как Twitch ID.
- Панель по умолчанию генерирует понятные URL с login.
- При переименовании Twitch-канала старый login временно сопоставляется с сохранённым Twitch ID;
  панель показывает предупреждение обновить OBS URL.
- Старые data-widget URL без `channel` **не получают события**.
- Отсутствующий, неизвестный, удалённый или отключённый канал показывает постоянную локализованную
  диагностическую карточку с причиной и примером правильного URL, а не тихо прозрачный экран.
- Удаление/отключение канала сразу прекращает data feed; повторное включение того же канала
  восстанавливает подключение.
- Панель показывает готовый channel-scoped URL у каждой карточки и кнопку копирования.
- Обычным localhost event/data widgets дополнительный secret token не нужен.
- Widget Bus остаётся localhost-only; защищённые media/control surfaces используют отдельные tokens.

## 5. Donation integrations и tokens

### 5.1 Источники донатов

- Основной способ получения донатов — исходящие локальные подключения панели к API/WebSocket сервисов.
- Официально поддерживаются одновременно:
  - DonatePay;
  - DonateX;
  - DonationAlerts.
- У каждого сервиса отдельный toggle, access token, status и reconnect-loop.
- Настройки интеграций отдельны для каждого Twitch-канала.
- Полученный event сразу получает стабильный channel ID и уходит только в Widget Bus этого канала.
- Статусы в панели: подключено / переподключение / понятная ошибка / время последнего успешного события.
- Reconnect выполняется автоматически.
- Дедупликация доната: `channel + provider + stable event_id`, сохраняется через reconnect/restart.
- События разных providers считаются разными.

### 5.2 External access tokens

- Настоящие access tokens DonatePay/DonateX/DonationAlerts шифруются существующим
  `TOKEN_ENCRYPTION_KEY`, если ключ задан.
- В local-only режиме без ключа plaintext допустим с постоянным предупреждением.
- В UI внешние access tokens masked/write-only.

### 5.3 Local webhook bridge

- Local donation webhook сохраняется как optional bridge для Streamer.bot, ручных test events
  и других программ на том же компьютере.
- Endpoint принимает mutation только от localhost.
- У каждого канала отдельный plaintext webhook token.
- Token по умолчанию замаскирован; раскрывается на 30 секунд после предупреждения либо копируется.
- После ручной ротации старый token сразу получает отказ.
- Публичный tunnel для этого endpoint сейчас не поддерживается.

### 5.4 Backup

- Обычный backup сохраняет plaintext donation webhook tokens и moderator-media tokens.
- До export/import панель явно предупреждает, что backup содержит секреты и его нельзя публиковать.
- Import доступен только локально.
- После восстановления старые OBS/local bridge URL должны снова работать без автоматической ротации.

## 6. Ollama

- Ollama можно выбрать **основным** AI provider, не только fallback.
- При недоступной Ollama автоматического перехода в cloud нет.
- Сообщения продолжают сохраняться в chat log, но не ставятся в очередь на будущий AI-ответ.
- После восстановления Ollama обрабатываются только новые сообщения.
- Панель показывает общий статус: «Ollama недоступна — сообщения сохраняются, ответы приостановлены».
- Техническое сообщение об ошибке в Twitch-чат не отправляется.
- Без Docker панель, chat log, moderation и widgets продолжают работать; приостанавливается только AI,
  использующий Ollama.

### 6.1 Immutable image

- `ollama/ollama:latest` нужно заменить на проверенный exact tag + digest.
- Разрешено скачать официальный image и проверить startup/version/health.
- На этом gate запрещены model pull и inference/prompt.
- Обновление image в будущем только вручную: новый tag/digest → pull → startup/health → отдельный commit.

### 6.2 Управление Docker

- Ollama-контейнером управляет панель.
- Backend разрешает только allowlist действий над Ollama: status/start/stop/restart и разрешённый model pull.
- Произвольные Docker container names/arguments и общий Docker manager не нужны.
- При shutdown панель останавливает Ollama только если сама запустила контейнер в этой process-session.
- Если контейнер уже работал до запуска панели либо остался после crash, панель использует его как внешний
  и автоматически не останавливает.

### 6.3 Модели

- Отсутствующая модель не скачивается автоматически.
- Ручная кнопка до pull показывает exact model/tag, ожидаемый размер, свободное место и предупреждение.
- Показываются progress/result; повторное нажатие не создаёт второй pull.
- Pull можно отменить.
- После отмены частичные layers остаются как resumable cache; панель не удаляет их автоматически.
- При shutdown активный pull отменяется после короткого grace period, затем панель закрывается.

## 7. API contracts

### 7.1 Старый role endpoint

- `PUT /api/accounts/{id}/role` нужно проверить на всех repository/local consumers.
- Если реальных callers нет, endpoint удалить.
- Панель продолжает использовать полный `role-config`.
- Удаление — отдельный маленький commit с focused tests.

### 7.2 Ошибки

- API переходит к настоящим HTTP 4xx.
- Переходный период длится до следующего version bump приложения.
- В переходной версии frontend понимает и старое `200 + ok:false`, и новый 4xx contract.
- После version bump legacy mutation endpoints переходят на 4xx согласно migration note.
- Новый error JSON содержит стабильный технический code и безопасные params, например:
  `{"ok": false, "error": {"code": "unknown_role", "params": {"role": "x"}}}`.
- UI переводит code/params на RU/EN/UA.
- Внутренние exceptions/tracebacks пользователю не возвращаются.

### 7.3 TTS config

- `GET /api/accounts/{id}/tts-config` до первого сохранения возвращает полный набор effective defaults
  и `configured:false`.
- GET не создаёт запись в БД.

## 8. Media Share и Song Request

- Media Share сохраняется.
- YouTube IFrame API всегда разрешён; отдельный runtime toggle не нужен.
- При первом использовании панель один раз показывает понятное предупреждение о внешнем YouTube API,
  интернете и ограничениях autoplay/embed.
- Согласие хранится в настройках панели и может быть сброшено кнопкой «Показать предупреждение снова».
- Нужны честные offline/error/reconnect states.
- Song Request сейчас остаётся модерируемой очередью **без autoplay**.
- Автоматическое воспроизведение — будущая отдельная задача; сначала отдельное исследование YouTube OBS,
  local player и Spotify, provider заранее не выбран.

## 9. Данные, cleanup и исторические файлы

### 9.1 Legacy data

- Legacy tables/rows не удаляются автоматически.
- Возможная очистка только отдельной owner-invoked командой после backup, dry-run report и явного подтверждения.
- Пока размер/производительность не являются проблемой, данные остаются.
- `scripts/migrate_legacy_data.py` перенести в recovery-only архив, добавить предупреждение
  «не запускать без backup» и idempotence/collision fixture.

### 9.2 Удалить после доказательства отсутствия consumers

- `templates/index_v10_backup.html`;
- `templates/obs_tts_widget.html`, сохранив рабочий `/obs/tts` через canonical renderer;
- `shot_mascot.png`;
- `get-pip.py`;
- `start_v12.sh`;
- `scripts/p5_split_app_js.py`;
- `scripts/p5_split_routes.py`.

Каждый cleanup выполняется маленьким отдельным commit: grep consumers → focused gate → coverage regenerate.

### 9.3 Архивировать вместе

- `docs/panel_review_data.json`;
- `scripts/panel_review_render.py`;
- связанный historical report, если он найден.

Связка переносится одним archive commit и больше не считается current source of truth.

## 10. ML и панель

- Stream Vision, diarization и voice clone остаются experimental opt-in через `--ml`.
- Они выключены по умолчанию и не блокируют основной bot core.
- Production readiness этих функций требует отдельного real device/ML acceptance.
- Управляющая панель всегда canonical dark.
- Темы widgets видны только в preview и не перекрашивают панель.
- Обычные формы/текст/карточки ограничиваются примерно 1400–1600 px; таблицы, графики и visual editor
  могут использовать больше ширины или собственный overflow.
- Не выполнять большой frontend split заранее: сначала измерить startup/interaction timings после
  разрешённого browser acceptance; при реальной проблеме начинать с lazy-init.
- Будущий отдельный moderator overlay site отложен до завершения текущего аудита.

## 11. i18n и accessibility

- Первый запуск панели — русский язык.
- Выбор RU/EN/UA сохраняется локально в браузере.
- Если перевода нет, fallback — русский; технический i18n key пользователю не показывается.
- RU/EN/UA обязательны для всех пользовательских строк:
  - панель;
  - widgets;
  - modals/instructions;
  - loading/empty/error states;
  - OBS diagnostic errors.
- API field names, stable error codes и developer logs не переводятся.
- Нужна полная базовая accessibility:
  - accessible names всем controls;
  - labels у inputs;
  - `role=dialog`, заголовок и описание modal;
  - focus при открытии;
  - Tab focus trap;
  - Escape closes;
  - возврат focus на trigger;
  - `aria-live` для runtime statuses/errors.

## 12. Общие правила нескольких ботов

- Все bot accounts наблюдают стрим/чат по своим разрешённым функциям.
- Обычный AI-бот без прямого обращения не обязан отвечать; сообщение используется как контекст.
- Прямое обращение определяется:
  - exact nickname или `@nickname` с нормализацией регистра;
  - Twitch Reply на сообщение конкретного бота.
- Обращение разрешает рассмотреть ответ, но не гарантирует его: действуют enabled-state, роль,
  attention, cooldown, hard limits и решение модели.
- Если человек явно назвал несколько ботов, отвечать могут все названные.
- Они генерируют ответы параллельно.
- Боты без TTS отправляют только текст.
- Все TTS-реплики одного канала всегда воспроизводятся последовательно через общую audio queue.
- Боты могут отвечать друг другу только при exact mention/Reply.
- Bot-to-bot limit настраивается отдельно у каждого бота; default 4, значение 0 полностью запрещает
  bot-to-bot ответы.
- Один человеческий message открывает новую chain; защита должна исключать бесконечный цикл.
- Moderator-бот может самостоятельно модерировать и разговаривать без обращения.
- Его обычная активность контролируется `chat_activity`, attention/rate limit и cooldown.
- Voice companion может отвечать без имени по включённым `on_speech`, `on_questions`, `on_silence`.

## 13. Новая роль «Режиссёр»

### 13.1 Назначение

- Добавить роль **«Режиссёр»**, internal key `director`.
- Режиссёр — AI-бот, который анализирует поток стрима и управляет выбранными non-AI lurker-ботами.
- Сам Режиссёр в Twitch-чат не пишет.
- Одновременно на одном канале активен только один Режиссёр.
- Автоматического резервного переключения на другой Director нет; при потере active Director live pause.
- Режиссёр управляет только lurker accounts, явно выбранными владельцем в channel-scoped multi-select.
- Новый lurker не добавляется автоматически.
- Смена роли/удаление/disable сразу исключает bot ID и отменяет его неотправленные задания.

### 13.2 Lurker как non-AI worker

- `lurker` не вызывает AI и не принимает самостоятельных содержательных решений.
- Он подключён к Twitch, участвует в chat log/events/bindings без дублей и может исполнять только
  проверенное задание Режиссёра.
- Существующий `mention_reply` для такого контракта должен быть пересмотрен/удалён.
- Lurker-ботам не нужны отдельные характеры: они создают естественную массовую реакцию.
- Запрещено передавать через них URL, приглашения, `!команды`, code-like строки и `@mentions`.
- Перед отправкой всё равно действует обычная outgoing moderation.

### 13.3 Источники и availability

Режиссёр использует одновременно:

- channel chat без дублей;
- Twitch events (follow/sub/donation/reward/raid и др.);
- Stream Vision;
- полную расшифровку речи стримера;
- title/category/tags и длительность стрима.

- Live требует одновременно исправных Stream Vision и speech transcription.
- Если любой обязательный источник потерян, новые планы запрещаются и неотправленный хвост отменяется.
- После восстановления обоих источников live возвращается автоматически только после 15 секунд
  стабильной работы.
- События, накопившиеся во время pause, задним числом не исполняются.
- Реальные live frames по умолчанию не сохраняются.
- При включённом хранении задаются срок в днях и максимум места на канал; старые незакреплённые кадры
  удаляются первыми, отдельный кадр можно закрепить.
- Полные transcripts сохраняются по stream sessions до ручного удаления; панель показывает объём,
  предупреждает о лимите диска и умеет удалить одну session или всё.

### 13.4 AI config и контекст

- У Режиссёра отдельные provider/model/temperature/max-tokens settings.
- Можно использовать Ollama, custom или cloud provider.
- Выбор cloud provider считается разрешением отправлять ему текст чата, transcript и текстовые
  Vision descriptions без дополнительного consent modal.
- Исходный audio и screenshots не отправляются в обычный Director request.
- Каждый request получает короткое текущее rolling-window, текущие источники и compact summary более
  ранней части текущей session, но не весь transcript.
- В новую stream session автоматически переходят только built-in и owner-approved training examples,
  config и active prompt version.
- AI monetary/token budget не ограничивается отдельным hard cap.

### 13.5 Наблюдение и запуск

- Режиссёр работает с continuous rolling context, но дорогой AI-анализ запускается по фиксированному
  channel-configured interval 3–120 секунд.
- High-priority Vision/chat/speech/Twitch event может разбудить анализ раньше.
- Wake cooldown настраивается в диапазоне 3–30 секунд; несколько сигналов объединяются.
- Одновременно выполняется максимум один Director analysis request; новый не стартует до завершения старого.
- Запуск live только ручной кнопкой владельца.
- Если AI, Vision или speech не готовы, кнопка не включает live и показывает точные причины.
- После старта нужно накопить минимум 30 секунд rolling context до первого реального плана.
- Twitch offline завершает session после настраиваемого grace 0–300 секунд; новые планы блокируются
  сразу, после возврата обязательны health gate и warm context rules.
- При окончательном offline хвост отменяется, transcript/audit финализируются.

### 13.6 Не только хайп-моменты

Режиссёр должен уметь осознанно реагировать также на:

- начало стрима;
- вход/постепенное появление lurker-ботов;
- incoming/outgoing raid;
- обычные спокойные моменты;
- начало/смену игры или видео;
- победу/поражение/смешной момент;
- массовую реакцию реального чата;
- follow/sub/donation/reward;
- объявленное завершение и фактический конец стрима.

- Lurker-боты не должны подключаться все мгновенно после старта.
- Нужен случайный постепенный join schedule; точный диапазон между упомянутыми владельцем 15 и 30
  минутами остаётся вопросом.
- У каждого lurker в панели есть кнопка **«Зайти сейчас»**, отменяющая его оставшуюся задержку.

### 13.7 Modes, prompt и обучение

- Основной рабочий режим — автоматический `live`.
- Дополнительно доступны:
  - `training`: никакой отправки в Twitch;
  - `suggest`: optional preview/approval plan;
  - `live`: автоматическое исполнение valid частей плана.
- Перед live строгая форма требует:
  - active Director и selected lurkers;
  - assignment mode;
  - three reaction ranges;
  - analysis interval и wake cooldown;
  - min/max delay;
  - max TTL;
  - готовые AI/Vision/speech sources;
  - active tested prompt version.
- System safety/schema часть prompt неизменяема кодом.
- Основной Director prompt редактируется версиями, сравнивается и откатывается.
- Новую версию можно replay-проверить на выбранных built-in/synthetic/real moments без Twitch send.
- Встроенная versioned training library готова сразу, не требует AI на первом запуске и редактируема.
- Fake training moments полностью текстовые: игра, видео, разговорный стрим, пауза, raid, начало/конец,
  победа/поражение, донат, массовый чат и решение «промолчать».
- Дополнительная AI-кнопка генерирует новые fake moments; это не fine-tuning модели.
- Training examples можно approve, edit или reject.
- Approved/edited examples входят в live context; rejected сохраняются как отрицательные «так не делать».
- У synthetic examples нет image; owner отказался от fake screenshots.

### 13.8 Язык, мемы и templates

- Channel language mode: `Auto / RU / EN / Mixed`.
- Auto использует речь и чат; UI показывает выбранный язык.
- RU/EN/Mixed могут использовать естественные короткие memes, slang и разрешённый translit.
- У канала редактируемый meme/chant dictionary.
- Exact duplicate chant допускается только в явном `chant` action и только для фразы из owner dictionary.
- Встроенный chant allowlist не используется.
- Обычный `diverse` plan создаёт разные короткие реакции.
- Optional channel-scoped template library включается отдельным toggle.
- Templates группируются по событиям, могут иметь безопасные placeholders и не удаляются при выключении.

### 13.9 Масштаб и structured plan

- Три строго возрастающих непересекающихся reaction ranges: `small`, `medium`, `large`.
- Каждый range имеет owner-defined min/max 0–100%; 0 означает осознанное молчание и сохраняется в audit.
- AI выбирает уровень и точный процент внутри его диапазона.
- Для большой группы не нужны сотни уникальных JSON rows.
- Compact plan содержит группы `text + percentage`; backend выбирает конкретных allowed/free lurkers
  либо AI назначает `bot_id` — assignment mode обязательно выбирается до live.
- В одном событии может участвовать любое число выбранных lurker-ботов вплоть до всех, согласно
  процентам и доступности; маленького fixed cap нет.
- Delay bounds вводятся владельцем; абсолютный валидный диапазон 0–300 секунд.
- AI задаёт фактическое окно внутри этих bounds.
- Max TTL вводится владельцем; абсолютный диапазон 1–600 секунд, TTL ≥ max delay.
- AI назначает TTL каждому plan; после него неотправленный хвост отменяется.
- Несколько актуальных plans могут идти параллельно, если их TTL/assignment не конфликтуют.
- Один lurker не участвует одновременно в двух plans: random assignment выбирает другого или уменьшает
  группу; invalid AI-assigned bot пропускается без замены.
- Ошибка отдельного lurker записывается, остальные продолжают; временный retry разрешён только тому же
  account до TTL.
- Невалидные части AI plan отбрасываются, valid части исполняются без компенсации/пересчёта процентов.
- Один immutable plan ID/group ID/message ID исполняется максимум один раз, включая reconnect/restart.
- Смысловые повторы разных moments отсеивает сам AI; backend не вводит fingerprint-дедуп разных plans.

### 13.10 Журнал и emergency stop

- Audit log сохраняет: время, channel, доступные источники, описание момента, level/percentage,
  выбранные accounts, texts/groups, delays, TTL, statuses, validation rejections, template/example IDs.
- Hidden chain-of-thought не сохраняется; только короткое объяснение результата.
- Emergency Stop постоянно доступен: переводит channel в paused, отменяет неотправленный хвост и
  запрещает новые plans. Уже отправленные Twitch messages не удаляются.
- Возврат после emergency stop требует отдельного подтверждения владельца.

## 14. Решения, которые не превращать в скрытые требования

- Автоматические lurker accounts не получают программную `[BOT]`-метку, profile marker или `!bots`
  disclosure: владелец объясняет это зрителям устно.
- Это решение не отменяет Twitch rules, AutoMod, channel modes или platform rate limits; runtime не должен
  пытаться обходить ограничения платформы.
- Lurker messages не должны использовать URL/commands/@mentions даже по указанию AI.

## 15. Неотвеченные вопросы — перенести в план, не блокировать этот документ

1. **Join schedule lurkers:** владелец упомянул random delay «до 15 минут» и «до 30 минут».
   Нужно выбрать точную модель: один диапазон, две волны или разные пределы по bot group.
2. Что происходит при кнопке «Зайти сейчас», если Twitch connect уже выполняется или account disabled.
3. Должен ли постепенный join повторяться после краткого reconnect панели или только при новой stream session.
4. Точные owner-entered initial значения:
   - small/medium/large ranges;
   - analysis interval;
   - wake cooldown;
   - min/max send delay;
   - max TTL;
   - offline grace.
5. Точная live-frame retention policy при включении: days, bytes, warning threshold, pinned-frame quota.
6. Transcript disk warning/maximum и формат export/delete confirmation.
7. Какие события считать incoming/outgoing raid и какие default fake training examples использовать для них.
8. Как Режиссёр понимает «стрим заканчивается» до Twitch offline: только по речи/Vision либо нужна
   owner hotkey/event.
9. Должны ли неотправленные start/raid/end plans иметь отдельные приоритеты относительно обычных plans.
10. Exact JSON schema Director plan и immutable system prompt — спроектировать в реализации,
    затем зафиксировать schema tests и replay fixtures.
11. Default assignment mode намеренно отсутствует; нужно выбрать `AI bot_id` или `backend random`
    до первого live на каждом канале.
12. Prompt/tool-call compatibility matrix для Ollama/custom/cloud models.
13. Должен ли optional `suggest` подтверждать весь plan одной кнопкой или поддерживать per-row editing;
    это не блокирует основной automatic live.
14. Конкретный следующий application version, на котором заканчивается compatibility `200 + ok:false`.
15. Выбор exact Ollama tag+digest после разрешённого image pull/startup/health gate.
16. Browser/OBS acceptance остаётся заблокирован до явного **«поехали»**.
