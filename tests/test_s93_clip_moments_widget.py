"""§9.3: публичный роут последних моментов клипов для OBS-виджета."""
import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


async def test_clip_moments_public(tmp_db, disable_auth):
    from app.database import init_db, get_db
    from app.widgets import admin_router, public_router
    from fastapi import FastAPI

    await init_db()
    db = await get_db()
    try:
        await db.executemany(
            "INSERT INTO accounts (id, nickname, token) VALUES (?, ?, 'fake')",
            ((7, "clip_a"), (8, "clip_b")),
        )
        await db.executemany(
            "INSERT INTO channels (account_id, channel_name, enabled) VALUES (?, ?, ?)",
            ((7, "wow", 1), (7, "other", 1), (7, "disabled", 0), (8, "wow", 1)),
        )
        await db.executemany(
            "INSERT INTO clip_moments (account_id, channel, rate, avg_rate, clip_url, timestamp) "
            "VALUES (?, ?, ?, 0.8, '', '2026-08-30T01:00:00')",
            ((7, "wow", 2.5), (7, "other", 3.5), (8, "wow", 4.5)),
        )
        await db.commit()
    finally:
        await db.close()

    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(public_router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/widgets/public/clip-moments?account_id=7&channel=%20%23WOW%20"
        )
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1 and items[0]["channel"] == "wow" and items[0]["rate"] == 2.5

        other_account = await client.get(
            "/api/widgets/public/clip-moments?account_id=8&channel=wow"
        )
        assert [item["rate"] for item in other_account.json()] == [4.5]

        missing_account = await client.get(
            "/api/widgets/public/clip-moments?channel=wow"
        )
        assert missing_account.status_code == 400
        assert missing_account.json()["detail"] == "binding_scope_required"

        disabled = await client.get(
            "/api/widgets/public/clip-moments?account_id=7&channel=disabled"
        )
        assert disabled.status_code == 400
        assert disabled.json()["detail"] == "binding_scope_not_found"

        legacy_account = await client.get(
            "/api/widgets/public/clip-moments?account_id=7"
        )
        assert {item["channel"] for item in legacy_account.json()} == {"wow", "other"}
        legacy_global = await client.get("/api/widgets/public/clip-moments")
        assert len(legacy_global.json()) == 3


async def test_clip_moments_browser_source_forwards_exact_scope():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "widgets/clip-moments/index.html").read_text(
        encoding="utf-8"
    )
    assert "qs.get('account_id')" in source
    assert "qs.get('channel')" in source
    assert "q.set('account_id', String(scopedAccount))" in source
    assert "q.set('channel', scopedChannel)" in source
