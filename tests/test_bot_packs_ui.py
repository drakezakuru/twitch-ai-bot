"""Q34a anchors: pack editor UI offline behavior + template wiring; no browser."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_bot_pack_editor_runtime():
    subprocess.run(
        ["node", "--test", "tests/bot_packs_ui.test.js"],
        cwd=ROOT, check=True, timeout=30,
    )


def test_bot_pack_template_and_api_wiring():
    template = (ROOT / "templates/partials/bots.html").read_text(encoding="utf-8")
    bots_js = (ROOT / "static/app/03_bots.js").read_text(encoding="utf-8")
    assert "showBotPackModal()" in template and 'id="botPackModal"' in template
    assert 'id="botPacksList"' in template and 'id="botPackBots"' in template
    assert "botPackSearch" in template and "botPackSelectAll" in template
    # CRUD module is registered on the server and loads with the bots list.
    server = (ROOT / "app/server.py").read_text(encoding="utf-8")
    assert "from app.bot_packs import router as _bot_packs_router" in server
    assert "await ensure_join_worker()" in server  # Q34c resumes queued joins after restart
    assert "loadBotPacks()" in bots_js
    database = (ROOT / "app/database.py").read_text(encoding="utf-8")
    assert "ensure_bot_packs_schema" in database
