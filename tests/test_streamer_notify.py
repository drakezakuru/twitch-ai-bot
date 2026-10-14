"""Tests for v10.4.7 Wave 4.5 — bot-to-streamer DM."""

from pathlib import Path

import pytest

from app.streamer_notify import (
    NotifySettings,
    RateLimiter,
    format_discord_payload,
    format_telegram_text,
    _md_escape,
)


def test_severity_filter_info_passes():
    s = NotifySettings(min_severity="info")
    assert s.severity_passes("info") is True
    assert s.severity_passes("warning") is True
    assert s.severity_passes("highlight") is True


def test_severity_filter_warning_blocks_info():
    s = NotifySettings(min_severity="warning")
    assert s.severity_passes("info") is False
    assert s.severity_passes("warning") is True
    assert s.severity_passes("highlight") is True


def test_severity_filter_highlight_only():
    s = NotifySettings(min_severity="highlight")
    assert s.severity_passes("info") is False
    assert s.severity_passes("warning") is False
    assert s.severity_passes("highlight") is True


def test_rate_limiter_allows_up_to_max():
    rl = RateLimiter(window_sec=60, max_per_window=3)
    assert rl.allow(now=1000.0) is True
    assert rl.allow(now=1001.0) is True
    assert rl.allow(now=1002.0) is True
    assert rl.allow(now=1003.0) is False


def test_rate_limiter_resets_after_window():
    rl = RateLimiter(window_sec=60, max_per_window=2)
    assert rl.allow(now=1000.0) is True
    assert rl.allow(now=1001.0) is True
    assert rl.allow(now=1002.0) is False
    # после window
    assert rl.allow(now=1100.0) is True


def test_format_discord_payload_structure():
    p = format_discord_payload("warning", "Toxic viewer", "user X плохо ведёт себя", channel="streamer1")
    assert "content" in p
    assert "embeds" in p
    assert p["embeds"][0]["title"] == "Toxic viewer"
    assert "streamer1" in p["content"]


def test_format_discord_payload_color_info():
    p = format_discord_payload("info", "t", "b")
    assert p["embeds"][0]["color"] == 0x5865F2


def test_format_telegram_text_contains_title():
    text = format_telegram_text("highlight", "Clip это", "интересный момент", channel="ch")
    assert "Clip" in text
    assert "ch" in text


def test_md_escape_escapes_specials():
    assert _md_escape("test.text!") == "test\\.text\\!"
    assert _md_escape("[link]") == "\\[link\\]"


def test_md_escape_empty():
    assert _md_escape("") == ""


@pytest.mark.asyncio
async def test_panel_note_save_list_read_delete(tmp_path, monkeypatch):
    db_path = tmp_path / "panel_notes.db"
    import app.database as db_mod

    monkeypatch.setattr(db_mod, "DB_PATH", db_path)
    monkeypatch.setattr(db_mod, "_shared_db", None)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    from app.streamer_notify import (
        save_panel_note, list_panel_notes,
        mark_panel_note_read, delete_panel_note,
    )

    nid = await save_panel_note(account_id=1, channel="ch", severity="info", title="t1", body="b1")
    assert nid > 0
    notes = await list_panel_notes(account_id=1)
    assert len(notes) == 1
    assert notes[0]["title"] == "t1"
    assert notes[0]["read_at"] is None

    await mark_panel_note_read(nid)
    notes = await list_panel_notes(account_id=1)
    assert notes[0]["read_at"] is not None

    await delete_panel_note(nid)
    notes = await list_panel_notes(account_id=1)
    assert len(notes) == 0


@pytest.mark.asyncio
async def test_panel_notes_filter_unread(tmp_path, monkeypatch):
    db_path = tmp_path / "panel_notes2.db"
    import app.database as db_mod

    monkeypatch.setattr(db_mod, "DB_PATH", db_path)
    monkeypatch.setattr(db_mod, "_shared_db", None)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    from app.streamer_notify import (
        save_panel_note, list_panel_notes, mark_panel_note_read,
    )
    a = await save_panel_note(2, "x", "info", "a", "a")
    b = await save_panel_note(2, "x", "info", "b", "b")
    await mark_panel_note_read(a)
    unread = await list_panel_notes(account_id=2, only_unread=True)
    assert len(unread) == 1
    assert unread[0]["id"] == b
