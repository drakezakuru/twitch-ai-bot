"""
Модуль per-bot логирования для Twitch бота.

Структура логов:
    logs/panel.log              - логи панели управления
    logs/<ник>/bot.log          - логи конкретного бота
    logs/<ник>/chat.log         - логи чата конкретного бота

Формат строк:
    [YYYY-MM-DD HH:MM:SS] [LEVEL] [module] message
"""

from __future__ import annotations

import logging
import re
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict


# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

LOG_ROOT = Path("logs")
LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [%(module_name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Ротация файлов (10 МБ, 5 бэкапов)
MAX_BYTES = 10 * 1024 * 1024
BACKUP_COUNT = 5

# Разрешённые символы в имени папки после санитизации
_SANITIZE_RE = re.compile(r"[^A-Za-z0-9_\-]")
_MAX_NICK_LEN = 64


# ---------------------------------------------------------------------------
# Форматтер / фильтр модуля
# ---------------------------------------------------------------------------

class _ModuleFilter(logging.Filter):
    """Проставляет module_name в record, если он не задан явно."""

    def __init__(self, default_module: str = "root") -> None:
        super().__init__()
        self._default = default_module

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "module_name"):
            record.module_name = getattr(record, "module", None) or self._default
        return True


def _build_formatter() -> logging.Formatter:
    return logging.Formatter(fmt=LOG_FORMAT, datefmt=DATE_FORMAT)


# ---------------------------------------------------------------------------
# Санитизация ника
# ---------------------------------------------------------------------------

def sanitize_nick(nick: str) -> str:
    """
    Приводит ник к безопасному имени папки.

    - Заменяет все запрещённые символы на '_'
    - Обрезает до _MAX_NICK_LEN символов
    - Не допускает пустого результата или '.'/'..'
    """
    if not isinstance(nick, str):
        nick = str(nick)

    cleaned = _SANITIZE_RE.sub("_", nick.strip())
    cleaned = cleaned.strip("._")
    cleaned = cleaned[:_MAX_NICK_LEN]

    if not cleaned or cleaned in {".", ".."}:
        cleaned = "unknown"

    return cleaned.lower()


# ---------------------------------------------------------------------------
# Фабрика логгеров
# ---------------------------------------------------------------------------

class _LoggerFactory:
    """Потокобезопасная фабрика/кэш логгеров."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: Dict[str, logging.Logger] = {}
        self._formatter = _build_formatter()

    def _ensure_dir(self, path: Path) -> None:
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RuntimeError(f"Не удалось создать директорию логов {path}: {exc}") from exc

    def _make_handler(self, file_path: Path) -> logging.Handler:
        self._ensure_dir(file_path.parent)
        try:
            if MAX_BYTES > 0:
                handler: logging.Handler = RotatingFileHandler(
                    filename=str(file_path),
                    maxBytes=MAX_BYTES,
                    backupCount=BACKUP_COUNT,
                    encoding="utf-8",
                )
            else:
                handler = logging.FileHandler(
                    filename=str(file_path),
                    encoding="utf-8",
                )
        except OSError as exc:
            raise RuntimeError(f"Не удалось открыть файл лога {file_path}: {exc}") from exc

        handler.setFormatter(self._formatter)
        return handler

    def _get_or_create(
        self,
        logger_name: str,
        file_path: Path,
        default_module: str,
        level: int,
    ) -> logging.Logger:
        with self._lock:
            cached = self._cache.get(logger_name)
            if cached is not None:
                return cached

            logger = logging.getLogger(logger_name)
            logger.setLevel(level)
            logger.propagate = False

            if not logger.handlers:
                logger.addFilter(_ModuleFilter(default_module))
                logger.addHandler(self._make_handler(file_path))

            self._cache[logger_name] = logger
            return logger

    def panel_logger(self, level: int = logging.INFO) -> logging.Logger:
        return self._get_or_create(
            logger_name="twitch.panel",
            file_path=LOG_ROOT / "panel.log",
            default_module="panel",
            level=level,
        )

    def bot_logger(self, nick: str, level: int = logging.INFO) -> logging.Logger:
        safe = sanitize_nick(nick)
        return self._get_or_create(
            logger_name=f"twitch.bot.{safe}",
            file_path=LOG_ROOT / safe / "bot.log",
            default_module="bot",
            level=level,
        )

    def chat_logger(self, nick: str, level: int = logging.INFO) -> logging.Logger:
        safe = sanitize_nick(nick)
        return self._get_or_create(
            logger_name=f"twitch.chat.{safe}",
            file_path=LOG_ROOT / safe / "chat.log",
            default_module="chat",
            level=level,
        )

    def close_all(self) -> None:
        """Закрывает все хэндлеры и очищает кэш."""
        with self._lock:
            for logger in self._cache.values():
                for handler in list(logger.handlers):
                    try:
                        handler.close()
                    except Exception:
                        pass
                    logger.removeHandler(handler)
            self._cache.clear()


_factory = _LoggerFactory()


# ---------------------------------------------------------------------------
# Публичный API
# ---------------------------------------------------------------------------

def get_panel_logger(level: int = logging.INFO) -> logging.Logger:
    """Логгер панели -> logs/panel.log"""
    return _factory.panel_logger(level)


def get_bot_logger(nick: str, level: int = logging.INFO) -> logging.Logger:
    """Логгер бота -> logs/<ник>/bot.log"""
    return _factory.bot_logger(nick, level)


def get_chat_logger(nick: str, level: int = logging.INFO) -> logging.Logger:
    """Логгер чата -> logs/<ник>/chat.log"""
    return _factory.chat_logger(nick, level)


def log(logger: logging.Logger, level: int, module: str, message: str, *args, **kwargs) -> None:
    """Логирует с явным именем модуля."""
    extra = kwargs.pop("extra", {}) or {}
    extra["module_name"] = module
    logger.log(level, message, *args, extra=extra, **kwargs)


def shutdown_logging() -> None:
    """Закрывает все файловые хэндлеры."""
    _factory.close_all()


__all__ = [
    "sanitize_nick",
    "get_panel_logger",
    "get_bot_logger",
    "get_chat_logger",
    "log",
    "shutdown_logging",
]
