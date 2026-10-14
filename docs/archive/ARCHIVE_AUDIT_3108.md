# ARCHIVE_AUDIT_3108.md — аудит архивных планов (P0, 31.08.2026)

> Выполнено по PLAN.md P0: каждый файл `docs/archive/*.md` сверен с кодом
> (существование файлов, `git log --all --grep`, grep по app/static/templates).
> Метод: не чекбоксы, а артефакты в репо. Коммит-пруфы в колонке «Доказательство».

## Сводная таблица

| Файл архива | Статус | Доказательство | Действие |
|---|---|---|---|
| PLAN_ALL_IN_ONE.md | PARTIAL | Ядро выполнено: bot_dirs.py, streamer_profile.py, personality_shift.py, chat-users UI, action_log+revert. Полировка §18/§21 (typography scale, Lighthouse) — НЕ сделано → живёт в PLAN.md P3/P2 | Недоделки покрыты живым планом; отдельно не поднимать |
| WIDGETS_PLAN.md | DONE | widget_bus.py, donation_integrations.py, beep_guard.py, blur_guard*, typing-indicator — все модули и роуты есть; git grep + commits | Закрыт. Хвосты §10.1–§10.7 — в ОСТАТОК.md → часть перенесена в PLAN.md P5 (виджеты) |
| MODERATION_PLAN.md | DONE | app/moderation.py, moderation_dicts/, timeout-policy route, can_timeout в routes.py, antispam в moderation settings | Закрыт |
| BRAIN_PLAN.md | DONE | summarizer.py, streamer_lore.py, learning.py, personality_shift.py, affinity_rules.py, brain_routes.py, templates/brain.html | Закрыт |
| OPS_PLAN.md | DONE | standalone.py, maintenance.py, instance_lock.py, backup.py, Dockerfile | Закрыт |
| PLAN_FEEDBACK_2908.md | PARTIAL | raid_follow в server.py (commit grep: raid_follow), clip_moments/, mimic в routes.py, multi_bot_chat.py. Хвосты — в ОСТАТОК.md §C (voice clone, категории оценки) | Закрыт, хвосты — решения владельца |
| PLAN_CURRENT.md | DONE → SUPERSEDED | stream_intents.py, mod_feed_routes.py, role_routes.py, per_bot_logging.py — всё в main после мержа 133d595 | Заменён PLAN.md (сделано при создании) |
| PLAN_SESSION_ROLES.md | DONE → SUPERSEDED | то же + widgets/mod-feed/index.html, tests test_roles_* | Смержено 133d595, replaced by PLAN.md |
| PLAN_SESSION_STREAM.md | DONE → SUPERSEDED | stream_tools_routes.py, beep_guard.py, blur-guard-v2/, twitch_polls.py | Смержено 133d595 |
| PLAN_SESSION_FIXES.md | DONE → SUPERSEDED | log_routes.py, panel_files.py, per_bot_logging.py, tests | Смержено 133d595 |
| PLAN_v11.md | DONE → SUPERSEDED | export/import характера (routes.py), ai_quality.py, bot_persona.py | История версий |
| AUDIT_SECTION1.md | DONE | Пометки-аудит разовые; пункты #5/#7/#8/#9/#10 учтены в последующих планах | История |
| AUDIT_FEEDBACK_2908.md | DONE | raid_follow, clip_moments — реализовано | История |
| AUDIT_FEEDBACK_3008.md | DONE | stream_tool_modes в bot_roles.py, роли | История |
| SMOKE_CHECKLIST_2908.md | DONE | Разовый чеклист; run.py/панель живы | История |
| ОСТАТОК.md | PARTIAL → ЖИВЫЕ ХВОСТЫ | См. ниже «Остатки из ОСТАТОК.md» — часть НИКОГДА не выполнялась | ⚠️ Хвосты → на решение владельца |
| HANDOFF_NEXT_SESSION.md | DONE → SUPERSEDED | Описан мерж fixes/roles — выполнен | История |
| HANDOFF_DB_LOCK_BUG.md | DONE | _db_registry.py, beep_guard fix, 1293/0/0 прогон | Баг закрыт (см. PLAN.md P1) |
| CONTEXT_SUMMARY.md | DONE → SUPERSEDED | Хэндофф сессии fixes; всё смержено | История |
| V10_vs_V12_comparison.md | DONE | Сравнительный документ, не задачи | История |
| CHANGELOG_v11..v14 | DONE | Логи изменений версий | История |

## ⚠️ Остатки из ОСТАТОК.md — НИКОГДА не выполнены, требуют решения владельца

По правилу P0 НЕ переносить самовольно. Список:

1. **§18 полировка UI**: typography scale, spacing-шаги, radii/shadows, контраст/focus states, Lighthouse ≥90.
2. **§12.1 TTS**: статус последнего синтеза + причина ошибки в UI; кнопка «🔊 Тест» TTS в Chat.
3. **§10.1–§10.7 виджеты**: inline-редактирование целей, `!np` команда, биндинги-форма (частично есть — widget_bindings.py от session/stream), гайд «виджеты без панели», дизайн-токены, `?scale=`.
4. **§12.2 голоса**: локальные XTTS/Coqui/F5-TTS, ElevenLabs clone, consent.
5. **§9k**: расширенные категории оценки ответов.
6. **§9 «Когда бот отвечает»**: переименование «Фильтр внимания», отдельные тумблеры.
7. **§24**: админ-формы для anime-runner, mascot, chat-roulette, combo-counter, lower-third, recent-events, stream-session (частично сделано 30.08 — wa2-секция; сверить список).
8. **§D инфраструктура данных**: миграция старых данных в per-bot структуру; включить per-bot папки в backup.

## Вывод

- Все сессионные планы и версии — DONE/SUPERSEDED (история).
- Единственный источник живой работы — PLAN.md (+PLAN_PANEL_REWORK.md).
- Из ОСТАТОК.md 8 групп хвостов — на решение владельца (не самовольничать).
