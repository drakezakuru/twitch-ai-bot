#!/usr/bin/env python3
"""Validate links in the small canonical documentation set."""
from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
ACTIVE_DOCS = (
    "README.md",
    "AGENTS.md",
    "PLAN_TODO.md",
    "FILE_ZONES.md",
    "docs/PRODUCT_RULES.md",
    "docs/DECISIONS.md",
    "docs/ARCHITECTURE.md",
    "docs/HISTORY.md",
    "docs/specs/DIRECTOR.md",
    "docs/specs/MODERATOR_SITE.md",
    "widgets/README.md",
    "moderator-site/README.md",
    "moderator-site/SPECIFICATION.md",
    "moderator-site/IMPLEMENTATION.md",
    "moderator-site/ACCEPTANCE.md",
    "moderator-site/DEPLOYMENT.md",
    "moderator-site/CONTRACT_INVENTORY.md",
    "omnivoice/README.md",
    "omnivoice/IMPLEMENTATION.md",
    "omnivoice/LICENSE_REVIEW.md",
    "voice-live/README.md",
)
INLINE_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
REFERENCE_LINK_RE = re.compile(r"^\s*\[[^\]]+\]:\s*(\S+)", re.MULTILINE)
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)


def active_docs() -> list[Path]:
    paths = [ROOT / relative for relative in ACTIVE_DOCS]
    paths.extend(sorted((ROOT / "docs" / "specs").glob("*.md")))
    return paths


def _href_target(raw: str) -> tuple[str, str]:
    href = raw.strip()
    if href.startswith("<") and ">" in href:
        href = href[1:href.index(">")]
    elif " " in href and not href.startswith(("http://", "https://", "mailto:")):
        href = href.split(None, 1)[0]
    path, marker, fragment = href.partition("#")
    return unquote(path), unquote(fragment) if marker else ""


def _slug(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text).strip().lower()
    text = re.sub(r"[^\w\- ]", "", text, flags=re.UNICODE)
    return re.sub(r"[- ]+", "-", text).strip("-")


def _headings(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    return {_slug(match.group(1)) for match in HEADING_RE.finditer(text)}


def validate() -> tuple[int, list[str]]:
    broken: list[str] = []
    checked = 0
    docs = active_docs()
    for md in docs:
        if not md.is_file():
            broken.append(f"missing active document: {md.relative_to(ROOT)}")
            continue
        text = md.read_text(encoding="utf-8")
        hrefs = [match.group(1) for match in INLINE_LINK_RE.finditer(text)]
        hrefs.extend(match.group(1) for match in REFERENCE_LINK_RE.finditer(text))
        for raw in hrefs:
            href, fragment = _href_target(raw)
            if href.startswith(("http://", "https://", "mailto:")):
                continue
            checked += 1
            target = (md.parent / href).resolve() if href else md.resolve()
            try:
                target.relative_to(ROOT)
            except ValueError:
                broken.append(f"{md.relative_to(ROOT)} → outside repository: {raw}")
                continue
            if not target.exists():
                broken.append(f"{md.relative_to(ROOT)} → missing: {raw}")
                continue
            if fragment and target.is_file() and target.suffix.lower() == ".md":
                slug = _slug(fragment)
                if slug not in _headings(target):
                    broken.append(f"{md.relative_to(ROOT)} → missing heading: {raw}")
    return checked, broken


def main() -> int:
    checked, broken = validate()
    for item in broken:
        print(f"BROKEN {item}")
    print(f"\nпроверено ссылок: {checked}; битых: {len(broken)}")
    return 1 if broken else 0


if __name__ == "__main__":
    raise SystemExit(main())
