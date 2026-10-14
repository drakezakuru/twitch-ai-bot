"""Canonical Twitch-channel scope for public data widgets and their events."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse

from app.database import get_db
from app.widget_inventory import LEGACY_PARAM_URLS, WIDGET_BY_ROUTE


_LOGIN_RE = re.compile(r"^[a-z0-9_]{1,25}$")
_MESSAGES = {
    "ru": {
        "missing": "Укажите канал Twitch в URL: ?channel=login или Twitch ID.",
        "unknown": "Канал Twitch не найден. Проверьте URL и настройки панели.",
        "disabled": "Этот канал отключён в панели.",
        "renamed": "Логин канала изменился. Обновите URL Browser Source в OBS.",
        "title": "Виджет не подключён",
    },
    "en": {
        "missing": "Add a Twitch channel to the URL: ?channel=login or Twitch ID.",
        "unknown": "Twitch channel was not found. Check the URL and panel settings.",
        "disabled": "This channel is disabled in the panel.",
        "renamed": "The channel login changed. Update the Browser Source URL in OBS.",
        "title": "Widget is not connected",
    },
    "ua": {
        "missing": "Додайте Twitch-канал до URL: ?channel=login або Twitch ID.",
        "unknown": "Twitch-канал не знайдено. Перевірте URL і налаштування панелі.",
        "disabled": "Цей канал вимкнено в панелі.",
        "renamed": "Логін каналу змінився. Оновіть URL Browser Source в OBS.",
        "title": "Віджет не підключено",
    },
}


def normalize_channel(value: Any) -> str:
    return str(value or "").strip().lower().lstrip("#")


@dataclass(frozen=True, slots=True)
class ChannelIdentity:
    requested: str
    login: str
    twitch_id: str
    enabled: bool
    renamed: bool = False

    @property
    def key(self) -> str:
        return self.twitch_id or self.login

    def payload(self) -> dict[str, str]:
        return {"channel": self.login, "channel_id": self.twitch_id}


async def resolve_channel(value: Any) -> ChannelIdentity | None:
    """Resolve exact login first, then current login, then stable Twitch ID."""
    requested = normalize_channel(value)
    if not requested:
        return None
    db = await get_db()
    try:
        row = await (await db.execute(
            "SELECT c.channel_name,c.twitch_channel_id,c.twitch_channel_login,"
            "MAX(CASE WHEN c.enabled=1 AND a.enabled=1 THEN 1 ELSE 0 END) AS active "
            "FROM channels c JOIN accounts a ON a.id=c.account_id "
            "WHERE lower(ltrim(c.channel_name,'#'))=? "
            "GROUP BY lower(ltrim(c.channel_name,'#')),c.twitch_channel_id,c.twitch_channel_login "
            "ORDER BY active DESC,c.id LIMIT 1",
            (requested,),
        )).fetchone()
        if row is None:
            row = await (await db.execute(
                "SELECT c.channel_name,c.twitch_channel_id,c.twitch_channel_login,"
                "MAX(CASE WHEN c.enabled=1 AND a.enabled=1 THEN 1 ELSE 0 END) AS active "
                "FROM channels c JOIN accounts a ON a.id=c.account_id "
                "WHERE lower(c.twitch_channel_login)=? "
                "GROUP BY c.twitch_channel_id,c.twitch_channel_login "
                "ORDER BY active DESC,c.id LIMIT 1",
                (requested,),
            )).fetchone()
        if row is None and requested.isdigit():
            row = await (await db.execute(
                "SELECT c.channel_name,c.twitch_channel_id,c.twitch_channel_login,"
                "MAX(CASE WHEN c.enabled=1 AND a.enabled=1 THEN 1 ELSE 0 END) AS active "
                "FROM channels c JOIN accounts a ON a.id=c.account_id "
                "WHERE c.twitch_channel_id=? GROUP BY c.twitch_channel_id,c.twitch_channel_login "
                "ORDER BY active DESC,c.id LIMIT 1",
                (requested,),
            )).fetchone()
    finally:
        await db.close()
    if row is None:
        return None
    configured = normalize_channel(row["channel_name"])
    current = normalize_channel(row["twitch_channel_login"]) or configured
    return ChannelIdentity(
        requested=requested,
        login=current,
        twitch_id=str(row["twitch_channel_id"] or ""),
        enabled=bool(row["active"]),
        renamed=bool(current != configured and requested == configured),
    )


async def remember_channel_identity(login: Any, twitch_id: Any) -> None:
    current = normalize_channel(login)
    stable_id = str(twitch_id or "").strip()
    if not current or not stable_id:
        return
    db = await get_db()
    try:
        await db.execute(
            "UPDATE channels SET twitch_channel_id=?,twitch_channel_login=? "
            "WHERE lower(ltrim(channel_name,'#'))=? OR twitch_channel_id=?",
            (stable_id, current, current, stable_id),
        )
        await db.commit()
    finally:
        await db.close()


def widget_ui_language(params: Any, path: str = "") -> str:
    requested = params.get("ui_lang")
    if requested is None:
        requested = "ru" if path == "/obs/tts" else params.get("lang", "ru")
    if requested == "uk":
        return "ua"
    return requested if requested in _MESSAGES else "ru"


def _message(locale: str, key: str) -> str:
    return _MESSAGES.get(locale, {}).get(key) or _MESSAGES["ru"].get(key) or _MESSAGES["ru"]["title"]


def diagnostic_html(code: str, *, lang: str = "ru", identity: ChannelIdentity | None = None) -> str:
    locale = widget_ui_language({"ui_lang": lang})
    detail = _message(locale, code)
    if identity and identity.renamed and code != "renamed":
        detail += f" {_message(locale, 'renamed')} ({html.escape(identity.login)})"
    elif identity and code == "renamed":
        detail += f" ({html.escape(identity.login)})"
    return (
        "<!doctype html><html lang='" + ("uk" if locale == "ua" else locale) + "'><head><meta charset='utf-8'>"
        "<meta name='color-scheme' content='dark'><style>"
        ":root{color-scheme:dark}html,body{margin:0;height:100%;background:#0f0f1a;"
        "color:#e5e7eb;font:16px/1.45 system-ui,sans-serif}body{display:grid;place-items:center}"
        ".card{max-width:34rem;margin:1rem;padding:1.25rem;border:1px solid #374151;"
        "border-radius:12px;background:#171725;text-align:center}h1{font-size:1.1rem;margin:0 0 .6rem}"
        "p{color:#cbd5e1;margin:0}</style></head><body><main class='card' role='alert'>"
        f"<h1>{html.escape(_message(locale, 'title'))}</h1><p>{detail}</p>"
        f"<span hidden data-widget-diagnostic='{html.escape(code)}'></span></main></body></html>"
    )


def _rename_warning(lang: str, identity: ChannelIdentity) -> str:
    locale = widget_ui_language({"ui_lang": lang})
    text = f"{_message(locale, 'renamed')} ({html.escape(identity.login)})"
    return (
        "<aside data-widget-channel-warning='renamed' role='status' style='position:fixed;"
        "z-index:2147483647;left:12px;right:12px;top:12px;padding:10px 14px;"
        "border:1px solid #f59e0b;border-radius:10px;background:#271d0b;color:#fde68a;"
        "font:14px/1.4 system-ui,sans-serif;text-align:center'>"
        f"{text}</aside>"
    )


async def widget_channel_middleware(request: Request, call_next):
    route = LEGACY_PARAM_URLS.get(request.url.path, request.url.path).split("?", 1)[0]
    contract = WIDGET_BY_ROUTE.get(route)
    if not contract or not contract.requires_channel or request.query_params.get("preview") == "1":
        return await call_next(request)
    lang = widget_ui_language(request.query_params, request.url.path)
    requested = request.query_params.get("channel", "")
    if not requested:
        return HTMLResponse(diagnostic_html("missing", lang=lang), status_code=200)
    identity = await resolve_channel(requested)
    if identity is None:
        return HTMLResponse(diagnostic_html("unknown", lang=lang), status_code=200)
    if not identity.enabled:
        return HTMLResponse(diagnostic_html("disabled", lang=lang, identity=identity), status_code=200)
    response = await call_next(request)
    if identity.renamed and response.headers.get("content-type", "").startswith("text/html"):
        body = b"".join([chunk async for chunk in response.body_iterator])
        document = body.decode("utf-8", "replace")
        warning = _rename_warning(lang, identity)
        document = document.replace("</body>", warning + "</body>")
        headers = dict(response.headers)
        headers.pop("content-length", None)
        return HTMLResponse(document, status_code=response.status_code, headers=headers)
    return response
