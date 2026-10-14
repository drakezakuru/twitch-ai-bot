from __future__ import annotations

import importlib.util
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("run_qa_panel", ROOT / "scripts" / "run_qa_panel.py")
assert SPEC and SPEC.loader
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


def test_prepare_environment_removes_credentials_and_scopes_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("TWITCH_TOKEN", "real-token")
    monkeypatch.setenv("TWITCH_CLIENT_SECRET", "real-secret")
    monkeypatch.setenv("OPENROUTER_API_KEY", "real-key")
    monkeypatch.setenv("PANEL_AUTH_USER", "owner")
    monkeypatch.setenv("PANEL_AUTH_PASS", "password")
    monkeypatch.setenv("SAFE_UNRELATED_VALUE", "kept")

    removed = RUNNER._prepare_environment(tmp_path)

    assert {"TWITCH_TOKEN", "TWITCH_CLIENT_SECRET", "OPENROUTER_API_KEY", "PANEL_AUTH_PASS"} <= set(removed)
    assert os.environ["SAFE_UNRELATED_VALUE"] == "kept"
    assert os.environ["TWITCH_BOT_DATA_DIR"] == str(tmp_path)
    assert os.environ["BOT_LOCKS_DIR"] == str(tmp_path / "locks")
    assert os.environ["PYTHON_DOTENV_DISABLED"] == "1"
    assert os.environ["PANEL_AUTH_USER"] == ""
    assert os.environ["PANEL_AUTH_PASS"] == ""
    assert os.environ["OLLAMA_HOST"] == "http://127.0.0.1:9"
