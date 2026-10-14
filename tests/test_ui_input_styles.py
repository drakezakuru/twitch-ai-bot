"""§1.1 audit PLAN_FEEDBACK_3008: all text-like form fields must carry .input.

Scans templates/partials/*.html, templates/base.html and dynamically rendered
HTML in static/app.js. Checkbox/radio/color/range/date/file/hidden are exempt
(they are not text fields). Known-styled exceptions are listed explicitly with
a reason so they cannot hide new offenders.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests import _panel_js

ROOT = Path(__file__).resolve().parents[1]

TAG_RE = re.compile(r"<(input|select|textarea)\b[^>]*>", re.S)

# Field types that must NOT get the .input class.
EXEMPT_TYPES = {
    "checkbox", "radio", "color", "range", "date", "file", "hidden",
    "time", "week", "month",
}

# file -> tag fragment prefix -> reason (already themed outside .input).
KNOWN_EXCEPTIONS = {
    "templates/base.html": {
        '<input type="text" id="globalSearch"': "styled by .search-bar input in app.css",
    },
}


def _strip_full_line_js_comments(src: str) -> str:
    """Blank out lines that are entirely a `//` comment.

    Panel JS comments sometimes mention HTML tags in prose (e.g. `<select>`
    больше не используется) — without this the tag regex mistakes commentary
    for a real unstyled field. Only whole-comment lines are blanked so line
    numbers in reported offenders stay accurate; `//` inside real code/strings
    on a mixed line is left untouched.
    """
    return "\n".join("" if line.strip().startswith("//") else line for line in src.split("\n"))


def _offenders() -> list[str]:
    problems: list[str] = []
    files = [
        ROOT / "templates" / "base.html",
        *_panel_js.panel_js_files(),
        *sorted((ROOT / "templates" / "partials").glob("*.html")),
    ]
    for path in files:
        rel = str(path.relative_to(ROOT))
        src = path.read_text(encoding="utf-8")
        if path.suffix == ".js":
            src = _strip_full_line_js_comments(src)
        for m in TAG_RE.finditer(src):
            tag = re.sub(r"\s+", " ", m.group(0))
            type_m = re.search(r'type=["\']?(\w+)', tag)
            ftype = type_m.group(1) if type_m else m.group(1)
            if ftype in EXEMPT_TYPES:
                continue
            if re.search(r'class=["\'][^"\']*\binput\b', tag):
                continue
            for prefix, reason in KNOWN_EXCEPTIONS.get(rel, {}).items():
                if tag.startswith(prefix):
                    break
            else:
                line = src[: m.start()].count("\n") + 1
                problems.append(f"{rel}:{line}: {tag[:140]} (no .input class)")
    return problems


def test_text_like_form_fields_have_input_class():
    problems = _offenders()
    assert not problems, (
        "Form fields missing the .input class (white/unthemed fields):\n"
        + "\n".join(problems)
    )


def test_no_broken_bg_secondary_fallback():
    """PLAN_FEEDBACK_3008_B §A: var(--bg-secondary) не существует в теме —
    fallback #f5f5f5 давал «белое на белом». Использовать .form-panel."""
    offenders = []
    files = [
        ROOT / "templates" / "base.html",
        *_panel_js.panel_js_files(),
        *sorted((ROOT / "templates" / "partials").glob("*.html")),
    ]
    for path in files:
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "--bg-secondary" in line:
                offenders.append(f"{path.relative_to(ROOT)}:{i}: {line.strip()[:120]}")
    assert not offenders, (
        "bg-secondary (non-existent CSS var, white-on-white in dark theme):\n"
        + "\n".join(offenders)
    )
