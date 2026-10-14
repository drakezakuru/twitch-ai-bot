"""PLAN_FEEDBACK_2908 §5 (остаток): профиль стримера инъектируется в промпт.

_load_streamer_profile_block форматирует резолвнутый профиль в компактный
блок для системного промпта (fallback-цепочка §5).
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_profile_block_injected_from_panel_global(tmp_db):
    from app.database import init_db
    from app.streamer_profile import upsert_streamer_profile
    from app.chat_analyzer import ChatAnalyzer

    await init_db()
    await upsert_streamer_profile(0, {
        "bio": "Стример про гонки, любит чёрный юмор",
        "occupation": "стример",
        "streaming_style": "entertaining",
        "favorite_games": ["Forza", "GT7"],
        "interests": ["авто", "симрейсинг"],
    }, channel="#racing")

    ca = ChatAnalyzer.__new__(ChatAnalyzer)
    block = await ca._load_streamer_profile_block(9, "#racing")
    assert block, "блок не построен"
    assert "Стример про гонки" in block
    assert "Forza" in block
    assert "entertaining" in block


async def test_profile_block_channel_priority(tmp_db):
    from app.database import init_db
    from app.streamer_profile import upsert_streamer_profile
    from app.chat_analyzer import ChatAnalyzer

    await init_db()
    await upsert_streamer_profile(0, {"bio": "канальное био про варкрафт"}, channel="#wow")

    ca = ChatAnalyzer.__new__(ChatAnalyzer)
    block = await ca._load_streamer_profile_block(5, "#wow")
    assert "канальное био" in block
    block2 = await ca._load_streamer_profile_block(5, "#other")
    assert block2 == ""


async def test_profile_block_empty_when_no_profile(tmp_db):
    from app.database import init_db
    from app.chat_analyzer import ChatAnalyzer

    await init_db()
    ca = ChatAnalyzer.__new__(ChatAnalyzer)
    block = await ca._load_streamer_profile_block(77, "#nothing")
    assert block == ""
