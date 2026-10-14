"""Repository runtime paths with an opt-in isolated data root."""

from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def data_root() -> Path:
    configured = os.getenv("TWITCH_BOT_DATA_DIR", "").strip()
    return Path(configured).expanduser().resolve() if configured else PROJECT_ROOT / "data"


DATA_ROOT = data_root()
DB_PATH = DATA_ROOT / "bot.db"
BOTS_ROOT = DATA_ROOT / "bots"
WIDGETS_ROOT = DATA_ROOT / "widgets"
SOUNDBOARD_DIR = WIDGETS_ROOT / "soundboard"
LEGACY_SOUNDBOARD_DIR = DATA_ROOT / "soundboard"
MODERATOR_MEDIA_ROOT = DATA_ROOT / "moderator-media"
BLUR_GUARD_DIR = DATA_ROOT / "blur-guard"
VOICE_CONTROL_DIR = DATA_ROOT / "voice-control"
