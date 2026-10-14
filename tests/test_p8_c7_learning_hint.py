"""P8-C7: карточка «Предложения» — оставить + честная подпись.

Подпись brain.learning_hint объясняет: предложения появляются из 👍/👎 и
анализа чата; «Применить» меняет поведение, «Отменить» откатывает.
Проверяем, что карточка и подпись на месте во всех 3 языках.
(Q17: карточка переехала из «Мозга» во вкладку бота, botTab-memory.)
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_learning_card_kept_with_hint():
    html = (ROOT / "templates" / "partials" / "bots.html").read_text(encoding="utf-8")
    assert "Обучение (предложения)" in html, "карточка «Предложения» пропала"
    assert 'data-i18n="brain.learning_hint"' in html, "подпись пропала"
    assert 'id="botLearningList"' in html, "список предложений во вкладке бота пропал"


def test_learning_hint_i18n_all_langs():
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    lines = [ln for ln in js.splitlines() if "'brain.learning_hint':" in ln]
    assert len(lines) >= 3, f"нет переводов для всех языков: {len(lines)}"
    for ln in lines:
        assert ("👍" in ln and "👎" in ln) or "feedback" in ln
        assert ("Применить" in ln or "Apply" in ln or "Застосувати" in ln)
        assert ("Отменить" in ln or "Undo" in ln or "Скасувати" in ln)
