# CHANGELOG v13

> Сессия «Эксплуатация» (OPS_PLAN.md). Версия панели: `/api/version` → v13.0.

## §1 Bot Files

- per-bot папки (`data/bots/<id>_<nick>/`) подключены к панели: вкладка бота
  «📁 Файлы» — дерево, просмотр/редактирование json/md/txt (≤256 КБ).
- Роуты: `GET /api/accounts/{id}/files`, `GET/PUT/DELETE .../files/{path}`.
- init/migrate структуры при старте бота — идемпотентно, миграция из БД — только
  чтение (persona → prompts/personality.txt).
- README больше не врёт про «НЕ РЕАЛИЗОВАНО».

## §2 Standalone

- `python run_bot.py <nick|*> [--channels a,b] [--stop] [-v]` — бот без панели
  (без FastAPI/браузера), общий wiring с панелью через app/bootstrap.py.
- Instance-lock: панель и standalone не могут управлять одним ботом одновременно.
- Standalone отказывается поднимать выключенного бота.

## §3 Надёжность

- **fallback виден в панели**: ai_log('fallback') пишется в bot_logs (категория
  `fallback` добавлена CHECK-миграцией — раньше события молча терялись).
- **Исправлен крах всех ботов**: NameError `manager` в run_bot() (bot_manager)
  валил задачу каждого бота при старте.
- Watchdog: раз в 60с переподнимает умершие таски по desired-состоянию.
- reconnect_count в статусе бота + в tooltip бейджа панели.
- TTS: реальный лимит перегруза (_pending ≤ 100; прежний cap по длине очереди
  был недостижим — очередь «самоопустошалась»).
- Crash-изоляция покрыта тестами; fallback-цепочки (429/5xx→Ollama,
  ElevenLabs→Web Speech) — end-to-end тесты.

## §4 Эксплуатация БД и логов

- Ротация logs/bot.log: RotatingFileHandler 10МБ × 5 (панель и standalone).
- Retention bot_logs: суточный GC, `BOT_LOG_RETENTION_DAYS` (дефолт 30).
- Авто-бэкап раз в `AUTO_BACKUP_DAYS` (дефолт 7) в data/backups/, ротация 5 шт.
- Настройки → БД: размер/записи + кнопка «Оптимизировать» (PRAGMA optimize+VACUUM).

## §5 Деплой

- `docker-compose.prod.yml`: healthcheck (/api/version), restart policy, volume
  data/logs/widgets, лимит памяти, профиль `tools` для Ollama.
- Dockerfile: HEALTHCHECK.
- `python run.py --doctor` — проверка окружения с понятным отчётом.
- `/api/version` + версия в footer панели.

## §6 Качество

- Тесты: миграция «старая v10 БД + init_db» (снапшот), tts fallback chain,
  bot_logs retention, standalone, crash-isolation, перегруз TTS-очереди.
- Линт-тест: onclick-атрибуты с кириллицей в активных шаблонах запрещены
  (i18n-only для новых рендеров).
- Браузерный smoke: `scripts/browser_smoke.py` (Playwright, см. README).
