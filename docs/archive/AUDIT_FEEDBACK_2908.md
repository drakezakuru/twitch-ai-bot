# AUDIT_FEEDBACK_2908 — аудит готовности по фактическому коду (30.08.2026)

> §1 из PLAN_FEEDBACK_2908 (перенесён из PLAN_ALL_IN_ONE): «функция / статус /
> файлы / API / тест». Проверка по коду и тестам, не по наличию кнопки.
> 1204 автотеста, 111 тестовых файлов. Дата аудита — 30.08.2026.

## Сводная таблица

| Функция | Статус | Файлы | API | Тест |
|---|---|---|---|---|
| **Панель / каркас** | | | | |
| i18n ru/en/ua (ключи + паритет) | ✅ | static/app.js (LANGS), data-i18n | — | ручн. |
| Тумблеры .toggle вместо чекбоксов | ✅ | app.js (uiToggle/setToggle), partials | — | ручн. |
| Сворачиваемые карточки (localStorage) | ✅ | app.js (initCollapsibleCards), app.css | — | ручн. |
| Пустые состояния с пояснениями | ✅ | app.js (logsEmptyHtml + ключи) | — | ручн. |
| **Миграции БД** | | | | |
| Схема виджетов на старте панели | ✅ | app/widgets.py (ensure_widgets_schema), app/database.py | — | test_p0_widget_migrations |
| Профиль стримера per-channel (PK) | ✅ | app/database.py (_migrate_streamer_channel) | — | test_s5_streamer_channel |
| CHECK 'xtts' в tts_bot_config | ✅ | app/database.py (_migrate_tts_bot_config_xtts) | — | test_s12_voice_clone_f5 |
| **Боты / чат** | | | | |
| Мульти-бот, старт/стоп, каналы | ✅ | app/bot_manager.py, app/server.py | /api/accounts, /api/bots/* | test_onboarding и др. |
| «Когда бот отвечает»: режимы/окно/кулдаун | ✅ | app/chat_analyzer.py, bot_attention_config | /api/accounts/{id}/attention-config | test_s7_reply_settings |
| Не перебивать стримера (guard) | ✅ | app/chat_analyzer.py (_last_streamer_msg, _generate_and_send) | attention-config | test_s7_reply_settings |
| Не озвучивать каждое сообщение (%) | ✅ | app/chat_analyzer.py (_tts_should_speak) | attention-config | test_s7_reply_settings |
| Упоминания toggle | ✅ | app/chat_analyzer.py (mention_ok) | attention-config | test_s7_reply_settings |
| Пер-канальные overrides характера | ✅ | app/chat_analyzer.py (_merged_settings), channel_overrides | /api/accounts/{id}/channel-overrides | существующие |
| Характер (слайдеры) + свои пресеты | ✅ | app/chat_analyzer.py, custom_behavior_presets | /api/accounts/{id}/persona, /behavior-presets | существующие |
| Профиль стримера: глобально + канал + fallback | ✅ | app/streamer_profile.py (get_*_resolved), Настройки UI | /api/streamer-profile?channel=, /resolve | test_s5_streamer_channel, test_s5_profile_prompt_injection |
| Профиль → инъекция в промпт | ✅ | app/chat_analyzer.py (_load_streamer_profile_block) | — | test_s5_profile_prompt_injection |
| База знаний стримера (kb) + channel | ✅ | app/ai_quality_db.py (list/add_kb) | /api/accounts/{id}/kb | test_s5_streamer_channel |
| **TTS** | | | | |
| Per-bot TTS (наследование глобального) | ✅ | app/tts_engine.py (_get_tts_config) | /api/accounts/{id}/tts-config | test_s6_tts_per_bot |
| Голоса провайдера в селекте + клоны | ✅ | static/app.js (fillBotTTSVoiceOptions) | /api/tts/voices, /api/voice-clones | ручн. |
| Статус последнего синтеза + причина | ✅ | app/tts_engine.py (bot_logs error), /tts-last | /api/accounts/{id}/tts-last, /tts-test | ручн. |
| TTS test голосом бота | ✅ | routes, chat 🔊 | /api/accounts/{id}/tts-test | ручн. |
| Widget Audio Bus (duck/pause) | ✅ | app/widget_bus.py, widgets/_shared/widget-bus-client.js | ws widget_bus | test_widget_bus |
| Авто-молчание по событиям (durations) | ✅ | routes (_ensure_duck_settings) | /api/tts/duck-settings | test_tts_duck_settings |
| **Voice clones** | | | | |
| XTTS/Coqui локально (zero-shot) | ✅ | app/tts_engine.py (XTTSProvider) | /api/voice-clones, preview | ручн. |
| F5-TTS локально | ✅ | app/tts_engine.py (F5TTSProvider), tts_clone_engine | preview | test_s12_voice_clone_f5 |
| ElevenLabs Voice Clone API | ✅ | routes (voices/add) | /api/voice-clones | ручн. |
| Валидация sample (формат/размер) | ✅ | app/voice_clone.py (save_clone_sample) | — | — |
| Consent-предупреждение | ✅ | templates/partials/bots.html (§12.2) | — | — |
| **Виджеты (OBS)** | | | | |
| Все виджеты отдаются как страницы | ✅ | widgets/*/index.html, app/widgets.py (роуты) | /widget/* | test_widget_* |
| Биндинги: чат/eventsub/hotkey | ✅ | app/widget_bindings.py | /api/widgets/bindings[/hotkey] | test_s3_hotkey_bindings |
| Донаты всех платформ → топ/челленджи | ✅ | app/donation_integrations.py, widgets.on_donation_received | webhook | test_s3_donation_hook |
| Цели: проценты + анимация «разлёта» | ✅ | widgets/goals/index.html (celebrate) | /api/widgets/goals | ручн. |
| Админ-формы для всех виджетов (§24) | ✅ | templates/partials/widgets.html, app.js (wa2*) | /api/widgets/* | ручн. |
| Emoji Chat / TTS-оверлей / Typing / Chat Reader | ✅ | widgets/{emoji-chat,tts-chat-overlay,typing-indicator,chat-reader} | — | test_chat_reader |
| **Модерация / аналитика** | | | | |
| Модерация: правила/события/политики | ✅ | app/moderation*.py | /api/accounts/{id}/moderation/* | test_moderation |
| Статистика + CSV-экспорт с фильтрами | ✅ | routes (/api/chat-log/export.csv) | — | test_s7_stats_csv_export |
| **Эксплуатация** | | | | |
| Резервное копирование (auto + zip/restore) | ✅ | app/backup.py, app/maintenance.py | — | test_backup, test_ops_* |
| Миграция легаси-данных | ✅ | scripts/migrate_legacy_data.py | — | ручн. (dry-run) |
| Логи ботов с бейджем ника | ✅ | app/bot_logs.py, renderLogLine | /api/bot-logs | test_p2_logs_nickname |

## Найденные пробелы (осознанно НЕ закрыты — по решению владельца)

1. **Vision-анализ (§13.2)**: Ollama Vision/облачный выбор провайдера — частично
   (провайдер берётся из глобальных AI-настроек; отдельные поля vision-модели
   есть). Категории контента: предустановки + пользовательские — в UI Blur Guard.
2. **§13.3 переобучение**: feedback-store есть; автоматическое переобучение
   модели — не делается (и не должно без подтверждения — правило плана).
3. **§7.1 «Контекст из голосовых сообщений стримера»**: diarization/whisper
   модули есть (app/diarization.py), полный контекст-конвейер — не подтверждён.
4. **Lighthouse ≥90 (§21)**: инструмент в системе отсутствует — не прогонялся.
5. **§9k расширенные категории AI-feedback** — опционально, не реализовано.
