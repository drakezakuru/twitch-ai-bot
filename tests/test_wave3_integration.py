"""Integration tests for v10.4.6 Wave 3 features (voice cloning).

Note: VOD RAG tests were removed when the feature was deleted as dead code
(see PLAN_ALL_IN_ONE.md §22, FEATURE_OWNERSHIP.md §16).
"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_chat_analyzer_has_wave3_defaults():
    from app.server import chat_analyzer

    s = chat_analyzer.get_settings(account_id=8888888)
    assert s["voice_clone_enabled"] is False
    assert s["voice_clone_model_name"] == ""


def test_routes_expose_wave3_endpoints():
    from app import routes

    paths = {getattr(r, "path", "") for r in routes.router.routes}
    assert "/api/voice-clone/models" in paths
    assert "/api/voice-clone/upload" in paths
    assert "/api/voice-clone/setup-guide" in paths
    assert "/api/voice-clone/models/{name}" in paths


def test_voice_clone_module_imports():
    from app import voice_clone

    assert hasattr(voice_clone, "save_voice_model_files")
    assert hasattr(voice_clone, "list_voice_models")
    assert hasattr(voice_clone, "select_voice_for_account")
    assert hasattr(voice_clone, "piper_command_for_model")


def test_tts_exposes_optional_local_clone_provider():
    from app.tts_engine import XTTSProvider

    provider = XTTSProvider("/tmp/missing-sample.wav")
    assert provider.language == "ru"


def test_routes_expose_clone_preview_endpoint():
    from app import routes

    paths = {getattr(r, "path", "") for r in routes.router.routes}
    assert "/api/voice-clones/{clone_id}/preview" in paths
