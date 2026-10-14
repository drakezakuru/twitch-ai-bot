"""Q01: расширенные действия правил модерации — Helix-контракт и OAuth-скоуп.

Шаг A/B (этот файл сейчас):
- скоуп `moderator:manage:banned_users` запрашивается device flow (`DEC-OWNER-015`);
- `ban_user` = POST /moderation/bans **без** `duration` (бан навсегда);
- `timeout_user` = тот же POST с `duration`, границы 1…1209600 проверяются локально;
- `unban_user` = DELETE /moderation/bans, 204 = успех, 400 «not banned» = `user_not_banned`;
- ошибки Helix (403/409) пробрасываются наружу, а не глотаются.

Шаг C (колонка `action_ext`, parse, движок применения) добавляется в этот же файл.
"""
from __future__ import annotations

import json

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app import database
from app import moderation as M
from app import twitch_helix, twitch_oauth

pytestmark = pytest.mark.asyncio

BAN_SCOPE = "moderator:manage:banned_users"
IDS = {"chan": "111", "modbot": "222", "spammer": "333"}


@pytest_asyncio.fixture(autouse=True)
async def _fresh_db(tmp_db, disable_auth):
    """Своя временная БД и чистые кэши движка на каждый тест (как в test_moderation.py)."""
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


async def _add_rule(aid: int, pattern: str = "плохослово", *, action: str = "block",
                    severity: int = 3, action_ext=None, channel: str = "") -> int:
    db = await database.get_db()
    try:
        cur = await db.execute(
            "INSERT INTO moderation_rules (account_id, channel, pattern, category, action, "
            "severity, enabled, action_ext) VALUES (?, ?, ?, 'insult', ?, ?, 1, ?)",
            (aid, channel, pattern, action, severity, action_ext),
        )
        await db.commit()
        rid = cur.lastrowid
    finally:
        await db.close()
    M.invalidate_cache(aid)
    return rid


async def _client() -> AsyncClient:
    from fastapi import FastAPI
    from app.routes import router
    from app.moderation_routes import router as moderation_policy_router
    app = FastAPI()
    app.include_router(router)
    app.include_router(moderation_policy_router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _patch_client(module, monkeypatch, handler, seen: list):
    """Подменяет httpx.AsyncClient в модуле на MockTransport, пишет запросы в seen."""
    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    class Client:
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            self.client = original(*args, **kwargs)

        async def __aenter__(self):
            return await self.client.__aenter__()

        async def __aexit__(self, *args):
            return await self.client.__aexit__(*args)

    monkeypatch.setattr(module.httpx, "AsyncClient", Client)


def _fake_helix(monkeypatch, status=200, body=None, text=None):
    """Готовый Helix: ID известны, конфиг есть, ответ на /moderation/bans задан."""
    seen: list = []

    async def fake_get_user_id(login, token):
        return IDS.get(login)

    monkeypatch.setattr(twitch_helix, "get_user_id", fake_get_user_id)
    monkeypatch.setattr(twitch_helix, "is_helix_configured", lambda: True)
    monkeypatch.setattr(twitch_helix, "_client_id", lambda: "client123")

    payload = body if body is not None else {"data": [{"user_id": "333", "end_time": None}]}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if text is not None:
            return httpx.Response(status, text=text)
        return httpx.Response(status, json=payload)

    _patch_client(twitch_helix, monkeypatch, handler, seen)
    return seen


# ─────────────────────────── Шаг A: OAuth-скоуп ───────────────────────────


async def test_default_scopes_contain_ban_scope_exactly_once():
    """Без этого скоупа Helix отвечает 401/403 на любой бан и таймаут (DEC-OWNER-015)."""
    assert twitch_oauth.DEFAULT_SCOPES.count(BAN_SCOPE) == 1


async def test_device_flow_sends_ban_scope_to_twitch(monkeypatch):
    monkeypatch.setenv("TWITCH_CLIENT_ID", "fakeclient123")
    seen: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={
            "device_code": "DEV_ABC",
            "user_code": "ABCDEF",
            "verification_uri": "https://www.twitch.tv/activate",
            "expires_in": 1800,
            "interval": 5,
        })

    _patch_client(twitch_oauth, monkeypatch, handler, seen)

    result = await twitch_oauth.start_device_flow()

    assert result["ok"] is True
    assert BAN_SCOPE in result["scopes"]
    # тело url-encoded, поэтому проверяем обе формы записи
    body = seen[0].content.decode()
    assert BAN_SCOPE in body or BAN_SCOPE.replace(":", "%3A") in body


