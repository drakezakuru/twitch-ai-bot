"""PLAN_FEEDBACK_3008 §6: модель ролей — миграция, API, валидация конфига."""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app import database
from app.api_errors import install_api_error_handlers
from app.bot_roles import (
    DEFAULT_ROLE,
    ROLE_DEFAULT_CONFIGS,
    VALID_ROLES,
    load_role_config,
    validate_role_config,
)
from app.role_routes import router as role_router


@pytest_asyncio.fixture(autouse=True)
async def _schema(tmp_db, disable_auth):
    await database.init_db()
    db = await database.get_db()
    try:
        await db.execute("INSERT OR IGNORE INTO accounts (id, nickname, token) VALUES (1, 'bot', 'tok')")
        await db.commit()
    finally:
        await db.close()


def _app() -> FastAPI:
    app = FastAPI()
    install_api_error_handlers(app)
    app.include_router(role_router)
    return app


# ---------- миграция ----------

@pytest.mark.asyncio
async def test_migration_adds_role_columns_with_defaults(tmp_db):
    db = await database.get_db()
    try:
        cur = await db.execute("PRAGMA table_info(accounts)")
        cols = {r["name"] for r in await cur.fetchall()}
        row = await db.execute("SELECT bot_role, role_config_json FROM accounts WHERE id=1")
        r = await row.fetchone()
    finally:
        await db.close()
    assert "bot_role" in cols and "role_config_json" in cols
    assert r["bot_role"] == DEFAULT_ROLE  # chatter
    assert r["role_config_json"] == "{}"


@pytest.mark.asyncio
async def test_migration_backup_snapshot_created(tmp_db):
    """§9: перед миграцией ролей — required-снапшот в data/backups."""
    snaps = sorted((tmp_db.parent / "backups").glob("bot.db.roles-accounts-*.db"))
    assert snaps, "required-бэкап перед миграцией ролей не создан"


# ---------- валидация конфига ----------

def test_validate_rejects_unknown_role_and_config_type():
    with pytest.raises(ValueError):
        validate_role_config("admin", {})
    with pytest.raises(ValueError):
        validate_role_config("moderator", "oops")


def test_validate_filters_unknown_keys_and_clamps():
    clean = validate_role_config("moderator", {
        "strictness": "strict", "ladder_t2_min": 999, "hacker_key": 1,
        "whitelist": ["x" * 500], "stream_tool_modes": {"category": "auto", "hack": 1},
    })
    assert clean["strictness"] == "strict"
    assert clean["ladder_t2_min"] == 600  # clamp 0..600
    assert "hacker_key" not in clean
    assert clean["whitelist"][0].endswith("x") and len(clean["whitelist"][0]) <= 200
    assert clean["stream_tool_modes"] == {"category": "auto"}


@pytest.mark.parametrize(
    ("role", "field", "invalid", "expected"),
    [
        ("chatter", "preset_key", "unknown", ""),
        ("chatter", "mimic_mode", "everything", "off"),
        ("moderator", "chat_activity", "always", "chatter"),
        ("moderator", "strictness", "extreme", "normal"),
        ("moderator", "dictionary", "remote", "builtin"),
        ("moderator", "confirm_mode", "never", "auto"),
        ("voice_companion", "companion_scope", "streamer_only", "channel_chat"),
        ("voice_companion", "voice_source", "remote", "preset"),
    ],
)
def test_validate_normalizes_invalid_role_enums(role, field, invalid, expected):
    clean = validate_role_config(role, {field: invalid})
    assert clean[field] == expected


def test_validate_normalizes_invalid_stream_tool_mode():
    clean = validate_role_config("moderator", {
        "stream_tool_modes": {"category": "dangerous", "title": "auto"},
    })
    assert clean["stream_tool_modes"] == {"category": "suggest", "title": "auto"}


def test_load_role_config_merges_defaults_and_survives_bad_json():
    base = load_role_config(None, "voice_companion")
    assert base["interruptible"] is False
    merged = load_role_config('{"voice_companion": {"rate": 1.5}}', "voice_companion")
    assert merged["rate"] == 1.5 and merged["cooldown_sec"] == 45
    broken = load_role_config("{not json", "lurker")
    assert broken == ROLE_DEFAULT_CONFIGS["lurker"]


