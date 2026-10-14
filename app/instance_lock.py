"""OPS_PLAN §2 — instance-lock: один процесс на один аккаунт-бота.

Панель и standalone-бот (run_bot.py) не должны одновременно управлять одним
и тем же ботом: Twitch закроет второе соединение, а chat_analyzer получит
дубли сообщений. Механизм: lock-файл data/locks/{account_id}.lock с PID,
захваченный через fcntl.flock (Linux) / msvcrt (Windows). flock освобождается
автоматически при смерти процесса — «мёртвых» лockов не остаётся.

API (синхронный, вызывается и из async-кода — операции мгновенные):
- acquire_account_lock(account_id) -> bool
- release_account_lock(account_id) -> None
- is_account_locked(account_id) -> bool
- lock_error(account_id) -> str   — человекочитаемая причина для UI/CLI
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCKS_DIR = Path(os.getenv("BOT_LOCKS_DIR", str(PROJECT_ROOT / "data" / "locks")))

# last_error per account — для lock_error()
_errors: dict[int, str] = {}

_flocked: dict[int, object] = {}  # account_id -> file object (держит flock)


def _lock_path(account_id: int) -> Path:
    LOCKS_DIR.mkdir(parents=True, exist_ok=True)
    return LOCKS_DIR / f"{account_id}.lock"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return True


def acquire_account_lock(account_id: int) -> bool:
    """Захватить lock аккаунта. False — если уже удерживается живым процессом."""
    path = _lock_path(account_id)
    try:
        # flock-подход: держим файл открытым всё время владения lock'ом.
        fh = open(path, "a+")
        try:
            import fcntl
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                fh.close()
                other = ""
                try:
                    other = fh_read_pid(path)
                except Exception:
                    pass
                _errors[account_id] = (
                    f"Бот #{account_id} уже запущен другим процессом"
                    + (f" (PID {other})" if other else "")
                )
                return False
        except ImportError:
            fcntl = None  # Windows-фолбэк ниже
        if fcntl is None:
            # Windows: pid-файл с проверкой живости процесса
            existing = fh_read_pid(path)
            if existing and existing.isdigit() and _pid_alive(int(existing)) \
                    and int(existing) != os.getpid():
                fh.close()
                _errors[account_id] = f"Бот #{account_id} уже запущен другим процессом (PID {existing})"
                return False
        fh.seek(0)
        fh.truncate()
        fh.write(str(os.getpid()))
        fh.flush()
        _flocked[account_id] = fh
        _errors.pop(account_id, None)
        return True
    except Exception as exc:
        # Не даём проблемам с lock-файлами уронить запуск бота — только лог.
        logger.warning("instance_lock acquire failed (non-fatal): %s", exc)
        _errors[account_id] = f"lock error: {exc}"
        return False


def fh_read_pid(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def release_account_lock(account_id: int) -> None:
    fh = _flocked.pop(account_id, None)
    if fh is not None:
        try:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            fh.close()
        except Exception:
            pass
    _errors.pop(account_id, None)


def is_account_locked(account_id: int) -> bool:
    if account_id in _flocked:
        return True
    path = _lock_path(account_id)
    if not path.exists():
        return False
    pid = fh_read_pid(path)
    return bool(pid and pid.isdigit() and _pid_alive(int(pid)) and int(pid) != os.getpid())


def lock_error(account_id: int) -> str:
    return _errors.get(account_id, f"Бот #{account_id} уже запущен другим процессом")


__all__ = [
    "acquire_account_lock",
    "release_account_lock",
    "is_account_locked",
    "lock_error",
]
