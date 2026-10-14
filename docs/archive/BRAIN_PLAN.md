# План: Мозг бота — память, контекст, обучение, автономность (отдельная сессия)

> Версия: v1 · Дата: 28.08.2026
> Источник: PLAN_ALL_IN_ONE.md §7 (память/контекст/KB/Mimicry), §8 (привязанности),
> §9b (Personality Shift), §9f (Threads/Pacing/Corrections), §14 (Stream Summarizer),
> §15 (Lore), §16 (безопасное автообучение) + фидбек владельца («бот должен помнить,
> что происходило раньше»; «память про стримера фулл»).
> Это **самостоятельный план** — сессии достаточно этого файла.

## Как читать


---
## ⛔ ПРАВИЛА БЕЗОПАСНОСТИ СЕССИИ (обязательно, читай первым)

- **Работай только в своей папке/ветке** — см. карту сессий в `PLAN_ALL_IN_ONE.md` §0
  и правила в `AGENTS.md`. Папка сессии = `session-<имя>/`, ветка = `session/<имя>`.
- **ЗАПРЕЩЕНО без явного запроса владельца:** `git stash`, `git stash pop/apply`,
  `git checkout -- <файл>`, `git restore`, `git reset`, `git checkout <ветка>`,
  `git push` и переписывание целых файлов своей устаревшей копией.
- **Обязательно:** после каждого зелёного шага — коммит в СВОЮ ветку; перед правкой
  файла — перечитай его с диска (мог измениться); правки — точечными Edit-ами.
- Чужие падающие тесты в полном прогоне — это чужой WIP, НЕ чини (проверяй свой скоуп).
- 🔒 **Твоя зона файлов:** `brain` (`app/summarizer.py`, `app/streamer_lore.py`, `app/learning.py`, `app/personality_shift.py`, `templates/partials/brain.html`, `tests/test_brain*`, `tests/test_summarizer*`). Полный реестр — `FILE_ZONES.md`.
---

- [ ] не сделано; [x] сделано и проверено; «Открытое решение» — делаем как написано,
  если владелец не сказал иное. Изоляция данных: всё per `bot_id + channel` (§2.1).

## 0. Аудит кода на 28.08.2026

- `app/user_memory.py`: факты per (account_id, username), add/update/delete, priority,
  TTL/expires_at есть в сигнатурах; изоляция подтверждена тестами
  (`test_isolated_per_account`, `test_history_retention_isolated_by_account_channel_and_user`).
  В БД также `user_message_history` (последние N сообщений юзера).
- `app/shared_user_facts.py` — общие факты per (channel, username) между ботами, backend есть, UI нет.
- `app/conversation_threads.py` — треды (feed → thread, cosine-походость), backend есть;
  в chat_analyzer НЕ подключён к prompt (только собирает).
- `app/streamer_profile.py` — профиль + автообновление; UI готов (вкладка «О стримере»).
- `app/ai_quality.py` — classify_message, banned topics, topic tokens; A/B (`ab_dashboard.py`).
- Привязанности: `bot_affinity` (per bot/channel/user, 0–100, lock, история),
  авто-прирост за сообщения есть в server.log_message.
- Stream Vision: кадры + Whisper (`app/stream_vision.py`), observations пишутся.
- Summarizer, lore, автообучение — **нет** (greenfield).
- `highlights.py` — детект всплесков чата (для суммаризатора пригодится).

## 1. Память per-user: довести до продукта

- [x] UI «Память» в панели: список юзеров с фактами, редактирование/удаление фактов
  (CRUD-роуты есть, UI есть базовый — добавить редактирование поля priority/TTL).
  *(v16: кнопка ✎ у факта — priority + TTL в днях, brain.html + app.js; confirm ✓/✓✓ есть)*
- [x] Приоритеты фактов в prompt: сортировка по (priority desc, updated_at desc),
  лимит фактов в контексте, weight в блоке памяти. *(сверено: format_facts_for_prompt,
  тест test_confirmed_first_in_prompt)*
- [x] TTL/decay: просроченные факты не подмешиваются — покрыть тестом;
  фоновая уборка (GC) раз в N часов. *(memory_gc_loop каждые 6 ч в server.py;
  test_gc_expired)*
- [x] Ручное подтверждение важных фактов: поле `confirmed` — подтверждённые живут
  дольше и идут в prompt первыми (галочка в UI). *(роут confirm + UI ✓; тесты)*
- [x] Авто-извлечение фактов из чата: LLM-extract по активным юзерам → черновик
  с source='auto' через одобрение (§4/§5). *(роут memory_auto_extract + кнопка
  «🤖 Извлечь факты»; периодический фоновый прогон — за владельцем, см. открытые вопросы)*

## 2. Контекст ответов: чат + стрим + стример

- [x] Источники контекста — селектор per-bot («chat/stream/streamer») — сверено,
  реально влияет на prompt (`_generate_and_send`: context_source_chat/stream/streamer);
  тесты дефолтов и переключения — test_v104_realtime_context.py.
- [x] Реплики стримера: диаризация/транскрипт из Stream Vision подмешиваются
  («последние N реплик», get_recent_streamer_lines + тесты изоляции/возраста).
- [x] Треды: сводка активного треда в prompt (format_thread_context, лимит
  threads_max_messages_in_prompt=6, §9f «ограниченное влияние»).
- [x] Не смешивать контекст между bot/channel — тесты на lore/threads/lines/live-digest
  (test_brain_modules.py, test_conversation_threads.py, test_stream_vision*).

## 3. Knowledge Base и Mimicry

