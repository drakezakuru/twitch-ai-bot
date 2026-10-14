"""
Роуты для просмотра per-bot логов.

GET /api/logs/<nick>/tail   - последние N строк лога бота
GET /api/logs/<nick>/file   - скачать файл лога
GET /api/logs/panel/tail    - последние N строк panel.log
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, PlainTextResponse

from app.per_bot_logging import sanitize_nick, LOG_ROOT
from app.security import auth_dependency

router = APIRouter(dependencies=[Depends(auth_dependency)])


def _tail(file_path: Path, lines: int = 100) -> str:
    """Читает последние N строк файла."""
    if not file_path.exists():
        return ""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
            return "".join(all_lines[-lines:])
    except Exception:
        return ""


@router.get("/api/logs/{nick}/tail")
async def tail_bot_log(nick: str, lines: int = Query(default=100, ge=1, le=1000)) -> dict[str, Any]:
    """Возвращает последние N строк лога бота."""
    safe = sanitize_nick(nick)
    file_path = LOG_ROOT / safe / "bot.log"
    content = _tail(file_path, lines)
    return {
        "ok": True,
        "nick": nick,
        "sanitized": safe,
        "file": str(file_path),
        "lines": content.count("\n"),
        "content": content,
    }


@router.get("/api/logs/{nick}/file")
async def download_bot_log(nick: str) -> FileResponse:
    """Скачивает файл лога бота."""
    safe = sanitize_nick(nick)
    file_path = LOG_ROOT / safe / "bot.log"
    if not file_path.exists():
        return PlainTextResponse("Log file not found", status_code=404)
    return FileResponse(
        path=str(file_path),
        filename=f"{nick}_bot.log",
        media_type="text/plain",
    )


@router.get("/api/logs/panel/tail")
async def tail_panel_log(lines: int = Query(default=100, ge=1, le=1000)) -> dict[str, Any]:
    """Возвращает последние N строк panel.log."""
    file_path = LOG_ROOT / "panel.log"
    content = _tail(file_path, lines)
    return {
        "ok": True,
        "file": str(file_path),
        "lines": content.count("\n"),
        "content": content,
    }


@router.get("/api/logs/panel/file")
async def download_panel_log() -> FileResponse:
    """Скачивает panel.log."""
    file_path = LOG_ROOT / "panel.log"
    if not file_path.exists():
        return PlainTextResponse("Log file not found", status_code=404)
    return FileResponse(
        path=str(file_path),
        filename="panel.log",
        media_type="text/plain",
    )
