"""v10.4.3: тесты raid-follow логики.

Покрытие:
1. ChatAnalyzer.set_raid_active / is_raid_active / clear_raid_active timing-логика;
2. server._load_raid_follow_settings читает дефолты для существующего аккаунта;
3. server._handle_raid_follow:
   - ничего не делает если raid_follow_enabled = 0,
   - заходит в target-канал когда включено;
4. EventSub channel.raid v1: condition содержит from_broadcaster_user_id.
"""

from __future__ import annotations

import asyncio
import sys
import time
from unittest.mock import AsyncMock, patch

import pytest

from app.ai_service import AIService
from app.chat_analyzer import ChatAnalyzer


@pytest.fixture()
def _reload_server():
    """Принудительно перезагружает app.server.

    Другие тесты в этом репо подсовывают в sys.modules['app.server'] свой
    ModuleType-стаб (см. tests/test_ai_summary.py:_install_stub_server) и
    не убирают его. Чтобы получить реальные функции _handle_raid_follow и
    _load_raid_follow_settings — выкидываем стаб из кэша.
    """
    sys.modules.pop("app.server", None)
    yield
    # После теста ничего не восстанавливаем: следующий тест сам решит,
    # нужен ли ему реальный server.


# ---------- ChatAnalyzer raid_active overlay ----------

def test_set_raid_active_extends_window():
    ca = ChatAnalyzer(ai=AIService(), send_fn=AsyncMock())
    now = time.time()
    ca.set_raid_active(7, "target", now + 60)
    assert ca.is_raid_active(7, "target") is True

    # короткий новый срок не должен обрывать существующий
    ca.set_raid_active(7, "target", now + 10)
    assert ca.is_raid_active(7, "target") is True
    assert ca._raid_active[(7, "target")] >= now + 60


def test_set_raid_active_normalizes_channel():
    ca = ChatAnalyzer(ai=AIService(), send_fn=AsyncMock())
    ca.set_raid_active(7, "#Target", time.time() + 60)
    assert ca.is_raid_active(7, "target") is True
    assert ca.is_raid_active(7, "#target") is True


def test_clear_raid_active():
    ca = ChatAnalyzer(ai=AIService(), send_fn=AsyncMock())
    ca.set_raid_active(7, "target", time.time() + 60)
    ca.clear_raid_active(7, "target")
    assert ca.is_raid_active(7, "target") is False


def test_is_raid_active_expires():
    ca = ChatAnalyzer(ai=AIService(), send_fn=AsyncMock())
    ca.set_raid_active(7, "target", time.time() - 1)  # уже истёк
    assert ca.is_raid_active(7, "target") is False
    # Истёкшая запись чистится из cache.
    assert (7, "target") not in ca._raid_active


# ---------- DB defaults + _load_raid_follow_settings ----------

@pytest.mark.asyncio
async def test_load_raid_follow_settings_defaults(tmp_db, _reload_server):
    """После init_db аккаунт получает дефолты: enabled=False, 10..60 мин, part_after=True."""
    from app.database import init_db, get_db
    from app.server import _load_raid_follow_settings

    await init_db()
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO accounts (nickname, token, enabled) VALUES (?, ?, ?)",
            ("bot1", "oauth:dummy", 1),
        )
        await db.commit()
        cur = await db.execute("SELECT id FROM accounts WHERE nickname = ?", ("bot1",))
        row = await cur.fetchone()
        account_id = row["id"]
    finally:
        await db.close()

    enabled, mn, mx, part = await _load_raid_follow_settings(account_id)
    assert enabled is False
    assert mn == 10
    assert mx == 60
    assert part is True


@pytest.mark.asyncio
async def test_load_raid_follow_settings_swaps_min_max(tmp_db, _reload_server):
    """Если min > max в БД — функция должна свапнуть для безопасности random.randint."""
    from app.database import init_db, get_db
    from app.server import _load_raid_follow_settings

    await init_db()
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO accounts (nickname, token, enabled, raid_follow_enabled, "
            "raid_follow_active_min, raid_follow_active_max) VALUES (?, ?, ?, ?, ?, ?)",
            ("bot2", "oauth:dummy", 1, 1, 50, 5),
        )
        await db.commit()
        cur = await db.execute("SELECT id FROM accounts WHERE nickname = ?", ("bot2",))
        account_id = (await cur.fetchone())["id"]
    finally:
        await db.close()

    enabled, mn, mx, _ = await _load_raid_follow_settings(account_id)
    assert enabled is True
    assert mn <= mx
    assert {mn, mx} == {5, 50}


# ---------- _handle_raid_follow ----------

