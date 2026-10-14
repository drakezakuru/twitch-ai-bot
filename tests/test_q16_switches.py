"""Q16 (DEC-OWNER-016): глобальные рубильники Настроек убраны, всё per-бот.

F1: главный рубильник провокаций удалён из Настроек; вкл/выкл — только у бота
во вкладке «Характер» (``conflictEnabled``). Сохранённое глобальное значение
``provocations_master_enabled`` не удаляется — рантайм читает его как
legacy-fallback.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def test_f1_settings_card_removed():
    settings = _read("templates", "partials", "settings.html")
    assert 'id="provocationsMaster"' not in settings
    assert "settings.provocations_master" not in settings
    # per-бот тумблер на месте (вкладка «Характер»)
    bots = _read("templates", "partials", "bots.html")
    assert 'id="conflictEnabled"' in bots


def test_f1_js_and_routes_removed():
    extras = _read("static", "app", "12_dashboard_extras.js")
    assert "loadProvocationsMaster" not in extras and "saveProvocationsMaster" not in extras
    chat = _read("static", "app", "04_chat_settings.js")
    assert "loadProvocationsMaster" not in chat
    routes = _read("app", "routes.py")
    assert '"/api/settings/provocations-master"' not in routes
    # legacy-значение читает рантайм, а не удаляется
    analyzer = _read("app", "chat_analyzer.py")
    assert '"provocations_master_enabled"' in analyzer


def test_f1_i18n_keys_removed_in_all_languages():
    js = _read("static", "app.js")
    for key in ("'settings.provocations_master':", "'settings.provocations_master_hint':"):
        assert js.count(key) == 0, key

def test_f3_global_tts_section_removed():
    settings = _read("templates", "partials", "settings.html")
    assert 'id="globalTTSProvider"' not in settings
    assert "settings.tts_global" not in settings
    # карта озвучки переехала в карточку бота
    bots = _read("templates", "partials", "bots.html")
    assert 'id="ttsRoutingMap"' in bots
    assert 'id="ttsRoutingMap"' not in settings
    js = _read("static", "app", "04_chat_settings.js")
    assert "saveGlobalTTS" not in js
    assert "function loadTTSRoutingMap(" in js
    # endpoint остался для онбординга и как legacy-fallback рантайма
    routes = _read("app", "routes_tts_config.py")
    assert '"/api/tts/config"' in routes

def test_f4_moderator_tts_console_lives_in_bot_card_only():
    settings = _read("templates", "partials", "settings.html")
    bots = _read("templates", "partials", "bots.html")
    assert 'id="moderatorTTSAdminCard"' in bots, "консоль в карточке бота-модератора"
    assert 'id="moderatorTTSAdminCard"' not in settings
    # карточка лежит внутри botTab-moderation
    tab = bots.split('id="botTab-moderation"', 1)[1]
    assert 'id="moderatorTTSAdminCard"' in tab.split('id="botTab-chat-users"', 1)[0]
    js = _read("static", "app", "04_chat_settings.js")
    assert "loadModeratorTTSAdmin();" not in js.split("function loadModeratorTTSAdmin", 1)[0].split("async function loadSettings", 1)[-1], \
        "loadSettings больше не тянет консоль"
    loader = _read("static", "app", "08_providers_moderation.js")
    assert "loadModeratorTTSAdmin()" in loader.split("async function loadBotModeration", 1)[1].split("}", 1)[0]

def test_f5_replay_auto_record_is_per_bot():
    settings = _read("templates", "partials", "settings.html")
    assert 'id="replayAutoRecord"' not in settings, "глобальный рубильник убран"
    bots = _read("templates", "partials", "bots.html")
    assert 'id="botReplayAutoRecord"' in bots
    extras = _read("static", "app", "12_dashboard_extras.js")
    assert "loadReplayAutoSetting" not in extras and "saveReplayAutoSetting" not in extras
    # per-бот API и резолв в bot_manager (явный выбор бота сильнее глобального fallback)
    wave = _read("app", "routes_wave4.py")
    assert '"/api/accounts/{account_id}/replay-settings"' in wave
    manager = _read("app", "bot_manager.py")
    assert "replay_auto_record FROM accounts" in manager
    # глобальный маршрут остался legacy-fallback, значение не удаляется
    routes = _read("app", "routes.py")
    assert '"/api/settings/replay-auto-record"' in routes
