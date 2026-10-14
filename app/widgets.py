"""v10.4.6 — OBS-виджеты.

Пять self-contained виджетов — каждый отдаётся как отдельный HTML-URL,
который кидаешь в OBS как Browser Source:

* ``/widget/animated-bg`` — анимированный фон (snow/stars/fire/rain/embers).
* ``/widget/goals`` — чек-лист «Цели на стрим».
* ``/widget/now-playing`` — мануальный «Что сейчас» (текст +
  опц. thumbnail). Для YouTube ссылки бот сам вытаскивает превью и
  название видео через oembed (без API-ключей).
* ``/widget/sub-goal`` — креативная sub goal-визуализация (дерево/риф/город).
* ``/widget/schedule`` — расписание-баннер «Сейчас / Скоро».

Endpoints без HTTP-auth (OBS Browser Source не умеет HTTP Basic), поэтому
HTML-страницы и публичные read-only endpoints висят на ``public_router``
(без auth_dependency). Управляющие endpoints (CRUD из панели) — на
``admin_router`` (с auth).

Now Playing — мануальный режим (v10.4.6): стример сам пишет в
панели «слушаю Imagine Dragons» / «смотрю обзор PS5». Если в поле
icon_url вставлен YouTube URL — бот вытягивает thumbnail и title через
oembed (без API-ключей). Spotify OAuth-вариант убран — оказался лишним.

EventSub-хук в ``on_subscribe_event`` — когда происходит
``channel.subscribe``, sub_goal.current инкрементится автоматически.
Если EventSub не настроен — счётчик можно крутить вручную из панели.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import sqlite3
import time
from html import escape
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from app.database import _add_column_if_missing, get_db, get_setting, set_setting
from app.emoji_core import EMOJI_PATTERN, count_emojis
from app.security import (
    auth_dependency,
    credential_storage_mode,
    decrypt_token,
    encrypt_token,
    is_encryption_enabled,
    mask_token,
    require_loopback_client,
    require_same_origin_request,
)
from app.widget_inventory import RETIRED_WIDGETS, RETIRED_WIDGET_TRANSLATIONS


logger = logging.getLogger(__name__)

# ══ §5 WIDGETS_PLAN: виджеты живут в папке widgets/<name>/index.html ══
# Каждый виджет — самостоятельный HTML-файл (можно править на лету и копировать
# папку widgets/ целиком для использования без панели). Роуты /widget/* читают
# файл с диска; mtime-кэш перечитывает изменённый файл без рестарта.
WIDGETS_DIR = Path(__file__).resolve().parent.parent / "widgets"
_widget_cache: dict[str, tuple[tuple[int, ...], str]] = {}

# Only bounded overlays opt into shared scale/position controls. Full-scene,
# strip, and native-design widgets keep their own coordinate contracts.
_WIDGET_BOUNDED_ROOTS: dict[str, str] = {
    "goals": "#box",
    "now-playing": "#np",
    "sub-goal": ".wrap",
    "schedule": "#wrap",
    "stream-session": "#box",
    "lower-third": "#lt",
    "mascot": "#stage",
    "chat-highlight": ".wrap",
    "chat-roulette": ".roulette-wrap",
    "song-request": "#wrap",
    "top-donator": "#wrap",
    "countdown": "#wrap",
    "donation-challenge": "#wrap, #noChallenge",
    "clip-moments": ".box",
    "latest-event-card": "#card",
    "tts-bot": "#tts-container",
    "tts-chat-overlay": "#tts-chat",
    "hype-meter": "#box",
    "subathon-timer": "#box",
    "emoji-leaderboard": ".box",
    "emoji-chat": "#list",
    "selected-chat": "#selectedChat",
    "mod-feed": "#feed",
    "soundboard": "#state",
    "recent-events": "#events",
    "streamer-hud": "#hud",
}


def _widget_html(name: str) -> str:
    path = WIDGETS_DIR / name / "index.html"
    theme_path = WIDGETS_DIR / "_shared" / "theme.css"
    appearance_path = WIDGETS_DIR / "_shared" / "appearance.js"
    i18n_path = WIDGETS_DIR / "_shared" / "i18n.js"
    try:
        stamp = (
            path.stat().st_mtime_ns,
            theme_path.stat().st_mtime_ns,
            appearance_path.stat().st_mtime_ns,
            i18n_path.stat().st_mtime_ns,
        )
    except OSError:
        return (f"<!DOCTYPE html><html><body style='font-family:sans-serif'>"
                f"<h3>Widget '{name}' not found</h3><p>Expected: {path}</p></body></html>")
    cached = _widget_cache.get(name)
    if cached and cached[0] == stamp:
        return cached[1]
    html = path.read_text(encoding="utf-8")
    asset_version = max(stamp[1:])
    root_selector = _WIDGET_BOUNDED_ROOTS.get(name)
    if root_selector:
        html = html.replace(
            "<html",
            f'<html data-widget-layout="bounded" data-widget-root="{root_selector}"',
            1,
        )
    html = html.replace(
        "<head>",
        f'<head><script src="/widget/_shared/i18n.js?v={asset_version}"></script>',
        1,
    )
    html = html.replace(
        "</head>",
        f'<link rel="stylesheet" href="/widget/_shared/theme.css?v={asset_version}">'
        f'<script src="/widget/_shared/appearance.js?v={asset_version}"></script></head>',
        1,
    )
    _widget_cache[name] = (stamp, html)
    return html


def _retired_widget_html(route: str) -> str:
    """Тёмная заглушка для выведенного из эксплуатации виджета.

    URL сохраняется живым: у владельца настроены OBS Browser Source на эти
    адреса, и пустой 404 в сцене читается как поломка сцены, а не как решение
    убрать виджет. Реестр причин — widget_inventory.RETIRED_WIDGETS.
    """
    title, reason, replacement = RETIRED_WIDGETS[route]
    labels = {
        "ru": {
            "retired.title": title,
            "retired.reason": reason,
            "retired.document_title": f"{title} — выведен из эксплуатации",
            "retired.replacement": "Замена:",
            "retired.remove": "Источник можно убрать из сцены OBS.",
        },
        "en": {
            "retired.replacement": "Replacement:",
            "retired.remove": "You can remove this source from your OBS scene.",
        },
        "ua": {
            "retired.replacement": "Заміна:",
            "retired.remove": "Джерело можна прибрати зі сцени OBS.",
        },
    }
    for locale, suffix in (("en", "retired"), ("ua", "виведено з експлуатації")):
        translated_title, translated_reason = RETIRED_WIDGET_TRANSLATIONS.get(locale, {}).get(route, ("", ""))
        if translated_title:
            labels[locale]["retired.title"] = translated_title
            labels[locale]["retired.document_title"] = f"{translated_title} — {suffix}"
        if translated_reason:
            labels[locale]["retired.reason"] = translated_reason
    translations = json.dumps(labels, ensure_ascii=False).replace("<", "\\u003c")
    extra = (
        '<p><span data-widget-i18n="retired.replacement">Замена:</span> '
        f"<code>{escape(replacement)}</code></p>" if replacement else ""
    )
    return (
        "<!DOCTYPE html><html lang='ru'><head><meta charset='utf-8'>"
        '<script src="/widget/_shared/i18n.js"></script>'
        f"<script>WidgetI18n.add({translations});</script>"
        '<title data-widget-i18n="retired.document_title">'
        f"{escape(title)} — выведен из эксплуатации</title><style>"
        ":root{color-scheme:dark}"
        "html,body{margin:0;height:100%;background:#0f0f1a;color:#e5e7eb;"
        "font:14px/1.5 system-ui,sans-serif;display:flex;align-items:center;"
        "justify-content:center}"
        ".box{max-width:22rem;padding:1.25rem;text-align:center;opacity:.85}"
        "h1{margin:0 0 .5rem;font-size:1rem}p{margin:.25rem 0;color:#9ca3af}"
        "code{color:#e5e7eb}"
        "</style></head><body><div class='box'>"
        f'<h1 data-widget-i18n="retired.title">{escape(title)}</h1>'
        f'<p data-widget-i18n="retired.reason">{escape(reason)}</p>{extra}'
        '<p data-widget-i18n="retired.remove">Источник можно убрать из сцены OBS.</p>'
        "</div></body></html>"
    )


# ====================================================================
# DB schema (вызывается из database.init_db через ensure_widgets_schema)
# ====================================================================


async def ensure_widgets_schema() -> None:
    """Создаёт таблицы виджетов + миграции. Идемпотентно."""
    db = await get_db()
    try:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS widget_counters_scoped (
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                key TEXT NOT NULL,
                label TEXT DEFAULT '',
                value INTEGER DEFAULT 0,
                animation TEXT DEFAULT 'minimal',
                color TEXT DEFAULT '',
                emoji TEXT DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (account_id, channel, key),
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS stream_goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                done INTEGER DEFAULT 0,
                sort_order INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS widget_goals_scoped (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                text TEXT NOT NULL,
                done INTEGER DEFAULT 0,
                percent INTEGER DEFAULT 0,
                sort_order INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_widget_goals_scope
                ON widget_goals_scoped(account_id, channel, sort_order, id);
            CREATE TABLE IF NOT EXISTS sub_goal (
                id INTEGER PRIMARY KEY,
                target INTEGER DEFAULT 50,
                current INTEGER DEFAULT 0,
                theme TEXT DEFAULT 'tree',
                title TEXT DEFAULT '',
                last_event_at TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS widget_sub_goal_scoped (
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                target INTEGER DEFAULT 50,
                current INTEGER DEFAULT 0,
                theme TEXT DEFAULT 'tree',
                title TEXT DEFAULT '',
                last_event_at TIMESTAMP,
                PRIMARY KEY (account_id, channel),
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS now_playing (
                id INTEGER PRIMARY KEY,
                kind TEXT DEFAULT 'music',
                text TEXT DEFAULT '',
                subtext TEXT DEFAULT '',
                icon_url TEXT DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS widget_now_playing_scoped (
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                kind TEXT DEFAULT 'music',
                text TEXT DEFAULT '',
                subtext TEXT DEFAULT '',
                icon_url TEXT DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (account_id, channel),
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS widget_lower_third_scoped (
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                name TEXT DEFAULT '',
                tagline TEXT DEFAULT '',
                social TEXT DEFAULT '',
                avatar_url TEXT DEFAULT '',
                theme TEXT DEFAULT 'minimal',
                visible INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (account_id, channel),
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS widget_mascot_scoped (
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                preset TEXT DEFAULT 'blob',
                custom_url TEXT DEFAULT '',
                idle_timeout_sec INTEGER DEFAULT 300,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (account_id, channel),
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS widget_recent_events_scoped (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                kind TEXT NOT NULL,
                username TEXT DEFAULT '',
                amount INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_widget_recent_events_scope
                ON widget_recent_events_scoped(account_id, channel, id DESC);
            CREATE TABLE IF NOT EXISTS widget_chat_highlight_scoped (
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                text TEXT DEFAULT '',
                author TEXT DEFAULT '',
                kind TEXT DEFAULT 'ai',
                theme TEXT DEFAULT 'glow',
                visible INTEGER DEFAULT 1,
                auto_mode INTEGER DEFAULT 1,
                display_sec INTEGER DEFAULT 15,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (account_id, channel),
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS widget_chat_roulette_scoped (
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                winner TEXT DEFAULT '',
                participants TEXT DEFAULT '[]',
                theme TEXT DEFAULT 'wheel',
                spin_duration_sec INTEGER DEFAULT 5,
                auto_interval_min INTEGER DEFAULT 0,
                visible INTEGER DEFAULT 1,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (account_id, channel),
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS widget_song_request_settings_scoped (
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                max_queue INTEGER DEFAULT 50,
                theme TEXT DEFAULT 'neon',
                visible INTEGER DEFAULT 1,
                show_count INTEGER DEFAULT 4,
                cooldown_sec INTEGER DEFAULT 30,
                max_per_user INTEGER DEFAULT 2,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (account_id, channel),
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS widget_song_request_queue_scoped (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                title TEXT NOT NULL,
                requested_by TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'queued',
                priority INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_widget_sr_queue_scope
                ON widget_song_request_queue_scoped(account_id, channel, status, priority, created_at);
            CREATE TABLE IF NOT EXISTS schedule_blocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_time TEXT NOT NULL,
                title TEXT NOT NULL,
                emoji TEXT DEFAULT '',
                sort_order INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS widget_titles (
                widget TEXT PRIMARY KEY,
                title TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS donations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                amount REAL NOT NULL,
                currency TEXT DEFAULT 'USD',
                message TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS top_donator_settings (
                id INTEGER PRIMARY KEY,
                theme TEXT DEFAULT 'neon',
                show_amount INTEGER DEFAULT 1,
                title_alltime TEXT DEFAULT 'Top Donator (All Time)',
                title_month TEXT DEFAULT 'Top Donator (Month)',
                title_day TEXT DEFAULT 'Top Donator (Day)',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS now_playing_settings (
                id INTEGER PRIMARY KEY,
                source TEXT DEFAULT 'manual',
                lastfm_user TEXT DEFAULT '',
                lastfm_api_key TEXT DEFAULT '',
                mpris_player TEXT DEFAULT '',
                poll_seconds INTEGER DEFAULT 15,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS widget_bindings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                source TEXT DEFAULT 'chat_command',
                match TEXT DEFAULT '',
                widget TEXT DEFAULT '',
                widget_key TEXT DEFAULT '',
                action TEXT DEFAULT 'increment',
                value TEXT DEFAULT '',
                role TEXT DEFAULT 'mod',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS donation_integration_settings (
                id INTEGER PRIMARY KEY,
                platform TEXT DEFAULT 'none',
                token TEXT DEFAULT '',
                enabled INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS donation_integrations (
                platform TEXT PRIMARY KEY,
                token TEXT DEFAULT '',
                enabled INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS donation_goal_sync (
                id INTEGER PRIMARY KEY,
                platform TEXT DEFAULT 'donatex',
                external_goal_id TEXT DEFAULT '',
                enabled INTEGER DEFAULT 0,
                last_amount REAL DEFAULT 0,
                synced INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS subathon_timer (
                id INTEGER PRIMARY KEY,
                end_at TIMESTAMP,
                running INTEGER DEFAULT 0,
                seconds_per_sub INTEGER DEFAULT 60,
                seconds_per_donation INTEGER DEFAULT 30,
                title TEXT DEFAULT 'SUBATHON'
            );
            CREATE TABLE IF NOT EXISTS subathon_timer_scoped (
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                end_at TIMESTAMP,
                running INTEGER DEFAULT 0,
                seconds_per_sub INTEGER DEFAULT 60,
                seconds_per_donation INTEGER DEFAULT 30,
                seconds_per_currency REAL DEFAULT 0,
                title TEXT DEFAULT 'SUBATHON',
                PRIMARY KEY (account_id, channel),
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS donation_integrations_scoped (
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                platform TEXT NOT NULL,
                token TEXT DEFAULT '',
                webhook_token TEXT DEFAULT '',
                enabled INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (account_id, channel, platform),
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS donation_ingress_receipts (
                account_id INTEGER NOT NULL DEFAULT 0,
                channel TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL,
                event_id TEXT NOT NULL,
                received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (account_id, channel, source, event_id)
            );
            CREATE TABLE IF NOT EXISTS donation_webhook_scopes (
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                token TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (account_id, channel),
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS donation_goal_sync_scoped (
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                platform TEXT DEFAULT 'donatex',
                external_goal_id TEXT DEFAULT '',
                enabled INTEGER DEFAULT 0,
                last_amount REAL DEFAULT 0,
                synced INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (account_id, channel),
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_donation_goal_sync_scoped_goal
                ON donation_goal_sync_scoped(external_goal_id)
                WHERE external_goal_id <> '';
            CREATE TABLE IF NOT EXISTS custom_poll (
                id INTEGER PRIMARY KEY,
                question TEXT DEFAULT '',
                choices TEXT DEFAULT '[]',
                votes TEXT DEFAULT '{}',
                open INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS soundboard_tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                filename TEXT NOT NULL UNIQUE,
                mime TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS emoji_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                day TEXT NOT NULL,
                count INTEGER DEFAULT 0,
                UNIQUE(username, day)
            );
        """)
        # Засеваем singleton-row (id=1) если их ещё нет.
        await db.execute(
            "INSERT OR IGNORE INTO sub_goal (id, target, current, theme, title) "
            "VALUES (1, 50, 0, 'tree', 'Цель: 50 сабов')"
        )
        await db.execute(
            "INSERT OR IGNORE INTO now_playing (id, kind, text) VALUES (1, 'music', '')"
        )
        await db.execute(
            "INSERT OR IGNORE INTO now_playing_settings (id, source) VALUES (1, 'manual')"
        )
        await db.execute(
            "INSERT OR IGNORE INTO donation_integration_settings (id, platform) "
            "VALUES (1, 'none')"
        )
        await db.execute(
            "INSERT OR IGNORE INTO donation_goal_sync (id, platform) VALUES (1, 'donatex')"
        )
        await db.execute(
            "INSERT OR IGNORE INTO subathon_timer (id, title) VALUES (1, 'SUBATHON')"
        )
        await _add_column_if_missing(db, "donations", "account_id", "INTEGER")
        await _add_column_if_missing(db, "donations", "channel", "TEXT")
        await _add_column_if_missing(db, "donation_integrations", "last_success_at", "TIMESTAMP")
        await _add_column_if_missing(
            db, "donation_integrations_scoped", "last_success_at", "TIMESTAMP",
        )
        legacy_bridge_rows = await db.execute(
            "SELECT account_id, channel, webhook_token "
            "FROM donation_integrations_scoped WHERE webhook_token <> '' ORDER BY rowid"
        )
        for row in await legacy_bridge_rows.fetchall():
            await db.execute(
                "INSERT OR IGNORE INTO donation_webhook_scopes "
                "(account_id, channel, token, enabled) VALUES (?, ?, ?, 1)",
                (row["account_id"], row["channel"], row["webhook_token"]),
            )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_donations_scope_created "
            "ON donations(account_id, channel, created_at)"
        )
        if is_encryption_enabled():
            for table in ("donation_integrations", "donation_integrations_scoped"):
                cursor = await db.execute(f"SELECT rowid, token FROM {table} WHERE token <> ''")
                for row in await cursor.fetchall():
                    encrypted = encrypt_token(str(row["token"] or ""))
                    if encrypted != row["token"]:
                        await db.execute(
                            f"UPDATE {table} SET token = ? WHERE rowid = ?",
                            (encrypted, row["rowid"]),
                        )
        # Решение владельца 31.08: тариф «секунды за единицу валюты» доната
        # (0 = использовать плоский seconds_per_donation).
        try:
            await db.execute(
                "ALTER TABLE subathon_timer ADD COLUMN seconds_per_currency REAL DEFAULT 0"
            )
        except Exception:
            pass  # колонка уже есть
        # Миграция: legacy singleton (donation_integration_settings) → per-platform.
        # Платформы из старой таблицы переносятся только если включены (enabled=1),
        # чтобы старое «none» не включало лишнего.
        try:
            cursor = await db.execute(
                "SELECT platform, token, enabled FROM donation_integration_settings "
                "WHERE enabled = 1 AND platform != 'none' LIMIT 1"
            )
            legacy = await cursor.fetchone()
            if legacy:
                await db.execute(
                    "INSERT OR REPLACE INTO donation_integrations "
                    "(platform, token, enabled) VALUES (?, ?, 1)",
                    (legacy["platform"], encrypt_token(str(legacy["token"] or ""))),
                )
                await db.commit()
        except Exception:
            pass
        await db.execute(
            "INSERT OR IGNORE INTO top_donator_settings "
            "(id, theme, show_amount, title_alltime, title_month, title_day) "
            "VALUES (1, 'neon', 1, 'Top Donator (All Time)', "
            "'Top Donator (Month)', 'Top Donator (Day)')"
        )
        # Дефолтные заголовки виджетов (юзер переопределит из панели).
        for w, t in (
            ("goals", "Цели на стрим"),
            ("now-playing", "Сейчас"),
            ("sub-goal", "Цель: 50 сабов"),
            ("schedule", "Расписание"),
            ("animated-bg", ""),
            ("top-donator-alltime", "Top Donator (All Time)"),
            ("top-donator-month", "Top Donator (Month)"),
            ("top-donator-day", "Top Donator (Day)"),
        ):
            await db.execute(
                "INSERT OR IGNORE INTO widget_titles (widget, title) VALUES (?, ?)",
                (w, t),
            )
        # Migration: add priority column to song_request_queue
        try:
            await db.execute(
                "ALTER TABLE song_request_queue ADD COLUMN priority INTEGER DEFAULT 0"
            )
        except Exception:
            pass  # column already exists

        # §11.5: cooldown и лимит очереди на юзера для song request
        try:
            await db.execute(
                "ALTER TABLE song_request_settings ADD COLUMN cooldown_sec INTEGER DEFAULT 30"
            )
        except Exception:
            pass
        try:
            await db.execute(
                "ALTER TABLE song_request_settings ADD COLUMN max_per_user INTEGER DEFAULT 2"
            )
        except Exception:
            pass

        # §11.1 WIDGETS_PLAN: цели в процентах вместо галочки.
        # done=1 в старых данных визуально эквивалентен percent=100 (см. goals_list_public).
        try:
            await db.execute(
                "ALTER TABLE stream_goals ADD COLUMN percent INTEGER DEFAULT 0"
            )
        except Exception:
            pass  # column already exists

        # Table for manually granted priority users
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sr_priority_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                granted_by TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Bot Intelligence: corrections table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bot_corrections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                channel TEXT DEFAULT '',
                username TEXT NOT NULL,
                original_context TEXT DEFAULT '',
                correction TEXT NOT NULL,
                permanent INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # §5 аудит 30.08: CREATE clip_moments убран — единственная схема
        # живёт в database.py (здесь была расхождение: nullable channel/text
        # timestamp vs NOT NULL/TIMESTAMP).

        # Countdown/Timer widget
        await db.execute("""
            CREATE TABLE IF NOT EXISTS countdown_timer (
                id INTEGER PRIMARY KEY,
                mode TEXT DEFAULT 'countdown',
                duration_sec INTEGER DEFAULT 300,
                remaining_sec INTEGER DEFAULT 300,
                state TEXT DEFAULT 'stopped',
                theme TEXT DEFAULT 'neon',
                title TEXT DEFAULT '',
                started_at TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS widget_countdown_scoped (
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                mode TEXT DEFAULT 'countdown',
                duration_sec INTEGER DEFAULT 300,
                remaining_sec INTEGER DEFAULT 300,
                state TEXT DEFAULT 'stopped',
                theme TEXT DEFAULT 'neon',
                title TEXT DEFAULT '',
                started_at TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (account_id, channel),
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            )
        """)
        await db.execute(
            "INSERT OR IGNORE INTO countdown_timer "
            "(id, mode, duration_sec, remaining_sec, state, theme, title) "
            "VALUES (1, 'countdown', 300, 300, 'stopped', 'neon', '')"
        )

        # Donation Challenges widget
        await db.execute("""
            CREATE TABLE IF NOT EXISTS donation_challenges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER,
                channel TEXT,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                target_amount REAL NOT NULL,
                current_amount REAL DEFAULT 0,
                currency TEXT DEFAULT 'USD',
                reward_text TEXT DEFAULT '',
                active INTEGER DEFAULT 1,
                completed INTEGER DEFAULT 0,
                theme TEXT DEFAULT 'neon',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            )
        """)
        # NULL scope keeps historical rows and scope-less OBS URLs isolated as legacy state.
        for column_sql in ("account_id INTEGER", "channel TEXT"):
            try:
                await db.execute(
                    f"ALTER TABLE donation_challenges ADD COLUMN {column_sql}"
                )
            except Exception:
                pass
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_donation_challenges_scope_active "
            "ON donation_challenges(account_id, channel, active, completed, created_at)"
        )

        # Latest Event Card widget settings
        await db.execute("""
            CREATE TABLE IF NOT EXISTS latest_event_card_settings (
                id INTEGER PRIMARY KEY,
                theme TEXT DEFAULT 'neon',
                filter_kind TEXT DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute(
            "INSERT OR IGNORE INTO latest_event_card_settings "
            "(id, theme, filter_kind) VALUES (1, 'neon', '')"
        )

        # Stream Reports (auto-highlights + post-stream reports)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS stream_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER,
                channel TEXT,
                report_type TEXT DEFAULT 'post_stream',
                data TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Indexes for frequently queried columns
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_recent_events_created "
            "ON recent_events(created_at DESC)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_donations_created "
            "ON donations(created_at)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_clip_moments_account_channel "
            "ON clip_moments(account_id, channel, created_at)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_chat_log_channel_ts "
            "ON chat_log(channel, timestamp)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_stream_goals_sort "
            "ON stream_goals(sort_order)"
        )

        # v13 §6.1 WIDGETS_PLAN: chat-reader налаштування (per-account).
        # Один рядок на account_id, lazy create.
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chat_reader_settings (
                account_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 0,
                read_all INTEGER DEFAULT 0,
                command TEXT DEFAULT '!read',
                min_role TEXT DEFAULT 'any',
                tts_provider TEXT DEFAULT '',
                max_chars INTEGER DEFAULT 200,
                cooldown_sec INTEGER DEFAULT 5,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            )
        """)

        # 6.5: unscoped rows cannot be assigned safely, so rebuild without copying them.
        binding_columns = {
            row[1] for row in await (await db.execute(
                "PRAGMA table_info(widget_bindings)"
            )).fetchall()
        }
        if not {"account_id", "channel"} <= binding_columns:
            await db.execute("DROP TABLE IF EXISTS widget_bindings_scoped")
            await db.execute("""
                CREATE TABLE widget_bindings_scoped (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER NOT NULL,
                    channel TEXT NOT NULL,
                    enabled INTEGER DEFAULT 1,
                    source TEXT DEFAULT 'chat_command',
                    match TEXT DEFAULT '',
                    widget TEXT DEFAULT '',
                    widget_key TEXT DEFAULT '',
                    action TEXT DEFAULT 'increment',
                    value TEXT DEFAULT '',
                    role TEXT DEFAULT 'mod',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
                )
            """)
            await db.execute("DROP TABLE widget_bindings")
            await db.execute(
                "ALTER TABLE widget_bindings_scoped RENAME TO widget_bindings"
            )
        await db.execute(
            "DELETE FROM widget_bindings WHERE account_id IS NULL OR account_id <= 0 "
            "OR trim(channel) = ''"
        )
        await db.execute(
            "UPDATE widget_bindings SET channel = lower(ltrim(trim(channel), '#'))"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_widget_bindings_scope_source "
            "ON widget_bindings(account_id, channel, enabled, source)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_widget_bindings_scope_event "
            "ON widget_bindings(account_id, channel, source, match)"
        )

        # Preserve scoped records while moving UI/executor to semantic names.
        await db.execute(
            "UPDATE widget_bindings SET action = 'pause' "
            "WHERE widget = 'countdown' AND action = 'stop'"
        )
        await db.execute(
            "UPDATE widget_bindings SET action = 'show' "
            "WHERE widget = 'lower_third' AND action = 'set'"
        )
        await db.execute(
            "UPDATE widget_bindings SET enabled = 0 "
            "WHERE widget = 'moderation' AND (source <> 'hotkey' OR role <> 'streamer')"
        )
        await db.execute(
            "UPDATE widget_bindings SET enabled = 0 WHERE id IN ("
            "SELECT duplicate.id FROM widget_bindings AS duplicate "
            "WHERE duplicate.enabled = 1 AND duplicate.source = 'eventsub' "
            "AND duplicate.match = 'channel.subscribe' "
            "AND duplicate.widget = 'sub_goal' "
            "AND duplicate.action = 'increment' "
            "AND duplicate.id <> (SELECT MIN(first.id) FROM widget_bindings AS first "
            "WHERE first.enabled = 1 AND first.source = duplicate.source AND first.match = duplicate.match "
            "AND first.widget = duplicate.widget AND first.action = duplicate.action "
            "AND first.account_id = duplicate.account_id AND first.channel = duplicate.channel))"
        )
        await db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_widget_bindings_one_sub_goal_subscribe "
            "ON widget_bindings(account_id, channel) "
            "WHERE enabled = 1 AND source = 'eventsub' "
            "AND match = 'channel.subscribe' AND widget = 'sub_goal' "
            "AND action = 'increment'"
        )

        await db.commit()
    finally:
        await db.close()