@pytest.mark.asyncio
async def test_handle_raid_follow_noop_when_disabled(tmp_db, _reload_server):
    from app.database import init_db, get_db
    from app.server import _handle_raid_follow, _raid_follow_tasks

    await init_db()
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO accounts (nickname, token, enabled, raid_follow_enabled) VALUES (?, ?, ?, ?)",
            ("bot3", "oauth:dummy", 1, 0),  # disabled
        )
        await db.commit()
        cur = await db.execute("SELECT id FROM accounts WHERE nickname = ?", ("bot3",))
        account_id = (await cur.fetchone())["id"]
    finally:
        await db.close()

    payload = {
        "from_broadcaster_user_login": "streamer",
        "to_broadcaster_user_login": "target",
        "viewers": 42,
    }
    _raid_follow_tasks.clear()
    await _handle_raid_follow(account_id, "streamer", payload)
    assert (account_id, "target") not in _raid_follow_tasks


@pytest.mark.asyncio
async def test_handle_raid_follow_skips_when_origin_mismatch(tmp_db, _reload_server):
    """Если origin != from_channel — функция должна вернуть без захода в target.
    (например, если EventSub маршрутит чужое событие в коллбэк)."""
    from app.database import init_db, get_db
    from app.server import _handle_raid_follow, _raid_follow_tasks

    await init_db()
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO accounts (nickname, token, enabled, raid_follow_enabled) VALUES (?, ?, ?, ?)",
            ("bot4", "oauth:dummy", 1, 1),
        )
        await db.commit()
        cur = await db.execute("SELECT id FROM accounts WHERE nickname = ?", ("bot4",))
        account_id = (await cur.fetchone())["id"]
    finally:
        await db.close()

    _raid_follow_tasks.clear()
    payload = {
        "from_broadcaster_user_login": "OTHER_STREAMER",
        "to_broadcaster_user_login": "target",
    }
    await _handle_raid_follow(account_id, "streamer", payload)
    assert (account_id, "target") not in _raid_follow_tasks


@pytest.mark.asyncio
async def test_handle_raid_follow_joins_target_when_enabled(tmp_db, _reload_server):
    """Когда включено и origin совпадает — должна стартовать задача и (мокнутый)
    join_channel должен быть вызван с target."""
    from app.database import init_db, get_db
    from app.server import (
        _handle_raid_follow, _raid_follow_tasks, _raid_follow_until, bot_manager, chat_analyzer,
    )

    await init_db()
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO accounts (nickname, token, enabled, raid_follow_enabled, "
            "raid_follow_active_min, raid_follow_active_max) VALUES (?, ?, ?, ?, ?, ?)",
            ("bot5", "oauth:dummy", 1, 1, 1, 1),  # ровно 1 минута для быстрого теста
        )
        await db.commit()
        cur = await db.execute("SELECT id FROM accounts WHERE nickname = ?", ("bot5",))
        account_id = (await cur.fetchone())["id"]
    finally:
        await db.close()

    _raid_follow_tasks.clear()
    _raid_follow_until.clear()

    mock_status = {"connected": True, "channels": ["streamer"]}
    join_mock = AsyncMock(return_value=True)
    set_raid_active_mock = patch.object(chat_analyzer, "set_raid_active").start()
    try:
        with patch.object(bot_manager, "get_status", return_value=mock_status):
            with patch.object(bot_manager, "join_channel", new=join_mock):
                payload = {
                    "from_broadcaster_user_login": "streamer",
                    "to_broadcaster_user_login": "target",
                }
                await _handle_raid_follow(account_id, "streamer", payload)
                # Дать runner стартовать и сделать join
                await asyncio.sleep(0.05)
                join_mock.assert_awaited()
                args = join_mock.call_args.args
                assert args[0] == account_id
                assert args[1] == "target"
                # raid-active overlay должен быть взведён
                assert set_raid_active_mock.called

                # cleanup: отменяем фоновую задачу чтобы не висел timer на минуту
                task = _raid_follow_tasks.get((account_id, "target"))
                if task and not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
    finally:
        patch.stopall()
        _raid_follow_tasks.clear()
        _raid_follow_until.clear()


# ---------- EventSub channel.raid v1 condition ----------

def test_eventsub_subscriptions_includes_channel_raid():
    """SUBSCRIPTIONS должен содержать channel.raid v1.
    Сам _subscribe_all делает switch на from_broadcaster_user_id (см. eventsub.py).
    """
    from app import eventsub
    types = [t for t, _v, _e in eventsub.SUBSCRIPTIONS]
    assert "channel.raid" in types
