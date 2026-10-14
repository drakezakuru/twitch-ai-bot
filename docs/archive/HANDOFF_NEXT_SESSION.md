# HANDOFF — контекст для новой сессии (что доделать)

> Дата: 30.08.2026. Цель: продолжить работу без потери контекста.
> Источник правды: `AGENTS.md` + `FILE_ZONES.md` — читать перед каждым шагом.
> Актуальные планы: `PLAN_CURRENT.md` (сводный, §1-§11) + `PLAN_PANEL_REWORK.md` (отдельно, строго последним).

## 1. Как работать (правила параллельных сессий)

- Каждая сессия — свой `git worktree` + своя ветка. Не `stash`/`reset`/`checkout --` без запроса владельца. Общие файлы (`app/routes.py`, `static/app.js`, шаблоны) — только точечными вставками; новые эндпоинты — в своём `app/*_routes.py` + `include_router` одной строкой в `app/server.py`.
- Коммит после каждого зелёного шага: `~/.local/bin/pytest tests/ -q` из папки своей ветки → `git commit` в СВОЮ ветку. Пушить/мержить в `main` — только владелец или интегратор (`git merge session/<имя>` из главной папки).
- i18n: все новые тексты `ru/en/ua` сразу (ключи через `t('...')` должны встречаться ≥3 раз в `static/app.js`, иначе падает `test_all_active_template_and_javascript_i18n_keys`).
- Корень чистый: разовые скрипты — в `scripts/`, временное — в `/tmp/opencode`.

## 2. Где что лежит

| Папка | Ветка | План | Состояние (30.08 вечер) |
|---|---|---|---|
| `twitch-ai-bot/` | `main` `aba6389` | `PLAN_CURRENT.md` + `PLAN_PANEL_REWORK.md` | §1-§2-§4-§5(карта) сделаны в коде, но чекбоксы в `PLAN_CURRENT.md` устарели — верь `git log`, не `[ ]` |
| `session-fixes/` | `session/fixes` `eecf79c` | `PLAN_SESSION_FIXES.md` | Готов (сквош): §11.A баги + §11.B per-bot логи `logs/panel.log`, `logs/<ник>/bot.log` + §11.I логи в Настройках |
| `session-roles/` | `session/roles` `7c1abe9` | `PLAN_SESSION_ROLES.md` | Основной прогресс: см. §3. Сюда уже смержены `session/fixes` и `session/stream` (интеграционная ветка) |
| `session-stream/` | `session/stream` `8b13a1a` | `PLAN_SESSION_STREAM.md` | Готов (сквош, 10 файлов): §S1 блюр v2 550 строк, §S2 beep_guard 462 строки, §S3 биндинги, §S5 `stream_tools_routes.py` 622 строки, §S6 команды стримера |

Старые сессии `session-{brain,moderation,ops,widgets}` — prunable, смержены в `main`.

## 3. Что уже сделано (не повторять)

**main (`aba6389`):**
- §1.1-1.3 стили форм + примеры виджетов + blur-превью с текстом под стеклом
- §2 Мозг → каналы: селект `*` (=все каналы), бейджи скоупа, KB per-channel, Summarizer per-channel через `channel_overrides` (наследование), профиль стримера в Мозге
- §9.1 `backup_before_migration()` (WAL-чекпоинт, `bot.db.<label>-<ts>.db` в `data/backups/`, `quick_check`, дедуп sha256, ротация)
- §4 двойной `##` в скоупе профиля + пояснения пустых состояний Мозга
- §5 `docs/AUDIT_TABLE_MAP.md` — 96 таблиц (владелец/скоуп/кто пишет/вердикт)
- Гигиена БД: 6 мёртвых таблиц удалены, `clip_moments` унифицирован, `cleanup_account_children()` при удалении бота
- Хотфиксы: белый-на-белом → `.form-panel`, профиль стримера теперь только в Мозге

