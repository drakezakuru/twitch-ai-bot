"""Launcher flags and operator-facing path contracts."""

from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import uuid

import pytest

import run


def _requirements(path: str) -> set[str]:
    return {
        line.split("#", 1)[0].strip().lower()
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.split("#", 1)[0].strip()
    }


def test_no_browser_flag_and_start_script_environment_disable_browser(monkeypatch):
    monkeypatch.delenv("TWITCH_BOT_NO_BROWSER", raising=False)
    assert run.should_open_browser([])
    assert not run.should_open_browser(["--no-browser"])

    monkeypatch.setenv("TWITCH_BOT_NO_BROWSER", "1")
    assert not run.should_open_browser([])


def test_panel_log_is_the_canonical_operator_path():
    source = Path("run.py").read_text(encoding="utf-8")

    assert run.LOG_FILE.as_posix() == "logs/panel.log"
    assert "logs/bot.log" not in source


def test_launcher_defaults_to_loopback_and_network_needs_auth_plus_encryption(monkeypatch):
    monkeypatch.delenv("PANEL_BIND_HOST", raising=False)
    monkeypatch.delenv("QA_PROFILE", raising=False)
    assert run.resolve_panel_host(encryption_enabled=False, auth_enabled=False) == "127.0.0.1"
    assert run.resolve_panel_host("0.0.0.0", encryption_enabled=False, auth_enabled=False) == "127.0.0.1"
    assert run.resolve_panel_host("0.0.0.0", encryption_enabled=True, auth_enabled=False) == "127.0.0.1"
    assert run.resolve_panel_host("0.0.0.0", encryption_enabled=False, auth_enabled=True) == "127.0.0.1"
    assert run.resolve_panel_host("0.0.0.0", encryption_enabled=True, auth_enabled=True) == "0.0.0.0"

    monkeypatch.setenv("QA_PROFILE", "1")
    assert run.resolve_panel_host("0.0.0.0", encryption_enabled=False, auth_enabled=False) == "0.0.0.0"


def test_ml_dependencies_are_explicitly_optional():
    core = _requirements("requirements.txt")
    ml = _requirements("requirements-ml.txt")

    assert not any("whisper" in item or "speechbrain" in item for item in core)
    assert "-r requirements.lock" in ml
    assert any(item.startswith("openai-whisper") for item in ml)
    assert any(item.startswith("speechbrain") for item in ml)

    for launcher in ("start.sh", "start.bat"):
        source = Path(launcher).read_text(encoding="utf-8")
        assert "--ml" in source
        assert "requirements-ml.txt" in source


def test_installers_do_not_bypass_runtime_manifest():
    for launcher in ("start.sh", "start.bat"):
        source = Path(launcher).read_text(encoding="utf-8").lower()
        assert "pip install -r requirements.lock" in source
        assert "pip install streamlink" not in source
        assert "pip install certifi" not in source

    dockerfile = Path("Dockerfile").read_text(encoding="utf-8").lower()
    assert "pip install --no-cache-dir -r requirements.lock" in dockerfile
    assert "requirements.txt streamlink" not in dockerfile


def test_docker_build_context_excludes_local_secrets_and_runtime_data(tmp_path):
    patterns = {
        line.strip()
        for line in Path(".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert {
        ".env", ".env.*", "!.env.example", ".git", ".hoplite", ".venv",
        "*.db", "*.db-*", "*.log", "artifacts", "data", "logs",
    } <= patterns

    docker = shutil.which("docker")
    if not docker:
        pytest.skip("Docker is required for build-context behavior verification")
    probe = subprocess.run(
        [docker, "info"], capture_output=True, text=True, timeout=20,
    )
    if probe.returncode:
        pytest.skip("Docker daemon is unavailable")

    context = tmp_path / "context"
    context.mkdir()
    (context / ".dockerignore").write_text(
        Path(".dockerignore").read_text(encoding="utf-8"), encoding="utf-8",
    )
    (context / "Dockerfile").write_text(
        "FROM scratch\nCOPY . /context\n", encoding="utf-8",
    )
    (context / "safe.txt").write_text("safe", encoding="utf-8")
    (context / ".env.example").write_text("SAFE_EXAMPLE=1", encoding="utf-8")
    sensitive = (
        ".env", ".env.local", ".git/config", ".hoplite/archive/state",
        ".venv/lib/token", "data/bot.db", "logs/panel.log", "artifacts/report.json",
    )
    for relative in sensitive:
        path = context / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not-for-image", encoding="utf-8")

    image = f"hoplite-dockerignore-test:{uuid.uuid4().hex}"
    container_id = ""
    try:
        build = subprocess.run(
            [docker, "build", "--quiet", "--tag", image, str(context)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if (
            "Hoplite Docker policy rejected" in build.stderr
            or "/var/run/hoplite-docker.sock" in build.stderr
        ):
            pytest.skip("Sandbox policy blocks Docker build API requests")
        build.check_returncode()
        container_id = subprocess.run(
            [docker, "create", image], check=True, capture_output=True,
            text=True, timeout=20,
        ).stdout.strip()
        copied = tmp_path / "copied-context"
        copied.mkdir()
        subprocess.run(
            [docker, "cp", f"{container_id}:/context/.", str(copied)],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
    finally:
        if container_id:
            subprocess.run(
                [docker, "rm", "--force", container_id], capture_output=True, timeout=20,
            )
        subprocess.run(
            [docker, "image", "rm", "--force", image], capture_output=True, timeout=20,
        )

    assert (copied / "safe.txt").read_text(encoding="utf-8") == "safe"
    assert (copied / ".env.example").is_file()
    for relative in sensitive:
        assert not (copied / relative).exists(), relative


def test_browser_smoke_missing_playwright_exit_contract(monkeypatch):
    import builtins
    import sys

    from scripts import browser_smoke

    real_import = builtins.__import__

    def import_without_playwright(name, *args, **kwargs):
        if name == "playwright.sync_api":
            raise ImportError("simulated missing optional dependency")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_playwright)
    monkeypatch.setattr(sys, "argv", ["browser_smoke.py"])
    assert browser_smoke.main() == 2


def test_core_lock_pins_every_direct_dependency_and_optional_manifests_reuse_it():
    direct = {
        re.split(r"[<>=!~\[\s]", item, maxsplit=1)[0]
        for item in _requirements("requirements.txt")
    }
    lock_lines = [
        line.strip().lower()
        for line in Path("requirements.lock").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith(("#", " "))
    ]
    assert lock_lines and all("==" in line for line in lock_lines)
    locked = {re.split(r"[=\s]", line, maxsplit=1)[0] for line in lock_lines}
    assert direct <= locked

    for manifest in ("requirements-dev.txt", "requirements-ml.txt"):
        assert "-r requirements.lock" in _requirements(manifest)
