"""DEC-DIRECTOR-009 / DEC-BOTS-004 offline UI behavior; no browser or providers."""
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_director_review_and_role_visibility_runtime():
    subprocess.run(
        ["node", "--test", "tests/director_review_ui.test.js", "tests/role_visibility_ui.test.js",
         "tests/panel_lurker_ui.test.js", "tests/director_storage_ui.test.js", "tests/director_page_ui.test.js"],
        cwd=ROOT, check=True, timeout=30,
    )
