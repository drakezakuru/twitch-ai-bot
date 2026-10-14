# Спецификация роли «Режиссёр»

> Подготовка роли к полноценному live-релизу обязательна по `DEC-DIRECTOR-010`; это не optional backlog.
> Runtime foundation и этап `DEC-DIRECTOR-009` / `DEC-BOTS-004` реализованы, но не закрывают всю спецификацию.
> Подробный обязательный план — `DIRECTOR-LIVE`, этапы `DIR-LIVE-00`…`DIR-LIVE-10` в
> [`PLAN_TODO.md`](../../PLAN_TODO.md); решения — в [`DECISIONS.md`](../DECISIONS.md).
> Browser/OBS, реальные провайдеры и ML требуют отдельного разрешения.

## 1. Цель

`director` — AI-роль, которая непрерывно анализирует Twitch-стрим и управляет явно выбранными
non-AI `lurker` accounts. Режиссёр создаёт естественные краткие реакции чата; сам от своего аккаунта
в Twitch не пишет.

Это не система обхода Twitch rate limits/AutoMod и не скрытый botnet. Backend обязан соблюдать
permissions, channel modes, outgoing moderation, idempotency и emergency stop независимо от prompt.

## 2. Участники и scope

- Один active Director на Twitch channel.
- Другие Director accounts могут быть offline/training, но automatic failover нет.
- Selected workers задаются owner multi-select из enabled lurker accounts этого channel.
- Новый lurker не добавляется автоматически.
- Role change/disable/remove мгновенно отзывает worker и отменяет его unsent задания.
- Lurker не вызывает AI и не принимает самостоятельных содержательных решений.
- Lurker сохраняет chat/events и выполняет только проверенный structured plan Director.
- Own bot messages видны Director как `own_bot`, но не входят в viewer activity, language detection,
  hype или copypasta source. В chat/emoji widgets и общей analytics владелец выбрал считать их обычно.
- Automation указывается владельцем в Twitch profile каждого lurker; панель профиль не проверяет/меняет.
- Через workers запрещены URL, приглашения, `!commands`, code-like strings и `@mentions`.

## 3. Источники контекста

Для live одновременно используются:

- deduplicated channel chat;
- Twitch events: follow/sub/donation/reward/raid и lifecycle;
- Stream Vision descriptions;
- full speech transcript;
- title/category/tags и stream duration.

Vision и speech — обязательные live sources. Потеря любого source ставит Director на pause, запрещает
новые plans и отменяет unsent хвост. Vision stale threshold настраивается, default 45 секунд;
speech/transcriber heartbeat threshold — default 15 секунд. Тишина и статичный кадр healthy, если
приходят свежие успешные heartbeat/description. Auto-resume возможен после 15 секунд стабильной работы;
paused events задним числом не исполняются. Raid/End по речи требуют verified owner voice; guest/unknown
speech используется как контекст, но не как команда.

## 4. AI config

Director имеет собственные:

- provider/model;
- temperature/max tokens;
- channel language `Auto / RU / EN / Mixed`, default Auto с translit;
- analysis interval 3–120 seconds, default 15;
- high-priority wake cooldown 3–30 seconds, default 5 — verified Twitch events (raid/follow/sub/cheer
  через integration hook) ставят priority; следующий анализ идёт по этому cooldown вместо полного интервала;
- consecutive AI errors до pause: 1–10, default 3.

Можно использовать Ollama, custom или cloud provider. При cloud provider отправляются short chat window,
short transcript window, Vision text description и compact current-session summary. Raw audio/screenshots
обычный Director request не получает.

Одновременно выполняется максимум один Director analysis request. Fixed interval является основой;
high-priority signal может разбудить анализ раньше, а несколько сигналов coalesce. Automatic provider
fallback отсутствует. После configured consecutive errors Director pause; восстановление требует
15 секунд healthy AI/Vision/speech и одного valid dry-run без Twitch send.

## 5. Stream session

- Live запускается только owner button.
- Если AI/Vision/speech не готовы, запуск отклоняется с точными причинами.
- После успешного start накапливается минимум 30 секунд rolling context.
- Director реагирует не только на hype: start, gradual joins, raids, quiet moments, game/video changes,
  win/loss, chat waves, follow/sub/donation/reward и end stream.
