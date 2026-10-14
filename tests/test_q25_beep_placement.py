"""Q25 (DEC-OWNER-005): настройка beep-конвейера живёт у бота-модератора.

Карточка beep_pipeline переехала из вкладки «Чат» в botTab-moderation;
бэкенд (beep_guard/beep_pipeline, beep_settings) не менялся — переехала только
точка входа в UI. Статус честный: работает или pass-through.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAT = (ROOT / "templates/partials/chat.html").read_text(encoding="utf-8")
BOTS = (ROOT / "templates/partials/bots.html").read_text(encoding="utf-8")
MOD_JS = (ROOT / "static/app/08_providers_moderation.js").read_text(encoding="utf-8")
STREAM_JS = (ROOT / "static/app/10_stream_p4_p6.js").read_text(encoding="utf-8")
APP_JS = (ROOT / "static/app.js").read_text(encoding="utf-8")

BP_IDS = ("beepPipelineCard", "bpEnabled", "bpSource", "bpSink", "bpHz", "bpSeg", "bpWhisperWarn", "bpStatus")


def test_beep_card_lives_in_moderator_bot_tab():
    moderation_tab = BOTS[BOTS.index('id="botTab-moderation"'):BOTS.index('id="botTab-memory"')]
    for element_id in BP_IDS:
        assert f'id="{element_id}"' in moderation_tab, element_id
    # Пакет модератора ссылает на карточку ниже, а не на вкладку «Чат».
    assert "getElementById('beepPipelineCard').scrollIntoView" in moderation_tab


def test_beep_card_removed_from_chat_section():
    for element_id in BP_IDS:
        assert f'id="{element_id}"' not in CHAT, element_id


def test_beep_pipeline_loads_with_moderation_tab_only():
    assert "loadBeepPipeline(); // Q25" in MOD_JS
    # Входе в «Чат» карточки больше нет — загрузка убрана.
    assert "if (name === 'chat') initChat(); // Q25" in APP_JS
    assert "loadBeepPipeline()" not in APP_JS.split("function showSection")[1].split("function initLang")[0]


def test_honest_status_pass_through_and_i18n():
    for lang_fragment in ("pass-through (звук идёт без обработки)",
                          "pass-through (audio goes through untreated)",
                          "pass-through (звук іде без обробки)"):
        assert lang_fragment in STREAM_JS
    for pack in ("'mod.pack_beep': 'Запикивание — ниже,'".replace(",", ""),
                 "'mod.pack_beep': 'Beep pipeline — below',",
                 "'mod.pack_beep': 'Запікування — нижче',"):
        assert pack in APP_JS


def test_backend_untouched():
    guard = (ROOT / "app/beep_pipeline.py").read_text(encoding="utf-8")
    assert 'get_setting("beep_pipeline", "")' in guard
    assert "beep_guard.ensure_schema" not in guard  # контракт beep_settings не менялся
