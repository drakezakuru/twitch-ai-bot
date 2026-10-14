# Research: аналоги и решения по виджетам

Исследование выполнено по публичной документации без браузерного gate. Общий вывод: данные, API и биндинги остаются нашими; заимствуются только UX-паттерны.

## Источники и выводы R0.1–R0.6

- **R0.1 — StreamElements Custom Widgets:** https://docs.streamelements.com/overlays/custom-widget — HTML/CSS/JS, CSS-анимации, события и очередь; для goals/counter/timer/chat берём ясную иерархию, крупные значения и короткие enter/exit-анимации.
- **R0.2 — Streamlabs Alert Box / Widget Themes:** https://streamlabs.com/content-hub/post/setting-up-your-streamlabs-alerts — вариации follow/sub/donate, последовательная очередь, медиа и звук; применимо к `recent-events`, `latest-event-card`, `follower-ticker` без замены наших событий.
- **R0.3 — платные пакеты:** OWN3D Pro https://www.own3d.pro/ и Nerd or Die https://nerdordie.com/resources/ — единая визуальная система, читаемая типографика, safe areas, WebM/CSS-анимации и масштабируемый текст задают планку полировки.
- **R0.4 — soundboard UX:** Sound Alerts https://soundalerts.com/, Streamer.bot https://docs.streamer.bot/ и Mix It Up https://wiki.mixitupapp.com/ — плитки звуков, trigger → action, очередь, громкость и cooldown; upload/list/play/bind остаются нашими.
- **R0.5 — polls:** Twitch Polls https://dev.twitch.tv/docs/api/reference/#create-poll и StreamElements polls https://docs.streamelements.com/chatbot/commands/default/poll — 2–5 вариантов, длительность, проценты и финальный результат; источник данных только наш Twitch/custom poll API.
- **R0.6 — GitHub/MIT:** https://github.com/adkostka/spotify-obs-overlay — self-hosted OBS browser source, темы, обложка и обрезка длинного текста; используем идеи, не код без повторной проверки LICENSE.

**R0.7:** ниже дана полная карта 39 публичных виджетов: аналог со ссылкой через список выше, заимствуемый UX, собственные данные/действия и вердикт.

## Таблица решений

| Виджет | Аналог | Что берём | Что остаётся своим | Вердикт |
|---|---|---|---|---|
| tts | StreamElements custom widget | очередь и ясное пустое состояние | TTS API/голоса | MERGE с tts-bot позже |
| animated-bg | OWN3D | уровень полировки и мягкие циклы | типы частиц | KEEP |
| goals | StreamElements goals | крупные цифры, анимированный progress | add_percent/reset | BORROW |
| now-playing | spotify-obs-overlay | обрезка длинного текста, обложка | Last.fm/MPRIS/!np | BORROW |
| sub-goal | StreamElements goals | progress и milestone | increment/set/reset | BORROW |
| schedule | OWN3D | карточки now/next | API расписания | BORROW |
| counter | StreamElements counter | крупная цифра и короткий pulse | произвольные keys | RETIRED (Q12: Д — оверлей; API счётчиков и чат-команды живут) |
| uptime | OWN3D | моноширинный таймер/offline | session API | KEEP |
| follower-ticker | Streamlabs event list | скорость и пауза ленты | channel events | BORROW |
| lower-third | Nerd or Die | безопасные поля и enter/exit | set binding | BORROW |
| mascot | OWN3D | состояния реакции | наши события | MERGE-кандидат с anime-runner |
| anime-runner | OWN3D | бесшовный цикл | наш runner | MERGE-кандидат с mascot |
| chat-highlight | StreamElements chat | enter/exit и переносы | chat data | BORROW |
| chat-roulette | StreamElements custom | wheel easing/empty | viewers API | BORROW |
| combo-counter | StreamElements counter | pulse threshold | анализ одинаковых сообщений | RETIRED (Q14: Д; автотрекинг серий убран) |
| song-request | StreamElements | очередь и empty state | наша очередь | BORROW |
| top-donator-alltime | Streamlabs event list | лидер + период | donations API | MERGED ✅ → `/widget/top-donator?period=alltime` (старый URL жив) |
| top-donator-month | Streamlabs event list | лидер + период | donations API | MERGED ✅ → `?period=month` (старый URL жив) |
| top-donator-day | Streamlabs event list | лидер + период | donations API | MERGED ✅ → `?period=day` (старый URL жив) |
| countdown | StreamElements timer | start/pause/reset states | bindings | KEEP |
| donation-challenge | Streamlabs goals | progress/milestone | multi-provider donations | BORROW |
| clip-moments | Twitch clips | понятная ошибка прав | наш detector/API | KEEP |
| voice-changer | OWN3D | device/offline state | voice integration | RETIRED (Q4: Д — pipeline не используется; URL живёт заглушкой) |
| latest-event-card | Streamlabs Alertbox | вариации типов | event API | MERGED ✅ Wave 4: общая event-модель, карточка своя |
| tts-bot | StreamElements custom | очередь | Golden Voice | MERGE с tts |
| typing-indicator | chat UI pattern | delayed enter/exit | bot generation state | RETIRED (Q26: Д; broadcast typing_indicator убран) |
| tts-chat-overlay | StreamElements chat | строки, fade-out | all/rewards/bot filters | KEEP |
| hype-meter | StreamElements goals | анимированная шкала | chat activity | BORROW |
| subathon-timer | StreamElements timer | milestone pulse | event time additions | KEEP |
| poll-overlay | Twitch Polls | 2–5 choices, percentages | Twitch/custom poll API | RETIRED (Q28: Д; нативные Twitch Polls остались) |
| emoji-leaderboard | StreamElements leaderboard | ранги и empty state | emoji stats | MERGED ✅ Wave 7: общее ядро распознавания, рейтинг свой |
| blur-guard | — | — | уникальная защита | RETIRED (Q36: Д; `/obs/blur-guard` → alias на v2) |
| blur-guard-v2 | — | — | зоны + live blur | KEEP |
| chat-reader | Sound Alerts/TTS queue | очередь и статус | TTS engine | MERGE-кандидат с tts |
| emoji-chat | StreamElements chat | enter/exit | emoji-only filter | MERGED ✅ Wave 7: общее ядро распознавания, лента своя |
| media-share | Streamlabs media | queue/error/moderation states | moderation/limits | BORROW |
| mod-feed | Streamer.bot actions | компактный action feed | moderation decisions | KEEP |
| soundboard | Sound Alerts / Streamer.bot / Mix It Up | плитки, очередь, volume/cooldown | upload/list/play/bind | BORROW |
| recent-events | Streamlabs Alertbox/event list | иконки и enter/exit | follow/sub/donate API | MERGED ✅ Wave 4: общая event-модель, лента своя |

`BORROW` означает только применение визуального/UX-паттерна к собственным данным. Массовая визуальная замена требует отдельной browser/OBS-приёмки, поэтому в этой небраузерной сессии не выполнялась.