"""Q12a/Q12b: полные карточки виджетов — формы наполнения в самих карточках.

Q12a: админ-формы 7 виджетов (lower-third, mascot, anime-runner, chat-roulette,
latest-event-card, uptime, recent-events) переехали из группы «🧩 Прочее и
гайды» в карточки этих виджетов в каталоге — свёрнутыми в <details> внутри
карточки (решение владельца 13.09: раскрышка, не модалка). Контролы и их id
не переименованы — JS (wa2LoadAll) и тесты завязаны на id.
Q12b: в «Прочее и гайды» форм не осталось — только гайды/документация.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANEL = (ROOT / "templates/partials/widgets.html").read_text(encoding="utf-8")
LABELS = (ROOT / "static/app/21_panel_labels.js").read_text(encoding="utf-8")

FORMS = ["lower-third", "mascot", "anime-runner", "chat-roulette",
         "latest-event-card", "uptime", "recent-events"]


def test_every_form_lives_in_its_catalog_card():
    for f in FORMS:
        condition = f"{{% if widget.slug == '{f}' %}}"
        assert condition in PANEL, f
        idx = PANEL.index(condition)
        details = PANEL.index('details class="wa-card-admin-form"', idx)
        form = PANEL.index(f'id="wa2Form-{f}"', details)
        endif = PANEL.index("{% endif %}", form)
        # форма лежит внутри своей раскрышки, раскрышка — внутри своего условия
        assert PANEL.index("</details>", form) < endif


def test_form_ids_are_untouched_and_unique():
    for f in FORMS:
        assert PANEL.count(f'id="wa2Form-{f}"') == 1, f


def test_extras_group_has_no_content_forms():
    # Q12b: owning-тест «в extras нет форм с id wa2Form-*»
    extras = PANEL.split('data-widget-group="extras"', 1)[1].split('data-widget-group="catalog"', 1)[0]
    assert "wa2Form-" not in extras
    assert "panel.extra.title" not in extras
    # гайды остались (curl-примеры §10.6)
    assert "widgets.standalone_title" in extras


def test_old_content_card_is_gone():
    assert "panel.extra.title" not in PANEL
    assert "panel.extra.hint" not in PANEL
    # ключи вычищены из словарей, новый ключ summary — на трёх языках
    assert LABELS.count("'panel.extra.title'") == 0
    assert LABELS.count("'panel.extra.content_form'") == 3