- Twitch offline сразу запрещает новые plans; grace default 60 seconds (legal 0–300) определяет,
  продолжается ли session после reconnect или финализируется. Реализация: offline ставит паузу с
  причиной `offline`, отменяет unsent и pending joins; верифицированный reconnect в grace перезапускает
  окно и auto-resumes после 15 секунд стабильного health; после grace сессия финализируется
  (transcript закрыт, state stopped), поздний reconnect не воскрешает её.
- Pause хранит причину (`manual` / `sources` / `ai_errors` / `offline`); resume после AI-error паузы
  требует valid dry-run, после manual/sources — 15 секунд стабильного health.
- Incoming raid создаётся только из точного Twitch event. Manual Raid/End показывает preview и требует
  confirmation; Raid-кнопка не вызывает реальный Twitch raid.
- Start/raid/end plans получают высокий приоритет, но не отменяют обычный valid хвост.
- Manual End закрывает только Director session, не Twitch stream и не обычных bots.
- Отдельный confirmed Stop закрывает session без финальной реакции.
- При завершении unsent хвост отменяется, transcript и audit закрываются.

## 6. Lurker join lifecycle

Selected lurkers входят постепенно: каждый получает независимую случайную задержку 0–30 минут при
первом входе текущей stream-session. Подключение происходит молча. Уже входивший worker после network
failure переподключается сразу по обычному backoff, без новой join-delay.

Для каждого worker панель показывает scheduled/connecting/online/error и кнопку «Зайти сейчас».
Кнопка активна только для scheduled: отменяет timer и создаёт не более одной connect attempt. Disabled,
connecting и online не запускают скрытый второй connect. Offline/end stream отменяет pending joins.
Если в момент реакции доступных workers ноль, plan фиксируется skipped и позже не воспроизводится.

## 7. Reaction levels и настройки

Для любого числа available workers владелец выбирает режим `absolute` или `percentage`.

Default absolute ranges:

- `small`: 0–3 bots;
- `medium`: 4–12 bots;
- `large`: 13–30 bots.

Default percentage ranges:

- `small`: 0–10%;
- `medium`: 10–35%;
- `large`: 35–70%.

Диапазоны редактируются, не пересекаются и строго возрастают. Ноль означает deliberate silence.
Процент >0 округляется до ближайшего целого с minimum 1. Text-group percentages суммарно равны
общему проценту; целые accounts распределяются методом наибольшего остатка. Расчёт использует только
enabled, online и свободных workers из immutable snapshot; поздний connect/disconnect plan не пересчитывает.

Timing defaults:

- send delay 1–20 seconds внутри legal 0–300;
- TTL 45 seconds внутри legal 1–600;
- TTL не меньше max delay;
- после TTL unsent хвост отменяется.

Live не включается без valid ranges, timing, assignment mode, selected workers, healthy sources и active
tested prompt version.

## 8. Structured plan

Immutable system/schema prompt требует plan со следующими полями:

- unique plan ID;
- channel/session/source snapshot IDs;
- short observable explanation без chain-of-thought;
- reaction level и percentage;
- assignment mode;
- compact groups `text + percentage`;
- optional individual rows;
- delay window и TTL;
- template/example references.

Exact schema проектируется перед реализацией и покрывается fixtures для Ollama/custom/cloud. Provider
использует JSON Schema/tool calling, если доступно, иначе strict JSON fallback. Полностью неразбираемый
ответ получает одну repair attempt; несовместимая model не допускается в live.

### Assignment modes

Owner может выбрать один mode для channel:

1. AI возвращает allowed `bot_id + text + delay`;
2. AI создаёт тексты/groups, backend случайно выбирает free workers из allowlist.

Default — backend random. Один worker не попадает в две text groups одного plan.

### Diverse, chant и copypasta

- Обычный generated text — максимум 120 symbols.
- `diverse` similarity настраивается `off/normal/strict`, default normal.
- `chant` допускает exact duplicate text. Owner dictionary постоянный; AI-added phrase действует только
  текущую session и становится permanent после owner approval.
- Copypasta имеет отдельный channel toggle, default off.
- Exact copypasta копирует одно Twitch message viewer/streamer; несколько сообщений не склеиваются.
- После использования она может стать temporary session template и повторяться без нового source message,
  но каждый repeat — новый fully validated plan.
