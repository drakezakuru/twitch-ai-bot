import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_channels_navigation_and_both_bulk_directions_are_wired():
    base = (ROOT / "templates/base.html").read_text(encoding="utf-8")
    template = (ROOT / "templates/partials/channels.html").read_text(encoding="utf-8")
    bots_js = (ROOT / "static/app/03_bots.js").read_text(encoding="utf-8")
    channels_js = (ROOT / "static/app/19_channels_bulk.js").read_text(encoding="utf-8")

    assert 'data-section="channels"' in base
    assert "partials/channels.html" in base
    assert "/static/app/19_channels_bulk.js" in base
    assert "openBotsToChannelsBulk()" in bots_js
    assert "function openChannelToBotsBulk(channel)" in channels_js
    assert "direction: _bulkDirection" in channels_js
    assert "downloadBulkChannels('csv')" in template
    assert "downloadBulkChannels('text')" in template
    assert 'aria-live="polite"' in template


def test_channels_and_bulk_i18n_keys_exist_in_all_languages():
    source = (ROOT / "static/app.js").read_text(encoding="utf-8")
    for key in (
        "nav.channels", "channels.title", "channels.hint", "channels.connected_count",
        "bulk.title", "bulk.hint", "bulk.bots_hint", "bulk.channels_hint",
        "bulk.start", "bulk.running", "bulk.value.added", "bulk.value.skipped",
        "bulk.reason.already_exists", "bulk.error.too_many_pairs",
    ):
        assert source.count(f"'{key}'") >= 3



def test_bulk_change_channel_ui_and_backend_are_wired():
    bots_js = (ROOT / "static/app/03_bots.js").read_text(encoding="utf-8")
    channels_js = (ROOT / "static/app/19_channels_bulk.js").read_text(encoding="utf-8")
    backend = (ROOT / "app/bulk_channels_routes.py").read_text(encoding="utf-8")

    # Кнопка в bulk-bar и диалог смены канала (Q08в, DEC-OWNER-006).
    assert "openBulkChangeChannel()" in bots_js
    assert "function openBulkChangeChannel()" in channels_js
    assert "startBulkChangeChannel()" in channels_js
    assert "pollBulkChangeChannel" in channels_js
    assert "id=\"bulkChangeReplace\"" in channels_js
    # Бэкенд-эндпоинт и per-item отчёт.
    assert '"/api/bulk/change-channel"' in backend
    assert "async def start_bulk_change_channel" in backend
    assert '"direction": "change_channel"' in backend


def test_bulk_change_channel_i18n_keys_exist_in_all_languages():
    source = (ROOT / "static/app.js").read_text(encoding="utf-8")
    for key in (
        "bulk.change_channel", "bulk.change_apply", "bulk.change_new",
        "bulk.change_need_channel", "bulk.change_replace", "bulk.change_hint",
        "bulk.change_done", "bulk.value.changed", "bulk.reason.ok",
        "bulk.reason.binding_disabled", "bulk.reason.change_failed",
    ):
        assert source.count(f"'{key}'") >= 3


def test_check_message_is_optional_and_off_by_default():
    """Q07/DEC-OWNER-011: чекбокс контрольного сообщения по умолчанию ВЫКЛ."""
    bots_html = (ROOT / "templates/partials/bots.html").read_text(encoding="utf-8")
    channels_html = (ROOT / "templates/partials/channels.html").read_text(encoding="utf-8")
    bots_js = (ROOT / "static/app/03_bots.js").read_text(encoding="utf-8")
    bulk_js = (ROOT / "static/app/19_channels_bulk.js").read_text(encoding="utf-8")
    app_js = (ROOT / "static/app.js").read_text(encoding="utf-8")

    for html, enabled_id in ((bots_html, "botCheckSendEnabled"), (channels_html, "bulkCheckSendEnabled")):
        assert f'id="{enabled_id}"' in html
        assert "check.send_enabled" in html
        for message_id in ("bulkCheckMessage", "botCheckMessage"):
            if f'id="{message_id}"' in html:
                assert re.search(rf'id="{message_id}"[^>]*disabled', html), message_id
    assert "botCheckSendEnabled').checked = false" in bots_js
    assert "bulkCheckSendEnabled').checked = false" in bulk_js
    assert "send_message: sendEnabled" in bots_js and "send_message: sendEnabled" in bulk_js
    assert "send_message=job[\"send_message\"]" in (ROOT / "app/bulk_channels_routes.py").read_text(encoding="utf-8")
    assert app_js.count("'check.send_enabled'") >= 3
