"""PLAN_SESSION_ROLES §R4: пресеты болтуна, копирка, самообучение, токен-бюджет."""

from __future__ import annotations

import json

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app import database
from app.bot_roles import (
    ANTI_ASSISTANT_RULE,
    CHATTER_PRESETS,
    chatter_style_block,
    learn_from_feedback,
    validate_role_config,
)
from app.role_routes import router as role_router


@pytest_asyncio.fixture(autouse=True)
async def _schema(tmp_db, disable_auth):
    await database.init_db()
    db = await database.get_db()
    try:
        await db.execute(
            "INSERT INTO accounts (id, nickname, token) VALUES (1, 'bot', 't')")
        await db.commit()
    finally:
        await db.close()


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(role_router)
    return app


# ---------- анти-ассистент: во всех пресетах ----------

def test_anti_assistant_in_all_presets():
    assert "AI" in ANTI_ASSISTANT_RULE and "1–2" in ANTI_ASSISTANT_RULE
    for key, preset in CHATTER_PRESETS.items():
        block = chatter_style_block({**{"preset_key": key}, "mimic_mode": "off"})
        if key == "custom":
            # «Свой» = чистый лист: только анти-ассистент
            assert ANTI_ASSISTANT_RULE in block
            continue
        assert ANTI_ASSISTANT_RULE in block, key
        assert preset["prompt"] in block, key


def test_anti_assistant_forbidden_phrases_not_in_examples():
    """Пресеты не должны сами содержать ассистентские конструкции."""
    bad = ("ты можешь", "стоит ", "попробуй", "рекомендую")
    for preset in CHATTER_PRESETS.values():
        text = (preset["prompt"] + " " + " ".join(preset["examples"])).lower()
        assert not any(b in text for b in bad), preset["label"]


# ---------- приоритет: copy > profile > preset ----------

def test_priority_copy_over_profile_over_preset():
    base = {"preset_key": "memny", "mimic_profile": "ПРОФИЛЬ", "anti_assistant": False}
    copy_cfg = {**base, "mimic_mode": "copy", "mimic_copy_msgs": ["ахах база"],
                "mimic_copy_summary": "коротко, с мемами"}
    block = chatter_style_block(copy_cfg)
    assert "Говори В ТОМ ЖЕ СТИЛЕ" in block and "ахах база" in block
    assert "мода" not in block and "ПРОФИЛЬ" not in block  # пресет/профиль не подмешаны
    prof_cfg = {**base, "mimic_mode": "profile"}
    block = chatter_style_block(prof_cfg)
    assert "ПРОФИЛЬ" in block and "Твой стиль общения" in block
    assert "Примеры твоих реплик" not in block  # пресет не активен
    off_cfg = {**base, "mimic_mode": "off"}
    assert "мода" in chatter_style_block(off_cfg)  # пресет работает при off


def test_strength_and_checks_reflected():
    cfg = {"mimic_mode": "copy", "mimic_copy_msgs": ["привет"], "mimic_strength": 85,
           "mimic_checks": {"lexicon": True, "emoji": False, "caps": True,
                            "typos": True, "length": False}}
    block = chatter_style_block(cfg)
    assert "85/100" in block
    assert "эмодзи" not in block.split("НЕ копируй")[1].split(".")[0]


def test_token_budget_cap():
    cfg = {"mimic_mode": "copy",
           "mimic_copy_msgs": ["х" * 200] * 50, "anti_assistant": True}
    block = chatter_style_block(cfg)
    assert len(block) <= 4000
    assert ANTI_ASSISTANT_RULE in block  # анти-ассистент переживает обрезку


def test_empty_block_when_nothing_configured():
    # анти-ассистент по умолчанию включён — «вечный подсказчик» лечится сразу
    assert chatter_style_block({}) == ANTI_ASSISTANT_RULE
    assert chatter_style_block({"anti_assistant": False}) == ""
    assert chatter_style_block({"anti_assistant": False,
                                "mimic_mode": "copy", "mimic_copy_msgs": []}) == ""


# ---------- самообучение ----------

def test_learn_up_adds_and_caps():
    raw = json.dumps({"chatter": {"learned_pool": []}})
    for i in range(35):
        raw = learn_from_feedback(raw, f"ответ {i}", 1)
    pool = json.loads(raw)["chatter"]["learned_pool"]
    assert len(pool) == 30  # лимит пула
    assert pool[-1] == "ответ 34"


def test_learn_down_removes():
    raw = json.dumps({"chatter": {"learned_pool": ["хороший ответ", "плохой ответ"]}})
    raw = learn_from_feedback(raw, "плохой ответ", -1)
    assert "плохой ответ" not in json.loads(raw)["chatter"]["learned_pool"]


def test_learn_ignores_empty_and_non_chatter():
    assert learn_from_feedback(json.dumps({"moderator": {}}), "msg", 1) == ""
    assert learn_from_feedback(None, "msg", 1) == ""
    assert learn_from_feedback(json.dumps({"chatter": {}}), "  ", 1) == ""


# ---------- API: копирка roundtrip ----------

@pytest.mark.asyncio
async def test_mimic_copy_roundtrip(tmp_db):
    db = await database.get_db()
    try:
        for i in range(60):
            await db.execute(
                "INSERT INTO chat_log (account_id, channel, author, message, is_bot) "
                "VALUES (1, 'ch', 'viewer42', ?, 0)",
                (f"сообщение {i} ахахах",),
            )
        await db.commit()
    finally:
        await db.close()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        r = await client.get("/api/accounts/1/mimic/candidates")
        body = r.json()
        assert body["items"][0]["username"] == "viewer42" and body["items"][0]["cnt"] == 60
        r = await client.post("/api/accounts/1/mimic/copy",
                              json={"user": "viewer42", "limit": 500})
        body = r.json()
        assert body["ok"] is True and body["fetched"] == 60 and body["saved"] == 50
        assert "выжимка" in body["summary"] or "длина" in body["summary"]
    db = await database.get_db()
    try:
        cur = await db.execute("SELECT role_config_json FROM accounts WHERE id = 1")
        raw = (await cur.fetchone())["role_config_json"]
    finally:
        await db.close()
    cfg = json.loads(raw)["chatter"]
    assert cfg["mimic_mode"] == "copy" and cfg["mimic_user"] == "viewer42"
    assert len(cfg["mimic_copy_msgs"]) == 50 and cfg["mimic_copy_summary"]


@pytest.mark.asyncio
async def test_learn_clear_endpoint(tmp_db):
    raw = json.dumps({"chatter": {"learned_pool": ["a", "b"]}})
    db = await database.get_db()
    try:
        await db.execute("UPDATE accounts SET role_config_json = ? WHERE id = 1", (raw,))
        await db.commit()
    finally:
        await db.close()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        r = await client.post("/api/accounts/1/mimic/learn-clear")
        assert r.json()["ok"] is True
    db = await database.get_db()
    try:
        cur = await db.execute("SELECT role_config_json FROM accounts WHERE id = 1")
        cfg = json.loads((await cur.fetchone())["role_config_json"])
    finally:
        await db.close()
    assert cfg["chatter"]["learned_pool"] == []


def test_validate_chatter_keys():
    clean = validate_role_config("chatter", {
        "mimic_mode": "copy", "mimic_strength": 150, "hacker": 1,
        "mimic_checks": {"caps": True, "nope": 1},
        "mimic_copy_msgs": ["ok"],
    })
    assert clean["mimic_strength"] == 100
    assert "hacker" not in clean
    assert clean["mimic_checks"] == {"caps": True}
