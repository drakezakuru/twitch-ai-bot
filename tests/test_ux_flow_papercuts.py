"""Focused regression checks for high-frequency panel interactions."""
from pathlib import Path

from tests import _panel_js


ROOT = Path(__file__).resolve().parents[1]


def test_global_search_supports_every_panel_section_and_locale():
    js = _panel_js.panel_js()
    assert "const GLOBAL_SECTION_SEARCH_KEYS" in js
    for section in ("dashboard", "bots", "chat", "analytics", "brain", "settings", "widgets", "chatlogger"):
        assert f"{section}:" in js
    assert "Object.values(LANGS)" in js
    assert "await api('/api/accounts')" in js


def test_chat_requires_a_specific_destination_before_sending():
    html = (ROOT / "templates" / "partials" / "chat.html").read_text(encoding="utf-8")
    js = _panel_js.panel_js()
    assert 'id="chatSendButton"' in html
    assert "function syncChatComposer()" in js
    assert "input.disabled = !enabled" in js
    assert "button.disabled = !enabled" in js
    assert "if (!channel) { toast(t('chat.select_channel'), 'error'); return; }" in js
    for key in ("chat.select_bot", "chat.select_channel"):
        assert js.count(f"'{key}'") >= 3