def test_lurker_dead_fields_removed():
    """C6 (PLAN_TODO ТРЕК 1): lurker-поля без читателей удалены, mention_reply работает."""
    cfg = ROLE_DEFAULT_CONFIGS["lurker"]
    assert set(cfg) == {"mention_reply"}, f"вернулись мёртвые lurker-поля: {sorted(cfg)}"
    # неизвестные ключи теперь отбрасываются валидатором, а не сохраняются молча
    clean = validate_role_config("lurker", {"collect_users": True, "mention_reply": True})
    assert clean == {"mention_reply": True}
    js = (Path(__file__).parent.parent / "static" / "app" / "06_roles.js").read_text(encoding="utf-8")
    for dead in ("collect_users", "collect_lore", "role.l.observations",
                 "observation_interval_min", "memory_limit_per_stream", "auto_cleanup_days"):
        assert dead not in js, f"мёртвое поле {dead} вернулось в форму роли"


@pytest.mark.asyncio
async def test_lurker_uses_common_autostart(tmp_db, monkeypatch):
    from app.bootstrap import autoconnect_enabled_bots

    db = await database.get_db()
    try:
        await db.execute("UPDATE accounts SET enabled = 1, bot_role = 'lurker' WHERE id = 1")
        await db.execute(
            "INSERT INTO channels (account_id, channel_name, enabled) VALUES (1, 'demo', 1)"
        )
        await db.commit()
    finally:
        await db.close()

    started = []

    async def fake_start(_manager, _analyzer, account, channels, *, eventsub_manager=None):
        started.append((account["bot_role"], channels))
        return True

    monkeypatch.setattr("app.bootstrap.start_account", fake_start)
    count = await autoconnect_enabled_bots(object(), object())

    assert count == 1
    assert started == [("lurker", ["demo"])]


# ---------- API ----------

@pytest.mark.asyncio
async def test_role_config_api_roundtrip(tmp_db):
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        r = await client.get("/api/accounts/1/role-config")
        body = r.json()
        assert body["ok"] is True and body["bot_role"] == "chatter"
        assert set(body["configs"].keys()) == set(VALID_ROLES)
        # canonical mutation одновременно выбирает роль и сохраняет её конфиг
        r = await client.put("/api/accounts/1/role-config", json={
            "role": "moderator",
            "config": {"strictness": "soft", "confirm_mode": "confirm"},
        })
        assert r.json()["bot_role"] == "moderator"
        r = await client.get("/api/accounts/1/role-config")
        body = r.json()
        assert body["bot_role"] == "moderator"
        assert body["configs"]["moderator"]["strictness"] == "soft"
        assert body["configs"]["moderator"]["confirm_mode"] == "confirm"
        # конфиг болтуна не потерялся (§6.7: per-role storage)
        r = await client.put("/api/accounts/1/role-config", json={
            "role": "chatter", "config": {},
        })
        assert r.json()["ok"] is True
        r = await client.get("/api/accounts/1/role-config")
        assert r.json()["bot_role"] == "chatter"
        assert r.json()["configs"]["moderator"]["strictness"] == "soft"


@pytest.mark.asyncio
async def test_role_api_rejects_unknown_role(tmp_db):
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        r = await client.put("/api/accounts/1/role-config", json={
            "role": "nope", "config": {},
        })
        assert r.status_code == 400
        assert r.json() == {
            "ok": False,
            "error": {"code": "unknown_role", "params": {"role": "nope"}},
        }


