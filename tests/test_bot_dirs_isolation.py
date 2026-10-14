from __future__ import annotations

import pytest

def test_bot_directory_uses_project_relative_root_and_safe_nickname(tmp_path, monkeypatch):
    from app import bot_dirs

    monkeypatch.setattr(bot_dirs, "BOTS_ROOT", tmp_path)
    path = bot_dirs.init_bot_dir(7, "../bot name/with spaces")

    assert path.parent == tmp_path
    assert ".." not in path.name
    assert "/" not in path.name
    assert (path / "prompts").is_dir()
    assert (path / "memory").is_dir()


@pytest.mark.asyncio
async def test_bot_file_operations_cannot_escape_bot_directory(tmp_path, monkeypatch):
    from app import bot_dirs

    monkeypatch.setattr(bot_dirs, "BOTS_ROOT", tmp_path)
    bot_dirs.init_bot_dir(1, "bot")

    assert await bot_dirs.write_bot_file(1, "../outside.txt", "secret", "bot") is False
    assert await bot_dirs.read_bot_file(1, "../outside.txt", "bot") is None
    assert await bot_dirs.delete_bot_file(1, "../outside.txt", "bot") is False