- Hard-filtered source не отправляется автоматически, попадает owner в suggest и может стать только
  negative training example.
- Всегда запрещены personal data/secrets, URL, commands, @mentions, system/mod/integration messages и
  управление integrations; channel outgoing policy дополнительно регулирует мат/caps/topics.
- Twitch reject/slow/rate/duplicate не обходится другим account или изменением текста.
- Optional templates имеют per-item mode `exact`, `placeholders` или `adaptable`.

## 9. Scheduling и partial execution

- Несколько non-conflicting plans могут исполняться параллельно.
- Один worker не участвует одновременно в двух plans.
- Random assignment выбирает другого free worker или уменьшает группу.
- Invalid AI-assigned worker пропускается без замены.
- Invalid groups/text/parameters отбрасываются; valid часть исполняется без compensation/recount и
  показывается жёлтым partial status с planned/valid/rejected details.
- Ошибка одного worker не останавливает остальных.
- Retry разрешён только тому же account при временной ошибке и до TTL.
- Plan/group/message ID исполняется максимум один раз через retry/reconnect/restart.
- Semantic duplicate moments отсеивает AI; backend не пытается угадывать сходство разных событий.
- Channel TTS всегда использует одну последовательную audio queue.

## 10. Modes

- `training`: анализ и plans без Twitch send;
- `suggest`: whole-plan preview/edit и сохранение как approved example либо отклонение, без Twitch send;
- `live`: automatic execution valid частей.

Основной желаемый режим — live. Suggest не должен блокировать MVP.

## 11. Prompt и обучение

- System/schema/safety prompt не редактируется owner text field.
- Owner prompt хранится всеми версиями до ручного удаления, с diff/activate/rollback.
- Новая версия обязана пройти настоящий schema/hard-safety replay через exact provider/model; automated
  tests используют fake-provider seam. Для активации owner отдельно подтверждает качество примеров.
- Active/last-working version нельзя удалить без замены; для referenced old version удаляется только text,
  а metadata/hash остаются в audit.
- Встроенная versioned library текстовых fake moments готова сразу и не вызывает AI при первом старте.
- Сценарии: game/video/talk, start/end, raid, pause, win/loss, donation, chat wave и silence.
- Optional AI generation создаёт дополнительные **текстовые** fake moments; это не fine-tuning.
- Fake screenshots не используются.
- Example можно approve, edit или reject; rejected служит negative example.
- Suggest сохраняет approved example для будущих автономных live-решений и никогда не отправляет plan
  в Twitch напрямую.
- В новую stream session переходят только built-in и owner-approved examples/config/prompt.

## 12. Storage

- Full transcript хранится по sessions до ручного удаления. Status warning при 5 GB, hard recording limit
  20 GB; после limit live продолжает работать по свежей речи без записи полной истории.
- Session export ZIP всегда содержит TXT+JSON transcript, audit и все frames с real usernames.
- Live frames default off; после включения retention 90 days или 10 GB per channel, что раньше.
- Pinned frames имеют отдельный hard limit 5 GB без auto-delete.
- Approved training examples имеют отдельный hard limit 10 GB; новые approvals блокируются при заполнении.
- Approved real example копирует весь moment, переживает удаление source session и маскирует usernames как
  `Viewer-1`, `Viewer-2` только внутри example.
- Session deletion показывает состав и требует ввести `УДАЛИТЬ`; общей delete-all кнопки нет. Удаляются
  transcript, frames и raw rejected evidence, audit остаётся без дословной речи/изображений. Повторный
  запрос удаления идемпотентен и не выдаёт ложное «удалено».
- Session export пишет ZIP потоково на диск (архив не грузится в память), включает manifest.json с
  sha256 и размерами; missing/corrupt файлы честно репортятся в manifest и ответе, не скрываются за успехом.
- `data/director/**` входит в общий backup/restore с per-file cap; restore валидирует пути (traversal
  пропускается) и восстанавливает содержимое, размеры и hashes, а не только manifest.
- Owner panel показывает sessions list (state + pause_reason), storage usage/limits, pin/unpin, export и
  deletion; причина паузы различима: `manual` / `sources` / `ai_errors` / `offline`.
