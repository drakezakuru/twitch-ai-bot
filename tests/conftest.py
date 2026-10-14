"""pytest fixtures.

Архитектура изоляции БД (HANDOFF_DB_LOCK_BUG.md):
  1. Патч aiosqlite.connect ставится ПЕРВЫМ (до импорта app.*) — каждый
     коннект попадает в реестр tests/_db_registry.py.
  2. tmp_db — autouse: КАЖДЫЙ тест получает свой tmp_path/bot.db
     (в т.ч. тесты, которые раньше писали в реальный data/bot.db).
  3. Teardown: синхронное закрытие ВСЕХ коннектов в их worker-потоках.
     Никаких cross-loop await close() — они вечновиснут (aiosqlite 0.22.1).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make project root importable
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ШАГ 1: реестр коннектов — патч ДО любого импорта app.*
from tests import _db_registry  # noqa: E402

_db_registry.install()


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    """Изоляция БД: каждый тест — свой tmp_path/bot.db.

    autouse: typing-тесты и прочие, забывшие фикстуру, тоже не трогают
    реальный data/bot.db. Тесты, самостоятельно патчащие DB_PATH,
    перекрывают эту подмену без конфликтов.
    """
    db_dir = tmp_path / "data"
    db_dir.mkdir()
    db_path = db_dir / "bot.db"
    monkeypatch.setenv("QA_PROFILE", "1")
    from app import database as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)
    # До теста: гасим всё, что пережило предыдущий тест (реестр надёжнее
    # ручного закрытия: ловит и «дикие» коннекты мимо синглтона).
    _db_registry.close_all()
    db_mod._shared_db = None
    db_mod._init_lock = None
    db_mod._init_lock_loop = None
    yield db_path
    # После теста: закрыть ВСЁ (shared + дикие коннекты), сбросить синглтоны.
    _db_registry.close_all()
    db_mod._shared_db = None
    db_mod._init_lock = None
    db_mod._init_lock_loop = None
    leftover = _db_registry.open_count()
    if leftover:
        # Диагностика утечки: не валим прогон, но громко пишем кто виноват.
        import os as _os
        detail = ""
        if _os.environ.get("DB_DEBUG_LOCK"):
            try:
                detail = str(_db_registry.describe_all())
            except Exception:
                detail = "describe failed"
        print(f"\n[DB-LEAK] после {db_path}: {leftover} открытых коннектов {detail}",
              flush=True)
        _db_registry.close_all()


@pytest.fixture()
def disable_auth(monkeypatch):
    """Гарантирует, что аутентификация панели выключена."""
    for key in ("PANEL_AUTH_USER", "PANEL_AUTH_PASS"):
        monkeypatch.delenv(key, raising=False)
    yield


@pytest.fixture(autouse=True)
def _reset_blur_guard_state():
    """Blur Guard держит состояние блюра в модульном dict (app/blur_guard.py::_state).

    Без сброса `/blur-guard/temp` из одного файла тестов оставляет блюр включённым
    для следующего — падает test_widget_blur_guard.py::test_manual_binds_and_state
    в зависимости от порядка файлов. БД тут не поможет: состояние не в БД.
    """
    def _reset():
        bg = sys.modules.get("app.blur_guard")
        if bg is None:
            return
        bg._state.update(blur_until=0.0, manual_on=False,
                         manual_off_until=0.0, last_check=0.0)

    _reset()
    yield
    _reset()


@pytest.fixture(autouse=True)
def _restore_app_server_module():
    """Изолирует подмены sys.modules['app.server'] внутри каждого теста.

    Несколько тестов подсовывают routes.py модуль-заглушку app.server
    (ai_summary, ai_compare, actor_revert_cmdk и др.). Если тест забыл
    восстановить модуль, все последующие тесты импортируют заглушку и падают
    с ImportError/AttributeError. Здесь модуль восстанавливается гарантированно.
    """
    saved = sys.modules.get("app.server")
    yield
    if saved is not None:
        sys.modules["app.server"] = saved
    else:
        sys.modules.pop("app.server", None)