@pytest.mark.asyncio
async def test_legacy_role_endpoint_is_removed(tmp_db):
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        response = await client.put("/api/accounts/1/role", json={"role": "moderator"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_role_sandbox(tmp_db):
    """§6.7: песочница — вердикт без реального чата."""
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        # lurker: гейт молчания
        r = await client.post("/api/accounts/1/role-sandbox", json={
            "role": "lurker", "message": "привет всем",
        })
        body = r.json()
        assert body["ok"] is True and "Промолчал" in body["verdict"]
        # moderator: ручной режим — только лог
        await client.put("/api/accounts/1/role-config", json={
            "role": "moderator",
            "config": {"strictness": "manual", "dictionary": "off"},
        })
        r = await client.post("/api/accounts/1/role-sandbox", json={
            "role": "moderator", "message": "просто хорошее сообщение",
        })
        body = r.json()
        assert body["ok"] is True and "Чисто" in body["verdict"]


@pytest.mark.asyncio
async def test_voice_companion_sandbox_reports_public_chat_and_tts_percent(tmp_db):
    db = await database.get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO bot_attention_config (account_id, tts_reply_percent) VALUES (1, 25)"
        )
        await db.commit()
    finally:
        await db.close()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        response = await client.post("/api/accounts/1/role-sandbox", json={
            "role": "voice_companion", "message": "что происходит на стриме?",
        })
    verdict = response.json()["verdict"]
    assert "публичный Twitch-чат" in verdict
    assert "25%" in verdict
    assert "tts_reply_percent" in verdict


# ---------- Q02: политика «категория → действие» в role_config ----------

def test_category_policy_default_present_for_moderator_only():
    assert ROLE_DEFAULT_CONFIGS["moderator"]["category_policy"] == {}
    assert "category_policy" not in ROLE_DEFAULT_CONFIGS["chatter"]


def test_category_policy_validates_values_to_canonical_keys():
    cfg = validate_role_config("moderator", {
        "category_policy": {
            "insult": "timeout_86400", "hate": "BAN", "threat": "mask",
            "sexual": "timeout_600", "spam": "", "unknown_cat": "ban",
        },
    })
    pol = cfg["category_policy"]
    assert pol["insult"] == "timeout_86400"
    assert pol["hate"] == "ban", "регистр/варианты нормализуются в канонический ключ"
    assert pol["threat"] == "mask"
    assert pol["spam"] == "", "пустое значение = лестница по severity"
    assert "unknown_cat" not in pol, "чужие категории отбрасываются whitelist-ом"


def test_category_policy_garbage_value_becomes_severity_ladder():
    cfg = validate_role_config("moderator", {"category_policy": {"insult": "banana"}})
    assert cfg["category_policy"]["insult"] == ""


def test_category_policy_dropped_for_non_moderator_roles():
    cfg = validate_role_config("chatter", {"category_policy": {"insult": "ban"}})
    assert "category_policy" not in cfg


def test_role_config_32kb_limit_including_category_policy():
    """Соглашение 13.09: owning-тест на случай «конфиг упёрся в лимит 32 КБ»."""
    huge = {"custom_words": ["ы" * 200] * 200}   # ~40 КБ одним полем
    with pytest.raises(ValueError, match="config too large"):
        validate_role_config("moderator", {**huge, "category_policy": {"insult": "ban"}})


@pytest.mark.asyncio
async def test_role_config_api_roundtrip_keeps_category_policy(tmp_db):
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        r = await client.put("/api/accounts/1/role-config", json={
            "role": "moderator",
            "config": {"category_policy": {"insult": "timeout_3600", "hate": "ban"}},
        })
        assert r.json()["ok"] is True
        assert r.json()["config"]["category_policy"] == {"insult": "timeout_3600", "hate": "ban"}

        r = await client.get("/api/accounts/1/role-config")
        pol = r.json()["configs"]["moderator"]["category_policy"]
        assert pol == {"insult": "timeout_3600", "hate": "ban"}


# ── D1 (bugfix 3e0cdd3, 12.09.2026): смена роли применяется сразу и снимает
# observation_only, если бот уходил с lurker; не трогает тумблер, если бот
# уходил с другой роли или остаётся lurker'ом ──

@pytest.mark.asyncio
async def test_leaving_lurker_role_clears_observation_only(tmp_db):
    db = await database.get_db()
    try:
        await db.execute(
            "UPDATE accounts SET bot_role='lurker', observation_only=1 WHERE id=1",
        )
        await db.commit()
    finally:
        await db.close()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        r = await client.put("/api/accounts/1/role-config", json={"role": "chatter", "config": {}})
        body = r.json()
        assert body["ok"] is True
        assert body["bot_role"] == "chatter"
        assert body["observation_only_cleared"] is True
    db = await database.get_db()
    try:
        row = await (await db.execute("SELECT observation_only FROM accounts WHERE id=1")).fetchone()
    finally:
        await db.close()
    assert row["observation_only"] == 0


@pytest.mark.asyncio
async def test_switching_between_non_lurker_roles_does_not_touch_observation_only(tmp_db):
    db = await database.get_db()
    try:
        await db.execute(
            "UPDATE accounts SET bot_role='moderator', observation_only=1 WHERE id=1",
        )
        await db.commit()
    finally:
        await db.close()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        r = await client.put("/api/accounts/1/role-config", json={"role": "chatter", "config": {}})
        assert r.json()["observation_only_cleared"] is False
    db = await database.get_db()
    try:
        row = await (await db.execute("SELECT observation_only FROM accounts WHERE id=1")).fetchone()
    finally:
        await db.close()
    # Тумблер стоял не из-за lurker-режима — трогать его при смене чужой роли нельзя.
    assert row["observation_only"] == 1


@pytest.mark.asyncio
async def test_staying_lurker_does_not_clear_observation_only(tmp_db):
    db = await database.get_db()
    try:
        await db.execute(
            "UPDATE accounts SET bot_role='lurker', observation_only=1 WHERE id=1",
        )
        await db.commit()
    finally:
        await db.close()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        r = await client.put("/api/accounts/1/role-config", json={
            "role": "lurker", "config": {"mention_reply": True},
        })
        assert r.json()["observation_only_cleared"] is False
    db = await database.get_db()
    try:
        row = await (await db.execute("SELECT observation_only FROM accounts WHERE id=1")).fetchone()
    finally:
        await db.close()
    assert row["observation_only"] == 1
