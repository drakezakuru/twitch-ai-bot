"""Focused runtime guard for the browser-only shared TTS transport."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_tts_core_browser_transport():
    result = subprocess.run(
        ["node", "--test", "tests/tts_core_transport.test.js"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


# ── OmniVoice optional provider (fake-QA without model download) ──

@pytest.mark.asyncio
async def test_omnivoice_provider_lazy_and_falls_back():
    from app.tts_engine import OmniVoiceProvider, TTSEngine
    provider = OmniVoiceProvider()
    # License confirmed by the owner (10.09, see omnivoice/LICENSE_REVIEW.md): the gate
    # is open, but the optional package is absent in the panel env — synthesize must
    # fail cleanly so the engine falls back to Piper/Web Speech.
    assert OmniVoiceProvider.weights_license_confirmed is True
    with pytest.raises(RuntimeError, match="not available"):
        await provider.synthesize("тест", "voice", "neutral", 1.0)
    engine = TTSEngine()
    assert "omnivoice" in engine._providers
    # Lazy load is a no-op (no torch import, no panel blocking) and never raises.
    provider._load_model()
    assert provider._model is None and provider._load_failed is True
