"""Эндпоинты для сбора и синхронизации смайлов канала (7TV, BTTV, FFZ)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.channel_emotes import (
    get_cached_channel_emotes,
    get_channel_emotes,
    get_channel_emotes_summary,
    sync_channel_emotes,
)
from app.routes import log_action
from app.security import auth_dependency

router = APIRouter(dependencies=[Depends(auth_dependency)], tags=["channel-emotes"])


@router.get("/api/channels/{channel}/emotes")
async def get_emotes_endpoint(channel: str, full: int = Query(0)) -> dict[str, Any]:
    """Возвращает сводку или полный список смайлов канала."""
    summary = get_channel_emotes_summary(channel)
    if full:
        emotes = await get_channel_emotes(channel, force_sync=False)
        return {**summary, "all_emotes": emotes}
    return summary


@router.post("/api/channels/{channel}/emotes/sync")
async def sync_emotes_endpoint(channel: str) -> dict[str, Any]:
    """Запускает принудительную синхронизацию смайлов канала из 7TV, BTTV и FFZ."""
    summary = await sync_channel_emotes(channel)
    await log_action(
        "sync_channel_emotes",
        f"Синхронизированы смайлы канала #{channel}: найдено {summary.get('total_count', 0)} (7TV: {summary.get('sources', {}).get('7tv', 0)}, BTTV: {summary.get('sources', {}).get('bttv', 0)}, FFZ: {summary.get('sources', {}).get('ffz', 0)})",
    )
    return summary
