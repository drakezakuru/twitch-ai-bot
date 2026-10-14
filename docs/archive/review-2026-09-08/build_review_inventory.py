#!/usr/bin/env python3
"""Build the reproducible path/symbol ledger for the whole-project review."""

from __future__ import annotations

import ast
import re
import subprocess
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "REVIEW_COVERAGE.md"

TRASH = {
    "get-pip.py": "vendored pip bootstrap; no repository caller",
    "shot_mascot.png": "unreferenced historical screenshot",
    "start_v12.sh": "stale versioned alias to start.sh --no-browser",
    "scripts/p5_split_app_js.py": "completed one-time structural migration helper",
    "scripts/p5_split_routes.py": "completed one-time structural migration helper",
    "scripts/panel_review_render.py": "historical manual report generator",
    "templates/index_v10_backup.html": "unreachable backup template",
    "templates/obs_tts_widget.html": "unreachable superseded OBS TTS template",
}

QUESTIONABLE = {
    "app/backup.py": "secret-bearing backup default",
    "app/diarization.py": "ML/manual runtime gate pending",
    "app/routes.py": "legacy overlay XSS and backup exposure findings",
    "app/security.py": "fail-open authentication finding",
    "app/server.py": "unmanaged lifespan tasks finding",
    "app/stream_vision.py": "external/ML manual runtime gate pending",
    "app/voice_clone.py": "external/ML manual runtime gate pending",
    "app/widget_bus.py": "global cross-account media bus finding",
    "app/widgets.py": "webhook, public mutation and secret-response findings",
    "docs/panel_review_data.json": "generated review snapshot; retention decision",
    "scripts/migrate_legacy_data.py": "one-shot migration; retention decision",
    "static/app.css": "unsupported light-theme branch",
    "static/app/08_providers_moderation.js": "hardcoded visible strings",
    "static/app/11_brain_v16.js": "hardcoded visible strings",
    "static/app/12_dashboard_extras.js": "secret loaded into DOM",
    "static/app/13_widgets_session.js": "hardcoded visible strings",
    "templates/base.html": "modal accessibility gaps",
    "templates/partials/widgets.html": "secret field and hardcoded registry strings",
    "tests/test_widgets_folder.py": "six assertions fail after runtime HTML injection",
    "widgets/media-share/index.html": "external API provenance and global bus scope",
    "widgets/README.md": "incomplete inventory, stale link and dimensions",
}


def tracked_files() -> list[str]:
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    return sorted(item.decode("utf-8", "surrogateescape") for item in raw.split(b"\0") if item)


def read_text(path: str) -> str:
    try:
        return (ROOT / path).read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""


def path_verdict(path: str) -> tuple[str, str]:
    if path in TRASH:
        return "A", TRASH[path]
    if path in QUESTIONABLE:
        return "C", QUESTIONABLE[path]
    if path.startswith("docs/archive/"):
        return "D", "retained project history required by AGENTS.md"
    if path.startswith("tests/"):
        return "D", "focused regression/support test; quality exceptions listed separately"
    if path.startswith("widgets/"):
        return "D", "active/shared widget asset covered by inventory and URL sweep"
    if path.startswith(("static/", "templates/")):
        return "D", "active panel/OBS surface covered by strict browser smoke"
    if path.startswith("app/"):
        return "D", "reachable backend module; module exceptions listed separately"
    if path.startswith("scripts/"):
        return "D", "documented operational/QA utility"
    if path.startswith("docs/") or path.endswith(".md"):
        return "D", "active specification, evidence, or retained documentation"
    return "D", "versioned runtime/build/configuration asset"


def public_symbols(paths: list[str], identifier_counts: Counter[str]) -> list[tuple[str, str, int, str, int]]:
    rows: list[tuple[str, str, int, str, int]] = []
    for path in paths:
        if not (path.startswith(("app/", "scripts/")) or path == "run.py") or not path.endswith(".py"):
            continue
        text = read_text(path)
        try:
            tree = ast.parse(text, filename=path)
        except SyntaxError:
            rows.append(("B", path, 1, "<syntax-error>", 0))
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
                refs = identifier_counts[node.name]
                decorated = bool(node.decorator_list)
                verdict = "D" if refs > 1 or decorated else "C"
                rows.append((verdict, path, node.lineno, node.name, refs))
            elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
                refs = identifier_counts[node.name]
                rows.append(("D" if refs > 1 else "C", path, node.lineno, node.name, refs))
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and not child.name.startswith("_"):
                        method = f"{node.name}.{child.name}"
                        method_refs = identifier_counts[child.name]
                        rows.append(("D" if method_refs > 1 else "C", path, child.lineno, method, method_refs))
    return rows


def esc(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def main() -> int:
    paths = tracked_files()
    # Exclude the generated ledger itself so listing a symbol does not become
    # artificial evidence that the symbol has a second runtime reference.
    texts = [read_text(path) for path in paths if path != str(OUT.relative_to(ROOT))]
    identifier_counts = Counter(
        identifier
        for text in texts
        for identifier in re.findall(r"\b[A-Za-z_]\w*\b", text)
    )
    path_rows = [(path, *path_verdict(path)) for path in paths]
    symbols = public_symbols(paths, identifier_counts)
    path_counts = Counter(row[1] for row in path_rows)
    symbol_counts = Counter(row[0] for row in symbols)

    lines = [
        "# REVIEW_COVERAGE — полный реестр покрытия",
        "",
        "> Generated by `scripts/build_review_inventory.py`. Edit classifications in the script,",
        "> then regenerate. Snapshot is tied to the current Git index; A means delete candidate,",
        "> C means owner/runtime decision, D means retained. Symbol-level defects are in DEAD_CODE.",
        "",
        "## Coverage gate",
        "",
        f"- Tracked paths: **{len(paths)} / {len(paths)} classified**; unreviewed: **0**.",
        f"- Path verdicts: A={path_counts['A']}, B={path_counts['B']}, C={path_counts['C']}, D={path_counts['D']}.",
        f"- Public Python symbols: **{len(symbols)} / {len(symbols)} classified**; "
        f"B={symbol_counts['B']}, C={symbol_counts['C']}, D={symbol_counts['D']}.",
        "- Runtime evidence and known exceptions: `REVIEW_RUNTIME.md` and `REVIEW_DEAD_CODE.md`.",
        "",
        "## Tracked paths",
        "",
        "| Path | Verdict | Evidence / disposition |",
        "|---|:---:|---|",
    ]
    lines.extend(f"| `{esc(path)}` | {verdict} | {esc(evidence)} |" for path, verdict, evidence in path_rows)
    lines.extend([
        "",
        "## Public Python symbols",
        "",
        "Static reference counts are triage evidence, not proof of runtime use. Decorated entrypoints",
        "are retained; zero/single-reference symbols are C until a dynamic/plugin caller is proven.",
        "",
        "| Verdict | Location | Symbol | Static references |",
        "|:---:|---|---|---:|",
    ])
    lines.extend(
        f"| {verdict} | `{esc(path)}:{line}` | `{esc(symbol)}` | {refs} |"
        for verdict, path, line, symbol, refs in symbols
    )
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(paths)} paths, {len(symbols)} symbols")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
