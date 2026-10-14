"""Тесты модуля twitch_credentials.

Проверяют, что:
  - значения из БД (UI) имеют приоритет над .env;
  - если БД пуста — используется .env (обратная совместимость);
  - get_status() корректно показывает источник;
  - save_to_db() реально применяет значения и подтягивается через load_from_db().
"""
from __future__ import annotations

import os

import pytest

from app import twitch_credentials


def _reset_runtime():
    twitch_credentials._runtime["client_id"] = None
    twitch_credentials._runtime["client_secret"] = None


def test_env_fallback(monkeypatch):
    _reset_runtime()
    monkeypatch.setenv("TWITCH_CLIENT_ID", "env_id")
    monkeypatch.setenv("TWITCH_CLIENT_SECRET", "env_secret")
    assert twitch_credentials.get_client_id() == "env_id"
    assert twitch_credentials.get_client_secret() == "env_secret"
    assert twitch_credentials.is_helix_configured() is True
    assert twitch_credentials.is_device_flow_configured() is True
    status = twitch_credentials.get_status()
    assert status["client_id_source"] == "env"
    assert status["client_secret_source"] == "env"


def test_runtime_overrides_env(monkeypatch):
    _reset_runtime()
    monkeypatch.setenv("TWITCH_CLIENT_ID", "env_id")
    twitch_credentials.set_runtime_credentials(client_id="ui_id")
    assert twitch_credentials.get_client_id() == "ui_id"
    status = twitch_credentials.get_status()
    assert status["client_id_source"] == "db"
    assert status["client_id"] == "ui_id"
    _reset_runtime()


def test_empty_runtime_falls_back_to_env(monkeypatch):
    _reset_runtime()
    monkeypatch.setenv("TWITCH_CLIENT_ID", "env_id")
    twitch_credentials.set_runtime_credentials(client_id="")  # очистили UI override
    # Пустая строка трактуется как "снять override" -> снова env
    assert twitch_credentials.get_client_id() == "env_id"
    _reset_runtime()


def test_no_creds(monkeypatch):
    _reset_runtime()
    monkeypatch.delenv("TWITCH_CLIENT_ID", raising=False)
    monkeypatch.delenv("TWITCH_CLIENT_SECRET", raising=False)
    assert twitch_credentials.get_client_id() == ""
    assert twitch_credentials.is_helix_configured() is False
    status = twitch_credentials.get_status()
    assert status["client_id_source"] == "none"
    assert status["client_secret_set"] is False


def test_status_does_not_leak_secret(monkeypatch):
    _reset_runtime()
    monkeypatch.setenv("TWITCH_CLIENT_SECRET", "supersecret")
    status = twitch_credentials.get_status()
    # client_secret НЕ должен присутствовать в ответе (только флаг client_secret_set)
    assert "client_secret" not in status
    assert status["client_secret_set"] is True


@pytest.mark.asyncio
async def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    """save_to_db() пишет в БД, потом load_from_db() поднимает оттуда."""
    from pathlib import Path

    from app import database

    _reset_runtime()
    monkeypatch.setattr(database, "DB_PATH", Path(tmp_path) / "test.db")
    await database.init_db()
    try:
        await twitch_credentials.save_to_db(
            client_id="db_id_xyz", client_secret="db_secret_abc"
        )
        # Очистим runtime — будто бы рестарт сервера
        _reset_runtime()
        await twitch_credentials.load_from_db()
        assert twitch_credentials.get_client_id() == "db_id_xyz"
        assert twitch_credentials.get_client_secret() == "db_secret_abc"
        status = twitch_credentials.get_status()
        assert status["client_id_source"] == "db"
        assert status["client_secret_source"] == "db"
    finally:
        await database.close_db()
        _reset_runtime()


@pytest.mark.asyncio
async def test_client_secret_is_encrypted_at_rest(tmp_path, monkeypatch):
    from pathlib import Path
    from cryptography.fernet import Fernet

    from app import database, security

    _reset_runtime()
    monkeypatch.setattr(database, "DB_PATH", Path(tmp_path) / "encrypted.db")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    security._FERNET = None
    security._FERNET_TRIED = False
    await database.init_db()
    try:
        await twitch_credentials.save_to_db(client_secret="db_secret_abc")
        stored = await database.get_setting(twitch_credentials.KEY_CLIENT_SECRET, "")
        assert stored.startswith("enc::")
        assert "db_secret_abc" not in stored

        _reset_runtime()
        await twitch_credentials.load_from_db()
        assert twitch_credentials.get_client_secret() == "db_secret_abc"
    finally:
        await database.close_db()
        _reset_runtime()
        security._FERNET = None
        security._FERNET_TRIED = False
