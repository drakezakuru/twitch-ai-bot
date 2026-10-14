#!/usr/bin/env bash
# Панель омнивойс — выбор и клонирование голосов.
# Запуск: двойной клик или ./start-панель.sh. Остановка: закрыть терминал (Ctrl+C).
BOT="${TWITCH_AI_BOT_DIR:-$HOME/Desktop/twitch-ai-bot}"
echo "Запускаю панель омнивойс… Первый старт ~1-2 минуты, модель уже скачана."
# браузер откроется сам, когда панель поднимется
( for i in $(seq 1 60); do
    curl -s -o /dev/null http://127.0.0.1:7860 && { xdg-open http://localhost:7860; break; }
    sleep 3
  done ) &
exec "$BOT/venv/bin/omnivoice-demo"
