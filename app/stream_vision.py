"""Stream Vision — что ИИ видит и слышит со стрима.

Каждые ``FRAME_INTERVAL`` секунд берёт кадр через ``streamlink`` + ``ffmpeg``,
прогоняет через AI-vision и эмитит событие ``stream_vision_result``.
Каждые ``AUDIO_INTERVAL`` секунд берёт кусок звука, прогоняет через Whisper и
эмитит ``stream_audio_result``.

Расширенные возможности (v10.2):
  - **Vision→Chat**: если AI описал что-то «яркое» (киллстрик, смешной момент),
    бот автоматически комментирует это в чат (через ``chat_cb``).
  - **Perceptual hash**: если новый кадр визуально идентичен предыдущему —
    пропускаем вызов AI (экономия квоты).
  - **Smart-полинг**: адаптивная частота захвата кадров: при бурной активности
    чата (много сообщений/мин) — кадры берутся чаще; при тишине — реже.

Включается per-channel: в карточке канала есть тоггл «👁️/🔊 Stream Vision».
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shlex
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable, Awaitable

from PIL import Image

from app.diarization import diarize_segments, format_diarized_transcript
from app.vision_prompt import build_vision_prompt, strip_reasoning

logger = logging.getLogger(__name__)

LogCallback = Callable[[str, str, int, str], Awaitable[None]]
# chat_cb: async def(account_id, channel, text) -> bool
ChatCallback = Callable[[int, str, str], Awaitable[bool]]


# ──────────────────── perceptual hash ────────────────────

def _phash(img: Image.Image, hash_size: int = 8) -> int:
    """Простой average-hash.

    Уменьшаем до 8×8 gray, считаем средний пиксель, каждый пиксель → 1/0.
    Результат — 64-bit int. Отличие двух кадров — ``bin(h1 ^ h2).count('1')``.
    """
    small = img.resize((hash_size, hash_size), Image.Resampling.LANCZOS).convert("L")
    pixels = list(small.getdata())
    avg = sum(pixels) / len(pixels)
    bits = 0
    for p in pixels:
        bits = (bits << 1) | (1 if p >= avg else 0)
    return bits


def _hamming(h1: int, h2: int) -> int:
    return bin(h1 ^ h2).count("1")


# ──────────────────── chat activity tracker ────────────────────

class ChatActivityTracker:
    """Отслеживает темп чата (msg/min) по каналам.

    Используется для smart-полинга: при бурной активности бот берёт кадры чаще.
    Каллбэк ``on_chat_message(channel)`` вызывается из ``chat_analyzer.on_message``.
    """

    def __init__(self, window: int = 60) -> None:
        self._window = window  # секунд
        self._timestamps: dict[str, list[float]] = {}

    def on_message(self, channel: str) -> None:
        ch = channel.lower().lstrip("#")
        now = time.monotonic()
        lst = self._timestamps.setdefault(ch, [])
        lst.append(now)
        # Периодически чистим старые (каждые 50 сообщений).
        if len(lst) % 50 == 0:
            cutoff = now - self._window
            self._timestamps[ch] = [t for t in lst if t > cutoff]

    def msg_per_min(self, channel: str) -> float:
        ch = channel.lower().lstrip("#")
        lst = self._timestamps.get(ch, [])
        if not lst:
            return 0.0
        now = time.monotonic()
        cutoff = now - self._window
        recent = [t for t in lst if t > cutoff]
        self._timestamps[ch] = recent
        if not recent:
            return 0.0
        return len(recent) * (60.0 / self._window)


# Глобальный трекер (импортируется в chat_analyzer).
chat_activity = ChatActivityTracker()


# v10.4: глобальная ссылка на менеджер (чтобы chat_analyzer мог дотянуться до
# последнего vision-наблюдения, не создавая циклического импорта через server).
_manager_ref: "Optional[StreamVisionManager]" = None


def set_manager(m: "StreamVisionManager") -> None:
    global _manager_ref
    _manager_ref = m


def get_last_observation(account_id: int, channel: str, max_age_sec: int = 120) -> "Optional[dict]":
    """v10.4: Удобный module-level wrapper, вызываемый из chat_analyzer."""
    m = _manager_ref
    if m is None:
        return None
    return m.get_last_observation(account_id, channel, max_age_sec=max_age_sec)


def add_streamer_line(account_id: int, channel: str, text: str, *, max_keep: int = 8) -> None:
    m = _manager_ref
    if m is not None:
        m.add_streamer_line(account_id, channel, text, max_keep=max_keep)


def get_recent_streamer_lines(
    account_id: int, channel: str, *, limit: int = 5, max_age_sec: int = 600
) -> "list[dict]":
    m = _manager_ref
    if m is None:
        return []
    return m.get_recent_streamer_lines(
        account_id, channel, limit=limit, max_age_sec=max_age_sec,
    )


# ──────────────────── config ────────────────────

# v10.4.2: папка для сохранённых кадров, раздаётся в server.py по пути /frames/.
# Глобальный константный путь — чтобы URL-ы в UI были стабильны.
# Дефолт — относительно корня проекта (переносимо между машинами и ОС).
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRAMES_DIR = Path(os.getenv("FRAMES_DIR", str(_PROJECT_ROOT / "data" / "stream_vision_frames")))


@dataclass
class StreamVisionConfig:
    # v10.4: дефолты сдвинуты в near-realtime сторону.
    frame_interval: int = 15         # секунд между кадрами (базовый)
    frame_interval_min: int = 3      # минимум при бурном чате (было 10)
    frame_interval_max: int = 45     # максимум при тишине
    audio_interval: int = 30         # было 60 — теперь 30с окна для near-realtime
    quality: str = "360p"            # 360p быстрее качается, AI-vision всё равно понимает
    whisper_language: str = "ru"
    whisper_model_size: str = "base"
    phash_threshold: int = 6         # макс. hamming distance — «одинаковые» кадры
    vision_chat_enabled: bool = True  # отправлять ли в чат описание ярких моментов
    # Порог «яркости» (длина описания, слово-ключи). Простая эвристика.
    vision_chat_min_words: int = 5   # минимум слов в описании чтобы считать «ярким»
    # v10.4: пайплайн (захват N+1 параллельно с AI-обработкой N). Снижает
    # эффективную задержку «событие → описание» примерно на длительность AI-запроса.
    pipelining: bool = True
    # v10.4.2: сохранять каждый скачанный кадр на диск + ссылку в UI/лог.
    save_frames: bool = True
    # Сколько последних кадров хранить per-channel (старше удаляются).
    max_saved_frames: int = 50
    # v10.4.2: авто-fallback на best/worst когда выбранное качество не найдено.
    # Нужно для каналов без transcoding (у них только Source + audio_only).
    quality_fallback: bool = True
    # v10.4.3: источник видео/аудио для захвата.
    #   "twitch" — streamlink + ffmpeg, как раньше (есть задержка HLS ~3-7 сек).
    #   "custom" — прямой вызов ffmpeg с пользовательскими input-флагами
    #              (см. stream_video_input / stream_audio_input). Подходит для
    #              OBS Virtual Camera, дисплея (x11grab/gdigrab), v4l2, dshow,
    #              avfoundation, NDI, локального файла или RTMP-сервера, на
    #              который OBS пушит. Задержка обычно 0..0.5 сек.
    stream_source: str = "twitch"
    # ffmpeg input args для video (без output options). Используется когда
    # stream_source != "twitch". Пример (Linux + OBS Virtual Camera):
    #   "-f v4l2 -i /dev/video0"
    # Windows + OBS Virtual Camera:
    #   '-f dshow -i video="OBS Virtual Camera"'
    # macOS + OBS Virtual Camera:
    #   "-f avfoundation -framerate 30 -i 'OBS Virtual Camera'"
    # X11 screen capture (Linux):
    #   "-f x11grab -framerate 15 -i :0.0"
    # Локальный RTMP (если OBS пушит на nginx-rtmp):
    #   "-i rtmp://127.0.0.1/live/stream"
    stream_video_input: str = ""
    # ffmpeg input args для audio. Опционально (для transcribe). Пример (Linux + Pulse):
    #   "-f pulse -i default"
    # Windows + dshow:
    #   '-f dshow -i audio="Stereo Mix"'
    stream_audio_input: str = ""
    # v10.4.4: vision-cache — пропускаем обработку кадра, если описание
    # семантически совпадает с предыдущим (Jaccard ≥ threshold). Экономит
    # повторные комментарии бота на однотипные сцены.
    vision_cache_enabled: bool = False
    vision_cache_similarity_threshold: float = 0.85
    # v10.4.8: вырезать chain-of-thought из ответа vision-модели
    # (для reasoning-моделей типа nemotron-reasoning, deepseek-r1 и т.п.,
    # которые сливают «We need to..., Let's parse... So answer: ...» в финал).
    vision_strip_reasoning: bool = True
    # v10.4.8: подмешивать в vision-промпт инфу из Helix (категория/название
    # стрима). Помогает модели сразу опознать игру и не выдумывать.
    vision_include_stream_info: bool = True
    # v10.4.8: стиль дефолтного vision-промпта.
    #   "basic"    — короткий промпт (как до v10.4.8).
    #   "detailed" — просит описывать PiP/split-screen/реакцию стримера отдельно.
    vision_prompt_style: str = "detailed"
    # v10.4.8: полная перебивка vision-промпта. Если задан — заменяет
    # выбранный стиль; channel_info всё равно подмешивается префиксом.
    vision_prompt_override: str = ""
    # v10.4.8: диаризация (различать голоса в одном смешанном аудиопотоке).
    #   "off"       — выкл, прежнее поведение (один сплошной текст).
    #   "heuristic" — лёгкая эвристика на acoustic-fingerprint'ах сегментов
    #                 whisper, без HF-токена и тяжёлых моделей. Помечает
    #                 фразы как [Голос 1], [Голос 2]... Капается на 3 спикеров.
    #   "whisperx"  — настоящая диаризация через WhisperX+pyannote.audio.
    #                 Требует доустановки пакета и HF-токена (HUGGINGFACE_TOKEN);
    #                 если пакет не установлен — деградирует до heuristic.
    audio_diarization_mode: str = "off"
    audio_diarization_max_speakers: int = 3

    @classmethod
    def from_env(cls) -> "StreamVisionConfig":
        return cls(
            frame_interval=int(os.getenv("FRAME_INTERVAL", "15") or 15),
            frame_interval_min=int(os.getenv("FRAME_INTERVAL_MIN", "3") or 3),
            frame_interval_max=int(os.getenv("FRAME_INTERVAL_MAX", "45") or 45),
            audio_interval=int(os.getenv("AUDIO_INTERVAL", "30") or 30),
            quality=os.getenv("STREAM_QUALITY", "360p") or "360p",
            whisper_language=os.getenv("WHISPER_LANGUAGE", "ru") or "ru",
            whisper_model_size=os.getenv("WHISPER_MODEL_SIZE", "base") or "base",
            phash_threshold=int(os.getenv("PHASH_THRESHOLD", "6") or 6),
            vision_chat_enabled=os.getenv("VISION_CHAT_ENABLED", "1") not in ("0", "false", "no"),
            vision_chat_min_words=int(os.getenv("VISION_CHAT_MIN_WORDS", "5") or 5),
            pipelining=os.getenv("VISION_PIPELINING", "1") not in ("0", "false", "no"),
            save_frames=os.getenv("SAVE_FRAMES", "1") not in ("0", "false", "no"),
            max_saved_frames=int(os.getenv("MAX_SAVED_FRAMES", "50") or 50),
            quality_fallback=os.getenv("QUALITY_FALLBACK", "1") not in ("0", "false", "no"),
            stream_source=(os.getenv("STREAM_SOURCE", "twitch") or "twitch").lower().strip(),
            stream_video_input=os.getenv("STREAM_VIDEO_INPUT", "") or "",
            stream_audio_input=os.getenv("STREAM_AUDIO_INPUT", "") or "",
            vision_cache_enabled=os.getenv("VISION_CACHE_ENABLED", "0") not in ("0", "false", "no"),
            vision_cache_similarity_threshold=float(os.getenv("VISION_CACHE_SIMILARITY", "0.85") or 0.85),
            vision_strip_reasoning=os.getenv("VISION_STRIP_REASONING", "1") not in ("0", "false", "no"),
            vision_include_stream_info=os.getenv("VISION_INCLUDE_STREAM_INFO", "1") not in ("0", "false", "no"),
            vision_prompt_style=(os.getenv("VISION_PROMPT_STYLE", "detailed") or "detailed").lower().strip(),
            vision_prompt_override=os.getenv("VISION_PROMPT_OVERRIDE", "") or "",
            audio_diarization_mode=(os.getenv("AUDIO_DIARIZATION_MODE", "off") or "off").lower().strip(),
            audio_diarization_max_speakers=int(os.getenv("AUDIO_DIARIZATION_MAX_SPEAKERS", "3") or 3),
        )


def _is_cli_available(name: str) -> bool:
    return shutil.which(name) is not None


# v10.4.8: автоустановка streamlink через pip когда его нет в PATH.
# Кэшируем shell-команду для запуска streamlink (либо "streamlink", либо
# "python -m streamlink_cli" если CLI установлен, но не попал в PATH).
_streamlink_invocation: Optional[str] = None
_streamlink_autoinstall_done: bool = False
_streamlink_last_error: str = ""
_streamlink_install_lock: Optional[asyncio.Lock] = None


def _quote_executable(path: str) -> str:
    """Cross-platform shell-quote для пути к python.exe / python."""
    if os.name == "nt":
        # cmd.exe: оборачиваем в двойные кавычки, экранируем " как ""
        return '"' + path.replace('"', '""') + '"'
    return shlex.quote(path)


def _can_import_streamlink_cli() -> bool:
    """Возвращает True если ``streamlink_cli`` можно импортировать."""
    try:
        import importlib.util
        spec = importlib.util.find_spec("streamlink_cli")
        return spec is not None
    except Exception:  # noqa: BLE001
        return False


def _get_streamlink_invocation() -> Optional[str]:
    """Возвращает shell-команду для запуска streamlink, или None.

    Сначала проверяет ``streamlink`` в PATH, затем пытается импортировать
    ``streamlink_cli`` — это работает когда pip install прошёл, но venv/bin
    (или ``~/.local/bin``) не на PATH. Результат кэшируется.
    """
    global _streamlink_invocation
    if _streamlink_invocation:
        return _streamlink_invocation
    if shutil.which("streamlink"):
        _streamlink_invocation = "streamlink"
        return _streamlink_invocation
    if _can_import_streamlink_cli():
        _streamlink_invocation = f"{_quote_executable(sys.executable)} -m streamlink_cli"
        return _streamlink_invocation
    return None


def _reset_streamlink_cache() -> None:
    """Сбросить кэш — для тестов и для случая когда пользователь поставил вручную."""
    global _streamlink_invocation, _streamlink_autoinstall_done, _streamlink_last_error
    _streamlink_invocation = None
    _streamlink_autoinstall_done = False
    _streamlink_last_error = ""


async def _run_pip_install(args: list[str]) -> tuple[int, str]:
    """Запускает ``python -m pip install ... streamlink``, возвращает (rc, output)."""
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", *args, "streamlink"]
    logger.info("streamlink autoinstall: %s", " ".join(cmd))
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
    except Exception as exc:  # noqa: BLE001
        return -1, f"subprocess error: {exc}"
    text = (out or b"").decode(errors="replace").strip()
    return proc.returncode, text


async def _ensure_streamlink_available() -> tuple[bool, str]:
    """Гарантирует наличие streamlink CLI (или модуля); при отсутствии — pip install.

    Возвращает ``(available, error_message)``. Если уже один раз pытались и не
    вышло — возвращает кэшированную ошибку с полным выводом pip, чтобы
    пользователь видел реальную причину.

    Пробует три стратегии установки по очереди:
      1. ``pip install streamlink`` — штатная установка (в venv этого достаточно).
      2. ``pip install --user streamlink`` — если PEP 668 / externally-managed.
      3. ``pip install --break-system-packages streamlink`` — последний шанс.
    """
    global _streamlink_install_lock, _streamlink_autoinstall_done, _streamlink_last_error
    if _get_streamlink_invocation() is not None:
        return True, ""
    if _streamlink_install_lock is None:
        _streamlink_install_lock = asyncio.Lock()
    async with _streamlink_install_lock:
        if _get_streamlink_invocation() is not None:
            return True, ""
        if _streamlink_autoinstall_done:
            return False, _streamlink_last_error or (
                "streamlink не установлен — автоустановка ранее не удалась, "
                "поставь вручную: pip install streamlink"
            )
        _streamlink_autoinstall_done = True

        strategies: list[tuple[list[str], str]] = [
            ([], "pip install streamlink"),
            (["--user"], "pip install --user streamlink"),
            (["--break-system-packages"], "pip install --break-system-packages streamlink"),
        ]
        errors: list[str] = []
        for args, label in strategies:
            rc, output = await _run_pip_install(args)
            if rc == 0:
                # Сбрасываем кэш invocation чтобы перепроверить PATH/импорт
                global _streamlink_invocation
                _streamlink_invocation = None
                if _get_streamlink_invocation() is not None:
                    logger.info("streamlink установлен через '%s'.", label)
                    return True, ""
                # pip говорит ОК, но ни в PATH ни как модуль — странно, но идём дальше
                errors.append(
                    f"{label}: rc=0, но streamlink не виден ни в PATH, ни как модуль streamlink_cli"
                )
                continue
            # rc != 0
            tail = output.strip()[-400:] if output else ""
            errors.append(f"{label}: rc={rc} {tail}".strip())
            # Если ошибка не похожа на PEP 668 / externally-managed — можно сразу прерваться,
            # но дешевле просто продолжить до конца списка стратегий.
        _streamlink_last_error = (
            "streamlink: автоустановка не удалась. Подробности:\n  "
            + "\n  ".join(errors)
            + "\nПоставь вручную: pip install streamlink"
        )
        return False, _streamlink_last_error


# Ключевые слова «яркий момент» (lower). Наличие любого → бот точно комментирует.
_EXCITING_KEYWORDS = {
    "убил", "килл", "kill", "killed", "фраг", "взорвал", "clutch", "клатч",
    "ace", "эйс", "win", "победа", "died", "умер", "рейд", "raid",
    "выиграл", "проиграл", "funny", "смешно", "упал", "взрыв",
    "headshot", "хедшот", "gg", "вау", "wow", "epic", "эпик", "спасение",
    "пентакилл", "pentakill", "triple", "трипл", "quad", "квадра",
    "goal", "гол", "сейв", "save",
}


class StreamVisionManager:
    """Запускает фоновые задачи захвата кадра/аудио для каждого канала."""

    def __init__(
        self,
        ai_service,
        log_cb: Optional[LogCallback] = None,
        chat_cb: Optional[ChatCallback] = None,
        cfg: Optional[StreamVisionConfig] = None,
        token_provider: Optional[Callable[[int], Optional[str]]] = None,
    ) -> None:
        self.ai = ai_service
        self.log_cb = log_cb
        self.chat_cb = chat_cb  # async def(account_id, channel, text) -> bool
        # v10.4.8: token_provider — функция (account_id) -> str | None для Helix-запросов
        # (категория/название стрима). Если не задан, vision_include_stream_info
        # будет no-op. Сетится через ``set_token_provider`` (server.py привязывает
        # к chat_analyzer._account_token).
        self.token_provider: Optional[Callable[[int], Optional[str]]] = token_provider
        # v10.4.3: cfg инжектится для тестов; production вызов передаёт None,
        # тогда читаем из env (старое поведение).
        self.cfg = cfg if cfg is not None else StreamVisionConfig.from_env()
        self._tasks: dict[tuple[int, str], asyncio.Task] = {}
        self._whisper_model = None
        self._whisper_lock = asyncio.Lock()
        # Perceptual hash предыдущего кадра per-channel.
        self._prev_phash: dict[tuple[int, str], int] = {}
        # v10.4: pipelining — фоновая задача обработки, чтобы цикл не блокировался AI-вызовом.
        self._inflight: dict[tuple[int, str], asyncio.Task] = {}
        # DEF-01a: аудио-захват — отдельная задача per (account, channel): Whisper на CPU
        # идёт 45–90 с, и раньше `await _capture_audio` в цикле стопорил кадры на это время.
        self._audio_inflight: dict[tuple[int, str], asyncio.Task] = {}
        # v10.4: последнее наблюдение (vision-описание + транскрипция аудио) per (account, channel).
        # Используется chat_analyzer для контекста ответа («бот видит стрим»).
        self._last_observation: dict[tuple[int, str], dict] = {}
        # v10.4.4: последнее описание для vision-cache (semantic-diff).
        self._last_description_txt: dict[tuple[int, str], str] = {}
        # v10.4.5: VAD silence watcher per (account, channel). Создаются lazily.
        from app.vad_silence import SilenceWatcher  # local import to avoid cycle
        self._silence_watchers: dict[tuple[int, str], SilenceWatcher] = {}
        # v16 BRAIN_PLAN §2: последние N реплик стримера per (account, channel) — deque[dict].
        from collections import deque
        self._streamer_lines: dict[tuple[int, str], deque] = {}

    # ---------- public ----------

    def is_running(self, account_id: int, channel: str) -> bool:
        key = (account_id, channel.lower().lstrip("#"))
        task = self._tasks.get(key)
        return bool(task and not task.done())

    def _attention_enabled(self, account_id: int, source: str) -> bool:
        """AI-BUDGET AB-3: гейт источника по переключателю внимания бота.

        Читает analyzer-настройки аккаунта (attention_vision / attention_hearing).
        Ленивый импорт server→chat_analyzer: если панели нет (тесты/standalone),
        источник считается включённым — поведение как до AI-BUDGET.
        """
        try:
            from app.server import chat_analyzer
            return bool(chat_analyzer.get_settings(int(account_id)).get(f"attention_{source}", True))
        except Exception:  # noqa: BLE001
            return True

    async def start(self, account_id: int, channel: str) -> bool:
        ch = channel.lower().lstrip("#")
        key = (account_id, ch)
        if key in self._tasks and not self._tasks[key].done():
            return True
        # v10.4.8: если streamlink нет в PATH — пробуем автоустановку через pip.
        ok, err_msg = await _ensure_streamlink_available()
        if not ok:
            await self._log("stream_error", err_msg or "streamlink не установлен", account_id, ch)
            return False
        if not _is_cli_available("ffmpeg"):
            await self._log("stream_error", "ffmpeg не установлен — apt install ffmpeg", account_id, ch)
            return False
        task = asyncio.create_task(self._loop(account_id, ch))
        self._tasks[key] = task
        await self._log(
            "stream_status",
            f"👁️🔊 Захват стрима #{ch} запущен "
            f"(кадр/{self.cfg.frame_interval}с base, аудио/{self.cfg.audio_interval}с, "
            f"phash≤{self.cfg.phash_threshold}, vision→chat={'ON' if self.cfg.vision_chat_enabled else 'OFF'})",
            account_id, ch,
        )
        return True

    async def stop(self, account_id: int, channel: str) -> None:
        ch = channel.lower().lstrip("#")
        key = (account_id, ch)
        task = self._tasks.pop(key, None)
        if task and not task.done():
            task.cancel()
            with contextlib.suppress(BaseException):
                await task
        self._prev_phash.pop(key, None)
        # v10.4: дочистим in-flight AI-задачу и забудем последнее наблюдение для этого канала.
        inflight = self._inflight.pop(key, None)
        if inflight and not inflight.done():
            inflight.cancel()
            with contextlib.suppress(BaseException):
                await inflight
        # DEF-01a: дочистим аудио-задачу (Whisper мог быть в полёте на момент stop()).
        audio_task = self._audio_inflight.pop(key, None)
        if audio_task and not audio_task.done():
            audio_task.cancel()
            with contextlib.suppress(BaseException):
                await audio_task
        self._last_observation.pop(key, None)
        await self._log("stream_status", f"⏹ Захват стрима #{ch} остановлен", account_id, ch)

    async def stop_all(self) -> None:
        keys = list(self._tasks.keys())
        for account_id, ch in keys:
            await self.stop(account_id, ch)

    def update_config(self, cfg: StreamVisionConfig) -> None:
        self.cfg = cfg

    def set_token_provider(self, provider: Optional[Callable[[int], Optional[str]]]) -> None:
        """v10.4.8: установить callback для получения OAuth-токена по account_id.

        Используется для Helix-запросов (категория стрима / название) в
        vision-промпт. ``None`` отключает.
        """
        self.token_provider = provider

    async def _fetch_channel_info(self, account_id: int, channel: str) -> Optional[dict]:
        """v10.4.8: вернуть Helix-инфу о канале (title/game_name) или None.

        No-op если ``vision_include_stream_info=False`` или нет token_provider.
        Все ошибки сетки/Helix глушим — vision должен работать и без контекста.
        """
        if not self.cfg.vision_include_stream_info or self.token_provider is None:
            return None
        try:
            token = self.token_provider(account_id)
        except Exception:  # noqa: BLE001
            return None
        if not token:
            return None
        try:
            from app.twitch_helix import get_channel_info
            info = await get_channel_info(channel, token)
            if isinstance(info, dict) and info:
                return info
        except Exception as exc:  # noqa: BLE001
            logger.debug("Helix channel_info failed for #%s: %s", channel, exc)
        return None

    def get_last_observation(self, account_id: int, channel: str, max_age_sec: int = 120) -> Optional[dict]:
        """v10.4: вернуть последнее vision/audio-наблюдение, если оно "свежее".

        Возвращает ``{description, transcript, at}`` или None если ничего нет
        или возраст > ``max_age_sec``. ``at`` — unix timestamp.
        """
        ch = (channel or "").lower().lstrip("#")
        rec = self._last_observation.get((account_id, ch))
        if not rec:
            return None
        age = time.time() - float(rec.get("at") or 0)
        if age > max_age_sec:
            return None
        return dict(rec)

    # ---------- v16 BRAIN_PLAN §2: реплики стримера ----------

    def add_streamer_line(self, account_id: int, channel: str, text: str,
                          *, max_keep: int = 8) -> None:
        """Сохраняет фразу стримера (из transcript) в deque последних N."""
        if not text or not text.strip():
            return
        ch = (channel or "").lower().lstrip("#")
        dq = self._streamer_lines.get((account_id, ch))
        if dq is None:
            from collections import deque
            dq = deque(maxlen=max_keep)
            self._streamer_lines[(account_id, ch)] = dq
        dq.append({"text": text.strip()[:400], "at": time.time()})

    def get_recent_streamer_lines(
        self, account_id: int, channel: str, *, limit: int = 5, max_age_sec: int = 600
    ) -> list[dict]:
        """Возвращает последние N реплик стримера (не старше ``max_age_sec``)."""
        ch = (channel or "").lower().lstrip("#")
        dq = self._streamer_lines.get((account_id, ch))
        if not dq:
            return []
        now = time.time()
        out = []
        for item in list(dq)[-limit:]:
            if now - float(item.get("at") or 0) > max_age_sec:
                continue
            out.append(item)
        return out

    def _store_observation(self, account_id: int, channel: str, *, description: str = "", transcript: str = "", frame_url: Optional[str] = None) -> None:
        ch = (channel or "").lower().lstrip("#")
        rec = self._last_observation.get((account_id, ch)) or {}
        if description:
            rec["description"] = description
        if transcript:
            rec["transcript"] = transcript
            # v16 BRAIN_PLAN §2: каждый свежий transcript добавляем в deque
            # последних реплик стримера (для подмешивания в prompt).
            try:
                self.add_streamer_line(account_id, ch, transcript)
            except Exception:
                pass
        # v10.4.2: frame_url обновляется только если явно передали (включая «» и None
        # — None означает «не трогай», чтобы аудио-update не стирал картинку).
        if frame_url is not None:
            rec["frame_url"] = frame_url
        rec["at"] = time.time()
        self._last_observation[(account_id, ch)] = rec

    # ---------- smart polling ----------

    def _effective_frame_interval(self, channel: str) -> float:
        """Адаптивный интервал захвата кадров по активности чата.

        msg/min ≥ 30 → ``frame_interval_min`` (бурный чат, что-то яркое);
        msg/min == 0  → ``frame_interval_max`` (тихо);
        линейная интерполяция между ними.
        """
        mpm = chat_activity.msg_per_min(channel)
        lo, hi = self.cfg.frame_interval_min, self.cfg.frame_interval_max
        if mpm >= 30:
            return float(lo)
        if mpm <= 0:
            return float(hi)
        # Линейно: 0→hi, 30→lo.
        ratio = mpm / 30.0
        return hi - ratio * (hi - lo)

    # ---------- internals ----------

    async def _log(self, event: str, detail: str, account_id: int, channel: str) -> None:
        logger.info("[stream_vision:%s] %s %s", channel, event, detail)
        if self.log_cb:
            try:
                await self.log_cb(event, detail, account_id, channel)
            except Exception as exc:  # noqa: BLE001
                logger.warning("stream_vision log_cb failed: %s", exc)

    def _get_silence_watcher(self, account_id: int, channel: str):
        """v10.4.5: Lazy-create silence watcher per (account, channel)."""
        from app.vad_silence import SilenceWatcher

        ch = channel.lower().lstrip("#")
        key = (int(account_id), ch)
        w = self._silence_watchers.get(key)
        # настройки берём из chat_analyzer (per-account)
        threshold_sec = 300.0
        cooldown_sec = 600.0
        try:
            from app.server import chat_analyzer  # type: ignore

            s = chat_analyzer.get_settings(account_id)
            threshold_sec = float(s.get("vad_silence_threshold_sec", 300) or 300)
            cooldown_sec = float(s.get("vad_silence_cooldown_sec", 600) or 600)
        except Exception:
            pass
        if w is None:
            w = SilenceWatcher(threshold_sec=threshold_sec, cooldown_sec=cooldown_sec)
            self._silence_watchers[key] = w
        else:
            w.threshold_sec = threshold_sec
            w.cooldown_sec = cooldown_sec
        return w

    async def _feed_silence_watcher(self, account_id: int, channel: str, transcript: str) -> None:
        """v10.4.5: VAD — обновляем watcher и эмитим 'afk stream' в чат, если порог достигнут."""
        # быстрая проверка — выключено ли вообще
        try:
            from app.server import chat_analyzer  # type: ignore

            s = chat_analyzer.get_settings(account_id)
        except Exception:
            return
        if not s.get("vad_silence_enabled"):
            return
        w = self._get_silence_watcher(account_id, channel)
        from app.vad_silence import has_speech_in_segment, pick_afk_message

        if has_speech_in_segment({"text": transcript}):
            w.mark_speech()
            return
        if w.should_emit_afk():
            # подбираем сообщение
            raw_msgs = (s.get("vad_silence_custom_messages") or "").strip()
            custom = None
            if raw_msgs:
                custom = [line.strip() for line in raw_msgs.splitlines() if line.strip()]
            msg = pick_afk_message(custom)
            w.mark_emitted()
            await self._log(
                "vad_afk",
                f"Молчание {w.silence_for():.0f}s ≥ {w.threshold_sec:.0f}s → '{msg}'",
                account_id, channel,
            )
            if self.chat_cb:
                try:
                    await self.chat_cb(account_id, channel, msg)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("vad chat_cb error: %s", exc)

    async def _loop(self, account_id: int, channel: str) -> None:
        """Основной цикл захвата.

        Если ``pipelining=True`` — кадр и AI-обработка живут в отдельной задаче,
        пока цикл уже ждёт следующий кадр. Это сильно снижает задержку реакции
        при включённом near-realtime: пока AI 2-5с думает над кадром N, мы уже
        качаем кадр N+1 (если приходит время очередного захвата).

        DEF-01a: аудио-захват всегда живёт в собственной задаче — Whisper на CPU
        занимает 45–90 с и не должен стопорить кадры и тик цикла. Пока предыдущая
        аудио-задача в полёте, тик пропускается (back-pressure, задачи не копятся).
        """
        next_frame_at = 0.0
        next_audio_at = 0.0
        key = (account_id, channel)
        while True:
            try:
                now = asyncio.get_event_loop().time()
                if now >= next_frame_at:
                    inflight = self._inflight.get(key)
                    busy = inflight is not None and not inflight.done()
                    if self.cfg.pipelining and not busy:
                        # Запускаем фоновую задачу — цикл сам считает следующий момент.
                        self._inflight[key] = asyncio.create_task(
                            self._capture_frame(account_id, channel)
                        )
                    elif not self.cfg.pipelining:
                        await self._capture_frame(account_id, channel)
                    # Если pipelining=ON и предыдущая задача ещё in-flight — пропускаем
                    # этот тик и ждём следующего интервала. Это естественный back-pressure.
                    interval = self._effective_frame_interval(channel)
                    next_frame_at = asyncio.get_event_loop().time() + interval
                if now >= next_audio_at:
                    # DEF-01a: аудио — отдельная задача, Whisper не стопорит кадры.
                    # Back-pressure: пока предыдущее аудио в полёте (Whisper дольше
                    # audio_interval) — тик пропускаем, задачи не копятся.
                    audio_task = self._audio_inflight.get(key)
                    audio_busy = audio_task is not None and not audio_task.done()
                    if not audio_busy:
                        self._audio_inflight[key] = asyncio.create_task(
                            self._capture_audio(account_id, channel)
                        )
                    next_audio_at = asyncio.get_event_loop().time() + self.cfg.audio_interval
                sleep_for = max(0.5, min(next_frame_at, next_audio_at) - asyncio.get_event_loop().time())
                await asyncio.sleep(sleep_for)
            except asyncio.CancelledError:
                # При отмене — снимем in-flight тоже, чтобы не висел.
                inflight = self._inflight.pop(key, None)
                if inflight and not inflight.done():
                    inflight.cancel()
                    with contextlib.suppress(BaseException):
                        await inflight
                # DEF-01a: аудио-задачу дочищаем так же, как кадровую.
                audio_task = self._audio_inflight.pop(key, None)
                if audio_task and not audio_task.done():
                    audio_task.cancel()
                    with contextlib.suppress(BaseException):
                        await audio_task
                raise
            except Exception as exc:  # noqa: BLE001
                logger.exception("stream_vision loop error: %s", exc)
                await self._log("stream_error", f"Внутренняя ошибка цикла: {exc}", account_id, channel)
                await asyncio.sleep(10)

    # ----- vision -----

    async def _capture_frame(self, account_id: int, channel: str) -> None:
        # AI-BUDGET AB-3: «Стрим Vision» выключен — кадр не качаем и vision-модель
        # не дёргаем (0 платных запросов). Аудио-цикл продолжает работать отдельно.
        if not self._attention_enabled(account_id, "vision"):
            logger.debug("stream_vision: vision вимкнено (acc=%s #%s) — кадр пропущено", account_id, channel)
            return
        mpm = chat_activity.msg_per_min(channel)
        eff = self._effective_frame_interval(channel)
        await self._log(
            "stream_vision_start",
            f"📥 Кадр #{channel} (интервал {eff:.0f}с, чат {mpm:.0f} msg/min)...",
            account_id, channel,
        )
        try:
            img = await asyncio.wait_for(self._grab_frame(channel), timeout=45.0)
        except asyncio.TimeoutError:
            await self._log("stream_vision_error", "⏱ Таймаут захвата кадра", account_id, channel)
            return
        except Exception as exc:  # noqa: BLE001
            await self._log("stream_vision_error", f"Ошибка захвата кадра: {exc}", account_id, channel)
            return
        if img is None:
            await self._log("stream_vision_error", "Не удалось получить кадр (стрим оффлайн?)", account_id, channel)
            return

        # --- Perceptual hash: пропускаем «такой же» кадр ---
        key = (account_id, channel)
        cur_hash = _phash(img)
        prev_hash = self._prev_phash.get(key)
        if prev_hash is not None:
            dist = _hamming(cur_hash, prev_hash)
            if dist <= self.cfg.phash_threshold:
                await self._log(
                    "stream_vision_start",
                    f"🔄 Кадр почти идентичен предыдущему (hamming={dist}), пропускаю AI-запрос",
                    account_id, channel,
                )
                return
        self._prev_phash[key] = cur_hash

        # v10.4.2: сохраняем кадр на диск ДО AI-вызова — чтобы даже если AI упадёт,
        # картинка всё равно была доступна для разбора «что же бот увидел».
        frame_url = self._save_frame_to_disk(channel, img)

        # v10.4.8: контекст стрима из Helix (категория/название) — даём
        # модели подсказку «это RAW! Cup по CS», чтобы не выдумывала.
        channel_info = await self._fetch_channel_info(account_id, channel)
        prompt = build_vision_prompt(
            style=self.cfg.vision_prompt_style,
            override=self.cfg.vision_prompt_override,
            channel_info=channel_info,
            include_stream_info=self.cfg.vision_include_stream_info,
        )

        # --- AI Vision ---
        try:
            description = await self.ai.analyze_image(
                img,
                prompt=prompt,
                account_id=account_id,
                channel=channel,
            )
        except Exception as exc:  # noqa: BLE001
            await self._log("stream_vision_error", f"AI-vision не ответил: {exc}", account_id, channel)
            return
        if not description:
            await self._log("stream_vision_error", "AI-vision вернул пустой ответ", account_id, channel)
            return

        # v10.4.8: вырезаем chain-of-thought (reasoning-leak) — длинный
        # английский монолог «We need to..., Let's parse..., So answer: "..."».
        if self.cfg.vision_strip_reasoning:
            cleaned = strip_reasoning(description)
            if cleaned and cleaned != description:
                logger.info(
                    "[stream_vision:%s] стрипнул reasoning: %d → %d символов",
                    channel, len(description), len(cleaned),
                )
                description = cleaned

        # v10.4.4: vision-cache — если описание ~совпадает с предыдущим
        # (Jaccard ≥ threshold), не дублируем downstream-логику (не обновляем
        # observation, не комментируем в чат). Экономит шум и дубль-реакции.
        if self.cfg.vision_cache_enabled:
            last_desc = self._last_description_txt.get(key, "")
            if last_desc:
                try:
                    from app.anti_detection import compute_self_similarity
                    sim = compute_self_similarity(description, [last_desc])
                except Exception:
                    sim = 0.0
                if sim >= self.cfg.vision_cache_similarity_threshold:
                    await self._log(
                        "stream_vision_cached",
                        f"♻️ Описание ~совпадает с предыдущим (sim={sim:.2f}), пропускаю",
                        account_id, channel,
                    )
                    return
        self._last_description_txt[key] = description

        # v10.4.2: в текст лога вложен маркер «[🖼 <url>]» — UI вырежет его
        # и покажет миниатюру. Для бэка-среды/CLI это просто информативный хвост.
        if frame_url:
            await self._log(
                "stream_vision_result",
                f"👁️ ВИЖУ НА СТРИМЕ: {description} [🖼 {frame_url}]",
                account_id, channel,
            )
        else:
            await self._log("stream_vision_result", f"👁️ ВИЖУ НА СТРИМЕ: {description}", account_id, channel)

        # v10.4: запоминаем последнее наблюдение для chat_analyzer (источник «🎥 со стрима»).
        # v10.4.2: в наблюдение также кладём frame_url — панель «Что бот видит» покажет её.
        self._store_observation(account_id, channel, description=description, frame_url=frame_url)

        # --- Vision → Chat: если момент «яркий» — бот комментирует в чат ---
        if self.cfg.vision_chat_enabled and self.chat_cb:
            await self._maybe_comment_in_chat(account_id, channel, description)

    async def _maybe_comment_in_chat(self, account_id: int, channel: str, description: str) -> None:
        """Если описание содержит признаки яркого момента — шлём в чат."""
        words = description.split()
        if len(words) < self.cfg.vision_chat_min_words:
            return
        desc_lower = description.lower()
        is_exciting = any(kw in desc_lower for kw in _EXCITING_KEYWORDS)
        # Также считаем «ярким» если бурный чат (≥15 msg/min) — значит что-то происходит.
        mpm = chat_activity.msg_per_min(channel)
        if not is_exciting and mpm < 15:
            return
        # Генерируем короткий комментарий на основе описания.
        try:
            comment = await self.ai.generate_text(
                prompt=(
                    f"Ты — зритель в Twitch-чате канала #{channel}. "
                    f"На стриме только что произошло: «{description}». "
                    "Напиши ОДНУ короткую реакцию для чата (до 150 символов), "
                    "как живой зритель — с эмоцией, без клише. "
                    "Не объясняй что видишь — прокомментируй. Только текст реплики."
                ),
                system="Ты — обычный зритель. Пиши неформально, кратко, с эмоцией.",
                account_id=account_id,
                channel=channel,
                temperature=0.6,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("vision→chat generate failed: %s", exc)
            return
        if not comment or len(comment.strip()) < 3:
            return
        comment = comment.strip().strip('"').strip("'")
        if len(comment) > 200:
            comment = comment[:197] + "..."
        await self._log("stream_vision_chat", f"💬→чат: {comment}", account_id, channel)
        try:
            await self.chat_cb(account_id, channel, comment)
        except Exception as exc:  # noqa: BLE001
            logger.warning("vision→chat send failed: %s", exc)

    async def _grab_frame(self, channel: str) -> Optional[Image.Image]:
        # v10.4.3: если выбран custom-источник (OBS / экран / RTMP / файл) —
        # минуем streamlink и пайпим ffmpeg напрямую. Это снимает HLS-задержку
        # Twitch (~3-7 сек) — пользователь получает «живой» источник.
        if self.cfg.stream_source != "twitch" and self.cfg.stream_video_input.strip():
            return await self._grab_frame_custom(channel)
        # v10.4.2: если quality_fallback включён — в список добавляем best,worst.
        # streamlink работает с csv: «360p,best,worst» — возьмёт первое найденное,
        # что лечит rc=183 на каналах без transcoding.
        if self.cfg.quality_fallback:
            quality_arg = f"{self.cfg.quality},best,worst"
        else:
            quality_arg = self.cfg.quality
        with tempfile.TemporaryDirectory(prefix="stream_vision_") as tmpdir:
            out = Path(tmpdir) / "frame.jpg"
            url = f"https://twitch.tv/{channel}"
            # v10.4.8: streamlink_inv может быть "streamlink" или
            # "python -m streamlink_cli" (если CLI не на PATH).
            streamlink_inv = _get_streamlink_invocation() or "streamlink"
            cmd = (
                f"{streamlink_inv} --stdout --twitch-disable-ads {url!s} {quality_arg} "
                f"| ffmpeg -loglevel error -y -i pipe:0 -frames:v 1 -q:v 3 {out.as_posix()!s}"
            )
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                msg = (stderr or b"").decode(errors="replace").strip()[-200:]
                if msg:
                    logger.warning("[stream_vision:%s] streamlink/ffmpeg rc=%s: %s", channel, proc.returncode, msg)
                return None
            if not out.exists() or out.stat().st_size == 0:
                return None
            try:
                return Image.open(out).convert("RGB")
            except Exception as exc:  # noqa: BLE001
                logger.warning("[stream_vision:%s] PIL open failed: %s", channel, exc)
                return None

    async def _grab_frame_custom(self, channel: str) -> Optional[Image.Image]:
        """v10.4.3: захват кадра напрямую через ffmpeg, без streamlink.

        Использует ``stream_video_input`` из конфига как INPUT-флаги. Берёт
        один кадр и сохраняет в jpeg. Для OBS Virtual Camera, дисплея,
        локального RTMP, NDI и т.д. — задержка ~0.
        """
        with tempfile.TemporaryDirectory(prefix="stream_vision_obs_") as tmpdir:
            out = Path(tmpdir) / "frame.jpg"
            cmd = (
                f"ffmpeg -loglevel error -y "
                f"{self.cfg.stream_video_input} "
                f"-frames:v 1 -q:v 3 {out.as_posix()!s}"
            )
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                msg = (stderr or b"").decode(errors="replace").strip()[-200:]
                if msg:
                    logger.warning(
                        "[stream_vision:%s] custom ffmpeg rc=%s: %s",
                        channel, proc.returncode, msg,
                    )
                return None
            if not out.exists() or out.stat().st_size == 0:
                return None
            try:
                return Image.open(out).convert("RGB")
            except Exception as exc:  # noqa: BLE001
                logger.warning("[stream_vision:%s] custom PIL open failed: %s", channel, exc)
                return None

    # v10.4.2: сохраняем кадр на диск + чистим старые.
    def _save_frame_to_disk(self, channel: str, img: Image.Image) -> Optional[str]:
        """Сохраняет ``img`` в ``data/stream_vision_frames/<channel>/<unix_ms>.jpg``.

        Возвращает относительный URL-путь вида ``/frames/<channel>/<file>``,
        который можно вставить в ``<img src=...>`` прямо в панель.

        При ``save_frames=False`` возвращает None.
        """
        if not self.cfg.save_frames:
            return None
        try:
            ch = (channel or "").lower().lstrip("#") or "unknown"
            ch_dir = FRAMES_DIR / ch
            ch_dir.mkdir(parents=True, exist_ok=True)
            ts_ms = int(time.time() * 1000)
            fname = f"{ts_ms}.jpg"
            fpath = ch_dir / fname
            # Сжимаем до ~85 quality — баланс размера и читаемости для человека.
            img.save(fpath, "JPEG", quality=85, optimize=True)
            self._cleanup_old_frames(ch_dir)
            # /frames/ — статика из server.py.
            return f"/frames/{ch}/{fname}"
        except Exception as exc:  # noqa: BLE001
            logger.warning("[stream_vision:%s] save frame failed: %s", channel, exc)
            return None

    def _cleanup_old_frames(self, ch_dir: Path) -> None:
        """Оставляем последние ``max_saved_frames`` кадров, старше удаляем.

        Сортируем по mtime — имена файлов и так unix-ms, но mtime надёжнее.
        """
        keep = max(1, int(self.cfg.max_saved_frames))
        try:
            files = sorted(
                (p for p in ch_dir.glob("*.jpg") if p.is_file()),
                key=lambda p: p.stat().st_mtime,
            )
            for old in files[:-keep]:
                with contextlib.suppress(OSError):
                    old.unlink()
        except OSError as exc:
            logger.debug("cleanup_old_frames failed: %s", exc)

    # ----- audio -----

    async def _capture_audio(self, account_id: int, channel: str) -> None:
        # AI-BUDGET AB-3: «Стрим слух» выключен — аудио не захватываем и
        # транскрипт не строим (наблюдение «что бот слышит» не обновляется).
        if not self._attention_enabled(account_id, "hearing"):
            logger.debug("stream_vision: hearing вимкнено (acc=%s #%s) — аудіо пропущено", account_id, channel)
            return
        await self._log("stream_audio_start", f"🎧 Слушаю стрим #{channel} ({self.cfg.audio_interval}с)...", account_id, channel)
        try:
            wav_path = await asyncio.wait_for(
                self._grab_audio(channel, duration=self.cfg.audio_interval),
                timeout=self.cfg.audio_interval + 30,
            )
        except asyncio.TimeoutError:
            await self._log("stream_audio_error", "⏱ Таймаут захвата аудио", account_id, channel)
            return
        except Exception as exc:  # noqa: BLE001
            await self._log("stream_audio_error", f"Ошибка захвата аудио: {exc}", account_id, channel)
            return
        if not wav_path:
            await self._log("stream_audio_error", "Не удалось получить аудио (стрим оффлайн?)", account_id, channel)
            return

        try:
            text, whisper_result = await self._transcribe(wav_path)
        except Exception as exc:  # noqa: BLE001
            await self._log("stream_audio_error", f"Whisper упал: {exc}", account_id, channel)
            with contextlib.suppress(FileNotFoundError):
                os.unlink(wav_path)
            return

        diarized_text = ""
        if text and self.cfg.audio_diarization_mode != "off":
            try:
                diarized_text = await asyncio.to_thread(
                    self._diarize_safe, wav_path, whisper_result,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("diarize error: %s", exc)
        if text:
            try:
                from app.voice_control import handle_stream_transcript
                await handle_stream_transcript(account_id, channel, text, wav_path)
            except Exception as exc:  # noqa: BLE001
                logger.debug("owner voice control error: %s", exc)
        # WAV больше не нужен — чистим после диаризации.
        with contextlib.suppress(FileNotFoundError):
            os.unlink(wav_path)

        if text:
            log_text = diarized_text or text
            await self._log("stream_audio_result", f"🔊 СЛЫШУ НА СТРИМЕ: {log_text}", account_id, channel)
            # v10.4: транскрипция тоже сохраняется — chat_analyzer может её использовать как контекст.
            self._store_observation(account_id, channel, transcript=log_text)
        else:
            await self._log("stream_audio_error", "Whisper не распознал речь (тишина / музыка?)", account_id, channel)

        # v10.4.5: VAD silence detection — кормим watcher и эмитим "afk stream" по таймауту.
        try:
            await self._feed_silence_watcher(account_id, channel, text or "")
        except Exception as exc:  # noqa: BLE001
            logger.debug("vad watcher error: %s", exc)

    async def _grab_audio(self, channel: str, duration: int) -> Optional[str]:
        fd, out_path = tempfile.mkstemp(prefix="stream_audio_", suffix=".wav")
        os.close(fd)
        # v10.4.3: custom-источник (OBS/PulseAudio/dshow/AVFoundation/etc).
        # Если задан stream_audio_input — берём звук с него (нулевая задержка).
        if self.cfg.stream_source != "twitch" and self.cfg.stream_audio_input.strip():
            cmd = (
                f"ffmpeg -loglevel error -y "
                f"{self.cfg.stream_audio_input} "
                f"-t {int(duration)} -ar 16000 -ac 1 -vn -acodec pcm_s16le {out_path!s}"
            )
        else:
            url = f"https://twitch.tv/{channel}"
            # v10.4.2: всегда пробуем audio_only -> worst -> заданный quality -> best.
            # У каналов без transcoding только audio_only/best, а у партнёров наоборот
            # — один из вариантов точно сработает.
            if self.cfg.quality_fallback:
                quality_arg = f"audio_only,worst,{self.cfg.quality},best"
            else:
                quality_arg = f"audio_only,worst,{self.cfg.quality}"
            streamlink_inv = _get_streamlink_invocation() or "streamlink"
            cmd = (
                f"{streamlink_inv} --stdout --twitch-disable-ads {url!s} {quality_arg} "
                f"| ffmpeg -loglevel error -y -i pipe:0 -t {int(duration)} "
                f"-ar 16000 -ac 1 -vn -acodec pcm_s16le {out_path!s}"
            )
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await proc.communicate()
        if proc.returncode != 0 or not Path(out_path).exists() or Path(out_path).stat().st_size < 1024:
            msg = (stderr or b"").decode(errors="replace").strip()[-200:]
            if msg:
                logger.warning("[stream_vision:%s] audio capture rc=%s: %s", channel, proc.returncode, msg)
            with contextlib.suppress(FileNotFoundError):
                os.unlink(out_path)
            return None
        return out_path

    async def _transcribe(self, wav_path: str) -> tuple[str, dict]:
        """Возвращает (text, full_whisper_result).

        full_whisper_result содержит ``segments`` — нужны для диаризации.
        """
        async with self._whisper_lock:
            if self._whisper_model is None:
                self._whisper_model = await asyncio.to_thread(self._load_whisper)
        if self._whisper_model is None:
            return "", {}

        def _run():
            res = self._whisper_model.transcribe(
                wav_path,
                language=self.cfg.whisper_language or None,
                fp16=False,
            )
            text = (res.get("text") or "").strip()
            return text, dict(res) if isinstance(res, dict) else {}

        return await asyncio.to_thread(_run)

    def _diarize_safe(self, wav_path: str, whisper_result: dict) -> str:
        """Запускает диаризацию синхронно, ловит все исключения.

        Возвращает пустую строку при любой ошибке — caller использует
        обычный whisper-text как fallback.

        Режимы:
          * ``off`` — диаризация выключена.
          * ``heuristic`` — лёгкая эвристика по акустическим отпечаткам
            (без зависимостей, см. ``app.diarization``).
          * ``whisperx`` — настоящая диаризация через WhisperX+pyannote.audio.
            Требует ``pip install whisperx`` + HuggingFace токен. Если хотя бы
            одно условие не выполнено — автоматический fallback на heuristic.
        """
        mode = (self.cfg.audio_diarization_mode or "off").lower()
        if mode == "off":
            return ""
        if mode == "whisperx":
            try:
                # Сначала пробуем whisperx-диаризацию полностью.
                text = self._diarize_whisperx(wav_path, whisper_result)
                if text:
                    return text
            except Exception as exc:  # noqa: BLE001
                logger.info("diarization: whisperx упал, fallback на heuristic: %s", exc)
            mode = "heuristic"
        if mode == "heuristic":
            segs = diarize_segments(
                wav_path, whisper_result,
                max_speakers=self.cfg.audio_diarization_max_speakers,
            )
            return format_diarized_transcript(segs)
        return ""

    def _diarize_whisperx(self, wav_path: str, whisper_result: dict) -> str:
        """Полноценная диаризация через WhisperX+pyannote.audio.

        Бросает Exception при любой ошибке (caller отлавливает и делает
        fallback на heuristic). Возвращает форматированный текст
        ``[Голос N] ...`` или пустую строку.
        """
        try:
            import whisperx  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "whisperx не установлен. Установи через панель "
                "(кнопка «Установить whisperx») или вручную: `pip install whisperx`."
            ) from exc

        hf_token = self._resolve_hf_token()
        if not hf_token:
            raise RuntimeError(
                "HuggingFace токен не задан. Получи токен на https://huggingface.co/settings/tokens, "
                "прими условия pyannote-моделей на https://huggingface.co/pyannote/speaker-diarization-3.1 "
                "и впиши токен в панели."
            )

        # WhisperX-диаризация: загрузить audio → DiarizationPipeline →
        # assign_word_speakers (нужен whisper-результат с словами).
        try:
            audio = whisperx.load_audio(wav_path)
            diarize_pipeline = whisperx.DiarizationPipeline(use_auth_token=hf_token, device="cpu")
            diar_result = diarize_pipeline(
                audio,
                min_speakers=1,
                max_speakers=self.cfg.audio_diarization_max_speakers,
            )
            wx_result = dict(whisper_result)
            wx_result.setdefault("segments", [])
            with_speakers = whisperx.assign_word_speakers(diar_result, wx_result)
        except Exception:
            raise

        # Конвертируем whisperx-результат в формат diarize_segments(): [{speaker, start, end, text}].
        out: list[dict] = []
        speaker_map: dict[str, int] = {}
        for seg in (with_speakers.get("segments") or []):
            spk = str(seg.get("speaker") or "")
            if spk and spk not in speaker_map:
                speaker_map[spk] = len(speaker_map)
            out.append({
                "speaker": speaker_map.get(spk, 0),
                "start": float(seg.get("start") or 0.0),
                "end": float(seg.get("end") or 0.0),
                "text": (seg.get("text") or "").strip(),
            })
        return format_diarized_transcript(out)

    def _resolve_hf_token(self) -> str:
        """Берёт HuggingFace-токен из БД (приоритет) или env (HUGGINGFACE_TOKEN/HF_TOKEN)."""
        # БД-токен. Read sync — пайплайн whisperx сам синхронный (asyncio.to_thread).
        try:
            import asyncio as _asyncio
            from app.database import get_setting as _get_setting  # noqa: WPS433
            try:
                loop = _asyncio.get_event_loop()
                if loop.is_running():
                    # Уже в event loop — синхронно ждать нельзя.
                    # _diarize_safe вызывается через asyncio.to_thread, так что
                    # event loop работает в main thread, а мы — в worker.
                    # Используем asyncio.run_coroutine_threadsafe.
                    fut = _asyncio.run_coroutine_threadsafe(_get_setting("huggingface_token", ""), loop)
                    db_token = (fut.result(timeout=5) or "").strip()
                else:
                    db_token = (_asyncio.run(_get_setting("huggingface_token", "")) or "").strip()
            except RuntimeError:
                db_token = ""
            if db_token:
                return db_token
        except Exception as exc:  # noqa: BLE001
            logger.debug("diarization: не смог прочитать hf-token из БД: %s", exc)
        # Fallback на env.
        env_tok = (os.environ.get("HUGGINGFACE_TOKEN") or os.environ.get("HF_TOKEN") or "").strip()
        return env_tok

    # ---- one-shot test methods (for "fast buttons") ----

    async def test_once_vision(self, account_id: int, channel: str) -> dict:
        """One-shot: grab frame + AI vision analysis.  Returns dict with result."""
        img = await asyncio.wait_for(self._grab_frame(channel), timeout=45.0)
        if img is None:
            return {"ok": False, "error": "Не удалось захватить кадр (стрим оффлайн?)"}
        channel_info = await self._fetch_channel_info(account_id, channel)
        prompt = build_vision_prompt(
            style=self.cfg.vision_prompt_style,
            override=self.cfg.vision_prompt_override,
            channel_info=channel_info,
            include_stream_info=self.cfg.vision_include_stream_info,
        )
        description = await self.ai.analyze_image(
            img, prompt=prompt, account_id=account_id, channel=channel,
        )
        if not description:
            return {"ok": False, "error": "AI-vision вернул пустой ответ"}
        if self.cfg.vision_strip_reasoning:
            cleaned = strip_reasoning(description)
            if cleaned:
                description = cleaned
        return {"ok": True, "description": description, "prompt": prompt}

    async def test_once_audio(self, account_id: int, channel: str) -> dict:
        """One-shot: grab audio + whisper + diarization.  Returns dict with result."""
        wav_path = await asyncio.wait_for(
            self._grab_audio(channel, duration=min(self.cfg.audio_interval, 15)),
            timeout=60,
        )
        if not wav_path:
            return {"ok": False, "error": "Не удалось захватить аудио (стрим оффлайн?)"}
        try:
            text, whisper_result = await self._transcribe(wav_path)
        except Exception as exc:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(wav_path)
            return {"ok": False, "error": f"Whisper упал: {exc}"}
        diarized_text = ""
        if text and self.cfg.audio_diarization_mode != "off":
            try:
                diarized_text = await asyncio.to_thread(
                    self._diarize_safe, wav_path, whisper_result,
                )
            except Exception:
                pass
        with contextlib.suppress(FileNotFoundError):
            os.unlink(wav_path)
        if not text:
            return {"ok": False, "error": "Whisper не распознал речь (тишина / музыка?)"}
        return {
            "ok": True,
            "text": text,
            "diarized_text": diarized_text or "",
            "diarization_mode": self.cfg.audio_diarization_mode,
        }

    def _load_whisper(self):
        try:
            import whisper  # type: ignore
        except Exception as exc:  # noqa: BLE001
            logger.warning("openai-whisper не установлен: %s", exc)
            return None
        try:
            return whisper.load_model(self.cfg.whisper_model_size)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Whisper model load failed: %s", exc)
            return None
