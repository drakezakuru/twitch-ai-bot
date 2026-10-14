"""Q28 (DEC-OWNER-017 п.5): брендовая палитра виджетов — per-канал.

Проверяем: дефолтный набор при отсутствии своей палитры; сохранение с
нормализацией hex и лимитом 10; per-канальную изоляцию (DEC-OWNER-002);
нормализацию канала (#Test_Channel → test_channel); отклонение мусора.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_default_palette_when_channel_has_none(tmp_db):
    from app.database import init_db
    from app.widget_brand_routes import get_brand_palette

    await init_db()
    colors = await get_brand_palette("test_channel")
    assert colors and all(c.startswith("#") and len(c) == 7 for c in colors)


async def test_put_normalizes_and_persists(tmp_db):
    from app.database import init_db, get_setting
    from app.widget_brand_routes import brand_palette_put, get_brand_palette

    await init_db()
    result = await brand_palette_put({"channel": "#Test_Channel", "colors": ["ff00aa", "#00ffaa", "nothex", "#00ffaa"]})
    assert result["ok"] is True
    assert result["channel"] == "test_channel"
    # нормализация: uppercase, дедуп, мусор отброшен
    assert result["colors"] == ["#FF00AA", "#00FFAA"]
    assert (await get_setting("widget_brand_palette:test_channel", "")).startswith("[")
    assert (await get_brand_palette("test_channel")) == ["#FF00AA", "#00FFAA"]


async def test_palettes_are_per_channel(tmp_db):
    from app.database import init_db
    from app.widget_brand_routes import brand_palette_put, get_brand_palette

    await init_db()
    await brand_palette_put({"channel": "a", "colors": ["#FF0000"]})
    await brand_palette_put({"channel": "b", "colors": ["#00FF00"]})
    assert (await get_brand_palette("a")) == ["#FF0000"]
    assert (await get_brand_palette("b")) == ["#00FF00"]
    # канал без своей палитры — дефолт, не чужая
    assert (await get_brand_palette("c")) != ["#FF0000"]


async def test_put_rejects_bad_payloads(tmp_db):
    from app.database import init_db
    from app.widget_brand_routes import brand_palette_put, MAX_COLORS

    await init_db()
    assert (await brand_palette_put({"channel": "", "colors": ["#FF0000"]}))["ok"] is False
    assert (await brand_palette_put({"channel": "a", "colors": "nope"}))["ok"] is False
    assert (await brand_palette_put({"channel": "a", "colors": []}))["ok"] is False
    too_many = ["#FF0000"] * (MAX_COLORS + 1)
    assert (await brand_palette_put({"channel": "a", "colors": too_many}))["ok"] is False
    assert (await brand_palette_put({"channel": "a", "colors": ["zzzzzz"]}))["ok"] is False


async def test_routes_registered(tmp_db):
    from app.server import app

    paths = {route.path for route in app.routes}
    assert "/api/widgets/brand-palette" in paths
