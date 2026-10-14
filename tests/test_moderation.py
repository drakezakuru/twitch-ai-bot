"""MODERATION_PLAN §5: тесты модерации чата и антиспама.

Проверяем:
1. Unit: словари загружаются, слово/regex matching, severity→action маппинг,
   частичная замена сохраняет длину, приоритет custom правил.
2. Антиспам: caps/links/repeat/emote/copypasta детект (пороговые кейсы).
3. API: CRUD правил, журнал, проверка сообщения, режимы off/log_only/replace/full.
4. Изоляция: правила per-account не смешиваются; channel='' = все каналы.
5. Исходящая модерация: заблокированный ответ бота не отправляется и логируется.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app import moderation as M
from app import database

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def _reset_moderation_cache(tmp_db, disable_auth):
    """Каждый тест получает чистые кэши движка и чистую временную БД."""
    M.invalidate_cache()
    await database.init_db()
    yield
    M.invalidate_cache()


async def _make_account(nickname: str = "bot1", **cols) -> int:
    db = await database.get_db()
    try:
        cur = await db.execute("INSERT INTO accounts (nickname, token) VALUES (?, ?)", (nickname, "oauth:tok"))
        await db.commit()
        aid = cur.lastrowid
        if cols:
            sets = ", ".join(f"{k} = ?" for k in cols)
            await db.execute(f"UPDATE accounts SET {sets} WHERE id = ?", (*cols.values(), aid))
            await db.commit()
    finally:
        await db.close()
    M.invalidate_cache(aid)
    return aid


async def _client() -> AsyncClient:
    from fastapi import FastAPI
    from app.routes import router
    from app.moderation_routes import router as moderation_policy_router
    app = FastAPI()
    app.include_router(router)
    app.include_router(moderation_policy_router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ──────────────── 1. Unit: ядро ────────────────


def test_builtin_dicts_load():
    rules = M.load_builtin_dicts()
    assert len(rules) > 50
    langs = {r.lang for r in rules}
    assert {"ru", "en", "ua"} <= langs
    cats = {r.category for r in rules}
    assert {"insult", "hate", "threat", "sexual"} <= cats
    # всё в пределах severity 1-5
    assert all(1 <= r.severity <= 5 for r in rules)


def test_severity_to_action_mapping():
    # План §1: 1-2 = replace, 3 = block, 4-5 = block (+timeout при full)
    assert M.severity_to_action(1) == "replace"
    assert M.severity_to_action(2) == "replace"
    assert M.severity_to_action(3) == "block"
    assert M.severity_to_action(4) == "block"
    assert M.severity_to_action(5) == "block"


def test_word_matching_prefix_and_regex():
    # Стем ловит словоформы
    rx = M._compile_pattern(M._normalize("уебищ"))
    assert M._find_matches(rx, M._normalize("он уебище"))
    assert M._find_matches(rx, M._normalize("какое уебища!"))
    # re: — произвольный regex: точная граница не ловит «геймер»
    rx2 = M._compile_pattern(M._normalize(r"re:\bгей\b"))
    assert M._find_matches(rx2, M._normalize("гей"))
    assert not M._find_matches(rx2, M._normalize("геймер"))
    # а расширенный regex ловит оба варианта
    rx2b = M._compile_pattern(M._normalize(r"re:\bгей(мер)?\b"))
    assert M._find_matches(rx2b, M._normalize("гей"))
    assert M._find_matches(rx2b, M._normalize("геймер"))
    # нейтральное слово не матчится
    rx3 = M._compile_pattern(M._normalize("лох"))
    assert not M._find_matches(rx3, M._normalize("привет друг"))


def test_mask_preserves_length():
    text = "ты дебил и вообще"
    matches = M._find_matches(M._compile_pattern(M._normalize("дебил")), M._normalize(text))
    masked = M._mask_spans(text, matches)
    assert len(masked) == len(text)
    assert masked == "ты ***** и вообще"


async def test_check_message_insult_full_mode():
    aid = await _make_account(moderation_mode="full")
    verdicts = await M.check_message(aid, "chan", "u1", "он уебище")
    assert verdicts, "ожидали вердикт"
    v = verdicts[0]
    assert v.category == "insult"
    assert v.action == "block"
    assert v.severity >= 3


async def test_check_message_replace_mode_masks():
    aid = await _make_account(moderation_mode="replace")
    # 'долбоёб' — sexual sev3 → block; нужно replace-слово: 'дебил' sev2
    verdicts = await M.check_message(aid, "chan", "u1", "ты дебил")
    assert verdicts[0].action == "replace"
    assert verdicts[0].masked_text is not None
    assert "*" in verdicts[0].masked_text
    assert "дебил" not in verdicts[0].masked_text


async def test_check_message_log_only_downgrades():
    aid = await _make_account(moderation_mode="log_only")
    verdicts = await M.check_message(aid, "chan", "u1", "он уебище")
    assert verdicts[0].action == "log"  # всё деградирует до log
    assert verdicts[0].rule_action == "block"  # но намерение правила сохранено


async def test_check_message_off_mode_only_threats():
    aid = await _make_account(moderation_mode="off")
    # Оскорбление в off — пусто
    assert await M.check_message(aid, "chan", "u1", "он уебище") == []
    # Угроза — всегда в журнал (решение владельца)
    v = await M.check_message(aid, "chan", "u1", "я тебя найду тебя и запугаю")
    assert v and all(x.category == "threat" and x.action == "log" for x in v)


async def test_custom_rule_priority_over_builtin():
    aid = await _make_account(moderation_mode="full")
    db = await database.get_db()
    try:
        # 'дебил' встроенный = sev2 (replace). Кастомное правило делает его block+threat
        await db.execute(
            "INSERT INTO moderation_rules (account_id, pattern, category, action, severity, enabled) "
            "VALUES (?, 'дебил', 'threat', 'block', 5, 1)",
            (aid,),
        )
        await db.commit()
    finally:
        await db.close()
    M.invalidate_cache(aid)
    verdicts = await M.check_message(aid, "chan", "u1", "ты дебил")
    assert verdicts[0].rule_id is not None, "должно сработать кастомное правило"
    assert verdicts[0].category == "threat"
    assert verdicts[0].action == "block"
    assert verdicts[0].severity == 5


async def test_custom_log_rule_does_not_stop_builtin():
    """Кастомное log-правило НЕ останавливает — встроенное продолжает проверять."""
    aid = await _make_account(moderation_mode="full")
    db = await database.get_db()
    try:
        await db.execute(
            "INSERT INTO moderation_rules (account_id, pattern, category, action, severity, enabled) "
            "VALUES (?, 'котик', 'custom', 'log', 1, 1)",
            (aid,),
        )
        await db.commit()
    finally:
        await db.close()
    M.invalidate_cache(aid)
    verdicts = await M.check_message(aid, "chan", "u1", "котик ты дебил")
    cats = [v.category for v in verdicts]
    assert "custom" in cats and "insult" in cats


async def test_custom_rule_exempt_roles():
    aid = await _make_account(moderation_mode="full")
    db = await database.get_db()
    try:
        await db.execute(
            "INSERT INTO moderation_rules (account_id, pattern, category, action, severity, enabled, exempt_roles) "
            "VALUES (?, 'дебил', 'insult', 'block', 3, 1, 'mod,vip')",
            (aid,),
        )
        await db.commit()
    finally:
        await db.close()
    M.invalidate_cache(aid)
    # Мод exempt — кастомное правило не применяется (встроенный словарь — применяется,
    # у него своих exempt-ролей нет: exempt переключатель per-rule, план §2)
    mod_verdicts = await M.check_message(aid, "chan", "u1", "ты дебил", role="mod")
    assert all(v.rule_id is None for v in mod_verdicts), "кастомное правило пропущено для mod"
    # Зритель — применяется
    viewer_verdicts = await M.check_message(aid, "chan", "u1", "ты дебил", role="viewer")
    assert any(v.rule_id is not None for v in viewer_verdicts)


# ──────────────── 2. Антиспам (§2) ────────────────


def _spam_settings(**kw) -> dict:
    base = {
        "moderation_can_timeout": False,
        "antispam_exempt_roles": "streamer,mod,vip",
        "antispam_caps_pct": 70,
        "antispam_repeat_count": 3,
        "antispam_links": True,
        "antispam_emote_pct": 80,
    }
    base.update(kw)
    return base


def _fresh_detector() -> M.SpamDetector:
    return M.SpamDetector()


async def test_spam_caps_detection():
    d = _fresh_detector()
    hits = d.check(1, "ch", "u1", "АААААААААА ЧТО ЭТО", _spam_settings())
    cats = {h.category for h in hits}
    assert "caps" in cats


async def test_spam_caps_threshold_not_hit_lowercase():
    d = _fresh_detector()
    hits = d.check(1, "ch", "u1", "аааааааа что это такое", _spam_settings())
    assert not any(h.category == "caps" for h in hits)


async def test_spam_links_detection():
    d = _fresh_detector()
    hits = d.check(1, "ch", "u1", "заходи https://spam.example.com", _spam_settings())
    assert any(h.category == "links" for h in hits)


async def test_spam_links_disabled():
    d = _fresh_detector()
    hits = d.check(1, "ch", "u1", "заходи https://spam.example.com", _spam_settings(antispam_links=False))
    assert not any(h.category == "links" for h in hits)


async def test_spam_repeat_detection_window():
    d = _fresh_detector()
    s = _spam_settings(antispam_repeat_count=3)
    h1 = d.check(1, "ch", "u1", "купите подписку", s)
    h2 = d.check(1, "ch", "u1", "купите подписку", s)
    assert not any(x.category == "repeat" for x in h1)
    assert not any(x.category == "repeat" for x in h2)
    h3 = d.check(1, "ch", "u1", "Купите подписку", s)  # регистр не важен
    assert any(x.category == "repeat" and "повтор 3x" in x.detail for x in h3)


async def test_spam_emote_detection():
    d = _fresh_detector()
    hits = d.check(1, "ch", "u1", "KEKW LUL POG 😂", _spam_settings())
    assert any(h.category == "emote" for h in hits)


async def test_spam_copypasta_detection():
    d = _fresh_detector()
    s = _spam_settings()
    d.check(1, "ch", "u1", "это очень длинная уникальная фраза которую все копируют в чат", s)
    hits = d.check(1, "ch", "u2", "это очень длинная уникальная фраза которую все копируют в чат", s)
    assert any(h.category == "copypasta" for h in hits)


async def test_spam_exempt_roles_skip():
    d = _fresh_detector()
    hits = d.check(1, "ch", "mod1", "ААААААААА ЧТО ЭТО", _spam_settings(), role="mod")
    assert hits == []


# ──────────────── 3. Журнал и исходящая модерация ────────────────


async def test_check_incoming_writes_events_log():
    aid = await _make_account(moderation_mode="full")
    verdicts, hits = await M.check_incoming(aid, "chan", "toxic1", "он уебище")
    assert verdicts
    db = await database.get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM moderation_events WHERE account_id = ? AND username = 'toxic1'", (aid,)
        )
        rows = await cur.fetchall()
    finally:
        await db.close()
    assert rows, "нарушение должно попасть в журнал"
    assert rows[0]["category"] == "insult"
    assert rows[0]["source"] == "chat_in"
    assert "уебище" in rows[0]["message_excerpt"]


async def test_threats_logged_even_in_off_mode():
    aid = await _make_account(moderation_mode="off")
    verdicts, hits = await M.check_incoming(aid, "chan", "menace", "я тебя найду тебя")
    assert verdicts  # threat-вердикты есть
    db = await database.get_db()
    try:
        cur = await db.execute("SELECT COUNT(*) AS n FROM moderation_events WHERE account_id = ?", (aid,))
        n = (await cur.fetchone())["n"]
    finally:
        await db.close()
    assert n > 0, "угрозы пишутся в журнал даже при выключенной модерации"


async def test_outgoing_blocked_and_logged():
    aid = await _make_account(moderation_mode="full")
    result = await M.check_outgoing(aid, "chan", "да ты уебище", source="bot_out")
    assert not result.ok, "sev3 block → ответ не публикуется"
    db = await database.get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM moderation_events WHERE account_id = ? AND source = 'bot_out'", (aid,)
        )
        rows = await cur.fetchall()
    finally:
        await db.close()
    assert rows, "блокировка исходящего должна логироваться"
    assert rows[0]["action_taken"] == "block"


async def test_outgoing_threat_blocked_even_off():
    aid = await _make_account(moderation_mode="off")
    result = await M.check_outgoing(aid, "chan", "я найду тебя")
    assert not result.ok, "угрозы блокируются в любом режиме"


async def test_outgoing_clean_passes():
    aid = await _make_account(moderation_mode="full")
    result = await M.check_outgoing(aid, "chan", "привет, добро пожаловать!")
    assert result.ok and result.text == "привет, добро пожаловать!"


# ──────────────── 4. Изоляция per-account / каналы ────────────────


async def test_rules_isolated_between_accounts():
    aid1 = await _make_account("bot1", moderation_mode="full")
    aid2 = await _make_account("bot2", moderation_mode="full")
    db = await database.get_db()
    try:
        await db.execute(
            "INSERT INTO moderation_rules (account_id, pattern, category, action, severity, enabled) "
            "VALUES (?, 'суперспецслово', 'custom', 'block', 5, 1)",
            (aid1,),
        )
        await db.commit()
    finally:
        await db.close()
    M.invalidate_cache(aid1)
    M.invalidate_cache(aid2)
    assert await M.check_message(aid1, "chan", "u1", "суперспецслово")
    assert await M.check_message(aid2, "chan", "u1", "суперспецслово") == []


async def test_channel_empty_rule_applies_everywhere():
    aid = await _make_account(moderation_mode="full")
    db = await database.get_db()
    try:
        # channel='' = все каналы
        await db.execute(
            "INSERT INTO moderation_rules (account_id, channel, pattern, category, action, severity, enabled) "
            "VALUES (?, '', 'всеканальноеслово', 'custom', 'block', 4, 1)",
            (aid,),
        )
        # channel='chanA' — только для chanA
        await db.execute(
            "INSERT INTO moderation_rules (account_id, channel, pattern, category, action, severity, enabled) "
            "VALUES (?, 'chanA', 'слово_только_а', 'custom', 'block', 4, 1)",
            (aid,),
        )
        await db.commit()
    finally:
        await db.close()
    M.invalidate_cache(aid)
    # '' правило работает в обоих каналах
    assert await M.check_message(aid, "chanA", "u1", "всеканальноеслово")
    assert await M.check_message(aid, "chanB", "u1", "всеканальноеслово")
    # правило канала A работает только в A
    assert await M.check_message(aid, "chanA", "u1", "слово_только_а")
    assert await M.check_message(aid, "chanB", "u1", "слово_только_а") == []


async def test_per_channel_mode_override():
    aid = await _make_account(moderation_mode="off")
    db = await database.get_db()
    try:
        await db.execute(
            "INSERT INTO channel_overrides (account_id, channel, overrides_json, enabled) "
            "VALUES (?, 'chanx', '{\"moderation_mode\": \"full\"}', 1)",
            (aid,),
        )
        await db.commit()
    finally:
        await db.close()
    M.invalidate_cache(aid)
    assert await M.get_mode(aid, "chanx") == "full"
    assert await M.get_mode(aid, "chany") == "off"  # без override — общий off
    # В chanx модерация работает, в chany — нет
    assert await M.check_message(aid, "chanx", "u1", "он уебище")
    assert await M.check_message(aid, "chany", "u1", "он уебище") == []


# ──────────────── 5. API ────────────────


async def test_api_settings_roundtrip():
    aid = await _make_account()
    async with await _client() as c:
        r = await c.get(f"/api/accounts/{aid}/moderation/settings")
        assert r.status_code == 200
        data = r.json()
        assert data["mode"] == "off"
        # Включение одним тумблером → full
        r = await c.put(f"/api/accounts/{aid}/moderation/settings", json={"mode": "full", "antispam_caps_pct": 90})
        assert r.status_code == 200 and r.json()["ok"]
        r = await c.get(f"/api/accounts/{aid}/moderation/settings")
        data = r.json()
        assert data["mode"] == "full"
        assert data["antispam_caps_pct"] == 90
    # Движок видит новый режим (кэш инвалидирован)
    assert await M.get_mode(aid, "chan") == "full"


async def test_api_invalid_mode_rejected():
    aid = await _make_account()
    async with await _client() as c:
        r = await c.put(f"/api/accounts/{aid}/moderation/settings", json={"mode": "banana"})
        assert r.json()["ok"] is False


async def test_api_rules_crud():
    aid = await _make_account()
    async with await _client() as c:
        # Create
        r = await c.post(f"/api/accounts/{aid}/moderation/rules", json={
            "pattern": "тестслово", "category": "insult", "action": "block", "severity": 4,
        })
        assert r.json()["ok"]
        rule_id = r.json()["id"]
        # Read
        r = await c.get(f"/api/accounts/{aid}/moderation/rules")
        rules = r.json()["rules"]
        assert len(rules) == 1 and rules[0]["pattern"] == "тестслово"
        # Update
        r = await c.put(f"/api/moderation/rules/{rule_id}", json={
            "pattern": "тестслово2", "category": "spam", "action": "replace", "severity": 2,
        })
        assert r.json()["ok"]
        r = await c.get(f"/api/accounts/{aid}/moderation/rules")
        assert r.json()["rules"][0]["pattern"] == "тестслово2"
        # Toggle
        r = await c.post(f"/api/moderation/rules/{rule_id}/toggle")
        assert r.json()["enabled"] is False
        # Delete
        r = await c.delete(f"/api/moderation/rules/{rule_id}")
        assert r.json()["ok"]
        r = await c.get(f"/api/accounts/{aid}/moderation/rules")
        assert r.json()["rules"] == []


async def test_api_rule_validation():
    aid = await _make_account()
    async with await _client() as c:
        # Плохой regex отклоняется
        r = await c.post(f"/api/accounts/{aid}/moderation/rules", json={
            "pattern": "re:[unclosed", "category": "custom", "action": "block", "severity": 3,
        })
        assert r.json()["ok"] is False
        # Плохая категория отклоняется
        r = await c.post(f"/api/accounts/{aid}/moderation/rules", json={
            "pattern": "слово", "category": "магия", "action": "block", "severity": 3,
        })
        assert r.json()["ok"] is False


async def test_api_rules_import():
    aid = await _make_account(moderation_mode="full")
    async with await _client() as c:
        r = await c.post(f"/api/accounts/{aid}/moderation/rules/import", json={
            "text": "# комментарий\nслово1\nслово2\n\nслово3", "action": "block", "severity": 3,
        })
        assert r.json()["added"] == 3
    M.invalidate_cache(aid)
    v = await M.check_message(aid, "chan", "u1", "ну слово2 же")
    assert v and v[0].rule_id is not None


async def test_api_events_and_test_message():
    aid = await _make_account(moderation_mode="full")
    await M.check_incoming(aid, "chan", "badguy", "он уебище")
    async with await _client() as c:
        r = await c.get(f"/api/accounts/{aid}/moderation/events")
        events = r.json()["events"]
        assert len(events) == 1 and events[0]["username"] == "badguy"
        # Фильтр по юзеру
        r = await c.get(f"/api/accounts/{aid}/moderation/events?username=goodguy")
        assert r.json()["events"] == []
        # Тест сообщения: вердикт без записи в журнал
        r = await c.post(f"/api/accounts/{aid}/moderation/test", json={"text": "ты дебил"})
        data = r.json()
        assert data["ok"] and data["verdicts"], "тест должен показать вердикт"
        assert data["mode"] == "full"
        r = await c.get(f"/api/accounts/{aid}/moderation/events")
        assert len(r.json()["events"]) == 1, "тест-проверка не пишет в журнал"
        # CSV-экспорт
        r = await c.get(f"/api/accounts/{aid}/moderation/events/export.csv")
        assert r.status_code == 200 and "badguy" in r.text
        # Очистка журнала
        r = await c.delete(f"/api/accounts/{aid}/moderation/events")
        assert r.json()["ok"]
        r = await c.get(f"/api/accounts/{aid}/moderation/events")
        assert r.json()["events"] == []


async def test_api_stats_and_recent_widget():
    aid1 = await _make_account("bot1", moderation_mode="full")
    aid2 = await _make_account("bot2", moderation_mode="full")
    await M.check_incoming(aid1, "chan", "u1", "он уебище")
    await M.check_incoming(aid2, "chan", "u2", "я тебя найду тебя")
    async with await _client() as c:
        r = await c.get(f"/api/accounts/{aid1}/moderation/stats")
        stats = r.json()
        assert stats["day"] >= 1
        assert stats["top_offenders"] and stats["top_offenders"][0]["username"] == "u1"
        # Виджет Dashboard видит нарушения всех аккаунтов
        r = await c.get("/api/moderation/recent")
        data = r.json()
        assert data["hour_total"] >= 2
        usernames = {e["username"] for e in data["events"]}
        assert {"u1", "u2"} <= usernames


async def test_api_per_channel_override():
    aid = await _make_account(moderation_mode="off")
    async with await _client() as c:
        r = await c.put(f"/api/accounts/{aid}/moderation/settings", json={
            "channel": "chanz", "channel_mode": "full",
        })
        assert r.json()["ok"]
    M.invalidate_cache(aid)
    assert await M.get_mode(aid, "chanz") == "full"
    assert await M.get_mode(aid, "other") == "off"


# ──────────────── 6. Интеграция с ботом ────────────────


class _FakeAI:
    async def generate_text(self, *a, **kw):
        return "ok"

    async def analyze_image(self, *a, **kw):
        return ""


class _FakeAuthor:
    def __init__(self, name, is_mod=False, is_vip=False, is_subscriber=False, is_broadcaster=False):
        self.name = name
        self.is_mod = is_mod
        self.is_vip = is_vip
        self.is_subscriber = is_subscriber
        self.is_broadcaster = is_broadcaster


class _FakeChannel:
    def __init__(self, name):
        self.name = name


class _FakeMessage:
    def __init__(self, channel, author, content):
        self.channel = _FakeChannel(channel)
        self.author = author
        self.content = content


class _FakeInstance:
    def __init__(self, account_id, nickname="mybot", token=""):
        self.account_id = account_id
        self.nickname = nickname
        self.token = token


async def test_on_message_full_mode_ignores_toxic():
    """В full-режиме бот не отвечает на block-сообщения, но пишет журнал."""
    from app.chat_analyzer import ChatAnalyzer
    sent = []

    async def capture_send(account_id, channel, text, **kw):
        sent.append(text)
        return True

    aid = await _make_account(moderation_mode="full")
    a = ChatAnalyzer(ai=_FakeAI(), send_fn=capture_send)
    a.update_settings(aid, {"enabled": True})
    instance = _FakeInstance(account_id=aid)
    await a.on_message(instance, _FakeMessage("chan", _FakeAuthor("toxic1"), "он уебище"))
    assert not sent, "бот не отвечает на нарушителя"
    db = await database.get_db()
    try:
        cur = await db.execute("SELECT COUNT(*) AS n FROM moderation_events WHERE account_id = ?", (aid,))
        assert (await cur.fetchone())["n"] > 0, "нарушение в журнале"
    finally:
        await db.close()


async def test_on_message_normal_message_still_works():
    from app.chat_analyzer import ChatAnalyzer
    sent = []

    async def capture_send(account_id, channel, text, **kw):
        sent.append(text)
        return True

    aid = await _make_account(moderation_mode="full")
    a = ChatAnalyzer(ai=_FakeAI(), send_fn=capture_send)
    a.update_settings(aid, {"enabled": True})
    instance = _FakeInstance(account_id=aid)
    await a.on_message(instance, _FakeMessage("chan", _FakeAuthor("norm1"), "привет, как стрим?"))
    assert sent == [], "нейтральное сообщение не триггерит ответ само по себе (mention off)"
    # но оно должно дойти до буфера/обработки — проверим отсутствие исключений через буфер
    key = a._buffer_key(aid, "chan")
    assert any("привет" in m["text"] for m in a._chat_buffer.get(key, []))


async def test_generate_and_send_blocks_toxic_reply():
    """§5: заблокированный ответ бота не отправляется и логируется."""
    from app.chat_analyzer import ChatAnalyzer
    sent = []

    async def capture_send(account_id, channel, text, **kw):
        sent.append(text)
        return True

    aid = await _make_account(moderation_mode="full")

    class _ToxicAI(_FakeAI):
        async def generate_text(self, *a, **kw):
            return "да ты уебище вообще"

    a = ChatAnalyzer(ai=_ToxicAI(), send_fn=capture_send)
    a.update_settings(aid, {"enabled": True, "reply_to_mentions": True})
    a.set_account_token(aid, "")
    await a._generate_and_send(aid, "chan", "mybot", "user1", "@mybot привет", is_mention=True)
    assert sent == [], "замаскированный/заблокированный ответ не отправляется"
    db = await database.get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM moderation_events WHERE account_id = ? AND source = 'bot_out'", (aid,)
        )
        rows = await cur.fetchall()
    finally:
        await db.close()
    assert rows, "блокировка ответа бота логируется"
    assert rows[0]["action_taken"] == "block"


async def test_generate_and_send_masks_replace_reply():
    """В replace-режиме ответ бота отправляется с маскировкой."""
    from app.chat_analyzer import ChatAnalyzer
    sent = []

    async def capture_send(account_id, channel, text, **kw):
        sent.append(text)
        return True

    aid = await _make_account(moderation_mode="replace")

    class _ToxicAI(_FakeAI):
        async def generate_text(self, *a, **kw):
            return "ну ты дебил конечно"

    a = ChatAnalyzer(ai=_ToxicAI(), send_fn=capture_send)
    a.update_settings(aid, {"enabled": True, "reply_to_mentions": True})
    a.set_account_token(aid, "")
    await a._generate_and_send(aid, "chan", "mybot", "user1", "@mybot привет", is_mention=True)
    assert len(sent) == 1, "replace-ответ отправляется"
    assert "дебил" not in sent[0] and "*****" in sent[0]


# ──────────────── 7. Политика «кто таймаутит» (auto/ask/learn) ────────────────


async def _helix_calls(monkeypatch):
    """Мокает twitch_helix.timeout_user, возвращает список вызовов."""
    calls = []

    async def fake_timeout_user(**kw):
        calls.append(kw)
        return True, None

    import app.twitch_helix as helix
    monkeypatch.setattr(helix, "timeout_user", fake_timeout_user)
    return calls


async def _add_timeout_rule(aid, pattern="таймаутслово"):
    db = await database.get_db()
    try:
        await db.execute(
            "INSERT INTO moderation_rules (account_id, pattern, category, action, severity, enabled) "
            "VALUES (?, ?, 'insult', 'timeout', 5, 1)",
            (aid, pattern),
        )
        await db.commit()
    finally:
        await db.close()
    M.invalidate_cache(aid)


async def test_timeout_policy_roundtrip_api():
    aid = await _make_account()
    await M.get_settings(aid)  # гарантирует, что колонка timeout_policy создана
    async with await _client() as c:
        r = await c.get(f"/api/accounts/{aid}/moderation/timeout-policy")
        assert r.status_code == 200 and r.json()["policy"] == "auto"
        # Неверная политика отклоняется
        r = await c.put(f"/api/accounts/{aid}/moderation/timeout-policy", json={"policy": "banana"})
        assert r.json()["ok"] is False
        r = await c.put(f"/api/accounts/{aid}/moderation/timeout-policy", json={"policy": "ask"})
        assert r.json()["ok"] is True
        r = await c.get(f"/api/accounts/{aid}/moderation/timeout-policy")
        assert r.json()["policy"] == "ask"
    assert (await M.get_settings(aid))["timeout_policy"] == "ask"


async def test_ask_policy_creates_pending_question(monkeypatch):
    calls = await _helix_calls(monkeypatch)
    aid = await _make_account(moderation_mode="full", moderation_can_timeout=1)
    await M.get_settings(aid)
    db = await database.get_db()
    try:
        await db.execute("UPDATE accounts SET timeout_policy = 'ask' WHERE id = ?", (aid,))
        await db.commit()
    finally:
        await db.close()
    M.invalidate_cache(aid)
    await _add_timeout_rule(aid)
    v = (await M.check_message(aid, "chan", "spammer", "ну ты таймаутслово"))[0]
    assert v.action == "timeout", "в ask-режиме вердикт timeout приходит даже без вопроса"
    applied = await M.maybe_timeout(aid, "chan", "spammer", v, token="oauth:x", bot_nickname="bot1")
    assert not applied and not calls, "таймаут НЕ выполняется без ответа владельца"
    pending = await M.list_pending_timeouts(aid)
    assert len(pending) == 1 and pending[0]["username"] == "spammer"
    assert pending[0]["status"] == "pending"


async def test_decision_yes_executes_timeout_and_learns(monkeypatch):
    calls = await _helix_calls(monkeypatch)
    aid = await _make_account(moderation_mode="full", moderation_can_timeout=1)
    await M.get_settings(aid)
    db = await database.get_db()
    try:
        await db.execute("UPDATE accounts SET timeout_policy = 'ask' WHERE id = ?", (aid,))
        await db.commit()
    finally:
        await db.close()
    M.invalidate_cache(aid)
    await _add_timeout_rule(aid)
    v = (await M.check_message(aid, "chan", "spammer", "ну ты таймаутслово"))[0]
    await M.maybe_timeout(aid, "chan", "spammer", v, token="oauth:x", bot_nickname="bot1")
    rec = (await M.list_pending_timeouts(aid))[0]
    result = await M.record_timeout_decision(rec["id"], True, token="oauth:x", bot_nickname="bot1")
    assert result["ok"] and result["executed"] and calls, "«Да» → таймаут через Helix"
    stats = await M.get_learn_stats(aid)
    assert stats and stats[0]["approved"] == 1 and stats[0]["rejected"] == 0


async def test_decision_no_blocks_learning(monkeypatch):
    calls = await _helix_calls(monkeypatch)
    aid = await _make_account(moderation_mode="full", moderation_can_timeout=1)
    await M.get_settings(aid)
    db = await database.get_db()
    try:
        await db.execute("UPDATE accounts SET timeout_policy = 'ask' WHERE id = ?", (aid,))
        await db.commit()
    finally:
        await db.close()
    M.invalidate_cache(aid)
    await _add_timeout_rule(aid)
    v = (await M.check_message(aid, "chan", "spammer", "ну ты таймаутслово"))[0]
    await M.maybe_timeout(aid, "chan", "spammer", v, token="oauth:x", bot_nickname="bot1")
    rec = (await M.list_pending_timeouts(aid))[0]
    result = await M.record_timeout_decision(rec["id"], False)
    assert result["ok"] and not result["executed"] and not calls, "«Нет» → таймаут не выполняется"
    stats = await M.get_learn_stats(aid)
    assert stats[0]["rejected"] == 1
    assert not stats[0]["auto"], "после отказа бот не решает сам"
    # Повторное решение того же вопроса невозможно
    again = await M.record_timeout_decision(rec["id"], True)
    assert again["ok"] is False


async def test_learn_mode_becomes_automatic(monkeypatch):
    calls = await _helix_calls(monkeypatch)
    aid = await _make_account(moderation_mode="full", moderation_can_timeout=1)
    await M.get_settings(aid)
    db = await database.get_db()
    try:
        # Владелец трижды сказал «Да» insult-таймаутам → бот выучил
        await db.execute(
            "INSERT INTO moderation_learn (account_id, category, approved, rejected) VALUES (?, 'insult', 3, 0)",
            (aid,),
        )
        await db.commit()
    finally:
        await db.close()
    M.invalidate_cache(aid)
    assert await M.should_auto_timeout(aid, "insult", "learn")
    await _add_timeout_rule(aid)
    v = (await M.check_message(aid, "chan", "spammer", "ну ты таймаутслово"))[0]
    applied = await M.maybe_timeout(aid, "chan", "spammer", v, token="oauth:x", bot_nickname="bot1")
    assert applied and calls, "выученная категория таймаутится без вопроса"
    assert await M.list_pending_timeouts(aid) == []
    # Незнакомая категория — всё ещё спрашивает
    assert not await M.should_auto_timeout(aid, "spam", "learn")


async def test_pending_global_api_and_decision_flow(monkeypatch):
    calls = await _helix_calls(monkeypatch)
    aid = await _make_account(moderation_mode="full", moderation_can_timeout=1)
    await M.get_settings(aid)
    db = await database.get_db()
    try:
        await db.execute("UPDATE accounts SET timeout_policy = 'ask', nickname = 'bot1' WHERE id = ?", (aid,))
        await db.commit()
    finally:
        await db.close()
    M.invalidate_cache(aid)
    await _add_timeout_rule(aid)
    v = (await M.check_message(aid, "chan", "spammer", "ну ты таймаутслово"))[0]
    await M.maybe_timeout(aid, "chan", "spammer", v, token="oauth:x", bot_nickname="bot1")

    async with await _client() as c:
        r = await c.get("/api/moderation/pending")
        data = r.json()
        assert data["total"] == 1 and data["events"][0]["username"] == "spammer"
        rec_id = data["events"][0]["id"]
        r = await c.post(f"/api/moderation/pending/{rec_id}/decision", json={"approved": True})
        assert r.json()["ok"] and r.json()["executed"]
        r = await c.get("/api/moderation/pending")
        assert r.json()["events"] == []