async def test_timeout_user_docstring_names_the_right_scope():
    """Docstring больше не должен вводить в заблуждение чужим скоупом."""
    assert BAN_SCOPE in twitch_helix.timeout_user.__doc__
    assert "moderator:manage:chat_settings" not in twitch_helix.timeout_user.__doc__


# ─────────────────── Шаг B: ban_user / timeout_user / unban_user ───────────────────


async def test_ban_user_posts_without_duration(monkeypatch):
    seen = _fake_helix(monkeypatch)

    ok, err = await twitch_helix.ban_user("oauth:t", "chan", "modbot", "spammer", reason="спам")

    assert (ok, err) == (True, "")
    request = seen[0]
    assert request.method == "POST"
    assert "broadcaster_id=111" in str(request.url)
    assert "moderator_id=222" in str(request.url)
    data = json.loads(request.content.decode())["data"]
    assert data["user_id"] == "333"
    assert data["reason"] == "спам"
    assert "duration" not in data, "бан навсегда = POST без duration"


async def test_ban_user_truncates_reason_to_500(monkeypatch):
    seen = _fake_helix(monkeypatch)

    await twitch_helix.ban_user("oauth:t", "chan", "modbot", "spammer", reason="ы" * 900)

    data = json.loads(seen[0].content.decode())["data"]
    assert len(data["reason"]) == 500


async def test_timeout_user_still_sends_duration(monkeypatch):
    seen = _fake_helix(monkeypatch)

    ok, err = await twitch_helix.timeout_user("oauth:t", "chan", "modbot", "spammer", 600, "флуд")

    assert (ok, err) == (True, "")
    data = json.loads(seen[0].content.decode())["data"]
    assert data["duration"] == 600


@pytest.mark.parametrize("duration", [1, 600, 1209600])
async def test_allowed_durations_reach_helix(monkeypatch, duration):
    seen = _fake_helix(monkeypatch)

    ok, _ = await twitch_helix.timeout_user("oauth:t", "chan", "modbot", "spammer", duration)

    assert ok is True
    assert json.loads(seen[0].content.decode())["data"]["duration"] == duration


@pytest.mark.parametrize("duration", [0, -10, 1209601, 99999999])
async def test_out_of_range_duration_rejected_without_http_call(monkeypatch, duration):
    seen = _fake_helix(monkeypatch)

    ok, err = await twitch_helix.timeout_user("oauth:t", "chan", "modbot", "spammer", duration)

    assert ok is False
    assert err == f"duration_out_of_range:{duration}"
    assert not seen, "Twitch не дёргаем на заведомо неверном duration"


@pytest.mark.parametrize("status", [400, 401, 403, 409, 429])
async def test_ban_user_propagates_helix_errors(monkeypatch, status):
    _fake_helix(monkeypatch, status=status, text='{"message":"nope"}')

    ok, err = await twitch_helix.ban_user("oauth:t", "chan", "modbot", "spammer")

    assert ok is False
    assert err.startswith(f"helix_{status}"), f"ошибка {status} обязана доходить до движка"


async def test_ban_user_without_helix_config(monkeypatch):
    monkeypatch.setattr(twitch_helix, "is_helix_configured", lambda: False)

    ok, err = await twitch_helix.ban_user("oauth:t", "chan", "modbot", "spammer")

    assert (ok, err) == (False, "helix_not_configured")


async def test_unban_user_uses_delete_with_query_ids(monkeypatch):
    seen = _fake_helix(monkeypatch, status=204, body={})

    ok, err = await twitch_helix.unban_user("oauth:t", "chan", "modbot", "spammer")

    assert (ok, err) == (True, "")
    request = seen[0]
    assert request.method == "DELETE"
    assert "broadcaster_id=111" in str(request.url)
    assert "moderator_id=222" in str(request.url)
    assert "user_id=333" in str(request.url)
    assert request.content in (b"", None), "у Unban User нет тела запроса"


async def test_unban_user_reports_not_banned_as_distinct_error(monkeypatch):
    """UI трактует это как «уже не забанен», а не как сбой (Q26)."""
    _fake_helix(monkeypatch, status=400, text='{"message":"The user is not banned"}')

    ok, err = await twitch_helix.unban_user("oauth:t", "chan", "modbot", "spammer")

    assert (ok, err) == (False, "user_not_banned")


