"""P8-C9 (часть 1): «Режим внимания» → «На что реагировать».

Вердикт владельца: слово «режим» техническое; подпись должна говорить
по-человечески, на что бот реагирует. Проверяем все 3 языка + разметку.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_attention_mode_renamed_everywhere():
    banned = ("Режим внимания", "Режим уваги", "Attention mode")
    for rel in ("static/app.js", "templates/partials/bots.html"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        for phrase in banned:
            assert phrase not in src, f"«{phrase}» осталось в {rel}"


def test_attention_mode_new_labels_present():
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "'attention.mode': 'На что реагировать'" in js
    assert "'attention.mode': 'What to react to'" in js
    assert "'attention.mode': 'На що реагувати'" in js
    html = (ROOT / "templates" / "partials" / "bots.html").read_text(encoding="utf-8")
    assert ">На что реагировать</label>" in html
