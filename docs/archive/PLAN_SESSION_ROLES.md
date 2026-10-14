# PLAN_SESSION_ROLES.md — сессия «Роли ботов: рантайм + mod-feed + Helix»

> План: PLAN_CURRENT.md §6 (остаток): рантайм-гейты, §6.1 mod-feed,
> §6.1a Helix стрим-инструменты, §6.6 пресеты болтуна/копирка, §6.7 хоткеи.
> Правила: AGENTS.md + FILE_ZONES.md. Коммит после каждого зелёного шага:
> `~/.local/bin/pytest tests/ -q` из ЭТОЙ папки → commit в `session/roles`.
> i18n ru/en/ua. База ролей уже есть: app/bot_roles.py, app/role_routes.py,
> вкладка «⚙️ Роль» (коммиты 1b22e95, e2cc8c1).

## Зона владения

- Свои: PLAN_SESSION_ROLES.md, app/mod_feed_routes.py, widgets/mod-feed.html,
  tests/test_roles_runtime.py, tests/test_mod_feed.py + расширения
  app/bot_roles.py / role_routes.py (файлы уже твои по зонам).
- Общие (chat_analyzer.py, bot_manager.py, app.js, шаблоны) — точечные
  вставки, не переписывание. Новые эндпоинты — только в своих роутерах.

## §R1. Рантайм-гейты по роли (PLAN_CURRENT §6.5) ✅ (0808e52)

- [x] lurker: НЕ пишет никогда (жёстко) — если mention_reply=true, отвечает
  ТОЛЬКО на прямое @упоминание; копит память/lore/наблюдения.
- [x] moderator: chat_activity=chatter (болтает) | moderation_only | silent —
  читается из role_config в анализаторе; дефолт его активности — всплывашки
  mod-feed (§R2), анонсы в чат выключены.
- [x] voice_companion: не пишет в чат (выход — голос; реакция на whisper —
  §R3/фаза whisper-интеграции отдельно).
- [x] chatter: регресс — поведение как сейчас (анти-ассистент из role_config).
- [x] Тесты: test_roles_runtime.py (6) — каждый гейт отдельным кейсом,
  «гейт ДО send» проверен через _generate_and_send с фейковым send_fn.
  Кэш роли 60с + invalidate_role_cache при смене роли/конфига.

## §R2. mod-feed: единый канал событий ролей (§6.1 + §6.8) ✅ (97009c3, 8e56b6e)

- [x] **Канал событий** app/mod_feed_routes.py: publish/poll курсором,
  kinds = violation/intent/action/lurker/beep; «НАМЕРЕНИЕ» с исполнителем —
  POST /api/mod-feed/intents/{id}/{approve|reject} (confirm_mode=confirm).
- [x] **Виджет /widget/mod-feed** (OBS): плашки, позиция/длительность/акцент/
  фильтр через URL (?pos=br&dur=8&kinds=...), поллинг переживает рестарт.
- [x] **Тосты в панели** дублируют события через broadcast_log (WS, type=
  mod_feed). Кнопки [Таймаут 1м][10м] в тостах — через интенты API.
- [x] **Rate-limit + дедуп** (§9 остаток): дедуп (account,channel,user,kind)
  в окне 60с — 10 одинаковых подряд дают одну плашку; dedup=False для
  важных событий.
- [x] Действия модератора по умолчанию — всплывашки; анонсы в чат
  выключены (announce_in_chat=false в конфиге роли).
- [ ] TTS-дублирование действий — опция (не сделано, низкий приоритет).
- [x] Тесты: test_mod_feed.py (6) + test_mod_feed_wire.py (3).

## §R3. Helix стрим-инструменты (§6.1a) — РОЛЬ-СТОРОНА ✅

> РАЗГРАНИЧЕНИЕ (владелец, координация): HTTP-клиент Helix и эндпоинты
> (GET/PATCH категории/названия, chat settings, history, scope-проверка) —
> зона session/stream, файл app/stream_tools_routes.py (см.
> PLAN_SESSION_STREAM.md §S5). roles НЕ создаёт этот файл.

