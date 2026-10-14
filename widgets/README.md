# widgets/ — OBS-виджеты

Каждый виджет — **один самостоятельный HTML-файл** (`widgets/<name>/index.html`):
весь HTML + CSS + JS внутри. Правится на лету — сервер подхватывает изменения
без рестарта (mtime-кэш в `app/widgets.py::_widget_html`).

## Активный inventory и рекомендуемый размер OBS

Канонический источник — `app/widget_inventory.py:WIDGET_INVENTORY` и
`WIDGET_OBS_SIZES`. Таблица обязана перечислять все активные контракты один раз.

| Slug | Файл | URL | Canvas OBS |
|---|---|---|---|
| `tts` | `tts-raw/index.html` | `/obs/tts` | 1000×180 (overlay) |
| `animated-bg` | `animated-bg/index.html` | `/widget/animated-bg` | 1920×1080 (fullscreen) |
| `goals` | `goals/index.html` | `/widget/goals` | 500×500 (overlay) |
| `now-playing` | `now-playing/index.html` | `/widget/now-playing` | 560×120 (overlay) |
| `sub-goal` | `sub-goal/index.html` | `/widget/sub-goal` | 520×420 (overlay) |
| `schedule` | `schedule/index.html` | `/widget/schedule` | 560×500 (overlay) |
| `uptime` | `stream-session/index.html` | `/widget/uptime` | 360×70 (overlay) |
| `follower-ticker` | `follower-ticker/index.html` | `/widget/follower-ticker` | 1920×80 (strip) |
| `lower-third` | `lower-third/index.html` | `/widget/lower-third` | 520×180 (overlay) |
| `mascot` | `mascot/index.html` | `/widget/mascot` | 240×240 (overlay) |
| `anime-runner` | `anime-runner/index.html` | `/widget/anime-runner` | 1920×1080 (fullscreen) |
| `chat-highlight` | `chat-highlight/index.html` | `/widget/chat-highlight` | 640×220 (overlay) |
| `chat-roulette` | `chat-roulette/index.html` | `/widget/chat-roulette` | 420×460 (overlay) |
| `song-request` | `song-request/index.html` | `/widget/song-request` | 440×320 (overlay) |
| `top-donator` | `top-donator/index.html` | `/widget/top-donator` | 420×240 (overlay) |
| `countdown` | `countdown/index.html` | `/widget/countdown` | 700×300 (overlay) |
| `donation-challenge` | `donation-challenge/index.html` | `/widget/donation-challenge` | 560×220 (overlay) |
| `clip-moments` | `clip-moments/index.html` | `/widget/clip-moments` | 460×360 (overlay) |
| `latest-event-card` | `latest-event-card/index.html` | `/widget/latest-event-card` | 440×280 (overlay) |
| `tts-bot` | `tts-bot/index.html` | `/widget/tts-bot` | 900×260 (overlay) |
| `tts-chat-overlay` | `tts-chat-overlay/index.html` | `/widget/tts-chat-overlay` | 800×240 (overlay) |
| `hype-meter` | `hype-meter/index.html` | `/widget/hype-meter` | 340×120 (overlay) |
| `subathon-timer` | `subathon-timer/index.html` | `/widget/subathon-timer` | 360×150 (overlay) |
| `emoji-leaderboard` | `emoji-leaderboard/index.html` | `/widget/emoji-leaderboard` | 320×360 (overlay) |
| `blur-guard-v2` | `blur-guard-v2/index.html` | `/obs/blur-guard-v2` | 1920×1080 (fullscreen) |
| `chat-reader` | `chat-reader/index.html` | `/widget/chat-reader` | 800×220 (overlay) |
| `emoji-chat` | `emoji-chat/index.html` | `/widget/emoji-chat` | 480×420 (overlay) |
| `selected-chat` | `selected-chat/index.html` | `/widget/selected-chat` | 560×600 (overlay) |
| `media-share` | `media-share/index.html` | `/widget/media-share` | 1920×1080 (fullscreen) |
| `mod-feed` | `mod-feed/index.html` | `/widget/mod-feed` | 560×500 (overlay) |
| `soundboard` | `soundboard/index.html` | `/widget/soundboard` | 360×60 (overlay) |
| `recent-events` | `recent-events/index.html` | `/widget/recent-events` | 480×420 (overlay) |
| `streamer-hud` | `streamer-hud/index.html` | `/widget/streamer-hud` | 480×560 (overlay) |

## Использование в OBS

1. В OBS: Источники → **Browser Source** → URL вида `http://localhost:8000/widget/goals`
2. Размер берите из таблицы выше; это canvas Browser Source, а не CSS-resize виджета.
3. Параметры темы: `?theme=dark|light` (у части виджетов: `?theme=neon|glass|fire|minimal`).

## Работа без панели

Панель (браузерный UI) не нужна — виджетам нужен только **работающий сервер**
(`python run.py`), потому что данные лежат в SQLite и отдаются через публичный API:

- все данные `/api/widgets/public/*` читаются без авторизации;
- менять данные без панели можно тремя путями:
  1. **HTTP API** — curl из OBS-скрипта/хоткея:
     `curl -X POST http://localhost:8000/api/widgets/counters/death/increment -H 'Content-Type: application/json' -d '{"delta":1}'`
     (increment/reset без Basic-auth, но только с loopback-адреса — для локальных OBS-хоткеев);
  2. **Чат-команды бота / биндинги** для поддерживаемых действий;
  3. **Донат-интеграции** через настроенные provider/webhook-потоки.

### Полностью автономные (без backend) виджеты