# ====================================================================
# In-memory TTL cache for public widget endpoints
# ====================================================================
_cache: dict[str, tuple[Any, float]] = {}
_CACHE_TTL_DEFAULT = 5.0  # seconds
_CACHE_TTL_SLOW = 10.0  # for top-donator endpoints


def _cache_get(key: str) -> Any | None:
    entry = _cache.get(key)
    if entry and entry[1] > time.time():
        return entry[0]
    return None


def _cache_set(key: str, value: Any, ttl: float = _CACHE_TTL_DEFAULT) -> None:
    if len(_cache) > 100:
        now = time.time()
        expired = [k for k, (_, exp) in _cache.items() if exp <= now]
        for k in expired:
            del _cache[k]
    _cache[key] = (value, time.time() + ttl)


def _cache_invalidate(*keys: str) -> None:
    for k in keys:
        _cache.pop(k, None)


# ====================================================================
# Routers
# ====================================================================

# Управляющие (auth) — крепим к существующему `router` через include_router.
admin_router = APIRouter(dependencies=[Depends(auth_dependency)])
# Публичные (без auth) — крепим к `ws_router`.
public_router = APIRouter()


# ====================================================================
# Widget #2: Stream goals
# ====================================================================


@admin_router.get("/api/widgets/goals")
async def goals_list_admin(
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    db = await get_db()
    try:
        if scope is None:
            cursor = await db.execute(
                "SELECT id, text, done, percent, sort_order, created_at FROM stream_goals "
                "ORDER BY sort_order ASC, id ASC"
            )
        else:
            cursor = await db.execute(
                "SELECT id, text, done, percent, sort_order, created_at "
                "FROM widget_goals_scoped WHERE account_id = ? AND channel = ? "
                "ORDER BY sort_order ASC, id ASC", scope,
            )
        return {"items": [dict(r) for r in await cursor.fetchall()]}
    finally:
        await db.close()


@admin_router.post("/api/widgets/goals")
async def goals_add(
    payload: dict, account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    text = (payload.get("text") or "").strip()
    if not text:
        return {"error": "text_required"}
    db = await get_db()
    try:
        table = "stream_goals" if scope is None else "widget_goals_scoped"
        if scope is None:
            cursor = await db.execute(
                f"SELECT COALESCE(MAX(sort_order), 0) + 1 AS next FROM {table}"
            )
        else:
            cursor = await db.execute(
                f"SELECT COALESCE(MAX(sort_order), 0) + 1 AS next FROM {table} "
                "WHERE account_id = ? AND channel = ?", scope,
            )
        row = await cursor.fetchone()
        order = int(row["next"]) if row else 1
        percent = 0
        if "percent" in payload:
            try:
                percent = max(0, min(100, int(payload["percent"])))
            except (TypeError, ValueError):
                percent = 0
        if scope is None:
            cursor = await db.execute(
                "INSERT INTO stream_goals (text, sort_order, percent, done) VALUES (?, ?, ?, ?)",
                (text, order, percent, 1 if percent >= 100 else 0),
            )
        else:
            cursor = await db.execute(
                "INSERT INTO widget_goals_scoped "
                "(account_id, channel, text, sort_order, percent, done) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (*scope, text, order, percent, 1 if percent >= 100 else 0),
            )
        await db.commit()
        _cache_invalidate(_widget_cache_key("goals", scope))
        return {"id": cursor.lastrowid or 0}
    finally:
        await db.close()


@admin_router.put("/api/widgets/goals/{gid}")
async def goals_update(
    gid: int, payload: dict, account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    table = "stream_goals" if scope is None else "widget_goals_scoped"
    scope_sql = "" if scope is None else " AND account_id = ? AND channel = ?"
    scope_params = () if scope is None else scope
    db = await get_db()
    try:
        existing = await (await db.execute(
            f"SELECT 1 FROM {table} WHERE id = ?{scope_sql}",
            (gid, *scope_params),
        )).fetchone()
        if not existing:
            return {"error": "not_found"}
        if "text" in payload:
            await db.execute(
                f"UPDATE {table} SET text = ? WHERE id = ?{scope_sql}",
                (str(payload["text"]).strip(), gid, *scope_params),
            )
        if "done" in payload:
            # §11.1: галочка = 100%. done=1 поднимает percent до 100,
            # done=0 сбрасывает процент ниже порога «выполнено».
            done_flag = 1 if payload["done"] else 0
            if done_flag:
                await db.execute(
                    f"UPDATE {table} SET done = 1, percent = 100 WHERE id = ?{scope_sql}",
                    (gid, *scope_params),
                )
            else:
                await db.execute(
                    f"UPDATE {table} SET done = 0, "
                    f"percent = MIN(percent, 99) WHERE id = ?{scope_sql}",
                    (gid, *scope_params),
                )
        if "percent" in payload:
            # §11.1: percent 0-100; 100% = «выполнено» (done синхронизируется).
            try:
                percent = max(0, min(100, int(payload["percent"])))
                await db.execute(
                    f"UPDATE {table} SET percent = ?, done = ? WHERE id = ?{scope_sql}",
                    (percent, 1 if percent >= 100 else 0, gid, *scope_params),
                )
            except (TypeError, ValueError):
                pass
        if "sort_order" in payload:
            try:
                await db.execute(
                    f"UPDATE {table} SET sort_order = ? WHERE id = ?{scope_sql}",
                    (int(payload["sort_order"]), gid, *scope_params),
                )
            except (TypeError, ValueError):
                pass
        await db.commit()
        _cache_invalidate(_widget_cache_key("goals", scope))
        return {"ok": True}
    finally:
        await db.close()


@admin_router.delete("/api/widgets/goals/{gid}")
async def goals_delete(
    gid: int, account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    db = await get_db()
    try:
        if scope is None:
            cursor = await db.execute("DELETE FROM stream_goals WHERE id = ?", (gid,))
        else:
            cursor = await db.execute(
                "DELETE FROM widget_goals_scoped "
                "WHERE id = ? AND account_id = ? AND channel = ?", (gid, *scope),
            )
        await db.commit()
        if not cursor.rowcount:
            return {"error": "not_found"}
        _cache_invalidate(_widget_cache_key("goals", scope))
        return {"ok": True}
    finally:
        await db.close()


@admin_router.post("/api/widgets/goals/clear-done")
async def goals_clear_done(
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    db = await get_db()
    try:
        if scope is None:
            cursor = await db.execute("DELETE FROM stream_goals WHERE done = 1")
        else:
            cursor = await db.execute(
                "DELETE FROM widget_goals_scoped "
                "WHERE done = 1 AND account_id = ? AND channel = ?", scope,
            )
        await db.commit()
        _cache_invalidate(_widget_cache_key("goals", scope))
        return {"ok": True, "deleted": cursor.rowcount or 0}
    finally:
        await db.close()


# Публичный read для виджета.
@public_router.get("/api/widgets/public/goals")
async def goals_list_public(
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    cache_key = _widget_cache_key("goals", scope)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    db = await get_db()
    try:
        if scope is None:
            cursor = await db.execute(
                "SELECT id, text, done, percent FROM stream_goals "
                "ORDER BY sort_order ASC, id ASC"
            )
        else:
            cursor = await db.execute(
                "SELECT id, text, done, percent FROM widget_goals_scoped "
                "WHERE account_id = ? AND channel = ? ORDER BY sort_order ASC, id ASC", scope,
            )
        items = []
        for r in await cursor.fetchall():
            item = dict(r)
            # §11.1 совместимость: старая галочка done=1 = 100%.
            if item.get("percent") is None:
                item["percent"] = 100 if item.get("done") else 0
            items.append(item)
        result = {"items": items}
    finally:
        await db.close()
    _cache_set(cache_key, result)
    return result


# §11.1: шаг цели (+/- percent) — для клик-кнопок поверх OBS-виджета (?admin=1)
# и для биндингов (§11.3).
@admin_router.post("/api/widgets/goals/{gid}/step")
async def goals_step(
    gid: int, payload: dict | None = None,
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    table = "stream_goals" if scope is None else "widget_goals_scoped"
    scope_sql = "" if scope is None else " AND account_id = ? AND channel = ?"
    scope_params = () if scope is None else scope
    delta = 1
    if payload and "delta" in payload:
        try:
            delta = int(payload["delta"])
        except (TypeError, ValueError):
            delta = 1
    db = await get_db()
    try:
        await db.execute(
            f"UPDATE {table} SET percent = MAX(0, MIN(100, percent + ?)), "
            "done = CASE WHEN MAX(0, MIN(100, percent + ?)) >= 100 THEN 1 ELSE done END "
            f"WHERE id = ?{scope_sql}",
            (delta, delta, gid, *scope_params),
        )
        await db.commit()
        _cache_invalidate(_widget_cache_key("goals", scope))
        cursor = await db.execute(
            f"SELECT id, text, done, percent FROM {table} WHERE id = ?{scope_sql}",
            (gid, *scope_params),
        )
        row = await cursor.fetchone()
        return dict(row) if row else {"error": "not_found"}
    finally:
        await db.close()


# ====================================================================
# Widget #4: Sub goal
# ====================================================================


async def _get_sub_goal_row(scope: tuple[int, str] | None = None) -> dict:
    db = await get_db()
    try:
        if scope is None:
            cursor = await db.execute(
                "SELECT id, target, current, theme, title, last_event_at "
                "FROM sub_goal WHERE id = 1"
            )
        else:
            cursor = await db.execute(
                "SELECT 1 AS id, target, current, theme, title, last_event_at "
                "FROM widget_sub_goal_scoped WHERE account_id = ? AND channel = ?", scope,
            )
        row = await cursor.fetchone()
        return dict(row) if row else {
            "id": 1, "target": 50, "current": 0, "theme": "tree",
            "title": "", "last_event_at": None,
        }
    finally:
        await db.close()


@admin_router.get("/api/widgets/sub-goal")
async def sub_goal_get(
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    return await _get_sub_goal_row(await _verified_widget_state_scope(account_id, channel))


@admin_router.put("/api/widgets/sub-goal")
async def sub_goal_update(
    payload: dict, account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    db = await get_db()
    try:
        fields = []
        values: list[Any] = []
        for k in ("target", "current"):
            if k in payload:
                try:
                    fields.append(f"{k} = ?")
                    values.append(max(0, int(payload[k])))
                except (TypeError, ValueError):
                    pass
        for k in ("theme", "title"):
            if k in payload:
                fields.append(f"{k} = ?")
                values.append(str(payload[k] or "").strip())
        if not fields:
            return {"ok": False, "error": "nothing_to_update"}
        if scope is None:
            values.append(1)
            await db.execute(
                f"UPDATE sub_goal SET {', '.join(fields)} WHERE id = ?", tuple(values),
            )
        else:
            await db.execute(
                "INSERT OR IGNORE INTO widget_sub_goal_scoped (account_id, channel) VALUES (?, ?)",
                scope,
            )
            values.extend(scope)
            await db.execute(
                f"UPDATE widget_sub_goal_scoped SET {', '.join(fields)} "
                "WHERE account_id = ? AND channel = ?", tuple(values),
            )
        await db.commit()
        _cache_invalidate(_widget_cache_key("sub-goal", scope))
    finally:
        await db.close()
    return {"ok": True, **(await _get_sub_goal_row(scope))}


@admin_router.post("/api/widgets/sub-goal/increment")
async def sub_goal_increment(
    payload: dict | None = None,
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    """Ручной инкремент (+1 по умолчанию или payload['delta'])."""
    delta = 1
    if payload and "delta" in payload:
        try:
            delta = int(payload["delta"])
        except (TypeError, ValueError):
            delta = 1
    scope = await _verified_widget_state_scope(account_id, channel)
    db = await get_db()
    try:
        if scope is None:
            await db.execute(
                "UPDATE sub_goal SET current = MAX(0, current + ?), "
                "last_event_at = CURRENT_TIMESTAMP WHERE id = 1", (delta,),
            )
        else:
            await db.execute(
                "INSERT OR IGNORE INTO widget_sub_goal_scoped (account_id, channel) VALUES (?, ?)",
                scope,
            )
            await db.execute(
                "UPDATE widget_sub_goal_scoped SET current = MAX(0, current + ?), "
                "last_event_at = CURRENT_TIMESTAMP WHERE account_id = ? AND channel = ?",
                (delta, *scope),
            )
        await db.commit()
        _cache_invalidate(_widget_cache_key("sub-goal", scope))
    finally:
        await db.close()
    return {"ok": True, **(await _get_sub_goal_row(scope))}


@admin_router.post("/api/widgets/sub-goal/reset")
async def sub_goal_reset(
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    db = await get_db()
    try:
        if scope is None:
            await db.execute("UPDATE sub_goal SET current = 0 WHERE id = 1")
        else:
            await db.execute(
                "UPDATE widget_sub_goal_scoped SET current = 0 "
                "WHERE account_id = ? AND channel = ?", scope,
            )
        await db.commit()
        _cache_invalidate(_widget_cache_key("sub-goal", scope))
    finally:
        await db.close()
    return {"ok": True, **(await _get_sub_goal_row(scope))}


@public_router.get("/api/widgets/public/sub-goal")
async def sub_goal_public(
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    cache_key = _widget_cache_key("sub-goal", scope)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    result = await _get_sub_goal_row(scope)
    _cache_set(cache_key, result)
    return result


# Хук для EventSub: в server.py on_eventsub_event вызывает этот метод
# когда event_type == 'channel.subscribe'. Делает auto-increment.
async def on_subscribe_event(
    *, increment_sub_goal: bool = True,
    account_id: int | None = None, channel: str | None = None,
) -> None:
    scope = await _verified_widget_state_scope(account_id, channel)
    db = await get_db()
    try:
        if increment_sub_goal:
            if scope is None:
                await db.execute(
                    "UPDATE sub_goal SET current = current + 1, "
                    "last_event_at = CURRENT_TIMESTAMP WHERE id = 1"
                )
            else:
                await db.execute(
                    "INSERT OR IGNORE INTO widget_sub_goal_scoped "
                    "(account_id, channel) VALUES (?, ?)", scope,
                )
                await db.execute(
                    "UPDATE widget_sub_goal_scoped SET current = current + 1, "
                    "last_event_at = CURRENT_TIMESTAMP WHERE account_id = ? AND channel = ?", scope,
                )
            await db.commit()
            _cache_invalidate(_widget_cache_key("sub-goal", scope))
    finally:
        await db.close()
    await _subathon_extend_for_sub(scope)


@public_router.post("/api/widgets/public/sub-goal/increment")
async def sub_goal_public_increment(
    request: Request,
    payload: dict | None = None,
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    """Ручной локальный инкремент для OBS Browser Source и hotkeys."""
    from app.security import require_loopback_client
    require_loopback_client(request)
    delta = 1
    if payload and "delta" in payload:
        try:
            delta = int(payload["delta"])
        except (TypeError, ValueError):
            delta = 1
    scope = await _verified_widget_state_scope(account_id, channel)
    db = await get_db()
    try:
        if scope is None:
            await db.execute(
                "UPDATE sub_goal SET current = MAX(0, current + ?), "
                "last_event_at = CURRENT_TIMESTAMP WHERE id = 1", (delta,),
            )
        else:
            await db.execute(
                "INSERT OR IGNORE INTO widget_sub_goal_scoped (account_id, channel) VALUES (?, ?)",
                scope,
            )
            await db.execute(
                "UPDATE widget_sub_goal_scoped SET current = MAX(0, current + ?), "
                "last_event_at = CURRENT_TIMESTAMP WHERE account_id = ? AND channel = ?",
                (delta, *scope),
            )
        await db.commit()
        _cache_invalidate(_widget_cache_key("sub-goal", scope))
    finally:
        await db.close()
    return {"ok": True}


# §9.3: subathon продлевается за каждый саб (EventSub-хук)
async def _subathon_extend_for_sub(scope: tuple[int, str] | None = None) -> None:
    try:
        db = await get_db()
        try:
            if scope is None:
                c3 = await db.execute(
                    "SELECT seconds_per_sub FROM subathon_timer WHERE id = 1"
                )
            else:
                await db.execute(
                    "INSERT OR IGNORE INTO subathon_timer_scoped "
                    "(account_id, channel) VALUES (?, ?)", scope,
                )
                c3 = await db.execute(
                    "SELECT seconds_per_sub FROM subathon_timer_scoped "
                    "WHERE account_id = ? AND channel = ?", scope,
                )
            r3 = await c3.fetchone()
        finally:
            await db.close()
        if r3 and r3["seconds_per_sub"]:
            await subathon_extend(int(r3["seconds_per_sub"]), scope)
    except Exception as exc:
        logger.debug("subathon extend (sub) failed: %s", exc)


# ====================================================================
# Widget #3: Now Playing (manual)
# ====================================================================
#
# Singleton-row (id=1) в таблице now_playing. Стример сам пишет
# в поле text «слушаю Imagine Dragons — Believer» / «смотрю обзор PS5».
# Если в icon_url попала YouTube ссылка — бэкенд через oembed автоматом
# тянет thumbnail и название видео (без OAuth и API ключей).


_YT_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)([A-Za-z0-9_-]{11})"
)


def _yt_video_id(text: str) -> str | None:
    """Из любой YouTube ссылки/строки выдёргивает 11-символьный videoId."""
    if not text:
        return None
    m = _YT_RE.search(text)
    if m:
        return m.group(1)
    # Может быть просто id уже (11 символов).
    if len(text) == 11 and re.fullmatch(r"[A-Za-z0-9_-]{11}", text):
        return text
    return None


async def _yt_oembed(url: str) -> dict | None:
    """oembed YouTube — возвращает {title, author_name, thumbnail_url}.
    Не требует API-ключа. Если не получилось — возвращает None."""
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                "https://www.youtube.com/oembed",
                params={"url": url, "format": "json"},
            )
            if resp.status_code != 200:
                return None
            return resp.json()
    except Exception as exc:
        logger.debug("[now-playing] oembed failed: %s", exc)
        return None


async def _get_now_playing_row(scope: tuple[int, str] | None = None) -> dict:
    db = await get_db()
    try:
        if scope is None:
            cursor = await db.execute(
                "SELECT id, kind, text, subtext, icon_url, updated_at "
                "FROM now_playing WHERE id = 1"
            )
        else:
            cursor = await db.execute(
                "SELECT 1 AS id, kind, text, subtext, icon_url, updated_at "
                "FROM widget_now_playing_scoped WHERE account_id = ? AND channel = ?", scope,
            )
        row = await cursor.fetchone()
        return dict(row) if row else {
            "id": 1, "kind": "music", "text": "", "subtext": "",
            "icon_url": "", "updated_at": "",
        }
    finally:
        await db.close()


@admin_router.get("/api/widgets/now-playing")
async def now_playing_get(
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    return await _get_now_playing_row(await _verified_widget_state_scope(account_id, channel))


@admin_router.put("/api/widgets/now-playing")
async def now_playing_put(
    payload: dict, account_id: int | None = None, channel: str | None = None,
) -> dict:
    """Обновляет «Что сейчас». Если в icon_url передан YouTube URL —
    автоматом резолвит thumbnail и подставляет title/author в text/subtext
    (если пользователь оставил их пустыми)."""
    return await apply_now_playing(payload, account_id=account_id, channel=channel)


async def apply_now_playing(
    payload: dict, account_id: int | None = None, channel: str | None = None,
) -> dict:
    """Единая точка записи now-playing: панель (PUT), автозаполнение §11.2
    (Last.fm/MPRIS) и чат-команда !np."""
    text = (payload.get("text") or "").strip()
    subtext = (payload.get("subtext") or "").strip()
    icon_url = (payload.get("icon_url") or "").strip()
    kind = (payload.get("kind") or "music").strip()
    if kind not in ("music", "video", "game", "movie", "podcast", "custom"):
        kind = "custom"

    # YouTube auto-resolve: если icon_url — YT ссылка, превратим её в thumbnail.
    yt_id = _yt_video_id(icon_url)
    if yt_id:
        oembed = await _yt_oembed(f"https://www.youtube.com/watch?v={yt_id}")
        thumb = f"https://i.ytimg.com/vi/{yt_id}/mqdefault.jpg"
        icon_url = thumb
        if oembed:
            if not text:
                text = oembed.get("title", "") or ""
            if not subtext:
                subtext = oembed.get("author_name", "") or ""

    scope = await _verified_widget_state_scope(account_id, channel)
    db = await get_db()
    try:
        if scope is None:
            await db.execute(
                "UPDATE now_playing SET kind = ?, text = ?, subtext = ?, "
                "icon_url = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
                (kind, text, subtext, icon_url),
            )
        else:
            await db.execute(
                "INSERT OR IGNORE INTO widget_now_playing_scoped "
                "(account_id, channel) VALUES (?, ?)", scope,
            )
            await db.execute(
                "UPDATE widget_now_playing_scoped SET kind = ?, text = ?, subtext = ?, "
                "icon_url = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE account_id = ? AND channel = ?",
                (kind, text, subtext, icon_url, *scope),
            )
        await db.commit()
        _cache_invalidate(_widget_cache_key("now-playing", scope))
    finally:
        await db.close()
    return {"ok": True, **(await _get_now_playing_row(scope))}


@admin_router.post("/api/widgets/now-playing/clear")
async def now_playing_clear(
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    db = await get_db()
    try:
        if scope is None:
            await db.execute(
                "UPDATE now_playing SET text = '', subtext = '', icon_url = '', "
                "updated_at = CURRENT_TIMESTAMP WHERE id = 1"
            )
        else:
            await db.execute(
                "UPDATE widget_now_playing_scoped SET text = '', subtext = '', icon_url = '', "
                "updated_at = CURRENT_TIMESTAMP WHERE account_id = ? AND channel = ?", scope,
            )
        await db.commit()
        _cache_invalidate(_widget_cache_key("now-playing", scope))
    finally:
        await db.close()
    return {"ok": True, **(await _get_now_playing_row(scope))}


# ── §11.2: источник автозаполнения now-playing ──────────────────


async def _get_np_source_settings() -> dict:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT source, lastfm_user, lastfm_api_key, mpris_player, "
            "poll_seconds FROM now_playing_settings WHERE id = 1"
        )
        row = await cursor.fetchone()
        if row:
            return dict(row)
        return {
            "source": "manual", "lastfm_user": "", "lastfm_api_key": "",
            "mpris_player": "", "poll_seconds": 15,
        }
    finally:
        await db.close()


def _serialize_np_source_settings(settings: dict) -> dict:
    return {
        "source": settings.get("source") or "manual",
        "lastfm_user": settings.get("lastfm_user") or "",
        "mpris_player": settings.get("mpris_player") or "",
        "poll_seconds": settings.get("poll_seconds") or 15,
        "has_lastfm_api_key": bool(settings.get("lastfm_api_key")),
    }


@admin_router.get("/api/widgets/now-playing/source")
async def np_source_get() -> dict:
    return _serialize_np_source_settings(await _get_np_source_settings())


@admin_router.put("/api/widgets/now-playing/source")
async def np_source_put(payload: dict) -> dict:
    db = await get_db()
    try:
        source = str(payload.get("source") or "manual").strip().lower()
        if source not in ("manual", "lastfm", "mpris"):
            source = "manual"
        fields = ["source = ?"]
        values: list[Any] = [source]
        for k in ("lastfm_user", "mpris_player"):
            if k in payload:
                fields.append(f"{k} = ?")
                values.append(str(payload[k] or "").strip())
        lastfm_api_key = str(payload.get("lastfm_api_key") or "").strip()
        if lastfm_api_key:
            fields.append("lastfm_api_key = ?")
            values.append(lastfm_api_key)
        if "poll_seconds" in payload:
            try:
                fields.append("poll_seconds = ?")
                values.append(max(5, min(300, int(payload["poll_seconds"]))))
            except (TypeError, ValueError):
                pass
        values.append(1)
        await db.execute(
            f"UPDATE now_playing_settings SET {', '.join(fields)} WHERE id = ?",
            tuple(values),
        )
        await db.commit()
    finally:
        await db.close()
    return {"ok": True, **_serialize_np_source_settings(await _get_np_source_settings())}


async def handle_now_playing_command(
    text: str, author: str, account_id: int, channel: str, role: str = "viewer",
) -> dict:
    """Чат-команда ``!np <название|youtube-ссылка>`` / ``!np clear`` (§11.2).

    Права: стример или модератор. Вызывается из chat_analyzer.on_message
    (lazy import — циклической зависимости нет).
    """
    if role not in ("broadcaster", "mod"):
        return {"ok": False, "error": "forbidden"}
    arg = text.strip()[3:].strip()  # после '!np'
    if not arg:
        return {"ok": False, "error": "usage"}
    if arg.lower() in ("clear", "очистить"):
        await now_playing_clear(account_id=account_id, channel=channel)
        return {"ok": True, "action": "cleared"}
    result = await apply_now_playing(
        {"text": arg, "icon_url": arg, "kind": "music"},
        account_id=account_id,
        channel=channel,
    )
    logger.info("[now-playing] !np от %s: %s", author, result.get("text", arg))
    return {"ok": True, "action": "set", **result}


@public_router.get("/api/widgets/public/now-playing")
async def now_playing_public(
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    cache_key = _widget_cache_key("now-playing", scope)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    row = await _get_now_playing_row(scope)
    result = {
        "playing": bool((row.get("text") or "").strip()),
        "kind": row.get("kind") or "custom",
        "text": row.get("text") or "",
        "subtext": row.get("subtext") or "",
        "icon_url": row.get("icon_url") or "",
    }
    _cache_set(cache_key, result)
    return result


# ====================================================================
# Widget #5: Schedule (Сейчас / Скоро)
# ====================================================================


@admin_router.get("/api/widgets/schedule")
async def schedule_list() -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, start_time, title, emoji, sort_order "
            "FROM schedule_blocks ORDER BY start_time, sort_order, id"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


@admin_router.post("/api/widgets/schedule")
async def schedule_add(payload: dict) -> dict:
    start_time = (payload.get("start_time") or "").strip()
    title = (payload.get("title") or "").strip()
    emoji = (payload.get("emoji") or "").strip()
    if not start_time or not title:
        return {"error": "start_time and title required"}
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO schedule_blocks (start_time, title, emoji) VALUES (?, ?, ?)",
            (start_time, title, emoji),
        )
        await db.commit()
        _cache_invalidate("public:schedule")
        return {"ok": True, "id": cursor.lastrowid}
    finally:
        await db.close()


@admin_router.put("/api/widgets/schedule/{block_id}")
async def schedule_update(block_id: int, payload: dict) -> dict:
    fields: list[str] = []
    values: list[Any] = []
    for k in ("start_time", "title", "emoji"):
        if k in payload:
            fields.append(f"{k} = ?")
            values.append(str(payload[k] or "").strip())
    if "sort_order" in payload:
        try:
            fields.append("sort_order = ?")
            values.append(int(payload["sort_order"]))
        except (TypeError, ValueError):
            pass
    if not fields:
        return {"error": "nothing_to_update"}
    values.append(block_id)
    db = await get_db()
    try:
        await db.execute(
            f"UPDATE schedule_blocks SET {', '.join(fields)} WHERE id = ?",
            tuple(values),
        )
        await db.commit()
        _cache_invalidate("public:schedule")
    finally:
        await db.close()
    return {"ok": True}


@admin_router.delete("/api/widgets/schedule/{block_id}")
async def schedule_delete(block_id: int) -> dict:
    db = await get_db()
    try:
        await db.execute("DELETE FROM schedule_blocks WHERE id = ?", (block_id,))
        await db.commit()
        _cache_invalidate("public:schedule")
    finally:
        await db.close()
    return {"ok": True}


@public_router.get("/api/widgets/public/schedule")
async def schedule_public() -> list[dict]:
    cached = _cache_get("public:schedule")
    if cached is not None:
        return cached
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT start_time, title, emoji FROM schedule_blocks "
            "ORDER BY start_time, sort_order, id"
        )
        rows = await cursor.fetchall()
        result = [dict(r) for r in rows]
    finally:
        await db.close()
    _cache_set("public:schedule", result)
    return result


# ====================================================================
# Editable widget titles (общая таблица widget_titles)
# ====================================================================


VALID_WIDGETS = (
    "animated-bg", "goals", "now-playing", "sub-goal", "schedule",
    # v10.4.7
    "counter-death", "counter-streak",
    "uptime", "follower-ticker", "lower-third", "mascot",
    # v10.4.8
    "anime-runner",
    # v10.5
    "chat-highlight",
    "chat-roulette",
    "combo-counter",
    "song-request",
    # v10.6
    "top-donator-alltime",
    "top-donator-month",
    "top-donator-day",
    # v10.7
    "countdown",
    "donation-challenge",
    "latest-event-card",
)


async def _get_widget_title(widget: str) -> str:
    if widget not in VALID_WIDGETS:
        return ""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT title FROM widget_titles WHERE widget = ?", (widget,)
        )
        row = await cursor.fetchone()
        return (row["title"] if row else "") or ""
    finally:
        await db.close()


@admin_router.get("/api/widgets/titles")
async def widget_titles_get() -> dict:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT widget, title FROM widget_titles"
        )
        rows = await cursor.fetchall()
        return {r["widget"]: r["title"] for r in rows}
    finally:
        await db.close()


@admin_router.put("/api/widgets/titles/{widget}")
async def widget_title_put(widget: str, payload: dict) -> dict:
    if widget not in VALID_WIDGETS:
        return {"error": "unknown_widget"}
    title = str(payload.get("title", "") or "")[:200]
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO widget_titles (widget, title) VALUES (?, ?) "
            "ON CONFLICT(widget) DO UPDATE SET title = excluded.title",
            (widget, title),
        )
        await db.commit()
    finally:
        await db.close()
    return {"ok": True, "widget": widget, "title": title}


# ====================================================================
# v10.4.7: Counters (death / streak / generic)
# ====================================================================


VALID_ANIMATIONS = ("minimal", "skull", "blood", "fire", "retro", "shake")


def _widget_state_scope(
    account_id: int | None, channel: str | None,
) -> tuple[int, str] | None:
    if account_id is None and channel is None:
        return None
    normalized = str(channel or "").strip().lower().lstrip("#")
    if not account_id or int(account_id) <= 0 or not normalized:
        raise HTTPException(status_code=400, detail="widget_scope_required")
    return int(account_id), normalized


async def _verified_widget_state_scope(
    account_id: int | None, channel: str | None,
) -> tuple[int, str] | None:
    scope = _widget_state_scope(account_id, channel)
    if scope is None:
        return None
    from app.widget_channel_scope import resolve_channel
    identity = await resolve_channel(scope[1])
    if identity is None or not identity.enabled:
        raise HTTPException(status_code=400, detail="widget_scope_not_found")
    db = await get_db()
    try:
        row = await (await db.execute(
            "SELECT channel_name FROM channels WHERE account_id = ? AND enabled = 1 "
            "AND (lower(ltrim(trim(channel_name), '#')) = ? OR twitch_channel_id = ?) "
            "ORDER BY id LIMIT 1",
            (scope[0], identity.requested, identity.key),
        )).fetchone()
    finally:
        await db.close()
    if not row:
        raise HTTPException(status_code=400, detail="widget_scope_not_found")
    return scope[0], str(row["channel_name"] or "").strip().lower().lstrip("#")


def _widget_cache_key(family: str, scope: tuple[int, str] | None) -> str:
    if scope is None:
        return "public:" + family
    return f"public:{family}:{scope[0]}:{scope[1]}"


def _counter_cache_key(key: str, scope: tuple[int, str] | None) -> str:
    if scope is None:
        return "public:counter:" + key
    return f"public:counter:{scope[0]}:{scope[1]}:{key}"


@admin_router.get("/api/widgets/counters")
async def counters_list(
    account_id: int | None = None, channel: str | None = None,
) -> list[dict]:
    scope = await _verified_widget_state_scope(account_id, channel)
    db = await get_db()
    try:
        if scope is None:
            cursor = await db.execute(
                "SELECT key, label, value, animation, color, emoji FROM counters ORDER BY key"
            )
        else:
            cursor = await db.execute(
                "SELECT key, label, value, animation, color, emoji "
                "FROM widget_counters_scoped WHERE account_id = ? AND channel = ? ORDER BY key",
                scope,
            )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


@admin_router.put("/api/widgets/counters/{key}")
async def counter_update(
    key: str, payload: dict, account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    fields: list[str] = []
    values: list[Any] = []
    for k in ("label", "animation", "color", "emoji"):
        if k in payload:
            v = str(payload[k] or "").strip()
            if k == "animation" and v not in VALID_ANIMATIONS:
                v = "minimal"
            fields.append(f"{k} = ?")
            values.append(v)
    if "value" in payload:
        try:
            fields.append("value = ?")
            values.append(int(payload["value"]))
        except (TypeError, ValueError):
            pass
    if not fields:
        return {"error": "nothing_to_update"}
    fields.append("updated_at = CURRENT_TIMESTAMP")
    values.append(key)
    db = await get_db()
    try:
        if scope is None:
            await db.execute(
                "INSERT OR IGNORE INTO counters (key, label) VALUES (?, ?)",
                (key, key.title()),
            )
            await db.execute(
                f"UPDATE counters SET {', '.join(fields)} WHERE key = ?", tuple(values),
            )
        else:
            await db.execute(
                "INSERT OR IGNORE INTO widget_counters_scoped "
                "(account_id, channel, key, label) VALUES (?, ?, ?, ?)",
                (*scope, key, key.title()),
            )
            values.extend(scope)
            await db.execute(
                f"UPDATE widget_counters_scoped SET {', '.join(fields)} "
                "WHERE key = ? AND account_id = ? AND channel = ?",
                tuple(values),
            )
        await db.commit()
        _cache_invalidate(_counter_cache_key(key, scope))
    finally:
        await db.close()
    return {"ok": True}


# Increment/reset не требуют Basic-auth для локальных OBS-hotkeys, но принимают
# запросы только с loopback-интерфейса.
@public_router.post("/api/widgets/counters/{key}/increment")
async def counter_increment(
    request: Request, key: str, payload: dict | None = None,
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    from app.security import require_loopback_client
    require_loopback_client(request)
    return await _counter_increment(key, payload, account_id, channel)


async def _counter_increment(
    key: str, payload: dict | None = None,
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    delta = 1
    if payload:
        try:
            delta = int(payload.get("delta", 1))
        except (TypeError, ValueError):
            delta = 1
    db = await get_db()
    try:
        if scope is None:
            await db.execute(
                "INSERT OR IGNORE INTO counters (key, label) VALUES (?, ?)",
                (key, key.title()),
            )
            await db.execute(
                "UPDATE counters SET value = value + ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE key = ?", (delta, key),
            )
            select_sql = "SELECT value FROM counters WHERE key = ?"
            select_params = (key,)
        else:
            await db.execute(
                "INSERT OR IGNORE INTO widget_counters_scoped "
                "(account_id, channel, key, label) VALUES (?, ?, ?, ?)",
                (*scope, key, key.title()),
            )
            await db.execute(
                "UPDATE widget_counters_scoped SET value = value + ?, "
                "updated_at = CURRENT_TIMESTAMP "
                "WHERE account_id = ? AND channel = ? AND key = ?",
                (delta, *scope, key),
            )
            select_sql = (
                "SELECT value FROM widget_counters_scoped "
                "WHERE account_id = ? AND channel = ? AND key = ?"
            )
            select_params = (*scope, key)
        await db.commit()
        _cache_invalidate(_counter_cache_key(key, scope))
        cursor = await db.execute(select_sql, select_params)
        row = await cursor.fetchone()
    finally:
        await db.close()
    return {"ok": True, "key": key, "value": row["value"] if row else 0}


@public_router.post("/api/widgets/counters/{key}/reset")
async def counter_reset(
    request: Request, key: str,
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    from app.security import require_loopback_client
    require_loopback_client(request)
    return await _counter_reset(key, account_id, channel)


async def _counter_reset(
    key: str, account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    db = await get_db()
    try:
        if scope is None:
            await db.execute(
                "UPDATE counters SET value = 0, updated_at = CURRENT_TIMESTAMP WHERE key = ?",
                (key,),
            )
        else:
            await db.execute(
                "UPDATE widget_counters_scoped SET value = 0, updated_at = CURRENT_TIMESTAMP "
                "WHERE account_id = ? AND channel = ? AND key = ?",
                (*scope, key),
            )
        await db.commit()
        _cache_invalidate(_counter_cache_key(key, scope))
    finally:
        await db.close()
    return {"ok": True, "key": key, "value": 0}


@public_router.get("/api/widgets/public/counter/{key}")
async def counter_public(
    key: str, account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    cache_key = _counter_cache_key(key, scope)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    db = await get_db()
    try:
        if scope is None:
            cursor = await db.execute(
                "SELECT key, label, value, animation, color, emoji, updated_at "
                "FROM counters WHERE key = ?", (key,),
            )
        else:
            cursor = await db.execute(
                "SELECT key, label, value, animation, color, emoji, updated_at "
                "FROM widget_counters_scoped "
                "WHERE account_id = ? AND channel = ? AND key = ?", (*scope, key),
            )
        row = await cursor.fetchone()
    finally:
        await db.close()
    if not row:
        result = {"key": key, "label": key.title(), "value": 0,
                  "animation": "minimal", "color": "", "emoji": "",
                  "updated_at": ""}
    else:
        result = dict(row)
    _cache_set(cache_key, result)
    return result


# ====================================================================
# v10.4.7: Stream session (REC + uptime widget)
# ====================================================================


@admin_router.get("/api/widgets/stream-session")
async def stream_session_get() -> dict:
    return await _get_stream_session()


async def _get_stream_session() -> dict:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT start_time, is_live FROM stream_session WHERE id = 1"
        )
        row = await cursor.fetchone()
        if not row:
            return {"start_time": "", "is_live": False}
        return {
            "start_time": row["start_time"] or "",
            "is_live": bool(row["is_live"]),
        }
    finally:
        await db.close()


@admin_router.post("/api/widgets/stream-session/start")
async def stream_session_start() -> dict:
    db = await get_db()
    try:
        await db.execute(
            "UPDATE stream_session SET start_time = CURRENT_TIMESTAMP, "
            "is_live = 1 WHERE id = 1"
        )
        await db.commit()
    finally:
        await db.close()
    return {"ok": True, **(await _get_stream_session())}


@admin_router.post("/api/widgets/stream-session/stop")
async def stream_session_stop() -> dict:
    db = await get_db()
    try:
        await db.execute(
            "UPDATE stream_session SET is_live = 0 WHERE id = 1"
        )
        await db.commit()
    finally:
        await db.close()
    return {"ok": True, **(await _get_stream_session())}


@public_router.get("/api/widgets/public/stream-session")
async def stream_session_public() -> dict:
    return await _get_stream_session()


# ====================================================================
# v10.4.7: Recent events (follower / sub / cheer / raid → ticker, mascot)
# ====================================================================


VALID_EVENT_KINDS = ("follow", "subscribe", "cheer", "raid", "manual", "donation")

# Wave 4 (owner survey Q25/Q29: М) — общая event-модель.
# recent-events (лента) и latest-event-card (одна карточка) — две ПРОЕКЦИИ
# одного набора данных: обе читают recent_events через _read_recent_events().
# Карточки и публичные URL у них разные — так решил владелец.
_EVENTS_KEEP_LAST = 50


async def _read_recent_events(
    limit: int, kind: str = "", scope: tuple[int, str] | None = None,
) -> list[dict]:
    """Последние события канала, опционально отфильтрованные по виду.

    Единственная точка чтения event-модели: и лента, и одиночная карточка
    ходят сюда, чтобы проекции не разъезжались по полям и порядку.
    """
    limit = max(1, min(int(limit or 10), _EVENTS_KEEP_LAST))
    kind = (kind or "").strip()
    table = "recent_events" if scope is None else "widget_recent_events_scoped"
    clauses: list[str] = []
    params: list[Any] = []
    if scope is not None:
        clauses.append("account_id = ? AND channel = ?")
        params.extend(scope)
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    where = "WHERE " + " AND ".join(clauses) + " " if clauses else ""
    sql = (f"SELECT id, kind, username, amount, created_at FROM {table} "
           f"{where}ORDER BY id DESC LIMIT ?")
    params.append(limit)
    db = await get_db()
    try:
        cursor = await db.execute(sql, tuple(params))
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


async def on_stream_event(
    kind: str, username: str, amount: int = 0,
    *, account_id: int | None = None, channel: str | None = None,
) -> None:
    """Вызывается из server.py при приёме EventSub события."""
    if kind not in VALID_EVENT_KINDS:
        return
    scope = await _verified_widget_state_scope(account_id, channel)
    table = "recent_events" if scope is None else "widget_recent_events_scoped"
    scope_columns = "" if scope is None else "account_id, channel, "
    scope_values = () if scope is None else scope
    db = await get_db()
    try:
        await db.execute(
            f"INSERT INTO {table} ({scope_columns}kind, username, amount) "
            f"VALUES ({'?, ?, ' if scope is not None else ''}?, ?, ?)",
            (*scope_values, kind, (username or "")[:64], int(amount or 0)),
        )
        if scope is None:
            await db.execute(
                "DELETE FROM recent_events WHERE id NOT IN ("
                "SELECT id FROM recent_events ORDER BY id DESC LIMIT ?)",
                (_EVENTS_KEEP_LAST,),
            )
        else:
            await db.execute(
                "DELETE FROM widget_recent_events_scoped "
                "WHERE account_id = ? AND channel = ? AND id NOT IN ("
                "SELECT id FROM widget_recent_events_scoped "
                "WHERE account_id = ? AND channel = ? ORDER BY id DESC LIMIT ?)",
                (*scope, *scope, _EVENTS_KEEP_LAST),
            )
        await db.commit()
    finally:
        await db.close()
    logger.info("[widgets/recent-events] %s by %s (+%s)", kind, username, amount)


@admin_router.get("/api/widgets/recent-events")
async def recent_events_get(
    limit: int = 10, account_id: int | None = None, channel: str | None = None,
) -> list[dict]:
    return await _read_recent_events(
        limit, scope=await _verified_widget_state_scope(account_id, channel),
    )


@admin_router.post("/api/widgets/recent-events")
async def recent_events_add(
    payload: dict, account_id: int | None = None, channel: str | None = None,
) -> dict:
    """Ручное добавление (для теста ticker'а / mascot'а)."""
    kind = (payload.get("kind") or "manual").strip()
    if kind not in VALID_EVENT_KINDS:
        kind = "manual"
    username = (payload.get("username") or "").strip()
    try:
        amount = int(payload.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0
    await on_stream_event(
        kind, username, amount, account_id=account_id, channel=channel,
    )
    return {"ok": True}


@admin_router.delete("/api/widgets/recent-events")
async def recent_events_clear(
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    db = await get_db()
    try:
        if scope is None:
            await db.execute("DELETE FROM recent_events")
        else:
            await db.execute(
                "DELETE FROM widget_recent_events_scoped "
                "WHERE account_id = ? AND channel = ?", scope,
            )
        await db.commit()
    finally:
        await db.close()
    # Q27a: очистка (в т.ч. по биндингу) должна быть видна в OBS сразу,
    # а не после истечения TTL-кэша ленты.
    _RECENT_EVENTS_PUBLIC_CACHE.clear()
    return {"ok": True}


@public_router.get("/widget/recent-events", response_class=HTMLResponse)
async def widget_recent_events() -> str:
    return _widget_html("recent-events")


@public_router.get("/api/widgets/public/recent-events")
async def recent_events_public(
    limit: int = 10, account_id: int | None = None, channel: str | None = None,
) -> list[dict]:
    """Проекция «лента»: последние события канала.

    BUG-2: панельные iframe-превью (десятки) опрашивают этот endpoint каждые
    несколько секунд с cache-buster'ом. Короткий TTL-кэш (успех 3 c, ошибка
    1 c) делает повторные запросы бесплатными для БД — для OBS-виджета
    задержка незаметна, а суммарный poll-шторм срезается на порядки.
    """
    lim = min(int(limit or 10), 30)
    key = (lim, account_id, (channel or "").strip().lower().lstrip("#"))
    now = time.monotonic()
    cached = _RECENT_EVENTS_PUBLIC_CACHE.get(key)
    if cached is not None:
        cached_at, cached_value = cached
        ttl = _RECENT_EVENTS_PUBLIC_ERROR_TTL if isinstance(cached_value, HTTPException) else _RECENT_EVENTS_PUBLIC_TTL
        if now - cached_at < ttl:
            if isinstance(cached_value, HTTPException):
                raise cached_value
            return cached_value
    try:
        data = await _read_recent_events(
            lim,
            scope=await _verified_widget_state_scope(account_id, channel),
        )
    except HTTPException as exc:
        _RECENT_EVENTS_PUBLIC_CACHE[key] = (now, exc)
        raise
    _RECENT_EVENTS_PUBLIC_CACHE[key] = (now, data)
    return data


# BUG-2: кэш публичного recent-events (см. docstring recent_events_public)
_RECENT_EVENTS_PUBLIC_CACHE: dict[tuple, tuple[float, Any]] = {}
_RECENT_EVENTS_PUBLIC_TTL = 3.0
_RECENT_EVENTS_PUBLIC_ERROR_TTL = 1.0


# ====================================================================
# v10.4.7: Lower third
# ====================================================================


@admin_router.get("/api/widgets/lower-third")
async def lower_third_get(
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    return await _get_lower_third(await _verified_widget_state_scope(account_id, channel))


async def _get_lower_third(scope: tuple[int, str] | None = None) -> dict:
    db = await get_db()
    try:
        if scope is None:
            cursor = await db.execute(
                "SELECT name, tagline, social, avatar_url, theme, visible "
                "FROM lower_third WHERE id = 1"
            )
        else:
            cursor = await db.execute(
                "SELECT name, tagline, social, avatar_url, theme, visible "
                "FROM widget_lower_third_scoped "
                "WHERE account_id = ? AND channel = ?", scope,
            )
        row = await cursor.fetchone()
        if not row:
            return {"name": "", "tagline": "", "social": "",
                    "avatar_url": "", "theme": "minimal", "visible": False}
        return {
            "name": row["name"] or "",
            "tagline": row["tagline"] or "",
            "social": row["social"] or "",
            "avatar_url": row["avatar_url"] or "",
            "theme": row["theme"] or "minimal",
            "visible": bool(row["visible"]),
        }
    finally:
        await db.close()


@admin_router.put("/api/widgets/lower-third")
async def lower_third_put(
    payload: dict, account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    fields = []
    values: list[Any] = []
    for k in ("name", "tagline", "social", "avatar_url", "theme"):
        if k in payload:
            fields.append(f"{k} = ?")
            values.append(str(payload[k] or "")[:300])
    if "visible" in payload:
        fields.append("visible = ?")
        values.append(1 if payload["visible"] else 0)
    if not fields:
        return {"error": "nothing_to_update"}
    fields.append("updated_at = CURRENT_TIMESTAMP")
    db = await get_db()
    try:
        if scope is None:
            await db.execute(
                f"UPDATE lower_third SET {', '.join(fields)} WHERE id = 1", tuple(values),
            )
        else:
            await db.execute(
                "INSERT OR IGNORE INTO widget_lower_third_scoped "
                "(account_id, channel) VALUES (?, ?)", scope,
            )
            values.extend(scope)
            await db.execute(
                f"UPDATE widget_lower_third_scoped SET {', '.join(fields)} "
                "WHERE account_id = ? AND channel = ?", tuple(values),
            )
        await db.commit()
    finally:
        await db.close()
    return {"ok": True, **(await _get_lower_third(scope))}


@public_router.get("/api/widgets/public/lower-third")
async def lower_third_public(
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    return await _get_lower_third(await _verified_widget_state_scope(account_id, channel))


# ====================================================================
# v10.4.7: Mascot
# ====================================================================


VALID_MASCOT_PRESETS = ("blob", "owl", "cat", "bot", "ghost", "custom")


@admin_router.get("/api/widgets/mascot")
async def mascot_get(
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    return await _get_mascot(await _verified_widget_state_scope(account_id, channel))


async def _get_mascot(scope: tuple[int, str] | None = None) -> dict:
    db = await get_db()
    try:
        if scope is None:
            cursor = await db.execute(
                "SELECT preset, custom_url, idle_timeout_sec "
                "FROM mascot_state WHERE id = 1"
            )
        else:
            cursor = await db.execute(
                "SELECT preset, custom_url, idle_timeout_sec "
                "FROM widget_mascot_scoped WHERE account_id = ? AND channel = ?",
                scope,
            )
        row = await cursor.fetchone()
        if not row:
            return {"preset": "blob", "custom_url": "",
                    "idle_timeout_sec": 300}
        return dict(row)
    finally:
        await db.close()


@admin_router.put("/api/widgets/mascot")
async def mascot_put(
    payload: dict, account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    preset = (payload.get("preset") or "blob").strip()
    if preset not in VALID_MASCOT_PRESETS:
        preset = "blob"
    custom_url = str(payload.get("custom_url") or "")[:500]
    try:
        idle = int(payload.get("idle_timeout_sec") or 300)
    except (TypeError, ValueError):
        idle = 300
    idle = max(30, min(idle, 3600))
    db = await get_db()
    try:
        if scope is None:
            await db.execute(
                "UPDATE mascot_state SET preset = ?, custom_url = ?, "
                "idle_timeout_sec = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = 1", (preset, custom_url, idle),
            )
        else:
            await db.execute(
                "INSERT INTO widget_mascot_scoped "
                "(account_id, channel, preset, custom_url, idle_timeout_sec) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(account_id, channel) DO UPDATE SET "
                "preset = excluded.preset, custom_url = excluded.custom_url, "
                "idle_timeout_sec = excluded.idle_timeout_sec, "
                "updated_at = CURRENT_TIMESTAMP",
                (*scope, preset, custom_url, idle),
            )
        await db.commit()
    finally:
        await db.close()
    return {"ok": True, **(await _get_mascot(scope))}


@public_router.get("/api/widgets/public/mascot")
async def mascot_public(
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    return await _get_mascot(await _verified_widget_state_scope(account_id, channel))


# ====================================================================
# v10.4.8: Anime Runner (бегающий анимешный аватар в углу)
# ====================================================================


VALID_RUNNER_CORNERS = ("br", "bl", "tr", "tl")
VALID_RUNNER_SPEEDS = ("slow", "normal", "fast", "turbo")
VALID_RUNNER_SIZES = ("S", "M", "L", "XL")
VALID_RUNNER_PATH_MODES = ("lane", "custom", "random")
VALID_SHIRT_PATTERNS = ("solid", "palm", "stripes")


def _hex_color(s: str, default: str) -> str:
    """Принять только короткий/длинный hex-цвет (#abc / #aabbcc)."""
    s = (s or "").strip()
    if not s:
        return default
    if len(s) not in (4, 7):
        return default
    if not s.startswith("#"):
        return default
    try:
        int(s[1:], 16)
        return s
    except ValueError:
        return default


_RUNNER_DEFAULTS = {
    "hair_color": "#f5f5f5", "outfit_color": "#3a4",
    "accent_color": "#ffaa44", "eye_color": "#3a8fff",
    "corner": "br", "speed": "normal", "size": "M",
    "pause_chance": 0.15, "idle_timeout_sec": 300,
    "ears_enabled": 1, "ears_color": "#222",
    "ears_inner_color": "#ff7eb9",
    "gloves_enabled": 0, "gloves_color": "#ffffff",
    "shoes_color": "#ffffff",
    "shirt_pattern": "palm", "shorts_color": "",
    "path_mode": "lane", "path_points": "[]",
    "random_period_sec": 90,
}


async def _get_anime_runner() -> dict:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT hair_color, outfit_color, accent_color, eye_color, "
            "corner, speed, size, pause_chance, idle_timeout_sec, "
            "ears_enabled, ears_color, ears_inner_color, "
            "gloves_enabled, gloves_color, shoes_color, "
            "shirt_pattern, shorts_color, "
            "path_mode, path_points, random_period_sec "
            "FROM anime_runner_state WHERE id = 1"
        )
        row = await cursor.fetchone()
        if not row:
            return dict(_RUNNER_DEFAULTS)
        d = dict(row)
        # Заполнить дыры если ALTER не успел.
        for k, v in _RUNNER_DEFAULTS.items():
            d.setdefault(k, v)
        return d
    finally:
        await db.close()


@admin_router.get("/api/widgets/anime-runner")
async def anime_runner_get() -> dict:
    return await _get_anime_runner()


@admin_router.put("/api/widgets/anime-runner")
async def anime_runner_put(payload: dict) -> dict:
    import json
    hair = _hex_color(payload.get("hair_color") or "", "#f5f5f5")
    outfit = _hex_color(payload.get("outfit_color") or "", "#3a4")
    accent = _hex_color(payload.get("accent_color") or "", "#ffaa44")
    eye = _hex_color(payload.get("eye_color") or "", "#3a8fff")
    corner = (payload.get("corner") or "br").strip()
    if corner not in VALID_RUNNER_CORNERS:
        corner = "br"
    speed = (payload.get("speed") or "normal").strip()
    if speed not in VALID_RUNNER_SPEEDS:
        speed = "normal"
    size = (payload.get("size") or "M").strip()
    if size not in VALID_RUNNER_SIZES:
        size = "M"
    try:
        pause_chance = float(payload.get("pause_chance") or 0.15)
    except (TypeError, ValueError):
        pause_chance = 0.15
    pause_chance = max(0.0, min(pause_chance, 0.9))
    try:
        idle = int(payload.get("idle_timeout_sec") or 300)
    except (TypeError, ValueError):
        idle = 300
    idle = max(30, min(idle, 3600))
    # v10.4.9 fields
    ears_enabled = 1 if payload.get("ears_enabled", 1) else 0
    ears_color = _hex_color(payload.get("ears_color") or "", "#222")
    ears_inner_color = _hex_color(payload.get("ears_inner_color") or "", "#ff7eb9")
    gloves_enabled = 1 if payload.get("gloves_enabled", 0) else 0
    gloves_color = _hex_color(payload.get("gloves_color") or "", "#ffffff")
    shoes_color = _hex_color(payload.get("shoes_color") or "", "#ffffff")
    shirt_pattern = (payload.get("shirt_pattern") or "palm").strip()
    if shirt_pattern not in VALID_SHIRT_PATTERNS:
        shirt_pattern = "palm"
    raw_shorts = (payload.get("shorts_color") or "").strip()
    if raw_shorts:
        shorts_color = _hex_color(raw_shorts, "")
    else:
        shorts_color = ""  # пусто = такой же как футболка
    path_mode = (payload.get("path_mode") or "lane").strip()
    if path_mode not in VALID_RUNNER_PATH_MODES:
        path_mode = "lane"
    # Sanitize path_points: list of [x, y] in 0..1.
    raw_pts = payload.get("path_points")
    pts: list = []
    if isinstance(raw_pts, list):
        for p in raw_pts[:300]:  # max 300 points
            try:
                x = float(p[0]); y = float(p[1])
                pts.append([max(0.0, min(1.0, x)),
                            max(0.0, min(1.0, y))])
            except (TypeError, ValueError, IndexError):
                continue
    elif isinstance(raw_pts, str):
        try:
            arr = json.loads(raw_pts)
            if isinstance(arr, list):
                for p in arr[:300]:
                    try:
                        x = float(p[0]); y = float(p[1])
                        pts.append([max(0.0, min(1.0, x)),
                                    max(0.0, min(1.0, y))])
                    except (TypeError, ValueError, IndexError):
                        continue
        except Exception:
            pts = []
    path_points = json.dumps(pts)
    try:
        random_period = int(payload.get("random_period_sec") or 90)
    except (TypeError, ValueError):
        random_period = 90
    random_period = max(10, min(random_period, 1800))
    db = await get_db()
    try:
        await db.execute(
            "UPDATE anime_runner_state SET hair_color = ?, outfit_color = ?, "
            "accent_color = ?, eye_color = ?, corner = ?, speed = ?, "
            "size = ?, pause_chance = ?, idle_timeout_sec = ?, "
            "ears_enabled = ?, ears_color = ?, ears_inner_color = ?, "
            "gloves_enabled = ?, gloves_color = ?, shoes_color = ?, "
            "shirt_pattern = ?, shorts_color = ?, "
            "path_mode = ?, path_points = ?, random_period_sec = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = 1",
            (hair, outfit, accent, eye, corner, speed, size,
             pause_chance, idle,
             ears_enabled, ears_color, ears_inner_color,
             gloves_enabled, gloves_color, shoes_color,
             shirt_pattern, shorts_color,
             path_mode, path_points, random_period),
        )
        await db.commit()
    finally:
        await db.close()
    return {"ok": True, **(await _get_anime_runner())}


@public_router.get("/api/widgets/public/anime-runner")
async def anime_runner_public() -> dict:
    return await _get_anime_runner()


# ====================================================================
# Widget HTML pages
# ====================================================================
#
# Все pages — self-contained (inline CSS+JS). Это специально:
# OBS Browser Source кэширует ресурсы агрессивно, и одиночный HTML
# меньше шансов «пожелтить» при апдейте.

_SERVICE_WORKER_JS = """
const CACHE_NAME = 'widget-cache-v2';
const API_CACHE_NAME = 'widget-api-cache-v1';
const API_TIMEOUT_MS = 3000;

// Install - no precaching needed
self.addEventListener('install', (event) => {
    self.skipWaiting();
});

// Activate - clean old caches
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE_NAME && k !== API_CACHE_NAME).map(k => caches.delete(k)))
        ).then(() => self.clients.claim())
    );
});

// Fetch strategy
self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // Shared runtimes and palettes must not stay stale in long-lived OBS sources.
    if (url.pathname.startsWith('/widget/_shared/')) {
        event.respondWith(networkFirstWithTimeout(event.request, CACHE_NAME, API_TIMEOUT_MS));
        return;
    }

    // Widget HTML pages: stale-while-revalidate
    if (url.pathname.startsWith('/widget/') && !url.pathname.endsWith('/sw.js')) {
        event.respondWith(staleWhileRevalidate(event.request, CACHE_NAME));
        return;
    }

    // Public API data: network-first with cache fallback
    if (url.pathname.startsWith('/api/widgets/public/')) {
        event.respondWith(networkFirstWithTimeout(event.request, API_CACHE_NAME, API_TIMEOUT_MS));
        return;
    }

    // Everything else: pass through
    event.respondWith(fetch(event.request));
});

async function staleWhileRevalidate(request, cacheName) {
    const cache = await caches.open(cacheName);
    const cached = await cache.match(request);

    const fetchPromise = fetch(request).then(response => {
        if (response.ok) {
            cache.put(request, response.clone());
        }
        return response;
    }).catch(() => cached);

    return cached || fetchPromise;
}

async function networkFirstWithTimeout(request, cacheName, timeoutMs) {
    const cache = await caches.open(cacheName);

    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
        const response = await fetch(request, {signal: controller.signal});
        clearTimeout(timeoutId);
        if (response.ok) {
            cache.put(request, response.clone());
        }
        return response;
    } catch (e) {
        const cached = await cache.match(request);
        if (cached) return cached;
        throw e;
    }
}
"""


@public_router.get("/widget/sw.js")
async def widget_service_worker() -> Response:
    return Response(
        content=_SERVICE_WORKER_JS,
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
    )


def _safe_title(t: str) -> str:
    """Минимальный escape для подстановки в HTML (без полноценной шаблонизации
    тут перебор)."""
    return (t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


@public_router.get("/widget/animated-bg", response_class=HTMLResponse)
async def widget_animated_bg(type: str = "snow", count: int = 0,
                             speed: float = 1.0, color: str = "",
                             bg: str = "transparent", title: str = "") -> str:
    """Анимированный фон. Параметры:

    * ``type`` — snow | stars | fire | rain | embers | matrix.
    * ``count`` — кол-во частиц (0 = авто-выбор по типу).
    * ``speed`` — множитель скорости (0.1..3).
    * ``color`` — цвет частиц (CSS-color, по типу есть дефолты).
    * ``bg`` — цвет фона (по умолчанию transparent — для оверлея в OBS).
    * ``title`` — опциональная плашка-надпись («brb 5 min»).
    """
    type_safe = type if type in ("snow", "stars", "fire", "rain", "embers", "matrix") else "snow"
    title = title if title else await _get_widget_title("animated-bg")
    return _widget_html("animated-bg").replace("__TYPE__", type_safe) \
        .replace("__COUNT__", str(int(count or 0))) \
        .replace("__SPEED__", str(float(speed))) \
        .replace("__COLOR__", color or "") \
        .replace("__BG__", bg or "transparent") \
        .replace("__TITLE__", _safe_title(title))


@public_router.get("/widget/goals", response_class=HTMLResponse)
async def widget_goals(theme: str = "dark", title: str = "") -> str:
    title = title if title else await _get_widget_title("goals")
    return _widget_html("goals").replace("__THEME__", "dark" if theme != "light" else "light") \
        .replace("__TITLE__", _safe_title(title))


@public_router.get("/widget/now-playing", response_class=HTMLResponse)
async def widget_now_playing(theme: str = "dark", title: str = "") -> str:
    title = title if title else await _get_widget_title("now-playing")
    return _widget_html("now-playing").replace("__THEME__", "dark" if theme != "light" else "light") \
        .replace("__TITLE__", _safe_title(title))


@public_router.get("/widget/sub-goal", response_class=HTMLResponse)
async def widget_sub_goal(title: str = "") -> str:
    # NB: sub-goal уже хранит title в sub_goal.title; URL-параметр оверрайдит.
    title_override = title or ""
    return _widget_html("sub-goal").replace("__TITLE_OVERRIDE__", _safe_title(title_override))


@public_router.get("/widget/schedule", response_class=HTMLResponse)
async def widget_schedule(theme: str = "dark", title: str = "",
                          tz: str = "local") -> str:
    """Виджет «Сейчас на стриме / Скоро».

    * ``theme`` — dark | light | arcade | cyber.
    * ``title`` — заголовок-баннер. Пустой → берётся из widget_titles.
    * ``tz`` — local (default, по часам зрителя) или UTC offset (``+3``).
    """
    theme_safe = theme if theme in ("dark", "light", "arcade", "cyber") else "dark"
    title = title if title else await _get_widget_title("schedule")
    return _widget_html("schedule").replace("__THEME__", theme_safe) \
        .replace("__TITLE__", _safe_title(title)) \
        .replace("__TZ__", _safe_title(tz))


# ---------- v10.4.7 widgets ----------

@public_router.get("/widget/counter", response_class=HTMLResponse)
async def widget_counter() -> HTMLResponse:
    """Выведен из эксплуатации (owner survey Q12: Д).

    URL сохранён ради уже настроенных OBS-сцен — отдаёт тёмную заглушку.
    Публичный API счётчиков (/api/widgets/counters/*) и таблица counters
    НЕ тронуты: на них навешаны чат-команды и хоткеи владельца.
    """
    return HTMLResponse(_retired_widget_html("/widget/counter"))


@public_router.get("/widget/uptime", response_class=HTMLResponse)
async def widget_uptime(theme: str = "rec", title: str = "") -> str:
    """REC / uptime indicator. theme: rec | minimal | retro."""
    theme_safe = theme if theme in ("rec", "minimal", "retro") else "rec"
    title = title if title else await _get_widget_title("uptime")
    return _widget_html("stream-session").replace("__THEME__", theme_safe) \
        .replace("__TITLE__", _safe_title(title))


@public_router.get("/widget/follower-ticker", response_class=HTMLResponse)
async def widget_follower_ticker(theme: str = "neon", title: str = "") -> str:
    """Бегущая строка с последними follow/sub/cheer/raid событиями."""
    theme_safe = theme if theme in ("neon", "minimal", "rainbow") else "neon"
    title = title if title else await _get_widget_title("follower-ticker")
    return _widget_html("follower-ticker").replace("__THEME__", theme_safe) \
        .replace("__TITLE__", _safe_title(title))


@public_router.get("/widget/lower-third", response_class=HTMLResponse)
async def widget_lower_third(theme: str = "", title: str = "") -> str:
    """Lower-third плашка (имя + tagline + соцсети)."""
    return _widget_html("lower-third").replace("__THEME_OVERRIDE__", _safe_title(theme)) \
        .replace("__TITLE_OVERRIDE__", _safe_title(title))


@public_router.get("/widget/mascot", response_class=HTMLResponse)
async def widget_mascot(preset: str = "", mascot: str = "") -> str:
    """Маскот-зверёк в углу с реакциями на сабы/тишину."""
    return _widget_html("mascot").replace("__PRESET_OVERRIDE__", _safe_title(preset)) \
        .replace("__CUSTOM_URL_OVERRIDE__", _safe_title(mascot))


@public_router.get("/widget/anime-runner", response_class=HTMLResponse)
async def widget_anime_runner(corner: str = "", speed: str = "",
                              size: str = "", hair: str = "",
                              outfit: str = "", accent: str = "",
                              eye: str = "", mode: str = "") -> str:
    """Анимешный аватар бегает в углу или по кастомному пути.

    URL-параметры (все опциональны, по умолчанию берутся из БД):
    * ``corner`` — br | bl | tr | tl (только для mode=lane)
    * ``speed`` — slow | normal | fast | turbo
    * ``size`` — S | M | L | XL
    * ``hair`` — hex-цвет волос
    * ``outfit`` — hex-цвет худи/одежды
    * ``accent`` — hex-цвет шарфа/акцента
    * ``eye`` — hex-цвет глаз
    * ``mode`` — lane | custom | random (path mode override)
    """
    return _widget_html("anime-runner") \
        .replace("__CORNER_OVERRIDE__", _safe_title(corner)) \
        .replace("__SPEED_OVERRIDE__", _safe_title(speed)) \
        .replace("__SIZE_OVERRIDE__", _safe_title(size)) \
        .replace("__HAIR_OVERRIDE__", _safe_title(hair)) \
        .replace("__OUTFIT_OVERRIDE__", _safe_title(outfit)) \
        .replace("__ACCENT_OVERRIDE__", _safe_title(accent)) \
        .replace("__EYE_OVERRIDE__", _safe_title(eye)) \
        .replace("__PATH_MODE_OVERRIDE__", _safe_title(mode))


# ====================================================================
# HTML templates (inline)
# ====================================================================


# ====================================================================
# v10.4.7: Counter widget HTML (death / streak / generic)
# ====================================================================


# ====================================================================
# v10.4.7: Uptime / REC indicator widget
# ====================================================================


# ====================================================================
# v10.4.7: Follower-ticker widget
# ====================================================================


# ====================================================================
# v10.4.7: Lower third widget
# ====================================================================


# ====================================================================
# v10.4.7: Mascot widget (animated SVG)
# ====================================================================

# ====================================================================
# v10.4.8: Anime Runner widget (бегающий анимешный аватар)
# ====================================================================


# ====================================================================
# Widget #12: Chat Highlight (v10.5)
# ====================================================================
#
# OBS-виджет «AI в чате» — показывает последнее сообщение бота (или
# любое выделенное сообщение) поверх стрима. В auto_mode бот
# автоматически пушит каждый свой ответ; стример может также вручную
# выставить текст из панели. display_sec — сколько секунд показывать
# сообщение перед fade-out.


async def _get_chat_highlight_row(scope: tuple[int, str] | None = None) -> dict:
    db = await get_db()
    try:
        if scope is None:
            cursor = await db.execute(
                "SELECT id, text, author, kind, theme, visible, auto_mode, "
                "display_sec, updated_at FROM chat_highlight WHERE id = 1"
            )
        else:
            cursor = await db.execute(
                "SELECT 1 AS id, text, author, kind, theme, visible, auto_mode, "
                "display_sec, updated_at FROM widget_chat_highlight_scoped "
                "WHERE account_id = ? AND channel = ?", scope,
            )
        row = await cursor.fetchone()
        return dict(row) if row else {
            "id": 1, "text": "", "author": "", "kind": "ai",
            "theme": "glow", "visible": 1, "auto_mode": 1,
            "display_sec": 15, "updated_at": "",
        }
    finally:
        await db.close()


@admin_router.get("/api/widgets/chat-highlight")
async def chat_highlight_get(
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    return await _get_chat_highlight_row(
        await _verified_widget_state_scope(account_id, channel),
    )


@admin_router.put("/api/widgets/chat-highlight")
async def chat_highlight_put(
    payload: dict, account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    db = await get_db()
    try:
        fields: list[str] = []
        values: list[Any] = []
        for k in ("text", "author", "kind", "theme"):
            if k in payload:
                fields.append(f"{k} = ?")
                values.append(str(payload[k] or "").strip())
        for k in ("visible", "auto_mode"):
            if k in payload:
                fields.append(f"{k} = ?")
                values.append(1 if payload[k] else 0)
        if "display_sec" in payload:
            try:
                fields.append("display_sec = ?")
                values.append(max(3, min(120, int(payload["display_sec"]))))
            except (TypeError, ValueError):
                pass
        if not fields:
            return {"ok": False, "error": "nothing_to_update"}
        if scope is not None:
            await db.execute(
                "INSERT OR IGNORE INTO widget_chat_highlight_scoped "
                "(account_id, channel) VALUES (?, ?)", scope,
            )
        fields.append("updated_at = CURRENT_TIMESTAMP")
        if scope is None:
            values.append(1)
            await db.execute(
                f"UPDATE chat_highlight SET {', '.join(fields)} WHERE id = ?",
                tuple(values),
            )
        else:
            values.extend(scope)
            await db.execute(
                f"UPDATE widget_chat_highlight_scoped SET {', '.join(fields)} "
                "WHERE account_id = ? AND channel = ?", tuple(values),
            )
        await db.commit()
    finally:
        await db.close()
    return {"ok": True, **(await _get_chat_highlight_row(scope))}


@public_router.get("/api/widgets/public/chat-highlight")
async def chat_highlight_public(
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    return await _get_chat_highlight_row(
        await _verified_widget_state_scope(account_id, channel),
    )


async def push_chat_highlight(
    text: str, author: str = "", kind: str = "ai",
    *, account_id: int | None = None, channel: str | None = None,
) -> None:
    """Вызывается из server.py / chat_analyzer когда бот отправляет сообщение.

    Если auto_mode включён — обновляет виджет автоматически.
    """
    scope = await _verified_widget_state_scope(account_id, channel)
    row = await _get_chat_highlight_row(scope)
    if not row.get("auto_mode"):
        return
    db = await get_db()
    try:
        if scope is None:
            await db.execute(
                "UPDATE chat_highlight SET text = ?, author = ?, kind = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = 1",
                (text[:500], author[:100], kind[:20]),
            )
        else:
            await db.execute(
                "INSERT OR IGNORE INTO widget_chat_highlight_scoped "
                "(account_id, channel) VALUES (?, ?)", scope,
            )
            await db.execute(
                "UPDATE widget_chat_highlight_scoped "
                "SET text = ?, author = ?, kind = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE account_id = ? AND channel = ?",
                (text[:500], author[:100], kind[:20], *scope),
            )
        await db.commit()
    finally:
        await db.close()


@public_router.get("/widget/chat-highlight", response_class=HTMLResponse)
async def widget_chat_highlight_page() -> HTMLResponse:
    return HTMLResponse(_widget_html("chat-highlight"))


# ====================================================================
# Widget #13: Chat Roulette (v10.5)
# ====================================================================
#
# Колесо рулетки — выбирает случайного зрителя из чата.
# Участники собираются из недавних сообщений (таблица chat_log)
# или вручную через API. Стример нажимает «Крутить» → виджет
# показывает анимацию колеса и останавливается на победителе.


async def _get_roulette_row(scope: tuple[int, str] | None = None) -> dict:
    db = await get_db()
    try:
        if scope is None:
            cursor = await db.execute(
                "SELECT id, winner, participants, theme, spin_duration_sec, "
                "auto_interval_min, visible, updated_at FROM chat_roulette WHERE id = 1"
            )
        else:
            cursor = await db.execute(
                "SELECT 1 AS id, winner, participants, theme, spin_duration_sec, "
                "auto_interval_min, visible, updated_at FROM widget_chat_roulette_scoped "
                "WHERE account_id = ? AND channel = ?", scope,
            )
        row = await cursor.fetchone()
        if row:
            d = dict(row)
            import json
            try:
                d["participants"] = json.loads(d["participants"])
            except Exception:
                d["participants"] = []
            return d
        return {
            "id": 1, "winner": "", "participants": [],
            "theme": "wheel", "spin_duration_sec": 5,
            "auto_interval_min": 0, "visible": 1, "updated_at": "",
        }
    finally:
        await db.close()


@admin_router.get("/api/widgets/chat-roulette")
async def roulette_get(
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    return await _get_roulette_row(
        await _verified_widget_state_scope(account_id, channel),
    )


@admin_router.put("/api/widgets/chat-roulette")
async def roulette_put(
    payload: dict, account_id: int | None = None, channel: str | None = None,
) -> dict:
    import json as _json
    scope = await _verified_widget_state_scope(account_id, channel)
    db = await get_db()
    try:
        fields: list[str] = []
        values: list[Any] = []
        for k in ("winner", "theme"):
            if k in payload:
                fields.append(f"{k} = ?")
                values.append(str(payload[k] or "").strip())
        if "participants" in payload:
            fields.append("participants = ?")
            values.append(_json.dumps(payload["participants"], ensure_ascii=False))
        if "visible" in payload:
            fields.append("visible = ?")
            values.append(1 if payload["visible"] else 0)
        for k in ("spin_duration_sec", "auto_interval_min"):
            if k in payload:
                try:
                    fields.append(f"{k} = ?")
                    values.append(max(1, int(payload[k])) if k == "spin_duration_sec" else max(0, int(payload[k])))
                except (TypeError, ValueError):
                    pass
        if not fields:
            return {"ok": False, "error": "nothing_to_update"}
        if scope is not None:
            await db.execute(
                "INSERT OR IGNORE INTO widget_chat_roulette_scoped "
                "(account_id, channel) VALUES (?, ?)", scope,
            )
        fields.append("updated_at = CURRENT_TIMESTAMP")
        if scope is None:
            values.append(1)
            await db.execute(
                f"UPDATE chat_roulette SET {', '.join(fields)} WHERE id = ?",
                tuple(values),
            )
        else:
            values.extend(scope)
            await db.execute(
                f"UPDATE widget_chat_roulette_scoped SET {', '.join(fields)} "
                "WHERE account_id = ? AND channel = ?", tuple(values),
            )
        await db.commit()
    finally:
        await db.close()
    return {"ok": True, **(await _get_roulette_row(scope))}


@admin_router.post("/api/widgets/chat-roulette/spin")
async def roulette_spin(
    payload: dict | None = None,
    account_id: int | None = None,
    channel: str | None = None,
) -> dict:
    """Собрать участников из chat_log и крутнуть колесо."""
    import random as _rng
    import json as _json

    scope = await _verified_widget_state_scope(account_id, channel)
    legacy_channel = str((payload or {}).get("channel", "")).strip()
    minutes = int((payload or {}).get("minutes", 10))

    db = await get_db()
    try:
        # Берём уникальных авторов из чата за последние N минут.
        if scope is None:
            channel_filter = "AND channel = ? " if legacy_channel else ""
            params = (f"-{minutes}",) + ((legacy_channel,) if legacy_channel else ())
        else:
            channel_filter = (
                "AND account_id = ? "
                "AND lower(ltrim(trim(channel), '#')) = ? "
            )
            params = (f"-{minutes}", *scope)
        cursor = await db.execute(
            "SELECT DISTINCT author FROM chat_log "
            "WHERE timestamp >= datetime('now', ? || ' minutes') "
            "AND author != '' "
            + channel_filter
            + "ORDER BY author",
            params,
        )
        rows = await cursor.fetchall()
        participants = [r["author"] for r in rows]
        if not participants:
            return {"error": "no_participants", "participants": []}

        winner = _rng.choice(participants)
        encoded_participants = _json.dumps(participants, ensure_ascii=False)
        if scope is None:
            await db.execute(
                "UPDATE chat_roulette SET winner = ?, participants = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = 1",
                (winner, encoded_participants),
            )
        else:
            await db.execute(
                "INSERT OR IGNORE INTO widget_chat_roulette_scoped "
                "(account_id, channel) VALUES (?, ?)", scope,
            )
            await db.execute(
                "UPDATE widget_chat_roulette_scoped "
                "SET winner = ?, participants = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE account_id = ? AND channel = ?",
                (winner, encoded_participants, *scope),
            )
        await db.commit()
    finally:
        await db.close()
    return {"ok": True, "winner": winner, "participants": participants}


@public_router.get("/api/widgets/public/chat-roulette")
async def roulette_public(
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    return await _get_roulette_row(
        await _verified_widget_state_scope(account_id, channel),
    )


@public_router.get("/widget/chat-roulette", response_class=HTMLResponse)
async def widget_roulette_page() -> HTMLResponse:
    return HTMLResponse(_widget_html("chat-roulette"))


# ====================================================================
# Widget #14: Combo Counter — ВЫВЕДЕН ИЗ ЭКСПЛУАТАЦИИ (owner survey Q14: Д)
# ====================================================================
#
# Карточка, admin/public API, автотрекинг серий в chat_analyzer и папка
# виджета удалены. Публичный URL /widget/combo-counter сохранён заглушкой
# ради уже настроенных OBS-сцен. Таблица combo_counter в БД не тронута:
# схему на этапе чистки не меняем (PLAN_TODO инварианты).


@public_router.get("/widget/combo-counter", response_class=HTMLResponse)
async def widget_combo_page() -> HTMLResponse:
    """Выведен из эксплуатации (owner survey Q14: Д)."""
    return HTMLResponse(_retired_widget_html("/widget/combo-counter"))


# ====================================================================
# Widget #15: Song Request Queue (v10.5)
# ====================================================================
#
# Очередь запросов песен. Зрители пишут !sr <название> в чате,
# песня добавляется в очередь. Стример управляет через панель:
# skip, clear, удалить конкретную. Виджет показывает текущую
# и следующие N песен.


async def _get_sr_settings(scope: tuple[int, str] | None = None) -> dict:
    db = await get_db()
    try:
        if scope is None:
            cursor = await db.execute(
                "SELECT id, enabled, max_queue, theme, visible, show_count, "
                "cooldown_sec, max_per_user, updated_at "
                "FROM song_request_settings WHERE id = 1"
            )
        else:
            cursor = await db.execute(
                "SELECT 1 AS id, enabled, max_queue, theme, visible, show_count, "
                "cooldown_sec, max_per_user, updated_at "
                "FROM widget_song_request_settings_scoped "
                "WHERE account_id = ? AND channel = ?", scope,
            )
        row = await cursor.fetchone()
        return dict(row) if row else {
            "id": 1, "enabled": 1, "max_queue": 50, "theme": "neon",
            "visible": 1, "show_count": 4, "updated_at": "",
        }
    finally:
        await db.close()


async def _get_sr_queue(
    limit: int = 50, scope: tuple[int, str] | None = None,
) -> list[dict]:
    db = await get_db()
    try:
        if scope is None:
            cursor = await db.execute(
                "SELECT id, title, requested_by, channel, status, created_at, priority "
                "FROM song_request_queue WHERE status = 'queued' "
                "ORDER BY priority DESC, created_at ASC LIMIT ?", (limit,),
            )
        else:
            cursor = await db.execute(
                "SELECT id, title, requested_by, channel, status, created_at, priority "
                "FROM widget_song_request_queue_scoped "
                "WHERE account_id = ? AND channel = ? AND status = 'queued' "
                "ORDER BY priority DESC, created_at ASC LIMIT ?", (*scope, limit),
            )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


async def _get_sr_now_playing(scope: tuple[int, str] | None = None) -> dict | None:
    db = await get_db()
    try:
        if scope is None:
            cursor = await db.execute(
                "SELECT id, title, requested_by, channel, status, created_at, priority "
                "FROM song_request_queue WHERE status = 'playing' "
                "ORDER BY created_at DESC LIMIT 1"
            )
        else:
            cursor = await db.execute(
                "SELECT id, title, requested_by, channel, status, created_at, priority "
                "FROM widget_song_request_queue_scoped "
                "WHERE account_id = ? AND channel = ? AND status = 'playing' "
                "ORDER BY created_at DESC LIMIT 1", scope,
            )
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


@admin_router.get("/api/widgets/song-request")
async def sr_get(account_id: int | None = None, channel: str | None = None) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    settings = await _get_sr_settings(scope)
    queue = await _get_sr_queue(settings.get("max_queue", 50), scope)
    now_playing = await _get_sr_now_playing(scope)
    return {**settings, "queue": queue, "now_playing": now_playing}


@admin_router.put("/api/widgets/song-request")
async def sr_put(
    payload: dict, account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    db = await get_db()
    try:
        fields: list[str] = []
        values: list[Any] = []
        if "enabled" in payload:
            fields.append("enabled = ?")
            values.append(1 if payload["enabled"] else 0)
        if "visible" in payload:
            fields.append("visible = ?")
            values.append(1 if payload["visible"] else 0)
        if "theme" in payload:
            fields.append("theme = ?")
            values.append(str(payload["theme"]).strip())
        for k in ("max_queue", "show_count", "cooldown_sec", "max_per_user"):
            if k in payload:
                try:
                    fields.append(f"{k} = ?")
                    values.append(max(0, int(payload[k])))
                except (TypeError, ValueError):
                    pass
        if not fields:
            return {"ok": False, "error": "nothing_to_update"}
        if scope is not None:
            await db.execute(
                "INSERT OR IGNORE INTO widget_song_request_settings_scoped "
                "(account_id, channel) VALUES (?, ?)", scope,
            )
        fields.append("updated_at = CURRENT_TIMESTAMP")
        if scope is None:
            values.append(1)
            await db.execute(
                f"UPDATE song_request_settings SET {', '.join(fields)} WHERE id = ?",
                tuple(values),
            )
        else:
            values.extend(scope)
            await db.execute(
                f"UPDATE widget_song_request_settings_scoped SET {', '.join(fields)} "
                "WHERE account_id = ? AND channel = ?", tuple(values),
            )
        await db.commit()
    finally:
        await db.close()
    return {"ok": True, **(await _get_sr_settings(scope))}


@admin_router.post("/api/widgets/song-request/add")
async def sr_add(
    payload: dict, account_id: int | None = None, channel: str | None = None,
) -> dict:
    from app.song_request_service import request_identity, validate_request_text, write_audit

    scope = await _verified_widget_state_scope(account_id, channel)
    raw_title = str(payload.get("title", ""))
    title, invalid_reason = validate_request_text(raw_title)
    requested_by = str(payload.get("requested_by", "")).strip()
    item_channel = scope[1] if scope is not None else str(payload.get("channel", "")).strip()
    settings = await _get_sr_settings(scope)
    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        if invalid_reason:
            await write_audit(
                db, scope, source="owner", actor=requested_by, request_text=raw_title,
                accepted=False, reason=invalid_reason,
            )
            await db.commit()
            return {"error": invalid_reason}
        table = "song_request_queue" if scope is None else "widget_song_request_queue_scoped"
        where = "" if scope is None else "account_id = ? AND channel = ? AND "
        params = () if scope is None else scope
        cursor = await db.execute(
            f"SELECT title FROM {table} WHERE {where}status IN ('queued', 'playing')", params,
        )
        identity = request_identity(title)
        if any(request_identity(row["title"]) == identity for row in await cursor.fetchall()):
            await write_audit(
                db, scope, source="owner", actor=requested_by, request_text=title,
                accepted=False, reason="duplicate_request",
            )
            await db.commit()
            return {"error": "duplicate_request"}
        cursor = await db.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE {where}status = 'queued'", params,
        )
        row = await cursor.fetchone()
        if row and row["n"] >= int(settings.get("max_queue", 50)):
            await write_audit(
                db, scope, source="owner", actor=requested_by, request_text=title,
                accepted=False, reason="queue_full",
            )
            await db.commit()
            return {"error": "queue_full"}
        if scope is None:
            cursor = await db.execute(
                "INSERT INTO song_request_queue (title, requested_by, channel) VALUES (?, ?, ?)",
                (title, requested_by[:50], item_channel[:50]),
            )
        else:
            cursor = await db.execute(
                "INSERT INTO widget_song_request_queue_scoped "
                "(account_id, channel, title, requested_by) VALUES (?, ?, ?, ?)",
                (*scope, title, requested_by[:50]),
            )
        await write_audit(
            db, scope, source="owner", actor=requested_by, request_text=title,
            accepted=True, reason="accepted", queue_item_id=cursor.lastrowid,
        )
        await db.commit()
        return {"ok": True, "id": cursor.lastrowid, "title": title}
    finally:
        await db.close()


@admin_router.post("/api/widgets/song-request/skip")
async def sr_skip(account_id: int | None = None, channel: str | None = None) -> dict:
    """Пропустить текущую — пометить playing как done, следующую как playing."""
    scope = await _verified_widget_state_scope(account_id, channel)
    table = "song_request_queue" if scope is None else "widget_song_request_queue_scoped"
    where = "" if scope is None else "account_id = ? AND channel = ? AND "
    params = () if scope is None else scope
    db = await get_db()
    try:
        await db.execute(
            f"UPDATE {table} SET status = 'done' WHERE {where}status = 'playing'", params,
        )
        cursor = await db.execute(
            f"SELECT id FROM {table} WHERE {where}status = 'queued' "
            "ORDER BY priority DESC, created_at ASC LIMIT 1", params,
        )
        row = await cursor.fetchone()
        if row:
            await db.execute(
                f"UPDATE {table} SET status = 'playing' WHERE id = ?",
                (row["id"],),
            )
        await db.commit()
    finally:
        await db.close()
    now_playing = await _get_sr_now_playing(scope)
    return {"ok": True, "now_playing": now_playing}


@admin_router.post("/api/widgets/song-request/clear")
async def sr_clear(account_id: int | None = None, channel: str | None = None) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    db = await get_db()
    try:
        if scope is None:
            await db.execute("DELETE FROM song_request_queue")
        else:
            await db.execute(
                "DELETE FROM widget_song_request_queue_scoped "
                "WHERE account_id = ? AND channel = ?", scope,
            )
        await db.commit()
    finally:
        await db.close()
    return {"ok": True}


@admin_router.delete("/api/widgets/song-request/{song_id}")
async def sr_delete(
    song_id: int, account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    db = await get_db()
    try:
        if scope is None:
            await db.execute("DELETE FROM song_request_queue WHERE id = ?", (song_id,))
        else:
            await db.execute(
                "DELETE FROM widget_song_request_queue_scoped "
                "WHERE id = ? AND account_id = ? AND channel = ?", (song_id, *scope),
            )
        await db.commit()
    finally:
        await db.close()
    return {"ok": True}


@admin_router.get("/api/widgets/song-request/priority")
async def sr_priority_list() -> dict:
    """List all manually granted priority users."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, username, granted_by, created_at FROM sr_priority_users "
            "ORDER BY created_at DESC"
        )
        return {"ok": True, "users": [dict(r) for r in await cursor.fetchall()]}
    finally:
        await db.close()


@admin_router.post("/api/widgets/song-request/priority/grant")
async def sr_priority_grant(payload: dict) -> dict:
    """Grant priority to a username."""
    username = str(payload.get("username", "")).strip().lower()
    granted_by = str(payload.get("granted_by", "")).strip()
    if not username:
        return {"error": "empty_username"}
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO sr_priority_users (username, granted_by) VALUES (?, ?)",
            (username, granted_by),
        )
        await db.commit()
        return {"ok": True, "username": username}
    finally:
        await db.close()


@admin_router.delete("/api/widgets/song-request/priority/{username}")
async def sr_priority_remove(username: str) -> dict:
    """Remove priority from a username."""
    db = await get_db()
    try:
        await db.execute(
            "DELETE FROM sr_priority_users WHERE username = ?", (username.lower(),)
        )
        await db.commit()
    finally:
        await db.close()
    return {"ok": True}


@admin_router.post("/api/widgets/song-request/{song_id}/boost")
async def sr_boost(song_id: int) -> dict:
    """Streamer override: boost a song to top of queue (priority=10)."""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE song_request_queue SET priority = 10 WHERE id = ?", (song_id,)
        )
        await db.commit()
    finally:
        await db.close()
    return {"ok": True}


@public_router.get("/api/widgets/public/song-request")
async def sr_public(account_id: int | None = None, channel: str | None = None) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    settings = await _get_sr_settings(scope)
    show_count = settings.get("show_count", 4)
    queue = await _get_sr_queue(show_count, scope)
    now_playing = await _get_sr_now_playing(scope)
    return {
        "visible": settings.get("visible", 1),
        "theme": settings.get("theme", "neon"),
        "now_playing": now_playing,
        "queue": queue[:show_count],
    }


# §11.5: cooldown на !sr per user (in-memory, сбрасывается при рестарте — ок).
_sr_user_last: dict[tuple[tuple[int, str] | None, str], float] = {}


async def add_song_request(
    title: str, requested_by: str, channel: str = "", badges: list[str] | None = None,
    *, account_id: int | None = None, source: str = "chat", event_id: str = "",
    priority_override: int = 0, boost_duplicate: bool = False,
) -> dict:
    """Вызывается из chat_analyzer при команде !sr."""
    import time as _time
    from app.song_request_service import request_identity, validate_request_text, write_audit

    scope = await _verified_widget_state_scope(account_id, channel if account_id else None)
    raw_title = str(title or "")
    title, invalid_reason = validate_request_text(raw_title)
    actor = str(requested_by or "").strip()[:50]
    if invalid_reason:
        db = await get_db()
        try:
            await write_audit(
                db, scope, source=source, actor=actor, request_text=raw_title,
                accepted=False, reason=invalid_reason, event_id=event_id,
            )
            await db.commit()
        finally:
            await db.close()
        return {"error": invalid_reason}
    settings = await _get_sr_settings(scope)
    if not settings.get("enabled"):
        db = await get_db()
        try:
            await write_audit(
                db, scope, source=source, actor=actor, request_text=title,
                accepted=False, reason="disabled", event_id=event_id,
            )
            await db.commit()
        finally:
            await db.close()
        return {"error": "disabled"}

    max_per_user = int(settings.get("max_per_user") or 0)
    cooldown = int(settings.get("cooldown_sec") or 0)
    priority = max(0, min(int(priority_override), 10))
    if badges:
        if "moderator" in badges:
            priority = max(priority, 3)
        if "vip" in badges:
            priority = max(priority, 2)
        if "subscriber" in badges:
            priority = max(priority, 1)
    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        table = "song_request_queue" if scope is None else "widget_song_request_queue_scoped"
        where = "" if scope is None else "account_id = ? AND channel = ? AND "
        scope_params = () if scope is None else scope
        if max_per_user > 0:
            cursor = await db.execute(
                f"SELECT COUNT(*) AS n FROM {table} WHERE requested_by = ? AND "
                f"{where}status = 'queued'",
                (actor, *scope_params),
            )
            row = await cursor.fetchone()
            if row and row["n"] >= max_per_user:
                await write_audit(
                    db, scope, source=source, actor=actor, request_text=title,
                    accepted=False, reason="user_limit", event_id=event_id,
                )
                await db.commit()
                return {"error": "user_limit", "limit": max_per_user}
        if cooldown > 0:
            cooldown_key = (scope, actor.lower())
            wait_left = cooldown - (_time.time() - _sr_user_last.get(cooldown_key, 0))
            if wait_left > 0:
                await write_audit(
                    db, scope, source=source, actor=actor, request_text=title,
                    accepted=False, reason="cooldown", event_id=event_id,
                )
                await db.commit()
                return {"error": "cooldown", "retry_after": int(wait_left) + 1}
        cursor = await db.execute(
            f"SELECT id, title FROM {table} WHERE {where}status IN ('queued', 'playing')",
            scope_params,
        )
        identity = request_identity(title)
        duplicate = next(
            (row for row in await cursor.fetchall() if request_identity(row["title"]) == identity),
            None,
        )
        if duplicate and boost_duplicate:
            await db.execute(
                f"UPDATE {table} SET priority = MAX(priority, ?) WHERE id = ?"
                + ("" if scope is None else " AND account_id = ? AND channel = ?"),
                (priority, duplicate["id"], *scope_params),
            )
            await write_audit(
                db, scope, source=source, actor=actor, request_text=title,
                accepted=True, reason="priority_boosted", queue_item_id=duplicate["id"],
                event_id=event_id,
            )
            await db.commit()
            return {"ok": True, "id": duplicate["id"], "title": title, "reason": "priority_boosted"}
        if duplicate:
            await write_audit(
                db, scope, source=source, actor=actor, request_text=title,
                accepted=False, reason="duplicate_request", event_id=event_id,
            )
            await db.commit()
            return {"error": "duplicate_request"}
        cursor = await db.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE {where}status = 'queued'",
            scope_params,
        )
        row = await cursor.fetchone()
        if row and row["n"] >= int(settings.get("max_queue", 50)):
            await write_audit(
                db, scope, source=source, actor=actor, request_text=title,
                accepted=False, reason="queue_full", event_id=event_id,
            )
            await db.commit()
            return {"error": "queue_full"}
        if scope is None:
            cursor = await db.execute(
                "SELECT id FROM sr_priority_users WHERE username = ?",
                (actor.lower(),),
            )
            if await cursor.fetchone():
                priority = max(priority, 2)
        if scope is None:
            cursor = await db.execute(
                "INSERT INTO song_request_queue (title, requested_by, channel, priority) "
                "VALUES (?, ?, ?, ?)",
                (title, actor, channel[:50], priority),
            )
        else:
            cursor = await db.execute(
                "INSERT INTO widget_song_request_queue_scoped "
                "(account_id, channel, title, requested_by, priority) VALUES (?, ?, ?, ?, ?)",
                (*scope, title, actor, priority),
            )
        new_id = cursor.lastrowid
        playing = await _get_sr_now_playing(scope)
        if not playing:
            await db.execute(
                f"UPDATE {'song_request_queue' if scope is None else 'widget_song_request_queue_scoped'} "
                "SET status = 'playing' WHERE id = ?",
                (new_id,),
            )
        await write_audit(
            db, scope, source=source, actor=actor, request_text=title,
            accepted=True, reason="accepted", queue_item_id=new_id, event_id=event_id,
        )
        await db.commit()
        _sr_user_last[(scope, actor.lower())] = _time.time()
        return {"ok": True, "id": new_id, "title": title}
    finally:
        await db.close()


@public_router.get("/widget/song-request", response_class=HTMLResponse)
async def widget_sr_page() -> HTMLResponse:
    return HTMLResponse(_widget_html("song-request"))


# ====================================================================
# YouTube Auto-Play Integration for Song Request (v10.5.1)
# ====================================================================
#
# При включённой настройке youtube_autoplay бот ищет песню на YouTube
# и возвращает video_id для встроенного плеера. Поддерживает:
# 1. YouTube Data API v3 (если есть YOUTUBE_API_KEY)
# 2. Fallback через invidious/piped (без ключа)


async def _youtube_search(query: str, api_key: str = "") -> str | None:
    """Ищет видео на YouTube, возвращает video_id или None."""
    if not query:
        return None

    # Сначала пробуем через YouTube Data API v3
    if api_key:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://www.googleapis.com/youtube/v3/search",
                    params={
                        "part": "snippet",
                        "q": query,
                        "type": "video",
                        "maxResults": 1,
                        "key": api_key,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("items", [])
                    if items:
                        return items[0]["id"]["videoId"]
        except Exception as exc:
            logger.warning("YouTube API search failed: %s", exc)

    # Fallback: через Piped API (бесплатный фронтенд YouTube, без ключей)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://pipedapi.kavin.rocks/search",
                params={"q": query, "filter": "videos"},
            )
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("items", [])
                if items:
                    url = items[0].get("url", "")
                    # url format: /watch?v=VIDEO_ID
                    if "v=" in url:
                        return url.split("v=")[-1].split("&")[0]
    except Exception as exc:
        logger.warning("Piped API search failed: %s", exc)

    return None


@admin_router.get("/api/widgets/song-request/youtube-search")
async def sr_youtube_search(q: str) -> dict:
    """Поиск видео на YouTube по названию песни."""
    import os

    api_key = os.getenv("YOUTUBE_API_KEY", "")
    video_id = await _youtube_search(q, api_key)
    if video_id:
        return {
            "ok": True,
            "video_id": video_id,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "embed_url": f"https://www.youtube.com/embed/{video_id}?autoplay=1&enablejsapi=1",
        }
    return {"ok": False, "error": "not_found"}


@admin_router.post("/api/widgets/song-request/youtube-settings")
async def sr_youtube_settings_save(payload: dict) -> dict:
    """Сохранить настройки YouTube авто-воспроизведения."""
    import os

    # Сохраняем в .env
    key = (payload.get("youtube_api_key") or "").strip()
    autoplay = payload.get("youtube_autoplay", False)

    # Запоминаем в переменных окружения runtime
    if key:
        os.environ["YOUTUBE_API_KEY"] = key
    os.environ["SR_YOUTUBE_AUTOPLAY"] = "1" if autoplay else "0"

    return {"ok": True, "youtube_autoplay": autoplay, "has_key": bool(key)}


@admin_router.get("/api/widgets/song-request/youtube-settings")
async def sr_youtube_settings_get() -> dict:
    """Получить текущие настройки YouTube."""
    import os

    key = os.getenv("YOUTUBE_API_KEY", "")
    autoplay = os.getenv("SR_YOUTUBE_AUTOPLAY", "0") == "1"
    return {"ok": True, "youtube_autoplay": autoplay, "has_key": bool(key)}


# ====================================================================
# Widget #16: Top Donator Leaderboard (v10.6)
# ====================================================================
#
# Один виджет показывает ТОП-5 донатеров за выбранный период: all-time, месяц,
# день (Wave 3, owner survey Q15-17 — раньше это были три отдельных виджета).
# Стример может добавлять донаты вручную из панели, или бот вызывает
# on_donation_event() из EventSub/webhook.

_TOP_DONATOR_PERIODS = ("alltime", "month", "day")
_TOP_DONATOR_TITLE_DEFAULTS = {
    "alltime": "Top Donator (All Time)",
    "month": "Top Donator (Month)",
    "day": "Top Donator (Day)",
}


def _top_donator_scope_key(scope: tuple[int, str] | None) -> str:
    return "legacy" if scope is None else f"{scope[0]}:{scope[1]}"


def _invalidate_top_donator_cache(scope: tuple[int, str] | None = None) -> None:
    if scope is None:
        for key in tuple(_cache):
            if key.startswith("public:top-donator:"):
                _cache.pop(key, None)
        return
    scope_key = _top_donator_scope_key(scope)
    _cache_invalidate(*(f"public:top-donator:{scope_key}:{p}" for p in _TOP_DONATOR_PERIODS))


async def _get_top_donator_settings() -> dict:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, theme, show_amount, title_alltime, title_month, "
            "title_day, updated_at FROM top_donator_settings WHERE id = 1"
        )
        row = await cursor.fetchone()
        return dict(row) if row else {
            "id": 1, "theme": "neon", "show_amount": 1,
            "title_alltime": "Top Donator (All Time)",
            "title_month": "Top Donator (Month)",
            "title_day": "Top Donator (Day)",
            "updated_at": "",
        }
    finally:
        await db.close()


async def _get_top_donors(
    period: str, limit: int = 5, scope: tuple[int, str] | None = None,
) -> list[dict]:
    """Return top donors aggregated by username for a given period."""
    valid_periods = ("alltime", "month", "day")
    if period not in valid_periods:
        return []
    db = await get_db()
    try:
        clauses = ["account_id IS NULL AND channel IS NULL"] if scope is None else [
            "account_id = ? AND channel = ?"
        ]
        params: list[Any] = [] if scope is None else [*scope]
        if period == "month":
            clauses.append("created_at >= date('now', 'start of month')")
        elif period == "day":
            clauses.append("created_at >= date('now')")
        where = "WHERE " + " AND ".join(clauses)
        cursor = await db.execute(
            f"SELECT username, SUM(amount) AS total, "
            f"MAX(created_at) AS last_donation_at "
            f"FROM donations {where} "
            f"GROUP BY username ORDER BY total DESC LIMIT ?",
            (*params, limit),
        )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


async def on_donation_event(
    username: str, amount: float, currency: str = "USD", message: str = "",
    *, account_id: int | None = None, channel: str | None = None,
) -> dict:
    """Insert a donation record. Called from EventSub or external webhook."""
    scope = await _verified_widget_state_scope(account_id, channel)
    db = await get_db()
    try:
        if scope is None:
            cursor = await db.execute(
                "INSERT INTO donations (username, amount, currency, message) "
                "VALUES (?, ?, ?, ?)",
                (username[:100], float(amount), currency[:10], message[:500]),
            )
        else:
            cursor = await db.execute(
                "INSERT INTO donations "
                "(account_id, channel, username, amount, currency, message) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (*scope, username[:100], float(amount), currency[:10], message[:500]),
            )
        await db.commit()
        _invalidate_top_donator_cache(scope)
        donation_id = cursor.lastrowid
    finally:
        await db.close()

    # Update active donation challenges
    try:
        db2 = await get_db()
        try:
            # Use atomic increment to avoid race conditions with concurrent donations
            where, scope_params = _donation_challenge_where(scope)
            await db2.execute(
                "UPDATE donation_challenges SET current_amount = current_amount + ?, "
                "completed = CASE WHEN current_amount + ? >= target_amount THEN 1 ELSE 0 END, "
                "completed_at = CASE WHEN current_amount + ? >= target_amount THEN CURRENT_TIMESTAMP ELSE completed_at END "
                f"WHERE {where} AND active = 1 AND completed = 0",
                (float(amount), float(amount), float(amount), *scope_params),
            )
            await db2.commit()
        finally:
            await db2.close()
    except Exception as exc:
        logger.warning("donation challenge update error: %s", exc)

    # §9.3: subathon продлевается за донат. Решение владельца 31.08: если
    # задан seconds_per_currency > 0 — время = amount × тариф (за единицу
    # валюты,DonatePay/DonateX/DonationAlerts/webhook все проходят здесь),
    # иначе плоский seconds_per_donation за донат.
    try:
        db3 = await get_db()
        try:
            if scope is None:
                c3 = await db3.execute(
                    "SELECT seconds_per_donation, seconds_per_currency "
                    "FROM subathon_timer WHERE id = 1"
                )
            else:
                await db3.execute(
                    "INSERT OR IGNORE INTO subathon_timer_scoped "
                    "(account_id, channel) VALUES (?, ?)", scope,
                )
                c3 = await db3.execute(
                    "SELECT seconds_per_donation, seconds_per_currency "
                    "FROM subathon_timer_scoped WHERE account_id = ? AND channel = ?", scope,
                )
            r3 = await c3.fetchone()
        finally:
            await db3.close()
        if r3:
            rate = float(r3["seconds_per_currency"] or 0)
            if rate > 0:
                await subathon_extend(max(1, int(float(amount) * rate)), scope)
            elif r3["seconds_per_donation"]:
                await subathon_extend(int(r3["seconds_per_donation"]), scope)
    except Exception as exc:
        logger.debug("subathon extend (donation) failed: %s", exc)

    return {"ok": True, "id": donation_id}


async def on_donation_received(
    platform: str, username: str, amount: float,
    currency: str = "USD", message: str = "",
    *, account_id: int | None = None, channel: str | None = None,
) -> dict:
    """PLAN_FEEDBACK_2908 §3: единая точка приёма доната из ЛЮБОЙ платформы.

    Вызывается из DonatePay polling, DonateX polling, DonationAlerts WS и
    универсального webhook (см. donation_integrations._process_donation).
    Внутри: запись доната (топ донатеров), активные челленджи (дельта,
    локальные донаты не затираются), subathon, recent-events.
    """
    result = await on_donation_event(
        username, amount, currency, message, account_id=account_id, channel=channel,
    )
    try:
        await on_stream_event(
            "donation", username, int(amount), account_id=account_id, channel=channel,
        )
    except Exception as exc:
        logger.warning("recent-events (donation) failed: %s", exc)
    result["platform"] = platform
    return result


# --- Admin endpoints ---


@admin_router.get("/api/widgets/top-donators")
async def top_donators_get(
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    settings = await _get_top_donator_settings()
    db = await get_db()
    try:
        if scope is None:
            cursor = await db.execute(
                "SELECT id, username, amount, currency, message, created_at "
                "FROM donations WHERE account_id IS NULL AND channel IS NULL "
                "ORDER BY created_at DESC LIMIT 50"
            )
        else:
            cursor = await db.execute(
                "SELECT id, username, amount, currency, message, created_at "
                "FROM donations WHERE account_id = ? AND channel = ? "
                "ORDER BY created_at DESC LIMIT 50", scope,
            )
        recent = [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()
    alltime = await _get_top_donors("alltime", scope=scope)
    month = await _get_top_donors("month", scope=scope)
    day = await _get_top_donors("day", scope=scope)
    return {
        **settings,
        "recent_donations": recent,
        "top_alltime": alltime,
        "top_month": month,
        "top_day": day,
    }


@admin_router.put("/api/widgets/top-donators")
async def top_donators_put(payload: dict) -> dict:
    db = await get_db()
    try:
        fields: list[str] = []
        values: list[Any] = []
        if "theme" in payload:
            t = str(payload["theme"]).strip()
            if t in ("neon", "glass", "fire", "minimal"):
                fields.append("theme = ?")
                values.append(t)
        if "show_amount" in payload:
            fields.append("show_amount = ?")
            values.append(1 if payload["show_amount"] else 0)
        if "title_alltime" in payload:
            fields.append("title_alltime = ?")
            values.append(str(payload["title_alltime"])[:200])
        if "title_month" in payload:
            fields.append("title_month = ?")
            values.append(str(payload["title_month"])[:200])
        if "title_day" in payload:
            fields.append("title_day = ?")
            values.append(str(payload["title_day"])[:200])
        if not fields:
            return {"ok": False, "error": "nothing_to_update"}
        fields.append("updated_at = CURRENT_TIMESTAMP")
        values.append(1)
        await db.execute(
            f"UPDATE top_donator_settings SET {', '.join(fields)} WHERE id = ?",
            tuple(values),
        )
        await db.commit()
    finally:
        await db.close()
    # Заголовок/тема/show_amount входят в кэшируемый ответ виджета — без сброса
    # кэша правка настроек не была бы видна в OBS до истечения TTL.
    _invalidate_top_donator_cache()
    return {"ok": True, **(await _get_top_donator_settings())}


@admin_router.post("/api/widgets/top-donators/add")
async def top_donators_add(
    payload: dict, account_id: int | None = None, channel: str | None = None,
) -> dict:
    username = str(payload.get("username", "")).strip()
    if not username:
        return {"error": "username_required"}
    try:
        amount = float(payload.get("amount", 0))
    except (TypeError, ValueError):
        return {"error": "invalid_amount"}
    if amount <= 0:
        return {"error": "invalid_amount"}
    currency = str(payload.get("currency", "USD")).strip()[:10] or "USD"
    message = str(payload.get("message", "")).strip()[:500]
    result = await on_donation_event(
        username, amount, currency, message, account_id=account_id, channel=channel,
    )
    return result


@admin_router.delete("/api/widgets/top-donators/{donation_id}")
async def top_donators_delete(
    donation_id: int, account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    db = await get_db()
    try:
        if scope is None:
            await db.execute(
                "DELETE FROM donations WHERE id = ? AND account_id IS NULL AND channel IS NULL",
                (donation_id,),
            )
        else:
            await db.execute(
                "DELETE FROM donations WHERE id = ? AND account_id = ? AND channel = ?",
                (donation_id, *scope),
            )
        await db.commit()
        _invalidate_top_donator_cache(scope)
    finally:
        await db.close()
    return {"ok": True}


# --- Public endpoints ---
#
# Wave 3 (owner survey Q15-17: М): три периода обслуживает одна реализация с
# явным параметром period. Три исторических URL сохранены как тонкие обёртки —
# у владельца они уже стоят в OBS-сценах.


async def _top_donator_payload(period: str, scope: tuple[int, str] | None = None) -> dict:
    """Данные виджета за период (alltime|month|day) — единая реализация."""
    cache_key = f"public:top-donator:{_top_donator_scope_key(scope)}:{period}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    settings = await _get_top_donator_settings()
    result = {
        "period": period,
        "donors": await _get_top_donors(period, scope=scope),
        "title": settings.get(f"title_{period}", _TOP_DONATOR_TITLE_DEFAULTS[period]),
        "theme": settings.get("theme", "neon"),
        "show_amount": bool(settings.get("show_amount", 1)),
    }
    _cache_set(cache_key, result, _CACHE_TTL_SLOW)
    return result


@public_router.get("/api/widgets/public/top-donator/{period}")
async def top_donator_public(
    period: str, account_id: int | None = None, channel: str | None = None,
) -> dict:
    if period not in _TOP_DONATOR_PERIODS:
        return {"error": "bad_period", "allowed": list(_TOP_DONATOR_PERIODS)}
    return await _top_donator_payload(
        period, await _verified_widget_state_scope(account_id, channel),
    )


# --- Widget HTML pages ---


def _top_donator_html(period: str, theme: str) -> HTMLResponse:
    safe_theme = theme if theme in ("neon", "glass", "fire", "minimal") else ""
    html = (_widget_html("top-donator")
            .replace("__PERIOD__", period)
            .replace("__THEME__", safe_theme))
    return HTMLResponse(html)


@public_router.get("/widget/top-donator", response_class=HTMLResponse)
async def widget_top_donator_page(period: str = "alltime", theme: str = "") -> HTMLResponse:
    """Единый top-donator с выбором периода (owner survey Q15-17: М).

    ``period`` — alltime|month|day (невалидное значение → alltime).
    Три исторических URL ниже сохранены как обёртки над этим роутом.
    """
    safe_period = period if period in _TOP_DONATOR_PERIODS else "alltime"
    return _top_donator_html(safe_period, theme)


@public_router.get("/widget/top-donator-alltime", response_class=HTMLResponse)
async def widget_top_donator_alltime_page(theme: str = "") -> HTMLResponse:
    """Исторический URL — сохранён ради уже настроенных OBS-сцен."""
    return _top_donator_html("alltime", theme)


@public_router.get("/widget/top-donator-month", response_class=HTMLResponse)
async def widget_top_donator_month_page(theme: str = "") -> HTMLResponse:
    """Исторический URL — сохранён ради уже настроенных OBS-сцен."""
    return _top_donator_html("month", theme)


@public_router.get("/widget/top-donator-day", response_class=HTMLResponse)
async def widget_top_donator_day_page(theme: str = "") -> HTMLResponse:
    """Исторический URL — сохранён ради уже настроенных OBS-сцен."""
    return _top_donator_html("day", theme)


# ====================================================================
# v10.7: Countdown / Timer Widget
# ====================================================================


async def _get_countdown_state(scope: tuple[int, str] | None = None) -> dict:
    db = await get_db()
    try:
        if scope is None:
            cursor = await db.execute("SELECT * FROM countdown_timer WHERE id = 1")
        else:
            cursor = await db.execute(
                "SELECT * FROM widget_countdown_scoped "
                "WHERE account_id = ? AND channel = ?", scope,
            )
        row = await cursor.fetchone()
        if not row:
            return {
                "mode": "countdown",
                "duration_sec": 300,
                "remaining_sec": 300,
                "state": "stopped",
                "theme": "neon",
                "title": "",
                "started_at": None,
            }
        return {
            "mode": row["mode"] or "countdown",
            "duration_sec": row["duration_sec"] or 300,
            "remaining_sec": row["remaining_sec"] or 300,
            "state": row["state"] or "stopped",
            "theme": row["theme"] or "neon",
            "title": row["title"] or "",
            "started_at": row["started_at"],
        }
    finally:
        await db.close()


@admin_router.get("/api/widgets/countdown")
async def countdown_get(
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    return await _get_countdown_state(await _verified_widget_state_scope(account_id, channel))


@admin_router.put("/api/widgets/countdown")
async def countdown_put(
    payload: dict, account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    db = await get_db()
    try:
        fields: list[str] = []
        values: list[Any] = []
        if "mode" in payload:
            m = str(payload["mode"]).strip()
            if m in ("countdown", "stopwatch"):
                fields.append("mode = ?")
                values.append(m)
        if "duration_sec" in payload:
            d = int(payload["duration_sec"])
            if 1 <= d <= 86400:
                fields.append("duration_sec = ?")
                values.append(d)
                fields.append("remaining_sec = ?")
                values.append(d)
        if "title" in payload:
            fields.append("title = ?")
            values.append(str(payload["title"])[:200])
        if "theme" in payload:
            t = str(payload["theme"]).strip()
            if t in ("neon", "glass", "fire", "minimal"):
                fields.append("theme = ?")
                values.append(t)
        if not fields:
            return {"ok": False, "error": "nothing_to_update"}
        fields.append("updated_at = CURRENT_TIMESTAMP")
        if scope is None:
            values.append(1)
            sql = f"UPDATE countdown_timer SET {', '.join(fields)} WHERE id = ?"
        else:
            await db.execute(
                "INSERT OR IGNORE INTO widget_countdown_scoped "
                "(account_id, channel) VALUES (?, ?)", scope,
            )
            values.extend(scope)
            sql = (
                f"UPDATE widget_countdown_scoped SET {', '.join(fields)} "
                "WHERE account_id = ? AND channel = ?"
            )
        await db.execute(sql, values)
        await db.commit()
    finally:
        await db.close()
    return {"ok": True, **(await _get_countdown_state(scope))}


@admin_router.post("/api/widgets/countdown/start")
async def countdown_start(
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    db = await get_db()
    try:
        if scope is None:
            await db.execute(
                "UPDATE countdown_timer SET state = 'running', "
                "started_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = 1"
            )
        else:
            await db.execute(
                "INSERT OR IGNORE INTO widget_countdown_scoped "
                "(account_id, channel) VALUES (?, ?)", scope,
            )
            await db.execute(
                "UPDATE widget_countdown_scoped SET state = 'running', "
                "started_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP "
                "WHERE account_id = ? AND channel = ?", scope,
            )
        await db.commit()
    finally:
        await db.close()
    return {"ok": True, **(await _get_countdown_state(scope))}


@admin_router.post("/api/widgets/countdown/stop")
async def countdown_stop(
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    """Stop the timer. Snapshot remaining seconds based on elapsed time."""
    scope = await _verified_widget_state_scope(account_id, channel)
    db = await get_db()
    try:
        if scope is None:
            table = "countdown_timer"
            where_sql = "id = ?"
            where_params = (1,)
        else:
            table = "widget_countdown_scoped"
            where_sql = "account_id = ? AND channel = ?"
            where_params = scope
            await db.execute(
                "INSERT OR IGNORE INTO widget_countdown_scoped "
                "(account_id, channel) VALUES (?, ?)", scope,
            )
        cursor = await db.execute(
            "SELECT mode, duration_sec, remaining_sec, state, started_at "
            f"FROM {table} WHERE {where_sql}", where_params,
        )
        row = await cursor.fetchone()
        if row and row["state"] == "running" and row["started_at"]:
            # Compute elapsed
            try:
                from datetime import datetime, timezone
                started = datetime.fromisoformat(str(row["started_at"])).replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                elapsed = int((now - started).total_seconds())
            except Exception:
                elapsed = 0
            if row["mode"] == "countdown":
                remaining = max(0, (row["remaining_sec"] or 0) - elapsed)
            else:
                remaining = (row["remaining_sec"] or 0) + elapsed
            await db.execute(
                f"UPDATE {table} SET state = 'stopped', remaining_sec = ?, "
                f"started_at = NULL, updated_at = CURRENT_TIMESTAMP WHERE {where_sql}",
                (remaining, *where_params),
            )
        else:
            await db.execute(
                f"UPDATE {table} SET state = 'stopped', "
                f"started_at = NULL, updated_at = CURRENT_TIMESTAMP WHERE {where_sql}",
                where_params,
            )
        await db.commit()
    finally:
        await db.close()
    return {"ok": True, **(await _get_countdown_state(scope))}


@admin_router.post("/api/widgets/countdown/reset")
async def countdown_reset(
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    db = await get_db()
    try:
        if scope is None:
            await db.execute(
                "UPDATE countdown_timer SET state = 'stopped', "
                "remaining_sec = duration_sec, started_at = NULL, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = 1"
            )
        else:
            await db.execute(
                "INSERT OR IGNORE INTO widget_countdown_scoped "
                "(account_id, channel) VALUES (?, ?)", scope,
            )
            await db.execute(
                "UPDATE widget_countdown_scoped SET state = 'stopped', "
                "remaining_sec = duration_sec, started_at = NULL, "
                "updated_at = CURRENT_TIMESTAMP WHERE account_id = ? AND channel = ?", scope,
            )
        await db.commit()
    finally:
        await db.close()
    return {"ok": True, **(await _get_countdown_state(scope))}


async def countdown_add_time(
    seconds: int = 300, account_id: int | None = None, channel: str | None = None,
) -> dict:
    """Adjust countdown duration and remaining time without changing run state."""
    delta = max(-86400, min(86400, int(seconds)))
    scope = await _verified_widget_state_scope(account_id, channel)
    db = await get_db()
    try:
        if scope is None:
            await db.execute(
                "UPDATE countdown_timer SET duration_sec = MAX(0, duration_sec + ?), "
                "remaining_sec = MAX(0, remaining_sec + ?), updated_at = CURRENT_TIMESTAMP "
                "WHERE id = 1", (delta, delta),
            )
        else:
            await db.execute(
                "INSERT OR IGNORE INTO widget_countdown_scoped "
                "(account_id, channel) VALUES (?, ?)", scope,
            )
            await db.execute(
                "UPDATE widget_countdown_scoped SET duration_sec = MAX(0, duration_sec + ?), "
                "remaining_sec = MAX(0, remaining_sec + ?), updated_at = CURRENT_TIMESTAMP "
                "WHERE account_id = ? AND channel = ?", (delta, delta, *scope),
            )
        await db.commit()
    finally:
        await db.close()
    return {"ok": True, **(await _get_countdown_state(scope))}


@public_router.get("/api/widgets/public/countdown")
async def countdown_public(
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    return await _get_countdown_state(await _verified_widget_state_scope(account_id, channel))


# --- Countdown Widget HTML ---


@public_router.get("/widget/countdown", response_class=HTMLResponse)
async def widget_countdown_page() -> HTMLResponse:
    return HTMLResponse(_widget_html("countdown"))


# ====================================================================
# v10.7: Donation Challenges Widget
# ====================================================================


def _donation_challenge_where(scope: tuple[int, str] | None) -> tuple[str, tuple[Any, ...]]:
    if scope is None:
        return "account_id IS NULL AND channel IS NULL", ()
    return "account_id = ? AND channel = ?", scope


@admin_router.get("/api/widgets/donation-challenges")
async def donation_challenges_list(
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    where, params = _donation_challenge_where(scope)
    db = await get_db()
    try:
        cursor = await db.execute(
            f"SELECT * FROM donation_challenges WHERE {where} ORDER BY created_at DESC",
            params,
        )
        rows = [dict(r) for r in await cursor.fetchall()]
        return {"challenges": rows}
    finally:
        await db.close()


@admin_router.post("/api/widgets/donation-challenges")
async def donation_challenges_create(payload: dict) -> dict:
    scope = await _verified_widget_state_scope(
        payload.get("account_id"), payload.get("channel"),
    )
    title = str(payload.get("title", "")).strip()
    if not title:
        return {"ok": False, "error": "title_required"}
    target = float(payload.get("target_amount", 0))
    if target <= 0:
        return {"ok": False, "error": "invalid_target_amount"}
    reward_text = str(payload.get("reward_text", ""))[:500]
    description = str(payload.get("description", ""))[:500]
    theme = str(payload.get("theme", "neon")).strip()
    if theme not in ("neon", "glass", "fire", "minimal"):
        theme = "neon"
    currency = str(payload.get("currency", "USD"))[:10]
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO donation_challenges "
            "(account_id, channel, title, description, target_amount, currency, reward_text, theme) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ((scope[0] if scope else None), (scope[1] if scope else None),
             title[:200], description, target, currency, reward_text, theme),
        )
        await db.commit()
        return {"ok": True, "id": cursor.lastrowid}
    finally:
        await db.close()


@admin_router.put("/api/widgets/donation-challenges/{challenge_id}")
async def donation_challenges_update(
    challenge_id: int, payload: dict,
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    where, scope_params = _donation_challenge_where(scope)
    db = await get_db()
    try:
        fields: list[str] = []
        values: list[Any] = []
        if "title" in payload:
            fields.append("title = ?")
            values.append(str(payload["title"])[:200])
        if "description" in payload:
            fields.append("description = ?")
            values.append(str(payload["description"])[:500])
        if "target_amount" in payload:
            t = float(payload["target_amount"])
            if t > 0:
                fields.append("target_amount = ?")
                values.append(t)
        if "reward_text" in payload:
            fields.append("reward_text = ?")
            values.append(str(payload["reward_text"])[:500])
        if "theme" in payload:
            t = str(payload["theme"]).strip()
            if t in ("neon", "glass", "fire", "minimal"):
                fields.append("theme = ?")
                values.append(t)
        if "active" in payload:
            fields.append("active = ?")
            values.append(1 if payload["active"] else 0)
        if not fields:
            return {"ok": False, "error": "nothing_to_update"}
        values.extend((challenge_id, *scope_params))
        sql = f"UPDATE donation_challenges SET {', '.join(fields)} WHERE id = ? AND {where}"
        cursor = await db.execute(sql, values)
        await db.commit()
    finally:
        await db.close()
    return {"ok": cursor.rowcount > 0, **({} if cursor.rowcount > 0 else {"error": "not_found"})}


@admin_router.delete("/api/widgets/donation-challenges/{challenge_id}")
async def donation_challenges_delete(
    challenge_id: int, account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    where, params = _donation_challenge_where(scope)
    db = await get_db()
    try:
        cursor = await db.execute(
            f"DELETE FROM donation_challenges WHERE id = ? AND {where}",
            (challenge_id, *params),
        )
        await db.commit()
    finally:
        await db.close()
    return {"ok": cursor.rowcount > 0, **({} if cursor.rowcount > 0 else {"error": "not_found"})}


@admin_router.post("/api/widgets/donation-challenges/{challenge_id}/add-funds")
async def donation_challenges_add_funds(
    challenge_id: int, payload: dict,
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    where, scope_params = _donation_challenge_where(scope)
    amount = float(payload.get("amount", 0))
    if amount <= 0:
        return {"ok": False, "error": "invalid_amount"}
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, target_amount, current_amount, completed "
            f"FROM donation_challenges WHERE id = ? AND {where}",
            (challenge_id, *scope_params),
        )
        row = await cursor.fetchone()
        if not row:
            return {"ok": False, "error": "not_found"}
        new_amount = (row["current_amount"] or 0) + amount
        completed = 1 if new_amount >= row["target_amount"] else (row["completed"] or 0)
        if completed and not row["completed"]:
            await db.execute(
                "UPDATE donation_challenges SET current_amount = ?, completed = 1, "
                "completed_at = CURRENT_TIMESTAMP WHERE id = ?",
                (new_amount, challenge_id),
            )
        else:
            await db.execute(
                "UPDATE donation_challenges SET current_amount = ? WHERE id = ?",
                (new_amount, challenge_id),
            )
        await db.commit()
        return {"ok": True, "current_amount": new_amount, "completed": bool(completed)}
    finally:
        await db.close()


@public_router.get("/api/widgets/public/donation-challenge/active")
async def donation_challenge_active(
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    where, params = _donation_challenge_where(scope)
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM donation_challenges "
            f"WHERE {where} AND active = 1 AND completed = 0 "
            "ORDER BY created_at ASC LIMIT 1",
            params,
        )
        row = await cursor.fetchone()
        if not row:
            return {"active": False}
        d = dict(row)
        d["active"] = True
        d["progress_pct"] = min(100.0, round(
            (d["current_amount"] / d["target_amount"]) * 100, 1
        )) if d["target_amount"] > 0 else 0
        return d
    finally:
        await db.close()


# --- Donation Challenge Widget HTML ---


@public_router.get("/widget/donation-challenge", response_class=HTMLResponse)
async def widget_donation_challenge_page() -> HTMLResponse:
    return HTMLResponse(_widget_html("donation-challenge"))


# ====================================================================
# v10.8: Latest Event Card widget
# ====================================================================


@public_router.get("/api/widgets/public/latest-event")
async def latest_event_public(
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    """Проекция «одна карточка»: последнее событие с учётом filter_kind.

    Читает ту же event-модель, что и лента recent-events (Wave 4).
    """
    settings = await _get_latest_event_card_settings()
    events = await _read_recent_events(
        1,
        kind=settings.get("filter_kind") or "",
        scope=await _verified_widget_state_scope(account_id, channel),
    )
    return {"event": events[0] if events else None}


async def _get_latest_event_card_settings() -> dict:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT theme, filter_kind, updated_at "
            "FROM latest_event_card_settings WHERE id = 1"
        )
        row = await cursor.fetchone()
        if row:
            return dict(row)
        return {"theme": "neon", "filter_kind": "", "updated_at": None}
    finally:
        await db.close()


@admin_router.get("/api/widgets/latest-event-card")
async def latest_event_card_get() -> dict:
    return await _get_latest_event_card_settings()


@admin_router.put("/api/widgets/latest-event-card")
async def latest_event_card_put(payload: dict) -> dict:
    db = await get_db()
    try:
        fields: list[str] = []
        values: list[Any] = []
        if "theme" in payload:
            t = str(payload["theme"]).strip()
            if t in ("neon", "glass", "rainbow", "minimal"):
                fields.append("theme = ?")
                values.append(t)
        if "filter_kind" in payload:
            fk = str(payload["filter_kind"]).strip()
            if fk in ("", "follow", "subscribe", "cheer", "raid"):
                fields.append("filter_kind = ?")
                values.append(fk)
        if not fields:
            return {"ok": False, "error": "nothing_to_update"}
        fields.append("updated_at = CURRENT_TIMESTAMP")
        values.append(1)
        sql = f"UPDATE latest_event_card_settings SET {', '.join(fields)} WHERE id = ?"
        await db.execute(sql, values)
        await db.commit()
    finally:
        await db.close()
    return {"ok": True, **(await _get_latest_event_card_settings())}


@public_router.get("/widget/clip-moments", response_class=HTMLResponse)
async def widget_clip_moments_page() -> HTMLResponse:
    """§9.3: OBS-виджет последних моментов клипов (?account=<id>)."""
    return HTMLResponse(_widget_html("clip-moments"))


@public_router.get("/widget/voice-changer", response_class=HTMLResponse)
async def widget_voice_changer_page() -> HTMLResponse:
    """Выведен из эксплуатации (owner survey Q4): voice-pipeline не используется.

    URL сохранён ради уже настроенных OBS-сцен — отдаёт тёмную заглушку.
    """
    return HTMLResponse(_retired_widget_html("/widget/voice-changer"))


@public_router.get("/widget/latest-event-card", response_class=HTMLResponse)
async def widget_latest_event_card_page() -> HTMLResponse:
    return HTMLResponse(_widget_html("latest-event-card"))


# ====================================================================
# v13 §2 WIDGETS_PLAN: TTS-бот "Golden Voice"
# ====================================================================
#
# Цей віджет — "правильний" оверлей для відповідей TTS-двигуна бота
# (на відміну від /obs/tts, який читає сирий чат браузерним Web Speech).
#
# URL-параметри:
#   account_id=<id>      — фільтрувати події TTS лише для конкретного бота.
#   color=<#hex>         — акцент-колір (default gold #FFD700, або з tts_bot_config).
#   emoji=<symbol>       — іконка біля імені (default 🎙️, або з tts_bot_config).


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    """Конвертує #rrggbb у rgba(r,g,b,a). При невалідному hex повертає gold."""
    try:
        h = hex_color.lstrip("#")
        if len(h) != 6:
            raise ValueError
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
        return f"rgba({r},{g},{b},{alpha})"
    except Exception:
        return f"rgba(255,215,0,{alpha})"


def _normalize_hex(hex_color: str, default: str = "#FFD700") -> str:
    """Нормалізує колір до #rrggbb (або повертає default)."""
    if not hex_color:
        return default
    h = hex_color.strip().lstrip("#")
    if len(h) != 6:
        return default
    try:
        int(h, 16)
    except ValueError:
        return default
    return f"#{h.upper()}"


_WIDGET_DESIGN_DEFAULTS: dict[str, dict[str, Any]] = {
    "chat-reader": {
        "theme": "dark", "accent": "#22D3EE", "bg": "#0F0F19",
        "opacity": 0.9, "radius": 14, "font": "sans", "size": 20,
        "scale": 1.0, "pos": "bc", "shadow": 1, "hold": 8, "maxw": 640,
    },
    "tts-raw": {
        "theme": "dark", "accent": "#00FF7F", "bg": "#000000",
        "opacity": 0.65, "radius": 6, "font": "sans", "size": 13,
        "scale": 1.0, "pos": "bl", "shadow": 0, "showstatus": 1,
    },
}
_WIDGET_THEME_COLORS = {
    "light": ("#2563EB", "#F8FAFC"),
    "neon": ("#D946EF", "#090014"),
    "fire": ("#FF6B35", "#1A0800"),
    "glass": ("#67E8F9", "#111827"),
    "mono": ("#FFFFFF", "#111111"),
}
_WIDGET_FONTS = {
    "sans": "'Segoe UI',system-ui,sans-serif",
    "serif": "Georgia,'Times New Roman',serif",
    "mono": "'Cascadia Mono','Courier New',monospace",
    "condensed": "'Arial Narrow','Roboto Condensed',sans-serif",
}
_WIDGET_POSITIONS = {"bl", "bc", "br", "tl", "tc", "tr"}


def _widget_theme_colors(widget: str, theme: str) -> tuple[str, str] | None:
    if theme == "dark":
        defaults = _WIDGET_DESIGN_DEFAULTS[widget]
        return defaults["accent"], defaults["bg"]
    return _WIDGET_THEME_COLORS.get(theme)


def _design_number(value: Any, default: float, low: float, high: float) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return default


def _design_bool(value: Any, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, str):
        return 0 if value.strip().lower() in {"0", "false", "off", "no"} else 1
    return 1 if value else 0


def _normalize_widget_design(widget: str, values: dict[str, Any]) -> dict[str, Any]:
    defaults = _WIDGET_DESIGN_DEFAULTS[widget]
    theme = str(values.get("theme") or defaults["theme"]).lower()
    if theme not in {"dark", *_WIDGET_THEME_COLORS}:
        theme = defaults["theme"]
    font = str(values.get("font") or defaults["font"]).lower()
    if font not in _WIDGET_FONTS:
        font = defaults["font"]
    pos = str(values.get("pos") or defaults["pos"]).lower()
    if pos not in _WIDGET_POSITIONS:
        pos = defaults["pos"]
    normalized: dict[str, Any] = {
        "theme": theme,
        "accent": _normalize_hex(str(values.get("accent") or ""), defaults["accent"]),
        "bg": _normalize_hex(str(values.get("bg") or ""), defaults["bg"]),
        "opacity": _design_number(values.get("opacity"), defaults["opacity"], 0.0, 1.0),
        "radius": int(_design_number(values.get("radius"), defaults["radius"], 0, 32)),
        "font": font,
        "size": int(_design_number(values.get("size"), defaults["size"], 12, 48)),
        "scale": _design_number(values.get("scale"), defaults["scale"], 0.5, 3.0),
        "pos": pos,
        "shadow": _design_bool(values.get("shadow"), defaults["shadow"]),
    }
    if widget == "chat-reader":
        normalized["hold"] = int(_design_number(values.get("hold"), defaults["hold"], 1, 60))
        normalized["maxw"] = int(_design_number(values.get("maxw"), defaults["maxw"], 240, 1600))
    else:
        normalized["showstatus"] = _design_bool(values.get("showstatus"), defaults["showstatus"])
    return normalized


async def _get_widget_design(widget: str) -> dict[str, Any]:
    if widget not in _WIDGET_DESIGN_DEFAULTS:
        raise HTTPException(status_code=404, detail="unknown widget design")
    stored: dict[str, Any] = {}
    raw = await get_setting(f"widget_design_{widget}", "")
    if raw:
        try:
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                stored = loaded
        except (TypeError, ValueError):
            pass
    return _normalize_widget_design(widget, {**_WIDGET_DESIGN_DEFAULTS[widget], **stored})


async def _resolve_widget_design(widget: str, overrides: dict[str, Any]) -> dict[str, Any]:
    current = await _get_widget_design(widget)
    supplied = {key: value for key, value in overrides.items() if value is not None}
    for key in ("opacity", "radius", "size", "scale", "hold", "maxw"):
        if key in supplied:
            try:
                float(supplied[key])
            except (TypeError, ValueError):
                supplied.pop(key)
    for key in ("accent", "bg"):
        if key in supplied and not re.fullmatch(r"#[0-9a-fA-F]{6}", str(supplied[key]).strip()):
            supplied.pop(key)
    if supplied.get("theme") not in {"dark", *_WIDGET_THEME_COLORS}:
        supplied.pop("theme", None)
    if supplied.get("font") not in _WIDGET_FONTS:
        supplied.pop("font", None)
    if supplied.get("pos") not in _WIDGET_POSITIONS:
        supplied.pop("pos", None)
    for key in ("shadow", "showstatus"):
        if key in supplied and str(supplied[key]).strip().lower() not in {
            "0", "1", "true", "false", "on", "off", "yes", "no",
        }:
            supplied.pop(key)
    requested_theme = str(supplied.get("theme") or "").lower()
    theme_colors = _widget_theme_colors(widget, requested_theme)
    if theme_colors:
        accent, bg = theme_colors
        current.update({"accent": accent, "bg": bg})
    current.update(supplied)
    return _normalize_widget_design(widget, current)


def _apply_widget_design(html: str, design: dict[str, Any]) -> str:
    accent = design["accent"]
    opacity = float(design["opacity"])
    shadow = "none"
    if design["shadow"]:
        shadow = f"0 0 20px {_hex_to_rgba(accent, 0.2)}"
    replacements = {
        "__DESIGN_ACCENT__": accent,
        "__DESIGN_BG_RGBA__": _hex_to_rgba(design["bg"], opacity),
        "__DESIGN_STATUS_BG_RGBA__": _hex_to_rgba(design["bg"], min(1.0, opacity + 0.05)),
        "__DESIGN_RADIUS__": str(design["radius"]),
        "__DESIGN_FONT__": _WIDGET_FONTS[design["font"]],
        "__DESIGN_SIZE__": str(design["size"]),
        "__DESIGN_SCALE__": str(design["scale"]),
        "__DESIGN_POS__": json.dumps(design["pos"]),
        "__DESIGN_SHADOW__": shadow,
        "__DESIGN_HOLD_MS__": str(int(design.get("hold", 8)) * 1000),
        "__DESIGN_MAXW__": str(design.get("maxw", 640)),
        "__DESIGN_SHOW_STATUS__": "true" if design.get("showstatus", 1) else "false",
    }
    for marker, value in replacements.items():
        html = html.replace(marker, value)
    return html


@admin_router.get("/api/widgets/design/{widget}")
async def widget_design_get(widget: str) -> dict:
    return {"ok": True, "settings": await _get_widget_design(widget)}


@admin_router.put("/api/widgets/design/{widget}")
async def widget_design_put(widget: str, payload: dict) -> dict:
    current = await _get_widget_design(widget)
    requested_theme = str(payload.get("theme") or "").lower()
    theme_colors = _widget_theme_colors(widget, requested_theme)
    if theme_colors and not ({"accent", "bg"} & payload.keys()):
        current["accent"], current["bg"] = theme_colors
    settings = _normalize_widget_design(widget, {**current, **payload})
    await set_setting(f"widget_design_{widget}", json.dumps(settings, ensure_ascii=False))
    return {"ok": True, "settings": settings}


@public_router.get("/widget/tts-bot", response_class=HTMLResponse)
async def widget_tts_bot_page(
    account_id: int | None = None,
    color: str = "",
    emoji: str = "",
) -> HTMLResponse:
    """§2: 'золотий' TTS-оверлей, реагує на type=tts з потрібного account_id."""
    # Якщо нічого не передано в URL — беремо з tts_bot_config для конкретного бота.
    db_color = ""
    db_emoji = ""
    if account_id:
        db = await get_db()
        try:
            cur = await db.execute(
                "SELECT widget_color, widget_emoji FROM tts_bot_config WHERE account_id = ?",
                (account_id,),
            )
            row = await cur.fetchone()
        finally:
            await db.close()
        if row:
            db_color = row["widget_color"] or ""
            db_emoji = row["widget_emoji"] or ""
    accent = _normalize_hex(color or db_color or "#FFD700")
    accent_soft = _hex_to_rgba(accent, 0.18)
    glow = _hex_to_rgba(accent, 0.45)
    icon = (emoji or db_emoji or "🎙️").strip()[:4] or "🎙️"
    safe_account = int(account_id) if account_id else 0
    return HTMLResponse(
        _widget_html("tts-bot")
        .replace("__TTS_ACCENT__", accent)
        .replace("__TTS_ACCENT_SOFT__", accent_soft)
        .replace("__TTS_GLOW__", glow)
        .replace("__TTS_ICON__", icon)
        .replace("__ACCOUNT_ID__", str(safe_account))
    )


@public_router.get("/widget/typing-indicator", response_class=HTMLResponse)
async def widget_typing_indicator_page() -> HTMLResponse:
    """Выведен из эксплуатации (owner survey Q26: Д).

    Вместе с ним убран broadcast typing_indicator из chat_analyzer.
    URL сохранён заглушкой ради уже настроенных OBS-сцен.
    """
    return HTMLResponse(_retired_widget_html("/widget/typing-indicator"))


@public_router.get("/widget/tts-chat-overlay", response_class=HTMLResponse)
async def widget_tts_chat_overlay_page(
    account_id: int | None = None,
    color: str = "",
    max_msgs: int = 5,
    retain_ms: int = 30000,
    filter: str = "all",
) -> HTMLResponse:
    """§8: окремий оверлей чату TTS-бота.

    Показує стрічку реплік TTS-бота (з емодзі-обгорткою), з фільтром
    по ``account_id``. Налаштування:

    * ``?account_id=`` — фільтр по боту.
    * ``?color=`` — акцент-колір (default gold, або з tts_bot_config).
    * ``?max_msgs=`` — скільки реплік тримати на екрані (1-20, default 5).
    * ``?retain_ms=`` — скільки мс тримати кожну репліку (2000-60000,
      default 30000 = 30с, P6 PLAN.md)."""
    db_color = ""
    if account_id and not color:
        db = await get_db()
        try:
            cur = await db.execute(
                "SELECT widget_color FROM tts_bot_config WHERE account_id = ?",
                (account_id,),
            )
            row = await cur.fetchone()
        finally:
            await db.close()
        if row:
            db_color = row["widget_color"] or ""
    accent = _normalize_hex(color or db_color or "#FFD700")
    try:
        safe_max = max(1, min(20, int(max_msgs)))
    except Exception:
        safe_max = 5
    try:
        safe_retain = max(2000, min(60000, int(retain_ms)))
    except Exception:
        safe_retain = 30000
    safe_account = int(account_id) if account_id else 0
    safe_filter = filter if filter in {"all", "rewards", "bot"} else "all"
    return HTMLResponse(
        _widget_html("tts-chat-overlay")
        .replace("__TTS_ACCENT__", accent)
        .replace("__ACCOUNT_ID__", str(safe_account))
        .replace("__MAX_MSGS__", str(safe_max))
        .replace("__RETAIN_MS__", str(safe_retain))
        .replace("__TTS_FILTER__", json.dumps(safe_filter))
    )


@admin_router.get("/api/widgets/tts-bot/config")
async def tts_bot_widget_get(account_id: int) -> dict:
    """Повертає колір/іконку/emoji-prefix/suffix для адмін-форми TTS-бота."""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT account_id, widget_color, widget_emoji, emoji_prefix, emoji_suffix "
            "FROM tts_bot_config WHERE account_id = ?",
            (account_id,),
        )
        row = await cur.fetchone()
    finally:
        await db.close()
    if not row:
        return {
            "account_id": account_id,
            "widget_color": "#FFD700",
            "widget_emoji": "🎙️",
            "emoji_prefix": "",
            "emoji_suffix": "",
        }
    return {
        "account_id": row["account_id"],
        "widget_color": _normalize_hex(row["widget_color"] or "", "#FFD700"),
        "widget_emoji": (row["widget_emoji"] or "🎙️"),
        "emoji_prefix": row["emoji_prefix"] or "",
        "emoji_suffix": row["emoji_suffix"] or "",
    }


@admin_router.put("/api/widgets/tts-bot/config")
async def tts_bot_widget_put(account_id: int, payload: dict) -> dict:
    """Оновлює колір/іконку/emoji-prefix/suffix для TTS-бота.

    Поля, яких немає в payload, **зберігають** попереднє значення з БД
    (COALESCE у виразі UPDATE). На insert — дефолти (gold, 🎙️, '').
    """
    has_color = "widget_color" in payload
    has_emoji = "widget_emoji" in payload
    has_prefix = "emoji_prefix" in payload
    has_suffix = "emoji_suffix" in payload

    color = _normalize_hex(payload.get("widget_color") or "#FFD700") if has_color else "#FFD700"
    emoji = ((payload.get("widget_emoji") or "🎙️")[:4] or "🎙️") if has_emoji else "🎙️"
    prefix = (payload.get("emoji_prefix") or "")[:16] if has_prefix else ""
    suffix = (payload.get("emoji_suffix") or "")[:16] if has_suffix else ""

    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO tts_bot_config "
            "(account_id, widget_color, widget_emoji, emoji_prefix, emoji_suffix) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(account_id) DO UPDATE SET "
            "widget_color = COALESCE(?, widget_color), "
            "widget_emoji = COALESCE(?, widget_emoji), "
            "emoji_prefix = COALESCE(?, emoji_prefix), "
            "emoji_suffix = COALESCE(?, emoji_suffix)",
            (account_id,
             color if has_color else "#FFD700",
             emoji if has_emoji else "🎙️",
             prefix if has_prefix else "",
             suffix if has_suffix else "",
             # Параметри для COALESCE(NULL, …) — якщо немає в payload, шлемо None
             # щоб COALESCE повернув старе значення.
             color if has_color else None,
             emoji if has_emoji else None,
             prefix if has_prefix else None,
             suffix if has_suffix else None),
        )
        await db.commit()
        # Повертаємо актуальні значення з БД (бо могло бути часткове оновлення).
        cur = await db.execute(
            "SELECT widget_color, widget_emoji, emoji_prefix, emoji_suffix "
            "FROM tts_bot_config WHERE account_id = ?",
            (account_id,),
        )
        row = await cur.fetchone()
    finally:
        await db.close()
    if not row:
        return {"ok": True, "account_id": account_id, "widget_color": color,
                "widget_emoji": emoji, "emoji_prefix": prefix, "emoji_suffix": suffix}
    return {
        "ok": True,
        "account_id": account_id,
        "widget_color": _normalize_hex(row["widget_color"] or "", "#FFD700"),
        "widget_emoji": row["widget_emoji"] or "🎙️",
        "emoji_prefix": row["emoji_prefix"] or "",
        "emoji_suffix": row["emoji_suffix"] or "",
    }


# ====================================================================
# v13 §6.1 WIDGETS_PLAN: Chat Reader (озвучка чату)
# ====================================================================
#
# Два незалежні режими (обидва можуть бути включені одночасно):
#   * ``read_all=1`` — озвучувати ВСІ повідомлення чату, що пройшли антиспам
#     та фільтр ``min_role`` (any/sub/vip/mod/broadcaster).
#   * ``command="!read"`` (default) — озвучувати ТІЛЬКИ повідомлення, що
#     починаються з команди, з обрізкою самої команди з тексту.
#
# Заради уникнення флуду — ``cooldown_sec`` (per-account, default 5с) між
# двома послідовними озвучками. Зберігається в in-memory dict
# ``_chat_reader_cooldown`` (скидається при рестарті — це нормально).
#
# Викликається з ``app/chat_analyzer.py:on_message`` (хук для §6.1).

_chat_reader_cooldown: dict[int, float] = {}  # account_id -> last_fire_ts

_ROLE_RANK = {"any": 0, "subscriber": 1, "vip": 2, "moderator": 3, "broadcaster": 4}


def _normalize_role(role: str) -> str:
    """Twitch badges приходять як ``moderator``/``vip``/``subscriber``/``broadcaster``.
    Дозволяємо ``any`` як «без фільтру»."""
    r = (role or "").lower().strip()
    return r if r in _ROLE_RANK else "any"


def _role_satisfies(actual: str, required: str) -> bool:
    """actual >= required?"""
    a = _ROLE_RANK.get(_normalize_role(actual), 0)
    r = _ROLE_RANK.get(_normalize_role(required), 0)
    return a >= r


def _badges_to_role(badges: list[str] | None) -> str:
    """Конвертує Twitch-badges у максимальну роль користувача."""
    if not badges:
        return "any"
    b = {x.lower() for x in badges}
    if "broadcaster" in b:
        return "broadcaster"
    if "moderator" in b:
        return "moderator"
    if "vip" in b:
        return "vip"
    if "subscriber" in b or "founder" in b:
        return "subscriber"
    return "any"


async def _get_chat_reader_settings(account_id: int) -> dict:
    """Per-account налаштування chat-reader (lazy create)."""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT account_id, enabled, read_all, command, min_role, "
            "tts_provider, max_chars, cooldown_sec "
            "FROM chat_reader_settings WHERE account_id = ?",
            (account_id,),
        )
        row = await cur.fetchone()
    finally:
        await db.close()
    if not row:
        return {
            "account_id": account_id,
            "enabled": 0,
            "read_all": 0,
            "command": "!read",
            "min_role": "any",
            "tts_provider": "",
            "max_chars": 200,
            "cooldown_sec": 5,
        }
    return dict(row)


async def read_chat_message(
    account_id: int,
    channel: str,
    author: str,
    text: str,
    *,
    role: str = "any",
    badges: list[str] | None = None,
    trigger: str = "all",
) -> dict:
    """§6.1: озвучити повідомлення чату через TTS.

    Викликається з ``chat_analyzer.on_message`` з ``trigger="command"``
    (якщо текст починається з ``!read``) або ``trigger="all"``
    (режим read_all).

    Повертає ``{"skipped": reason}`` якщо чат-рідер вимкнений, порушений
    cooldown, або текст порожній. При успіху — ``{"ok": True, "tts": "synthesized"}``.
    """
    settings = await _get_chat_reader_settings(account_id)
    if not settings.get("enabled"):
        return {"skipped": "disabled"}
    if not text or not text.strip():
        return {"skipped": "empty"}

    # min_role фільтр (для read_all) — команду можуть писати і звичайні
    # глядачі, тому min_role обов'язковий тільки в режимі 'all'.
    actual_role = badges_to_role_safe(badges) if trigger == "all" else _normalize_role(role)
    if trigger == "all":
        if not _role_satisfies(actual_role, settings.get("min_role") or "any"):
            return {"skipped": "role_too_low"}

    # Cooldown
    cooldown = max(0, int(settings.get("cooldown_sec") or 0))
    if cooldown > 0:
        now = time.time()
        last = _chat_reader_cooldown.get(account_id, 0.0)
        if now - last < cooldown:
            return {"skipped": "cooldown"}
        _chat_reader_cooldown[account_id] = now

    # За потреби обрізати текст
    try:
        max_chars = max(1, min(500, int(settings.get("max_chars") or 200)))
    except Exception:
        max_chars = 200
    speech_text = text.strip()[:max_chars]
    if not speech_text:
        return {"skipped": "empty_after_trim"}

    # Делегуємо в TTS-двигун через загальну аудіо-чергу (§7).
    # Chat-reader має нижчий пріоритет за звичайні TTS-відповіді бота.
    try:
        from app.audio_queue import get_audio_queue
        queue = get_audio_queue()
        kind = "tts_chat_reader" if trigger == "all" else "tts_chat_reader"
        await queue.enqueue(
            kind=kind, account_id=account_id, channel=channel,
            text=speech_text, trigger=trigger,
        )
        return {"ok": True, "trigger": trigger, "text": speech_text}
    except Exception as exc:
        return {"error": f"tts_failed: {exc}"}


def _badges_to_role_safe(badges: list[str] | None) -> str:
    """Аліас, що приймає None/list і повертає максимальну роль."""
    if badges:
        return _badges_to_role(badges)
    return "any"


# DEPRECATED: реальний API — _badges_to_role_safe (читабельніше).
badges_to_role_safe = _badges_to_role_safe


@admin_router.get("/api/widgets/chat-reader/settings")
async def chat_reader_settings_get(account_id: int) -> dict:
    """Per-account налаштування chat-reader для адмін-форми."""
    return {"ok": True, "settings": await _get_chat_reader_settings(account_id)}


@admin_router.put("/api/widgets/chat-reader/settings")
async def chat_reader_settings_put(account_id: int, payload: dict) -> dict:
    """Оновлення налаштувань chat-reader (enabled, read_all, command, min_role, ...)."""
    enabled = 1 if payload.get("enabled") else 0
    read_all = 1 if payload.get("read_all") else 0
    command = (payload.get("command") or "!read").strip()[:32] or "!read"
    if not command.startswith("!"):
        command = "!" + command.lstrip("!")
    min_role = _normalize_role(payload.get("min_role") or "any")
    tts_provider = (payload.get("tts_provider") or "")[:32]
    try:
        max_chars = max(20, min(500, int(payload.get("max_chars") or 200)))
    except (TypeError, ValueError):
        max_chars = 200
    try:
        cooldown = max(0, min(60, int(payload.get("cooldown_sec") or 0)))
    except (TypeError, ValueError):
        cooldown = 5
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO chat_reader_settings "
            "(account_id, enabled, read_all, command, min_role, tts_provider, max_chars, cooldown_sec) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(account_id) DO UPDATE SET "
            "enabled=excluded.enabled, read_all=excluded.read_all, command=excluded.command, "
            "min_role=excluded.min_role, tts_provider=excluded.tts_provider, "
            "max_chars=excluded.max_chars, cooldown_sec=excluded.cooldown_sec",
            (account_id, enabled, read_all, command, min_role, tts_provider, max_chars, cooldown),
        )
        await db.commit()
    finally:
        await db.close()
    return {"ok": True,
            "settings": await _get_chat_reader_settings(account_id)}



# ====================================================================
# §11.3 WIDGETS_PLAN: биндинги виджетов (CRUD + пресеты).
# Исполнение действий — app/widget_bindings.py (run_binding / хуки).
# ====================================================================


def _binding_channel(value: Any) -> str:
    return str(value or "").strip().lower().lstrip("#")


def _binding_account_id(value: Any) -> int:
    try:
        account_id = int(value or 0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="binding_scope_required")
    return account_id


async def _validate_binding_scope(db: Any, account_id: int, channel: str) -> None:
    if account_id <= 0 or not channel:
        raise HTTPException(status_code=400, detail="binding_scope_required")
    row = await (await db.execute(
        "SELECT 1 FROM channels WHERE account_id = ? AND enabled = 1 "
        "AND lower(ltrim(trim(channel_name), '#')) = ?",
        (account_id, channel),
    )).fetchone()
    if not row:
        raise HTTPException(status_code=400, detail="binding_scope_not_found")


@admin_router.get("/api/widgets/binding-contract")
async def binding_contract_get() -> dict:
    from app.widget_bindings import BINDING_CONTRACT

    return BINDING_CONTRACT


@admin_router.get("/api/widgets/bindings")
async def bindings_list(account_id: int, channel: str) -> dict:
    channel = _binding_channel(channel)
    db = await get_db()
    try:
        await _validate_binding_scope(db, account_id, channel)
        cursor = await db.execute(
            "SELECT id, account_id, channel, enabled, source, match, widget, widget_key, "
            "action, value, role FROM widget_bindings "
            "WHERE account_id = ? AND channel = ? ORDER BY id ASC",
            (account_id, channel),
        )
        return {"items": [dict(r) for r in await cursor.fetchall()]}
    finally:
        await db.close()


@admin_router.post("/api/widgets/bindings/hotkey")
async def bindings_hotkey_exec(payload: dict) -> dict:
    """PLAN_FEEDBACK_2908 §3.1: нажатие хоткея в открытой панели → действие.

    Фронтенд слушает keydown и шлёт нормализованную комбинацию
    ('ctrl+shift+d'); сервер матчит enabled-биндинги source='hotkey' и
    выполняет тот же run_binding, что и чат-команды."""
    from app.widget_bindings import handle_hotkey
    account_id = _binding_account_id(payload.get("account_id"))
    channel = _binding_channel(payload.get("channel"))
    db = await get_db()
    try:
        await _validate_binding_scope(db, account_id, channel)
    finally:
        await db.close()
    return await handle_hotkey(str(payload.get("combo") or ""), account_id, channel)


@admin_router.post("/api/widgets/bindings/presets/{name}")
async def bindings_preset_apply(name: str, payload: dict) -> dict:
    from app.widget_bindings import apply_preset

    account_id = _binding_account_id(payload.get("account_id"))
    channel = _binding_channel(payload.get("channel"))
    db = await get_db()
    try:
        await _validate_binding_scope(db, account_id, channel)
    finally:
        await db.close()
    result = await apply_preset(name, account_id, channel)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@admin_router.post("/api/widgets/bindings")
async def bindings_create(payload: dict) -> dict:
    from app.widget_bindings import ROLES, SOURCES, validate_binding_contract
    source = str(payload.get("source") or "chat_command").strip()
    if source not in SOURCES:
        raise HTTPException(status_code=400, detail="bad_source")
    match = str(payload.get("match") or "").strip()
    widget = str(payload.get("widget") or "").strip()
    if not match:
        raise HTTPException(status_code=400, detail="match_required")
    action = str(payload.get("action") or "").strip()
    role = str(payload.get("role") or "mod").strip()
    if role not in ROLES:
        role = "mod"
    widget_key = str(payload.get("widget_key") or "").strip()
    value = str(payload.get("value") or "").strip()
    account_id = _binding_account_id(payload.get("account_id"))
    channel = _binding_channel(payload.get("channel"))
    contract_error = validate_binding_contract(
        source, match, widget, widget_key, action, value, role,
    )
    if contract_error:
        raise HTTPException(status_code=400, detail=contract_error)
    db = await get_db()
    try:
        await _validate_binding_scope(db, account_id, channel)
        try:
            cursor = await db.execute(
                "INSERT INTO widget_bindings (account_id, channel, enabled, source, match, widget, "
                "widget_key, action, value, role) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (account_id, channel, 1 if payload.get("enabled", True) else 0, source, match, widget,
                 widget_key, action, value, role),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="duplicate_binding") from exc
        await db.commit()
        return {"ok": True, "id": cursor.lastrowid or 0}
    finally:
        await db.close()


@admin_router.put("/api/widgets/bindings/{bid}")
async def bindings_update(bid: int, payload: dict) -> dict:
    from app.widget_bindings import ROLES, SOURCES, validate_binding_contract
    scope_account_id = _binding_account_id(payload.get("account_id"))
    scope_channel = _binding_channel(payload.get("channel"))
    db = await get_db()
    try:
        await _validate_binding_scope(db, scope_account_id, scope_channel)
        current = await (await db.execute(
            "SELECT account_id, channel, source, match, widget, widget_key, action, value, role "
            "FROM widget_bindings WHERE id = ? AND account_id = ? AND channel = ?",
            (bid, scope_account_id, scope_channel),
        )).fetchone()
    finally:
        await db.close()
    if not current:
        raise HTTPException(status_code=404, detail="binding_not_found")
    proposed_source = str(payload.get("source", current["source"])).strip()
    proposed_widget = str(payload.get("widget", current["widget"])).strip()
    proposed_action = str(payload.get("action", current["action"])).strip()
    proposed_match = str(payload.get("match", current["match"])).strip()
    proposed_key = str(payload.get("widget_key", current["widget_key"])).strip()
    proposed_value = str(payload.get("value", current["value"])).strip()
    proposed_role = str(payload.get("role", current["role"])).strip()
    if proposed_source not in SOURCES:
        raise HTTPException(status_code=400, detail="bad_source")
    if proposed_role not in ROLES:
        proposed_role = "mod"
    contract_error = validate_binding_contract(
        proposed_source, proposed_match, proposed_widget, proposed_key,
        proposed_action, proposed_value, proposed_role,
    )
    if contract_error:
        raise HTTPException(status_code=400, detail=contract_error)
    fields: list[str] = []
    values: list[Any] = []
    if "enabled" in payload:
        fields.append("enabled = ?")
        values.append(1 if payload["enabled"] else 0)
    for k in ("source", "match", "widget_key", "value"):
        if k in payload:
            fields.append(f"{k} = ?")
            values.append(str(payload[k] or "").strip())
    if "action" in payload:
        fields.append("action = ?")
        values.append(str(payload["action"]).strip())
    if "role" in payload:
        role = str(payload["role"]).strip()
        if role not in ROLES:
            role = "mod"
        fields.append("role = ?")
        values.append(role)
    if not fields:
        return {"error": "nothing_to_update"}
    fields.append("id = ?")
    values.append(bid)
    values.extend((scope_account_id, scope_channel))
    db = await get_db()
    try:
        try:
            await db.execute(
                f"UPDATE widget_bindings SET {', '.join(fields[:-1])} "
                "WHERE id = ? AND account_id = ? AND channel = ?",
                tuple(values),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="duplicate_binding") from exc
        await db.commit()
    finally:
        await db.close()
    return {"ok": True}


@admin_router.delete("/api/widgets/bindings/{bid}")
async def bindings_delete(bid: int, account_id: int, channel: str) -> dict:
    channel = _binding_channel(channel)
    db = await get_db()
    try:
        await _validate_binding_scope(db, account_id, channel)
        cursor = await db.execute(
            "DELETE FROM widget_bindings WHERE id = ? AND account_id = ? AND channel = ?",
            (bid, account_id, channel),
        )
        await db.commit()
        if not cursor.rowcount:
            raise HTTPException(status_code=404, detail="binding_not_found")
    finally:
        await db.close()
    return {"ok": True}


# ====================================================================
# §11.4 WIDGETS_PLAN: донат-интеграции — МУЛЬТИПЛАТФОРМЕННЫЙ режим
# (решение владельца 28.08): DonatePay, DonateX и DonationAlerts могут
# быть включены ОДНОВРЕМЕННО. Циклы — app/donation_integrations.py.
# ====================================================================


async def _get_donation_integration_row(
    platform: str, scope: tuple[int, str] | None = None,
) -> dict:
    """Настройки одной платформы: {platform, token, enabled}."""
    db = await get_db()
    try:
        if scope is None:
            cursor = await db.execute(
                "SELECT platform, token, enabled, '' AS webhook_token, last_success_at "
                "FROM donation_integrations WHERE platform = ?", (platform,),
            )
        else:
            cursor = await db.execute(
                "SELECT platform, token, webhook_token, enabled, last_success_at "
                "FROM donation_integrations_scoped "
                "WHERE account_id = ? AND channel = ? AND platform = ?",
                (*scope, platform),
            )
        row = await cursor.fetchone()
        if row:
            result = dict(row)
            result["token"] = decrypt_token(str(result.get("token") or ""))
            return result
        return {"platform": platform, "token": "", "enabled": 0}
    finally:
        await db.close()


async def _list_donation_integrations(
    scope: tuple[int, str] | None = None,
) -> list[dict]:
    db = await get_db()
    try:
        if scope is None:
            cursor = await db.execute(
                "SELECT platform, token, enabled, '' AS webhook_token, last_success_at "
                "FROM donation_integrations ORDER BY platform ASC"
            )
        else:
            cursor = await db.execute(
                "SELECT platform, token, webhook_token, enabled, last_success_at "
                "FROM donation_integrations_scoped "
                "WHERE account_id = ? AND channel = ? ORDER BY platform ASC", scope,
            )
        rows = [dict(r) for r in await cursor.fetchall()]
        for row in rows:
            row["token"] = decrypt_token(str(row.get("token") or ""))
        return rows
    finally:
        await db.close()


async def _all_donation_integration_rows() -> list[dict]:
    """Internal dispatcher feed; credentials never leave the process."""
    db = await get_db()
    try:
        legacy = await db.execute(
            "SELECT NULL AS account_id, NULL AS channel, platform, token, enabled, last_success_at "
            "FROM donation_integrations"
        )
        scoped = await db.execute(
            "SELECT account_id, channel, platform, token, enabled, last_success_at "
            "FROM donation_integrations_scoped"
        )
        rows = [dict(row) for row in (*await legacy.fetchall(), *await scoped.fetchall())]
        for row in rows:
            row["token"] = decrypt_token(str(row.get("token") or ""))
        return rows
    finally:
        await db.close()


async def _all_donation_goal_sync_scopes() -> list[tuple[int, str]]:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT account_id, channel FROM donation_goal_sync_scoped "
            "WHERE enabled = 1 AND external_goal_id <> ''"
        )
        return [(int(row["account_id"]), str(row["channel"])) for row in await cursor.fetchall()]
    finally:
        await db.close()


@admin_router.get("/api/widgets/donation-integration")
async def donation_integration_get(
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    from app.donation_integrations import get_status
    scope = await _verified_widget_state_scope(account_id, channel)
    items = []
    for row in await _list_donation_integrations(scope):
        token = row.get("token") or ""
        webhook_token = row.get("webhook_token") or ""
        items.append({
            "platform": row["platform"],
            "enabled": bool(row.get("enabled")),
            "token_set": bool(token),
            "token_hint": ("…" + token[-4:]) if len(token) > 4 else "***" if token else "",
            "webhook_token_set": bool(webhook_token),
            "webhook_token_hint": ("…" + webhook_token[-4:]) if len(webhook_token) > 4 else "",
            "status": get_status(row["platform"], scope, row.get("last_success_at")),
        })
    return {"items": items, "storage_mode": credential_storage_mode()}


@admin_router.put("/api/widgets/donation-integration")
async def donation_integration_put(
    payload: dict, account_id: int | None = None, channel: str | None = None,
) -> dict:
    """Upsert одной платформы: {platform, enabled, token?}.

    Токен обновляется только если передан непустой (не затираем сохранённый).
    """
    platform = str(payload.get("platform") or "").strip().lower()
    if platform not in ("donatepay", "donatex", "donationalerts"):
        return {"error": "bad_platform"}
    enabled = 1 if payload.get("enabled") else 0
    token = str(payload.get("token") or "").strip()
    stored_token = encrypt_token(token) if token else ""
    webhook_token = str(payload.get("webhook_token") or "").strip()
    scope = await _verified_widget_state_scope(account_id, channel)
    db = await get_db()
    try:
        if scope is None:
            cursor = await db.execute(
                "SELECT token FROM donation_integrations WHERE platform = ?", (platform,),
            )
        else:
            cursor = await db.execute(
                "SELECT token FROM donation_integrations_scoped "
                "WHERE account_id = ? AND channel = ? AND platform = ?", (*scope, platform),
            )
        row = await cursor.fetchone()
        if row is None:
            if scope is None:
                await db.execute(
                    "INSERT INTO donation_integrations (platform, token, enabled) VALUES (?, ?, ?)",
                    (platform, stored_token, enabled),
                )
            else:
                await db.execute(
                    "INSERT INTO donation_integrations_scoped "
                    "(account_id, channel, platform, token, webhook_token, enabled) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (*scope, platform, stored_token, webhook_token, enabled),
                )
        else:
            fields = "enabled = ?, updated_at = CURRENT_TIMESTAMP"
            values: list[Any] = [enabled]
            if token:  # пустой токен не затирает сохранённый
                fields = "token = ?, " + fields
                values.insert(0, stored_token)
            if scope is not None and webhook_token:
                fields = "webhook_token = ?, " + fields
                values.insert(0, webhook_token)
            if scope is None:
                values.append(platform)
                await db.execute(
                    f"UPDATE donation_integrations SET {fields} WHERE platform = ?", tuple(values),
                )
            else:
                values.extend((*scope, platform))
                await db.execute(
                    f"UPDATE donation_integrations_scoped SET {fields} "
                    "WHERE account_id = ? AND channel = ? AND platform = ?", tuple(values),
                )
        await db.commit()
    finally:
        await db.close()
    saved = await _get_donation_integration_row(platform, scope)
    return {"ok": True, "platform": platform, "enabled": bool(saved.get("enabled"))}


@admin_router.post("/api/widgets/donation-integration/{platform}/reconnect")
async def donation_integration_reconnect(
    platform: str, account_id: int | None = None, channel: str | None = None,
) -> dict:
    platform = platform.strip().lower()
    if platform not in ("donatepay", "donatex", "donationalerts"):
        return {"error": "bad_platform"}
    scope = await _verified_widget_state_scope(account_id, channel)
    from app.donation_integrations import reconnect_integration
    return await reconnect_integration(platform, scope)


async def _donation_bridge_record(scope: tuple[int, str]) -> dict:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT token, enabled FROM donation_webhook_scopes "
            "WHERE account_id = ? AND channel = ?", scope,
        )
        row = await cursor.fetchone()
        if row:
            return {"token": str(row["token"] or ""), "enabled": bool(row["enabled"]), "legacy": False}
        legacy = await db.execute(
            "SELECT webhook_token FROM donation_integrations_scoped "
            "WHERE account_id = ? AND channel = ? AND webhook_token <> '' "
            "ORDER BY platform LIMIT 1", scope,
        )
        legacy_row = await legacy.fetchone()
        token = str(legacy_row["webhook_token"] or "") if legacy_row else ""
        return {"token": token, "enabled": bool(token), "legacy": bool(token)}
    finally:
        await db.close()


@admin_router.get("/api/widgets/donation-bridge")
async def donation_bridge_get(account_id: int, channel: str) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    if scope is None:
        raise HTTPException(status_code=400, detail="widget_scope_required")
    record = await _donation_bridge_record(scope)
    return {
        "enabled": record["enabled"],
        "token_set": bool(record["token"]),
        "token_hint": mask_token(record["token"]),
        "legacy": record["legacy"],
    }


@admin_router.put("/api/widgets/donation-bridge")
async def donation_bridge_put(
    request: Request, payload: dict, account_id: int, channel: str,
) -> dict:
    require_loopback_client(request)
    require_same_origin_request(request)
    scope = await _verified_widget_state_scope(account_id, channel)
    if scope is None:
        raise HTTPException(status_code=400, detail="widget_scope_required")
    current = await _donation_bridge_record(scope)
    enabled = bool(payload.get("enabled"))
    if enabled and not current["token"]:
        return {"ok": False, "error": "bridge_token_required"}
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO donation_webhook_scopes (account_id, channel, token, enabled) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(account_id, channel) DO UPDATE SET "
            "token = excluded.token, enabled = excluded.enabled, updated_at = CURRENT_TIMESTAMP",
            (*scope, current["token"], 1 if enabled else 0),
        )
        await db.commit()
    finally:
        await db.close()
    return {"ok": True, "enabled": enabled}


@admin_router.get("/api/widgets/donation-bridge/reveal")
async def donation_bridge_reveal(request: Request, account_id: int, channel: str) -> dict:
    require_loopback_client(request)
    require_same_origin_request(request)
    scope = await _verified_widget_state_scope(account_id, channel)
    if scope is None:
        raise HTTPException(status_code=400, detail="widget_scope_required")
    record = await _donation_bridge_record(scope)
    if not record["token"]:
        raise HTTPException(status_code=409, detail="bridge_token_required")
    return {"token": record["token"], "hide_after_seconds": 30}


@admin_router.post("/api/widgets/donation-bridge/rotate")
async def donation_bridge_rotate(request: Request, account_id: int, channel: str) -> dict:
    require_loopback_client(request)
    require_same_origin_request(request)
    scope = await _verified_widget_state_scope(account_id, channel)
    if scope is None:
        raise HTTPException(status_code=400, detail="widget_scope_required")
    token = secrets.token_urlsafe(32)
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO donation_webhook_scopes (account_id, channel, token, enabled) "
            "VALUES (?, ?, ?, 1) ON CONFLICT(account_id, channel) DO UPDATE SET "
            "token = excluded.token, enabled = 1, updated_at = CURRENT_TIMESTAMP",
            (*scope, token),
        )
        await db.commit()
    finally:
        await db.close()
    return {"ok": True, "token": token, "hide_after_seconds": 30}


# ── Синхронизация внешних сборов → donation-challenge (решение владельца) ──
# DonateX-сбор (goal из их API) автоматически двигает активный челлендж:
# каждый опрос применяет дельту внешнего currentAmount, локальные донаты
# не затираются. Первый опрос задаёт базовую линию (без дельты).


@admin_router.get("/api/widgets/donation-goal-sync")
async def donation_goal_sync_get(
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    db = await get_db()
    try:
        if scope is None:
            cursor = await db.execute(
                "SELECT platform, external_goal_id, enabled, last_amount, synced "
                "FROM donation_goal_sync WHERE id = 1"
            )
        else:
            cursor = await db.execute(
                "SELECT platform, external_goal_id, enabled, last_amount, synced "
                "FROM donation_goal_sync_scoped WHERE account_id = ? AND channel = ?", scope,
            )
        row = await cursor.fetchone()
        return dict(row) if row else {
            "platform": "donatex", "external_goal_id": "", "enabled": 0,
            "last_amount": 0, "synced": 0,
        }
    finally:
        await db.close()


@admin_router.put("/api/widgets/donation-goal-sync")
async def donation_goal_sync_put(
    payload: dict, account_id: int | None = None, channel: str | None = None,
) -> dict:
    platform = str(payload.get("platform") or "donatex").strip().lower()
    if platform not in ("donatex", "donatepay", "donationalerts"):
        platform = "donatex"
    goal_id = str(payload.get("external_goal_id") or "").strip()
    enabled = 1 if payload.get("enabled") else 0
    scope = await _verified_widget_state_scope(account_id, channel)
    db = await get_db()
    try:
        if scope is None:
            await db.execute(
                "UPDATE donation_goal_sync SET platform = ?, external_goal_id = ?, "
                "enabled = ?, last_amount = 0, synced = 0, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = 1", (platform, goal_id, enabled),
            )
        else:
            if goal_id:
                cursor = await db.execute(
                    "SELECT 1 FROM donation_goal_sync_scoped WHERE external_goal_id = ? "
                    "AND (account_id <> ? OR channel <> ?)", (goal_id, *scope),
                )
                if await cursor.fetchone():
                    return {"ok": False, "error": "goal_scope_conflict"}
            await db.execute(
                "INSERT INTO donation_goal_sync_scoped "
                "(account_id, channel, platform, external_goal_id, enabled) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(account_id, channel) DO UPDATE SET platform = excluded.platform, "
                "external_goal_id = excluded.external_goal_id, enabled = excluded.enabled, "
                "last_amount = 0, synced = 0, updated_at = CURRENT_TIMESTAMP",
                (*scope, platform, goal_id, enabled),
            )
        await db.commit()
    finally:
        await db.close()
    return {"ok": True}


# Ручная запись доната из внешних систем (webhook/скрипт/тест) — публичный,
# как counter increment: OBS-хоткей и внешние донат-сервисы не имеют auth-сессии.
@public_router.get("/api/widgets/public/clip-moments")
async def clip_moments_public(
    account_id: int = 0, channel: str = "", limit: int = 5,
) -> list[dict]:
    """§9.3: последние моменты клипов для OBS-виджета (read-only, без auth)."""
    limit = max(1, min(int(limit or 5), 20))
    channel = _binding_channel(channel)
    db = await get_db()
    try:
        if channel:
            await _validate_binding_scope(db, account_id, channel)
            cursor = await db.execute(
                "SELECT channel, rate, avg_rate, clip_url, timestamp FROM clip_moments "
                "WHERE account_id = ? AND lower(ltrim(trim(channel), '#')) = ? "
                "ORDER BY id DESC LIMIT ?",
                (account_id, channel, limit),
            )
        elif account_id > 0:
            # Compatibility: historical account-only OBS URLs remain account-global.
            cursor = await db.execute(
                "SELECT channel, rate, avg_rate, clip_url, timestamp FROM clip_moments "
                "WHERE account_id = ? ORDER BY id DESC LIMIT ?",
                (account_id, limit),
            )
        else:
            cursor = await db.execute(
                "SELECT channel, rate, avg_rate, clip_url, timestamp FROM clip_moments "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


@public_router.post("/api/widgets/public/donation-webhook")
async def donation_webhook_public(request: Request, payload: dict) -> dict:
    """Простой входящий webhook для внешнего донат-сервиса (§3/§11.4).

    Ожидает {event_id, username, amount, currency?, message?, secret?}. Ingress
    всегда требует global secret или scoped webhook token.
    """
    import hmac
    import os
    require_loopback_client(request)
    secret = os.environ.get("DONATION_WEBHOOK_SECRET", "")
    scope = await _verified_widget_state_scope(
        payload.get("account_id"), payload.get("channel"),
    )
    supplied_secret = str(payload.get("secret") or "")
    if scope is None:
        if not secret:
            return {"error": "webhook_not_configured"}
        if not hmac.compare_digest(supplied_secret, secret):
            return {"error": "bad_secret"}
    else:
        bridge = await _donation_bridge_record(scope)
        scoped_secret = bridge["token"] if bridge["enabled"] else ""
        if not scoped_secret:
            return {"error": "webhook_not_configured"}
        if not hmac.compare_digest(supplied_secret, scoped_secret):
            return {"error": "bad_secret"}
    try:
        amount = float(payload.get("amount") or 0)
    except (TypeError, ValueError):
        return {"error": "bad_amount"}
    if amount <= 0:
        return {"error": "bad_amount"}
    event_id = str(payload.get("event_id") or payload.get("id") or "").strip()
    if not event_id:
        return {"error": "event_id_required"}
    if len(event_id) > 255:
        return {"error": "event_id_too_long"}
    from app.donation_integrations import _process_donation
    processed = await _process_donation(
        "webhook",
        str(payload.get("username") or "anonymous")[:100],
        amount,
        str(payload.get("currency") or "USD")[:10],
        str(payload.get("message") or "")[:500],
        account_id=scope[0] if scope else None,
        channel=scope[1] if scope else None,
        event_id=event_id,
    )
    if processed is None:
        return {"error": "processing_failed"}
    return {"ok": True, **({"duplicate": True} if not processed else {})}


# ====================================================================
# §9.3 WIDGETS_PLAN: дополнительные виджеты.
#   * subathon-timer  — таймер, продлевается за сабы/донаты
#   * emoji-leaderboard — топ юзеров по отправленным эмодзи за день
#   * hype-meter      — клиентский (см. widgets/hype-meter), backend не нужен
#   * poll-overlay    — выведен из эксплуатации (owner survey Q28)
# ====================================================================


# ── Subathon Timer ───────────────────────────────────────────────


async def subathon_extend(
    seconds: int, scope: tuple[int, str] | None = None,
) -> None:
    """Продлевает таймер (вызывается из on_subscribe_event / on_donation_event)."""
    db = await get_db()
    try:
        if scope is None:
            cursor = await db.execute(
                "SELECT running, end_at FROM subathon_timer WHERE id = 1"
            )
        else:
            await db.execute(
                "INSERT OR IGNORE INTO subathon_timer_scoped "
                "(account_id, channel) VALUES (?, ?)", scope,
            )
            cursor = await db.execute(
                "SELECT running, end_at FROM subathon_timer_scoped "
                "WHERE account_id = ? AND channel = ?", scope,
            )
        row = await cursor.fetchone()
        if not row or not row["running"]:
            return
        if scope is None:
            await db.execute(
                "UPDATE subathon_timer SET end_at = datetime(COALESCE(end_at, "
                "CURRENT_TIMESTAMP), '+' || ? || ' seconds') WHERE id = 1",
                (max(0, int(seconds)),),
            )
        else:
            await db.execute(
                "UPDATE subathon_timer_scoped SET end_at = datetime(COALESCE(end_at, "
                "CURRENT_TIMESTAMP), '+' || ? || ' seconds') "
                "WHERE account_id = ? AND channel = ?",
                (max(0, int(seconds)), *scope),
            )
        await db.commit()
    finally:
        await db.close()
    _cache_invalidate(_widget_cache_key("subathon", scope))


@admin_router.get("/api/widgets/subathon")
async def subathon_get(
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    db = await get_db()
    try:
        if scope is None:
            cursor = await db.execute(
                "SELECT id, end_at, running, seconds_per_sub, seconds_per_donation, "
                "seconds_per_currency, title FROM subathon_timer WHERE id = 1"
            )
        else:
            await db.execute(
                "INSERT OR IGNORE INTO subathon_timer_scoped "
                "(account_id, channel) VALUES (?, ?)", scope,
            )
            cursor = await db.execute(
                "SELECT account_id AS id, end_at, running, seconds_per_sub, "
                "seconds_per_donation, seconds_per_currency, title "
                "FROM subathon_timer_scoped WHERE account_id = ? AND channel = ?", scope,
            )
        row = await cursor.fetchone()
        if not row:
            return {}
        out = dict(row)
        # remaining для статуса в карточке (как считает виджет)
        try:
            import datetime as _dt
            if out["running"] and out["end_at"]:
                end = _dt.datetime.fromisoformat(str(out["end_at"]).replace("Z", "+00:00")).replace(tzinfo=None)
                out["remaining"] = max(0, int((end - _dt.datetime.utcnow()).total_seconds()))
            else:
                out["remaining"] = 0
        except Exception:
            out["remaining"] = 0
        return out
    finally:
        await db.close()


@admin_router.put("/api/widgets/subathon")
async def subathon_put(
    payload: dict, account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    db = await get_db()
    try:
        fields: list[str] = []
        values: list[Any] = []
        for k in ("seconds_per_sub", "seconds_per_donation"):
            if k in payload:
                try:
                    fields.append(f"{k} = ?")
                    values.append(max(1, min(3600, int(payload[k]))))
                except (TypeError, ValueError):
                    pass
        if "seconds_per_currency" in payload:
            try:
                # 0 = плоский тариф за донат; > 0 = секунд за единицу валюты
                fields.append("seconds_per_currency = ?")
                values.append(max(0.0, min(3600.0, float(payload["seconds_per_currency"]))))
            except (TypeError, ValueError):
                pass
        if "title" in payload:
            fields.append("title = ?")
            values.append(str(payload["title"] or "SUBATHON")[:60])
        if fields:
            if scope is None:
                values.append(1)
                await db.execute(
                    f"UPDATE subathon_timer SET {', '.join(fields)} WHERE id = ?", tuple(values),
                )
            else:
                await db.execute(
                    "INSERT OR IGNORE INTO subathon_timer_scoped "
                    "(account_id, channel) VALUES (?, ?)", scope,
                )
                values.extend(scope)
                await db.execute(
                    f"UPDATE subathon_timer_scoped SET {', '.join(fields)} "
                    "WHERE account_id = ? AND channel = ?", tuple(values),
                )
        await db.commit()
    finally:
        await db.close()
    return {"ok": True}


@admin_router.post("/api/widgets/subathon/start")
async def subathon_start(
    payload: dict | None = None,
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    minutes = 30
    if payload and "minutes" in payload:
        try:
            minutes = max(1, int(payload["minutes"]))
        except (TypeError, ValueError):
            minutes = 30
    db = await get_db()
    try:
        if scope is None:
            await db.execute(
                "UPDATE subathon_timer SET running = 1, "
                "end_at = datetime('now', '+' || ? || ' minutes') WHERE id = 1", (minutes,),
            )
        else:
            await db.execute(
                "INSERT OR IGNORE INTO subathon_timer_scoped "
                "(account_id, channel) VALUES (?, ?)", scope,
            )
            await db.execute(
                "UPDATE subathon_timer_scoped SET running = 1, "
                "end_at = datetime('now', '+' || ? || ' minutes') "
                "WHERE account_id = ? AND channel = ?", (minutes, *scope),
            )
        await db.commit()
    finally:
        await db.close()
    _cache_invalidate(_widget_cache_key("subathon", scope))
    return {"ok": True}


@admin_router.post("/api/widgets/subathon/stop")
async def subathon_stop(
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    db = await get_db()
    try:
        if scope is None:
            await db.execute("UPDATE subathon_timer SET running = 0 WHERE id = 1")
        else:
            await db.execute(
                "UPDATE subathon_timer_scoped SET running = 0 "
                "WHERE account_id = ? AND channel = ?", scope,
            )
        await db.commit()
    finally:
        await db.close()
    _cache_invalidate(_widget_cache_key("subathon", scope))
    return {"ok": True}


@public_router.get("/api/widgets/public/subathon")
async def subathon_public(
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    scope = await _verified_widget_state_scope(account_id, channel)
    cache_key = _widget_cache_key("subathon", scope)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    db = await get_db()
    try:
        if scope is None:
            cursor = await db.execute(
                "SELECT end_at, running, title FROM subathon_timer WHERE id = 1"
            )
        else:
            cursor = await db.execute(
                "SELECT end_at, running, title FROM subathon_timer_scoped "
                "WHERE account_id = ? AND channel = ?", scope,
            )
        row = await cursor.fetchone()
    finally:
        await db.close()
    if not row:
        return {"running": False, "remaining": 0, "title": "SUBATHON"}
    remaining = 0
    if row["running"] and row["end_at"]:
        # end_at хранится в UTC (sqlite CURRENT_TIMESTAMP) — считаем остаток в SQL
        db2 = await get_db()
        try:
            if scope is None:
                c2 = await db2.execute(
                    "SELECT MAX(0, CAST(strftime('%s', end_at) AS INTEGER) - "
                    "CAST(strftime('%s', 'now') AS INTEGER)) AS r "
                    "FROM subathon_timer WHERE id = 1"
                )
            else:
                c2 = await db2.execute(
                    "SELECT MAX(0, CAST(strftime('%s', end_at) AS INTEGER) - "
                    "CAST(strftime('%s', 'now') AS INTEGER)) AS r "
                    "FROM subathon_timer_scoped WHERE account_id = ? AND channel = ?", scope,
                )
            rrow = await c2.fetchone()
            remaining = int(rrow["r"] or 0) if rrow else 0
        finally:
            await db2.close()
    result = {"running": bool(row["running"]), "remaining": remaining,
              "title": row["title"] or "SUBATHON"}
    _cache_set(cache_key, result)
    return result


# ── Poll Overlay — ВЫВЕДЕН ИЗ ЭКСПЛУАТАЦИИ (owner survey Q28: Д) ──
#
# Оверлей, свой !vote-опрос (custom_poll) и его admin/public API удалены.
# Управление настоящими Twitch Polls (/api/widgets/twitch-poll) осталось ниже:
# это голосование Twitch показывает сам, оверлей ему не нужен.
# Таблица custom_poll в БД не тронута — схему на этапе чистки не меняем.


# ── Emoji Leaderboard ────────────────────────────────────────────

def _count_emojis(text: str) -> int:
    """Количество unicode-эмодзи в тексте.

    Wave 7 (Q34/Q35): распознавание живёт в общем ядре app/emoji_core.py —
    лента emoji-chat и рейтинг emoji-leaderboard трактуют эмодзи одинаково.
    """
    return count_emojis(text)


async def on_chat_emoji(username: str, text: str) -> None:
    """Хук из chat broadcast: инкремент счётчика эмодзи юзера за сегодня."""
    n = _count_emojis(text)
    if n <= 0:
        return
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO emoji_stats (username, day, count) VALUES (?, date('now'), ?) "
            "ON CONFLICT(username, day) DO UPDATE SET count = count + excluded.count",
            (username.lower()[:100], n),
        )
        await db.commit()
    finally:
        await db.close()
    _cache_invalidate("public:emoji-leaderboard")


@public_router.get("/api/widgets/public/emoji-core")
async def emoji_core_public() -> dict:
    """Общее ядро распознавания эмодзи для фронтенда (Wave 7, Q34/Q35).

    emoji-chat берёт отсюда тот же паттерн, по которому считает
    emoji-leaderboard, — иначе лента и рейтинг расходились бы в том, что
    вообще считать эмодзи.
    """
    return {"pattern": EMOJI_PATTERN, "flags": "gu"}


@public_router.get("/api/widgets/public/emoji-leaderboard")
async def emoji_leaderboard_public(limit: int = 10) -> dict:
    cached = _cache_get("public:emoji-leaderboard")
    if cached is not None:
        return cached
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT username, count FROM emoji_stats WHERE day = date('now') "
            "ORDER BY count DESC, username ASC LIMIT ?",
            (max(1, min(25, limit)),),
        )
        items = [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()
    result = {"items": items}
    _cache_set("public:emoji-leaderboard", result)
    return result


# ── §9.3: роуты новых виджетов ───────────────────────────────────


@public_router.get("/widget/hype-meter", response_class=HTMLResponse)
async def widget_hype_meter() -> str:
    """Чисто клиентский виджет: частота сообщений чата по WS."""
    return _widget_html("hype-meter")


@public_router.get("/widget/subathon-timer", response_class=HTMLResponse)
async def widget_subathon_timer() -> str:
    return _widget_html("subathon-timer")


@public_router.get("/widget/poll-overlay", response_class=HTMLResponse)
async def widget_poll_overlay() -> HTMLResponse:
    """Выведен из эксплуатации (owner survey Q28: Д).

    Управление НАСТОЯЩИМИ Twitch Polls (/api/widgets/twitch-poll) сохранено —
    оно показывает голосование средствами самого Twitch, без оверлея.
    Свой !vote-опрос (custom_poll) удалён вместе с виджетом.
    """
    return HTMLResponse(_retired_widget_html("/widget/poll-overlay"))


@public_router.get("/widget/emoji-leaderboard", response_class=HTMLResponse)
async def widget_emoji_leaderboard() -> str:
    return _widget_html("emoji-leaderboard")


# §5/§11.0: раздача общих runtime и design assets для виджетов.
@public_router.get("/widget/_shared/{fname:path}")
async def widget_shared_file(fname: str) -> Response:
    path = (WIDGETS_DIR / "_shared" / fname).resolve()
    if not str(path).startswith(str(WIDGETS_DIR.resolve() / "_shared")) or not path.is_file():
        return Response("not found", status_code=404, media_type="text/plain")
    media_type = "text/css" if path.suffix == ".css" else "application/javascript"
    return Response(path.read_text(encoding="utf-8"), media_type=media_type)


# ── §13 WIDGETS_PLAN: роут OBS-оверлея Blur Guard ────────────────


@public_router.get("/obs/blur-guard", response_class=HTMLResponse)
async def widget_blur_guard() -> HTMLResponse:
    """Старый Blur Guard заменён на v2 (owner survey Q36: Д).

    URL оставлен ALIAS'ом на v2, а не заглушкой: у владельца уже настроены
    OBS-сцены на этот адрес, и v2 умеет всё, что умел старый (reactive blur),
    плюс зоны и live-настройки — сцена продолжает работать как раньше.
    Удаление самого URL — отдельное решение.
    """
    return HTMLResponse(_widget_html("blur-guard-v2"))


# P4 PLAN.md: blur-guard-v2 (мультизоны always-on, gaussian/mosaic/combo)
@public_router.get("/obs/blur-guard-v2", response_class=HTMLResponse)
async def widget_blur_guard_v2() -> str:
    return _widget_html("blur-guard-v2")


# §6.1 WIDGETS_PLAN: роут виджета chat-reader (озвучка чата, оверлей пузыря).
@public_router.get("/widget/chat-reader", response_class=HTMLResponse)
async def widget_chat_reader(
    theme: str | None = None, accent: str | None = None,
    bg: str | None = None, opacity: str | None = None,
    radius: str | None = None, font: str | None = None,
    size: str | None = None, scale: str | None = None,
    pos: str | None = None, shadow: str | None = None,
    hold: str | None = None, maxw: str | None = None,
) -> str:
    design = await _resolve_widget_design("chat-reader", locals())
    return _apply_widget_design(_widget_html("chat-reader"), design)


# ====================================================================
# Решения владельца (28.08.2026, «позадавай вопросы»):
#   * Twitch Polls — нативные голосования Helix для poll-overlay
#   * Twitch/BTTV/7TV emote-картинки в emoji-chat (public emotes API)
#   * Свой видео-виджет media-share (YT-плеер + пауза при TTS)
# ====================================================================


@public_router.get("/api/widgets/public/twitch-poll")
async def twitch_poll_public(account_id: int = 0, channel: str = "") -> dict:
    """Активное нативное Twitch-голосование (кэш 3с). None если нет/нет скоупа."""
    if not account_id or not channel:
        return {"poll": None}
    from app.twitch_polls import get_active_poll
    poll = await get_active_poll(account_id, channel)
    return {"poll": poll}


@admin_router.post("/api/widgets/twitch-poll")
async def twitch_poll_create(payload: dict) -> dict:
    from app.twitch_polls import create_poll
    return await create_poll(
        int(payload.get("account_id") or 0),
        str(payload.get("channel") or "").strip().lstrip("#"),
        str(payload.get("title") or ""),
        list(payload.get("choices") or []),
        int(payload.get("duration_seconds") or 120),
    )


@admin_router.post("/api/widgets/twitch-poll/end")
async def twitch_poll_end(payload: dict) -> dict:
    from app.twitch_polls import end_poll
    return await end_poll(
        int(payload.get("account_id") or 0),
        str(payload.get("channel") or "").strip().lstrip("#"),
    )


# ── Emotes (Twitch/BTTV/7TV) для emoji-chat ──────────────────────

_EMOTE_CACHE: dict[str, tuple[float, dict]] = {}
_EMOTE_TTL = 3600.0


async def _fetch_json(url: str) -> Any | None:
    try:
        import httpx
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    return None


def _bttv_url(id_: str) -> str:
    return f"https://cdn.betterttv.net/emote/{id_}/2x"


async def _twitch_global_emotes(token: str) -> dict:
    """Глобальные Twitch-эмоции через Helix (нужен любой валидный токен)."""
    out: dict[str, str] = {}
    try:
        import httpx
        from app.twitch_helix import HELIX_BASE, _client_id, _strip_oauth
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                f"{HELIX_BASE}/chat/emotes/global",
                headers={"Authorization": f"Bearer {_strip_oauth(token)}",
                         "Client-Id": _client_id()},
            )
            if resp.status_code == 200:
                for e in resp.json().get("data", []):
                    fmt = (e.get("format") or ["static"])[0]
                    theme = (e.get("theme_mode") or ["dark"])[0]
                    scale = (e.get("scale") or ["2.0"])[0]
                    url = (e.get("images", {}).get("url_1x") or
                           f"https://static-cdn.jtvnw.net/emoticons/v2/{e.get('id')}/{fmt}/{theme}/{scale}")
                    if e.get("name") and url:
                        out[e["name"]] = url
    except Exception:
        pass
    return out


async def _collect_emotes(channel: str) -> dict:
    """Карта code -> URL картинки: Twitch (если есть токен) + BTTV + 7TV."""
    emotes: dict[str, str] = {}
    # Twitch глобальные (по любому доступному аккаунтному токену)
    token = None
    try:
        from app.chat_analyzer import _account_token as _tok_map
        if hasattr(_tok_map, "get"):
            for aid in list(getattr(_tok_map, "keys", lambda: [])()):
                tok = _tok_map.get(aid)
                if tok:
                    token = tok
                    break
    except Exception:
        pass
    if token:
        emotes.update(await _twitch_global_emotes(token))
    # BTTV global
    data = await _fetch_json("https://api.betterttv.net/3/cached/emotes/global")
    if isinstance(data, list):
        for e in data:
            if e.get("code") and e.get("id"):
                emotes[e["code"]] = _bttv_url(e["id"])
    # BTTV channel (нужен twitch user id — берём через helix, если есть токен)
    try:
        if token and channel:
            from app.twitch_helix import get_user_id
            bid = await get_user_id(channel, token)
            if bid:
                data = await _fetch_json(f"https://api.betterttv.net/3/cached/users/twitch/{bid}")
                if isinstance(data, dict):
                    for key in ("channelEmotes", "sharedEmotes"):
                        for e in data.get(key) or []:
                            if e.get("code") and e.get("id"):
                                emotes[e["code"]] = _bttv_url(e["id"])
    except Exception:
        pass
    # 7TV global
    data = await _fetch_json("https://7tv.io/v3/emote-sets/global")
    if isinstance(data, dict):
        for e in data.get("emotes") or []:
            name = e.get("name")
            host = (e.get("data", {}) or {}).get("host", {}) or {}
            files = host.get("url") and host.get("files")
            if name and host.get("url") and files:
                webp = next((f["name"] for f in files if f.get("name") == "2x.webp"),
                            files[0]["name"] if files else None)
                if webp:
                    emotes[name] = f"https:{host['url']}/{webp}"
    return emotes


@public_router.get("/api/widgets/public/emotes")
async def emotes_public(channel: str = "") -> dict:
    """Карта эмодзи-кодов в URL картинок. Кэш 1ч (в памяти)."""
    channel = channel.lower().strip().lstrip("#")
    key = channel or "_global"
    now = time.time()
    cached = _EMOTE_CACHE.get(key)
    if cached and (now - cached[0]) < _EMOTE_TTL:
        return {"emotes": cached[1]}
    emotes = await _collect_emotes(channel)
    _EMOTE_CACHE[key] = (now, emotes)
    return {"emotes": emotes}


# §9.2 WIDGETS_PLAN: Emoji Chat — оверлей живого чата с цветными никами,
# эмодзи (unicode + Twitch/BTTV/7TV emote-картинки) сохраняются.
@public_router.get("/widget/emoji-chat", response_class=HTMLResponse)
async def widget_emoji_chat(theme: str = "dark", title: str = "") -> str:
    # Канал/максимум/ботов виджет берёт из query сам (?channel=&max=&bots=),
    # а тему подставляет роут: она нужна как CSS-класс до первой отрисовки.
    # Без подстановки в разметку уезжал литерал `__THEME__`, и темы
    # light/neon/fire/glass не применялись вообще.
    safe_theme = theme if theme in {"dark", "light", "neon", "fire", "glass"} else "dark"
    return _widget_html("emoji-chat").replace("__THEME__", safe_theme)


# ── Media-share: публичный переход к следующему треку ────────────


@public_router.post("/api/widgets/public/song-request/next")
async def song_request_next_public(
    account_id: int | None = None, channel: str | None = None,
) -> dict:
    """Для видео-виджета media-share (OBS): трек закончился → следующий.

    Публичный (как counter increment) — плеер в OBS не имеет auth-сессии.
    """
    return await sr_skip(account_id, channel)


# §4/§9.3 (решение владельца): роут видео-виджета media-share.
@public_router.get("/widget/media-share", response_class=HTMLResponse)
async def widget_media_share() -> str:
    return _widget_html("media-share")


# W9: OBS-only soundboard. Files are generated names under the active data root.

@admin_router.get("/api/widgets/soundboard/tracks")
async def soundboard_tracks() -> dict:
    from app.soundboard_library import list_tracks
    return {"items": await list_tracks()}

@admin_router.post("/api/widgets/soundboard/tracks")
async def soundboard_upload(request: Request) -> dict:
    from app.soundboard_library import store_uploads

    form = await request.form()
    uploads = [item for item in (*form.getlist("files"), *form.getlist("file")) if hasattr(item, "read")]
    try:
        return await store_uploads(uploads)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@public_router.get("/api/widgets/public/soundboard/tracks/{track_id}")
async def soundboard_audio(
    track_id: int, account_id: int | None = None, channel: str = "", token: str = "",
) -> Response:
    from app.widget_channel_scope import normalize_channel
    scoped = account_id is not None or bool(channel) or bool(token)
    if scoped:
        from app.moderator_sound_routes import valid_obs_token
        if account_id is None or not await valid_obs_token(account_id, channel, token):
            raise HTTPException(status_code=403, detail="invalid_obs_token")
    db = await get_db()
    try:
        if scoped:
            row = await (await db.execute(
                "SELECT t.filename,t.mime FROM soundboard_tracks t "
                "JOIN moderator_console_sound_approvals a ON a.track_id=t.id "
                "WHERE t.id=? AND a.account_id=? AND a.channel=? AND a.enabled=1",
                (track_id, account_id, normalize_channel(channel)),
            )).fetchone()
        else:
            row = await (await db.execute(
                "SELECT filename,mime FROM soundboard_tracks WHERE id=?", (track_id,)
            )).fetchone()
    finally: await db.close()
    from app.soundboard_library import track_file_path
    path = track_file_path(row["filename"]) if row else None
    if path is None:
        raise HTTPException(status_code=404, detail="track_not_found")
    return Response(path.read_bytes(), media_type=row["mime"], headers={"Cache-Control":"private,max-age=3600"})

async def soundboard_play(track_id: int, account_id: int, channel: str) -> dict:
    from app.soundboard_library import play_track
    scope = await _verified_widget_state_scope(account_id, channel)
    try:
        return await play_track(track_id, account_id=scope[0], channel=scope[1])
    except ValueError as exc:
        status = 404 if str(exc) in {"track_not_found", "track_file_missing"} else 409
        raise HTTPException(status_code=status, detail=str(exc)) from exc

@admin_router.post("/api/widgets/soundboard/play/{track_id}")
async def soundboard_play_route(track_id: int, account_id: int = 0, channel: str = "") -> dict:
    from app.widget_channel_scope import normalize_channel
    if account_id <= 0 or not normalize_channel(channel):
        raise HTTPException(status_code=400, detail="widget_scope_required")
    return await soundboard_play(track_id, account_id, channel)

# /api/widgets/soundboard/stop зарегистрирован в app/soundboard_routes.py
from app.soundboard_routes import stop_playback as soundboard_stop_route

@public_router.get("/widget/soundboard", response_class=HTMLResponse)
async def widget_soundboard(
    account_id: int | None = None, channel: str = "", token: str = "",
) -> str:
    if account_id is not None or channel or token:
        from app.moderator_sound_routes import valid_obs_token
        if account_id is None or not await valid_obs_token(account_id, channel, token):
            raise HTTPException(status_code=403, detail="invalid_obs_token")
    return _widget_html("soundboard")


@public_router.post("/api/widgets/public/soundboard/track-ended")
async def soundboard_track_ended(account_id: int = 0, channel: str = "", token: str = "") -> dict:
    from app.soundboard_library import finish_playback
    from app.widget_channel_scope import normalize_channel
    chan = normalize_channel(channel)
    if account_id <= 0 or not chan:
        raise HTTPException(status_code=400, detail="widget_scope_required")
    if token:
        from app.moderator_sound_routes import valid_obs_token
        if not await valid_obs_token(account_id, chan, token):
            raise HTTPException(status_code=403, detail="invalid_obs_token")
    return await finish_playback(account_id=account_id, channel=chan)