async def test_unban_user_other_400_is_a_real_error(monkeypatch):
    _fake_helix(monkeypatch, status=400, text='{"message":"Invalid broadcaster_id"}')

    ok, err = await twitch_helix.unban_user("oauth:t", "chan", "modbot", "spammer")

    assert ok is False
    assert err.startswith("helix_400")


@pytest.mark.parametrize("missing", ["chan", "modbot", "spammer"])
async def test_ban_user_reports_which_id_failed(monkeypatch, missing):
    async def fake_get_user_id(login, token):
        return None if login == missing else IDS.get(login)

    monkeypatch.setattr(twitch_helix, "get_user_id", fake_get_user_id)
    monkeypatch.setattr(twitch_helix, "is_helix_configured", lambda: True)
    monkeypatch.setattr(twitch_helix, "_client_id", lambda: "client123")
    seen: list = []
    _patch_client(twitch_helix, monkeypatch, lambda request: httpx.Response(200, json={}), seen)

    ok, err = await twitch_helix.ban_user("oauth:t", "chan", "modbot", "spammer")

    expected = {"chan": "broadcaster_not_found", "modbot": "moderator_not_found",
                "spammer": "target_not_found"}[missing]
    assert (ok, err) == (False, expected)
    assert not seen, "без всех ID запрос к Twitch не уходит"


# ─────────────────── Шаг C: колонка action_ext и движок ───────────────────


async def test_action_ext_column_created_by_init_db():
    db = await database.get_db()
    try:
        cur = await db.execute("PRAGMA table_info(moderation_rules)")
        cols = {row["name"]: row for row in await cur.fetchall()}
    finally:
        await db.close()
    assert "action_ext" in cols, "миграция обязана добавлять колонку action_ext"


@pytest.mark.parametrize("raw,expected", [
    (None, ("auto", None)),
    ("", ("auto", None)),
    ("auto", ("auto", None)),
    ("mask", ("replace", None)),
    ("block", ("block", None)),
    ("ban", ("ban", None)),
    ("timeout_600", ("timeout", 600)),
    ("timeout_3600", ("timeout", 3600)),
    ("timeout_86400", ("timeout", 86400)),
    ("timeout_604800", ("timeout", 604800)),
    ("timeout_1209600", ("timeout", 1209600)),
    ("BAN", ("ban", None)),
    ("  ban  ", ("ban", None)),
])
async def test_parse_action_ext_known_values(raw, expected):
    assert M.parse_action_ext(raw) == expected


@pytest.mark.parametrize("raw", ["banana", "timeout_999", "timeout", "ban_forever", "unban", 123])
async def test_parse_action_ext_unknown_value_falls_back_to_auto(raw):
    """Legacy-строка или опечатка не должны ломать модерацию."""
    assert M.parse_action_ext(raw) == ("auto", None)


async def test_every_action_ext_timeout_is_within_twitch_limits():
    for key, seconds in M.ACTION_EXT_TIMEOUTS.items():
        assert twitch_helix.BAN_MIN_DURATION <= seconds <= twitch_helix.BAN_MAX_DURATION, key


async def test_rule_without_action_ext_keeps_old_ladder():
    aid = await _make_account(moderation_mode="full", moderation_can_timeout=1)
    await _add_rule(aid, action="block", severity=5, action_ext=None)

    verdicts = await M.check_message(aid, "chan", "spammer", "ну ты плохослово")

    assert verdicts[0].action == "block"
    assert verdicts[0].action_ext == ""
    assert verdicts[0].duration_sec is None


async def test_action_ext_overrides_rule_action():
    """Правило action=log, severity=1, но выбран «бан навсегда» → вердикт ban."""
    aid = await _make_account(moderation_mode="full", moderation_can_timeout=1)
    await _add_rule(aid, action="log", severity=1, action_ext="ban")

    verdicts = await M.check_message(aid, "chan", "spammer", "ну ты плохослово")

    assert verdicts[0].action == "ban"
    assert verdicts[0].action_ext == "ban"
    assert verdicts[0].rule_action == "log", "исходное действие правила остаётся видимым"