- [x] **Со стороны роли**: мод «предложить/авто» для каждого стрим-действия
  (stream_tool_modes из role_config модератора, уже в bot_roles.py):
  roles публикует НАМЕРЕНИЕ («сменить категорию на X») в mod-feed,
  режим confirm ждёт одобрения, режим auto дергает эндпоинт stream-сессии.
- [x] **История по-ролевому**: события одобрения/авто уводятся в общий
  журнал действий (кто/что/когда/одобрено) — UI-читалка в модераторской
  вкладке.
- [x] **Авто-категория по vision-кадрам**: роли решает КОГДА предложить
  (по кадрам stream_vision) и публикует предложение; сам Helix-PATCH —
  эндпоинт stream-сессии.
- [x] **Scope-ошибка**: если stream-эндпоинт вернул «нет права» — честный
  тост в панели (какое право добавить на dev.twitch.tv), не молча.
- [x] Тесты: мок ответов stream-эндпоинтов (успех/403-scope), публикация
  намерений в mod-feed, режим auto vs confirm.

## §R4. Пресеты болтуна + копирка (§6.6) ✅ (8c1bb32)

- [x] Пресеты в CHATTER_PRESETS: «Свой в доску», «Эмоциональный»,
  «Ехидный», «Тихий знаток», «Мемный», «Свой (чистый лист)» — промпт +
  3-4 примера у каждого.
- [x] **Анти-ассистент фильтр** (ANTI_ASSISTANT_RULE) — во всех пресетах
  и по умолчанию для роли chatter; переживает токен-обрезку.
- [x] **Копирка, 2 режима**: A «📋 Копия сообщений» — GET mimic/candidates
  (топ по активности из chat_log), POST mimic/copy (до 500 → few-shot
  последние 50 ≤200 симв. + авто-выжимка: длина/капс/эмодзи/частые слова);
  B «🎨 Стиль-профиль» — POST mimic/profile-build (AI собирает, панель
  редактирует), сила 0-100 + чекбоксы (лексика/эмодзи/капс/опечатки/длина).
- [x] Runtime: chatter_style_block() в system prompt; приоритет copy >
  profile > preset > дефолт; хранение в role_config.chatter;
  **токен-бюджет 4000 симв.** (анти-ассистент выживает при обрезке).
- [x] **Самообучение**: хук в post_ai_feedback — 👍 → learned_pool (лимит
  30), 👎 → исключается; POST mimic/learn-clear — очистить выученное.
- [x] Тесты: test_roles_style.py (12) — анти-паттерны, приоритет,
  сила/чекбоксы, бюджет, пул, roundtrip copy.

## §R5. Хоткеи и дашборд ролей (§6.7 остаток) ✅ (d57ca67, 03368ac)

- [x] Хоткеи: биндинг widget='moderation' + actions timeout_last /
  warn_last / slow_on / slow_off / emote_on / emote_off / clear —
  работают пока панель открыта (существующая подсказка bindings.hint);
  Helix-помощники update_chat_settings/clear_chat_messages в twitch_helix.py.
- [x] Дашборд «🧩 Боты по ролям»: /api/mod-feed/roles-summary (роль + цвет +
  каналы + счётчики нарушений/действий из фида), карточка на дашборде.
- [ ] Болтуны общаются МЕЖДУ собой — НЕ сделано (существующий
  multi_bot_chat_enabled покрывает базу; ролевой гейт — кандидат в §R1-фоллоу).

## Итог сессии

- Готово: §R1, §R2, §R4, §R5 (хоткеи+дашборд). Полный pytest зелёный (1264).
- ✅ §R3 — сделан: app/stream_intents.py + app/stream_intent_routes.py (propose/modes/history), tests/test_stream_intents.py (6).
- [ ] Болтуны между собой — фоллоу (низкий приоритет).
- Ветка session/roles готова к merge в main владельцем.

## Порядок работ

R1 (гейты) → R2 (mod-feed) → R4 (пресеты/копирка) → R3 (роль-сторона Helix,
эндпоинты ждём от session/stream §S5 — при их отсутствии мокаем в тестах)
→ R5.