**session/roles (`7c1abe9`, integration, 1264 теста зелёных):**
- §R1 гейты: `chat_analyzer._role_reply_gate()` до `send` — lurker (только @), moderator `silent/moderation_only`, voice_companion не пишет в чат; кэш 60с
- §R2 mod-feed: `app/mod_feed_routes.py` (publish/poll курсором, дедуп 60с, фильтры kinds), интенты `[Одобрить]/[Пропустить]`, OBS-виджет `/widget/mod-feed`, wire-in нарушений бота-модератора
- §R4 болтун: 6 пресетов + `ANTI_ASSISTANT_RULE` во всех, копирка 2 режима (A copy 50 few-shot + выжимка, B profile AI), сила 0-100 + чекбоксы, `chatter_style_block()` в system prompt, самообучение `learn_from_feedback()` (👍 пул 30)
- §R5 хоткеи `widget='moderation'` (`timeout_last`/`warn_last`/slow/clear через новые `twitch_helix.update_chat_settings`/`clear_chat_messages`), дашборд `rolesSummary`
- Мержи `main` + `fixes` + `stream` (app.js слит трёхсторонним `merge-file`, роли-блок дедуплицирован)

**session/fixes, session/stream:** см. коммиты выше; код в `session-roles` уже содержит их изменения.

## 4. Что осталось (приоритет — PLAN_CURRENT.md §Приоритет + PLAN_SESSION_*)

**P0 — мержи в `main` (интегратор, владелец):**
- [ ] `git merge session/fixes`, `git merge session/stream`, `git merge session/roles` из `twitch-ai-bot/` (порядок: fixes → stream → roles; roles уже содержит fixes+stream, так что достаточно `git merge session/roles`). Разрешить конфликты `static/app.js` трёхсторонним мержем (как в roles: `merge-file` с базой `78bf75d`), `app/server.py` — склеить `include_router` строки.

**P1 — хвосты `session/roles` (§R3 + мелочи):**
- [ ] §R3 роль-сторона Helix — теперь разблокирован (`stream_tools_routes.py` на месте). Реализовать потребление эндпоинтов: `auto`/`предложить` по `stream_tool_modes` из `bot_roles.moderator`, публикация намерений в mod-feed, `approve` дергает Helix, история в `bot_logs`. Тесты на моках stream-эндпоинтов.
- [ ] §R2 хвост: TTS-дублирование действий модератора (опция `tts_announce`).
- [ ] §R5 хвост: «болтуны между собой» — гейт `multi_bot_chat` только для `role==chatter`.
- [ ] Отметить `[x]` в `PLAN_SESSION_ROLES.md` и `PLAN_CURRENT.md` §6.

**P2 — PLAN_CURRENT.md оставшееся (если не покрыто сессиями):**
- [ ] §3 Каналы/Twitch: подсказка «+ Канал», карточка Helix — проверить, не дублирует ли stream §S5 (координация).
- [ ] §6.1/6.1a/6.7 детали модератора (лестница в UI уже частично в roles, стрим-инструменты — в stream, хоткеи — в roles) — сверить чек-лист.
- [ ] §7 запикивание (фаза 3 виртуального микрофона — только после ручной проверки звука владельцем).
- [ ] §8 Режим стрима — в stream §S6 (проверить чекбоксы).
- [ ] §10 дыры (§8 тесты, §6.1 отчёт модератора, §6.7 импорт валидация, доки `FEATURE_OWNERSHIP.md`/`FILE_ZONES.md`).
- [ ] §11.C/E/F/H/I — биндинги/блюр/превью/Тwitch/профиль уже в stream/fixes, сверить с планом и отметить.

**P3 — отдельно, последним:**
- [ ] `PLAN_PANEL_REWORK.md` — §1 Мозг 2.0 per-bot (карта `docs/BRAIN_PER_BOT_MAP.md`, экран «Мозг бота X», промпт-инспектор) + §2 аудит ВСЕХ менюшек (`docs/AUDIT_PLACEMENT.md`) + §3 UX-стандарт. Не начинать до закрытия `PLAN_CURRENT.md`.

