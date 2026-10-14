"""P8-B1/B2/B3/B5 + W1/W2: «виджеты поехали».

B1: у формы с живым iframe — ровно ОДНО превью (mini-preview удалены),
iframe-превью на тёмном фоне (никакого «белого говна» на пустых данных).
B2: пресеты биндингов («💀 Смерти / ⭐ Саб-цель / ⏳ Countdown») только на
5 релевантных карточках К2-набора (goals/sub_goal/now_playing/counter/countdown).
B3: у форм без живого превью есть «👀 Например».
W1: зоны blur-guard применяются живо по WS (PUT /api/blur-guard {always_zones}
→ broadcast blur_config с always_zones; виджет уже ловит always_zones).
W2: dead-подписки clean_frame/dirty_frame удалены из blur-guard-v2.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
W_HTML = ROOT / "templates" / "partials" / "widgets.html"
V2_HTML = ROOT / "widgets" / "blur-guard-v2" / "index.html"


def _card_of(anchor: str) -> str:
    s = W_HTML.read_text(encoding="utf-8")
    i = s.index(anchor)
    j = s.rindex('<div class="card mb-4"', 0, i)
    # тело карточки до следующей карточки
    nxt = s.find('<div class="card mb-4"', i)
    return s[j:nxt if nxt != -1 else len(s)]


def test_b1_single_preview_per_form():
    s = W_HTML.read_text(encoding="utf-8")
    # mini-preview остался только у blur-guard (нет живого iframe)
    assert s.count('class="mini-preview"') == 1
    for anchor in ("widget.goals.title", "widget.sub_goal.title", "widget.now_playing.title",
                   "widget.schedule.title", "⏳ Countdown",
                   "widgets.donators", "widgets.songs"):
        card = _card_of(anchor)
        assert "mini-preview" not in card, f"у {anchor} осталось двойное превью"
        assert "widget-preview" in card, f"у {anchor} пропало живое превью"


def test_b1_dark_preview_background():
    s = W_HTML.read_text(encoding="utf-8")
    iframes = re.findall(r'<iframe class="widget-preview"[^>]*>', s)
    assert iframes, "нет живых превью"
    assert all("background:#0f0f1a" in f for f in iframes), "iframe-превью без тёмного фона"


def test_b2_legacy_card_presets_removed():
    s = W_HTML.read_text(encoding="utf-8")
    assert "data-wa-presets" not in s
    tail = (ROOT / "static" / "app" / "16_tail.js").read_text(encoding="utf-8")
    assert "WIDGET_PRESETS" not in tail
    assert "wa-preset-btns" not in tail


def test_b3_examples_for_forms_without_preview():
    s = W_HTML.read_text(encoding="utf-8")
    for anchor, key in (
        ("cp_tts.title", "widgets.example.cp_tts"),
        ("tts_chat.title", "widgets.example.tts_chat"),
        ("🗳 Twitch-голосование", "widgets.example.poll"),
        ("🦾 Субатон", "widgets.example.subathon"),
    ):
        card = _card_of(anchor)
        assert key in card, f"нет «👀 Например» у {anchor}"
    # i18n всех новых ключей в 3 языках
    js = (ROOT / "static" / "app" / "15_feedback_2908.js").read_text(encoding="utf-8")
    for key in ("widgets.example.cp_tts", "widgets.example.tts_chat",
                "widgets.example.poll", "widgets.example.subathon"):
        assert js.count(f"'{key}':") >= 3, key


def test_w1_zones_live_update():
    src = (ROOT / "app" / "blur_guard.py").read_text(encoding="utf-8")
    assert "always_zones" in src
    # Проверяем поведение, а не форматирование вызова: сохранение зон/процента
    # должно рассылать blur_config открытым оверлеям.
    assert '_broadcast("blur_config", payload)' in src, "живая рассылка blur_config пропала"
    # payload собирается из _runtime_config (always_zones включены) до рассылки
    fn = src.split("async def broadcast_runtime", 1)
    assert len(fn) == 2
    assert "payload = _runtime_config(await get_settings())" in fn[1].split("\nasync def", 1)[0]
    config = src.split("def _runtime_config", 1)
    assert len(config) == 2
    assert '"always_zones"' in config[1].split("\ndef ", 1)[0]
    routes = (ROOT / "static" / "app" / "10_stream_p4_p6.js").read_text(encoding="utf-8")
    assert "applyBlurZonesLive" in routes
    html = W_HTML.read_text(encoding="utf-8")
    assert "applyBlurZonesLive()" in html
    v2 = V2_HTML.read_text(encoding="utf-8")
    assert "always_zones" in v2, "виджет не применяет зоны из blur_config"


def test_w2_dead_subscriptions_removed():
    v2 = V2_HTML.read_text(encoding="utf-8")
    assert 'case "clean_frame"' not in v2
    assert 'case "dirty_frame"' not in v2
    assert "function reportCleanFrame" not in v2
    assert "function reportDirtyFrame" not in v2
