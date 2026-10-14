"""P8-A2: вечное «Загрузка...» в Аналитике.

C-010 migration: поведение (init-цепочка showSection, empty/error state
loadAnalytics/loadAnalyticsLogs/loadHeatmap/loadChat24h/loadFeedbackSummary,
фильтры, no eternal «Загрузка...») доказывается исполнением продакшн-кода в
Node VM — `tests/panel_analytics_state.test.js`. Здесь остаются non-runtime
контракты: разметка analytics.html наполняется чем-то из панельного JS и
i18n-ключ analytics.empty ×3.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "static" / "app.js"
CHAT_JS = ROOT / "static" / "app" / "04_chat_settings.js"
WIDGETS_JS = ROOT / "static" / "app" / "07_widgets.js"
ANALYTICS_HTML = ROOT / "templates" / "partials" / "analytics.html"


def test_analytics_placeholder_ids_have_loaders():
    """Каждый id из analytics.html должен встречаться в панельном JS —
    иначе элемент ничем не наполняется. (P8-C14: trending-блок удалён.)"""
    html = ANALYTICS_HTML.read_text(encoding="utf-8")
    ids = set(re.findall(r'id="(\w+)"', html))
    assert "trendingList" not in ids, "trending-карточка должна быть удалена (C14)"
    assert {"sentimentSummary", "feedbackSummaryBox", "heatmapGrid",
            "chartHour24", "analyticsLogsContent"} <= ids, \
        f"разметка analytics.html изменилась — обнови тест: {sorted(ids)}"
    js = "\n".join(p.read_text(encoding="utf-8") for p in (APP_JS, CHAT_JS, WIDGETS_JS,
                                      ROOT / "static" / "app" / "08_providers_moderation.js"))
    missing = [i for i in sorted(ids) if f"$('{i}')" not in js and f"getElementById('{i}')" not in js]
    assert not missing, f"элементы Аналитики, которые ничто не наполняет: {missing}"


def test_analytics_empty_i18n_key_all_langs():
    src = APP_JS.read_text(encoding="utf-8")
    assert re.search(r"'analytics\.empty':\s*'[^']+'", src), "нет ключа analytics.empty"
    assert "Данных пока нет" in src


def test_analytics_runtime_behavior():
    """Node VM исполняет продакшн-лоадеры Аналитики (loading/empty/error)."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for panel behavior tests")
    subprocess.run(
        [node, "--test", "tests/panel_analytics_state.test.js"],
        cwd=ROOT,
        check=True,
    )
