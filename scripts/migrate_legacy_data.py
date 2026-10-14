"""§2.2 PLAN_FEEDBACK_2908: перенос легаси-данных в twitch-ai-bot/data/.

Ищет старые корневые папки данных рядом с проектом (../data и т.п.) и
КОПИРУЕТ недостающее в актуальную структуру twitch-ai-bot/data/. Правила:
  - файл/папка отсутствует в цели → копируем;
  - цель существует → НЕ трогаем (актуальные данные важнее легаси);
  - bot.db никогда не перезаписывается (только если в цели нет bot.db);
  - отчёт → data/legacy_migration_report.json; повторный запуск безвреден.

Запуск: python3 scripts/migrate_legacy_data.py [--dry-run]
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = PROJECT_ROOT / "data"
LEGACY_CANDIDATES = [
    PROJECT_ROOT.parent / "data",               # twitch-ai-bot-v10/data
    PROJECT_ROOT / "data_legacy",               # ручной вариант
]

REPORT = {
    "run_at": datetime.now(timezone.utc).isoformat(),
    "dry_run": False,
    "scanned": [],
    "copied": [],
    "skipped_existing": [],
    "skipped_db": [],
    "errors": [],
}

NEVER_OVERWRITE = {"bot.db", "bot.db-wal", "bot.db-shm"}


def _copy_tree(src: Path, dst: Path) -> None:
    if src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        REPORT["copied"].append(str(dst))
        return
    for item in src.rglob("*"):
        if item.is_file():
            rel = item.relative_to(src)
            target = dst / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                REPORT["skipped_existing"].append(str(target))
                continue
            shutil.copy2(item, target)
            REPORT["copied"].append(str(target))


def main() -> int:
    REPORT["dry_run"] = "--dry-run" in sys.argv
    if not DATA_DIR.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)

    for legacy in LEGACY_CANDIDATES:
        if not legacy.exists() or legacy.resolve() == DATA_DIR.resolve():
            continue
        REPORT["scanned"].append(str(legacy))
        for item in legacy.rglob("*"):
            if not item.is_file():
                continue
            rel = item.relative_to(legacy)
            target = DATA_DIR / rel
            if rel.name in NEVER_OVERWRITE and target.exists():
                REPORT["skipped_db"].append(f"{rel} (цель новее/существует)")
                continue
            if target.exists():
                # забираем легаси только если цель старее и это не БД
                if rel.name in NEVER_OVERWRITE:
                    continue
                if item.stat().st_mtime > target.stat().st_mtime:
                    REPORT["skipped_existing"].append(str(target))
                    continue
            if REPORT["dry_run"]:
                REPORT["copied"].append(f"[dry] {target}")
                continue
            try:
                _copy_tree(item, target)
            except Exception as exc:  # noqa: BLE001
                REPORT["errors"].append(f"{item}: {exc}")

    out = DATA_DIR / "legacy_migration_report.json"
    if not REPORT["dry_run"]:
        out.write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: (v if not isinstance(v, list) else v[:8] + ([f"... ещё {len(v)-8}"] if len(v) > 8 else [])) for k, v in REPORT.items()}, ensure_ascii=False, indent=2))
    print(f"\nОтчёт: {out if not REPORT['dry_run'] else '(dry-run — не записан)'}")
    return 1 if REPORT["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
