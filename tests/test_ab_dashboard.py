"""Tests for app.ab_dashboard (pure helpers + ranking)."""

from __future__ import annotations

import pytest

from app.ab_dashboard import (
    like_ratio,
    rank_variants,
    safe_div,
    summary_metrics,
    total_responses,
    variant_score,
)


def test_safe_div_basic():
    assert safe_div(10, 2) == 5.0
    assert safe_div(10, 0, default=-1) == -1
    assert safe_div("x", 1, default=0) == 0


def test_like_ratio_no_total():
    assert like_ratio(0, 0) == 0.0


def test_like_ratio_all_likes():
    assert like_ratio(10, 0) == 1.0


def test_like_ratio_half():
    assert like_ratio(5, 5) == 0.5


def test_variant_score_all_zero():
    score = variant_score(
        likes=0, dislikes=0, avg_support=0, avg_mentions=0,
        avg_replies=0, breakthroughs=0, n_responses=0,
    )
    assert score == 0.0


def test_variant_score_likes_positive():
    score = variant_score(
        likes=10, dislikes=2, avg_support=0, avg_mentions=0,
        avg_replies=0, breakthroughs=0, n_responses=10,
    )
    # raw = 8, normalize by sqrt(11) ≈ 3.317
    assert 2.0 < score < 3.0


def test_variant_score_dislikes_drag_down():
    s_good = variant_score(
        likes=10, dislikes=0, avg_support=0, avg_mentions=0,
        avg_replies=0, breakthroughs=0, n_responses=10,
    )
    s_bad = variant_score(
        likes=0, dislikes=10, avg_support=0, avg_mentions=0,
        avg_replies=0, breakthroughs=0, n_responses=10,
    )
    assert s_good > 0
    assert s_bad < 0


def test_variant_score_breakthroughs_weighted():
    base = variant_score(
        likes=0, dislikes=0, avg_support=0, avg_mentions=0,
        avg_replies=0, breakthroughs=0, n_responses=10,
    )
    with_bt = variant_score(
        likes=0, dislikes=0, avg_support=0, avg_mentions=0,
        avg_replies=0, breakthroughs=5, n_responses=10,
    )
    assert with_bt > base


def test_variant_score_normalizes_by_responses():
    # Маленький sample — большой score не должен переоценить редкий вариант
    s_small = variant_score(
        likes=5, dislikes=0, avg_support=0, avg_mentions=0,
        avg_replies=0, breakthroughs=0, n_responses=1,
    )
    s_large = variant_score(
        likes=5, dislikes=0, avg_support=0, avg_mentions=0,
        avg_replies=0, breakthroughs=0, n_responses=1000,
    )
    assert s_small > s_large


def test_rank_variants_sorts_desc():
    variants = [
        {"id": 1, "score": 0.5},
        {"id": 2, "score": 1.5},
        {"id": 3, "score": -0.5},
    ]
    ranked = rank_variants(variants)
    assert ranked[0]["id"] == 2
    assert ranked[0]["rank"] == 1
    assert ranked[1]["id"] == 1
    assert ranked[2]["id"] == 3


def test_rank_variants_leader_marked():
    variants = [
        {"id": 1, "score": 0.5},
        {"id": 2, "score": 1.5},
    ]
    ranked = rank_variants(variants)
    assert ranked[0]["recommendation"] == "leader"


def test_rank_variants_drop_marked():
    variants = [{"id": 1, "score": -1.5}]
    ranked = rank_variants(variants)
    assert ranked[0]["recommendation"] == "drop"


def test_rank_variants_keep_marked():
    variants = [{"id": 1, "score": -0.2}]
    ranked = rank_variants(variants)
    assert ranked[0]["recommendation"] == "keep"


def test_rank_variants_no_leader_if_negative():
    variants = [{"id": 1, "score": 0.0}]
    ranked = rank_variants(variants)
    assert ranked[0]["recommendation"] == "keep"  # 0.0 не leader


def test_total_responses():
    variants = [
        {"n_responses": 10},
        {"n_responses": 5},
        {"n_responses": 0},
    ]
    assert total_responses(variants) == 15


def test_summary_metrics_basic():
    variants = [
        {"label": "A", "n_responses": 10, "likes": 8, "dislikes": 2, "breakthroughs": 1, "rank": 1, "score": 1.0},
        {"label": "B", "n_responses": 5, "likes": 1, "dislikes": 3, "breakthroughs": 0, "rank": 2, "score": -0.5},
    ]
    s = summary_metrics(variants)
    assert s["n_variants"] == 2
    assert s["n_responses"] == 15
    assert s["likes"] == 9
    assert s["dislikes"] == 5
    assert s["breakthroughs"] == 1
    assert s["leader"] == "A"


def test_summary_metrics_empty():
    s = summary_metrics([])
    assert s["n_variants"] == 0
    assert s["n_responses"] == 0
    assert s["leader"] == ""

# Владелец 27.09 (вечер): бэкенд A/B-теста промптов существовал без экрана —
# добавляем route-level регресс на весь цикл, раз он теперь реально используется.
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.database import get_db, init_db


@pytest_asyncio.fixture
async def client(tmp_db, disable_auth):
    from app.server import app
    await init_db()
    db = await get_db()
    try:
        await db.execute("INSERT INTO accounts(nickname, token, enabled) VALUES ('abbot', 'x', 1)")
        await db.commit()
    finally:
        await db.close()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as value:
        yield value


@pytest.mark.asyncio
async def test_variant_crud_feeds_the_dashboard(client):
    resp = await client.post("/api/accounts/1/prompt-variants", json={
        "label": "A", "system_prompt": "Ты дружелюбный", "weight": 70,
    })
    assert resp.status_code == 200, resp.text
    variant_id = resp.json()["id"]

    resp = await client.get("/api/accounts/1/prompt-variants")
    items = resp.json()["items"]
    assert len(items) == 1 and items[0]["label"] == "A"

    resp = await client.get("/api/ab-dashboard?account_id=1")
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["ok"] is True
    assert payload["summary"]["n_variants"] == 1
    assert payload["variants"][0]["id"] == variant_id

    resp = await client.put(f"/api/accounts/1/prompt-variants/{variant_id}", json={"enabled": False})
    assert resp.status_code == 200, resp.text

    resp = await client.delete(f"/api/accounts/1/prompt-variants/{variant_id}")
    assert resp.status_code == 200, resp.text
    assert (await client.get("/api/accounts/1/prompt-variants")).json()["items"] == []


@pytest.mark.asyncio
async def test_use_ab_variants_toggle_persists_via_analyzer_settings(client):
    resp = await client.put("/api/accounts/1/analyzer", json={"use_ab_variants": True})
    assert resp.status_code == 200, resp.text
    resp = await client.get("/api/accounts/1/analyzer")
    assert resp.json()["use_ab_variants"] is True
