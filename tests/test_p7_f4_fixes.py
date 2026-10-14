"""P7 Ф4 — регресс-тесты fixes. Ф2-2: /api/moderation/pending на СВЕЖЕЙ БД.

Прецедент-класс: snippets (эндпоинт жил, таблицы не было → 500 на новых
инсталляциях; ddbfb8f). Ленивый создатель moderation._ensure_extra_schema()
теперь вызывается в list_pending_timeouts/record_timeout_decision —
проверяем, что GET отдаёт 200 на пустой tmp_db, а не 500.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio


async def test_moderation_pending_ok_on_fresh_db():
    """GET /api/moderation/pending на свежей базе — 200 (не «no such table»)."""
    from app.server import app
    from app import moderation as _mod

    # флаг ленивой схемы — глобальный по процессу; предыдущие тесты
    # модерации выставили его для СВОЕЙ tmp-базы
    _mod._extra_schema_ready = False

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/moderation/pending")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["events"] == []
    assert data["total"] == 0


def test_hash_whitelist_covers_all_sections():
    """Ф2-4: диплинк #brain открывался как dashboard — 'brain' забыт в
    whitelist hash-restore. Whitelist должен покрывать ВСЕ section-контейнеры
    шаблонов (сейчас их 7)."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    tpl = ""
    for p in (root / "templates").rglob("*.html"):
        # brain.html — паршал, убранный из рендера
        # (Q19 comment в base.html); их «section-*» не открыть диплинком,
        # т.к. base.html их вообще не включает.
        if p.name in ("brain.html",):
            continue
        tpl += p.read_text(encoding="utf-8")
    sections = set(re.findall(r'id="section-([a-z]+)"', tpl))
    js = "\n".join(
        p.read_text(encoding="utf-8")
        for p in (root / "static" / "app.js", *(root / "static" / "app").glob("*.js"))
    )
    m = re.search(r"const valid = \[(.*?)\]", js, re.S)
    assert m, "whitelist hash-restore не найден"
    valid = set(re.findall(r"'([a-z]+)'", m.group(1)))
    assert sections <= valid, f"секции без диплинка: {sections - valid}"


def test_blur_example_text_not_hardcoded():
    """F5: пояснение примера блюра не должно содержать захардкоженные
    «15 сек / 100%» — значения показываются живыми span waBgPrevDur/waBgPrevPct,
    которые синхронизирует waBgPreviewSync."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    tpl = (root / "templates" / "partials" / "widgets.html").read_text(encoding="utf-8")
    assert 'id="waBgPrevDur"' in tpl and 'id="waBgPrevPct"' in tpl, \
        "живые span'ы примера пропали из шаблона"
    js = "\n".join(p.read_text(encoding="utf-8")
                   for p in (root / "static" / "app").glob("*.js"))
    assert "waBgPreviewSync" in js and "waBgPrevDur" in js, \
        "синхронизация примера пропала"
    # ни в шаблоне, ни в i18n не должно остаться «на 15 сек, … на 100%»
    assert "на 15 сек" not in tpl
    for p in (root / "static" / "app").glob("*.js"):
        t = p.read_text(encoding="utf-8")
        assert "на 15 сек, экран закрыт на 100%" not in t, p.name
        assert "for 15s at 100%" not in t, p.name


def test_moderation_ai_hint_present():
    """F6: в карточке «🛡 Автомодерация» есть пояснение, что ИИ не участвует
    (словари+правила), а ИИ-анализ — вкладка «Анализатор»."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    tpl = (root / "templates" / "partials" / "bots.html").read_text(encoding="utf-8")
    # data-i18n-атрибут внутри тега допустим (i18n-заглушка поверх текста)
    assert ">без ИИ</strong>" in tpl
    assert "Анализатор" in tpl


def test_donations_form_has_example_line():
    """F1 (целевое состояние): служебная форма «Донат-интеграции» — без живого
    превью, но со строкой «👀 Например»."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    tpl = (root / "templates" / "partials" / "widgets.html").read_text(encoding="utf-8")
    assert "👀 Например: донат «Nick" in tpl


def test_dead_stream_commands_block_removed():
    """Ф1-1: мёртвый JS-блок §S6 «Команды стримера» (дергал несуществующий
    /api/stream-commands, в UI не был подключен) — удалён. Если фича вернётся,
    роут и UI делаются вместе."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    js = "\n".join(p.read_text(encoding="utf-8")
                   for p in (root / "static" / "app.js", *(root / "static" / "app").glob("*.js")))
    assert "stream-commands" not in js
    assert "loadStreamerCommands" not in js
    assert "streamer.cmd_title" not in js


def test_inputs_can_shrink_on_narrow_screens():
    """Ф2-3: .input/.field-* имеют max-width:100%, .form-group/.flex —
    min-width:0 (иначе фиксированные ширины дают overflow на 390px)."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    css = (root / "static" / "app.css").read_text(encoding="utf-8")
    assert "max-width: 100%;" in css.split(".field-220")[1][:200]
    assert ".form-group { min-width: 0; }" in css
    assert ".flex { min-width: 0; }" in css
    # и перенос строк на узком экране (вторая итерация Ф2-3)
    assert ".flex { flex-wrap: wrap; }" in css
    assert ".form-group { min-width: 0 !important; max-width: 100%; }" in css
    # базовое правило .input содержит max-width:100%
    base = css.split("\n.input {", 1)[1].split("}", 1)[0]
    assert "max-width: 100%;" in base
