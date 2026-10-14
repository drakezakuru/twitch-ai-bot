"""v10.4.3: тесты custom (OBS) источника Stream Vision.

Проверяем:
1. StreamVisionConfig.from_env() корректно считывает STREAM_SOURCE/INPUT envs;
2. _grab_frame branchится на _grab_frame_custom когда stream_source != twitch
   и stream_video_input не пуст;
3. _grab_audio пайпит ffmpeg напрямую с stream_audio_input.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.stream_vision import StreamVisionConfig, StreamVisionManager


def test_from_env_defaults_to_twitch(monkeypatch):
    for k in ("STREAM_SOURCE", "STREAM_VIDEO_INPUT", "STREAM_AUDIO_INPUT"):
        monkeypatch.delenv(k, raising=False)
    cfg = StreamVisionConfig.from_env()
    assert cfg.stream_source == "twitch"
    assert cfg.stream_video_input == ""
    assert cfg.stream_audio_input == ""


def test_from_env_reads_custom_source(monkeypatch):
    monkeypatch.setenv("STREAM_SOURCE", "custom")
    monkeypatch.setenv("STREAM_VIDEO_INPUT", "-f v4l2 -i /dev/video0")
    monkeypatch.setenv("STREAM_AUDIO_INPUT", "-f pulse -i default")
    cfg = StreamVisionConfig.from_env()
    assert cfg.stream_source == "custom"
    assert cfg.stream_video_input == "-f v4l2 -i /dev/video0"
    assert cfg.stream_audio_input == "-f pulse -i default"


def test_from_env_normalizes_source_case(monkeypatch):
    monkeypatch.setenv("STREAM_SOURCE", "  CUSTOM  ")
    cfg = StreamVisionConfig.from_env()
    assert cfg.stream_source == "custom"


@pytest.mark.asyncio
async def test_grab_frame_routes_to_custom_when_configured():
    """Если stream_source=custom и stream_video_input не пуст — должен
    вызваться _grab_frame_custom, а streamlink/ffmpeg-pipe — нет.
    """
    cfg = StreamVisionConfig(
        stream_source="custom",
        stream_video_input="-f lavfi -i color=c=red:s=320x240",
    )
    mgr = StreamVisionManager(ai_service=None, cfg=cfg)
    sentinel = object()
    with patch.object(mgr, "_grab_frame_custom", new=AsyncMock(return_value=sentinel)) as mock_custom:
        result = await mgr._grab_frame("anybody")
    assert result is sentinel
    mock_custom.assert_awaited_once_with("anybody")


@pytest.mark.asyncio
async def test_grab_frame_falls_back_to_twitch_when_input_empty():
    """Если stream_source=custom, но stream_video_input='', НЕ зовём custom —
    идём по старому пути streamlink (он, конечно, упадёт в тесте — но мы
    мокнем create_subprocess_shell чтобы убедиться что URL — это twitch.tv).
    """
    cfg = StreamVisionConfig(stream_source="custom", stream_video_input="")
    mgr = StreamVisionManager(ai_service=None, cfg=cfg)
    captured: dict = {}

    async def fake_subprocess(cmd, **kw):
        captured["cmd"] = cmd

        class _Proc:
            returncode = 1

            async def communicate(self):
                return (b"", b"error")

        return _Proc()

    with patch("asyncio.create_subprocess_shell", new=fake_subprocess):
        result = await mgr._grab_frame("somebody")
    assert result is None
    assert "twitch.tv/somebody" in captured["cmd"]
    assert "streamlink" in captured["cmd"]


@pytest.mark.asyncio
async def test_grab_audio_uses_custom_input_when_configured():
    cfg = StreamVisionConfig(
        stream_source="custom",
        stream_video_input="-f v4l2 -i /dev/video0",
        stream_audio_input="-f pulse -i default",
    )
    mgr = StreamVisionManager(ai_service=None, cfg=cfg)
    captured: dict = {}

    async def fake_subprocess(cmd, **kw):
        captured["cmd"] = cmd

        class _Proc:
            returncode = 1

            async def communicate(self):
                return (b"", b"")

        return _Proc()

    with patch("asyncio.create_subprocess_shell", new=fake_subprocess):
        result = await mgr._grab_audio("anybody", duration=5)
    assert result is None
    # custom-путь: ffmpeg напрямую, БЕЗ streamlink, без twitch.tv URL
    assert "streamlink" not in captured["cmd"]
    assert "twitch.tv" not in captured["cmd"]
    assert "-f pulse -i default" in captured["cmd"]
