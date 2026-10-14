from pathlib import Path
# Q06 (решение владельца, 13.09.2026): блок «Все команды изменения виджетов во время
# эфира собраны здесь» удалён. Тесты переведены в tombstone-режим: блока нет, а сами
# карточки виджетов (sub-goal, countdown) и их формы не тронуты.
H = Path("templates/partials/widgets.html").read_text()
J = Path("static/app/07_widgets.js").read_text()
SESS = Path("static/app/13_widgets_session.js").read_text()
S = Path("static/app.js").read_text()
L = Path("static/app/21_panel_labels.js").read_text()

_REMOVED_TOKENS = (
    "widgetManualControls", "waSubDelta", "waSubReset", "waCounterManualList",
    "waLoadCounters", "waCounterDelta", "waCounterReset", "waCdAction",
)


def test_manual_block_removed():
    for token in _REMOVED_TOKENS:
        assert token not in H, token
        assert token not in J, token
        assert token not in SESS, token


def test_widget_cards_kept():
    # Сами виджеты и их карточки не тронуты: формы sub-goal и countdown остались.
    assert 'id="waSubTarget"' in H and 'id="waCdMode"' in H
    assert "waSubSave" in J and "waLoadCd" in J and "waLoadSubGoal" in J


def test_manual_i18n_removed():
    for k in ("widgets.manual_title", "widgets.manual_hint", "widgets.manual_sub_title",
              "widgets.manual_sub_hint", "widgets.manual_counter_title",
              "widgets.manual_counter_hint", "widgets.manual_countdown_title",
              "widgets.manual_countdown_hint", "widgets.cd_start", "widgets.cd_stop"):
        assert S.count("'" + k + "':") == 0, k
    assert "panel.sub_add" not in L and "panel.sub_remove" not in L
    # Карточка counter удалена (owner survey Q12) и не вернулась.
    assert "widget.counter.title" not in H


def test_legacy_presets_removed():
    assert "data-wa-presets" not in H
    assert "WIDGET_PRESETS" not in Path("static/app/16_tail.js").read_text()
