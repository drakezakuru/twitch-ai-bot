# AUDIT_FEEDBACK_3008 — глубокий аудит (почему так + правильно ли)

> PLAN_FEEDBACK_3008 §5. Заполняется по мере проверки. Формат:
> «функция / как работает / почему так / вердикт / что чинить».
> Начато 30.08 с блока БД (вопрос владельца: «ничего не перемешивается?»).

## БД: изоляция данных функций

### Карта «таблица → владелец / скоуп» (первичная ревизия, 98 таблиц)

| Таблица | Владелец | Скоуп | Вердикт |
|---|---|---|---|
| accounts, channels, patterns, triggers, … | database.py (ядро) | per-account | ✅ |
| widget-таблицы (goals, sub_goal, counters, …) | app/widgets.py | global/account | ✅ (P0: создаются на старте) |
| clip_moments, stream_goals, sub_goal, now_playing, schedule_blocks, widget_titles | CREATE в ДВУХ местах (database.py + widgets.py) | — | ⚠️ дубли: схемы сейчас идентичны, ставлен тест-страж `test_s5_db_isolation.py`; долг — свести к одному владельцу |
| ai_feedback (👍/👎 + категории §9k) | routes.py | per-account | ✅ |
| bot_response_feedback | ai_quality_db.py | per chat_log_id / A/B-вариант | ✅ живая, НЕ дублирует ai_feedback (другое назначение) |
| streamer_profile / streamer_face | streamer_profile.py | account + channel (§5) | ✅ |
| tts_bot_config | tts_engine.py | per-account (+CHECK xtts) | ✅ |
| bot_attention_config | chat_analyzer.py | per-account | ✅ |

### Формат channel по таблицам (ревизия)

| Таблица | Формат | Вердикт |
|---|---|---|
| chat_log.channel | `name` (без #) | ✅ внутренне консистентно; экспорт CSV ожидает то же |
| channels.channel_name | `name` | ✅ |
| streamer_profile.channel | `#name` (lower) | ✅ с §5; API нормализует |
| streamer_kb.channel / style_examples.channel | `name` (lower, # срезается в роуте) | ✅ |
| widget_bindings | match — команда/хоткей, не канал | n/a |

**Вывод по перемешиванию:** сквозного смешивания НЕТ — у каждой функции свои
таблицы и свой формат канала внутри себя. Найденные риски: (1) 6 дублей CREATE
(дрейф-риск, страж поставлен), (2) формат канала между модулями различается —
требует конвертера только на стыках (сейчас стыки: attention-config, kb UI —
обрабатывают lstrip('#')).

### Что чинить (уезжает в работу)

- [ ] Свести 6 дублей CREATE к одному владельцу (после миграционного окна).
- [x] Тест-страж на дрейф схем и новые дубли (`test_s5_db_isolation.py`).

## (далее заполняется по §5: чат-движок, кулдауны, TTS-очередь, модерация, EventSub, виджеты, миграции, производительность)