@pytest.mark.parametrize("action_ext,seconds", [
    ("timeout_600", 600), ("timeout_3600", 3600), ("timeout_86400", 86400),
    ("timeout_604800", 604800), ("timeout_1209600", 1209600),
])
async def test_action_ext_timeouts_carry_duration(action_ext, seconds):
    aid = await _make_account(moderation_mode="full", moderation_can_timeout=1)
    await _add_rule(aid, action="block", severity=3, action_ext=action_ext)

    verdicts = await M.check_message(aid, "chan", "spammer", "ну ты плохослово")

    assert verdicts[0].action == "timeout"
    assert verdicts[0].duration_sec == seconds


async def test_action_ext_mask_masks_matched_text():
    aid = await _make_account(moderation_mode="full", moderation_can_timeout=1)
    await _add_rule(aid, action="block", severity=5, action_ext="mask")

    verdicts = await M.check_message(aid, "chan", "spammer", "ну ты плохослово")

    v = verdicts[0]
    assert v.action == "replace"
    assert v.masked_text is not None
    assert len(v.masked_text) == len("ну ты плохослово"), "маскировка сохраняет длину"
    assert "*" in v.masked_text


async def test_ban_degrades_to_block_when_punishments_disabled():
    """can_timeout выключен и политика auto → вечного бана быть не должно."""
    aid = await _make_account(moderation_mode="full", moderation_can_timeout=0)
    await M.get_settings(aid)
    await _add_rule(aid, action="block", severity=5, action_ext="ban")

    verdicts = await M.check_message(aid, "chan", "spammer", "ну ты плохослово")

    assert verdicts[0].action == "block"


async def test_ban_degrades_to_log_in_log_only_mode():
    aid = await _make_account(moderation_mode="log_only", moderation_can_timeout=1)
    await _add_rule(aid, action="block", severity=5, action_ext="ban")

    verdicts = await M.check_message(aid, "chan", "spammer", "ну ты плохослово")

    assert verdicts[0].action == "log"


async def test_ban_survives_with_ask_policy_even_without_can_timeout():
    """Политика ask — владелец разрешает наказание вручную, поэтому ban не деградирует."""
    aid = await _make_account(moderation_mode="full", moderation_can_timeout=0)
    await M.get_settings(aid)
    db = await database.get_db()
    try:
        await db.execute("UPDATE accounts SET timeout_policy = 'ask' WHERE id = ?", (aid,))
        await db.commit()
    finally:
        await db.close()
    M.invalidate_cache(aid)
    await _add_rule(aid, action="block", severity=5, action_ext="ban")

    verdicts = await M.check_message(aid, "chan", "spammer", "ну ты плохослово")

    assert verdicts[0].action == "ban"


async def test_outgoing_reply_with_ban_rule_is_not_published():
    aid = await _make_account(moderation_mode="full", moderation_can_timeout=1)
    await _add_rule(aid, action="block", severity=5, action_ext="ban")

    result = await M.check_outgoing(aid, "chan", "сам ты плохослово", source="bot_out")

    assert result.ok is False and result.text == ""
    assert result.verdicts[0].action == "ban"


async def test_api_saves_and_returns_action_ext():
    aid = await _make_account()
    async with await _client() as c:
        r = await c.post(f"/api/accounts/{aid}/moderation/rules", json={
            "pattern": "банслово", "category": "insult", "action": "log", "severity": 5,
            "action_ext": "ban",
        })
        assert r.json()["ok"] is True
        rule_id = r.json()["id"]

        r = await c.get(f"/api/accounts/{aid}/moderation/rules")
        rules = r.json()["rules"]
        assert rules[0]["action_ext"] == "ban"

        r = await c.put(f"/api/moderation/rules/{rule_id}", json={
            "pattern": "банслово", "category": "insult", "action": "log", "severity": 5,
            "action_ext": "timeout_86400",
        })
        assert r.json()["ok"] is True
        r = await c.get(f"/api/accounts/{aid}/moderation/rules")
        assert r.json()["rules"][0]["action_ext"] == "timeout_86400"


async def test_api_without_action_ext_stores_null():
    """Существующее поведение: правило без action_ext хранит NULL, а не пустую строку."""
    aid = await _make_account()
    async with await _client() as c:
        r = await c.post(f"/api/accounts/{aid}/moderation/rules", json={
            "pattern": "обычноеслово", "category": "insult", "action": "block", "severity": 3,
        })
        assert r.json()["ok"] is True
        r = await c.get(f"/api/accounts/{aid}/moderation/rules")
        assert r.json()["rules"][0]["action_ext"] is None


