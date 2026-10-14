# Widget binding contracts — Track 6.5

Статический аудит 05.09.2026. Канонический список — `WIDGET_INVENTORY` в
`app/widget_inventory.py` (32 активных контракта). `Binding: none` означает
осознанный display/data-driven контракт, а не недоделанную форму.

| Widget | Data source | Manual control | Binding |
|---|---|---|---|
| `tts` | WebSocket chat/TTS queue | TTS design | none |
| `animated-bg` | URL config + local animation | URL/design config | none |
| `goals` | public goals API | goal CRUD and percent | `add_percent`, `reset` by goal ID |
| `now-playing` | public API + configured media source | set, clear, source | `set`, `clear` |
| `sub-goal` | public API + subscribe EventSub | save, ±1, reset | `increment`, `set`, `reset` |
| `schedule` | public schedule API | block CRUD | none |
| `uptime` | stream-session API | stream lifecycle | none |
| `follower-ticker` | recent-events API | event pipeline | none |
| `lower-third` | public lower-third API | content and visibility | `show`, `hide` |
| `mascot` | character config + event bus | preset/assets | none |
| `anime-runner` | character config | color/corner/speed | none |
| `chat-highlight` | highlighted-chat API | selected-chat flow | none; trusted selection workflow |
| `chat-roulette` | roulette API | config and spin | none; scoped panel workflow |
| `song-request` | request queue API | queue/settings | none; moderated request workflow |
| `top-donator` | donation API by period | period/donation records | none |
| `countdown` | public timer API | start, pause, reset | `start`, `pause`, `reset`, `add_time` |
| `donation-challenge` | active challenge API | challenge/funds CRUD | none; donation ingress + scoped panel CRUD |
| `clip-moments` | scoped clips API | clip workflow | none; state is read-only per account/channel |
| `latest-event-card` | shared recent-events model | test event/config | none |
| `tts-bot` | WebSocket TTS queue | TTS settings | none |
| `tts-chat-overlay` | WebSocket TTS queue | overlay/TTS settings | none |
| `hype-meter` | WebSocket chat activity | automatic | none |
| `subathon-timer` | timer API + EventSub/donations | start/stop/tariffs | none; trusted ingress + scoped panel controls |
| `emoji-leaderboard` | emoji statistics API | automatic | none |
| `blur-guard-v2` | blur state API + WebSocket/OBS | on/off/config/zones | none; protected public controls are its contract |
| `chat-reader` | WebSocket TTS queue | reader/design settings | none |
| `emoji-chat` | emoji core + WebSocket | automatic | none |
| `selected-chat` | selected history + WebSocket | trusted users/display | none |
| `media-share` | moderated media queue + WebSocket | queue moderation | none; moderated queue workflow |
| `mod-feed` | moderation event API | feed/filter settings | none |
| `soundboard` | WebSocket soundboard event | upload/play | `play_track:<positive track ID>` |
| `recent-events` | shared recent-events model | test event/clear | none |

## Проверенные инварианты

- У всех 32 контрактов есть папка реализации либо явный alias, каноническая
  карточка, публичный route и непустой preview URL.
- Пять widget-scoped binding-контрактов объявлены в `WIDGET_BINDING_SLUGS`;
  Soundboard создаёт только track-specific action из строки конкретного трека.
- `BINDING_CONTRACT` в `app/widget_bindings.py` — единый active manifest для
  semantic action ID, i18n label, source/role policy и typed key/value schema.
  Панель получает его через `/api/widgets/binding-contract`; отдельной JS-копии
  action map нет. Retired Counter не показывается, но legacy executor/preset API
  остаются для сохранённых интеграций.
- Все контракты настраиваются через единый builder «где → когда → тогда».
  Кнопки карточек только выбирают соответствующий виджет и открывают этот builder;
  отдельных технических форм и дублирующих списков правил в карточках нет.
- EventSub принимает только `follow`, `subscribe`, `cheer`, `raid`; роль события
  всегда `any`. Chat-команды доступны только broadcaster/mod, а panel hotkey —
  только владельцу. Moderation binding допускается только как panel hotkey владельца.
- Goal ID и числовые values валидируются до сохранения; неизвестные source/event,
  пустые match и несуществующие semantic action отклоняются HTTP 400.
- Subathon, Chat Highlight, Chat Roulette, Donation Challenge, Song Request,
  Media Share, Clip Moments и Blur Guard не получают фиктивные bindings:
  их осмысленные controls уже принадлежат scoped panel/queue/data-source workflow.
  Blur Guard остаётся scene-global; privacy controls не экспортируются в chat-команды.
- Управляемые semantic actions доступны через scoped chat/EventSub/panel-hotkey
  contract; keydown не срабатывает в form fields. OBS hotkeys управляют сценами и
  sources, а не admin binding API, поэтому фиктивного OBS adapter нет. Для внешней
  клавиши явно документированы Streamer.bot/public API и chat-команды.
- Soundboard, TTS, Twitch clip и moderation отсутствуют в voice rollback
  whitelist. Moderator `confirm_mode` сохраняет approve/reject до внешнего
  действия. Clip Detector только пишет найденный момент; Twitch Helix вызывается
  отдельной кнопкой, проверяет exact enabled account/channel и честно возвращает
  permission error без записи ложного клипа.

## Scope и состояние виджетов

`widget_bindings` хранит обязательные `account_id` и нормализованный `channel`.
CRUD, chat, EventSub, panel hotkey и пресеты работают только в точном scope;
moderation action требует явно выбранный moderator-account того же канала.
Legacy global binding-строки удаляются при миграции, потому что безопасно
приписать их конкретному scope невозможно.

Владелец выбрал per-account/channel state-модель (Q20, 05.09). Новые scoped
OBS URL и state API получают явные `account_id`/`channel`; старые публичные URL
сохраняются как compatibility default и не удаляются. Миграция выполняется по
state family с cross-scope тестами: binding scope A не меняет payload scope B.

Scoped storage завершён для `counters`, `goals`, `sub-goal`, `countdown`,
`now-playing` и `lower-third`; `clip-moments` уже хранил оба поля, и теперь его
public read/Browser Source тоже фильтрует точную пару. Панель берёт scope из явных account/channel
селекторов, а новые Browser Source URL передают ту же пару в public API. URL без
обоих параметров по-прежнему читают отдельные legacy singleton/global rows — они
не выбирают «первый enabled account» и поэтому не могут молча переключиться при
добавлении бота. Last.fm/MPRIS пишет только в legacy `now_playing`: локальный
источник не несёт channel context. WebSocket broadcast пока остаётся глобальным;
изоляцию обеспечивают scoped HTTP reads, а формат существующих WS events не меняется.

Для Clip Moments старые URL без `channel` сохранены как явная compatibility-модель:
без параметров читается общий legacy feed, а исторический `account_id`-only URL —
account-global feed. Новые URL панели всегда передают одновременно `account_id` и
нормализованный `channel`; неизвестный или disabled scope отклоняется с `400`.

Живая browser/OBS-проверка карточек и preview не подменяется этим статическим
аудитом; она остаётся отдельным acceptance gate.
