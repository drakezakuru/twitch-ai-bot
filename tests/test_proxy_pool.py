"""Unit-тесты для модуля общего пула прокси (Proxy Pool):
1. Нормализация и маскирование различных форматов прокси.
2. Добавление, дедупликация и получение списка из пула.
3. Столбление (claim) прокси ботом (авто и ручной выбор), синхронизация с accounts.proxy.
4. Освобождение (release) прокси ботом.
5. Автоматическая замена (failover) при отказе прокси.
6. Очистка нерабочих (clean-dead) и удаление.
7. REST API эндпоинты пула и привязки к ботам.
"""
import pytest
from httpx import AsyncClient, ASGITransport

from app.database import init_db, get_db
from app.server import app
from app.proxy_pool import (
    normalize_proxy_string,
    mask_proxy_url,
    extract_proxy_identity,
    add_proxies_to_pool,
    get_proxy_pool_items,
    claim_proxy_for_bot,
    release_proxy_for_bot,
    failover_bot_proxy,
    clean_dead_proxies_from_pool,
    clean_duplicate_proxies_from_pool,
    clean_slow_proxies_from_pool,
    delete_proxy_from_pool,
    get_proxy_pool_settings,
    save_proxy_pool_settings,
)


def test_normalize_and_mask_proxy():
    # 1. host:port:user:pass (стандартный формат провайдеров прокси)
    url1 = normalize_proxy_string("185.220.101.5:8080:my_user:secret_pass123")
    assert url1 == "http://my_user:secret_pass123@185.220.101.5:8080"
    assert mask_proxy_url(url1) == "http://my_user:****@185.220.101.5:8080"

    # 2. user:pass@host:port
    url2 = normalize_proxy_string("admin:p@ss!@95.110.200.1:3128")
    assert "95.110.200.1:3128" in url2
    assert "admin" in url2
    masked2 = mask_proxy_url(url2)
    assert "****" in masked2
    assert "p@ss!" not in masked2

    # 3. socks5://host:port
    url3 = normalize_proxy_string("socks5://127.0.0.1:9050")
    assert url3 == "socks5://127.0.0.1:9050"
    assert mask_proxy_url(url3) == "socks5://127.0.0.1:9050"

    # 4. host:port
    url4 = normalize_proxy_string("45.15.14.12:8888")
    assert url4 == "http://45.15.14.12:8888"

    # 5. Мусорные строки и невалидные порты (не должны падать)
    assert normalize_proxy_string("not_a_proxy") is None
    assert normalize_proxy_string("http://") is None
    assert normalize_proxy_string("1.2.3.4:abc") is None
    assert normalize_proxy_string("http://47.108.159.113:9098socks4:") is None
    assert normalize_proxy_string("http://47.108.159.113:999999") is None


@pytest.mark.asyncio
async def test_auto_split_sticky_proxies():
    """Проверка автоматического разделения слипшихся URL без переноса строки."""
    await init_db()
    db = await get_db()
    try:
        await db.execute("DELETE FROM proxy_pool")
        await db.commit()
    finally:
        await db.close()

    sticky = "http://47.108.159.113:9098socks4://192.111.137.37:18762"
    res = await add_proxies_to_pool(sticky)
    assert res["ok"] is True
    assert res["added"] == 2
    assert res["invalid"] == 0


@pytest.mark.asyncio
async def test_add_and_list_proxies():
    await init_db()
    # Очищаем таблицу пула для чистоты теста
    db = await get_db()
    try:
        await db.execute("DELETE FROM proxy_pool")
        await db.commit()
    finally:
        await db.close()

    raw_text = """
    # Комментарий
    192.168.1.1:8080:user1:pass1
    192.168.1.2:8080:user2:pass2
    192.168.1.1:8080:user1:pass1   # дубликат
    bad_line_ignored
    http://user3:pass3@192.168.1.3:3128
    """

    res = await add_proxies_to_pool(raw_text)
    assert res["ok"] is True
    assert res["added"] == 3
    assert res["duplicates"] == 1
    assert res["invalid"] == 1

    items = await get_proxy_pool_items()
    assert len(items) == 3
    # Проверяем маскирование паролей в выдаче
    for item in items:
        assert "***" in item["masked_url"]
        assert "pass" not in item["masked_url"]
        assert item["is_assigned"] is False


