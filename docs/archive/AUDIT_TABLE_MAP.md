# AUDIT_TABLE_MAP.md — §5 карта таблиц: владелец / скоуп / кто пишет / вердикт

> Сгенерировано 30.08 (сессия main) по запросу владельца: «ничего не
> перемешивается?». Метод: скан всех CREATE TABLE IF NOT EXISTS (96) по
> app/ + widgets/, writers = INSERT/UPDATE/DELETE/REPLACE, скоуп по наличию
> account_id / channel в схеме. Пометки «ок с пометкой» — почистить при
> удалении бота или при следующей миграции; «МЁРТВАЯ» — 0 обращений в коде.

## Главные находки

1. **clip_moments — схемы РАЗНЫЕ** (widgets.py vs database.py: nullable
   channel + text timestamp vs not null + timestamp) — единственный реальный
   дубль-конфликт; унифицировать, дубль убрать. Остальные 8 дублей — SAME,
   безвредны, но лишние.
2. **6 мёртвых таблиц** (0 чтений/записей): personality_shift_state,
   shared_chatter_facts, raid_context_log, streamer_events, streamer_stats,
   voice_speakers — кандидат на удаление (проверить строки в живой bot.db).
3. **Удаление бота оставляет мусор** в 10+ таблицах без FK (chat_log ок —
   намеренно; moderation_learn/pending, streamer_notes, replay_sessions,
   bot_topic_log — нужен cleanup в руте удаления бота).
4. **FK без CASCADE опасно**: bot_corrections, stream_reports имеют FK
   account_id без ON DELETE CASCADE — DELETE бота с детьми уронит
   FOREIGN KEY constraint failed (проверить реальный кейс удаления).
   ❌ ПЕРЕСМОТРЕНО (30.08, PRAGMA foreign_key_list живой БД): реального FK
   на этих таблицах НЕТ — это просто колонки; риск был только мусор-строки.
5. **Две таблицы фидбека живые и разные**: ai_feedback (👍/👎 ответов,
   routes/ab_dashboard) и bot_response_feedback (качество ответов,
   ai_quality_db) — дублей записи нет.
