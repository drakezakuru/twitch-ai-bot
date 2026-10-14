# REVIEW_RUNTIME — fake-local runtime evidence

> Snapshot: **2026-09-06 UTC**. This record is evidence for the review, not a
> production-readiness claim. All commands below were run in the repository
> virtual environment against the deterministic `local` QA namespace.

## Environment and isolation

- Managed preview configuration: `HOPLITE_PREVIEW_PROFILE=full-qa`,
  `QA_PROFILE_NAME=local`, then `.hoplite/run.sh` starts
  `scripts/run_qa_panel.py` rather than `run.py`.
- The profile is rooted at `data/qa-profiles/local/` and is marked by
  `.qa-profile-root.json` (`twitch-ai-bot-qa-profile`, version 1). Profile-name
  validation rejects traversal, invalid names, and symlinked namespaces.
- The panel runner removes inherited variables whose names indicate credentials,
  disables dotenv, clears panel credentials, points every mutable runtime path
  (database, bot files, locks, voice assets, frames, backups, soundboard) into
  that profile, and uses an unreachable local Ollama endpoint.
- The verified profile fingerprint was
  `7f39ee3f922889f753ba6e82c0b42e87f21df4a50666db6e182340c09d6fc680`.
  It contains three **disabled** fake accounts (`qa_modbot`, `qa_ttsbot`,
  `qa_chatbot`), their three enabled fake channels, three generated WAV fixtures,
  sentinel-only tokens, and zero SQLite foreign-key errors. Disabled accounts
  prevent live Twitch autoconnect.
- Pytest has a separate, stronger isolation boundary: the autouse `tmp_db`
  fixture sends each test to its own `tmp_path/data/bot.db`, resets database
  singletons, and closes registered `aiosqlite` connections. It does not use the
  persistent QA database.

## Reproducible commands and results

### Core dependency boundary (C-007)

- A fresh temporary Python venv installed `requirements.txt`, passed `pip check`,
  and imported `app.server` while `whisper` and `speechbrain` were both absent.
- Launcher/voice/beep focused matrix: **19 passed**. This covers the explicit
  `--ml` manifest contract and degraded core behavior without provider calls.

```bash
.venv/bin/python scripts/qa_profile.py verify --profile local
.venv/bin/python scripts/run_qa_panel.py --profile local --check
```

Both commands passed. The first prints the profile manifest; the second confirmed
the offline runner preparation and removed **0** inherited credential-like
variables in this sandbox.

```bash
.venv/bin/python -m pytest -q \
  tests/test_qa_profile.py tests/test_track6_chatbot_acceptance.py \
  tests/test_bot_logs_cleanup_scope.py tests/test_eventsub_reconnect.py \
  tests/test_chat_display_runtime.py tests/test_p1_bot_page_cards.py \
  tests/test_tts_core_transport.py
```

Result: **39 passed, 0 failed, 4 warnings, 15.01 s**. This focused set covers
the deterministic profile and fake moderator flow (Twitch Helix timeout/slow-mode
calls are monkeypatched), fake chatbot runtime plus panel conversation,
scope-limited log cleanup, EventSub reconnect handling, safe chat-history
rendering, configured-channel UI, and shared TTS transport reconnection.
The four warnings are non-async functions in `test_p1_bot_page_cards.py` marked
with `pytest.mark.asyncio`; they do not fail the run.

Additional focused evidence collected in the same fake-local review:

- EventSub chat/reconnect/dedup/status/raid matrix: **20 passed**. Fake Helix
  payload assertions prove the required `broadcaster_user_id + user_id` chat
  condition, chat-flag subscription rebuild, and old-socket delivery until the
  replacement welcome without any Twitch connection.
- strict browser smoke: **19/19** scenarios, **0** JavaScript errors, **0** HTTP
  responses `>=400`, **0** error toasts and no mobile horizontal overflow;
- widget preview/compatibility sweep completed without an error in its emitted
  route results;
- `scripts/verify_widget_runtime.js`: **6/6** selected widgets started without
  an uncaught runtime error;
- moderator/media/widget transport group: **116 passed, 3 skipped**;
- `node --test tests/tts_core_transport.test.js`: **2 passed**;
- `python -m compileall -q app scripts run.py`: passed;
- markdown link audit: **34 checked, 0 broken** in the initial snapshot.

These are local Chromium/offline results, not real OBS CEF or provider evidence.

## Resolved stale widget guards

```bash
.venv/bin/python -m pytest -q tests/test_widgets_folder.py
```

Original result: **11 passed, 6 failed, 7.95 s**. Five parameterized route assertions
(`uptime`, `lower-third`, `mascot`, `countdown`, `donation-challenge`) and the
live-reload assertion compare an original `<html ...>`/`<head ...>` substring
literally. The current widget loader deliberately injects
`data-widget-layout` and `data-widget-root` attributes into the opening
`<html>` tag for bounded runtime appearance, so the route still returns HTTP 200
but the stale byte-for-byte marker expectation failed. The existing bounded-layout
contract tests separately proved the injected runtime contract; on 06.09 the
folder guard was changed to probe post-loader HTML and to assert preservation of
the unmodified body plus injected metadata/assets. The related selected-chat
guard now accepts its shared `ChatMessageCore.apiBase()` implementation instead
of requiring a duplicate private variable. Both focused files pass.

## Available artifacts and unexecuted runtime checks

- `scripts/qa_preview_sweep.py`, `scripts/browser_smoke.py` and
  `scripts/verify_widget_runtime.js` supplied the audit results above. Existing
  unrelated `logs/smoke-*.png` remain historical artifacts and are not presented
  as current screenshots.
- No screenshots or videos were committed. Runtime evidence is textual because
  this audit does not change a UI surface; historical images were not reused.

## Deliberate limits

- The full `pytest tests/` suite was **not run**. Repository policy requires
  focused tests by default. ML tests require the separately installed
  Whisper/Torch stack and would not replace targeted runtime evidence.
- ML-heavy tests (`test_diarization.py`, `test_stream_vision.py`,
  `test_stream_source_custom.py`, `test_s12_voice_clone_f5.py`) were not run for
  the same policy and dependency-cost reason.
- No real Twitch/EventSub, donation provider, AI provider, OAuth token, OBS
  WebSocket, camera/microphone, or live OBS Browser Source was contacted. Review
  policy prohibits production credentials/calls; external behavior is covered
  only through fake profiles, monkeypatches, stubs, and offline endpoints.
- Fresh fake Chromium automation was performed, but no real/manual OBS acceptance.
  A real OBS scene/hotkey/audio/device check remains owner-operated acceptance
  work; it cannot be inferred from Chromium or historical screenshots.