Открываются просто как файл (`file://`) или с любого статик-сервера:

- `animated-bg/index.html` — чистый JS-эффект;
- остальные требуют `/api/widgets/public/*` или `/ws` — то есть работающий сервер
  (без панели, но с сервером).

## Редактирование

- Правьте `widgets/<name>/index.html` напрямую — изменения видны в OBS после F5
  (и на сервере сразу, рестарт не нужен).
- Роуты `/widget/*` в `app/widgets.py` читают эти файлы через `_widget_html(name)`.
- Удалённый файл → понятная страница ошибки, сервер не падает.

## Дизайн-система (§11.6/§12.3)

- `widgets/_shared/theme.css` — единые токены: палитра (`--w-accent`, `--w-gold`),
  радиусы, тени, шрифты (body ≥ 18px), безопасные отступы.
- `?scale=1.5` — масштаб виджета для 1440p/4K (zoom), поддерживают новые виджеты
  (hype-meter, subathon-timer, emoji-leaderboard, emoji-chat).
- `?api=http://panel:8000` — все виджеты (§11.0): адрес панели переопределяется,
  если виджет открыт с другого хоста/порта.
- `_shared/widget-bus-client.js` — сниппет для сторонних виджетов, реагирующих
  на duck/pause-события Widget Bus (§1/§4).

## Compatibility-контракты после owner survey 03.09

`/widget/moderator-media` — отдельный защищённый output, не карточка общего
inventory. URL создаётся owner-only поверхностью и работает только с точными
`account_id + channel + rotated OBS token`; reusable preview URL намеренно нет.

Публичные compatibility URL сохраняются явно:

- retired placeholders: `/widget/voice-changer`, `/widget/counter`,
  `/widget/combo-counter`, `/widget/typing-indicator`, `/widget/poll-overlay`;
- alias на актуальную реализацию: `/obs/blur-guard` → `/obs/blur-guard-v2`;
- legacy period routes: `/widget/top-donator-alltime`,
  `/widget/top-donator-month`, `/widget/top-donator-day`.

- **Карточки добавлены в панель**: follower-ticker, donation-challenge, emoji-chat,
  hype-meter (+ subathon-timer с тарифами: за саб / плоско за донат / за единицу валюты).
- **tts-chat-overlay** — карточка «💬 TTS-чат (озвучки)» (P6); **tts-raw** = `/obs/tts`
  и **stream-session** = `/widget/uptime` — в grid-сетке виджетов.
- **emoji-leaderboard** и **media-share** — актуальны (owner survey 03.09, Q34/Q8):
  emoji-виджеты объединены общим ядром `app/emoji_core.py`, media-share оставлен.
  Баннер «Виджет не актуален» от 31.08 снят — он противоречил решению survey.
- **media-share и YouTube:** реальный OBS output загружает внешний YouTube IFrame API и требует
  интернет; safe preview в панели YouTube не загружает. YouTube получает video ID и обычные данные
  сетевого запроса браузера/OBS и может запретить embed или autoplay. Панель показывает эти сбои,
  потерю queue/API и reconnect отдельно, не выдавая queue status за доказанное воспроизведение.
  Request provenance и решение модерации остаются в channel-scoped Song Request audit. Перед первым
  копированием output URL показывается сохраняемое предупреждение, которое можно открыть повторно
  через Настройки → Media Share и YouTube.
- **voice-changer** — выведен из эксплуатации (owner survey Q4: pipeline не используется).
  Папка удалена, карточки нет; URL `/widget/voice-changer` живёт тёмной заглушкой ради
  уже настроенных OBS-сцен (реестр — `app/widget_inventory.py:RETIRED_WIDGETS`).
- **counters** — оверлей выведен из эксплуатации (owner survey Q12). Папка удалена,
  URL `/widget/counter` живёт заглушкой. **API счётчиков остался рабочим:**
  `/api/widgets/public/counter/<key>`, `/api/widgets/counters/<key>/increment|reset`;
  mutations доступны только локальным curl/OBS-хоткеям, чат-команды работают через
  внутренний binding path, ручное управление — в панели.
- **combo-counter** — выведен из эксплуатации (owner survey Q14). Папка, admin/public
  API и автотрекинг серий в `chat_analyzer` удалены; URL живёт заглушкой.
- **typing-indicator** — выведен из эксплуатации (owner survey Q26). Папка и
  broadcast-хук `typing_indicator` в `chat_analyzer` удалены; URL живёт заглушкой.
- **poll-overlay** — выведен из эксплуатации (owner survey Q28). Папка, оверлей,
  свой `!vote`-опрос (`custom_poll` API) и его форма в панели удалены; URL живёт
  заглушкой. **Нативные Twitch Polls остались:** создаются из панели через
  `/api/widgets/twitch-poll` и показываются самим Twitch.
- **top-donator** — Wave 3 (owner survey Q15-17: М): три виджета объединены в один
  с параметром `?period=alltime|month|day`. Исторические URL `/widget/top-donator-alltime`,
  `-month`, `-day` продолжают работать (реестр — `app/widget_inventory.py:LEGACY_PARAM_URLS`),
  публичный API — `/api/widgets/public/top-donator/<period>`.
- **blur-guard** (старый) — удалён (owner survey Q36): v2 умеет всё то же плюс зоны
  и live-настройки. URL `/obs/blur-guard` оставлен **alias'ом на `/obs/blur-guard-v2`**,
  а не заглушкой — уже настроенные OBS-сцены продолжают работать как раньше
  (реестр — `app/widget_inventory.py:ALIAS_WIDGETS`).