@pytest.mark.parametrize("bad", ["banana", "timeout_999", "unban", "BAN_FOREVER"])
async def test_api_rejects_unknown_action_ext(bad):
    aid = await _make_account()
    async with await _client() as c:
        r = await c.post(f"/api/accounts/{aid}/moderation/rules", json={
            "pattern": "слово", "category": "insult", "action": "block", "severity": 3,
            "action_ext": bad,
        })
        assert r.json()["ok"] is False
        assert "Расширенное действие" in r.json()["error"]
        r = await c.get(f"/api/accounts/{aid}/moderation/rules")
        assert r.json()["rules"] == [], "невалидное правило не должно сохраняться"


async def test_api_import_propagates_action_ext_to_every_word():
    aid = await _make_account()
    async with await _client() as c:
        r = await c.post(f"/api/accounts/{aid}/moderation/rules/import", json={
            "text": "слово1\nслово2\nслово3", "action": "log", "severity": 4,
            "action_ext": "timeout_3600",
        })
        assert r.json()["ok"] is True and r.json()["added"] == 3
        r = await c.get(f"/api/accounts/{aid}/moderation/rules")
        rules = r.json()["rules"]
        assert len(rules) == 3
        assert all(rule["action_ext"] == "timeout_3600" for rule in rules)


async def test_legacy_rules_are_not_rewritten_by_migration():
    """Миграция добавляет колонку, но не переписывает существующие правила."""
    aid = await _make_account(moderation_mode="full", moderation_can_timeout=1)
    rule_id = await _add_rule(aid, action="timeout", severity=4, action_ext=None)

    verdicts = await M.check_message(aid, "chan", "spammer", "ну ты плохослово")
    assert verdicts[0].action == "timeout"

    db = await database.get_db()
    try:
        cur = await db.execute("SELECT action, action_ext FROM moderation_rules WHERE id = ?", (rule_id,))
        row = await cur.fetchone()
    finally:
        await db.close()
    assert row["action"] == "timeout" and row["action_ext"] is None


# ─────────────── Шаг C2: предохранитель бана, очередь, список защищённых ───────────────


async def _pending_rows(aid: int) -> list[dict]:
    await M._ensure_extra_schema()
    db = await database.get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM moderation_pending WHERE account_id = ? ORDER BY id DESC", (aid,)
        )
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


def _verdict(action: str, *, duration=None) -> M.Verdict:
    return M.Verdict(category="insult", action=action, severity=5, rule_name="r1",
                     action_ext=action if action in ("ban", "timeout") else "",
                     duration_sec=duration)


async def test_moderation_pending_and_protected_schema_created():
    await M._ensure_extra_schema()
    db = await database.get_db()
    try:
        cur = await db.execute("PRAGMA table_info(moderation_pending)")
        pending_cols = {row["name"] for row in await cur.fetchall()}
        cur = await db.execute("PRAGMA table_info(moderation_protected)")
        protected_cols = {row["name"] for row in await cur.fetchall()}
        cur = await db.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_mod_protected_acc'")
        idx = await cur.fetchone()
    finally:
        await db.close()
    assert {"requested_action", "duration_sec", "role"} <= pending_cols
    assert {"account_id", "channel", "username", "note", "created_at"} <= protected_cols
    assert idx is not None


async def test_protected_list_add_remove_and_channel_isolation():
    aid = await _make_account()
    await M.add_protected(aid, "#Chan", "Friend", note="друг")
    await M.add_protected(aid, "other", "VipGuy")

    rows = await M.list_protected(aid, "chan")
    assert [(r["username"], r["channel"]) for r in rows] == [("friend", "chan")]

    all_rows = await M.list_protected(aid)
    assert len(all_rows) == 2

    assert await M.remove_protected(aid, "CHAN", "FRIEND") is True
    assert await M.list_protected(aid, "chan") == []
    assert await M.remove_protected(aid, "chan", "ghost") is False


async def test_is_protected_by_role_and_by_manual_list():
    aid = await _make_account()
    # роли защищены автоматически, независимо от списков
    for role in ("moderator", "mod", "editor", "broadcaster", "streamer", "staff", "admin"):
        assert await M.is_protected(aid, "chan", "someone", role=role) is True
    # vip и подписчик — НЕ защищены автоматически
    assert await M.is_protected(aid, "chan", "somevip", role="vip") is False
    assert await M.is_protected(aid, "chan", "somesub", role="subscriber") is False
    # но попадают под защиту через ручной список канала
    await M.add_protected(aid, "chan", "SomeVip")
    assert await M.is_protected(aid, "chan", "somevip", role="vip") is True
    # ручной список per-канал: на другом канале защиты нет
    assert await M.is_protected(aid, "otherchan", "somevip", role="vip") is False


