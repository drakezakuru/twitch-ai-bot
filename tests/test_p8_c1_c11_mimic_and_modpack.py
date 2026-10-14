"""P8-C1 + P8-C11.

C1: копирка — свободный ввод ника чатера; «Собрать стиль чатера» собирает
ВСЮ доступную историю из нашего chat_log (до 400 сообщений) + best-effort
logs.ivr.fi (внешние API Twitch-истории не существует — SE/kappa закрыт).
C11: «Пакет модератора» — карточка-навигатор во вкладке модерации бота
(автомодерация, стрим-инструменты — тут; beep — «Чат»; blur-guard — «Виджеты»).
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_c1_mimic_free_nick_input():
    js = (ROOT / "static" / "app" / "06_roles.js").read_text(encoding="utf-8")
    assert 'id="mimicNick"' in js, "нет свободного поля ника в копирке"
    assert "mimicCandidatesList" in js, "нет подсказок для свободного ввода"
    # build читает mimicNick первым
    build = js[js.index("async function mimicBuildProfile"):]
    assert "mimicNick" in build.split("}")[0] or "mimicNick" in build[:400]


def test_c1_profile_build_full_history_and_ivr():
    src = (ROOT / "app" / "role_routes.py").read_text(encoding="utf-8")
    assert "LIMIT 400" in src, "история чатера не расширялась"
    assert "logs.ivr.fi" in src, "нет best-effort источника ivr.fi"


def test_c11_moderator_pack_card():
    html = (ROOT / "templates" / "partials" / "bots.html").read_text(encoding="utf-8")
    assert 'id="moderatorPackCard"' in html
    assert "mod.pack_beep" in html and "mod.pack_blur" in html
    app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    for key in ("mod.pack_title", "mod.pack_hint", "mod.pack_automod",
                "mod.pack_stream_tools", "mod.pack_beep", "mod.pack_blur"):
        assert app_js.count(f"'{key}':") >= 3, key
