"""§11.2 WIDGETS_PLAN: автозаполнение виджета Now Playing.

Источники (приоритет настраивается в панели, вкладка «Виджеты»):
    * ``lastfm`` — polling Last.fm API (user.getrecenttracks, nowplaying=true),
      нужны ``lastfm_user`` + ``lastfm_api_key``.
    * ``mpris``  — локальный плеер через ``playerctl -a metadata``
      (Linux / Steam Deck: Spotify, браузерный YT Music и т.п.).
    * ``manual`` — только ручное заполнение из панели или чат-командой ``!np``
      (fallback; источник по умолчанию, loop ничего не пишет).

Ручные правки (панель / !np) всегда приоритетнее: loop обновляет виджет только
если источник включён и трек реально изменился (дедуп по ``text``).
"""

from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)

_LASTFM_URL = "https://ws.audioscrobbler.com/2.0/"


async def get_np_source_settings() -> dict:
    from app.widgets import _get_np_source_settings
    return await _get_np_source_settings()


async def poll_lastfm(settings: dict) -> dict | None:
    """Last.fm user.getrecenttracks → {text, subtext} или None."""
    user = (settings.get("lastfm_user") or "").strip()
    api_key = (settings.get("lastfm_api_key") or "").strip()
    if not user or not api_key:
        return None
    try:
        import httpx
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(_LASTFM_URL, params={
                "method": "user.getrecenttracks",
                "user": user,
                "api_key": api_key,
                "format": "json",
                "limit": 1,
            })
            if resp.status_code != 200:
                return None
            tracks = (
                resp.json().get("recenttracks", {}).get("track", [])
            )
            if isinstance(tracks, dict):
                tracks = [tracks]
            for track in tracks:
                if not isinstance(track, dict):
                    continue
                if track.get("@attr", {}).get("nowplaying") != "true":
                    continue
                name = (track.get("name") or "").strip()
                artist = (track.get("artist", {}) or {}).get("#text", "").strip()
                if name:
                    return {"text": name, "subtext": artist, "kind": "music"}
            return None
    except Exception as exc:
        logger.debug("[now-playing/lastfm] poll failed: %s", exc)
        return None


async def poll_mpris(settings: dict) -> dict | None:
    """playerctl metadata → {text, subtext} или None (нет playerctl / плеера)."""
    player = (settings.get("mpris_player") or "").strip()
    try:
        proc = await asyncio.create_subprocess_exec(
            *(["playerctl", "-p", player, "metadata", "--format",
               "{{ title }}|||{{ artist }}"] if player else
              ["playerctl", "metadata", "--format", "{{ title }}|||{{ artist }}"]),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        except asyncio.TimeoutError:
            proc.kill()
            return None
        if proc.returncode != 0:
            return None
        line = out.decode("utf-8", "replace").strip().splitlines()
        if not line:
            return None
        title, _, artist = line[0].partition("|||")
        title = title.strip()
        if not title or title.lower() == "no players found":
            return None
        return {"text": title, "subtext": artist.strip(), "kind": "music"}
    except FileNotFoundError:
        return None  # playerctl не установлен
    except Exception as exc:
        logger.debug("[now-playing/mpris] poll failed: %s", exc)
        return None


async def poll_once() -> dict | None:
    """Один опрос активного источника. None = нечего писать в виджет."""
    settings = await get_np_source_settings()
    source = (settings.get("source") or "manual").strip().lower()
    if source == "lastfm":
        return await poll_lastfm(settings)
    if source == "mpris":
        return await poll_mpris(settings)
    return None


async def now_playing_loop() -> None:
    """Фоновый цикл (запускается из server.lifespan одной строкой).

    Пишет только в legacy compatibility state: локальный MPRIS/Last.fm
    источник не имеет account/channel scope и не размножается по каналам.
    """
    logger.info("[now-playing] sources loop запущен")
    last_text: str | None = None
    interval = 15
    while True:
        try:
            settings = await get_np_source_settings()
            interval = max(5, int(settings.get("poll_seconds") or 15))
            data = await poll_once()
            if data and data.get("text") and data["text"] != last_text:
                from app.widgets import apply_now_playing
                await apply_now_playing({**data, "source": "auto"})
                last_text = data["text"]
                logger.info("[now-playing] автообновление: %s — %s",
                            data["text"], data.get("subtext", ""))
            elif not data:
                last_text = None
        except Exception as exc:
            logger.debug("[now-playing] loop iteration failed: %s", exc)
        await asyncio.sleep(interval)