- Raw rejected data хранится в local DB/backup/export без маскирования по решению владельца; отдельного
  warning перед backup/export нет.
- Synthetic training остаётся text-only.

## 13. Audit и emergency stop

Audit содержит:

- time/channel/session;
- available sources и context summary;
- level/percentage;
- selected accounts и text groups;
- delays/TTL;
- validation rejection, send/skip/error statuses;
- template/example IDs.

Hidden chain-of-thought не сохраняется. Реализация audit-записи plan: accounts (id), число групп,
delay_min/max, TTL, planned/valid/rejected и source_snapshot_id; тексты сообщений в audit не пишутся.

Emergency Stop виден только во вкладке Director; optional hotkey назначает owner, default отсутствует.
Он срабатывает мгновенно без confirmation:

- переводит channel в paused;
- отменяет unsent хвост;
- запрещает новые plans.

Возврат после Emergency Stop только ручной: 15 seconds health + valid dry-run. Панель предлагает last
working prompt, но не откатывает автоматически.

Обычная Pause замораживает хвост до исходного TTL. Resume требует 15 seconds health без dry-run, если
config не менялся. Settings read-only в live и редактируются в off/paused через Save + dirty guard.
Отдельный Stop с confirmation закрывает session без end reaction. После process restart session
восстанавливается paused, unsent хвост отменён, automatic live resume запрещён.

## 14. Remaining implementation gates

Продуктовые вопросы интервью закрыты. Python/Node gates проверяют код без браузера, OBS и сети;
они не доказывают совместимость реальной модели и целевого устройства.

- `app/director_plan.py` содержит versioned JSON Schema и pure validation; `app/director.py` — scheduler
  и production adapter. Текущий adapter передаёт schema текстом и использует strict JSON; поддержка native
  tool calling/structured-output конкретными моделями пока не заявляется.
- Additive Director tables и replay/example tables создаются через `ensure_schema`, legacy rows не удаляются.
- Перед live release нужны отдельные проверки выбранных Ollama/custom/cloud models, source health,
  полного storage/lifecycle контракта и всех ещё не подтверждённых сценариев большой спецификации.
- Browser/real OBS/ML acceptance остаётся отдельным gate после owner **«поехали»**.

## 15. Реализованный review workflow (`DEC-DIRECTOR-009`)

### Настройка и проверка

1. Сохранить Director account, channel, workers, provider/model и остальные параметры.
2. Создать неизменяемую версию owner prompt. System/schema/safety policy хранится отдельно и не редактируется
   этим полем; owner preferences и контекст передаются как данные.
3. Нажать «Проверить через provider/model». Это явный запрос к выбранному провайдеру, но не к Twitch,
   камере или микрофону. Встроенный `director-replay/v1` содержит шесть текстовых synthetic cases:
   победа, разговор, raid, тишина, недоверенные команды/URL и попытка повторить персональные данные.
4. Просмотреть ответы и результат каждой проверки. Replay проверяет всю schema, включая неиспользуемые
   поля, затем scope, worker/параметрические ограничения и hard-safety. Тесты используют fake AI и HTTP transports.
5. Отметить подтверждение качества и активировать. Backend требует `quality_confirmed: true` и тот
   `replay_run_id`, ответы которого были просмотрены. Один лишь флаг `tested` или клиентская metadata не годится.

Replay использует снимок настроек провайдера, отдельный запрос на каждый case, timeout 25 секунд на case
и persistent claim сроком 240 секунд. Одновременная проверка того же channel отвергается. Процесс не держит
SQLite write transaction во время provider call. Отмена, ошибка, истечение claim, изменение config/endpoint
или запуск сессии во время проверки не создают пригодный proof.

Proof включает prompt content hash, config version/fingerprint, provider/model, fingerprint effective endpoint
и версию replay suite. Имена endpoint/модели не доказывают неизменность удалённых весов: это конечная проверка
совместимости и безопасности на synthetic cases, не универсальная гарантия поведения AI.

Смена настроек требует повторной проверки и активации. Start/resume и production analysis проверяют proof;
результат незавершённого analysis не принимается после смены использованных prompt/config/provider.

### API

Все endpoints ниже используют существующую owner access policy:

