# REVIEW_KEEP — D: retained ядро и защищаемые контракты

> D означает «оставить в текущем review», не «без дефектов». Mixed files остаются D/C на path-level,
> а конкретные broken symbols перечислены в `REVIEW_DEAD_CODE.md`.

## Strong runtime/test evidence

| Domain | Retained contract | Evidence |
|---|---|---|
| Fake isolation | `scripts/run_qa_panel.py` очищает secret-like env, валидирует profile и не auto-connect'ит disabled bots. | `REVIEW_RUNTIME.md`; QA profile verify/check. |
| Widget URLs | 32 active folders/routes/previews, 5 retired placeholders, blur alias и 3 top-donator legacy URLs сохраняются. | strict 19/19 browser smoke, preview sweep, `verify_widget_runtime.js`, inventory tests. |
| TTS transport | Общая очередь с отдельными `tts`, `tts-bot`, `chat-reader`, `tts-chat-overlay` modes/URLs. | Node transport 2 passed; focused widget transport suite. |
| Scoped widgets | Goals/counters/sub-goal/countdown/now-playing/lower-third/clips/donations/subathon/mascot/highlight/song/media/roulette используют exact account+channel HTTP scope. | Track 6 focused suites в `PLAN_TODO.md`; fake acceptance. |
| Database connection | WAL, busy timeout, foreign keys, synchronous NORMAL. | `app/database.py:1433-1438`; DB-focused tests. |
| Token serialization | Account API маскирует access/refresh tokens. | `app/routes.py:186-195`; security focused suite. |
| Owner voice gate | Enabled exact scope и fail-closed speaker verification. | `app/voice_control.py:59-74,179-193`; focused voice tests. |
| Event dedup | EventSub IDs bounded to 2048. | `app/eventsub.py:149-170`; reconnect tests. |
| Markdown links | Active-doc link checker retained. | `scripts/check_md_links.py:28-45`; 34/38-link runs, 0 broken. |

## Medium static + focused evidence

- `app/ai_service.py:254-264`: per-account provider selection и отдельная custom vision model.
- `app/user_memory.py:65,529`: per-account memory и account/channel/user history; isolation test.
- `app/chat_analyzer.py:238,2098`: scoped trackers и role gate before generation/send.
- `app/moderation.py:511,549`: dictionary/mode/outgoing gate и persisted audit trail.
- `sentiment`, `word_stats`, `conversation_threads`, `multi_bot_chat`, `proactive_questions`,
  `affinity_rules`: direct focused tests, конкретных дефектов в pass не найдено.
- `scripts/qa_preview_sweep.py:47-77`: HTTP gate active/retired/alias/legacy widgets.
- `tests/test_p5_app_split.py:51-69`: actual Node syntax checks, включая concatenated global scope.
- Archived docs остаются historical evidence по правилу `AGENTS.md`; они не current truth.

## Compatibility surfaces protected from cleanup

- Все public OBS Browser Source URLs из `app/widget_inventory.py`, включая retired/alias/legacy.
- Legacy DB rows/columns и additive migration paths до явного owner decision.
- Callback/webhook/admin/compatibility routes нельзя объявлять dead из-за отсутствия panel `fetch()`.
- `/widget/moderator-media` — подтверждённый владельцем protected per-channel output вне public inventory; URL сохраняется, reusable token-bearing preview запрещён.
