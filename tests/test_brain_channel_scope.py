"""PLAN_FEEDBACK_3008 §2.1: lore/learning/runs — скоуп «все каналы» (channel='*')."""

from __future__ import annotations

from datetime import datetime

import pytest
import pytest_asyncio

from app import learning, streamer_lore, summarizer
from app.database import get_db, init_db


@pytest_asyncio.fixture(autouse=True)
async def _init_schema(tmp_db):
    """Полная схема (accounts нужна FK-ам lore/learning/runs)."""
    await init_db()


async def _make_account(aid: int) -> None:
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO accounts (id, nickname, token) VALUES (?, ?, ?)",
            (aid, f"bot{aid}", "oauth:tok"),
        )
        await db.commit()
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_list_lore_star_returns_global_and_channel(tmp_db):
    await _make_account(1)
    await _make_account(2)
    await streamer_lore.add_suggestion(
        account_id=1, channel="", fact="глобальный факт",
        source="manual", importance=60,
    )
    await streamer_lore.add_suggestion(
        account_id=1, channel="alekzz", fact="факт канала",
        source="manual", importance=50,
    )
    await streamer_lore.add_suggestion(
        account_id=2, channel="", fact="чужой бот",
        source="manual", importance=50,
    )
    everything = await streamer_lore.list_lore(1, "*")
    assert {it["fact"] for it in everything} == {"глобальный факт", "факт канала"}
    only_global = await streamer_lore.list_lore(1, "")
    assert [it["fact"] for it in only_global] == ["глобальный факт"]
    only_channel = await streamer_lore.list_lore(1, "alekzz")
    assert [it["fact"] for it in only_channel] == ["факт канала"]
    # items содержат channel для бейджа скоупа в UI
    assert all("channel" in it for it in everything)


@pytest.mark.asyncio
async def test_list_learning_star_returns_all_scopes(tmp_db):
    await _make_account(1)
    await learning.add_suggestion(
        account_id=1, channel="", kind="kb_topic", payload={"k": "v"},
        reason="r", source="chat",
    )
    await learning.add_suggestion(
        account_id=1, channel="alekzz", kind="kb_topic", payload={"k": "v2"},
        reason="r2", source="chat",
    )
    everything = await learning.list_suggestions(1, "*")
    assert len(everything) == 2
    assert {it["channel"] for it in everything} == {"", "alekzz"}
    only_global = await learning.list_suggestions(1, "")
    assert len(only_global) == 1 and only_global[0]["channel"] == ""


@pytest.mark.asyncio
async def test_summarizer_list_runs_star_returns_all_channels(tmp_db):
    await _make_account(1)
    p_start = datetime(2026, 8, 30, 10, 0, 0)
    p_end = datetime(2026, 8, 30, 12, 0, 0)
    await summarizer.create_run(account_id=1, channel="alekzz",
                                period_start=p_start, period_end=p_end, lang="ru")
    await summarizer.create_run(account_id=1, channel="other",
                                period_start=p_start, period_end=p_end, lang="ru")
    everything = await summarizer.list_runs(1, "*")
    assert {r["channel"] for r in everything} == {"alekzz", "other"}
    only_one = await summarizer.list_runs(1, "alekzz")
    assert [r["channel"] for r in only_one] == ["alekzz"]