6. **channel-формат**: streamer_lore/learning/summarizer нормализуют
   (lower, без #); widgets-таблицы хранят как пишут из UI. Единый помощник
   _normalize_channel разнести в общий модуль и применять при записи.

## Таблица (96)

| таблица | скоуп | кто пишет | дубли схем | вердикт | заметка |
|---|---|---|---|---|---|
| accounts | global/panel | пишет: moderation_routes, role_routes, routes, server | схемы: 1 файл(ов) | ok | центральная; пишет много модулей (roles/moderation/server) — ожидаемо |
| action_log | global/panel | пишет: routes | схемы: 1 файл(ов) | ok |  |
| ai_feedback | account+channel | пишет: routes | схемы: 1 файл(ов) | ok | живая: 👍/👎 на ответы бота (routes, ab_dashboard) |
| anime_runner_state | global/panel | пишет: database, widgets | схемы: 1 файл(ов) | ok |  |
| banlist | account | пишет: routes | схемы: 1 файл(ов) | ok |  |
| banned_topics | account | пишет: ai_quality_db | схемы: 1 файл(ов) | ok |  |
| blur_guard_feedback | global/panel | пишет: blur_guard | схемы: 1 файл(ов) | ok |  |
| blur_guard_rules | global/panel | пишет: blur_guard | схемы: 1 файл(ов) | ok |  |
| blur_guard_settings | global/panel | пишет: blur_guard | схемы: 1 файл(ов) | ok |  |
| bot_affinity | account+channel | пишет: affinity_rules, bootstrap, database, routes | схемы: 1 файл(ов) | ok |  |
| bot_affinity_history | account+channel | пишет: affinity_rules, routes | схемы: 1 файл(ов) | ok |  |
| bot_attention_config | account | пишет: routes | схемы: 1 файл(ов) | ok |  |
| bot_conversation_history | account+channel | пишет: chat_analyzer | схемы: 1 файл(ов) | ok |  |
| bot_corrections | account+channel | пишет: routes | схемы: 1 файл(ов) | ok | FK есть, но БЕЗ CASCADE — удаление бота с коррекциями уронит DELETE? проверить: sqlite с foreign_keys=ON бросит ошибку → нужен CASCADE или cleanup |
| bot_engagement | account+channel | пишет: engagement | схемы: 1 файл(ов) | ok |  |
| bot_logs | account+channel | пишет: bot_logs | схемы: 1 файл(ов) | ok |  |
| bot_response_feedback | global/panel | пишет: ai_quality_db | схемы: 1 файл(ов) | ok | живая: фидбек качества ответов (ai_quality_db) — назначение другое, дублей записи нет |
| bot_streamer_affinity | account | пишет: routes | схемы: 1 файл(ов) | ok |  |
| bot_topic_log | account+channel | пишет: ai_quality_db | схемы: 1 файл(ов) | ок с пометкой | без FK — cleanup при удалении бота |
| channel_overrides | account+channel | пишет: brain_routes, routes | схемы: 1 файл(ов) | ok | пишут brain_routes (summarizer per-channel §2.3) и routes (overrides UI) — два писателя, НО разные ключи внутри JSON; следить |
| channels | account | пишет: routes | схемы: 1 файл(ов) | ok |  |
| chat_highlight | global/panel | пишет: database, widgets | схемы: 1 файл(ов) | ok |  |
| chat_log | account+channel | пишет: bootstrap, routes, server | схемы: 1 файл(ов) | ok | без FK намеренно: логи переживают удаление бота; чистить ретеншеном |
| chat_reader_settings | account | пишет: widgets | схемы: 1 файл(ов) | ok |  |
| chat_roulette | global/panel | пишет: database, widgets | схемы: 1 файл(ов) | ok |  |
| chat_users | account+channel | пишет: chat_analyzer, routes | схемы: 1 файл(ов) | ok | память о юзерах кросс-ботовая, чистка ретеншеном |
| clip_moments | account+channel | пишет: routes | схемы: 2 файл(ов) | ЧИНИТЬ | СХЕМА РАЗНАЯ: widgets.py `channel text default ''`+`timestamp text` vs database.py `not null`+`timestamp timestamp` — унифицировать на вариант database.py, дубль из widgets.py убрать |
| combo_counter | global/panel | пишет: database, widgets | схемы: 1 файл(ов) | ok |  |
| countdown_timer | global/panel | пишет: widgets | схемы: 1 файл(ов) | ok |  |
| counters | global/panel | пишет: database, widgets | схемы: 1 файл(ов) | ok |  |
| custom_behavior_presets | account | пишет: routes | схемы: 1 файл(ов) | ok |  |
| custom_poll | global/panel | пишет: widgets | схемы: 1 файл(ов) | ok |  |
| custom_providers | global/panel | пишет: routes | схемы: 1 файл(ов) | ok |  |
| donation_challenges | global/panel | пишет: donation_integrations, widgets | схемы: 1 файл(ов) | ok |  |
| donation_goal_sync | global/panel | пишет: donation_integrations, widgets | схемы: 1 файл(ов) | ok |  |
| donation_integration_settings | global/panel | пишет: widgets | схемы: 1 файл(ов) | ok |  |
| donation_integrations | global/panel | пишет: widgets | схемы: 1 файл(ов) | ok |  |
| donations | global/panel | пишет: widgets | схемы: 1 файл(ов) | ok |  |
| emoji_stats | global/panel | пишет: widgets | схемы: 1 файл(ов) | ok |  |
| event_responses | account | пишет: routes | схемы: 1 файл(ов) | ok |  |
| latest_event_card_settings | global/panel | пишет: widgets | схемы: 1 файл(ов) | ok |  |
| learning_suggestions | account+channel | пишет: learning | схемы: 1 файл(ов) | ok |  |
| lower_third | global/panel | пишет: database, widgets | схемы: 1 файл(ов) | ok |  |
| mascot_state | global/panel | пишет: database, widgets | схемы: 1 файл(ов) | ok |  |
| moderation_events | account+channel | пишет: moderation, routes | схемы: 1 файл(ов) | ok |  |
| moderation_learn | account | пишет: moderation | схемы: 1 файл(ов) | ок с пометкой | без FK — при удалении бота остаются строки обучения; добавить cleanup в удаление бота |
| moderation_pending | account+channel | пишет: moderation | схемы: 1 файл(ов) | ок с пометкой | без FK —孤儿 вопросы при удалении бота; cleanup при удалении |
| moderation_rules | account+channel | пишет: routes | схемы: 1 файл(ов) | ok |  |
| now_playing | global/panel | пишет: database, widgets | схемы: 2 файл(ов) | ok |  |
| now_playing_settings | global/panel | пишет: widgets | схемы: 1 файл(ов) | ok |  |
| pattern_variants | global/panel | пишет: ai_quality_db | схемы: 1 файл(ов) | ok |  |
| patterns | account | пишет: routes | схемы: 1 файл(ов) | ok |  |
| personality_shift_state | account+channel | пишет: — | схемы: 1 файл(ов) | МЁРТВАЯ | в коде 0 чтений/записей — shift хранится в settings; удалить (проверив строки в живой БД) |
| personas | account | пишет: routes | схемы: 1 файл(ов) | ok |  |
| quick_phrases | account | пишет: routes | схемы: 1 файл(ов) | ok |  |
| raid_context_log | account | пишет: — | схемы: 1 файл(ов) | МЁРТВАЯ | 0 обращений — кандидат на удаление |
| recent_events | global/panel | пишет: widgets | схемы: 1 файл(ов) | ok |  |
| replay_events | global/panel | пишет: replay_debug | схемы: 1 файл(ов) | ok |  |
| replay_sessions | account+channel | пишет: replay_debug | схемы: 1 файл(ов) | ок с пометкой | без FK — cleanup при удалении бота |
| schedule_blocks | global/panel | пишет: widgets | схемы: 2 файл(ов) | ok |  |
| scheduled_messages | account+channel | пишет: routes | схемы: 1 файл(ов) | ok |  |
| settings | global/panel | пишет: database, routes | схемы: 1 файл(ов) | ok | общий key-value; namespace-конфликты глобальных vs per-bot ключей проверены в §4.4, расширить при появлении новых |
| shared_chatter_facts | account+channel | пишет: — | схемы: 1 файл(ов) | МЁРТВАЯ | 0 обращений — кандидат на удаление |
| shared_user_facts | account | пишет: shared_user_facts | схемы: 1 файл(ов) | ok |  |
| song_request_queue | global/panel | пишет: widgets | схемы: 1 файл(ов) | ok |  |
| song_request_settings | global/panel | пишет: database, widgets | схемы: 1 файл(ов) | ok |  |
| sr_priority_users | global/panel | пишет: widgets | схемы: 1 файл(ов) | ok |  |
| stream_goals | global/panel | пишет: widgets | схемы: 2 файл(ов) | ok |  |
| stream_reports | account+channel | пишет: routes | схемы: 1 файл(ов) | ок с пометкой | FK без CASCADE: DELETE бота упадёт при наличии отчётов — добавить ON DELETE CASCADE |
| stream_session | global/panel | пишет: database, widgets | схемы: 1 файл(ов) | ok |  |
| streamer_events | account+channel | пишет: — | схемы: 1 файл(ов) | МЁРТВАЯ | 0 обращений — кандидат на удаление |
| streamer_face | account+channel | пишет: streamer_profile | схемы: 1 файл(ов) | ok | аналогично streamer_profile: глобальный артефакт, не каскадить |
| streamer_kb | account | пишет: ai_quality_db, brain_routes | схемы: 1 файл(ов) | ok | пишут brain_routes (импорт KB) и ai_quality_db (add) — один домен KB, ок |
| streamer_lore | account+channel | пишет: streamer_lore | схемы: 1 файл(ов) | ok |  |
| streamer_notes | account+channel | пишет: streamer_notify | схемы: 1 файл(ов) | ок с пометкой | без FK — cleanup при удалении бота |
| streamer_profile | account+channel | пишет: streamer_profile | схемы: 1 файл(ов) | ok | без FK — удаление бота оставляет строки профиля (глобальный профиль должен переживать бота) — это ОСОЗНАННО, пометить в доке |
| streamer_stats | account | пишет: — | схемы: 1 файл(ов) | МЁРТВАЯ | 0 обращений — кандидат на удаление |
| style_examples | account+channel | пишет: ai_quality_db | схемы: 1 файл(ов) | ok |  |
| sub_goal | global/panel | пишет: database, widgets | схемы: 2 файл(ов) | ok |  |
| subathon_timer | global/panel | пишет: widgets | схемы: 1 файл(ов) | ok |  |
| summarizer_checkpoints | global/panel | пишет: summarizer | схемы: 2 файл(ов) | ok |  |
| summarizer_live | account+channel | пишет: summarizer | схемы: 2 файл(ов) | ok |  |
| summarizer_runs | account+channel | пишет: summarizer | схемы: 2 файл(ов) | ok |  |
| top_donator_settings | global/panel | пишет: widgets | схемы: 1 файл(ов) | ok |  |
| triggers | account | пишет: chat_analyzer, routes | схемы: 1 файл(ов) | ok | routes (CRUD) + chat_analyzer (usage-счётчики) — ок |
| tts_bot_config | account | пишет: routes, widgets | схемы: 1 файл(ов) | ok | routes (per-bot UI) + widgets (дефолт) — ок |
| tts_duck_settings | global/panel | пишет: routes | схемы: 1 файл(ов) | ok |  |
| tts_settings | global/panel | пишет: database, routes | схемы: 1 файл(ов) | ok |  |
| tts_voice_presets | global/panel | пишет: database | схемы: 1 файл(ов) | ok |  |
| user_memory | account | пишет: user_memory | схемы: 1 файл(ов) | ok |  |
| user_message_history | account+channel | пишет: routes, user_memory | схемы: 1 файл(ов) | ok | routes + user_memory — один домен памяти |
| voice_clones | global/panel | пишет: routes | схемы: 1 файл(ов) | ok |  |
| voice_speakers | account+channel | пишет: — | схемы: 1 файл(ов) | МЁРТВАЯ | 0 обращений — кандидат на удаление |
| widget_bindings | global/panel | пишет: widget_bindings, widgets | схемы: 1 файл(ов) | ok | widget_bindings (UI) + widgets (пресеты) — один домен, ок |
| widget_titles | global/panel | пишет: database, widgets | схемы: 2 файл(ов) | ok |  |
| word_filter | account+channel | пишет: routes | схемы: 1 файл(ов) | ok |  |
