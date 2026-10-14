"""P8-C8/W3: прописи ролей + публичный chat/TTS companion + подпись провайдера.

voice_companion наблюдает стрим и чат, пишет в публичный Twitch-чат через
общую chat_out-цепочку и озвучивает отправленные реплики по tts_reply_percent.
"""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).parent.parent


def test_role_descriptions_rewritten():
    js = (ROOT / "static" / "app" / "06_roles.js").read_text(encoding="utf-8")
    for key in ("role.desc.chatter", "role.desc.moderator",
                "role.desc.voice_companion", "role.desc.lurker"):
        assert f"'{key}':" in js
    # новые прописи содержат человеческое объяснение пользы
    assert "Собеседник в чате (озвучиваемый)" in js
    assert "публичном Twitch-чате" in js
    assert "tts_reply_percent" not in js  # UI points to the existing human-facing TTS percentage, no duplicate field
    assert "Модерирует чат" in js
    assert "Non-AI наблюдатель" in js
    assert "viewer memory" not in js
    assert "база знаний для других ботов" not in js
    assert "Живой зритель в чате" in js


def test_lurker_panel_has_group_and_minimum_settings():
    bots_js = (ROOT / "static" / "app" / "03_bots.js").read_text(encoding="utf-8")
    template = (ROOT / "templates" / "partials" / "bots.html").read_text(encoding="utf-8")
    app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

    assert 'bot.bot_role || \'chatter\') === \'lurker\'' in bots_js
    assert 'class="bot-role-section" open' in bots_js
    assert "roleSlotOverview" in bots_js
    assert "botRoleAllowsTab" in bots_js and "botQuickBehaviorCard" in bots_js
    assert 'id="roleSlotOverview"' in template
    assert 'id="botQuickBehaviorCard"' in template
    for text in ("Луркеры", "Lurkers", "Луркери"):
        assert text in app_js


def test_lurker_panel_runtime_behavior():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for panel behavior tests")
    subprocess.run([node, "--test", "tests/panel_lurker_ui.test.js"], cwd=ROOT, check=True)


def test_companion_scope_default_and_validation():
    from app.bot_roles import ROLE_DEFAULT_CONFIGS, load_role_config, validate_role_config
    cfg = load_role_config(None, "voice_companion")
    assert cfg["companion_scope"] == "channel_chat"
    clean = validate_role_config("voice_companion", {"companion_scope": "channel_chat"})
    assert clean["companion_scope"] == "channel_chat"


def test_role_gate_allows_chat_for_companion():
    src = (ROOT / "app" / "chat_analyzer.py").read_text(encoding="utf-8")
    assert 'if role == "voice_companion":\n            return True' in src


def test_sandbox_verdict_uses_public_chat_and_existing_tts_percent():
    src = (ROOT / "app" / "role_routes.py").read_text(encoding="utf-8")
    assert "публичный Twitch-чат" in src
    assert "tts_reply_percent" in src
    assert "в чат не пишет" not in src


def test_summaries_have_provider_label():
    src = (ROOT / "app" / "summarizer.py").read_text(encoding="utf-8")
    assert "Сводка сгенерирована провайдером" in src
    routes = (ROOT / "app" / "routes_ai_summary.py").read_text(encoding="utf-8")
    assert "provider_label" in routes


def test_role_names_consistent():
    js = (ROOT / "static" / "app" / "06_roles.js").read_text(encoding="utf-8")
    for key in ("role.name.chatter", "role.name.moderator",
                "role.name.voice_companion", "role.name.lurker"):
        assert f"'{key}':" in js
