"""Разрешённые темы и поведение ботов per-канал + базовый пресет Twitch.

Проверяем: сид пресета из стартового набора Twitch; наследование (нет ключа канала → пресет);
свой список канала; рантайм-блок _load_allowed_topics_block; API /api/allowed-topics/channel
и /api/allowed-topics/preset; ограничение размера.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_allowed_preset_seeded_from_starter(tmp_db):
    from app.database import init_db
    from app.channel_allowed import get_allowed_preset_text, count_rules

    await init_db()
    text = await get_allowed_preset_text()
    assert text.strip(), "стартовый набор не пуст"
    assert count_rules(text) >= 5
    assert "атмосферу" in text


async def test_channel_inherits_allowed_until_own_list(tmp_db):
    from app.database import init_db
    from app.channel_allowed import set_channel_allowed_text, resolve_channel_allowed

    await init_db()
    await set_channel_allowed_text("#ChanA", "Поддерживать стримера в битвах\n# коммент\nШутить в тему")
    own, source = await resolve_channel_allowed("chana")
    assert source == "channel" and "стримера в битвах" in own
    inherited, source = await resolve_channel_allowed("chanb")
    assert source == "preset" and inherited.strip()


async def test_allowed_runtime_block_header_is_honest(tmp_db):
    from app.database import init_db
    from app.chat_analyzer import ChatAnalyzer

    await init_db()
    from app.channel_allowed import set_channel_allowed_text
    await set_channel_allowed_text("livechan", "Поощрять рейды\nХвалить донатеров")

    ai = type("_AI", (), {"generate_text": staticmethod(asyncio_coro("ok")),
                          "analyze_image": staticmethod(asyncio_coro(""))})()
    a = ChatAnalyzer(ai=ai, send_fn=_no_send)
    own_block = await a._load_allowed_topics_block("#LiveChan")
    assert "канал #livechan" in own_block and "Поощрять рейды" in own_block
    assert "ЧТО РАЗРЕШЕНО И ПООЩРЯЕТСЯ" in own_block
    preset_block = await a._load_allowed_topics_block("otherchan")
    assert "базовый пресет Twitch" in preset_block


def _no_send(*args, **kwargs):
    return True


def asyncio_coro(value):
    async def _coro(*args, **kwargs):
        return value
    return _coro


async def test_allowed_api_roundtrip(tmp_db, disable_auth):
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
        r = (await client.get("/api/allowed-topics/channel?channel=%23mychan")).json()
        assert r["ok"] and r["source"] == "preset" and r["text"].strip()

        # свой список канала
        r = (await client.put("/api/allowed-topics/channel", json={
            "channel": "#mychan", "text": "Обсуждать текущую игру\n# комментарий\nПоддерживать диалог"})).json()
        assert r["ok"] and r["rules"] == 2
        r = (await client.get("/api/allowed-topics/channel?channel=mychan")).json()
        assert r["source"] == "channel" and "Обсуждать текущую игру" in r["text"]

        # пресет можно отредактировать, канал без своего списка это подхватит
        r = (await client.put("/api/allowed-topics/preset", json={"text": "Новое разрешённое действие"})).json()
        assert r["ok"] and r["rules"] == 1
        r = (await client.get("/api/allowed-topics/channel?channel=otherchan")).json()
        assert "Новое разрешённое действие" in r["text"]

        # без канала — 400
        assert (await client.get("/api/allowed-topics/channel")).status_code == 400
    finally:
        await client.aclose()


async def test_allowed_api_rejects_oversize(tmp_db, disable_auth):
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
        assert (await client.put("/api/allowed-topics/channel", json={"channel": "c", "text": big})).json()["error"] == "too_long"
        assert (await client.put("/api/allowed-topics/preset", json={"text": big})).json()["error"] == "too_long"
    finally:
        await client.aclose()
