"""BOT-CHANNEL-UI: CRUD каналов в панели и привязка канала к боту.

Проверяются разметка/скрипты панели (API-контракт живёт в tests/test_channel_admin.py).
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CHANNELS_HTML = REPO / "templates" / "partials" / "channels.html"
CHANNELS_JS = REPO / "static" / "app" / "19_channels_bulk.js"
BOTS_JS = REPO / "static" / "app" / "03_bots.js"
APP_JS = REPO / "static" / "app.js"

CHANNELS_KEYS = (
    "channels.add", "channels.add_hint", "channels.add_bot", "channels.add_no_bots",
    "channels.add_invalid", "channels.rename", "channels.rename_prompt", "channels.rename_conflict",
    "channels.delete", "channels.delete_hint", "channels.delete_no_data", "channels.delete_confirm_data",
    "channels.deps_failed", "channels.binding_actions",
    "toast.channel_renamed", "toast.channel_rename_failed", "toast.channel_add_failed",
    "toast.channel_delete_failed",
)
BOTS_KEYS = ("bots.change_channel", "bots.change_channel_hint", "bots.change_channel_new",
             "bots.change_channel_none")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_channels_section_has_create_and_delete_modals():
    """BC-4: в секции «Каналы» есть добавление канала и подтверждение удаления."""
    tpl = _read(CHANNELS_HTML)
    assert tpl.count('id="channelCreateModal"') == 1
    assert tpl.count('id="channelCreateName"') == 1
    assert tpl.count('id="channelCreateBot"') == 1
    assert "openChannelCreateModal()" in tpl
    assert "submitChannelCreate()" in tpl
    assert tpl.count('id="channelDepsModal"') == 1
    assert tpl.count('id="channelDepsConfirm"') == 1
    assert "confirmChannelDelete()" in tpl
    # существующая bulk-связка не тронута
    assert "openChannelToBotsBulk" in _read(CHANNELS_JS)


def test_channels_overview_renders_binding_actions():
    """Карточка канала: переименование и удаление привязки доступны из секции."""
    js = _read(CHANNELS_JS)
    assert "openChannelRenameModal(" in js
    assert "openChannelDeleteModal(" in js
    assert "renameChannelBinding(" in js
    assert "/dependencies" in js
    assert "channel_has_dependencies" in js
    assert "?force=true" in js
    assert "binding_id" in js


def test_channel_i18n_defined_in_three_languages():
    app = _read(APP_JS)
    for key in CHANNELS_KEYS + BOTS_KEYS:
        assert app.count(f"'{key}'") >= 3, key


def test_bot_card_has_change_channel_action():
    """BC-1/BC-2: смена канала доступна с карточки бота, без ухода в другую секцию."""
    js = _read(BOTS_JS)
    assert "openBotChannelModal(" in js
    assert "botChannelLoad(" in js
    assert "botChannelAttach(" in js
    assert "botChannelCreate(" in js
    assert "botChannelRename(" in js
    assert "botChannelDetach(" in js
    assert js.count("openBotChannelModal(") >= 2  # кнопка на карточке + объявление функции


def test_bot_change_channel_modal_markup():
    js = _read(BOTS_JS)
    assert "overlay.id = 'botChannelModal'" in js
    assert 'id="botChannelAddSelect"' in js
    assert 'id="botChannelNewName"' in js
    # перенос существующей привязки использует PATCH с account_id (BC-1)
    assert re.search(r"jopts\('PATCH', \{account_id: accountId\}\)", js)
    assert "openPanelDialog(" in js


def test_bot_remove_channel_confirms_dependencies():
    """Удаление канала из карточки бота не сносит данные без подтверждения."""
    js = _read(BOTS_JS)
    fn = js.split("async function removeChannel(", 1)[1].split("\n}", 1)[0]
    assert "channel_has_dependencies" in fn
    assert "force=true" in fn
    assert "window.confirm(" in fn
