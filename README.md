# Twitch AI Bot Panel

Локальная веб-панель для нескольких Twitch-ботов, AI-реакций, модерации,
анализа стрима, TTS и OBS Browser Source-виджетов. Основной запуск и управление
владельца выполняются через панель на `http://localhost:8000`.

## Навигация по README

- [Что уже умеет проект](#что-уже-умеет-проект)
- [OBS-виджеты](#obs-виджеты)
- [TTS, голос и интерфейс модератора](#tts-голос-и-интерфейс-модератора)
- [Быстрый старт](#быстрый-старт)
- [Конфигурация](#конфигурация-env)
- [Архитектура](#архитектура)
- [API](#api-reference)
- [Эксплуатация и тесты](#эксплуатация-v13)

## Статус и документация

README описывает рабочие функции и отдельно помечает незавершённые. Это важно:
наличие backend-модуля ещё не означает, что у функции готов UI и пройдена живая
проверка в OBS.

- [Что делать дальше](PLAN_TODO.md) — единственный активный план.
- [Решения владельца](docs/DECISIONS.md) — почему выбран именно такой контракт.
- [Архитектура](docs/ARCHITECTURE.md) — scope, данные, безопасность, widgets и runtime.
- [Правила продукта](docs/PRODUCT_RULES.md) — обязательные safety/UI/i18n-инварианты.
- [История](docs/HISTORY.md) и [архив](docs/archive/) — завершённые планы и audit evidence.
- [Режиссёр](docs/specs/DIRECTOR.md) — обязательная подготовка к live-релизу; подробные этапы
  `DIR-LIVE-00`…`DIR-LIVE-10` находятся в [активном плане](PLAN_TODO.md), полная приёмка ещё не пройдена.
- [Модераторский сайт](moderator-site/README.md) — отдельная папка со спецификацией, порядком реализации,
  тестами и deployment инструкциями; сайт пока не реализован.

## Что уже умеет проект

### Панель и Twitch-аккаунты

- Несколько Twitch-аккаунтов: добавление, редактирование, включение, запуск и остановка.
- Device Code Login или ручной OAuth; опциональный автоматический refresh токенов.
- Несколько каналов на бота, индивидуальные channel overrides и HTTP/SOCKS5 proxy.
- Прямая отправка сообщений, live-чат и логи через WebSocket.
- Роли ботов: `chatter`, `moderator`, `voice_companion`, `lurker`; роль задаёт
  допустимое поведение, а не только подпись в UI.
- Командная палитра `Ctrl+K`, импорт/экспорт настроек, RU/EN/UA интерфейс.

### AI, персона и контекст

- OpenRouter, Ollama, Gemini, OpenAI и Anthropic; per-bot override модели.
- Настраиваемая персона: юмор, сарказм, серьёзность, эмоциональность и другие
  параметры, семь пресетов, AI-генерация и адаптация к настроению чата.
- Источники контекста можно сочетать: Twitch-чат, кадры/звук стрима, профиль
  стримера, текущая игра и заголовок трансляции.
- Профиль и фото стримера, долговременные факты о зрителях, affinity, threads,
  заметки, база знаний и краткие сводки контекста.
- Сравнение 1–4 моделей, feedback по AI-ответам и локальный fallback на Ollama.

### Чат и автоматизация

- Attention filter, noise filtering и пакетная обработка нескольких сообщений
  одним AI-запросом; observation/silent режимы без отправки ответа в чат.
- Триггеры по ключевым словам с channel scope, тестом причины срабатывания,
  cooldown и включением/выключением.
- Антиспам: cooldown пользователя, caps, ссылки, повторы и blacklist.
- EventSub: follow, subscribe, cheer, raid и Channel Points; raid-контекст и overrides.
- DonatePay, DonateX и DonationAlerts могут одновременно передавать события донатов;
  сбор синхронизируется с Donation Challenge, а подписки/донаты продлевают Subathon.
- Engagement KPI, настроение, sentiment, trending, word cloud и статистика реакций.
- Replay-сессии и auto-highlight/post-stream отчёты для отладки поведения.
- Clip Detector отмечает всплеск активности и сохраняет момент. Настоящий Twitch clip
  создаётся только отдельной кнопкой и только при наличии нужных API-прав.

### Stream Vision и звук

- Захват Twitch HLS либо custom ffmpeg input от OBS, экрана, камеры, RTMP или файла.
- Vision-анализ кадров и, после установки optional ML stack, Whisper-транскрипция
  аудио с настраиваемыми интервалами.
- Опциональная diarization: лёгкая эвристика или WhisperX/pyannote при отдельно
  установленных ML-зависимостях и настроенном Hugging Face token.
- Beep pipeline для найденных фрагментов и сохранение ограниченной истории кадров.

### Модерация

- Настройки и правила per account, журнал событий, статистика, CSV-экспорт и test mode.
- Действия warn/timeout/ban/delete требуют существующего confirmation flow;
  внешнее действие нельзя выдавать за физически обратимое.
- `mod-feed` показывает решения модерации в OBS; это read-only display, не пульт.

### Данные, безопасность и надёжность

- SQLite с идемпотентными миграциями; изолированные папки, промпты и логи per bot.
- HTTP Basic для панели и Fernet-шифрование OAuth-токенов при заданных env-переменных.
- Ротация логов, retention, авто-бэкап, restore/download, `PRAGMA optimize` и `VACUUM`.
- Reconnect с exponential backoff, watchdog, crash-изоляция ботов и очередь TTS с лимитом.
- `python run.py --doctor` проверяет окружение без вывода секретов.

## OBS-виджеты

Панель содержит каталог, настройки, публичный read-only URL и живой iframe-preview.
URL вида `/widget/...` и `/obs/...` предназначены для OBS Browser Source; секретные
настройки и управляющие формы в публичную страницу не попадают.

| Группа | Виджеты | Назначение |
|---|---|---|
| Чат | `chat-highlight`, `selected-chat`, `chat-roulette` | Выделение сообщения, allowlist-лента и розыгрыш зрителей |
| TTS | `tts-raw`, `tts-bot`, `chat-reader`, `tts-chat-overlay` | Три варианта audio output и отдельный display-only текстовый overlay |
| Цели и таймеры | `goals`, `sub-goal`, `countdown`, `subathon-timer`, `donation-challenge` | Прогресс целей, countdown и продление времени событиями |
| Музыка и медиа | `now-playing`, `song-request`, `soundboard`, `media-share` | Текущий трек, очередь заказов, звуковые плитки и модерируемое медиа |
| События | `follower-ticker`, `latest-event-card`, `recent-events`, `top-donator` | Follow/event ленты, последняя карточка и лидер донатов |
| Стрим | `schedule`, `uptime`, `lower-third`, `clip-moments`, `mod-feed` | Расписание, сессия, подпись, моменты для клипа и решения модерации |
| Реакции | `hype-meter`, `emoji-chat`, `emoji-leaderboard` | Активность чата и статистика эмодзи |
| Оформление | `animated-bg`, `mascot`, `anime-runner` | Фон, реактивный маскот и canvas-анимация |
| Защита | `blur-guard-v2` | Маска/картинка либо управление настоящим OBS filter через OBS WebSocket v5 |

`/obs/blur-guard` сохранён как alias на `/obs/blur-guard-v2`. Browser Source не
может размывать пиксели другого OBS source: настоящий blur делается фильтром OBS
на конкретном source/group. Полный инвентарь и рекомендуемые размеры canvas
задаются в `app/widget_inventory.py`.

### Widget bindings

Semantic actions реализованы для Goals, Sub Goal, Countdown, Now Playing,
Lower Third и Soundboard. Источники — panel hotkey, точная chat-команда и
ограниченный EventSub; backend повторно валидирует action, роль и typed value.

> **Safety gate:** текущая таблица bindings ещё legacy-global. До миграции на exact
> `account_id + channel` chat/EventSub bindings и moderator hotkeys нельзя считать
> cross-channel safe. Старые global rows будут удалены, а не автоматически назначены
> случайному аккаунту. Актуальный статус — Track 6.5 в `PLAN_TODO.md`.

## TTS, голос и интерфейс модератора

### Что работает сейчас

- Web Speech, Piper и ElevenLabs; per-bot voice, emotion, volume и speed.
- Локальные Piper-модели и voice clones через XTTS/F5-TTS, preview голоса и
  отдельный voice override для Channel Points.
- WebSocket-очередь в OBS. В OBS нужно включить звук только у **одного** из
  `tts-raw`, `tts-bot` или `chat-reader`, иначе одна реплика прозвучит несколько раз.
- `tts-chat-overlay` показывает текст и сам звук не воспроизводит.

### Какой интерфейс нужен модераторам

Для модераторов удобнее не Twitch-чат и не публичный OBS overlay, а **отдельная
защищённая web-консоль** в стиле компактного overlay: она открывается на телефоне,
планшете или втором мониторе, содержит поле реплики, approved voices, избранное,
личный default, очередь и статус отправки. OBS-страница остаётся только audio/display
output. Так модератор не запоминает команды, а токены и глобальные настройки не
попадают в Browser Source.

Точная `!tts <текст>` и настраиваемый alias останутся удобным запасным способом.
Оба интерфейса должны использовать один backend и один owner-managed allowlist по
стабильному Twitch user ID, с exact account/channel scope, rate limit, blacklist,
ограничением длины и audit каждой реплики. Badge moderator/VIP/sub сам по себе
доступ к TTS не выдаёт.

### Запланировано, но ещё не готово

- Защищённая moderator TTS console, выдача/отзыв доступа владельцем, approved
  voice catalog, favorites и личный default.
- В этой же console — moderator media deck: выбор approved GIF/коротких видео и
  звуков, favorites, отдельные права на показ, проигрывание и upload. GIF/медиа
  выводит отдельный OBS source, а звуки используют существующий Soundboard.
- Для media deck запрещены произвольные HTML/JS и прямые внешние URL; нужны
  exact account/channel scope, file validation, cooldown, audit и owner Stop/Clear.
- Явная `!tts`/custom-команда только для allowlist; обычный чат автоматически
  озвучиваться не будет.
- Owner voice enrollment через микрофон с playback/перезаписью/удалением образца.
- Голосовые команды из stream audio только после speaker verification, настроенной
  activation phrase и whitelist intent parser. Низкая уверенность не запускает действие.
- Song Request из точной `!sr`, Channel Points и донатов; полный lifecycle очереди.
- UI нативных Twitch Polls и Predictions с проверкой broadcaster scopes. Старый
  собственный `!vote` и retired `/widget/poll-overlay` возвращаться не будут.
- Безопасный undo только для обратимого локального состояния. TTS, Soundboard,
  Twitch clips и moderation физического rollback не имеют.

## Быстрый старт

### Самый простой способ

**Linux / SteamOS / macOS:**
```bash
./start.sh
```

**Windows:** двойной клик на `start.bat` (или из консоли):

```bat
copy .env.example .env
start.bat
```

`start.bat` сам создаёт/лечит venv, ставит зависимости из `requirements.lock`
и запускает `python run.py`. Флаги: `--reinstall` (пересоздать venv),
`--skip-install` (только активировать и запустить), `--ml` (дополнительно
поставить optional Whisper/SpeechBrain stack из `requirements-ml.txt`).

> Перед первым запуском заполните `.env` (скопируйте из `.env.example`):
> без `TWITCH_TOKEN` бот не подключится, а без ключа AI-провайдера не будет
> ответов — либо выберите локальный Ollama.

### Ручная установка

```bash
sudo apt install -y ffmpeg
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.lock
cp .env.example .env
python run.py
```

Локальная Whisper-транскрипция, diarization и проверка голоса владельца требуют
тяжёлого optional ML stack (Torch не ставится вместе с core-панелью):

```bash
./start.sh --ml
# либо в активированной venv:
pip install -r requirements-ml.txt
```

Откройте **http://localhost:8000** в браузере.

`requirements.txt` задаёт допустимые диапазоны direct dependencies, а
`requirements.lock` фиксирует воспроизводимый core graph для Python 3.10+ на Linux,
macOS и Windows.
После изменения диапазонов lock обновляется отдельно:

```bash
uv pip compile requirements.txt --python-version 3.10 --universal \
  --output-file requirements.lock --no-emit-index-url
```

### Запуск профильных тестов

```bash
pip install -r requirements-dev.txt
pytest tests/test_<нужный_модуль>.py -q
```

ML-профиль и полный suite тяжёлые из-за Whisper/Torch и без отдельной необходимости
не запускаются.

## Конфигурация (.env)

| Переменная | Описание | По умолчанию |
|---|---|---|
| `AI_PROVIDER` | `openrouter` / `ollama` / `gemini` / `openai` / `anthropic` | `openrouter` |
| `OPENROUTER_API_KEY` | Ключ OpenRouter | — |
| `OPENROUTER_VISION_MODEL` | Модель для изображений | `google/gemini-2.0-flash-exp:free` |
| `OPENROUTER_CHAT_MODEL` | Модель для текста | `google/gemini-2.0-flash-exp:free` |
| `OLLAMA_HOST` | Адрес Ollama | `http://localhost:11434` |
| `PANEL_AUTH_USER` | Логин Basic Auth только для явного LAN/network доступа | — |
| `PANEL_AUTH_PASS` | Пароль Basic Auth только для явного LAN/network доступа | — |
| `PANEL_ALLOW_INSECURE_LOCAL` | Устаревший compatibility-флаг; localhost и так работает без пароля | — |
| `PANEL_BIND_HOST` | Интерфейс панели; обычный запуск только на loopback | `127.0.0.1` |
| `TOKEN_ENCRYPTION_KEY` | Ключ Fernet; вместе с полной auth-парой обязателен для сетевого bind | — |
| `TWITCH_CLIENT_ID` | Client ID Twitch приложения | — |
| `TWITCH_CLIENT_SECRET` | Client Secret | — |
| `DEFAULT_PROXY` | Прокси по умолчанию | — |

## Архитектура

Панель построена как локальное FastAPI-приложение:

- `run.py` запускает сервер и ограничивает обычный режим адресом `127.0.0.1`;
- `app/` содержит lifecycle, Twitch runtime, AI/TTS, SQLite и feature routers;
- `templates/` и `static/` — интерфейс владельца;
- `widgets/` — OBS Browser Source outputs и shared browser cores;
- `tests/` — focused unit/integration/behavior contracts.

Полная актуальная схема scope, маршрутов, данных, секретов, widgets и lifecycle находится в
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Не используйте старые audit/plans как описание
текущего runtime.

> Подробная текущая схема находится в [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
> Незавершённая работа — только в [PLAN_TODO.md](PLAN_TODO.md), а старые audit/plans —
> исторические материалы в [docs/archive/](docs/archive/) и git.

## API Reference

Ниже перечислены ключевые пользовательские endpoints, а не вручную замороженная
копия всей схемы. Полная актуальная OpenAPI-документация доступна в запущенной
панели по `/docs`, JSON-схема — по `/openapi.json`.

### Базовые (v10)

| Метод | URL | Описание |
|---|---|---|
| GET | `/api/accounts` | Список аккаунтов |
| POST | `/api/accounts` | Добавить аккаунт |
| PUT | `/api/accounts/:id` | Обновить аккаунт |
| DELETE | `/api/accounts/:id` | Удалить аккаунт |
| POST | `/api/accounts/:id/toggle` | Вкл/выкл аккаунт |
| POST | `/api/accounts/:id/start` | Запустить бота |
| POST | `/api/accounts/:id/stop` | Остановить бота |
| POST | `/api/send` | Отправить сообщение |
| GET | `/api/logs` | Логи чата |
| WS | `/ws` | WebSocket (live-логи + TTS events) |

### Анализ чата (v10)

| Метод | URL | Описание |
|---|---|---|
| GET | `/api/accounts/:id/analyzer` | Настройки анализатора |
| PUT | `/api/accounts/:id/analyzer` | Обновить настройки |
| GET | `/api/analyzer-presets` | Пресеты «режима бота» |
| POST | `/api/accounts/:id/analyzer-presets/:preset_id` | Применить пресет к боту |

### AI Override (v10.4)

| Метод | URL | Описание |
|---|---|---|
| GET | `/api/accounts/:id/ai-override` | Текущий override |
| PUT | `/api/accounts/:id/ai-override` | Установить override |

### v11: Персона

| Метод | URL | Описание |
|---|---|---|
| GET | `/api/accounts/:id/persona` | Получить персону |
| PUT | `/api/accounts/:id/persona` | Сохранить персону |
| GET | `/api/persona-presets` | Список пресетов (7 штук) |
| POST | `/api/accounts/:id/persona/apply-preset` | Применить пресет `{preset_id}` |
| POST | `/api/accounts/:id/generate-persona` | AI-генерация `{description}` |

### v11/v12: Streamer Profile + Face (вкладка «👤 О стримере» в настройках бота)

| Метод | URL | Описание |
|---|---|---|
| GET | `/api/accounts/:id/streamer-profile` | Получить профиль стримера |
| PUT | `/api/accounts/:id/streamer-profile` | Обновить профиль |
| GET | `/api/accounts/:id/streamer-face?include=0/1` | Получить фото лица |
| POST | `/api/accounts/:id/streamer-face` | Загрузить фото (multipart) |
| DELETE | `/api/accounts/:id/streamer-face` | Удалить фото |

> Вкладка «О стримере» (§9a): форма профиля + загрузка/удаление фото + превью.
> Покрыто тестами: tests/test_p1_streamer_profile_ui.py.

### v11: TTS

| Метод | URL | Описание |
|---|---|---|
| GET | `/api/tts/config` | Глобальный TTS конфиг |
| PUT | `/api/tts/config` | Обновить глобальный TTS |
| GET | `/api/accounts/:id/tts-config` | Per-bot TTS конфиг |
| PUT | `/api/accounts/:id/tts-config` | Обновить per-bot TTS |
| GET | `/api/tts/voices` | Список голосов/пресетов |
| GET | `/api/voice-clones` | Список клонов голосу |

### v11: Attention Filter + Chat Users

| Метод | URL | Описание |
|---|---|---|
| GET | `/api/accounts/:id/attention-config` | Настройки внимания |
| PUT | `/api/accounts/:id/attention-config` | Обновить конфиг |
| GET | `/api/accounts/:id/chat-users` | Список пользователей чата (⚠️ backend есть, в UI не вызывается) |
| PUT | `/api/accounts/:id/chat-users/:username` | Toggle enabled (⚠️ backend есть, в UI не вызывается) |

### v11: Bot Logs

| Метод | URL | Описание |
|---|---|---|
| GET | `/api/accounts/:id/bot-logs` | Логи бота (фильтры: level, category, q) |
| GET | `/api/bot-logs` | Все логи (фильтры: account_id, level, category, from, to) |
| DELETE | `/api/accounts/:id/bot-logs` | Очистить старые логи |
| GET | `/api/accounts/:id/bot-logs/export` | Экспорт CSV/JSON |

### Триггеры (v12)

| Метод | URL | Описание |
|---|---|---|
| GET | `/api/accounts/:id/triggers` | Список триггеров (channel, fires, last_fired_at) |
| POST | `/api/accounts/:id/triggers` | Создать триггер `{keyword, response, use_ai, channel}` |
| PUT | `/api/triggers/:id` | Обновить триггер |
| POST | `/api/triggers/:id/test` | Тестовый запуск `{text, channel}` → fired + причина отказа |
| POST | `/api/triggers/:id/toggle` | Вкл/выкл |
| DELETE | `/api/triggers/:id` | Удалить |

> Причины отказа теста: `trigger_disabled` / `channel_mismatch` / `no_keyword_match`.
> Триггер с пустым `channel` работает во всех каналах бота.

### v11: Channel Overrides

| Метод | URL | Описание |
|---|---|---|
| GET | `/api/accounts/:id/channel-overrides` | Список overrides |
| PUT | `/api/accounts/:id/channel-overrides` | Установить override (`{channel, enabled, overrides}` в body) |
| DELETE | `/api/accounts/:id/channel-overrides/:channel` | Удалить override канала |

### ✅ Bot Files (per-bot папки) — v13

Per-bot папки `data/bots/<id>_<ник>/` подключены к панели: вкладка бота «📁 Файлы»
(дерево файлов + просмотр/редактирование текстовых файлов прямо в панели).

| Метод | URL | Описание |
|---|---|---|
| GET | `/api/accounts/:id/files` | Список файлов (auto-init структуры при первом запросе) |
| GET | `/api/accounts/:id/files/{path}` | Прочитать текстовый файл |
| PUT | `/api/accounts/:id/files/{path}` | Записать (`{"content": "..."}`) |
| DELETE | `/api/accounts/:id/files/{path}` | Удалить файл |

Ограничения: только `json/md/txt` (и ряд текстовых конфигов), размер ≤ 256 КБ,
path traversal закрыт (покрыто тестами `test_ops_bot_files.py`).
Структура создаётся идемпотентно при старте бота (панель и standalone);
миграция существующих данных — только чтение (persona → `prompts/personality.txt`),
БД-источник не изменяется.

### Standalone runtime (служебный режим)

```bash
python scripts/run_bot.py <ник>
```

- Без FastAPI/браузера: только бот, AI, триггеры, TTS-события в лог.
- Общий SQLite и общий wiring с панелью (`app/bootstrap.py`) — поведение то же.
- Instance-lock: один и тот же бот не может управляться из панели и standalone
  одновременно (lock-файлы `data/locks/`, flock).
- Для обычной эксплуатации владельца используйте только `run.py`/панель.
  Standalone оставлен для разработки и диагностики и не является основным UX.

### ✅ Надёжность (v13)

- **Fallback AI** (OpenRouter 429/5xx/timeout → Ollama) логируется в bot_logs
  (категория `fallback`) — событие видно во вкладке логов бота в панели.
- **TTS деградация**: ElevenLabs (нет ключа/ошибка) → Piper → Web Speech;
  очередь ограничена (≤100 ожидающих, лишние запросы отменяются).
- **Reconnect**: обрыв соединения → авто-переподключение с exponential backoff;
  число переподключений видно в tooltip бейджа бота.
- **Watchdog**: раз в 60с сверяет желаемое состояние (включённые боты) с
  фактическим и переподнимает упавшие задачи.
- **Crash-изоляция**: падение одного бота не убивает остальных (тесты).

#### Оффлайн-чеклист (ручная проверка)

Полный запуск без интернета (локальный стек):

1. `.env`: `LOCAL_FALLBACK_ENABLED=1`; в панели AI-провайдер → Ollama,
   TTS-провайдер → Piper (модель загружена заранее), offline_mode = ON.
2. Отключите интернет/Wi-Fi. Запустите `python run.py --doctor` — ключи облачных
   провайдеров не требуются, ошибки только про Twitch (это ожидаемо).
3. `./start.sh`. Бот подключится к Twitch IRC
   только при наличии сети — без сети сообщения не читаются, но панель работает.
4. Проверьте: AI-ответ генерируется (Ollama), TTS озвучивает (Piper), ошибок
   fallback в логах нет (fallback не нужен — локальный провайдер основной).
5. Включите интернет — облачный провайдер возвращается в строй автоматически
   (сброс cooldown по первому успеху).

### Прочее

| Метод | URL | Описание |
|---|---|---|
| GET | `/api/engagement/settings` | Настройки engagement |
| PUT | `/api/engagement/settings` | Обновить engagement |
| GET | `/api/engagement/stats` | Статистика реакций |
| GET | `/api/stream-vision/config` | Конфиг Stream Vision |
| PUT | `/api/stream-vision/config` | Обновить Stream Vision |
| POST | `/api/backup/restore` | Восстановить бэкап |
| GET | `/api/backup/download` | Скачать бэкап |

## Новые настройки v11 (per-bot через analyzer)

| Настройка | Тип | Default | Описание |
|-----------|-----|---------|----------|
| `observation_only` | bool | false | Пишет в БД, но НЕ в чат |
| `silent_analysis` | bool | false | Анализирует чат без ответов |
| `log_all_messages` | bool | true | Сохранять все сообщения в chat_log |
| `batch_enabled` | bool | false | Пакетная обработка сообщений |
| `batch_window_sec` | float | 5.0 | Окно батча (сек) |
| `batch_max_size` | int | 5 | Максимум сообщений в пакете |
| `min_messages_to_respond` | int | 2 | Минимум сообщений для ответа |
| `raid_save_context` | bool | false | Сохранять контекст рейда |
| `raid_apply_overrides` | bool | false | Применять overrides для рейда |

## Новые настройки v11 (per-bot через persona)

| Настройка | Тип | Default | Описание |
|-----------|-----|---------|----------|
| `humor_level` | int 0-100 | 50 | Уровень юмора |
| `sarcasm_level` | int 0-100 | 30 | Сарказм |
| `darkness_level` | int 0-100 | 10 | Чёрный юмор |
| `crudeness_level` | int 0-100 | 0 | Грубость |
| `adult_humor` | int 0-100 | 0 | Взрослый юмор |
| `seriousness` | int 0-100 | 50 | Серьёзность |
| `emotionality` | int 0-100 | 50 | Эмоциональность |
| `contact_level` | int 0-100 | 50 | Привязанность к стримеру |
| `chat_affinity` | int 0-100 | 50 | Привязанность к чату |
| `dynamic_personality` | bool | false | Динамическая адаптация |
| `mood_influence` | int 0-100 | 0 | Влияние настроения чата |

## Пресеты персоны (v11)

| Пресет | Юмор | Сарказм | Adult | Серьёзность | Описание |
|--------|-------|---------|-------|-------------|------|
| 🟢 Новичок | 30 | 20 | 0 | 50 | Тихий, осторожный |
| 🤝 Друг | 60 | 40 | 30 | 40 | Добрый, поддерживает |
| 😈 Тролль | 80 | 80 | 50 | 20 | Подкалывает, провоцирует |
| 🧠 Мудрец | 40 | 60 | 10 | 80 | Советы и подколы |
| ☠️ Токсик | 70 | 90 | 80 | 10 | Жёсткий, без фильтров |
| 😌 Спокойный | 20 | 10 | 0 | 50 | Ровный тон |
| 🌪️ Дикий | 90 | 85 | 90 | 5 | Без границ |

## Docker

```bash
docker build -t twitch-bot .
docker run -p 8000:8000 --env-file .env twitch-bot
```

Production (healthcheck, restart policy, volume data/, лимит памяти):

```bash
docker compose -f docker-compose.prod.yml up -d
# с локальным Ollama:
docker compose --profile tools -f docker-compose.prod.yml up -d
```

## Эксплуатация (v13)

- `python run.py --doctor` — проверка окружения: ключи, Helix, Ollama, папки,
  права записи; отчёт «что не настроено и на что это влияет».
- Версия: `GET /api/version` (в панели — footer).
- Логи: `logs/panel.log` — ротация 10МБ × 5; per-bot логи — суточная чистка по
  `BOT_LOG_RETENTION_DAYS` (дефолт 30, 0 = отключить).
- Авто-бэкап: раз в `AUTO_BACKUP_DAYS` (дефолт 7) в `data/backups/`,
  хранится `AUTO_BACKUP_KEEP` (дефолт 5) копий; ручной — в панели.
- БД: Настройки → БД — размер/записи, кнопка «Оптимизировать» (PRAGMA optimize + VACUUM).

## Браузерный smoke (опционально)

```bash
pip install playwright && playwright install chromium
python scripts/browser_smoke.py
```

Открывает панель, проверяет §20-список: вкладки ботов, Quick Send, health-бейджи,
триггеры, TTS-тест, провайдеры, переключение языков, responsive 390px.
Коды завершения: `0` — проверки зелёные, `1` — найдены ошибки панели,
`2` — Playwright не установлен (ошибка подготовки окружения, не пропуск).

## Тесты

```bash
pip install -r requirements-dev.txt
pytest tests/test_<нужный_модуль>.py -q
```

Набор тестов меняется вместе с кодом; актуальный результат смотрите в выводе
локального или CI-запуска. Полный `pytest tests/` занимает заметное время и тянет
ML-зависимости, поэтому по умолчанию запускаются только тесты затронутого модуля.
Покрыты персона, attention filter, TTS, bot logs, presets, streamer profile,
engagement, anti-spam, security, backup, diarization и интеграционные сценарии.

> Число тестов и полный список несоответствий между документацией/UI и фактическим кодом
> актуализируются в [docs/archive/AUDIT_SECTION1.md](docs/archive/AUDIT_SECTION1.md) — сверяйтесь с ним, а не только
> с этим README, если нужна точная картина готовности функций.

## Лицензия

Проект распространяется по лицензии **MIT** с дополнением
«Условие добросовестного использования» (Good Faith Use Addendum).
Полный текст — в файле [LICENSE](LICENSE).
