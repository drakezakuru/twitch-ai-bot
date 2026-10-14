"""v10.4.6 Wave 3: Voice cloning через Piper fine-tune.

Piper уже используется в TTS-стеке. Здесь мы добавляем:

1. Конфиг кастомных голосовых моделей: `voice_models/<bot_id>.onnx + .onnx.json`.
2. Helper `select_voice_for_account(account_id)` — резолвит путь к onnx.
3. UI-API чтобы загружать .onnx-файлы.
4. Документация по fine-tune'у (см. ``app/voice_clone_setup.md``).

Сам fine-tune НЕ делается в run-time (это требует GPU и датасета 5-10 мин).
Юзер тренирует модель локально и заливает готовый `.onnx + .json` через API.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# Дефолт — относительно корня проекта (переносимо между машинами и ОС).
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
VOICE_MODELS_DIR = Path(os.getenv("VOICE_MODELS_DIR", str(_PROJECT_ROOT / "data" / "voice_models")))
VOICE_CLONES_DIR = Path(os.getenv("VOICE_CLONES_DIR", str(VOICE_MODELS_DIR.parent / "voice_clones")))


def ensure_voice_dir() -> Path:
    VOICE_MODELS_DIR.mkdir(parents=True, exist_ok=True)
    return VOICE_MODELS_DIR


def ensure_clone_dir() -> Path:
    VOICE_CLONES_DIR.mkdir(parents=True, exist_ok=True)
    return VOICE_CLONES_DIR


def save_clone_sample(name: str, sample_bytes: bytes, suffix: str = ".wav") -> str:
    """Store a local clone sample without allowing path traversal."""
    safe_name = "".join(c for c in (name or "").strip() if c.isalnum() or c in "-_ ").strip()
    if not safe_name or len(sample_bytes) > 25 * 1024 * 1024:
        raise ValueError("invalid clone sample")
    suffix = suffix.lower() if suffix.lower() in {".wav", ".mp3", ".flac", ".ogg"} else ".wav"
    path = ensure_clone_dir() / f"{safe_name}-{uuid.uuid4().hex[:10]}{suffix}"
    path.write_bytes(sample_bytes)
    return str(path.absolute())


@dataclass
class VoiceModel:
    """Описание загруженной voice-model."""

    name: str
    onnx_path: str
    config_path: str = ""
    sample_rate: int = 22050
    language: str = "ru"
    speaker_count: int = 1

    def exists(self) -> bool:
        return Path(self.onnx_path).exists()

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "onnx_path": self.onnx_path,
            "config_path": self.config_path,
            "sample_rate": self.sample_rate,
            "language": self.language,
            "speaker_count": self.speaker_count,
            "exists": self.exists(),
        }


def list_voice_models() -> list[VoiceModel]:
    """Сканирует каталог voice_models и возвращает все .onnx-голосовые модели."""
    ensure_voice_dir()
    out: list[VoiceModel] = []
    for f in sorted(VOICE_MODELS_DIR.iterdir()):
        if f.suffix.lower() != ".onnx":
            continue
        name = f.stem
        cfg_path = f.with_suffix(".onnx.json")
        cfg = {}
        if cfg_path.exists():
            try:
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.debug("voice config parse error for %s: %s", cfg_path, exc)
        out.append(VoiceModel(
            name=name,
            onnx_path=str(f.absolute()),
            config_path=str(cfg_path.absolute()) if cfg_path.exists() else "",
            sample_rate=int(cfg.get("audio", {}).get("sample_rate", 22050)),
            language=str(cfg.get("language", {}).get("code", "ru")),
            speaker_count=int(cfg.get("num_speakers", 1) or 1),
        ))
    return out


def find_voice_model(name: str) -> Optional[VoiceModel]:
    """Резолвит модель по имени."""
    for vm in list_voice_models():
        if vm.name.lower() == (name or "").lower():
            return vm
    return None


def save_voice_model_files(name: str, onnx_bytes: bytes, json_bytes: bytes | None = None) -> VoiceModel:
    """Сохраняет загруженный .onnx (+ опциональный .onnx.json)."""
    ensure_voice_dir()
    if not name or "/" in name or ".." in name:
        raise ValueError("invalid voice name")
    onnx_path = VOICE_MODELS_DIR / f"{name}.onnx"
    onnx_path.write_bytes(onnx_bytes)
    config_path = ""
    if json_bytes:
        cfg = VOICE_MODELS_DIR / f"{name}.onnx.json"
        cfg.write_bytes(json_bytes)
        config_path = str(cfg.absolute())
    return VoiceModel(
        name=name,
        onnx_path=str(onnx_path.absolute()),
        config_path=config_path,
    )


def delete_voice_model(name: str) -> bool:
    ensure_voice_dir()
    onnx = VOICE_MODELS_DIR / f"{name}.onnx"
    cfg = VOICE_MODELS_DIR / f"{name}.onnx.json"
    deleted = False
    if onnx.exists():
        onnx.unlink()
        deleted = True
    if cfg.exists():
        cfg.unlink()
        deleted = True
    return deleted


def select_voice_for_account(account_id: int, *, voice_name: str = "") -> Optional[VoiceModel]:
    """Резолвит voice-model для аккаунта.

    Параметр ``voice_name`` приходит из per-account settings;
    если пустой — возвращаем None (TTS использует default piper-voice).
    """
    if not voice_name:
        return None
    return find_voice_model(voice_name)


def piper_command_for_model(text: str, vm: VoiceModel, out_wav: str) -> list[str]:
    """Возвращает argv для запуска piper с пользовательской моделью.

    Запуск идёт через subprocess в caller-е, мы только формируем команду.
    """
    cmd = ["piper", "--model", vm.onnx_path, "--output_file", out_wav]
    if vm.config_path:
        cmd += ["--config", vm.config_path]
    return cmd


def write_setup_guide(target_path: str = "app/voice_clone_setup.md") -> str:
    """Создаёт markdown-инструкцию по тренировке голоса (если её нет)."""
    p = Path(target_path)
    if p.exists():
        return str(p.absolute())
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_GUIDE_MD, encoding="utf-8")
    return str(p.absolute())


_GUIDE_MD = """# Piper Voice Cloning — Setup Guide

