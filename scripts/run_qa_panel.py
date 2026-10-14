#!/usr/bin/env python3
"""Run the panel against a verified offline fake-data profile."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

_PROFILE_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_SECRET_NAME_MARKERS = ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "AUTH_PASS", "CLIENT_ID")


def _prepare_environment(root: Path) -> list[str]:
    removed: list[str] = []
    for key in tuple(os.environ):
        if any(marker in key.upper() for marker in _SECRET_NAME_MARKERS):
            removed.append(key)
            os.environ.pop(key, None)

    values = {
        "TWITCH_BOT_DATA_DIR": str(root),
        "BOT_LOCKS_DIR": str(root / "locks"),
        "VOICE_MODELS_DIR": str(root / "voice_models"),
        "VOICE_CLONES_DIR": str(root / "voice_clones"),
        "FRAMES_DIR": str(root / "stream_vision_frames"),
        "AUTO_BACKUP_DIR": str(root / "backups"),
        "PYTHON_DOTENV_DISABLED": "1",
        "QA_PROFILE": "1",
        "PANEL_ALLOW_INSECURE_LOCAL": "1",
        "PANEL_AUTH_USER": "",
        "PANEL_AUTH_PASS": "",
        "AI_PROVIDER": "ollama",
        "OLLAMA_HOST": "http://127.0.0.1:9",
    }
    os.environ.update(values)
    return sorted(removed)


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline panel backed by deterministic fake data")
    parser.add_argument("--profile", default="local")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--check", action="store_true", help="verify isolation without starting server")
    args = parser.parse_args()
    if not _PROFILE_NAME_RE.fullmatch(args.profile or ""):
        parser.error("unsafe profile name")

    root = (PROJECT_ROOT / "data" / "qa-profiles" / args.profile).resolve()
    removed = _prepare_environment(root)

    from app.qa_profile import verify_profile

    manifest = verify_profile(args.profile)
    print(
        f"QA profile '{args.profile}' verified: {manifest['fingerprint']} "
        f"(removed {len(removed)} inherited credential variables)",
        flush=True,
    )
    if args.check:
        return 0

    import uvicorn

    uvicorn.run("app.server:app", host=args.host, port=args.port, reload=False, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
