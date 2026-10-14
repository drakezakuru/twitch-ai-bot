"""Tests for app/backup.py — Feature Z (full backup / restore)."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from starlette.requests import Request
from starlette.datastructures import UploadFile


@pytest.mark.asyncio
async def test_automatic_backup_never_exports_env(monkeypatch, tmp_path):
    from app import maintenance

    seen: list[bool] = []

    async def fake_backup(*, include_env: bool):
        seen.append(include_env)
        return b"safe-backup", "auto.zip"

    monkeypatch.setattr(maintenance, "auto_backup_days", lambda: 1)
    monkeypatch.setattr(maintenance, "BACKUPS_DIR", tmp_path)
    monkeypatch.setattr(maintenance.backup_mod, "make_backup_zip", fake_backup)

    result = await maintenance.run_auto_backup()

    assert result == tmp_path / "auto.zip"
    assert seen == [False]


@pytest.mark.asyncio
async def test_make_backup_zip_contains_db_and_manifest(tmp_db, monkeypatch, tmp_path):
    from app import database, backup as backup_mod

    # Подменяем .env-путь, чтобы не трогать реальный
    fake_env = tmp_path / ".env.fake"
    fake_env.write_text("PANEL_AUTH_USER=hello\n")
    monkeypatch.setattr(backup_mod, "ENV_PATH", fake_env)

    await database.init_db()

    zip_bytes, fname = await backup_mod.make_backup_zip(include_env=True)
    assert fname.endswith(".zip")
    assert fname.startswith("twitch-ai-bot-backup-")

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = set(zf.namelist())
        assert "bot.db" in names
        assert ".env" in names
        assert "backup_manifest.json" in names
        # bot.db has SQLite magic
        head = zf.read("bot.db")[:16]
        assert head.startswith(b"SQLite format 3\x00")
        # .env content preserved
        assert zf.read(".env").decode() == "PANEL_AUTH_USER=hello\n"


@pytest.mark.asyncio
async def test_make_backup_zip_skip_env(tmp_db, monkeypatch, tmp_path):
    from app import database, backup as backup_mod
    fake_env = tmp_path / ".env.fake"
    fake_env.write_text("X=1\n")
    monkeypatch.setattr(backup_mod, "ENV_PATH", fake_env)

    await database.init_db()
    zip_bytes, _ = await backup_mod.make_backup_zip(include_env=False)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        assert ".env" not in zf.namelist()
        assert "bot.db" in zf.namelist()


@pytest.mark.asyncio
async def test_make_backup_zip_excludes_env_by_default(tmp_db, monkeypatch, tmp_path):
    from app import database, backup as backup_mod
    fake_env = tmp_path / ".env.fake"
    fake_env.write_text("SECRET=value\n")
    monkeypatch.setattr(backup_mod, "ENV_PATH", fake_env)

    await database.init_db()
    zip_bytes, _ = await backup_mod.make_backup_zip()
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        assert ".env" not in zf.namelist()


@pytest.mark.asyncio
async def test_restore_from_zip_replaces_db(tmp_db, monkeypatch, tmp_path):
    from app import database, backup as backup_mod

    fake_env = tmp_path / ".env.fake"
    fake_env.write_text("ORIG=1\n")
    monkeypatch.setattr(backup_mod, "ENV_PATH", fake_env)

    # Создаём БД и кладём в неё уникальный маркер
    await database.init_db()
    db = await database.get_db()
    await db.execute(
        "INSERT INTO accounts (nickname, token) VALUES (?, ?)",
        ("backup_marker", "tok_orig"),
    )
    await db.commit()
    await db.close()

    # Делаем бэкап
    zip_bytes, _ = await backup_mod.make_backup_zip(include_env=True)

    # Меняем БД (добавляем второй аккаунт)
    db = await database.get_db()
    await db.execute(
        "INSERT INTO accounts (nickname, token) VALUES (?, ?)",
        ("after_backup", "tok_new"),
    )
    await db.commit()
    await db.close()

    # Перезаписываем .env
    fake_env.write_text("CHANGED=2\n")

    # Восстанавливаем
    res = await backup_mod.restore_from_zip(zip_bytes, restore_env=True)
    assert res["ok"] is True
    assert res["env_restored"] is True

    # БД должна содержать ТОЛЬКО backup_marker
    db = await database.get_db()
    cursor = await db.execute("SELECT nickname FROM accounts ORDER BY nickname")
    rows = [r[0] for r in await cursor.fetchall()]
    await db.close()
    assert rows == ["backup_marker"]

    # .env восстановлен
    assert fake_env.read_text() == "ORIG=1\n"

    # Старая БД должна быть в .bak-* файле
    db_dir = database.DB_PATH.parent
    bak_files = list(db_dir.glob("bot.db.bak-*"))
    assert len(bak_files) >= 1


@pytest.mark.asyncio
async def test_restore_invalid_zip(tmp_db):
    from app import backup as backup_mod
    res = await backup_mod.restore_from_zip(b"not-a-zip-file")
    assert res["ok"] is False
    assert "zip" in res["error"].lower()


@pytest.mark.asyncio
async def test_restore_zip_without_db_rejected(tmp_db):
    from app import backup as backup_mod
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        zf.writestr("readme.txt", "hello")
    res = await backup_mod.restore_from_zip(buf.getvalue())
    assert res["ok"] is False
    assert "bot.db" in res["error"]


@pytest.mark.asyncio
async def test_restore_zip_with_bogus_db_rejected(tmp_db):
    from app import backup as backup_mod
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        zf.writestr("bot.db", b"this is not sqlite")
    res = await backup_mod.restore_from_zip(buf.getvalue())
    assert res["ok"] is False
    assert "SQLite" in res["error"] or "sqlite" in res["error"].lower()


@pytest.mark.asyncio
async def test_backup_includes_per_bot_folders(tmp_db):
    """О8 PLAN.md: data/bots/<dir>/** попадает в zip (мелкие файлы)."""
    from app import database
    await database.init_db()
    import os
    bots_root = os.path.join(os.path.dirname(str(database.DB_PATH)), "..", "data", "bots")
    # DB_PATH = <tmp>/data/bot.db → bots_root = <tmp>/data/bots
    bots_root = os.path.normpath(bots_root)
    os.makedirs(os.path.join(bots_root, "1_test", "prompts"), exist_ok=True)
    with open(os.path.join(bots_root, "1_test", "prompts", "system.txt"), "w") as f:
        f.write("PROMPT-TEST-CONTENT")
    with open(os.path.join(bots_root, "1_test", "prompts", "big.bin"), "wb") as f:
        f.write(b"0" * (21 * 1024 * 1024))  # 21 МБ — должен быть пропущен

    from app.backup import make_backup_zip
    import zipfile, io
    data, _ = await make_backup_zip(include_env=False)
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert "data/bots/1_test/prompts/system.txt" in names
    assert "data/bots/1_test/prompts/big.bin" not in names


@pytest.mark.asyncio
async def test_backup_excludes_widget_media_cache_temp_and_secrets(tmp_db):
    from app import database
    from app.backup import make_backup_zip

    await database.init_db()
    data_root = database.DB_PATH.parent
    widget_root = data_root / "widgets" / "soundboard"
    widget_root.mkdir(parents=True)
    (widget_root / ("a" * 32)).with_suffix(".mp3").write_bytes(b"durable-audio")
    (widget_root / ".upload-in-progress").write_bytes(b"temporary")
    (widget_root / "secret.txt").write_text("must-not-backup", encoding="utf-8")

    zip_bytes, _ = await make_backup_zip(include_env=False)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        assert not {name for name in zf.namelist() if name.startswith("data/widgets/")}


@pytest.mark.asyncio
async def test_backup_restore_preserves_moderator_media_obs_url(tmp_db, monkeypatch):
    from app import database, moderator_media_routes as media
    from app.backup import make_backup_zip, restore_from_zip

    await database.init_db()
    db = await database.get_db()
    try:
        await db.execute("INSERT INTO accounts (id,nickname,token) VALUES (1,'one','token')")
        await db.execute("INSERT INTO channels (account_id,channel_name) VALUES (1,'shared')")
        await db.commit()
    finally:
        await db.close()
    monkeypatch.setattr(media, "_audit", lambda *_: _done())
    request = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1234)})
    original = await media.rotate_obs_token(request, 1, "shared")
    archive, _ = await make_backup_zip()
    replacement = await media.rotate_obs_token(request, 1, "shared")
    assert not await media._valid_obs_token(1, "shared", original["token"])

    restored = await restore_from_zip(archive)
    assert restored["ok"] is True
    assert await media._valid_obs_token(1, "shared", original["token"])
    assert not await media._valid_obs_token(1, "shared", replacement["token"])


@pytest.mark.asyncio
async def test_backup_restore_preserves_scoped_donation_secrets(tmp_db):
    from app import database
    from app.backup import make_backup_zip, restore_from_zip
    from app.widgets import ensure_widgets_schema

    await database.init_db()
    await ensure_widgets_schema()
    db = await database.get_db()
    try:
        await db.execute("INSERT INTO accounts (id,nickname,token) VALUES (1,'donation','token')")
        await db.execute("INSERT INTO channels (account_id,channel_name) VALUES (1,'shared')")
        await db.execute(
            "INSERT INTO donation_integrations_scoped "
            "(account_id,channel,platform,token,enabled) VALUES (1,'shared','donatepay','provider-token',1)"
        )
        await db.execute(
            "INSERT INTO donation_webhook_scopes "
            "(account_id,channel,token,enabled) VALUES (1,'shared','bridge-token',1)"
        )
        await db.commit()
    finally:
        await db.close()

    archive, _ = await make_backup_zip()
    db = await database.get_db()
    try:
        await db.execute(
            "UPDATE donation_integrations_scoped SET token = 'replacement' "
            "WHERE account_id = 1 AND channel = 'shared'"
        )
        await db.execute(
            "UPDATE donation_webhook_scopes SET token = 'replacement' "
            "WHERE account_id = 1 AND channel = 'shared'"
        )
        await db.commit()
    finally:
        await db.close()

    assert (await restore_from_zip(archive))["ok"] is True
    db = await database.get_db()
    try:
        provider = await db.execute(
            "SELECT token FROM donation_integrations_scoped "
            "WHERE account_id = 1 AND channel = 'shared'"
        )
        bridge = await db.execute(
            "SELECT token FROM donation_webhook_scopes "
            "WHERE account_id = 1 AND channel = 'shared'"
        )
        assert (await provider.fetchone())["token"] == "provider-token"
        assert (await bridge.fetchone())["token"] == "bridge-token"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_backup_routes_reject_non_loopback_clients(tmp_db):
    from app import routes

    remote = Request({"type": "http", "headers": [], "client": ("198.51.100.4", 1234)})
    with pytest.raises(Exception) as download_error:
        await routes.backup_download(remote)
    assert getattr(download_error.value, "status_code", None) == 403

    upload = UploadFile(filename="backup.zip", file=io.BytesIO(b"unused"))
    with pytest.raises(Exception) as restore_error:
        await routes.backup_restore(remote, upload)
    assert getattr(restore_error.value, "status_code", None) == 403

    cross_site = Request({
        "type": "http",
        "headers": [(b"host", b"127.0.0.1:8000"), (b"origin", b"https://example.invalid")],
        "client": ("127.0.0.1", 1234),
    })
    with pytest.raises(Exception) as csrf_error:
        await routes.backup_restore(cross_site, upload)
    assert getattr(csrf_error.value, "status_code", None) == 403


@pytest.mark.asyncio
async def test_make_db_snapshot_and_download_db(tmp_db):
    """Снимок bot.db содержит заголовок SQLite и отдаётся через download-db."""
    from app import database, backup as backup_mod, routes

    await database.init_db()
    db_bytes, fname = await backup_mod.make_db_snapshot()
    assert fname.startswith("bot-") and fname.endswith(".db")
    assert db_bytes.startswith(b"SQLite format 3\x00")

    # Проверка эндпоинта routes.backup_download_db с loopback-клиента
    loopback = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1234)})
    response = await routes.backup_download_db(loopback)
    assert response.status_code == 200
    assert response.media_type == "application/x-sqlite3"
    assert response.body.startswith(b"SQLite format 3\x00")


async def _done() -> None:
    return None
