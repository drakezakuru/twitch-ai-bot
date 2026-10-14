"""OPS_PLAN §2 — standalone-режим: бот без панели (run_bot.py → app/standalone.py).

Проверяем на тестовой БД:
1. run_standalone поднимает включённого бота (mock Twitch), инициализирует per-bot
   папку, удерживает instance-lock и корректно останавливается по stop_event.
2. Чужой lock → отказ (код 3): панель и standalone не могут управлять одним ботом.
3. Неизвестный/выключенный аккаунт → код 2, нет каналов → код 4.
4. Lock освобождается после остановки.
"""
from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.asyncio


def _patch_start_bot(monkeypatch, started: list[tuple]):
    from app.bot_manager import TwitchBotManager

    async def fake_start_bot(self, account_id, nickname, token, channels, proxy=""):
        started.append((account_id, tuple(channels)))
        return True

    monkeypatch.setattr(TwitchBotManager, "start_bot", fake_start_bot)


async def _seed_enabled_account(nickname: str = "standbot", enabled: int = 1) -> int:
    from app import database
    db = await database.get_db()
    try:
        cur = await db.execute("SELECT id FROM accounts WHERE nickname = ?", (nickname,))
        row = await cur.fetchone()
        if row:
            await db.execute("UPDATE accounts SET enabled = ? WHERE id = ?", (enabled, row["id"]))
            await db.commit()
            return row["id"]
        await db.execute(
            "INSERT INTO accounts (nickname, token, enabled) VALUES (?, 'oauth:stand', ?)",
            (nickname, enabled),
        )
        await db.commit()
        cur = await db.execute("SELECT id FROM accounts WHERE nickname = ?", (nickname,))
        return (await cur.fetchone())["id"]
    finally:
        await db.close()


def _isolate_bot_dirs(monkeypatch, tmp_db):
    from app import bot_dirs
    monkeypatch.setattr(bot_dirs, "BOTS_ROOT", tmp_db.parent / "bots")


async def test_run_standalone_starts_and_stops(tmp_db, monkeypatch):
    from app import database
    await database.init_db()
    _isolate_bot_dirs(monkeypatch, tmp_db)
    account_id = await _seed_enabled_account()

    started: list[tuple] = []
    _patch_start_bot(monkeypatch, started)

    from app.standalone import run_standalone
    stop_event = asyncio.Event()
    stop_event.set()  # старт → сразу корректная остановка

    code = await asyncio.wait_for(
        run_standalone("standbot", channels=["testchan"], stop_event=stop_event),
        timeout=30,
    )
    assert code == 0
    assert started and started[0][0] == account_id
    assert started[0][1] == ("testchan",)

    # Per-bot папка инициализирована (OPS_PLAN §1 — идемпотентно при старте)
    from app.bot_dirs import BOTS_ROOT
    assert (BOTS_ROOT / f"{account_id}_standbot").is_dir()

    # Lock освобождён (acquire+release, чтобы не удержать его для следующих тестов)
    from app.instance_lock import acquire_account_lock, release_account_lock
    assert acquire_account_lock(account_id), "lock должен быть свободен после остановки"
    release_account_lock(account_id)


async def test_run_standalone_respects_instance_lock(tmp_db, monkeypatch):
    from app import database
    await database.init_db()
    _isolate_bot_dirs(monkeypatch, tmp_db)
    account_id = await _seed_enabled_account()

    from app.instance_lock import acquire_account_lock, release_account_lock
    assert acquire_account_lock(account_id)  # «панель» держит бота

    started: list[tuple] = []
    _patch_start_bot(monkeypatch, started)

    from app.standalone import run_standalone
    stop_event = asyncio.Event()
    stop_event.set()
    code = await asyncio.wait_for(
        run_standalone("standbot", channels=["c"], stop_event=stop_event),
        timeout=30,
    )
    assert code == 3, "второй процесс не должен управлять тем же ботом"
    assert not started

    release_account_lock(account_id)


async def test_run_standalone_unknown_account(tmp_db, monkeypatch):
    from app import database
    await database.init_db()
    _isolate_bot_dirs(monkeypatch, tmp_db)
    _patch_start_bot(monkeypatch, [])

    from app.standalone import run_standalone
    stop_event = asyncio.Event()
    stop_event.set()
    code = await run_standalone("net-takogo-bota", channels=["c"], stop_event=stop_event)
    assert code == 2


async def test_run_standalone_disabled_account(tmp_db, monkeypatch):
    from app import database
    await database.init_db()
    _isolate_bot_dirs(monkeypatch, tmp_db)
    await _seed_enabled_account("offbot", enabled=0)
    _patch_start_bot(monkeypatch, [])

    from app.standalone import run_standalone
    stop_event = asyncio.Event()
    stop_event.set()
    code = await run_standalone("offbot", channels=["c"], stop_event=stop_event)
    assert code == 2


async def test_run_standalone_without_channels(tmp_db, monkeypatch):
    from app import database
    await database.init_db()
    _isolate_bot_dirs(monkeypatch, tmp_db)
    await _seed_enabled_account("nochan")
    _patch_start_bot(monkeypatch, [])

    from app.standalone import run_standalone
    stop_event = asyncio.Event()
    stop_event.set()
    # channels=None → берутся из БД; у бота их нет → пропуск → код 4
    code = await run_standalone("nochan", channels=None, stop_event=stop_event)
    assert code == 4