async def _set_policy(aid: int, policy: str) -> None:
    """timeout_policy создаётся ленивой миграцией — сначала гарантируем схему."""
    await M._ensure_extra_schema()
    db = await database.get_db()
    try:
        await db.execute("UPDATE accounts SET timeout_policy = ? WHERE id = ?", (policy, aid))
        await db.commit()
    finally:
        await db.close()
    M.invalidate_cache(aid)


async def test_maybe_punish_ban_on_protected_viewer_is_deferred_and_not_executed(monkeypatch):
    """DEC-OWNER-014: вечный бан защищённого не применяется вообще — ни наказания,
    ни маскировки, ни таймаута; случай в очереди и в журнале."""
    aid = await _make_account(moderation_mode="full", moderation_can_timeout=1)
    await M.add_protected(aid, "chan", "spammer")
    seen = _fake_helix(monkeypatch)  # любой запрос к Helix = провал теста

    status = await M.maybe_punish(aid, "chan", "spammer", _verdict("ban"),
                                  token="oauth:x", bot_nickname="modbot", role="viewer")

    assert status == M.PUNISH_DEFERRED
    assert seen == [], "к Twitch за наказанием не обращаемся"
    rows = await _pending_rows(aid)
    assert len(rows) == 1
    assert rows[0]["requested_action"] == "ban"
    assert rows[0]["status"] == "pending"

    db = await database.get_db()
    try:
        cur = await db.execute(
            "SELECT source, message_excerpt FROM moderation_events WHERE account_id = ?", (aid,)
        )
        events = [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()
    assert any(e["source"] == "punishment_recommend" and "защищён" in e["message_excerpt"] for e in events)


async def test_maybe_punish_ban_on_moderator_role_is_deferred(monkeypatch):
    """Модератор канала защищён автоматически, без ручного списка."""
    aid = await _make_account(moderation_mode="full", moderation_can_timeout=1)
    seen = _fake_helix(monkeypatch)

    status = await M.maybe_punish(aid, "chan", "modfriend", _verdict("ban"),
                                  token="oauth:x", bot_nickname="modbot", role="moderator")

    assert status == M.PUNISH_DEFERRED
    assert seen == []
    rows = await _pending_rows(aid)
    assert rows[0]["requested_action"] == "ban"
    assert rows[0]["role"] == "moderator"


async def test_maybe_punish_ban_on_regular_viewer_is_applied(monkeypatch):
    aid = await _make_account(moderation_mode="full", moderation_can_timeout=1)
    seen = _fake_helix(monkeypatch)

    status = await M.maybe_punish(aid, "chan", "spammer", _verdict("ban"),
                                  token="oauth:x", bot_nickname="modbot", role="viewer")

    assert status == M.PUNISH_APPLIED
    assert len(seen) == 1
    data = json.loads(seen[0].content.decode())["data"]
    assert "duration" not in data, "бан навсегда = POST без duration"


@pytest.mark.parametrize("role", ["vip", "subscriber", "viewer"])
async def test_maybe_punish_timeout_on_protected_applies_without_confirmation(monkeypatch, role):
    """Защита — только от вечного бана; таймаут к защищённому применяется как настроено."""
    aid = await _make_account(moderation_mode="full", moderation_can_timeout=1)
    await M.add_protected(aid, "chan", "spammer")
    seen = _fake_helix(monkeypatch)

    status = await M.maybe_punish(aid, "chan", "spammer", _verdict("timeout", duration=86400),
                                  token="oauth:x", bot_nickname="modbot", role=role)

    assert status == M.PUNISH_APPLIED
    assert json.loads(seen[0].content.decode())["data"]["duration"] == 86400


async def test_maybe_punish_timeout_uses_duration_from_verdict(monkeypatch):
    """«Таймаут 1 день» не должен выполняться как 10 минут (жёсткий 600 убран)."""
    aid = await _make_account(moderation_mode="full", moderation_can_timeout=1)
    seen = _fake_helix(monkeypatch)

    status = await M.maybe_punish(aid, "chan", "spammer",
                                  _verdict("timeout", duration=M.ACTION_EXT_TIMEOUTS["timeout_1209600"]),
                                  token="oauth:x", bot_nickname="modbot", role="viewer")

    assert status == M.PUNISH_APPLIED
    assert json.loads(seen[0].content.decode())["data"]["duration"] == 1209600


async def test_maybe_punish_without_token_or_rubric_is_skipped(monkeypatch):
    aid = await _make_account(moderation_mode="full", moderation_can_timeout=0)
    seen = _fake_helix(monkeypatch)

    status = await M.maybe_punish(aid, "chan", "spammer", _verdict("timeout", duration=600),
                                  token="oauth:x", bot_nickname="modbot")

    assert status == M.PUNISH_SKIPPED
    assert seen == []
    assert await _pending_rows(aid) == [], "skipped не кладёт ничего в очередь"


async def test_maybe_punish_non_punish_action_is_skipped():
    aid = await _make_account()
    assert await M.maybe_punish(aid, "chan", "spammer", _verdict("block")) == M.PUNISH_SKIPPED
    assert await M.maybe_punish(aid, "chan", "", _verdict("timeout", duration=600)) == M.PUNISH_SKIPPED


async def test_maybe_punish_ask_policy_defers_with_requested_action():
    aid = await _make_account(moderation_mode="full", moderation_can_timeout=0)
    await _set_policy(aid, "ask")

    status = await M.maybe_punish(aid, "chan", "spammer", _verdict("timeout", duration=3600),
                                  token="oauth:x", bot_nickname="modbot", role="viewer")

    assert status == M.PUNISH_DEFERRED
    rows = await _pending_rows(aid)
    assert rows[0]["requested_action"] == "timeout"
    assert rows[0]["duration_sec"] == 3600


async def test_maybe_timeout_delegates_to_maybe_punish(monkeypatch):
    """Старый API остаётся: True только когда таймаут реально применён."""
    aid = await _make_account(moderation_mode="full", moderation_can_timeout=1)
    _fake_helix(monkeypatch)

    applied = await M.maybe_timeout(aid, "chan", "spammer", _verdict("timeout", duration=600),
                                    token="oauth:x", bot_nickname="modbot")
    skipped = await M.maybe_timeout(aid, "chan", "spammer", _verdict("block"),
                                    token="oauth:x", bot_nickname="modbot")

    assert applied is True
    assert skipped is False


async def test_record_timeout_decision_executes_requested_ban(monkeypatch):
    """Одобрение владельца — явное решение: из очереди исполняется ban, а не таймаут 600."""
    aid = await _make_account(moderation_mode="full", moderation_can_timeout=1)
    await M.add_protected(aid, "chan", "spammer")
    _fake_helix(monkeypatch)
    await M.maybe_punish(aid, "chan", "spammer", _verdict("ban"),
                         token="", bot_nickname="modbot", role="viewer")
    rec = (await _pending_rows(aid))[0]

    result = await M.record_timeout_decision(rec["id"], True, token="oauth:x", bot_nickname="modbot")

    assert result == {"ok": True, "approved": True, "executed": True}
    rows = await _pending_rows(aid)
    assert rows[0]["status"] == "executed"


async def test_record_timeout_decision_executes_requested_duration(monkeypatch):
    aid = await _make_account(moderation_mode="full", moderation_can_timeout=0)
    await _set_policy(aid, "ask")
    seen = _fake_helix(monkeypatch)
    await M.maybe_punish(aid, "chan", "spammer", _verdict("timeout", duration=604800),
                         token="", bot_nickname="modbot", role="viewer")
    rec = (await _pending_rows(aid))[0]

    result = await M.record_timeout_decision(rec["id"], True, token="oauth:x", bot_nickname="modbot")

    assert result["executed"] is True
    assert json.loads(seen[0].content.decode())["data"]["duration"] == 604800, \
        "из очереди исполняется запрошенная длительность, а не 600 с"


async def test_record_timeout_decision_rejection_does_not_execute(monkeypatch):
    aid = await _make_account(moderation_mode="full", moderation_can_timeout=0)
    await _set_policy(aid, "ask")
    seen = _fake_helix(monkeypatch)
    await M.maybe_punish(aid, "chan", "spammer", _verdict("ban"),
                         token="", bot_nickname="modbot", role="viewer")
    rec = (await _pending_rows(aid))[0]

    result = await M.record_timeout_decision(rec["id"], False)

    assert result == {"ok": True, "approved": False, "executed": False}
    assert seen == []

