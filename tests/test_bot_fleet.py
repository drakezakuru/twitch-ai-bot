"""Unit-тесты для функций флота ботов:
1. Чекер токенов и прокси («Светофор базы ботов») 🟢/🟡/🔴 (#1).
2. Плавный заход ботов (Staggered Join, #2).
3. Авто-запуск ботов по онлайну стримера (Live Trigger, #3).
4. Квота на канал (#4) — отбор самых активных.
5. Массовые действия чекбоксами (Bulk Actions, #6).
6. Случайная задержка между сообщениями (Q36 Humanizer Jitter).
7. Автовыбор самого давно молчавшего бота (Q35 LRU Speaker).
8. Подгонка числа аккаунтов под число зрителей (Q39).
"""
import pytest
import time
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport

from app.database import init_db, get_db
from app.server import app
from app.bot_fleet import (
    record_bot_spoken,
    get_least_recently_spoken,
    get_humanizer_jitter,
    get_humanizer_jitter_for_channel,
    sort_bots_by_activity,
    filter_and_limit_bots,
    save_channel_fleet_settings,
    check_single_account_health,
)


@pytest.mark.asyncio
async def test_q35_lru_speaker():
    """Q35: выбор самого давно молчавшего аккаунта."""
    from app import bot_fleet
    bot_fleet._last_spoken.clear()

    channel = "testchan"
    candidates = [1, 2, 3]

    # Если никто не говорил - возвращается один из кандидатов
    picked = get_least_recently_spoken(channel, candidates)
    assert picked in candidates

    # Пометим, что боты 1 и 2 говорили недавно
    now = time.time()
    record_bot_spoken(1, channel, now - 100)
    record_bot_spoken(2, channel, now - 50)
    # Бот 3 еще не говорил, должен быть выбран именно он
    picked = get_least_recently_spoken(channel, candidates)
    assert picked == 3

    # Теперь пусть и бот 3 поговорил самым последним (now)
    record_bot_spoken(3, channel, now)
    # Самым давно молчавшим стал бот 1 (now - 100)
    picked = get_least_recently_spoken(channel, candidates)
    assert picked == 1


@pytest.mark.asyncio
async def test_q36_humanizer_jitter():
    """Q36: джиттер задержки сообщений по настройкам канала."""
    await init_db()
    channel = "streamer_jitter"

    # По умолчанию без настроек (диапазон 1.0 - 5.0)
    jitter = await get_humanizer_jitter_for_channel(channel)
    assert 1.0 <= jitter <= 5.0

    # Сохраняем кастомные настройки 2.0 - 2.5
    await save_channel_fleet_settings(channel, {
        "message_jitter_min_sec": 2.0,
        "message_jitter_max_sec": 2.5,
    })
    jitter = await get_humanizer_jitter_for_channel(channel)
    assert 2.0 <= jitter <= 2.5


@pytest.mark.asyncio
async def test_quota_active_selection_and_q39_viewers_scaling():
    """Тест квоты, отбора самых активных ботов и подгонки под зрителей (Q39)."""
    bots = [
        {"id": 1, "nickname": "lurker1", "bot_role": "lurker", "contact_level": 1, "sent_messages": 0},
        {"id": 2, "nickname": "chat_pro", "bot_role": "chatter", "contact_level": 5, "sent_messages": 100},
        {"id": 3, "nickname": "chat_mid", "bot_role": "chatter", "contact_level": 2, "sent_messages": 20},
        {"id": 4, "nickname": "mod_bot", "bot_role": "moderator", "contact_level": 0, "sent_messages": 10},
    ]

    # Сортировка по активности
    sorted_bots = sort_bots_by_activity(bots)
    # chat_pro должен быть первым (chatter, contact_level=5)
    assert sorted_bots[0]["id"] == 2
    # chat_mid второй
    assert sorted_bots[1]["id"] == 3

    # Ограничение по квоте bot_limit = 2 (active_first)
    limited = await filter_and_limit_bots(bots, {"bot_limit": 2, "selection_mode": "active_first"})
    assert len(limited) == 2
    assert limited[0]["id"] == 2
    assert limited[1]["id"] == 3

    # Q39: подгонка под зрителей: 30 зрителей при 20% -> 6 ботов
    many_bots = [{"id": i, "bot_role": "chatter", "contact_level": 1, "sent_messages": i} for i in range(1, 21)]
    scaled = await filter_and_limit_bots(
        many_bots,
        {"scale_with_viewers": True, "viewer_ratio_percent": 20.0},
        current_viewers=30,
    )
    assert len(scaled) == 6


