"""Q11a/Q11b → Q27b/Q27c: биндинги «КОГДА → ТОГДА» с автоподстановкой бота.

Q11a: ручные селекты бота/канала заменены авто-подстановкой — скоуп правил =
общий скоуп «Виджетов» (селектор канала, Q10a); бот-модератор канала
подставляется сам (/api/channel-overview отдаёт роли).
Q11b: у виджета без биндингов (нет binding_slug) в UI нет ни одного упоминания
биндингов.
Q27b/Q27c (DEC-OWNER-017): правила живут в карточке виджета (details
.wa-widget-rules); общая модалка/карточка/список/селект виджета/пресет-селект
удалены.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def test_q27c_general_builder_is_gone():
    html = _read("templates", "partials", "widgets.html")
    session = _read("static", "app", "13_widgets_session.js")
    # общая карточка автоматизации, модалка и её селекты снесены
    for anchor in ('id="waBindingsCard"', 'id="waBindingBuilder"', 'id="waBindWidget"',
                   'id="waBindingsList"', 'id="waBindPreset"', 'id="waBindAutoLine"',
                   'id="waBindBotPickField"', 'id="waBindAddBtn"', 'waBindingModalOpen',
                   'waBindingsCount'):
        assert anchor not in html, anchor
        assert anchor not in session, anchor
    # owning-тест Q27c: нет общего списка правил и селекта виджета в форме правил
    assert "waBindingsList" not in html + session
    assert 'id="waBindSource"' not in html + session


def test_q11a_builder_scope_is_automatic():
    html = _read("templates", "partials", "widgets.html")
    session = _read("static", "app", "13_widgets_session.js")
    # ручные селекты скоупа удалены
    assert 'id="waBindAccount"' not in html
    assert 'id="waBindChannel"' not in html
    # скоуп правил делегирован общему channel-first скоупу
    assert "const raw = waChannelScopeStored();" in session
    # авто-строка «у бота X на канале #Y» — в секциях карточек
    assert "function waRulesAutoLine(" in session
    assert "window._waChannelScopeBots" in session
    assert "waBindingsLoad()" in session


def test_q11a_moderator_bot_is_preferred_for_scope():
    admin = _read("static", "app", "07_widgets.js")
    assert "b.connected && b.role === 'moderator'" in admin, "модератор-бот подставляется сам"
    assert "window._waChannelScopeBots" in admin
    backend = _read("app", "bulk_channels_routes.py")
    assert "a.bot_role" in backend, "/api/channel-overview отдаёт роли ботов"


def test_q11a_builder_when_then_kept():
    # Q27b: КОГДА → ТОГДА — в inline-форме секции карточки (строится JS-ом)
    session = _read("static", "app", "13_widgets_session.js")
    assert "t('bindings.when')" in session
    assert "t('bindings.then')" in session
    assert "wa-rules-source" in session and "wa-rules-action" in session
    # в шаблоне секции правил есть у каждого виджета с контрактом
    html = _read("templates", "partials", "widgets.html")
    assert 'data-rules-slug="{{ widget.binding_slug }}"' in html
    assert 'data-rules-slug="goals"' in html
