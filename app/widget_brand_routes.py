"""Q28 (DEC-OWNER-017 п.5): брендовая палитра акцентов виджетов — per-канал.

У каждого канала своя палитра (DEC-OWNER-002): цвета хранятся в settings-kv
``widget_brand_palette:<channel>`` (JSON-список hex-цветов, ≤10). Палитру
редактируют в шапке «Виджетов», а из карточек виджетов её цвета применяются
к превью (accent) одним кликом или пипеткой.

Подключается одной строкой include_router в app/server.py.
"""
from __future__ import annotations

import json
import re
from typing import Any

from fastapi import APIRouter, Depends

from app.database import get_setting, set_setting
from app.security import auth_dependency

router = APIRouter(dependencies=[Depends(auth_dependency)])

MAX_COLORS = 10
_DEFAULT_PALETTE = ["#A78BFA", "#22D3EE", "#22C55E", "#F97316", "#F87171", "#FFD700"]


def _normalize_channel(channel: str) -> str:
    return (channel or "").strip().lower().lstrip("#")


def _normalize_hex(value: Any, fallback: str | None = None) -> str | None:
    raw = str(value or "").strip()
    if raw.startswith("#"):
        raw = raw[1:]
    if not re.fullmatch(r"[0-9a-fA-F]{6}", raw):
        return fallback
    return f"#{raw.upper()}"


def _palette_key(channel: str) -> str:
    return f"widget_brand_palette:{_normalize_channel(channel)}"


async def get_brand_palette(channel: str) -> list[str]:
    """Палитра канала; нет своей — дефолтный набор (наследуется, как пресет)."""
    raw = await get_setting(_palette_key(channel), "")
    if not raw:
        return list(_DEFAULT_PALETTE)
    try:
        stored = json.loads(raw)
    except (TypeError, ValueError):
        return list(_DEFAULT_PALETTE)
    if not isinstance(stored, list):
        return list(_DEFAULT_PALETTE)
    colors = []
    for item in stored[:MAX_COLORS]:
        color = _normalize_hex(item)
        if color and color not in colors:
            colors.append(color)
    return colors or list(_DEFAULT_PALETTE)


@router.get("/api/widgets/brand-palette")
async def brand_palette_get(channel: str = "") -> dict:
    return {"ok": True, "channel": _normalize_channel(channel), "colors": await get_brand_palette(channel)}


@router.put("/api/widgets/brand-palette")
async def brand_palette_put(payload: dict) -> dict:
    channel = _normalize_channel(str(payload.get("channel") or ""))
    if not channel:
        return {"ok": False, "error": "channel_required"}
    raw_colors = payload.get("colors")
    if not isinstance(raw_colors, list) or not (1 <= len(raw_colors) <= MAX_COLORS):
        return {"ok": False, "error": "colors_invalid", "max": MAX_COLORS}
    colors: list[str] = []
    for item in raw_colors:
        color = _normalize_hex(item)
        if color and color not in colors:
            colors.append(color)
    if not colors:
        return {"ok": False, "error": "colors_invalid", "max": MAX_COLORS}
    await set_setting(_palette_key(channel), json.dumps(colors, ensure_ascii=False))
    return {"ok": True, "channel": channel, "colors": colors}