@pytest.mark.asyncio
async def test_health_check_single_and_batch():
    """Тест проверки здоровья аккаунта и прокси («Светофор»)."""
    await init_db()
    account_good = {
        "id": 101,
        "nickname": "good_bot",
        "token": "valid_token",
        "proxy": "http://127.0.0.1:8080",
    }
    account_bad_token = {
        "id": 102,
        "nickname": "bad_bot",
        "token": "expired_token",
        "proxy": "",
    }

    async def mock_validate_token(tok):
        if tok == "valid_token":
            return {"login": "good_bot", "user_id": "123"}
        return None

    with patch("app.twitch_helix.validate_token", side_effect=mock_validate_token), \
         patch("app.bot_fleet._ping_proxy", return_value="ok"):
        res_good = await check_single_account_health(account_good)
        assert res_good["status"] == "ok"
        assert res_good["proxy_ok"] is True
        assert res_good["token_valid"] is True

        res_bad = await check_single_account_health(account_bad_token)
        assert res_bad["status"] == "auth_error"
        assert res_bad["token_valid"] is False


@pytest.mark.asyncio
async def test_fleet_api_routes():
    """Тест API маршрутов bot_fleet_routes."""
    await init_db()
    db = await get_db()
    # Создадим тестовые аккаунты
    await db.execute(
        "INSERT INTO accounts (id, nickname, token, bot_role, enabled) "
        "VALUES (201, 'alpha', 't1', 'lurker', 1), (202, 'beta', 't2', 'lurker', 1)"
    )
    await db.execute(
        "INSERT INTO channels (account_id, channel_name, enabled) "
        "VALUES (201, 'stream1', 1), (202, 'stream1', 1)"
    )
    await db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Настройки флота канала
        post_res = await ac.post("/api/channels/testchan/fleet-settings", json={
            "auto_start_on_live": True,
            "auto_stop_on_offline": True,
            "bot_limit": 5,
            "selection_mode": "active_first",
            "scale_with_viewers": True,
            "viewer_ratio_percent": 15.0,
            "stagger_sec_min": 1.0,
            "stagger_sec_max": 2.0,
            "message_jitter_min_sec": 1.5,
            "message_jitter_max_sec": 3.0,
        })
        assert post_res.status_code == 200
        assert post_res.json()["ok"] is True

        get_res = await ac.get("/api/channels/testchan/fleet-settings")
        assert get_res.status_code == 200
        s = get_res.json()["settings"]
        assert s["auto_start_on_live"] is True
        assert s["bot_limit"] == 5
        assert s["scale_with_viewers"] is True

        # 2. Массовое изменение роли (Bulk Action set_role)
        bulk_res = await ac.post("/api/accounts/bulk-action", json={
            "action": "set_role",
            "ids": [201, 202],
            "role": "chatter"
        })
        assert bulk_res.status_code == 200
        assert bulk_res.json()["ok"] is True

        # Проверим, что роль сменилась
        async with db.execute("SELECT bot_role FROM accounts WHERE id = 201") as cur:
            row = await cur.fetchone()
            assert row[0] == "chatter"

        # 3. Массовое добавление канала (Bulk Action add_channel)
        add_res = await ac.post("/api/accounts/bulk-action", json={
            "action": "add_channel",
            "ids": [201],
            "channel": "newstream"
        })
        assert add_res.status_code == 200
        assert add_res.json()["ok"] is True

        # 4. Проверка здоровья через API
        with patch("app.twitch_helix.validate_token", return_value={"login": "alpha", "user_id": "1"}):
            check_res = await ac.post("/api/accounts/health-check", json={"account_ids": [201]})
            assert check_res.status_code == 200
            assert check_res.json()["ok"] is True
            assert check_res.json()["total"] == 1

        # 5. Получение сохраненного статуса здоровья
        status_res = await ac.get("/api/accounts/health-status")
        assert status_res.status_code == 200
        statuses = status_res.json()["statuses"]
        assert "201" in statuses
        assert statuses["201"]["status"] == "ok"