@pytest.mark.asyncio
async def test_claim_and_release_proxy_for_bot():
    await init_db()
    db = await get_db()
    try:
        await db.execute("DELETE FROM proxy_pool")
        await db.execute("DELETE FROM accounts WHERE id >= 900")
        await db.execute("INSERT INTO accounts (id, nickname, token, proxy) VALUES (901, 'BotOne', 'oauth:1', '')")
        await db.execute("INSERT INTO accounts (id, nickname, token, proxy) VALUES (902, 'BotTwo', 'oauth:2', '')")
        await db.commit()
    finally:
        await db.close()

    await add_proxies_to_pool("10.0.0.1:8000:u1:p1\n10.0.0.2:8000:u2:p2")
    items = await get_proxy_pool_items()
    assert len(items) == 2
    p1_id = items[0]["id"]
    p2_id = items[1]["id"]

    # 1. Автовыбор свободного прокси для бота 901
    claim1 = await claim_proxy_for_bot(901)
    assert claim1["ok"] is True
    assert claim1["proxy_id"] in (p1_id, p2_id)

    # Проверяем, что в таблице accounts прописался proxy
    db = await get_db()
    try:
        cur = await db.execute("SELECT proxy FROM accounts WHERE id = 901")
        acc1 = await cur.fetchone()
        assert acc1["proxy"] == claim1["proxy_url"]
    finally:
        await db.close()

    # 2. Ручной выбор конкретного свободного прокси для бота 902
    other_id = p2_id if claim1["proxy_id"] == p1_id else p1_id
    claim2 = await claim_proxy_for_bot(902, proxy_id=other_id)
    assert claim2["ok"] is True
    assert claim2["proxy_id"] == other_id

    # 3. Попытка занять уже занятый прокси
    err_claim = await claim_proxy_for_bot(901, proxy_id=other_id)
    assert err_claim["ok"] is False
    assert "уже занят" in err_claim["error"]

    # 4. Освобождение прокси ботом 901
    rel = await release_proxy_for_bot(901)
    assert rel["ok"] is True

    # Проверяем accounts.proxy и статус в пуле
    db = await get_db()
    try:
        cur = await db.execute("SELECT proxy FROM accounts WHERE id = 901")
        acc1 = await cur.fetchone()
        assert acc1["proxy"] == ""

        cur = await db.execute("SELECT assigned_account_id FROM proxy_pool WHERE id = ?", (claim1["proxy_id"],))
        p_row = await cur.fetchone()
        assert p_row["assigned_account_id"] is None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_failover_bot_proxy():
    await init_db()
    db = await get_db()
    try:
        await db.execute("DELETE FROM proxy_pool")
        await db.execute("DELETE FROM accounts WHERE id = 903")
        await db.execute("INSERT INTO accounts (id, nickname, token, proxy) VALUES (903, 'BotThree', 'oauth:3', '')")
        await db.commit()
    finally:
        await db.close()

    await add_proxies_to_pool("10.0.0.10:8000:u:p\n10.0.0.20:8000:u:p")
    # Столбим первый прокси
    c = await claim_proxy_for_bot(903)
    assert c["ok"] is True
    first_url = c["proxy_url"]

    # Эмулируем отказ прокси -> вызываем failover
    from app.server import bot_manager
    class _MockInst:
        proxy = first_url
        bot = None
    mock_inst = _MockInst()
    bot_manager.instances[903] = mock_inst
    try:
        fo = await failover_bot_proxy(903, reason="Connection timed out")
        assert fo["ok"] is True
        assert fo["new_proxy"] != fo["old_proxy"]
        assert mock_inst.proxy == fo["new_proxy_url"]
    finally:
        bot_manager.instances.pop(903, None)

    # Проверяем, что старый прокси помечен как error
    db = await get_db()
    try:
        cur = await db.execute("SELECT status, last_error, assigned_account_id FROM proxy_pool WHERE url = ?", (first_url,))
        dead_p = await cur.fetchone()
        assert dead_p["status"] == "error"
        assert "Connection timed out" in dead_p["last_error"]
        assert dead_p["assigned_account_id"] is None

        # Очистка мертвых прокси
        cleaned = await clean_dead_proxies_from_pool()
        assert cleaned >= 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_proxy_pool_settings():
    await init_db()
    s = await get_proxy_pool_settings()
    assert "auto_failover" in s
    assert "notify_owner" in s

    # Сохраняем новые настройки
    await save_proxy_pool_settings(auto_failover=False, notify_owner=True)
    s2 = await get_proxy_pool_settings()
    assert s2["auto_failover"] is False
    assert s2["notify_owner"] is True


