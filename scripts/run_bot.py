#!/usr/bin/env python3
"""Standalone-запуск Twitch AI бота без панели (OPS_PLAN §2).

Использование (из корня проекта):
    python scripts/run_bot.py <nickname>                # один бот по нику
    python scripts/run_bot.py *                         # все включённые боты
    python scripts/run_bot.py <nickname> --channels a,b # override каналов
    python scripts/run_bot.py <nickname> --stop         # остановить standalone-процесс бота

Панель (run.py) и standalone управляют ботами через один lock: один и тот же
бот не может быть запущен из панели и standalone одновременно (app/instance_lock.py).
Когда панель нужна: менять настройки/персону/триггеры. Когда нет: бот просто
крутится в чате — тогда run_bot.py легче панели (нет FastAPI/браузера).
"""

import argparse
import asyncio
import logging
import os
import signal
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Запуск из подпапки scripts/ — корень проекта должен быть в sys.path для app.*
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
# Рабочая директория = корень (logs/, data/ ищутся относительно него)
os.chdir(PROJECT_ROOT)


def _setup_logging(verbose: bool) -> None:
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    handlers.append(RotatingFileHandler(
        log_dir / "bot_standalone.log", maxBytes=10 * 1024 * 1024,
        backupCount=5, encoding="utf-8",
    ))
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass


def _stop(nickname: str) -> int:
    """Посылает SIGTERM процессу, удерживающему lock аккаунта."""
    asyncio.run(_init_db_only())
    from app.standalone import resolve_account
    from app.instance_lock import _lock_path, fh_read_pid

    async def _resolve():
        if nickname in ("*", "all"):
            return None
        return await resolve_account(nickname)

    acc = asyncio.run(_resolve())
    if nickname in ("*", "all"):
        ids = [p.stem for p in Path("data/locks").glob("*.lock")] if Path("data/locks").exists() else []
    elif acc:
        ids = [str(acc["id"])]
    else:
        print(f"Аккаунт '{nickname}' не найден")
        return 2
    stopped = 0
    me = os.getpid()
    for aid in ids:
        pid_text = fh_read_pid(_lock_path(int(aid)))
        if not pid_text.isdigit():
            continue
        pid = int(pid_text)
        if pid == me:
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            print(f"SIGTERM → PID {pid} (бот #{aid})")
            stopped += 1
        except ProcessLookupError:
            print(f"PID {pid} не найден (бот #{aid} уже остановлен)")
    return 0 if stopped else 1


async def _init_db_only() -> None:
    from app.database import init_db
    await init_db()


def main() -> None:
    parser = argparse.ArgumentParser(description="Twitch AI Bot — standalone без панели")
    parser.add_argument("nickname", help="ник бота (или * для всех включённых)")
    parser.add_argument("--channels", default="", help="каналы через запятую (override настроек)")
    parser.add_argument("--stop", action="store_true", help="остановить запущенный standalone-бот")
    parser.add_argument("--verbose", "-v", action="store_true", help="DEBUG-логи")
    args = parser.parse_args()

    _setup_logging(args.verbose)
    _load_dotenv()

    if args.stop:
        sys.exit(_stop(args.nickname))

    channels = [c for c in args.channels.split(",") if c.strip()] or None

    from app.standalone import run_standalone
    try:
        code = asyncio.run(run_standalone(args.nickname, channels))
    except KeyboardInterrupt:
        code = 0
    sys.exit(code)


if __name__ == "__main__":
    main()
