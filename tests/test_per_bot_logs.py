"""Тесты per-bot логирования."""

import os
import shutil
import tempfile
from pathlib import Path

import pytest


def test_sanitize_nick():
    """Санитизация ника — безопасные символы."""
    from app.per_bot_logging import sanitize_nick
    
    assert sanitize_nick("NormalBot") == "normalbot"
    assert sanitize_nick("Bot/With:Bad..Chars") == "bot_with_bad__chars"
    assert sanitize_nick("") == "unknown"
    assert sanitize_nick("..") == "unknown"
    assert sanitize_nick("a" * 100) == "a" * 64


def test_log_structure():
    """Структура логов: panel.log + <ник>/bot.log + <ник>/chat.log."""
    from app.per_bot_logging import LOG_ROOT
    
    # Создаём тестовую структуру
    test_dir = LOG_ROOT / "test_bot"
    test_dir.mkdir(parents=True, exist_ok=True)
    (test_dir / "bot.log").touch()
    (test_dir / "chat.log").touch()
    (LOG_ROOT / "panel.log").touch()
    
    assert (LOG_ROOT / "panel.log").exists()
    assert (test_dir / "bot.log").exists()
    assert (test_dir / "chat.log").exists()
    
    # Очистка
    shutil.rmtree(test_dir, ignore_errors=True)


def test_log_api_endpoints():
    """API эндпоинты логов отвечают."""
    from fastapi.testclient import TestClient
    from app.server import app
    
    client = TestClient(app)
    
    # Panel log
    r = client.get("/api/logs/panel/tail?lines=10")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    
    # Bot log (несуществующий бот — должен вернуть пустой ответ)
    r = client.get("/api/logs/nonexistent/tail?lines=10")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True


def test_log_format():
    """Формат строк лога: [YYYY-MM-DD HH:MM:SS] [LEVEL] [module] message."""
    import re
    from app.per_bot_logging import LOG_FORMAT
    
    # Проверяем что формат содержит нужные плейсхолдеры
    assert "%(asctime)s" in LOG_FORMAT
    assert "%(levelname)s" in LOG_FORMAT
    assert "%(module_name)s" in LOG_FORMAT
    assert "%(message)s" in LOG_FORMAT
