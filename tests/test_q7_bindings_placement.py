"""Q7 (B6): единый builder биндингов без технических дублей.

Карточки виджетов только открывают общий builder с выбранным виджетом.
Soundboard передаёт туда параметризованное действие конкретного трека.
Тест ловит рассинхрон между источниками правды:

* `app/widget_bindings.py:ALLOWED_ACTIONS` — что разрешено исполнять;
* `app/widget_bindings.py:BINDING_CONTRACT` — что предлагает форма через API;
* `app/widget_inventory.py:WIDGET_BINDING_SLUGS` — у каких карточек есть CTA.
"""
from __future__ import annotations

from pathlib import Path

from app.widget_bindings import ALLOWED_ACTIONS, BINDING_CONTRACT
from app.widget_inventory import WIDGET_INVENTORY, WIDGET_BINDING_SLUGS

ROOT = Path(__file__).resolve().parents[1]
PANEL = (ROOT / "templates/partials/widgets.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "static/app/13_widgets_session.js").read_text(encoding="utf-8")
I18N = (ROOT / "static/app/15_feedback_2908.js").read_text(encoding="utf-8")


def test_manifest_offers_actions_for_every_active_widget():
    for slug, spec in BINDING_CONTRACT["widgets"].items():
        assert slug in ALLOWED_ACTIONS, f"{slug}: нет в ALLOWED_ACTIONS"
        if slug == "soundboard":
            assert spec["actions"] == [] or spec["actions"] == {}
            assert spec["dynamic_action"]["prefix"] == "play_track:"
            continue
        assert spec["actions"], f"{slug}: форма покажет пустой список действий"


def test_manifest_actions_are_subset_of_allowed_actions():
    for slug, spec in BINDING_CONTRACT["widgets"].items():
        for action in spec["actions"]:
            assert action in ALLOWED_ACTIONS[slug], f"{slug}.{action} исполнитель не примет"
    assert "WA_BINDING_ACTIONS" not in SCRIPT
    assert "await wapi('/api/widgets/binding-contract')" in SCRIPT


def test_every_manifest_action_has_i18n_label():
    for spec in BINDING_CONTRACT["widgets"].values():
        for action, action_spec in spec["actions"].items():
            label = action_spec["label"]
            assert label.startswith("bindings.action_")
            assert I18N.count(f"'{label}'") >= 3, f"{action}: нет подписи RU/EN/UA"


def test_card_binding_ctas_cover_widget_scoped_actions_only():
    """Карточка получает CTA только если действия относятся к самому виджету."""
    for item in WIDGET_INVENTORY:
        if item.binding_slug:
            assert item.binding_slug in ALLOWED_ACTIONS, item.slug
    # moderation — не виджет из реестра, soundboard биндится кнопкой у трека
    assert "moderation" not in WIDGET_BINDING_SLUGS.values()
    assert "soundboard" not in WIDGET_BINDING_SLUGS.values()


def test_reviewed_workflow_widgets_do_not_get_fake_bindings():
    """Q27a (DEC-OWNER-017 п.4): владелец расширил биндинги на все виджеты с
    ОСМЫСЛЕННЫМИ действиями — subathon-timer, chat-highlight, chat-roulette,
    donation-challenge, song-request и blur-guard-v2 получили реальные действия
    (контракт v2), правило «без фейковых биндингов» остаётся для виджетов,
    у которых осмысленных действий пока нет."""
    no_bindings_yet = {"media-share", "clip-moments"}
    with_bindings_v2 = {
        "subathon-timer": "subathon_timer", "chat-highlight": "chat_highlight",
        "chat-roulette": "chat_roulette", "donation-challenge": "donation_challenge",
        "song-request": "song_request", "blur-guard-v2": "blur_guard_v2",
    }
    inventory = {item.slug: item for item in WIDGET_INVENTORY}
    assert no_bindings_yet <= inventory.keys()
    for slug in no_bindings_yet:
        assert not inventory[slug].binding_slug
        assert slug.replace("-", "_") not in ALLOWED_ACTIONS
    for slug, widget in with_bindings_v2.items():
        assert inventory[slug].binding_slug == widget
        assert widget in ALLOWED_ACTIONS


def test_soundboard_bind_button_fills_track_specific_action():
    """Кнопка биндинга трека обязана подставлять play_track:<id>, а не пустоту.
    Q27b: действие уходит в секцию правил карточки Soundboard (prefillAction)."""
    src = (ROOT / "static/app/07_widgets.js").read_text(encoding="utf-8")
    fn = src.split("function waSoundboardBind(", 1)[1].split("\n}", 1)[0]
    assert "play_track:${id}" in fn
    assert "waWidgetBindingAdd('soundboard', action)" in fn, "трек подставляется в секцию карточки"
    assert 'data-rules-slug="soundboard"' in fn, "секция правил Soundboard ищется в карточке"
    assert "waRulesFormSync(section)" in fn, "после track action кнопка создания должна включиться"


def test_binding_ui_enforces_eventsub_and_moderation_roles():
    assert BINDING_CONTRACT["sources"]["eventsub"]["roles"] == ["any"]
    assert BINDING_CONTRACT["sources"]["hotkey"]["roles"] == ["streamer"]
    assert BINDING_CONTRACT["sources"]["chat_command"]["roles"] == ["mod", "streamer"]
    assert BINDING_CONTRACT["widgets"]["moderation"]["sources"] == ["hotkey"]
    assert "allowedRoles" in SCRIPT and "allowedSources" in SCRIPT


def test_generated_goals_binding_has_required_key_input():
    # Q27c: поле ключа живёт в inline-форме секции карточки (wa-rules-key-field)
    assert 'wa-rules-key-field' in SCRIPT
    assert BINDING_CONTRACT["widgets"]["goals"]["key"] == {
        "type": "positive_integer", "required": True, "kind": "goal",
    }
    assert "const needsKey = !!contract.key" in SCRIPT


def test_widget_cards_host_inline_rules_sections():
    """Q27b (DEC-OWNER-017 п.4): правила живут в карточке виджета — секция
    «⚡ Правила» (details.wa-widget-rules) с inline-формой КОГДА → ТОГДА.
    waWidgetBindingAdd открывает и скроллит к секции, а не к общей модалке."""
    assert 'data-rules-slug="goals"' in PANEL
    assert 'data-rules-slug="sub_goal"' in PANEL
    assert 'data-rules-slug="now_playing"' in PANEL
    assert 'data-rules-slug="countdown"' in PANEL
    assert 'data-rules-slug="soundboard"' in PANEL
    assert 'data-rules-slug="{{ widget.binding_slug }}"' in PANEL
    assert "onclick=\"waWidgetBindingAdd('goals')\"" in PANEL
    add_fn = SCRIPT.split("function waWidgetBindingAdd", 1)[1].split("\nfunction ", 1)[0]
    assert "waBindingModalOpen(builder)" not in add_fn, \
        "waWidgetBindingAdd больше не открывает общую модалку — только секцию карточки"
    assert "scrollIntoView" in add_fn and "waRulesFormSync(section)" in add_fn
    assert "function waRulesEnsure(" in SCRIPT
    assert "function waRulesFormSync(" in SCRIPT
    assert "function waRulesAdd(" in SCRIPT
    assert "function waRulesRenderAll(" in SCRIPT
    assert "wa-rules-match" in SCRIPT and 'list="waBindEventOptions"' in SCRIPT
    assert "bindings.rules_section" in SCRIPT and "bindings.press_keys" in SCRIPT
    for legacy_class in ("waWB-source", "waWB-match", "waWB-key", "waWB-action", "waWB-value", "waWB-role"):
        assert legacy_class not in PANEL


def test_widget_rules_sections_have_i18n_in_three_languages():
    for key in ("bindings.rules_section", "bindings.press_keys"):
        assert SCRIPT.count(f"'{key}'") >= 3, f"{key}: нет RU/EN/UA"
