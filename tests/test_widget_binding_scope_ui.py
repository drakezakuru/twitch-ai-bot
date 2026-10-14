from pathlib import Path

from app.widget_bindings import BINDING_CONTRACT


ROOT = Path(__file__).resolve().parents[1]
SESSION_JS = (ROOT / "static/app/13_widgets_session.js").read_text(encoding="utf-8")
HOTKEY_JS = (ROOT / "static/app/15_feedback_2908.js").read_text(encoding="utf-8")
WIDGET_ADMIN_JS = (ROOT / "static/app/07_widgets.js").read_text(encoding="utf-8")
WIDGETS_HTML = (ROOT / "templates/partials/widgets.html").read_text(encoding="utf-8")


def test_binding_scope_is_channel_first_with_auto_bot():
    # Q11a→Q27c: ручные селекты бота/канала и общая карточка билдера удалены;
    # скоуп правил = общий channel-first скоуп «Виджетов» (Q10a), бот-модератор
    # канала подставляется сам, авто-строку показывает каждая секция карточки.
    assert 'id="waBindingsCard"' not in WIDGETS_HTML
    assert 'id="waBindAccount"' not in WIDGETS_HTML
    assert 'id="waBindChannel"' not in WIDGETS_HTML
    assert 'id="waBindAutoLine"' not in WIDGETS_HTML
    assert 'id="waBindBotPickField"' not in WIDGETS_HTML
    assert "const scope = waBindingScope();" in SESSION_JS
    assert "new URLSearchParams(scope)" in SESSION_JS
    # скоуп правил = общий скоуп «Виджетов» (channel-first, Q10a)
    assert "const raw = waChannelScopeStored();" in SESSION_JS
    # модератор-бот выбирается первым при построении скоупа
    assert "b.connected && b.role === 'moderator'" in WIDGET_ADMIN_JS
    assert "window._waChannelScopeBots" in WIDGET_ADMIN_JS
    # авто-строка теперь в секциях карточек (waRulesAutoLine), а не в общей карточке
    assert "function waRulesAutoLine(" in SESSION_JS
    assert "window._waChannelScopeBots" in SESSION_JS
    assert 'data-i18n="bindings.rules_section"' in WIDGETS_HTML


def test_binding_ui_is_guided_and_human_readable():
    # Q27c: форма правил — inline в секции карточки (waRulesEnsure), общий билдер снесён
    assert 'id="waBindMatchLabel"' not in WIDGETS_HTML
    assert 'id="waBindKeyField"' not in WIDGETS_HTML
    assert 'id="waBindValueField"' not in WIDGETS_HTML
    assert 'id="waBindAddBtn"' not in WIDGETS_HTML
    assert 'id="waBindingBuilder"' not in WIDGETS_HTML
    assert "function waRulesEnsure(" in SESSION_JS
    assert "function waRulesFormSync(" in SESSION_JS
    assert 'class="wa-binding-sentence"' in SESSION_JS
    assert "waBindingContractLabel('sources', b.source)" in SESSION_JS
    for language in ("LANGS.ru", "LANGS.en", "LANGS.ua"):
        assert language in SESSION_JS
    assert SESSION_JS.count("'bindings.rules_section'") == 3
    # datalist событий остался — inline-формы карточек ссылаются на него
    assert 'id="waBindEventOptions"' in WIDGETS_HTML


def test_binding_builder_dynamic_fields_follow_source_widget_and_action():
    assert "source === 'eventsub' ? 'event' : source === 'hotkey' ? 'hotkey' : 'chat'" in SESSION_JS
    assert 'list="waBindEventOptions"' in SESSION_JS
    assert "classList.toggle('hidden', source !== 'hotkey')" in SESSION_JS
    assert "const needsKey = !!contract.key" in SESSION_JS
    assert "!actionContract.value || actionContract.value.type === 'none'" in SESSION_JS


