# Widget data manifest

**Scope:** all active contracts in `app.widget_inventory.WIDGET_INVENTORY`.
SQLite and existing settings APIs remain the source of truth for configuration,
state, queues, IDs and artifact references. Soundboard artifacts are stored at
`data/widgets/soundboard/`; recognized legacy files in `data/soundboard/` are
read compatibly and atomically moved into the new location on Soundboard schema
setup. No API or OBS URL changes are required.

## Classes and retention policy

| Class | Canonical location | Retention / deletion | Backup |
|---|---|---|---|
| Settings/config | SQLite, via owning settings API | Until owner changes or removes it through the owning API | Included through `bot.db` |
| Durable state/queue | SQLite, including artifact IDs/references | Feature workflow consumes or clears it; never delete files to alter it | Included through `bot.db` |
| Uploaded media | Dedicated media root; `data/widgets/<slug>/` only for widget artifacts | Owner delete, or documented conservative orphan cleanup after grace period | Future backup: durable referenced artifacts only |
| Cache/temp | Process memory or OS temporary files | TTL/request lifetime; safe to purge on restart | **Never included** |
| Secrets | Protected environment or credential/settings storage | Rotate/revoke through owning credential flow | Never stored or backed up as widget artifacts |

The existing backup archives `bot.db` (and optionally `.env` and small
`data/bots/` files), not widget media. Any future artifact backup must exclude
cache/temp, dot-temporary uploads, unreferenced orphans and secrets. Restore
must restore SQLite first and report a missing artifact rather than invent a
reference or silently discard it.

## Active widget classification

**SQLite/API** means the current SQLite-backed owning API is canonical.
**memory/OS temp** is reconstructible and non-backup. “No secret” means no
widget-owned secret; provider credentials remain outside widget folders.

| Active widget | Settings/config | Durable state / queue | Uploaded media | Cache / temp | Secrets |
|---|---|---|---|---|---|
| `tts` | SQLite/API TTS policy | SQLite/API queue metadata | — | memory/OS generated-audio temp | no secret |
| `animated-bg` | URL/design parameters | — | — | browser animation memory | no secret |
| `goals` | SQLite/API goal definitions | SQLite/API progress | — | endpoint memory cache | no secret |
| `now-playing` | SQLite/API source/settings | SQLite/API current track | remote cover/reference only | endpoint memory cache | provider credential outside widget folder |
| `sub-goal` | SQLite/API target/settings | SQLite/API scoped progress | — | endpoint memory cache | EventSub credential outside widget folder |
| `schedule` | SQLite/API schedule blocks | SQLite/API current/next selection | — | browser render memory | no secret |
| `uptime` | SQLite/API stream lifecycle settings | SQLite/API session state | — | browser timer memory | no secret |
| `follower-ticker` | SQLite/API display settings | SQLite/API recent events | — | browser ticker memory | EventSub credential outside widget folder |
| `lower-third` | SQLite/API presentation config | SQLite/API visible content/state | — | endpoint memory cache | no secret |
| `mascot` | SQLite/API preset/config | SQLite/API scoped reaction state | repository assets, not uploads | browser animation memory | no secret |
| `anime-runner` | SQLite/API character settings | — | repository assets, not uploads | browser animation memory | no secret |
| `chat-highlight` | SQLite/API display settings | SQLite/API selected message | — | endpoint memory cache | no secret |
| `chat-roulette` | SQLite/API scoped settings | SQLite/API participants/winner | — | spin animation memory | no secret |
| `song-request` | SQLite/API request policy | SQLite/API moderated request queue | remote URL/reference only | endpoint memory cache | no secret |
| `top-donator` | SQLite/API period/display settings | SQLite/API donation records | — | endpoint memory cache | provider credential outside widget folder |
| `countdown` | SQLite/API timer configuration | SQLite/API running timer state | — | browser countdown memory | no secret |
| `donation-challenge` | SQLite/API challenge configuration | SQLite/API scoped challenge/funds state | — | endpoint memory cache | provider/webhook secrets outside widget folder |
| `clip-moments` | SQLite/API clip settings | SQLite/API scoped detected moments | remote Twitch references only | endpoint memory cache | Twitch credential outside widget folder |
| `latest-event-card` | SQLite/API display settings | SQLite/API shared latest event | — | browser render memory | EventSub/provider credentials outside widget folder |
| `tts-bot` | SQLite/API TTS bot settings | SQLite/API queue metadata | — | memory/OS generated-audio temp | no secret |
| `tts-chat-overlay` | SQLite/API overlay settings | SQLite/API queue/display state | — | browser fade timer memory | no secret |
| `hype-meter` | SQLite/API display settings | SQLite/API chat activity data | — | WebSocket/browser meter memory | no secret |
| `subathon-timer` | SQLite/API tariffs/settings | SQLite/API scoped timer state | — | endpoint memory cache | provider/EventSub credentials outside widget folder |
| `emoji-leaderboard` | SQLite/API display settings | SQLite/API emoji statistics | — | browser render memory | no secret |
| `blur-guard-v2` | SQLite/API zones/config | SQLite/API enabled state | `data/blur-guard/` images | browser/endpoint cache | no secret |
| `chat-reader` | SQLite/API reader policy | SQLite/API queue metadata | — | memory/OS generated-audio temp | no secret |
| `emoji-chat` | SQLite/API display settings | SQLite/API emoji event data | — | WebSocket/browser memory | no secret |
| `selected-chat` | SQLite/API trusted-user/display settings | SQLite/API selected history | — | WebSocket/browser memory | no secret |
| `media-share` | SQLite/API moderation settings | SQLite/API moderated media queue | `data/moderator-media/` when uploaded | player/browser temp | no secret |
| `mod-feed` | SQLite/API filters/settings | SQLite/API moderation events | — | endpoint/browser memory | no secret |
| `soundboard` | SQLite/API track metadata/settings | SQLite/API tracks and playback events | `data/widgets/soundboard/`; legacy `data/soundboard/` read/move compatible | `.upload-*` and player memory | no secret |
| `recent-events` | SQLite/API display settings | SQLite/API shared event feed | — | browser/endpoint memory | EventSub/provider credentials outside widget folder |

## Protected moderator output

`/widget/moderator-media` is intentionally outside the reusable widget inventory. Its owner-only
control surface generates an exact `account_id + channel` Browser Source URL containing a rotated
OBS token, so publishing a reusable panel preview URL would bypass its capability boundary. Its
configuration, queue and approved-library references live in SQLite; uploaded files live under
`data/moderator-media/<account>/<channel-hash>/`. The token is stored only as a SHA-256 hash and is
required by the output page, state, completion and file APIs. The route remains part of the public
overlay denominator through `PROTECTED_WIDGET_OUTPUTS`.

## Operational safety invariants

1. A widget folder is for artifacts only: no secrets, SQLite copies, queue/config
   snapshots or replacement source of truth.
2. Cache/temp is never backed up or restored; a restart may clear it safely.
3. Owner media deletion validates scope, removes the durable reference and artifact
   together, and reports a missing file honestly.
4. Orphan cleanup deletes only proved-unreferenced artifacts after a grace period;
   it never scans or deletes secrets.
5. A future migration uses same-filesystem temporary output and atomic rename,
   commits the SQLite reference only after the artifact is durable, preserves the
   legacy file until commit succeeds, and rolls back the new file/reference on
   failure.