@pytest.mark.asyncio
async def test_proxy_pool_api_endpoints():
    await init_db()
    db = await get_db()
    try:
        await db.execute("DELETE FROM proxy_pool")
        await db.execute("DELETE FROM accounts WHERE id = 904")
        await db.execute("INSERT INTO accounts (id, nickname, token, proxy) VALUES (904, 'BotFour', 'oauth:4', '')")
        await db.commit()
    finally:
        await db.close()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Добавление через API
        resp = await ac.post("/api/proxy-pool/add", json={"text": "10.0.0.50:8080:api_u:api_p"})
        assert resp.status_code == 200
        assert resp.json()["added"] == 1

        # 2. Получение списка
        resp = await ac.get("/api/proxy-pool")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert len(data["items"]) >= 1
        p_id = data["items"][0]["id"]

        # 3. Закрепление за ботом через API
        resp = await ac.post(f"/api/accounts/904/claim-proxy", json={"proxy_id": p_id})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # 4. Отвязка прокси через API
        resp = await ac.post("/api/accounts/904/release-proxy")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # 5. Массовое авто-столбление прокси
        resp = await ac.post("/api/accounts/bulk-claim-proxies", json={"account_ids": [904]})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["claimed_count"] == 1

        # 6. Удаление прокси из пула
        resp = await ac.delete(f"/api/proxy-pool/{p_id}/delete")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_clean_slow_proxies():
    """Тест очистки медленных (пинг >= max_ping_ms) и ошибочных прокси."""
    await init_db()
    db = await get_db()
    try:
        await db.execute("DELETE FROM proxy_pool")
        # Вставляем 3 прокси: быстрый, медленный, битый
        await db.execute("""
            INSERT INTO proxy_pool (url, status, latency_ms)
            VALUES ('http://1.1.1.1:8080', 'ok', 350.0)
        """)
        await db.execute("""
            INSERT INTO proxy_pool (url, status, latency_ms)
            VALUES ('http://2.2.2.2:8080', 'slow', 2450.0)
        """)
        await db.execute("""
            INSERT INTO proxy_pool (url, status, latency_ms)
            VALUES ('http://3.3.3.3:8080', 'error', 0.0)
        """)
        await db.commit()
    finally:
        await db.close()

    # Вызываем очистку с порогом 2000 мс
    cleaned = await clean_slow_proxies_from_pool(max_ping_ms=2000.0)
    assert cleaned == 2

    # Проверяем, что остался только быстрый прокси
    items = await get_proxy_pool_items()
    assert len(items) == 1
    assert items[0]["latency_ms"] == 350.0

    # Проверяем также через HTTP API
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Добавим еще один медленный
        db = await get_db()
        try:
            await db.execute("""
                INSERT INTO proxy_pool (url, status, latency_ms)
                VALUES ('http://4.4.4.4:8080', 'slow', 2100.0)
            """)
            await db.commit()
        finally:
            await db.close()

        resp = await ac.post("/api/proxy-pool/clean-slow", json={"max_ping_ms": 2000})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["deleted"] == 1


@pytest.mark.asyncio
async def test_claim_proxies_for_active_and_settings():
    """Тест раздачи прокси только активным ботам (enabled=1, пропуская 0) и настройки auto_clean."""
    await init_db()
    db = await get_db()
    try:
        await db.execute("DELETE FROM proxy_pool")
        await db.execute("DELETE FROM accounts WHERE id IN (995, 996)")
        # Бот 995: включен (enabled=1), Бот 996: выключен (enabled=0, юзать не хотим)
        await db.execute("INSERT INTO accounts (id, nickname, token, enabled, proxy) VALUES (995, 'ActiveBot', 'oauth:a', 1, '')")
        await db.execute("INSERT INTO accounts (id, nickname, token, enabled, proxy) VALUES (996, 'DisabledBot', 'oauth:d', 0, '')")
        # Добавляем 1 свободный прокси
        await db.execute("INSERT INTO proxy_pool (url, status, latency_ms) VALUES ('http://5.5.5.5:8080', 'ok', 400.0)")
        await db.commit()
    finally:
        await db.close()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Раздаем только активным
        resp = await ac.post("/api/accounts/claim-proxies-for-active")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["active_total"] == 1
        assert data["claimed_count"] == 1

        # Проверяем в БД: активный получил прокси, выключенный остался без прокси
        db = await get_db()
        try:
            cur1 = await db.execute("SELECT proxy FROM accounts WHERE id = 995")
            assert (await cur1.fetchone())["proxy"] == "http://5.5.5.5:8080"

            cur2 = await db.execute("SELECT proxy FROM accounts WHERE id = 996")
            assert (await cur2.fetchone())["proxy"] == ""
        finally:
            await db.close()

        # Проверяем сохранение auto_clean в settings
        s_resp = await ac.post("/api/proxy-pool/settings", json={"auto_failover": True, "notify_owner": True, "auto_clean": True})
        assert s_resp.status_code == 200
        assert s_resp.json()["auto_clean"] is True


