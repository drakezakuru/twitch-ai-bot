"""Синхронизация и сбор смайлов канала (7TV, BTTV, FFZ, Twitch, Default).

Позволяет ботам естественно реагировать на спам смайлов и мемы конкретного канала,
а не только на базовый набор KEKW/LULW.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from app.highlights import DEFAULT_REACTION_TOKENS

logger = logging.getLogger("channel_emotes")

_CACHE_TTL_SEC = 7200.0  # 2 часа

# In-memory кэш: channel -> (timestamp, list[str])
_EMOTE_CACHE: dict[str, tuple[float, list[str]]] = {}
# Кэш с разбивкой по источникам: channel -> (timestamp, dict[str, Any])
_EMOTE_DETAILS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


async def _safe_fetch_json(client: httpx.AsyncClient, url: str) -> Any:
    """Безопасный HTTP GET с таймаутом."""
    try:
        resp = await client.get(url, headers={"User-Agent": "TwitchAIBot/1.0"})
        if resp.status_code == 200:
            return resp.json()
    except Exception as exc:
        logger.debug("Fetch failed for %s: %s", url, exc)
    return None


async def fetch_7tv_emotes(client: httpx.AsyncClient, channel: str, user_id: str = "") -> list[str]:
    """Сбор смайлов 7TV (global + channel)."""
    names: set[str] = set()

    # 1. Global 7TV
    data = await _safe_fetch_json(client, "https://7tv.io/v3/emote-sets/global")
    if isinstance(data, dict):
        for e in data.get("emotes") or []:
            if isinstance(e, dict) and e.get("name"):
                names.add(str(e["name"]))

    # 2. Channel 7TV
    channel_clean = channel.lower().lstrip("#")
    if user_id:
        cdata = await _safe_fetch_json(client, f"https://7tv.io/v3/users/twitch/{user_id}")
        if isinstance(cdata, dict):
            em_set = cdata.get("emote_set") or {}
            for e in em_set.get("emotes") or []:
                if isinstance(e, dict) and e.get("name"):
                    names.add(str(e["name"]))

    return sorted(names)


async def fetch_bttv_emotes(client: httpx.AsyncClient, channel: str, user_id: str = "") -> list[str]:
    """Сбор смайлов BTTV (global + channel)."""
    codes: set[str] = set()

    # 1. Global BTTV
    data = await _safe_fetch_json(client, "https://api.betterttv.net/3/cached/emotes/global")
    if isinstance(data, list):
        for e in data:
            if isinstance(e, dict) and e.get("code"):
                codes.add(str(e["code"]))

    # 2. Channel BTTV
    if user_id:
        cdata = await _safe_fetch_json(client, f"https://api.betterttv.net/3/cached/users/twitch/{user_id}")
        if isinstance(cdata, dict):
            for key in ("channelEmotes", "sharedEmotes"):
                for e in cdata.get(key) or []:
                    if isinstance(e, dict) and e.get("code"):
                        codes.add(str(e["code"]))

    return sorted(codes)


async def fetch_ffz_emotes(client: httpx.AsyncClient, channel: str) -> list[str]:
    """Сбор смайлов FrankerFaceZ (global + room)."""
    names: set[str] = set()
    channel_clean = channel.lower().lstrip("#")

    # 1. Room FFZ
    if channel_clean:
        rdata = await _safe_fetch_json(client, f"https://api.frankerfacez.com/v1/room/{channel_clean}")
        if isinstance(rdata, dict):
            sets = rdata.get("sets") or {}
            for s in sets.values():
                for em in (s.get("emoticons") if isinstance(s, dict) else []) or []:
                    if isinstance(em, dict) and em.get("name"):
                        names.add(str(em["name"]))

    # 2. Global FFZ
    gdata = await _safe_fetch_json(client, "https://api.frankerfacez.com/v1/set/global")
    if isinstance(gdata, dict):
        sets = gdata.get("sets") or {}
        for s in sets.values():
            for em in (s.get("emoticons") if isinstance(s, dict) else []) or []:
                if isinstance(em, dict) and em.get("name"):
                    names.add(str(em["name"]))

    return sorted(names)


async def _resolve_twitch_user_id(channel: str) -> str:
    """Пытается определить twitch user id через Helix или БД."""
    channel_clean = channel.lower().lstrip("#")
    if not channel_clean:
        return ""
    try:
        from app.chat_analyzer import _account_token as _tok_map
        token = None
        if hasattr(_tok_map, "get"):
            for aid in list(getattr(_tok_map, "keys", lambda: [])()):
                tok = _tok_map.get(aid)
                if tok:
                    token = tok
                    break
        if token:
            from app.twitch_helix import get_user_id
            uid = await get_user_id(channel_clean, token)
            if uid:
                return str(uid)
    except Exception as exc:
        logger.debug("Failed to resolve user_id for %s: %s", channel, exc)
    return ""


async def sync_channel_emotes(channel: str) -> dict[str, Any]:
    """Синхронизирует все смайлы канала из внешних API и обновляет кэш."""
    channel_clean = channel.lower().lstrip("#")
    now = time.time()
    user_id_res = _resolve_twitch_user_id(channel_clean)
    if asyncio.iscoroutine(user_id_res):
        user_id = await user_id_res
    else:
        user_id = str(user_id_res or "")

    timeout = httpx.Timeout(5.0, connect=3.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        t7_task = fetch_7tv_emotes(client, channel_clean, user_id)
        bttv_task = fetch_bttv_emotes(client, channel_clean, user_id)
        ffz_task = fetch_ffz_emotes(client, channel_clean)

        res_7tv, res_bttv, res_ffz = await asyncio.gather(
            t7_task, bttv_task, ffz_task, return_exceptions=True
        )

    list_7tv = res_7tv if isinstance(res_7tv, list) else []
    list_bttv = res_bttv if isinstance(res_bttv, list) else []
    list_ffz = res_ffz if isinstance(res_ffz, list) else []

    all_emotes_set: set[str] = set(DEFAULT_REACTION_TOKENS)
    all_emotes_set.update(list_7tv)
    all_emotes_set.update(list_bttv)
    all_emotes_set.update(list_ffz)

    combined_list = sorted(all_emotes_set)
    _EMOTE_CACHE[channel_clean] = (now, combined_list)

    summary = {
        "ok": True,
        "channel": channel_clean,
        "total_count": len(combined_list),
        "sources": {
            "7tv": len(list_7tv),
            "bttv": len(list_bttv),
            "ffz": len(list_ffz),
            "default": len(DEFAULT_REACTION_TOKENS),
        },
        "sample": combined_list[:60],
        "synced_at": now,
    }
    _EMOTE_DETAILS_CACHE[channel_clean] = (now, summary)
    return summary


def get_cached_channel_emotes(channel: str) -> list[str]:
    """Быстрый синхронный доступ к кэшированным смайлам канала."""
    channel_clean = channel.lower().lstrip("#")
    now = time.time()
    cached = _EMOTE_CACHE.get(channel_clean)
    if cached and (now - cached[0]) < _CACHE_TTL_SEC:
        return cached[1]
    # Fallback на глобальный или базовый набор
    global_cached = _EMOTE_CACHE.get("")
    if global_cached and (now - global_cached[0]) < _CACHE_TTL_SEC:
        return global_cached[1]
    return list(DEFAULT_REACTION_TOKENS)


async def get_channel_emotes(channel: str, force_sync: bool = False) -> list[str]:
    """Возвращает список всех известных смайлов для канала, при необходимости делая sync."""
    channel_clean = channel.lower().lstrip("#")
    now = time.time()
    cached = _EMOTE_CACHE.get(channel_clean)
    if not force_sync and cached and (now - cached[0]) < _CACHE_TTL_SEC:
        return cached[1]

    data = await sync_channel_emotes(channel_clean)
    return _EMOTE_CACHE.get(channel_clean, (now, list(DEFAULT_REACTION_TOKENS)))[1]


def get_channel_emotes_summary(channel: str) -> dict[str, Any]:
    """Возвращает сводку по смайлам канала."""
    channel_clean = channel.lower().lstrip("#")
    now = time.time()
    cached = _EMOTE_DETAILS_CACHE.get(channel_clean)
    if cached and (now - cached[0]) < _CACHE_TTL_SEC:
        return cached[1]
    # Default placeholder
    emotes = get_cached_channel_emotes(channel_clean)
    return {
        "ok": True,
        "channel": channel_clean,
        "total_count": len(emotes),
        "sources": {
            "7tv": 0,
            "bttv": 0,
            "ffz": 0,
            "default": len(DEFAULT_REACTION_TOKENS),
        },
        "sample": emotes[:60],
        "synced_at": 0,
    }
