# REVIEW_WIDGETS — полный widget/OBS contract review

## Denominator

**41 адресный контракт:** 32 active + 5 retired + 1 alias + 3 legacy parameter URLs.
Дополнительно найден `/widget/moderator-media`: protected moderator output, не входящий в canonical
inventory; это W-B01, а не Track 7 moderator-overlay site.

## Active matrix

| Slug | Route / folder | Preview / canvas | Binding |
|---|---|---|---|
| tts | `/obs/tts` / `tts-raw` | live-dark / 1000×180 | — |
| animated-bg | `/widget/animated-bg` / same | live-dark / 1920×1080 | — |
| goals | `/widget/goals` / same | live-dark / 500×500 | goals |
| now-playing | `/widget/now-playing` / same | live-dark / 560×120 | now_playing |
| sub-goal | `/widget/sub-goal` / same | live-dark / 520×420 | sub_goal |
| schedule | `/widget/schedule` / same | live-dark / 560×500 | — |
| uptime | `/widget/uptime` / `stream-session` | live-dark / 360×70 | — |
| follower-ticker | `/widget/follower-ticker` / same | live-dark / 1920×80 | — |
| lower-third | `/widget/lower-third` / same | live-dark / 520×180 | lower_third |
| mascot | `/widget/mascot` / same | live-dark / 240×240 | — |
| anime-runner | `/widget/anime-runner` / same | live-dark / 1920×1080 | — |
| chat-highlight | `/widget/chat-highlight` / same | live-dark / 640×220 | — |
| chat-roulette | `/widget/chat-roulette` / same | live-dark / 420×460 | — |
| song-request | `/widget/song-request` / same | live-dark / 440×320 | — |
| top-donator | `/widget/top-donator` / same | live-dark / 420×240 | — |
| countdown | `/widget/countdown` / same | live-dark / 700×300 | countdown |
| donation-challenge | `/widget/donation-challenge` / same | live-dark / 560×220 | — |
| clip-moments | `/widget/clip-moments` / same | live-dark / 460×360 | — |
| latest-event-card | `/widget/latest-event-card` / same | live-dark / 440×280 | — |
| tts-bot | `/widget/tts-bot` / same | live-dark / 900×260 | — |
| tts-chat-overlay | `/widget/tts-chat-overlay` / same | representative-dark / 800×240 | — |
| hype-meter | `/widget/hype-meter` / same | live-dark / 340×120 | — |
| subathon-timer | `/widget/subathon-timer` / same | live-dark / 360×150 | — |
| emoji-leaderboard | `/widget/emoji-leaderboard` / same | live-dark / 320×360 | — |
| blur-guard-v2 | `/obs/blur-guard-v2` / same | live-dark / 1920×1080 | — |
| chat-reader | `/widget/chat-reader` / same | live-dark / 800×220 | — |
| emoji-chat | `/widget/emoji-chat` / same | live-dark / 480×420 | — |
| selected-chat | `/widget/selected-chat` / same | live-dark / 560×600 | — |
| media-share | `/widget/media-share` / same | live-dark / 1920×1080 | — |
| mod-feed | `/widget/mod-feed` / same | live-dark / 560×500 | — |
| soundboard | `/widget/soundboard` / same | live-dark / 360×60 | track-specific |
| recent-events | `/widget/recent-events` / same | representative-dark / 480×420 | — |

Canonical values and preview query strings come from `app/widget_inventory.py:137-171`; panel cards
are registry-driven. Binding semantics are in `docs/WIDGET_BINDING_CONTRACTS.md`.

## Compatibility matrix

| Type | URLs | Required behavior |
|---|---|---|
| retired | voice-changer, counter, combo-counter, typing-indicator, poll-overlay | HTTP-live dark explanatory placeholder; no card/folder |
| alias | `/obs/blur-guard` → `/obs/blur-guard-v2` | actual replacement, not placeholder |
| merged | top-donator-alltime/month/day → canonical `?period=` | forced period, existing OBS source remains valid |
| protected exception | `/widget/moderator-media` | exact account+channel+token; no silent removal |

## Runtime verdict

- Strict fake browser smoke: **19/19**, 0 JS errors, 0 HTTP ≥400, 0 error toasts, no mobile overflow.
- Preview URL sweep covered active/compatibility contracts without displayed errors.
- Offline `verify_widget_runtime.js`: **6/6** checked widgets started without errors.
- Strong static/focused widget suites: transport/runtime/preview tests pass; W-B01 закрыт explicit
  protected-output contract, stale runtime assertions заменены behavior tests в C-010.
- Real OBS/CEF, audio device, WebSocket reconnect under OBS sleep and real stream readability were not
  exercised because production credentials/provider calls are prohibited; owner acceptance remains.

## Source/license/CEF review

Repository widgets are project-owned HTML/CSS/JS; no copied third-party code was established by this
review. `docs/RESEARCH_WIDGETS.md` is UX research only and explicitly forbids copying without a fresh
LICENSE check. **Exception:** media-share dynamically loads the YouTube IFrame API; provenance,
privacy/CSP, offline fallback and OBS CEF compatibility remain C-014. For every other contract the
source status is `internal repository implementation`; license distribution policy is repository-level,
not a per-widget third-party license. CEF evidence is fake Chromium/browser only, not real OBS CEF.

## Findings

W-B01 protected moderator-media exception и W-B02 beep duck contract закрыты. W-B03 channel-scoped
Widget Bus, UI-B06 registry i18n/theme и C-014 YouTube provenance/offline behavior имеют owner decision,
но ждут исполнения. C-003 public mutations и C-015 README закрыты. Full metadata и rollback находятся
в `REVIEW_DEAD_CODE.md` / `REVIEW_QUESTIONABLE.md`; канон решений — `OWNER_DECISIONS_2026-09-08.md`.