def test_binding_rule_cards_render_disabled_roles_and_track_actions():
    assert "b.enabled ? '' : 'is-disabled'" in SESSION_JS
    assert "b.enabled ? t('bindings.active') : t('bindings.disabled')" in SESSION_JS
    assert "rawAction.startsWith('play_track:') ? 'play_track'" in SESSION_JS
    assert "trackId ? `<code>#${esc(trackId)}</code>`" in SESSION_JS
    # правила карточки фильтруются по виджету секции
    assert "filter(b => b.widget === slug)" in SESSION_JS


def test_generic_soundboard_action_cannot_be_submitted():
    assert BINDING_CONTRACT["widgets"]["soundboard"]["actions"] == {}
    assert BINDING_CONTRACT["widgets"]["soundboard"]["dynamic_action"]["prefix"] == "play_track:"
    assert "addBtn.disabled = !action" in SESSION_JS
    assert "slug === 'soundboard' ? t('bindings.soundboard_pick')" in SESSION_JS


def test_binding_ui_scopes_mutations_and_hotkey_execution():
    assert "...waBindingScope()," in SESSION_JS
    assert "{...waBindingScope(), enabled}" in SESSION_JS
    assert "new URLSearchParams(waBindingScope())" in SESSION_JS
    assert "if (!scope.account_id || !scope.channel) return;" in HOTKEY_JS
    assert "{ combo, ...scope }" in HOTKEY_JS


def test_panel_hotkeys_are_focus_safe_and_do_not_claim_obs_integration():
    assert "tag === 'input' || tag === 'textarea' || tag === 'select'" in HOTKEY_JS
    assert "el?.isContentEditable" in HOTKEY_JS
    assert HOTKEY_JS.count("'bindings.hint':") == 3
    assert HOTKEY_JS.count("OBS hotkeys") == 3
    assert "OBS-хоткей, открывающий панель" not in HOTKEY_JS


def test_binding_overview_exposes_bot_roles_for_auto_pick():
    # Q11a: /api/channel-overview отдаёт роль каждого бота — источник авто-подстановки
    src = (ROOT / "app/bulk_channels_routes.py").read_text(encoding="utf-8")
    assert "a.bot_role" in src
    assert '"role":' in src


def test_binding_preset_select_is_removed_with_general_builder():
    # Q27c (DEC-OWNER-017): пресет-селект и кнопка пресета жили в общей карточке
    # билдера — снесены вместе с ней; бэкенд-пресеты остаются контрактом API
    # (покрыты tests/test_widget_bindings.py::apply_preset)
    assert 'id="waBindPreset"' not in WIDGETS_HTML
    assert 'waBindingPresetApply' not in WIDGETS_HTML
    assert 'waBindingPresetApply' not in SESSION_JS
    assert "/api/widgets/bindings/presets/{name}" in (ROOT / "app/widgets.py").read_text(encoding="utf-8")


def test_widget_state_controls_use_selected_binding_scope():
    assert "function wstateapi(" in WIDGET_ADMIN_JS
    assert "url.searchParams.set('account_id'" in WIDGET_ADMIN_JS
    assert "url.searchParams.set('channel'" in WIDGET_ADMIN_JS
    # counters исключён: ручные контролы счётчиков удалены в Q06 (R-ВИД3),
    # счётчики меняются только биндингами/чат-командами
    for route in ("goals", "sub-goal", "now-playing", "countdown"):
        assert f"wstateapi('/api/widgets/{route}" in WIDGET_ADMIN_JS
    assert "wstateapi('/api/widgets/lower-third'" in HOTKEY_JS
    assert "waRefreshScopedWidgetPreviews();" in SESSION_JS


def test_browser_sources_forward_scope_to_public_api():
    shared = (ROOT / "widgets/_shared/appearance.js").read_text(encoding="utf-8")
    assert "window.widgetScopedUrl" in shared
    assert "params.get('account_id')" in shared
    assert "params.get('channel')" in shared
    for folder in ("goals", "sub-goal", "now-playing", "countdown", "lower-third"):
        source = (ROOT / f"widgets/{folder}/index.html").read_text(encoding="utf-8")
        assert "fetch(widgetScopedUrl(" in source
    assert "'/widget/clip-moments'" in WIDGET_ADMIN_JS
    assert "waCopyWidgetUrl('{{ widget.route }}')" in WIDGETS_HTML