## Кратко

Piper умеет fine-tune'иться на 5-10 минут датасета. Это **не делается в run-time бота** (нужен GPU + датасет + 1-3 часа тренировки). Юзер делает это локально и заливает готовый `.onnx` + `.onnx.json` в `data/voice_models/`.

## Шаги

### 1. Собери датасет голоса (5-10 минут)

WAV-файлы 22050 Hz, mono, без фоновой музыки. Каждый файл с транскриптом.

```
data/raw_voice/sample_001.wav
data/raw_voice/sample_001.txt   # текст этого WAV
data/raw_voice/sample_002.wav
data/raw_voice/sample_002.txt
...
```

### 2. Установи piper-train

```bash
pip install piper-train
```

### 3. Подготовь датасет

```bash
python -m piper_train.preprocess \\
  --language ru --input-dir data/raw_voice \\
  --output-dir data/preprocessed_voice \\
  --dataset-format ljspeech \\
  --sample-rate 22050 \\
  --single-speaker
```

### 4. Тренировка (нужен NVidia GPU)

```bash
python -m piper_train \\
  --dataset-dir data/preprocessed_voice \\
  --max_epochs 6000 \\
  --batch-size 32 \\
  --checkpoint-epochs 1000 \\
  --quality medium
```

При батч-сайзе 32 на RTX 3060 — около 2-3 часов до 6000 epoch.

### 5. Экспорт в .onnx

```bash
python -m piper_train.export_onnx \\
  data/preprocessed_voice/lightning_logs/version_0/checkpoints/epoch=5999-step=N.ckpt \\
  data/voice_models/my_voice.onnx

cp data/preprocessed_voice/config.json data/voice_models/my_voice.onnx.json
```

### 6. Загрузи в бота

Положи `my_voice.onnx` + `my_voice.onnx.json` в `data/voice_models/`.
Бот подхватит автоматом — выбери модель в UI на вкладке «Аккаунты → ⚙ → 🎤 Voice cloning».

## CPU вариант

Если GPU нет — Piper всё равно умеет inference на CPU (тренировку на CPU не делай — это месяцы). Используй готовые публичные модели:

- https://huggingface.co/rhasspy/piper-voices
- https://github.com/rhasspy/piper/blob/master/VOICES.md

Скачай `.onnx + .onnx.json` нужного голоса (русский: `ru_RU-irinia-medium.onnx`),
положи в `data/voice_models/`, выбери в UI.

## Безопасность

- Не используй voice голоса другого человека без согласия (твич может банить за impersonation).
- Стримерский voice clone — окей если стример сам разрешил.
"""
