"""Реестр ВСЕХ aiosqlite-коннектов процесса + синхронное закрытие (HANDOFF_DB_LOCK_BUG).

Проблема: коннекты, созданные мимо database._shared_db (реимпорт app.server,
тесты без tmp_db, фоновые задачи на мёртвом loop), переживают тест и держат
файл с незакоммиченной транзакцией -> flaky "database is locked".

Решение: перехватываем aiosqlite.connect, ведём реестр, в teardown закрываем
каждый коннект В ЕГО СОБСТВЕННОМ worker-потоке (sqlite3-объекты привязаны к
потоку-создателю: raw.close() из главного потока кидает ProgrammingError и
молча терялся — отсюда утечки). Если worker уже мёртв — сбрасываем ссылку
conn._connection: dealloc sqlite3 закрывает хендл без проверки потока.
"""
from __future__ import annotations

import gc
import sqlite3
import threading
import weakref
from typing import Any

import aiosqlite

try:
    from aiosqlite.core import _STOP_RUNNING_SENTINEL
except ImportError:  # pragma: no cover
    _STOP_RUNNING_SENTINEL = object()

_orig_connect = aiosqlite.connect
_registry: "weakref.WeakSet[aiosqlite.Connection]" = weakref.WeakSet()
_registry_lock = threading.Lock()
_closed_total = 0


def _tracked_connect(*args: Any, **kwargs: Any):
    conn = _orig_connect(*args, **kwargs)
    with _registry_lock:
        _registry.add(conn)
    return conn


def install() -> None:
    """Ставит патч aiosqlite.connect. Идемпотентно. Вызывать ДО импорта app.*"""
    if getattr(aiosqlite, "_registry_patched", False):
        return
    aiosqlite.connect = _tracked_connect  # type: ignore[assignment]
    aiosqlite._registry_patched = True  # type: ignore[attr-defined]


def _iter_all_connections() -> list["aiosqlite.Connection"]:
    """Все живые коннекты: из реестра + gc-скан (ловит созданные до install())."""
    seen: set[int] = set()
    out: list["aiosqlite.Connection"] = []
    with _registry_lock:
        known = list(_registry)
    for c in known:
        if id(c) not in seen:
            seen.add(id(c))
            out.append(c)
    for obj in gc.get_objects():
        if isinstance(obj, aiosqlite.Connection) and id(obj) not in seen:
            seen.add(id(obj))
            out.append(obj)
    return out


def _hard_close_one(conn: "aiosqlite.Connection") -> None:
    """Синхронно гасит коннект. Никогда не кидает и не висит дольше ~5с."""
    global _closed_total
    raw = getattr(conn, "_connection", None)
    if raw is None:
        return

    # 1. Гасим worker-поток: _running=False + close-задача В ЕГО потоке + sentinel.
    conn._running = False
    done = threading.Event()

    def _close_raw() -> None:
        r = conn._connection
        if r is not None:
            try:
                r.close()  # разрешено: выполняется в потоке-создателе
            except Exception:
                pass
        conn._connection = None
        done.set()

    tx = getattr(conn, "_tx", None)
    if tx is not None:
        try:
            tx.put_nowait((None, _close_raw))
            tx.put_nowait((None, lambda: _STOP_RUNNING_SENTINEL))
        except Exception:
            done.set()
    else:
        done.set()

    thread = getattr(conn, "_thread", None)
    if isinstance(thread, threading.Thread) and thread.is_alive():
        done.wait(timeout=2.0)
        thread.join(timeout=2.0)

    # 2. Worker не закрыл (мёртв/занят) — НИКОГДА не зовём raw.close() из
    #    чужого потока: при занятом worker он блокируется на нативном
    #    sqlite-мьютексе НАВСЕГДА (C-уровень, faulthandler не видит).
    #    Просто сбрасываем ссылку: sqlite3_close_v2 в dealloc неблокирующий.
    if conn._connection is not None:
        conn._connection = None
        gc.collect()

    conn._tx = None
    conn._thread = None
    with _registry_lock:
        _closed_total += 1


def close_all() -> int:
    """Синхронно закрывает ВСЕ живые aiosqlite-коннекты. Возвращает сколько."""
    n = 0
    for conn in _iter_all_connections():
        try:
            if getattr(conn, "_connection", None) is None:
                continue
            _hard_close_one(conn)
            n += 1
        except Exception:
            pass
    with _registry_lock:
        _registry.clear()
    return n


def open_count() -> int:
    """Сколько живых коннектов с открытым sqlite3-хендлом осталось."""
    n = 0
    for conn in _iter_all_connections():
        if getattr(conn, "_connection", None) is not None:
            n += 1
    return n


def describe_all(timeout: float = 2.0) -> list[dict]:
    """Файлы всех открытых коннектов — запрос через их же worker-потоки.

    Единственный легальный способ: sqlite3-объекты привязаны к потоку.
    Вызывать ДО close_all() при диагностике (env DB_DEBUG_LOCK=1).
    """
    out = []
    for conn in _iter_all_connections():
        raw_open = getattr(conn, "_connection", None) is not None
        info = {"conn": repr(conn), "raw_open": raw_open, "files": None}
        tx = getattr(conn, "_tx", None)
        thread = getattr(conn, "_thread", None)
        if raw_open and tx is not None and thread is not None and thread.is_alive():
            box: list = []
            ev = threading.Event()

            def _q(box=box, ev=ev, conn=conn):
                try:
                    cur = conn._connection.execute("PRAGMA database_list")
                    box.append(cur.fetchall())
                except Exception as e:  # noqa: BLE001
                    box.append(f"err:{e}")
                ev.set()

            try:
                tx.put_nowait((None, _q))
                ev.wait(timeout)
                info["files"] = str(box[0]) if box else "worker-busy/timeout"
            except Exception as e:  # noqa: BLE001
                info["files"] = f"queue-err:{e}"
        out.append(info)
    return out


def stats() -> str:
    return f"registry closed_total={_closed_total} open_now={open_count()}"