- [x] KB: CRUD есть; в prompt идут только `enabled=1` (retrieve_kb фильтрует — тест
  test_disabled_kb_not_in_prompt); импорт/экспорт JSON bulk *(v16: brain_routes
  kb_export/kb_import + UI-карточка, merge/replace, дубликаты пропускаются)*.
- [x] Mimicry: примеры — ручное добавление/удаление из UI (вкладка есть),
  top-K примеров в prompt по косинусной близости темы *(v16: pick_style_examples
  query= → _tokenize/_tf/cosine из conversation_threads; вызов в chat_analyzer
  передаёт text/context)*.
- [x] Стиль не меняется молча: action_log пишется (kb_add, style_example_add,
  lore_*, learning_*, kb_import/kb_export, learning_revert_last).

## 4. Stream Summarizer (§14)

- [x] Модуль `app/summarizer.py`: live-loop (server.py, 30 мин, тумблер
  summarizer_live_enabled), run-pipeline с чекпоинтами, файлы отчёта.
- [x] «Live summary» — каждые 30 мин, пишется в summarizer_live + подмешивается
  в контекст (get_live_digest).
- [x] «Прогнать стрим»: кнопка в «Мозг» (канал/период/язык) → фоновый отчёт
  (главное, смешное, неудачи, реакции чата, события, lore-предложения).
- [x] Результаты в `data/bots/summarizer/<channel>/<date>/{summary.md, events.json,
  funny-moments.json, chat-analysis.json, lore-suggestions.json, digests.json}`.
- [x] Список прошлых прогонов, просмотр, экспорт MD/JSON *(v16: кнопки ⬇MD/⬇JSON)*,
  удаление.
- [x] Прогресс: чекпоинты по 30-мин окнам (resumable — тест run_lifecycle).

## 5. Lore стримера (§15) — одобряемая память

- [x] Таблица `streamer_lore` (source summary|chat|manual|auto, evidence, confidence,
  importance, status suggested|approved|rejected, expires_at).
- [x] Suggestions из summarizer/авто-фактов; карточка «Lore» в панели:
  добавить/изменить/отклонить/подтвердить с источником, датой, confidence.
- [x] В prompt только approved; expire учитывается (тесты).
- [x] Никогда не меняет поведение автоматически — только через подтверждение.

## 6. Безопасное автообучение (§16)

- [x] Таблица `learning_suggestions` (kind style_example|kb_topic|persona_delta|
  banned_topic, payload_json, reason, status, дедуп pending).
- [x] Применение по kind (style/kb/banned → реальные таблицы; persona_delta → log),
  sources: manual/auto; engagement/feedback — точки расширения.
- [x] Разделение скоупов: suggestions per (account_id, channel); style_examples
  имеют channel; KB — общий на аккаунт.
- [x] Панель «Обучение»: список → применить/отклонить; применённые пишут action_log.
- [x] Роллбэк: кнопка «↩ Отменить последнее» *(v16: brain_routes learning/revert_last —
  инверсия последнего applied, статус reverted; тесты)*.

## 7. Personality Shift (§9b) и привязанности (§8)

- [x] Shift: временный сдвиг mood/emotionality после рейда (trigger из raid-handler),
  cap 30 мин, восстановление по таймеру; read-only индикатор в «Мозг» + тумблер
  интенсивности 0/1/2; без ручных чисел.
- [x] Привязанности: авто-изменение по содержанию *(v16: app/affinity_rules.py —
  юмор ↑, поддержка ↑, конфликт ↓ (конфликт сильнее поддержки), дефолт +1; lock/auto_adjust
  уважаются; событийные дельты пишут bot_affinity_history; хук в server.log_message)*.
- [x] Уровни привязанности в UI: незнакомец/зритель/знакомый/постоянный/близкий
  (0-20-40-60-80) — рядом со слайдерами (app.js-инъекция) + роут affinity_level.

## 8. Тесты

- [x] Изоляция контекста bot/channel: lore, live-digest, streamer-lines, threads, affinity.
- [x] Summarizer: чекпоинты (resumable), отчёт на фикстурных данных (FakeAI),
  lore-suggestions, файлы, парсер RU/EN.
- [x] Lore: suggested не в prompt, approved в prompt, expiry, importance-сортировка.
- [x] Автообучение: предложение → применение → откат (style/kb), dedup, изоляция.
- [x] Shift: trigger/expire/intensity/изоляция/disable.
- [x] Affinity: правила дельт, lock/auto_adjust, изоляция, уровни-пороги.
- [x] KB: enabled-фильтр, import/export roundtrip, валидация записей.
- [x] Mimicry: top-K по косинусу (relevant first), поведение без query.

## Приоритет

1. §1 память (UI + priority/TTL/подтверждение) — быстрые победы на готовом backend.
2. §2 контекст (треды в prompt, реплики стримера) — заметный эффект на ответы.
3. §4 Summarizer (live summary) → §5 Lore → §6 автообучение.
4. §3 KB/Mimicry усиления, §7 shift/affinity.

## Открытые вопросы владельцу — РЕШЕНЫ (28.08.2026)

- Summarizer: отчёты на каком языке? → **Язык панели**. Реализовано:
  диалог «Прогнать стрим» по умолчанию берёт язык панели (en→EN, иначе RU,
  включая ua→ru); для live-сводок — настройка `summarizer_live_lang`
  (вкладка «Мозг», селектор «как панель»: en→EN, ua/ru→RU).
- Авто-факты: порог confidence для автодобавления без одобрения? → **Всё
  через одобрение** (текущее поведение сохранено: source='auto' → lore
  suggestions, владелец подтверждает; source=streamer — нет такого потока).
