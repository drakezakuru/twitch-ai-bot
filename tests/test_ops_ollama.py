"""Focused immutable-image and non-generative health contracts for Ollama."""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IMAGE = "ollama/ollama:0.33.3@sha256:32931b46719f673c05fdbaa81ccb26da18ea4a1c57590a754874ab28ba269eb2"


def test_ollama_image_is_pinned_by_version_and_digest_in_all_compose_files():
    for name in ("docker-compose.yml", "docker-compose.prod.yml"):
        text = (ROOT / name).read_text(encoding="utf-8")
        images = re.findall(r"^\s*image:\s*(ollama/ollama:\S+)$", text, re.MULTILINE)
        assert images == [IMAGE], name
        assert "ollama/ollama:latest" not in text


def test_ollama_healthcheck_does_not_pull_or_run_a_model():
    for name in ("docker-compose.yml", "docker-compose.prod.yml"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert 'test: ["CMD", "ollama", "list"]' in text
        assert "ollama pull" not in text
        assert "ollama run" not in text