@pytest.mark.asyncio
async def test_twitch_bot_client_proxy_wrapping():
    """Тест перехвата ws_connect и request в TwitchBotClient при наличии instance.proxy."""
    from app.irc.client import TwitchBotClient
    from app.irc.types import BotInstance
    import aiohttp

    inst = BotInstance(
        account_id=999,
        nickname="ProxyBot",
        token="oauth:fake",
        channels=["testchan"],
        proxy="http://user:pass@127.0.0.1:8888",
    )
    bot = TwitchBotClient(inst)

    recorded_ws_kwargs = {}
    recorded_req_kwargs = {}

    class DummySession:
        async def ws_connect(self, url, **kwargs):
            recorded_ws_kwargs.update(kwargs)
            return None

        async def _request(self, method, url, **kwargs):
            recorded_req_kwargs.update(kwargs)
            return None

    dummy = DummySession()
    bot._apply_proxy(dummy)

    # 1. Проверяем ws_connect
    await dummy.ws_connect("wss://irc-ws.chat.twitch.tv:443")
    assert recorded_ws_kwargs.get("proxy") == "http://user:pass@127.0.0.1:8888"

    # 2. Проверяем _request (HTTP валидация и helix)
    await dummy._request("GET", "https://id.twitch.tv/oauth2/validate")
    assert recorded_req_kwargs.get("proxy") == "http://user:pass@127.0.0.1:8888"

    # 3. Динамическая смена при failover
    inst.proxy = "http://newproxy:9999"
    recorded_ws_kwargs.clear()
    await dummy.ws_connect("wss://irc-ws.chat.twitch.tv:443")
    assert recorded_ws_kwargs.get("proxy") == "http://newproxy:9999"


@pytest.mark.asyncio
async def test_clean_slow_proxies_only_unassigned():
    """Тест: фоновая чистка с only_unassigned=True удаляет только свободные медленные прокси."""
    await init_db()
    db = await get_db()
    try:
        await db.execute("DELETE FROM proxy_pool")
        await db.execute("DELETE FROM accounts WHERE id = 998")
        await db.execute("INSERT INTO accounts (id, nickname, token, proxy) VALUES (998, 'BusyBot', 'oauth:b', 'http://assigned:8080')")
        # 1-й медленный: свободен
        await db.execute("INSERT INTO proxy_pool (url, status, latency_ms, assigned_account_id) VALUES ('http://free_slow:8080', 'ok', 3500.0, NULL)")
        # 2-й медленный: привязан к активному боту
        await db.execute("INSERT INTO proxy_pool (url, status, latency_ms, assigned_account_id) VALUES ('http://assigned:8080', 'ok', 4000.0, 998)")
        await db.commit()
    finally:
        await db.close()

    # Фоновая чистка: only_unassigned=True
    deleted = await clean_slow_proxies_from_pool(2000.0, only_unassigned=True)
    assert deleted == 1

    db = await get_db()
    try:
        cur = await db.execute("SELECT url FROM proxy_pool")
        rows = [r["url"] for r in await cur.fetchall()]
        assert "http://free_slow:8080" not in rows
        assert "http://assigned:8080" in rows

        # Прокси активного бота в accounts НЕ затерт!
        cur2 = await db.execute("SELECT proxy FROM accounts WHERE id = 998")
        assert (await cur2.fetchone())["proxy"] == "http://assigned:8080"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_stream_health_returns_proxy_fields():
    """Тест: эндпоинт /api/stream-health отдаёт поля proxy, proxy_latency_ms и proxy_status."""
    await init_db()
    db = await get_db()
    try:
        await db.execute("DELETE FROM channels WHERE channel_name = 'healthchan'")
        await db.execute("DELETE FROM accounts WHERE id = 999")
        await db.execute("DELETE FROM proxy_pool WHERE url = 'http://testuser:pass@1.2.3.4:8080'")
        await db.execute("INSERT INTO accounts (id, nickname, token, enabled, bot_role, proxy) VALUES (999, 'HealthBot', 'oauth:h', 1, 'chatter', 'http://testuser:pass@1.2.3.4:8080')")
        await db.execute("INSERT INTO channels (account_id, channel_name, enabled) VALUES (999, 'healthchan', 1)")
        await db.execute("INSERT INTO proxy_pool (url, latency_ms, status) VALUES ('http://testuser:pass@1.2.3.4:8080', 215.5, 'ok')")
        await db.commit()
    finally:
        await db.close()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/stream-health?channel=healthchan")
        assert resp.status_code == 200
        data = resp.json()
        assert "channels" in data
        ch = data["channels"][0]
        bot = ch["bots"][0]
        assert bot["nickname"] == "HealthBot"
        assert "***" in bot["proxy"]  # маскированный URL
        assert bot["proxy_latency_ms"] == 215.5
        assert bot["proxy_status"] == "ok"