| Метод и путь после `/api/director/{channel}` | Контракт |
| --- | --- |
| `GET /prompts` | Версии, тексты, replay reports и effective `tested/active` |
| `POST /prompts` | `{prompt_text}` создаёт draft, не вызывает AI |
| `POST /prompts/{id}/tested` | `{}` запускает server-owned replay; `replay_metadata` от клиента отвергается |
| `POST /prompts/{id}/activate` | `{quality_confirmed: true, replay_run_id}` активирует проверенную версию |
| `GET /suggestions` | Последние 100 Suggest plans с решением и сообщениями |
| `POST /suggestions/{id}/approve` | `{messages: [{text}, ...]}` в исходном порядке либо исходные сообщения при отсутствии поля |
| `POST /suggestions/{id}/reject` | Отклонение без выполнения plan |
| `GET /examples` | Одобренные примеры только текущего channel |

Ошибки имеют stable code. В частности: `replay_in_progress`, `replay_config_changed`, `prompt_not_tested`,
`prompt_replay_stale`, `prompt_quality_confirmation_required`, `suggestion_already_reviewed`,
`unsafe_example_text`, `example_storage_full`. Raw provider exceptions в UI не возвращаются.

### Suggest и хранение

Одобрение никогда не создаёт `director_messages`/dispatch job и не вызывает sender. Оно сохраняет отдельный
example, а отклонение только review decision. Повтор одинакового решения идемпотентен; другое решение или
другой payload после сохранения конфликтуют. Чужой channel/не-Suggest plan не принимается.

Пример содержит отредактированные безопасные сообщения и копию ограниченного source context: до 30 chat
сообщений и до 1000 символов каждого Vision/speech текста. Известные usernames из snapshot заменяются на
`Viewer-N` без учёта регистра. Это маскирование известных имён, а не универсальный PII-анонимайзер.
Примеры переживают очистку session evidence; последние пять approved examples своего channel входят в
следующие запросы Director как недоверенный контекст. Лимит сохранённых JSON examples — 10 GiB на channel.
Полный artifact/training storage contract из раздела 12 этим этапом не объявляется завершённым.

## 16. Пульт оператора: ручной режим и заготовки (`Q40b`, `Q35`)

Ручной режим (`app/director_manual.py`) — альтернатива AI-сессии: канал переключается в `manual` только
пока сессия остановлена, AI-планировщик для него не запускается. Отправитель выбирается оператором явно
(включённый lurker этого канала) — без автоподбора «самого давно молчавшего». Каждое сообщение проходит
те же текстовые запреты, что и AI-планы (`_safe_text`: URL, `!команды`, `@упоминания`, код, секреты/PII),
плюс outgoing moderation, и логируется в `director_manual_messages` независимо от исхода. Общая
`emergency_stop_all` ставит `emergency_fence` на все ручные каналы; снятие — только явным `unfence`.
`DUPLICATE_GUARD_SEC` защищает лишь от двойного клика/Enter, не является лимитом темпа отправки.

Q35 добавляет заготовки поверх той же таблицы отправки: `director_manual_presets` — до `PRESET_LIMIT` (9)
текстов на channel, каждый со своей `position`. Заготовки проходят тот же `_safe_text` при создании/правке,
хранятся отдельно от истории отправок и сами по себе не отправляются — оператор кликает заготовку или жмёт
`Alt+1…Alt+9` (по позиции), текст подставляется в поле композера, а отправка остаётся отдельным явным
действием (Enter/кнопка), сохраняя выбор отправителя вручную. `reorder_presets` меняет позиции (и тем
самым — какой хоткей на какую заготовку указывает) одним атомарным списком id; частичный или чужой список
отклоняется как `manual_preset_order_invalid`.

API (owner-only, как остальной Director): `GET/POST /api/director/{channel}/manual/presets`,
`PUT/DELETE /api/director/{channel}/manual/presets/{id}`, `POST .../manual/presets/reorder`. Хоткеи
работают только пока открыта вкладка Режиссёра и канал в ручном режиме (`static/app/20_director.js`).

Replay claims, reviews и examples находятся в основной SQLite DB. Director использует выделенные connections:
общий `database.get_db()` возвращает singleton proxy с no-op `close`, поэтому он не обеспечивает изоляцию
многозапросных транзакций. Revocation при bulk account deletion явно использует transaction connection caller.

