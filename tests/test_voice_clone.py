"""Тесты для app/voice_clone.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _isolate(tmp_path, monkeypatch):
    """Изолируем VOICE_MODELS_DIR во временную папку."""
    monkeypatch.setenv("VOICE_MODELS_DIR", str(tmp_path))
    import app.voice_clone as vc
    # модуль кеширует VOICE_MODELS_DIR на импорте — патчим in-place
    monkeypatch.setattr(vc, "VOICE_MODELS_DIR", Path(tmp_path))
    return tmp_path


def test_list_voice_models_empty_dir(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    from app.voice_clone import list_voice_models, ensure_voice_dir

    ensure_voice_dir()
    assert list_voice_models() == []


def test_save_voice_model_creates_files(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    from app.voice_clone import save_voice_model_files, list_voice_models

    onnx_bytes = b"FAKE_ONNX_BYTES_FOR_TEST_12345"
    json_bytes = json.dumps({
        "audio": {"sample_rate": 22050},
        "language": {"code": "ru"},
        "num_speakers": 1,
    }).encode("utf-8")

    vm = save_voice_model_files("my_voice", onnx_bytes, json_bytes)
    assert vm.name == "my_voice"
    assert vm.exists()
    listed = list_voice_models()
    assert len(listed) == 1
    assert listed[0].name == "my_voice"
    assert listed[0].sample_rate == 22050
    assert listed[0].language == "ru"


def test_save_voice_model_without_json(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    from app.voice_clone import save_voice_model_files

    vm = save_voice_model_files("no_cfg", b"x" * 100, None)
    assert vm.exists()
    assert vm.config_path == ""


def test_save_voice_model_rejects_traversal(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    from app.voice_clone import save_voice_model_files

    with pytest.raises(ValueError):
        save_voice_model_files("../etc/passwd", b"x", None)
    with pytest.raises(ValueError):
        save_voice_model_files("foo/bar", b"x", None)
    with pytest.raises(ValueError):
        save_voice_model_files("", b"x", None)


def test_find_voice_model_resolves(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    from app.voice_clone import save_voice_model_files, find_voice_model

    save_voice_model_files("alpha", b"x" * 10, None)
    save_voice_model_files("beta", b"y" * 10, None)
    assert find_voice_model("alpha") is not None
    assert find_voice_model("ALPHA") is not None  # case-insensitive
    assert find_voice_model("gamma") is None


def test_delete_voice_model(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    from app.voice_clone import save_voice_model_files, delete_voice_model, list_voice_models

    save_voice_model_files("temp", b"x" * 10, None)
    assert len(list_voice_models()) == 1
    deleted = delete_voice_model("temp")
    assert deleted is True
    assert list_voice_models() == []


def test_delete_nonexistent_returns_false(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    from app.voice_clone import delete_voice_model

    assert delete_voice_model("does_not_exist") is False


def test_select_voice_for_account_empty_returns_none(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    from app.voice_clone import select_voice_for_account

    assert select_voice_for_account(account_id=1, voice_name="") is None
    assert select_voice_for_account(account_id=1, voice_name="missing") is None


def test_select_voice_for_account_resolves_existing(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    from app.voice_clone import save_voice_model_files, select_voice_for_account

    save_voice_model_files("streamer_voice", b"x" * 10, None)
    vm = select_voice_for_account(1, voice_name="streamer_voice")
    assert vm is not None
    assert vm.name == "streamer_voice"


def test_piper_command_constructs_argv(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    from app.voice_clone import save_voice_model_files, piper_command_for_model

    vm = save_voice_model_files("v1", b"x" * 10, json.dumps({}).encode())
    cmd = piper_command_for_model("hello", vm, "/tmp/out.wav")
    assert cmd[0] == "piper"
    assert "--model" in cmd
    assert vm.onnx_path in cmd
    assert "--output_file" in cmd
    assert "/tmp/out.wav" in cmd


def test_piper_command_without_config(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    from app.voice_clone import save_voice_model_files, piper_command_for_model

    vm = save_voice_model_files("v2", b"x" * 10, None)
    cmd = piper_command_for_model("hi", vm, "/tmp/o.wav")
    assert "--config" not in cmd


def test_voice_model_to_dict():
    from app.voice_clone import VoiceModel

    vm = VoiceModel(
        name="test", onnx_path="/tmp/x.onnx",
        config_path="/tmp/x.onnx.json",
        sample_rate=22050, language="ru", speaker_count=1,
    )
    d = vm.to_dict()
    assert d["name"] == "test"
    assert d["sample_rate"] == 22050
    assert "exists" in d


def test_write_setup_guide_creates_md(tmp_path):
    from app.voice_clone import write_setup_guide

    target = tmp_path / "guide.md"
    path = write_setup_guide(str(target))
    assert Path(path).exists()
    content = Path(path).read_text(encoding="utf-8")
    assert "Piper" in content
    assert "fine-tune" in content.lower()


def test_write_setup_guide_idempotent(tmp_path):
    from app.voice_clone import write_setup_guide

    target = tmp_path / "guide.md"
    write_setup_guide(str(target))
    first_mtime = target.stat().st_mtime
    # повторный вызов не должен перезаписывать
    write_setup_guide(str(target))
    assert target.stat().st_mtime == first_mtime
