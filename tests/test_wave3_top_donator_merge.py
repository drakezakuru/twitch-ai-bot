"""Wave 3 (owner survey Q15-17: М): три top-donator → одна реализация.

Виджет и публичный API параметризованы периодом; три исторических URL
(`/widget/top-donator-alltime|-month|-day`) сохранены — они уже стоят в
OBS-сценах владельца.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


async def _client():
    from app.database import init_db
    from app.widgets import admin_router, public_router, ensure_widgets_schema
    await init_db()
    await ensure_widgets_schema()
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(public_router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_public_api_is_period_parameterized(tmp_db, disable_auth):
    async with await _client() as c:
        for period in ("alltime", "month", "day"):
            r = await c.get(f"/api/widgets/public/top-donator/{period}")
            assert r.status_code == 200, period
            body = r.json()
            assert body["period"] == period
            assert "donors" in body and "title" in body and "theme" in body


async def test_public_api_rejects_unknown_period(tmp_db, disable_auth):
    async with await _client() as c:
        body = (await c.get("/api/widgets/public/top-donator/quarter")).json()
        assert body.get("error") == "bad_period"
        assert body["allowed"] == ["alltime", "month", "day"]


async def test_titles_stay_per_period(tmp_db, disable_auth):
    """Объединение не должно склеить три разных заголовка в один."""
    async with await _client() as c:
        await c.put("/api/widgets/top-donators", json={
            "title_alltime": "За всё время", "title_month": "За месяц", "title_day": "За день",
        })
        titles = {}
        for period in ("alltime", "month", "day"):
            titles[period] = (await c.get(f"/api/widgets/public/top-donator/{period}")).json()["title"]
        assert titles == {
            "alltime": "За всё время", "month": "За месяц", "day": "За день",
        }


async def test_legacy_urls_pin_their_period(tmp_db, disable_auth):
    async with await _client() as c:
        for legacy, period in (
            ("/widget/top-donator-alltime", "alltime"),
            ("/widget/top-donator-month", "month"),
            ("/widget/top-donator-day", "day"),
        ):
            old = await c.get(legacy)
            new = await c.get(f"/widget/top-donator?period={period}")
            assert old.status_code == 200, legacy
            assert old.text == new.text, f"{legacy} разошёлся с каноническим URL"
            assert "__PERIOD__" not in old.text, "период не подставлен в HTML"


async def test_unknown_period_falls_back_to_alltime(tmp_db, disable_auth):
    async with await _client() as c:
        bogus = await c.get("/widget/top-donator?period=quarter")
        alltime = await c.get("/widget/top-donator?period=alltime")
        assert bogus.status_code == 200
        assert bogus.text == alltime.text