UI хранит черновики и confirmation отдельно по channel, не применяет поздние ответы к другой странице,
экранирует owner/model текст и обновляет RU/EN/UA без потери редактируемых сообщений.
## 17. Очередь ручных отправок и лимит темпа (Q36)

Несколько ручных отправок подряд для одного канала не уходят разом: `app/director_manual.py`
держит per-channel `asyncio.Lock` (`_channel_locks`) и время последней фактической отправки
(`_channel_last_dispatch`). Каждый вызов `send()` встаёт в очередь этого канала (FIFO — порядок
постановки в очередь = порядок фактических отправок) и ждёт `SEND_RATE_LIMIT_SEC` (2 c) с момента
предыдущей отправки этого же канала, прежде чем пройти обычные проверки (режим/fence/lurker/
дубль) и модерацию. Разные каналы друг друга не блокируют — у каждого своя очередь и свой таймер.

В отличие от Q34 (случайный разброс времени входа ботов в стрим) здесь темп фиксированный, без
рандомизации: цель — не спам-волна подряд идущих сообщений, а не маскировка бота.

`_channel_pending` считает заявки, стоящие в очереди канала (включая ту, что уже отправляется).
`director_manual.queue_depth(channel)` отдаёт это число, роут `GET /api/director/{channel}/operator/
queue` — панельная обёртка над ним. Композер (`static/app/20_director.js`) во время своей отправки
опрашивает этот роут раз в 300 мс и, если в очереди больше одной заявки, показывает статус
«В очереди канала: N» вместо «Отправляем…» — оператор видит, что реальная задержка не баг, а темп.

Тесты: `tests/test_director_manual.py` (параллельные отправки одного канала разнесены минимум на
`SEND_RATE_LIMIT_SEC` × (N−1), без рандомного довеса; разные каналы не сериализуются друг против
друга; `queue_depth`/роут отдают текущую глубину), `tests/director_page_ui.test.js` (статус очереди
в композере).
## 18. Быстрый ответ из чата (Q37)

Кнопка «↩» на строке живого чата логгера (`chatLogViewer`, `templates/partials/chatlogger.html`,
рендер строк — `_clRenderLines()` в `static/app.js`) вызывает `chatLogQuickReply(channel, username)`
(`static/app/20_director.js`): переключает панель на Режиссёра, выбирает нужный канал (используя уже
загруженный список каналов, если он есть — без лишнего похода в сеть) и, если канал в ручном режиме
(Q40b), подставляет `@username ` в начало композера ручной отправки и ставит туда фокус — одно
действие вместо ручного переключения между экранами чата и отправки.

Если канал не привязан ни к одному боту или он сейчас в режиме «ИИ» — быстрый ответ не переключает
режим сам (это могло бы прервать идущую AI-сессию) и просто показывает тост с объяснением; текст в
композере не трогается. Режиссёр показывает все привязанные каналы, чтобы владелец мог заранее
настроить новый канал; запуск и ручная отправка всё равно требуют подходящего lurker-бота.

Тесты: `tests/director_page_ui.test.js` — переход на уже открытый канал без лишнего запроса статуса,
переход на другой канал в ручном режиме, отказ на ИИ-режиме и на неизвестном канале без изменения
композера.
## 19. История ручных отправок с «Повторить» (Q38)

В журнале ручных отправок (`renderDirectorManualLog()`, `static/app/20_director.js`, данные —
`director_manual_messages` из Q40b) у каждой строки есть кнопка «↻» (`directorManualRepeat`).
Она подставляет текст этой отправки в композер и, если бот-отправитель всё ещё включённый lurker
в этом канале, заново выбирает его в списке отправителей. Если бот с тех пор отключён/сменил роль
(история хранит запись как есть) — подставляется только текст, выбор отправителя оператор делает
сам. Отправка остаётся отдельным явным действием: «Повторить» не отправляет сообщение автоматически.

Идентификатор сообщения передаётся кнопкой через `data-msg-id`, а не литералом текста в `onclick` —
произвольные кавычки/переносы строк в тексте иначе сломали бы HTML-атрибут.

Тесты: `tests/director_page_ui.test.js` — рендер кнопки на каждой строке, повтор с доступным
отправителем переизбирает его, повтор с недоступным отправителем не трогает текущий выбор.
