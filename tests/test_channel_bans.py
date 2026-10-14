"""Q18 (DEC-OWNER-004): запретные темы per-канал + базовый пресет Twitch.

Проверяем: сид пресета из legacy prompt_base (Q05:19) или стартового набора
Twitch; наследование (нет ключа канала → пресет); свой список канала;
рантайм-блок с честным заголовком; API /api/bans/channel и /api/bans/preset;
legacy /api/prompt-base остаётся читаемым.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_preset_seeded_from_legacy_prompt_base(tmp_db):
    from app.database import init_db, get_setting, set_setting
    from app.channel_bans import PRESET_KEY, get_preset_text

    await init_db()
    await set_setting("prompt_base", "Не употреблять мат\nНе обсуждать политику")
    text = await get_preset_text()
    assert "Не употреблять мат" in text
    assert await get_setting(PRESET_KEY, "") == text, "сид сохраняется (миграция Q05:19)"


async def test_preset_seeded_from_twitch_starter_without_legacy(tmp_db):
    from app.database import init_db
    from app.channel_bans import get_preset_text, count_rules

    await init_db()
    text = await get_preset_text()
    assert text.strip(), "стартовый набор Twitch не пуст"
    assert count_rules(text) >= 5


async def test_channel_inherits_preset_until_own_list(tmp_db):
    from app.database import init_db
    from app.channel_bans import set_channel_text, resolve_channel_bans

    await init_db()
    await set_channel_text("#ChanA", "Без спойлеров к сериалам")
    own, source = await resolve_channel_bans("chana")
    assert source == "channel" and "Без спойлеров" in own
    inherited, source = await resolve_channel_bans("chanb")
    assert source == "preset" and inherited.strip()


async def test_runtime_block_header_is_honest(tmp_db):
    from app.database import init_db
    from app.chat_analyzer import ChatAnalyzer

    await init_db()
    from app.channel_bans import set_channel_text
    await set_channel_text("livechan", "Без спойлеров к сериалам")

    ai = type("_AI", (), {"generate_text": staticmethod(asyncio_coro("ok")),
                          "analyze_image": staticmethod(asyncio_coro(""))})()
    a = ChatAnalyzer(ai=ai, send_fn=_no_send)
    own_block = await a._load_prompt_base_block("#LiveChan")
    assert "канал #livechan" in own_block and "Без спойлеров" in own_block
    preset_block = await a._load_prompt_base_block("otherchan")
    assert "базовый пресет Twitch" in preset_block


def _no_send(*args, **kwargs):
    return True


def asyncio_coro(value):
    async def _coro(*args, **kwargs):
        return value
    return _coro


async def test_bans_api_roundtrip(tmp_db, disable_auth):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from app.database import init_db
    from app.routes import router

    await init_db()
    app = FastAPI()
    app.include_router(router)
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    try:
        # наследование: пока своего списка нет — source=preset
        r = (await client.get("/api/bans/channel?channel=%23mychan")).json()
        assert r["ok"] and r["source"] == "preset" and r["text"].strip()

        # свой список канала
        r = (await client.put("/api/bans/channel", json={
            "channel": "#mychan", "text": "Без спойлеров\n# комментарий\nБез политики"})).json()
        assert r["ok"] and r["rules"] == 2
        r = (await client.get("/api/bans/channel?channel=mychan")).json()
        assert r["source"] == "channel" and "Без спойлеров" in r["text"]

        # пресет можно отредактировать, канал без своего списка это подхватит
        r = (await client.put("/api/bans/preset", json={"text": "Новый базовый запрет"})).json()
        assert r["ok"] and r["rules"] == 1
        r = (await client.get("/api/bans/channel?channel=otherchan")).json()
        assert "Новый базовый запрет" in r["text"]

        # без канала — 400
        assert (await client.get("/api/bans/channel")).status_code == 400

        # legacy-роут остаётся читаемым и помечен legacy
        r = (await client.get("/api/prompt-base")).json()
        assert r["ok"] and r.get("legacy") is True
    finally:
        await client.aclose()


async def test_bans_api_rejects_oversize(tmp_db, disable_auth):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from app.database import init_db
    from app.routes import router

    await init_db()
    app = FastAPI()
    app.include_router(router)
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    try:
        big = "x" * 8100
        assert (await client.put("/api/bans/channel", json={"channel": "c", "text": big})).json()["error"] == "too_long"
        assert (await client.put("/api/bans/preset", json={"text": big})).json()["error"] == "too_long"
    finally:
        await client.aclose()