## 5. Архитектурные заметки (чтобы не искать)

- `accounts.bot_role` (`chatter|moderator|voice_companion|lurker`, default `chatter`) + `accounts.role_config_json` = `{"chatter": {...}, "moderator": {...}}` — per-role без потери (§6.7). Чтение: `bot_roles.load_role_config(json, role)` (+дефолты), запись через `PUT /api/accounts/{id}/role*` (`app/role_routes.py`).
- Per-channel Summarizer/judge: `channel_overrides` (UNIQUE account+channel, `overrides_json`, `enabled`), `CHANNEL_MERGE_KEYS` в `chat_analyzer.py` (туда добавлен `summarizer_live_*`), чтение `await chat_analyzer._merged_settings(aid, ch, base)`.
- Mod-feed: `app/mod_feed_routes.py` — in-memory `deque(200)`, `_INTENTS` + `_INTENT_EXECUTORS`, `_LAST_VIOLATOR`, `_DEDUP` 60с. Публичные `GET /api/mod-feed/public/poll?since=&kinds=`, админ `POST /api/mod-feed/events`, `POST /intents/{id}/{approve|reject}`. WS-дубли через `app.server.broadcast_log`.
- Chatter-стиль: `bot_roles.CHATTER_PRESETS`, `ANTI_ASSISTANT_RULE`, `chatter_style_block(cfg)` (приоритет copy>profile>preset, бюджет 4000), `learn_from_feedback()` — хук в `app/routes.py` `post_ai_feedback`.
- Helix: `app/twitch_helix.py` — `timeout_user`, `update_chat_settings`, `clear_chat_messages`, `is_helix_configured()`. Каналы: `channel.lstrip('#').lower()`.
- Тесты: `~/.local/bin/pytest tests/ -q` из папки ветки. БД на тест — `tmp_db` (монкипатчит `database.DB_PATH` → `tmp_path/data/bot.db`), singleton `_shared_db` сбрасывается фикстурой. `disable_auth` — выключает Basic-auth.
- Известная ловушка: `from app.server import chat_analyzer` на уровне модуля теста ломает изоляцию `sys.modules['app.server']` (conftest `_restore_app_server_module`). Импортировать внутри тестов/фикстур.

## 6. Команды для новой сессии

```bash
# открыть нужную ветку
git worktree list
# продолжить roles (интеграционная, уже содержит fixes+stream)
# workdir: <project-root>/session-roles  branch: session/roles
~/.local/bin/pytest tests/test_roles_runtime.py tests/test_mod_feed.py tests/test_roles_style.py -q
# полный прогон (5-6 мин)
~/.local/bin/pytest tests/ -q
# мерж в main (из twitch-ai-bot/, владелец)
git fetch . && git merge session/roles -m "merge roles (R1+R2+R4+R5, интеграции fixes+stream)"
~/.local/bin/pytest tests/ -q  # проверка main после мержа
```

## 7. Промпт для нового чата (скопировать)

> Продолжи работу над Twitch AI Bot. Прочитай `AGENTS.md`, `FILE_ZONES.md`, `HANDOFF_NEXT_SESSION.md`, `PLAN_CURRENT.md` и `PLAN_PANEL_REWORK.md`. Работаешь в worktree `session-roles` (ветка `session/roles`, уже содержит мержи fixes+stream). Приоритет: §R3 (роль-сторона Helix, теперь разблокирован), затем хвосты §R2 TTS + §R5 “болтуны между собой”, затем сверка `PLAN_CURRENT.md` чекбоксов и мерж в `main`. Правила: коммит после зелёного `pytest`, i18n `ru/en/ua`, не трогай чужие зоны.

