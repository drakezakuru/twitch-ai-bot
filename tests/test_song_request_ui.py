"""Owner UI contract for Track 6.7 Song Request policy and audit."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PANEL = (ROOT / "templates/partials/widgets.html").read_text(encoding="utf-8")
WIDGET_JS = (ROOT / "static/app/07_widgets.js").read_text(encoding="utf-8")
SESSION_JS = (ROOT / "static/app/13_widgets_session.js").read_text(encoding="utf-8")
APP_JS = (ROOT / "static/app.js").read_text(encoding="utf-8")


def test_owner_ui_exposes_scoped_policy_and_audit() -> None:
    for element_id in (
        "waSrMaxQueue",
        "waSrPointsCreateId",
        "waSrPointsPriorityId",
        "waSrDonationEnabled",
        "waSrDonationThreshold",
        "waSrDonationCurrency",
        "waSrDonationAction",
        "waSrAudit",
    ):
        assert f'id="{element_id}"' in PANEL

    assert "wstateapi('/api/widgets/song-request/entitlements')" in WIDGET_JS
    assert "wstateapi('/api/widgets/song-request/entitlements', 'PUT'" in WIDGET_JS
    assert "wstateapi('/api/widgets/song-request/audit')" in WIDGET_JS
    assert "waLoadSr()" in SESSION_JS


def test_owner_ui_discloses_logical_playback_and_non_refundable_events() -> None:
    assert 'data-i18n="song_request.playback_hint"' in PANEL
    assert 'data-i18n="song_request.entitlements_hint"' in PANEL
    assert 'data-i18n="song_request.audit_hint"' in PANEL
    for key in (
        "song_request.playback_hint",
        "song_request.entitlements_hint",
        "song_request.audit_hint",
        "song_request.max_queue",
    ):
        assert APP_JS.count(f"'{key}'") == 3