def test_extract_proxy_identity():
    """Проверка извлечения канонического ключа прокси для поиска повторок."""
    # 1. IP адрес с портами и протоколами - для Твича 1 IP = 1 бот, ключ совпадает независимо от порта
    id1 = extract_proxy_identity("185.220.101.5:8080:my_user:secret_pass123")
    assert id1 == ("185.220.101.5", 0, "")

    id2 = extract_proxy_identity("socks5://185.220.101.5:8080")
    assert id2 == ("185.220.101.5", 0, "")

    id3 = extract_proxy_identity("http://185.220.101.5:8080")
    assert id3 == ("185.220.101.5", 0, "")

    # 2. Другой порт на том же IP - тоже дубликат IP (один исходящий адрес на Twitch)
    id_other_port = extract_proxy_identity("185.220.101.5:8081")
    assert id_other_port == ("185.220.101.5", 0, "")
    assert id_other_port == id1

    # Другой IP адрес - уникальный
    id_different_ip = extract_proxy_identity("185.220.101.6:8080")
    assert id_different_ip == ("185.220.101.6", 0, "")
    assert id_different_ip != id1

    # 3. Доменный шлюз (ротируемые прокси): разные пользователи/порты = разные сессии
    id_gw1 = extract_proxy_identity("gate.smartproxy.com:7000:session1:pass1")
    id_gw2 = extract_proxy_identity("gate.smartproxy.com:7000:session2:pass2")
    id_gw_other_port = extract_proxy_identity("gate.smartproxy.com:7001:session1:pass1")
    id_gw1_dup = extract_proxy_identity("http://session1:pass1@gate.smartproxy.com:7000")
    assert id_gw1 == ("gate.smartproxy.com", 7000, "session1")
    assert id_gw2 == ("gate.smartproxy.com", 7000, "session2")
    assert id_gw1 != id_gw2
    assert id_gw1 != id_gw_other_port
    assert id_gw1 == id_gw1_dup

    # 4. Невалидные строки
    assert extract_proxy_identity("") is None
    assert extract_proxy_identity("invalid_string") is None


@pytest.mark.asyncio
async def test_add_proxies_deduplication():
    """Тест автоматической проверки повторок при добавлении списка прокси."""
    await init_db()
    db = await get_db()
    try:
        await db.execute("DELETE FROM proxy_pool")
        await db.commit()
    finally:
        await db.close()

    # Пачка содержит один и тот же адрес в разных форматах и дубли
    batch1 = """
    192.168.10.1:8080
    http://192.168.10.1:8080
    socks5://192.168.10.1:8080
    192.168.10.2:8080:u1:p1
    """
    res1 = await add_proxies_to_pool(batch1)
    assert res1["ok"] is True
    assert res1["added"] == 2  # 192.168.10.1:8080 (1 раз) + 192.168.10.2:8080
    assert res1["duplicates"] == 2  # 2 повторки 192.168.10.1:8080 отсеяны

    # Вторая пачка: попытка повторно добавить прокси, уже имеющийся в базе
    batch2 = """
    http://user_x:pass_y@192.168.10.1:8080
    192.168.10.3:9090
    """
    res2 = await add_proxies_to_pool(batch2)
    assert res2["ok"] is True
    assert res2["added"] == 1  # добавлен только новый 192.168.10.3:9090
    assert res2["duplicates"] == 1  # 192.168.10.1:8080 опознан как дубликат уже в БД


