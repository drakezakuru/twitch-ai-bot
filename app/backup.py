"""Бэкап / восстановление в один клик (Feature Z).

Архивирует целиком SQLite-БД (`bot.db`) и `.env` в zip,
позволяет восстановить из такого zip обратно.

Используется через эндпоинты `/api/backup/download` и `/api/backup/restore`
в `app/routes.py`.
"""

from __future__ import annotations

import io
import json
import logging
import shutil
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from app import database

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
SQLITE_MAGIC = b"SQLite format 3\x00"
MANIFEST_VERSION = 1


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


async def _checkpoint_db() -> None:
    """WAL checkpoint, чтобы файл .db содержал последние изменения."""
    db = await database.get_db()
    try:
        try:
            await db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            await db.commit()
        except Exception as exc:
            logger.warning("WAL checkpoint failed: %s", exc)
    finally:
        await db.close()


async def make_backup_zip(include_env: bool = False) -> tuple[bytes, str]:
    """Сформировать zip-бэкап в памяти.

    Returns: (zip_bytes, suggested_filename)
    """
    await _checkpoint_db()

    db_path = database.DB_PATH
    if not db_path.exists():
        raise FileNotFoundError(f"DB file not found: {db_path}")

    buf = io.BytesIO()
    manifest = {
        "version": MANIFEST_VERSION,
        "created_at": _utc_now_iso(),
        "files": [],
    }
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        # bot.db (полная копия файла, содержит все таблицы и данные)
        db_bytes = db_path.read_bytes()
        zf.writestr("bot.db", db_bytes)
        manifest["files"].append({"name": "bot.db", "size": len(db_bytes)})

        # WAL/SHM файлы по возможности тоже кладём — пусть будут (после checkpoint
        # они должны быть пустыми или маленькими, но если приложение активно
        # пишет, могут содержать незакоммиченные изменения).
        for suffix in ("-wal", "-shm"):
            extra = db_path.with_name(db_path.name + suffix)
            if extra.exists():
                data = extra.read_bytes()
                if data:
                    zf.writestr(f"bot.db{suffix}", data)
                    manifest["files"].append({"name": f"bot.db{suffix}", "size": len(data)})

        # .env (если есть и просили)
        if include_env and ENV_PATH.exists():
            env_text = ENV_PATH.read_text(encoding="utf-8")
            zf.writestr(".env", env_text)
            manifest["files"].append({"name": ".env", "size": len(env_text.encode("utf-8"))})

        # О8 PLAN.md: per-bot папки (data/bots/<id>_<ник>/ — промпты, память,
        # голоса, логи, exports) — кладём целиком, если папка есть.
        # От папки базы (data/), а не PROJECT_ROOT — чтобы следовать за DB_PATH.
        bots_root = db_path.parent / "bots"
        if bots_root.is_dir():
            for bot_dir in sorted(bots_root.iterdir()):
                if not bot_dir.is_dir():
                    continue
                for f in sorted(bot_dir.rglob("*")):
                    if not f.is_file() or f.stat().st_size > 20 * 1024 * 1024:
                        continue  # >20 МБ (например, voice_model.onnx) не тащим в zip
                    arcname = f"data/bots/{f.relative_to(bots_root).as_posix()}"
                    data = f.read_bytes()
                    zf.writestr(arcname, data)
                    manifest["files"].append({"name": arcname, "size": len(data)})

        # DIR-LIVE-05: feature-owned Director assets (data/director/** — session
        # evidence, examples). Тот же per-file cap; многогигабайтные transcript-файлы
        # в in-memory zip не помещаются — это документированный cap контракта.
        director_root = db_path.parent / "director"
        if director_root.is_dir():
            for f in sorted(director_root.rglob("*")):
                if not f.is_file() or f.stat().st_size > 20 * 1024 * 1024:
                    continue
                arcname = f"data/director/{f.relative_to(director_root).as_posix()}"
                data = f.read_bytes()
                zf.writestr(arcname, data)
                manifest["files"].append({"name": arcname, "size": len(data)})

        zf.writestr("backup_manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))

    fname = f"twitch-ai-bot-backup-{_utc_now_iso()}.zip"
    return buf.getvalue(), fname


async def make_db_snapshot() -> tuple[bytes, str]:
    """Сформировать консистентный снимок файла bot.db.

    Returns: (db_bytes, suggested_filename)
    """
    await _checkpoint_db()

    db_path = database.DB_PATH
    if not db_path.exists():
        raise FileNotFoundError(f"DB file not found: {db_path}")

    db_bytes = db_path.read_bytes()
    if len(db_bytes) < 16 or not db_bytes.startswith(SQLITE_MAGIC):
        raise ValueError("Corrupt SQLite database file")

    fname = f"bot-{_utc_now_iso()}.db"
    return db_bytes, fname


def _validate_zip(zf: zipfile.ZipFile) -> dict:
    """Проверить структуру архива; вернуть распарсенный manifest или дефолтный."""
    names = set(zf.namelist())
    if "bot.db" not in names:
        raise ValueError("Архив не похож на бэкап: нет файла bot.db")

    # Заголовок SQLite
    header = zf.read("bot.db")[:16]
    if not header.startswith(SQLITE_MAGIC):
        raise ValueError("bot.db не является валидным SQLite-файлом")

    if "backup_manifest.json" in names:
        try:
            manifest = json.loads(zf.read("backup_manifest.json").decode("utf-8"))
        except Exception:
            manifest = {"version": 0}
    else:
        manifest = {"version": 0}
    return manifest


async def restore_from_zip(zip_bytes: bytes, *, restore_env: bool = False) -> dict:
    """Восстановить БД (и опционально .env) из zip-архива.

    Текущий bot.db перед заменой переименовывается в `bot.db.bak-<ts>`.
    Singleton-коннект закрывается перед заменой и переоткроется при следующем
    обращении.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes), mode="r")
    except zipfile.BadZipFile as exc:
        return {"ok": False, "error": f"Не zip-архив: {exc}"}

    with zf:
        try:
            manifest = _validate_zip(zf)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

        # Подготавливаем целевые пути.
        db_path = database.DB_PATH
        db_path.parent.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())

        # Закрываем текущее соединение, чтобы освободить файл.
        try:
            await database.close_db()
        except Exception as exc:
            logger.warning("close_db before restore: %s", exc)

        # Бэкап текущего bot.db
        if db_path.exists():
            try:
                shutil.move(str(db_path), str(db_path.with_name(f"{db_path.name}.bak-{ts}")))
            except Exception as exc:
                return {"ok": False, "error": f"Не удалось забэкапить старую БД: {exc}"}

        # Удаляем WAL/SHM от старого коннекта
        for suffix in ("-wal", "-shm"):
            old = db_path.with_name(db_path.name + suffix)
            if old.exists():
                try:
                    old.unlink()
                except Exception:
                    pass

        # Распаковываем bot.db (+ wal/shm если есть)
        try:
            db_path.write_bytes(zf.read("bot.db"))
            for suffix in ("-wal", "-shm"):
                name = f"bot.db{suffix}"
                if name in zf.namelist():
                    db_path.with_name(db_path.name + suffix).write_bytes(zf.read(name))
        except Exception as exc:
            return {"ok": False, "error": f"Не удалось записать БД: {exc}"}

        # .env
        env_restored = False
        if restore_env and ".env" in zf.namelist():
            try:
                if ENV_PATH.exists():
                    shutil.copy2(str(ENV_PATH), str(ENV_PATH.with_name(f".env.bak-{ts}")))
                ENV_PATH.write_text(zf.read(".env").decode("utf-8"), encoding="utf-8")
                env_restored = True
            except Exception as exc:
                logger.warning("Restore .env failed: %s", exc)

        # DIR-LIVE-05: восстановление feature-owned data/ файлов (data/bots/**,
        # data/director/**) с безопасными путями. Чужеродные/absolutные/traversal
        # имена пропускаются; существующие вне архива файлы не удаляются.
        data_root = db_path.parent
        restored_files = 0
        skipped_paths = 0
        for name in zf.namelist():
            if not name.startswith("data/") or name.endswith("/"):
                continue
            relative = PurePosixPath(name).relative_to("data")
            if relative.is_absolute() or any(part in ("..", "") for part in relative.parts) or str(relative).startswith("/"):
                skipped_paths += 1
                continue
            target = (data_root / relative).resolve()
            if data_root.resolve() not in target.parents:
                skipped_paths += 1
                continue
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(name))
                restored_files += 1
            except OSError as exc:
                logger.warning("Restore %s failed: %s", name, exc)
                return {"ok": False, "error": f"Не удалось восстановить {name}: {exc}"}

    return {
        "ok": True,
        "manifest": manifest,
        "env_restored": env_restored,
        "restored_files": restored_files,
        "skipped_paths": skipped_paths,
        "note": "Перезапустите панель, чтобы новые .env-переменные применились (БД уже подхвачена).",
    }
