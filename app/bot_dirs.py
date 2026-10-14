"""Bot directories — структура папок per-bot для ізоляції промптів, пам'яті, логів.

Структура:
    data/bots/{account_id}_{nickname}/
        ├── config.json
        ├── prompts/
        │   ├── system.txt
        │   ├── personality.txt
        │   ├── style_examples/
        │   └── banned_topics.txt
        ├── memory/
        │   ├── conversation.jsonl
        │   ├── user_facts.json
        │   └── streamer_profile.json
        ├── voice/
        │   ├── voice_model.onnx
        │   ├── voice_config.json
        │   └── streamer_face.jpg
        ├── logs/
        │   ├── bot.log
        │   └── chat_history.jsonl
        └── exports/
            ├── chat_export.csv
            └── stats.json
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from app.database import get_db
from app.runtime_paths import BOTS_ROOT, PROJECT_ROOT

logger = logging.getLogger(__name__)


def _bot_dir_name(account_id: int, nickname: str) -> str:
    """Генерує назву папки бота: {account_id}_{nickname}."""
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in nickname)
    return f"{account_id}_{safe}"


def get_bot_dir(account_id: int, nickname: str = "") -> Path:
    """Повертає Path до папки бота. Якщо nickname порожній — шукає за account_id."""
    if nickname:
        return BOTS_ROOT / _bot_dir_name(account_id, nickname)
    # Пошук за account_id
    if not BOTS_ROOT.exists():
        return BOTS_ROOT / f"{account_id}_unknown"
    for d in BOTS_ROOT.iterdir():
        if d.is_dir() and d.name.startswith(f"{account_id}_"):
            return d
    return BOTS_ROOT / f"{account_id}_unknown"


def init_bot_dir(account_id: int, nickname: str) -> Path:
    """Створює структуру папок для бота (ідемпотентно)."""
    bot_dir = BOTS_ROOT / _bot_dir_name(account_id, nickname)
    subdirs = [
        "prompts",
        "prompts/style_examples",
        "memory",
        "voice",
        "logs",
        "exports",
    ]
    for sub in subdirs:
        (bot_dir / sub).mkdir(parents=True, exist_ok=True)

    # config.json — створюємо якщо не існує
    config_file = bot_dir / "config.json"
    if not config_file.exists():
        config_file.write_text(json.dumps({
            "account_id": account_id,
            "nickname": nickname,
            "version": "11.0",
        }, ensure_ascii=False, indent=2))

    logger.info("Bot directory initialized: %s", bot_dir)
    return bot_dir


async def migrate_bot_dir(account_id: int, nickname: str) -> None:
    """Мігрує дані з БД в per-bot папки (при першому запуску v11)."""
    bot_dir = init_bot_dir(account_id, nickname)

    db = await get_db()
    try:
        # persona_json → personality.txt
        cur = await db.execute(
            "SELECT persona_json FROM accounts WHERE id = ?", (account_id,)
        )
        row = await cur.fetchone()
        if row and row["persona_json"]:
            personality_file = bot_dir / "prompts" / "personality.txt"
            if not personality_file.exists():
                personality_file.write_text(row["persona_json"])


        # user_memory → memory/user_facts.json
        cur = await db.execute(
            "SELECT username, facts FROM user_memory WHERE account_id = ?",
            (account_id,),
        )
        rows = await cur.fetchall()
        if rows:
            facts_file = bot_dir / "memory" / "user_facts.json"
            if not facts_file.exists():
                facts = {r["username"]: json.loads(r["facts"] or "[]") for r in rows}
                facts_file.write_text(json.dumps(facts, ensure_ascii=False, indent=2))

        # streamer_kb → memory/streamer_profile.json
        cur = await db.execute(
            "SELECT topic, content, tags FROM streamer_kb WHERE account_id = ?",
            (account_id,),
        )
        rows = await cur.fetchall()
        if rows:
            profile_file = bot_dir / "memory" / "streamer_profile.json"
            if not profile_file.exists():
                kb = [{"topic": r["topic"], "content": r["content"], "tags": r["tags"]} for r in rows]
                profile_file.write_text(json.dumps(kb, ensure_ascii=False, indent=2))

        # style_examples → prompts/style_examples/
        # (в таблице style_examples нет rating — используем created_at)
        cur = await db.execute(
            "SELECT id, message, note, created_at FROM style_examples WHERE account_id = ?",
            (account_id,),
        )
        rows = await cur.fetchall()
        if rows:
            examples_dir = bot_dir / "prompts" / "style_examples"
            for r in rows:
                f = examples_dir / f"example_{r['id']}.txt"
                if not f.exists():
                    f.write_text(f"ID: {r['id']}\nDate: {r['created_at']}\nNote: {r['note']}\n\n{r['message']}")

        # banned_topics → prompts/banned_topics.txt
        cur = await db.execute(
            "SELECT pattern, fallback, mode FROM banned_topics WHERE account_id = ? AND enabled = 1",
            (account_id,),
        )
        rows = await cur.fetchall()
        if rows:
            banned_file = bot_dir / "prompts" / "banned_topics.txt"
            if not banned_file.exists():
                lines = [f"{r['pattern']} | {r['fallback']} | {r['mode']}" for r in rows]
                banned_file.write_text("\n".join(lines))

    finally:
        await db.close()


async def list_bot_files(account_id: int, nickname: str = "") -> list[dict[str, Any]]:
    """Список файлів у папці бота."""
    bot_dir = get_bot_dir(account_id, nickname)
    if not bot_dir.exists():
        return []

    files = []
    for f in sorted(bot_dir.rglob("*")):
        if f.is_file():
            rel = f.relative_to(bot_dir)
            files.append({
                "path": str(rel),
                "size": f.stat().st_size,
                "modified": f.stat().st_mtime,
            })
    return files


async def read_bot_file(account_id: int, file_path: str, nickname: str = "") -> str | None:
    """Читає файл з папки бота."""
    bot_dir = get_bot_dir(account_id, nickname)
    target = bot_dir / file_path
    # Безпека: не виходимо за межі bot_dir
    try:
        target.resolve().relative_to(bot_dir.resolve())
    except ValueError:
        return None
    if not target.exists():
        return None
    return target.read_text()


async def write_bot_file(account_id: int, file_path: str, content: str, nickname: str = "") -> bool:
    """Записує файл у папку бота."""
    bot_dir = get_bot_dir(account_id, nickname)
    target = bot_dir / file_path
    try:
        target.resolve().relative_to(bot_dir.resolve())
    except ValueError:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return True


async def delete_bot_file(account_id: int, file_path: str, nickname: str = "") -> bool:
    """Видаляє файл з папки бота."""
    bot_dir = get_bot_dir(account_id, nickname)
    target = bot_dir / file_path
    try:
        target.resolve().relative_to(bot_dir.resolve())
    except ValueError:
        return False
    if target.exists():
        target.unlink()
        return True
    return False


async def export_bot_dir(account_id: int, nickname: str = "") -> Path | None:
    """Створює ZIP-архів папки бота."""
    import zipfile
    bot_dir = get_bot_dir(account_id, nickname)
    if not bot_dir.exists():
        return None
    archive_path = bot_dir.parent / f"{bot_dir.name}.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in bot_dir.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(bot_dir.parent))
    return archive_path


__all__ = [
    "BOTS_ROOT",
    "get_bot_dir",
    "init_bot_dir",
    "migrate_bot_dir",
    "list_bot_files",
    "read_bot_file",
    "write_bot_file",
    "delete_bot_file",
    "export_bot_dir",
]
