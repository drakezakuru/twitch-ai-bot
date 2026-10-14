from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_bot_check_controls_and_reports_are_wired():
    js = (ROOT / "static/app/03_bots.js").read_text(encoding="utf-8")
    template = (ROOT / "templates/partials/bots.html").read_text(encoding="utf-8")

    assert "showBotCheckModal()" in js
    assert "POST', {\n            account_ids: [..._selectedBots]" in js
    assert "/api/bot-checks/${_botCheckId}/cancel" in js
    assert "downloadBotCheck('csv')" in template
    assert "downloadBotCheck('text')" in template
    assert 'aria-live="polite"' in template


def test_bot_check_i18n_keys_exist_in_all_languages():
    source = (ROOT / "static/app.js").read_text(encoding="utf-8")
    for key in (
        "check.title", "check.hint", "check.channel", "check.message",
        "check.running", "check.download_csv", "check.download_text",
        "check.value.not_confirmed", "check.reason.no_messages",
        "check.reason.send_rejected",
    ):
        assert source.count(f"'{key}'") == 3