@pytest.mark.asyncio
async def test_clean_duplicate_proxies_from_pool_logic():
    """Тест очистки дубликатов: сохранение лучшего прокси и защита привязанного бота."""
    await init_db()
    db = await get_db()
    try:
        await db.execute("DELETE FROM proxy_pool")
        await db.execute("DELETE FROM accounts WHERE id = 991")
        await db.execute("INSERT INTO accounts (id, nickname, token, proxy) VALUES (991, 'BotDup', 'oauth:d', '')")

        # Набор 1: два дубликата для 10.10.10.1:8080.
        # Один со статусом 'error', второй 'ok' с низким пингом 95ms. 'ok' должен сохраниться.
        await db.execute("INSERT INTO proxy_pool (id, url, status, latency_ms) VALUES (101, 'http://10.10.10.1:8080', 'error', 0)")
        await db.execute("INSERT INTO proxy_pool (id, url, status, latency_ms) VALUES (102, 'socks5://10.10.10.1:8080', 'ok', 95.0)")

        # Набор 2: два дубликата для 10.10.10.2:8080.
        # Первый (id=103) привязан к боту 991. Он должен сохраниться, а непривязанный id=104 удален.
        await db.execute("INSERT INTO proxy_pool (id, url, status, latency_ms, assigned_account_id) VALUES (103, 'http://10.10.10.2:8080', 'untested', 0, 991)")
        await db.execute("INSERT INTO proxy_pool (id, url, status, latency_ms, assigned_account_id) VALUES (104, 'socks5://10.10.10.2:8080', 'ok', 50.0, NULL)")

        # Набор 3: уникальный прокси (без дубликатов)
        await db.execute("INSERT INTO proxy_pool (id, url, status, latency_ms) VALUES (105, 'http://10.10.10.3:8080', 'ok', 120.0)")

        # Набор 4: разные порты на одном IP (10.10.10.4:1111 и 10.10.10.4:2222).
        # Быстрый 'ok' 40ms (id=107) должен сохраниться, а медленный 1500ms (id=106) удален как дубликат IP.
        await db.execute("INSERT INTO proxy_pool (id, url, status, latency_ms) VALUES (106, 'socks5://10.10.10.4:1111', 'ok', 1500.0)")
        await db.execute("INSERT INTO proxy_pool (id, url, status, latency_ms) VALUES (107, 'socks5://10.10.10.4:2222', 'ok', 40.0)")

        await db.commit()
    finally:
        await db.close()

    res = await clean_duplicate_proxies_from_pool()
    assert res["deleted"] == 3
    assert res["unique_remaining"] == 4

    items = await get_proxy_pool_items()
    remaining_ids = {x["id"] for x in items}
    # id=102 сохранен (ok), id=101 удален
    assert 102 in remaining_ids
    assert 101 not in remaining_ids
    # id=103 сохранен (assigned к боту 991), id=104 удален
    assert 103 in remaining_ids
    assert 104 not in remaining_ids
    # id=105 уникальный сохранен
    assert 105 in remaining_ids
    # id=107 (быстрый порт на том же IP) сохранен, id=106 удален
    assert 107 in remaining_ids
    assert 106 not in remaining_ids


@pytest.mark.asyncio
async def test_api_clean_duplicates_endpoint():
    """Тест API эндпоинта POST /api/proxy-pool/clean-duplicates."""
    await init_db()
    db = await get_db()
    try:
        await db.execute("DELETE FROM proxy_pool")
        await db.execute("INSERT INTO proxy_pool (id, url, status) VALUES (201, 'http://172.16.0.1:8080', 'ok')")
        await db.execute("INSERT INTO proxy_pool (id, url, status) VALUES (202, 'socks5://172.16.0.1:8080', 'untested')")
        await db.commit()
    finally:
        await db.close()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/proxy-pool/clean-duplicates")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["deleted"] == 1
        assert data["unique_remaining"] == 1
