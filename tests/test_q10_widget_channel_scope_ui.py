"""Q10a: channel-first скоуп виджетов — селектор канала в шапке «Виджетов».

Проверяем: селектор `waChannelScope` существует и заполнение идёт из
`/api/channel-overview`; выбор хранится в localStorage `widgetChannelScope`
как «account_id:channel»; определена `waBindingScope()` (раньше её не было —
действовали только per-widget override); per-widget override читается первым
(сильнее селектора); смена канала перезагружает admin-формы и превью;
i18n-ключи на трёх языках.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def test_widgets_header_has_channel_selector():
    html = _read("templates", "partials", "widgets.html")
    assert 'id="waChannelScope"' in html
    assert 'onchange="waChannelScopeChanged()"' in html
    assert 'id="waChannelScopeBadge"' in html
    assert 'data-i18n="widgets.channel_scope"' in html


def test_wa_binding_scope_defined_and_channel_first():
    js = _read("static", "app", "07_widgets.js")
    session_js = _read("static", "app", "13_widgets_session.js")
    assert "function waBindingScope(" in session_js, "раньше функции не было — был только override"
    assert "widgetChannelScope" in js
    # per-widget override читается ПЕРВЫМ (сильнее селектора)
    scope_fn = js[js.index("function waWidgetStateUrl"):]
    assert scope_fn.index("waWidgetScopeOverrideFor(path)") < scope_fn.index("waBindingScope()")
    assert "waLoadChannelScopeSelect" in js
    assert "/api/channel-overview" in js
    # смена канала перезагружает admin-формы и скоуп-превью
    changed = js[js.index("function waChannelScopeChanged"):]
    assert "loadWidgetsAdmin();" in changed
    assert "waRefreshScopedWidgetPreviews();" in changed
    assert "waLoadChannelScopeSelect(); // Q10a" in js, "загрузка секции тянет селектор"


def test_channel_scope_i18n_in_three_languages():
    js = _read("static", "app.js")
    for key in ("'widgets.channel_scope':", "'widgets.scope_demo':"):
        assert js.count(key) == 3, key


def test_demo_mode_without_channel():
    """Q10b: без канала — демо, а не widget_scope_required."""
    js = _read("static", "app", "07_widgets.js")
    wstate = js[js.index("async function wstateapi("):]
    assert "return { ok: true, demo: true };" in wstate, "GET без скоупа не дёргает сеть"
    assert "widgets.scope_demo" in wstate, "запись без скоупа честно просит выбрать канал"
    assert "'?preview=1'" in js, "превью/URL без скоупа уходят в demo (?preview=1)"
    assert "waWidgetBestUrl(path) : path" in js, "копирование без скоупа даёт публичный URL"
    assert "wstateapi(`/api/widgets/soundboard/play/${id}`" in js, \
        "soundboard play идёт через demo-aware wstateapi"


def test_widget_scope_required_never_shown_to_user():
    """Q10c: строка widget_scope_required нигде не показывается пользователю."""
    js = _read("static", "app", "07_widgets.js")
    assert js.count("throw new Error('widget_scope_required')") == 1, \
        "единственное место — внутренний throw-инвариант waWidgetStateUrl"
    # все вызовы waWidgetStateUrl — за demo-фоллбеком или за guard-ом wstateapi
    assert "catch (e) { frame.src = widgetOutputUrl(url.pathname + '?preview=1'); }" in js
    assert "topDonatorUrl.textContent = widgetOutputUrl(`/widget/top-donator?period=${period}&preview=1`);" in js
    assert "catch (e) { url = widgetOutputUrl(`/widget/top-donator?period=${safe}&preview=1`); }" in js
    assert "catch (e) { return widgetOutputUrl(path); }" in js, "waWidgetBestUrl"
    guard = js[js.index("async function wstateapi("):]
    assert guard.index("if (!scope.account_id || !scope.channel)") < guard.index("wapi(waWidgetStateUrl(path)")
    # в шаблонах строки нет вовсе
    for partial in (ROOT / "templates" / "partials").glob("*.html"):
        assert "widget_scope_required" not in partial.read_text(encoding="utf-8"), partial.name
