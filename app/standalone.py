"""OPS_PLAN §2 — standalone-режим: бот работает без панели (без FastAPI).

Используется run_bot.py. Общий wiring с панелью — через app/bootstrap.py.
Один процесс — либо панель, либо N standalone-ботов; одновременное управление
одним ботом из двух процессов запрещено через app/instance_lock.py.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from pathlib import Path

from app.bootstrap import (
    autoconnect_enabled_bots,
    load_ai_state,
    wire_components,
)
from app.bot_manager import TwitchBotManager
from app.chat_analyzer import ChatAnalyzer
from app.database import get_db, init_db

logger = logging.getLogger(__name__)


async def resolve_account(nickname: str) -> dict | None:
    """Ищет ВКЛЮЧЁННЫЙ аккаунт по нику (без учёта регистра).

    Выключенного бота standalone не поднимает (§2: run_bot только для enabled).
    """
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM accounts WHERE LOWER(nickname) = LOWER(?) AND enabled = 1",
            (nickname,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def account_channels(account_id: int, override: list[str] | None = None) -> list[str]:
    if override:
        return [c.strip().lstrip("#").lower() for c in override if c.strip()]
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT channel_name FROM channels WHERE account_id = ? AND enabled = 1",
            (account_id,),
        )
        return [r["channel_name"] for r in await cur.fetchall()]
    finally:
        await db.close()


async def run_standalone(
    nickname: str,
    channels: list[str] | None = None,
    *,
    stop_event: asyncio.Event | None = None,
) -> int:
    """Поднимает бота(ов) без панели. Возвращает exit-код.

    - nickname "*" — все включённые боты (или один бот по нику);
    - channels — override каналов (иначе берутся из БД);
    - stop_event — внешняя остановка (сигнал/тест); None → работает до Ctrl+C.
    """
    from app import twitch_credentials

    await init_db()
    await twitch_credentials.load_from_db()

    from app.ai_service import AIService
    from app import ai_service as ai_service_mod

    bot_manager = TwitchBotManager()
    ai_service = AIService()
    chat_analyzer = ChatAnalyzer(ai=ai_service, send_fn=bot_manager.send_message)

    # AI-настройки + wiring (общий с панелью). broadcast-колбэков нет —
    # standalone без WS, события всё равно пишутся в bot_logs.
    await load_ai_state(ai_service)
    wire_components(bot_manager, chat_analyzer)

    # Определяем, каких ботов запускать
    if nickname in ("*", "all"):
        accounts = await _enabled_accounts()
    else:
        acc = await resolve_account(nickname)
        accounts = [acc] if acc else []
    if not accounts:
        logger.error("Аккаунт(ы) не найдены или выключены: %s", nickname)
        return 2

    # instance-lock: не даём двум процессам управлять одним ботом
    from app.instance_lock import acquire_account_lock, release_account_lock, lock_error
    locked: list[int] = []
    for acc in accounts:
        if not acquire_account_lock(acc["id"]):
            logger.error("%s — пропускаю", lock_error(acc["id"]))
        else:
            locked.append(acc["id"])
    accounts = [a for a in accounts if a["id"] in locked]
    if not accounts:
        return 3

    started = []
    try:
        # OPS_PLAN §1: per-bot папки инициализируем при старте (идемпотентно)
        from app.bot_dirs import migrate_bot_dir
        for acc in accounts:
            try:
                await migrate_bot_dir(acc["id"], acc["nickname"])
            except Exception:
                logger.warning("bot dir init failed for #%s", acc["id"], exc_info=True)

        from app.bootstrap import start_account
        for acc in accounts:
            chans = await account_channels(acc["id"], channels)
            if not chans:
                logger.warning("[%s] нет каналов — пропускаю", acc["nickname"])
                release_account_lock(acc["id"])
                locked.remove(acc["id"])
                continue
            if await start_account(bot_manager, chat_analyzer, acc, chans):
                started.append(acc["id"])
                logger.info("=== [%s] standalone-бот запущен: %s ===",
                            acc["nickname"], ", ".join(chans))

        if not started:
            return 4

        # Фоновые циклы: watchdog (§3) + обслуживание (§4: retention, бэкап, PRAGMA optimize)
        from app.maintenance import maintenance_loop
        wd = asyncio.create_task(bot_manager.watchdog_loop())
        mt = asyncio.create_task(maintenance_loop())
        try:
            if stop_event is None:
                stop_event = asyncio.Event()
                loop = asyncio.get_running_loop()
                for sig in (signal.SIGINT, signal.SIGTERM):
                    try:
                        loop.add_signal_handler(sig, stop_event.set)
                    except (NotImplementedError, RuntimeError):
                        pass
            logger.info("Standalone работает. Ctrl+C — остановить.")
            await stop_event.wait()
        finally:
            wd.cancel()
            mt.cancel()
    finally:
        for aid in list(locked):
            release_account_lock(aid)
        await bot_manager.stop_all()
        from app.database import close_db
        await close_db()
        logger.info("Standalone остановлен.")
    return 0


async def _enabled_accounts() -> list[dict]:
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM accounts WHERE enabled = 1")
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()
