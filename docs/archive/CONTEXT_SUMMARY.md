# Контекст сессии — Session Fixes

## Что это за проект
Twitch AI Bot Panel — панель управления AI-ботами для Twitch чата.
- Фреймворк: FastAPI + Jinja2 + vanilla JS
- Папка проекта: `session-fixes`
- Ветка: `session/fixes`

## Chatbase API (для генерации кода)
- Agent ID: `<your-agent-id>`
- API Key: `<your-api-key>`
- Endpoint: `https://www.chatbase.co/api/v2/agents/{agent_id}/chat`
- Важно: промпт в Chatbase уже настроен на кодинг

## Прокси (локальный, для OpenCode)
- Папка: `chatbase-hermes-proxy`
- Запуск: `./start-smart.sh /path/to/project`
- Порт: 3921
- Авто-применяет код к файлам

---

## §A. Баги — ВСЁ ВЫПОЛНЕНО ✅

### A1 ✅ Сырой ключ role.name.chatter
- Файл: `static/app.js` (строки ~5071, ~5127)
- Фикс: Добавлен fallback в `_roleT()` — преобразует ключ в читаемое имя
- Фикс: Cache-busting `?v=1.0.1` в `templates/base.html` для app.js и app.css

### A2 ✅ Генерация заготовок на украинском
- Файл: `app/routes.py` (строка ~7823)
- Фикс: Переведены промпты с украинского на русский
- System: "Ты генерируешь заготовки для Twitch-бота. Верни только JSON."

### A3 ✅ Blur Guard проценты
- Файл: `static/app.js` (функция `waBgPreviewSync`)
- Фикс: Синхронизация number↔range↔plaшка + валидация значений

### A4 ✅ Фото стримера
- Файл: `app/streamer_profile.py` (функция `get_streamer_face`)
- Фикс: Добавлен `has_face` в SQL запрос когда `include_image=True`

### A5 ✅ Bulk-бар дубли
- Файл: `static/app.js` (функция `renderBotsList`)
- Фикс: Скрыты индивидуальные кнопки старт для выбранных ботов

### A6 ✅ Быстрые слова
- Файл: `app/bot_manager.py`
- Фикс: Добавлено подробное логирование для диагностики

---

## §B. Per-bot логи — ВСЁ ВЫПОЛНЕНО ✅

### B1-B6 ✅ Модуль логирования
- Файл: `app/per_bot_logging.py` (НОВЫЙ)
- Структура: `logs/panel.log`, `logs/<ник>/bot.log`, `logs/<ник>/chat.log`
- Санитизация ника, ротация 10MB×5, формат `[YYYY-MM-DD HH:MM:SS] [LEVEL] [module] message`

### B4 ✅ Роуты логов
- Файл: `app/log_routes.py` (НОВЫЙ)
- `GET /api/logs/{nick}/tail?lines=100`
- `GET /api/logs/{nick}/file`
- `GET /api/logs/panel/tail?lines=100`
- `GET /api/logs/panel/file`
- Подключен в `app/server.py`

### B3 ✅ UI вкладки «Логи»
- Файл: `static/app.js` (функция `loadBotLogs` обновлена)
- Файл: `templates/partials/bots.html` (добавлена кнопка 📥)
- Теперь загружает файловые логи с нового API

### run.py ✅ Логирование
- Фильтр шума aiosqlite (только WARNING+)
- panel.log вместо bot.log

### bot_manager.py ✅ Per-bot логи
- Старт/стоп, подключение, ошибки → `logs/<ник>/bot.log`
- Сообщения чата → `logs/<ник>/chat.log`
- Отправленные сообщения → `logs/<ник>/bot.log`

---

## §I. Логи в Настройках — НЕ НАЧАТО ⏳

Нужно добавить карточку «📋 Последние логи» в Настройки:
- Файл: `templates/partials/settings.html`
- Показывает хвост panel.log
- Кнопка Обновить
- API уже готово: `GET /api/logs/panel/tail`

---

## Полезные команды

```bash
# Запуск сервера
cd session-fixes
python run.py

# Тесты
~/.local/bin/pytest tests/ -q

# Коммит
git add -A && git commit -m "fix: ..."
```

## Файлы которые редактировались
- `static/app.js` — A1, A3, A5, B3
- `templates/base.html` — A1 (cache-busting)
- `app/routes.py` — A2
- `app/streamer_profile.py` — A4
- `app/bot_manager.py` — A6, B-логи
- `app/server.py` — B4 (подключение роутов)
- `app/per_bot_logging.py` — НОВЫЙ (B1-B6)
- `app/log_routes.py` — НОВЫЙ (B4)
- `run.py` — фильтр шума
- `templates/partials/bots.html` — B3 (кнопка 📥)
