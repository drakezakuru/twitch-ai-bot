# FILE_ZONES — карта текущих подсистем

> Это навигационная карта, а не система worktree/session-владения. Изменение может затрагивать
> несколько зон, если контракт действительно сквозной. Общие файлы редактируются точечно, а каждый
> завершённый шаг получает focused tests и отдельный локальный commit.

## Формат

Строки `ЗОНА | <имя> | <путь>`. Правила поддерживаются руками — тестов на md-файлы в проекте
нет (`DEC-OWNER-012`, удалены 13.09.2026):

- зона и path существуют;
- один exact path не принадлежит двум зонам;
- старые session/worktree записи запрещены.

Карта намеренно содержит только load-bearing файлы и директории. Полный список исходников не нужен.

## Backend core

ЗОНА | backend-core | app/server.py
ЗОНА | backend-core | app/api_errors.py
ЗОНА | backend-core | app/routes.py
ЗОНА | backend-core | app/account_parser.py
ЗОНА | backend-core | app/database.py
ЗОНА | backend-core | app/security.py
ЗОНА | backend-core | app/backup.py
ЗОНА | backend-core | app/runtime_paths.py

## AI и brain

ЗОНА | ai-brain | app/ai_service.py
ЗОНА | ai-brain | app/brain_routes.py
ЗОНА | ai-brain | app/learning.py
ЗОНА | ai-brain | app/user_memory.py
ЗОНА | ai-brain | app/bot_roles.py
ЗОНА | ai-brain | app/director.py
ЗОНА | ai-brain | app/director_plan.py
ЗОНА | ai-brain | app/director_manual.py
ЗОНА | ai-brain | app/director_review.py
ЗОНА | ai-brain | app/director_routes.py
ЗОНА | ai-brain | app/stream_vision.py
ЗОНА | ai-brain | app/diarization.py
ЗОНА | ai-brain | app/voice_clone.py

## Twitch runtime

ЗОНА | twitch-runtime | app/bot_manager.py
ЗОНА | twitch-runtime | app/irc/
ЗОНА | twitch-runtime | app/chat_analyzer.py
ЗОНА | twitch-runtime | app/eventsub.py
ЗОНА | twitch-runtime | app/twitch_helix.py
ЗОНА | twitch-runtime | app/twitch_oauth.py
ЗОНА | twitch-runtime | app/stream_tools_routes.py
ЗОНА | twitch-runtime | app/chat_logger_routes.py
ЗОНА | twitch-runtime | app/stream_health.py
ЗОНА | twitch-runtime | app/weekly_schedule.py
ЗОНА | twitch-runtime | app/channel_bans.py
ЗОНА | twitch-runtime | app/channel_allowed.py
ЗОНА | twitch-runtime | app/channel_clone_routes.py
ЗОНА | twitch-runtime | app/channel_emotes.py
ЗОНА | twitch-runtime | app/channel_emotes_routes.py
ЗОНА | twitch-runtime | app/viewer_dossier_routes.py
ЗОНА | twitch-runtime | app/bot_fleet.py
ЗОНА | twitch-runtime | app/bot_fleet_routes.py
ЗОНА | twitch-runtime | app/proxy_pool.py
ЗОНА | twitch-runtime | app/proxy_pool_routes.py

## Widgets и media

ЗОНА | widgets-media | widgets/
ЗОНА | widgets-media | app/widget_inventory.py
ЗОНА | widgets-media | app/widget_bus.py
ЗОНА | widgets-media | app/widget_bindings.py
ЗОНА | widgets-media | app/widgets.py
ЗОНА | widgets-media | app/audio_queue.py
ЗОНА | widgets-media | app/donation_integrations.py
ЗОНА | widgets-media | app/moderator_media_routes.py
ЗОНА | widgets-media | app/media_share_routes.py
ЗОНА | widgets-media | app/soundboard_routes.py
ЗОНА | widgets-media | app/soundboard_library.py
ЗОНА | widgets-media | app/song_request_routes.py
ЗОНА | widgets-media | app/streamer_hud_routes.py
ЗОНА | widgets-media | app/tts_mute_state.py

## Moderation и moderator console

ЗОНА | moderation | app/moderation.py
ЗОНА | moderation | app/moderation_routes.py
ЗОНА | moderation | app/moderation_dicts/
ЗОНА | moderation | app/moderator_console_routes.py
ЗОНА | moderation | app/moderator_sound_routes.py
ЗОНА | moderation | app/mod_feed_routes.py

## Panel frontend

ЗОНА | panel-frontend | static/
ЗОНА | panel-frontend | templates/

## Ops и launchers

ЗОНА | ops | run.py
ЗОНА | ops | start.sh
ЗОНА | ops | start.bat
ЗОНА | ops | start_bg.sh
ЗОНА | ops | Dockerfile
ЗОНА | ops | docker-compose.yml
ЗОНА | ops | docker-compose.prod.yml
ЗОНА | ops | requirements.txt
ЗОНА | ops | requirements.lock
ЗОНА | ops | requirements-dev.txt
ЗОНА | ops | requirements-ml.txt
ЗОНА | ops | requirements-qa.txt
ЗОНА | ops | .env.example

## Documentation, QA и tests

ЗОНА | docs-tests | README.md
ЗОНА | docs-tests | AGENTS.md
ЗОНА | docs-tests | PLAN_TODO.md
ЗОНА | docs-tests | FILE_ZONES.md
ЗОНА | docs-tests | docs/
ЗОНА | docs-tests | moderator-site/
ЗОНА | docs-tests | omnivoice/
ЗОНА | docs-tests | voice-live/
ЗОНА | docs-tests | tests/
ЗОНА | docs-tests | scripts/

## Сквозные изменения

При изменении общего контракта можно править несколько зон в одном маленьком commit. Примеры:

- новый owner API: feature router + one-line `include_router` + focused route test;
- Widget Bus scope: publishers, bus, listeners и two-channel tests меняются атомарно;
- новый i18n key: RU/EN/UA + owning template/JS behavior test;
- file move/delete: сначала исправить active links/tests/map, затем переместить файл.

Нельзя использовать эту карту как оправдание для полного overwrite общего файла или для изменения
несвязанной подсистемы «заодно».
