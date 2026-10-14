from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_global_privacy_mode_is_removed():
    sources = []
    for root in (ROOT / "static", ROOT / "templates"):
        for path in root.rglob("*"):
            if path.is_file():
                try:
                    sources.append(path.read_text(encoding="utf-8"))
                except UnicodeDecodeError:
                    continue  # бинарные ассеты (favicon.ico и т.п.) — не исходники
    sources = "\n".join(sources)
    for needle in (
        "privacyModeBtn",
        "togglePrivacyMode",
        "applyPrivacyMode",
        "PRIVACY_STORAGE_KEY",
        "privacy-mode",
        "privacy.hide",
        "privacy.show",
    ):
        assert needle not in sources


def test_sensitive_inputs_remain_password_fields():
    html = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "templates").rglob("*.html")
    )
    for field_id in ("newBotToken", "twitchClientSecret", "cpApiKey"):
        assert f'type="password" id="{field_id}"' in html
