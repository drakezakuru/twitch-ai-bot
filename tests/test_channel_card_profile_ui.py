"""Q09a: модалка «Профиль канала» — редактор инфо о стримере в карточке канала.

Проверяем, что модалка и кнопка существуют, редактор переиспользует те же
префиксные per-channel функции (`loadGlobalStreamerProfile('ccp')` и др.),
что и прежний редактор «Мозга» (источник данных один —
`/api/streamer-profile?channel=#…`), а новые i18n-строки есть на трёх языках.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def test_channels_partial_has_profile_modal():
    html = _read("templates", "partials", "channels.html")
    assert 'id="channelProfileModal"' in html
    assert 'id="channelProfileTitle"' in html
    assert 'id="channelProfileChannel"' in html
    assert 'id="channelProfileBot"' in html
    assert 'id="ccpChannel"' in html, "скрытый держатель канала для префиксного редактора"
    for field in (
        "ccpAge", "ccpGender", "ccpLocation", "ccpOccupation", "ccpStyle",
        "ccpBio", "ccpInterests", "ccpGames", "ccpScopeBadge", "ccpFacePreview",
    ):
        assert f'id="{field}"' in html
    assert "loadGlobalStreamerProfile('ccp')" in html
    assert "saveGlobalStreamerProfile('ccp')" in html
    assert "deleteGlobalStreamerProfile('ccp')" in html
    assert "uploadGlobalStreamerFace(this, 'ccp')" in html


def test_channel_card_button_opens_profile():
    js = _read("static", "app", "19_channels_bulk.js")
    assert "function openChannelProfile(" in js
    assert "openChannelProfile(this.dataset.channel)" in js, "кнопка на карточке канала"
    assert "loadGlobalStreamerProfile('ccp')" in js
    assert "channelProfileBot" in js


def test_profile_data_source_is_per_channel_api():
    py = _read("app", "routes_global_profile.py")
    assert '@router.get("/api/streamer-profile")' in py
    assert "_required_channel" in py, "без канала API отвечает 400 — скоуп '*' из UI не приходит"


def test_profile_i18n_in_three_languages():
    js = _read("static", "app.js")
    assert "'channels.profile_tab': '👤 Профиль канала'" in js
    assert "'channels.profile_tab': '👤 Channel profile'" in js
    assert "'channels.profile_tab': '👤 Профіль каналу'" in js
    assert js.count("'channels.profile_hint':") == 3
    assert js.count("'channels.profile_bot':") == 3


def test_lore_section_in_channel_profile_modal():
    """Q09b: lore per (бот × канал) — те же API, что были в «Мозге»."""
    html = _read("templates", "partials", "channels.html")
    for el_id in ("cpLoreList", "cpLoreAddForm", "cpLoreNewFact", "cpLoreNewImportance", "cpLoreNewSource"):
        assert f'id="{el_id}"' in html
    assert "cpLoreShowAdd()" in html
    assert "cpLoreAdd(true)" in html
    assert 'onchange="cpLoadLore()' in html, "смена бота перезагружает lore канала"
    assert 'data-i18n="channels.profile_lore_hint"' in html

    js = _read("static", "app", "19_channels_bulk.js")
    for fn in ("function cpLoadLore(", "function cpLoreShowAdd(", "function cpLoreHideAdd(",
               "function cpLoreAdd(", "async function cpLoreAct(", "async function cpLoreDelete("):
        assert fn in js
    assert "/api/accounts/${acc}/lore?channel=${encodeURIComponent(_channelProfileChannel)}" in js
    assert "channel: _channelProfileChannel" in js, "факт пишется ровно в этот канал, без скоупа '*'"
    assert "cpLoadLore();" in js, "открытие модалки тянет lore"

    appjs = _read("static", "app.js")
    assert appjs.count("'channels.profile_lore_hint':") == 3


def test_summary_settings_section_in_channel_profile_modal():
    """Q09c: live-сводки per-канал — override настроек бота с честным статусом."""
    html = _read("templates", "partials", "channels.html")
    for el_id in ("cpSumLiveEnabled", "cpSumLiveLang", "cpSumLiveScopeStatus"):
        assert f'id="{el_id}"' in html
    assert "cpSaveSummarySettings()" in html
    assert "cpLoadLore(); cpLoadSummarySettings()" in html, "смена бота перезагружает lore и сводки"

    js = _read("static", "app", "19_channels_bulk.js")
    assert "async function cpLoadSummarySettings(" in js
    assert "async function cpSaveSummarySettings(" in js
    assert "/api/accounts/${acc}/summarizer/settings?channel=${encodeURIComponent(_channelProfileChannel)}" in js
    assert "channel: _channelProfileChannel" in js
    assert "dynamic.scope_override" in js and "dynamic.scope_inherited" in js, \
        "честный статус: override канала или наследуется от бота"
    assert "cpLoadSummarySettings();" in js, "открытие модалки тянет настройки сводок"

    appjs = _read("static", "app.js")
    assert appjs.count("'channels.profile_summary_hint':") == 3


def test_editors_removed_from_brain():
    """Q09d: редакторы данных per-channel живут только в карточке канала."""
    brain = _read("templates", "partials", "brain.html")
    for gone in ('id="loreList"', 'id="loreAddForm"', 'id="bspChannel"', 'id="bspBio"',
                 'id="sumLiveChannel"', 'id="sumLiveEnabled"'):
        assert gone not in brain, "редактор должен уйти из «Мозга» в карточку канала"
    # браузер прогонов сводок остаётся в «Мозге»: прогон — действие, не редактор данных
    assert 'id="summarizerRunsList"' in brain
    assert 'id="sumRunStart"' in brain

    js = _read("static", "app", "11_brain_v16.js")
    assert "loadSummarizerRuns();" in js
    assert "loadBrainProfile();" not in js
    assert "loadLore(); loadSummarizerRuns(); loadSummarizerSettings();" not in js


def test_banned_topics_section_and_preset_in_channel_modal():
    """Q18b: запретные темы per-канал + пресет Twitch (DEC-OWNER-004)."""
    html = _read("templates", "partials", "channels.html")
    for el_id in ("cpBansText", "cpBansSourceBadge", "cpBansPresetText"):
        assert f'id="{el_id}"' in html
    for call in ("cpSaveBans()", "cpSeedBansFromPreset()", "cpSaveBansPreset()"):
        assert call in html
    assert 'data-i18n="channels.bans_title"' in html

    js = _read("static", "app", "19_channels_bulk.js")
    for fn in ("async function cpLoadBans(", "async function cpSaveBans(",
               "function cpSeedBansFromPreset(", "async function cpSaveBansPreset("):
        assert fn in js
    assert "/api/bans/channel?channel=${encodeURIComponent(_channelProfileChannel)}" in js
    assert "/api/bans/preset" in js
    assert "cpLoadBans();" in js, "открытие модалки тянет запреты канала"

    appjs = _read("static", "app.js")
    for key in ("'channels.bans_title':", "'channels.bans_hint':", "'channels.bans_seed':",
                "'channels.bans_preset_title':", "'channels.bans_inherited':"):
        assert appjs.count(key) == 3, key

    brain = _read("templates", "partials", "brain.html")
    assert 'id="promptBaseText"' not in brain, "глобальный редактор запреток убран из «Мозга»"
    brainjs = _read("static", "app", "11_brain_v16.js")
    assert "loadPromptBase();" not in brainjs


def test_brain_tab_removed_and_runs_moved():
    """Q19: вкладка «Мозг» убрана; прогоны — в модалке канала; мозг-файлы живы (мины)."""
    base = _read("templates", "base.html")
    assert 'data-section="brain"' not in base
    assert "showSection('brain')" not in base
    assert "{% include 'partials/brain.html' %}" not in base
    # мины Q19: мозг-файлы обслуживают ботов и виджеты — script-теги остаются
    for script in ("09_brain_p3.js", "11_brain_v16.js", "14_brain_memory.js", "15_feedback_2908.js"):
        assert f"/static/app/{script}" in base, script
    appjs = _read("static", "app.js")
    assert "if (name === 'brain') initBrain();" not in appjs
    chat_settings = _read("static", "app", "04_chat_settings.js")
    assert ("const valid = ['dashboard', 'bots', 'chat', 'analytics', "
            "'settings', 'widgets', 'chatlogger', 'channels', 'director']") in chat_settings

    html = _read("templates", "partials", "channels.html")
    for el_id in ("cpRunsList", "cpRunsForm", "cpRunStart", "cpRunEnd", "cpRunLang", "cpRunView"):
        assert f'id="{el_id}"' in html
    assert "cpStartRun()" in html and "cpRunsShowForm()" in html
    js = _read("static", "app", "19_channels_bulk.js")
    for fn in ("async function cpLoadRuns(", "async function cpStartRun(", "async function cpViewRun(",
               "async function cpDeleteRun(", "async function cpExportRun("):
        assert fn in js
    assert "/summarizer/runs?channel=${encodeURIComponent(_channelProfileChannel)}" in js
    assert "channel: _channelProfileChannel" in js, "прогон пишется на канал модалки"
    appjs = _read("static", "app.js")
    assert appjs.count("'channels.runs_title':") == 3
