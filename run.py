#!/usr/bin/env python3
"""Запуск Twitch AI Bot Panel."""

import logging
import os
import sys
import threading
import time
import traceback
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path


def fix_ssl_certificates() -> None:
    """Fix SSL certificate errors on Windows."""
    # Remove broken SSL_CERT_FILE if it points to non-existent file
    for key in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
        val = os.environ.get(key, "")
        if val and not os.path.exists(val):
            del os.environ[key]
    # Set certifi path only if file exists
    try:
        import certifi
        ca_path = certifi.where()
        if os.path.exists(ca_path):
            os.environ.setdefault("SSL_CERT_FILE", ca_path)
            os.environ.setdefault("REQUESTS_CA_BUNDLE", ca_path)
    except ImportError:
        pass

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "panel.log"

# Фильтр: убираем SQL шум от aiosqlite
class _NoiseFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Пропускаем спам aiosqlite
        if "aiosqlite" in record.name:
            return record.levelno >= logging.WARNING
        return True

# OPS_PLAN §4: ротация 10МБ × 5 файлов
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"),
    ],
)
# Добавляем фильтр шума ко всем логгерам
logging.getLogger().addFilter(_NoiseFilter())
logging.getLogger("aiosqlite").setLevel(logging.WARNING)
logger = logging.getLogger("run")


def open_browser() -> None:
    """Открывает браузер после небольшой задержки (ждём старт сервера)."""
    time.sleep(2)
    url = "http://localhost:8000"
    logger.info("Открываю браузер: %s", url)
    webbrowser.open(url)


def should_open_browser(args: list[str] | None = None) -> bool:
    args = sys.argv[1:] if args is None else args
    disabled_by_env = os.getenv("TWITCH_BOT_NO_BROWSER", "").strip().lower() in {
        "1", "true", "yes", "on",
    }
    return "--no-browser" not in args and not disabled_by_env


def ensure_env_file() -> None:
    """Create .env with Ollama defaults if it doesn't exist."""
    env_path = Path(".env")
    if not env_path.exists():
        env_path.write_text(
            "AI_PROVIDER=ollama\n"
            "OLLAMA_HOST=http://localhost:11434\n"
            "OLLAMA_CHAT_MODEL=llama3\n"
            "OLLAMA_VISION_MODEL=llava\n",
            encoding="utf-8",
        )
        logger.info(".env created with Ollama defaults")


# ── OPS_PLAN §5: .env doctor — проверка окружения без запуска панели ──

def _load_dotenv() -> None:
    env_path = Path(".env")
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


def resolve_panel_host(
    requested_host: str | None = None,
    *,
    encryption_enabled: bool | None = None,
    auth_enabled: bool | None = None,
) -> str:
    """Keep the default desktop launch local; protect every network bind."""
    host = (requested_host or os.getenv("PANEL_BIND_HOST", "127.0.0.1")).strip() or "127.0.0.1"
    from app.security import is_auth_enabled, is_encryption_enabled, is_loopback_host

    encrypted = is_encryption_enabled() if encryption_enabled is None else encryption_enabled
    authenticated = is_auth_enabled() if auth_enabled is None else auth_enabled
    qa_profile = os.getenv("QA_PROFILE", "").strip().lower() in {"1", "true", "yes", "on"}
    if not qa_profile and not is_loopback_host(host) and not (encrypted and authenticated):
        logger.warning("!" * 72)
        logger.warning("ВНИМАНИЕ: сетевой доступ к панели не настроен безопасно.")
        logger.warning("Bind принудительно изменён на 127.0.0.1; localhost работает без пароля.")
        logger.warning("Для LAN настройте PANEL_AUTH_USER, PANEL_AUTH_PASS и TOKEN_ENCRYPTION_KEY.")
        logger.warning("!" * 72)
        host = "127.0.0.1"
    os.environ["PANEL_BIND_HOST"] = host
    return host


def _check(label: str, ok: bool | None, impact: str) -> str:
    """ok=True → ✓, False → ✗, None → ⚠ (не критично)."""
    mark = {True: "✓", False: "✗", None: "⚠"}[ok]
    suffix = "" if ok else f"  → {impact}"
    return f"  [{mark}] {label}{suffix}"


def run_doctor() -> int:
    """Проверка ключей, Helix, Ollama, папок, прав записи. 0 = всё критичное ок."""
    import shutil
    import sqlite3

    _load_dotenv()
    provider = os.getenv("AI_PROVIDER", "openrouter").strip().lower()
    problems = 0

    print("\n=== Twitch AI Bot — doctor ===")
    print(f"Python: {sys.version.split()[0]} (нужен 3.10+)")
    if sys.version_info < (3, 10):
        problems += 1
        print(_check("Версия Python", False, "панель требует Python 3.10+"))

    # Папки и права записи
    print("\nПапки:")
    for d in ("data", "logs", "data/backups"):
        p = Path(d)
        try:
            p.mkdir(parents=True, exist_ok=True)
            probe = p / ".doctor-probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            print(_check(f"{d}/ (запись)", True, ""))
        except OSError as exc:
            problems += 1
            print(_check(f"{d}/ (запись)", False, f"нет прав записи: {exc}"))

    # БД
    print("\nБаза данных:")
    db_path = Path("data/bot.db")
    if db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            res = conn.execute("PRAGMA integrity_check").fetchone()[0]
            conn.close()
            ok = res == "ok"
            if not ok:
                problems += 1
            size_mb = db_path.stat().st_size / 1024 / 1024
            print(_check(f"SQLite {db_path} ({size_mb:.1f} МБ), integrity={res}", ok,
                         "БД повреждена — восстанови из бэкапа (data/backups)"))
        except sqlite3.Error as exc:
            problems += 1
            print(_check("SQLite", False, str(exc)))
    else:
        print(_check("data/bot.db", None, "БД будет создана при первом запуске"))

    # AI-провайдер
    print(f"\nAI-провайдер: {provider}")
    if provider == "ollama":
        host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        try:
            import urllib.request
            with urllib.request.urlopen(f"{host.rstrip('/')}/api/tags", timeout=3) as resp:
                models = [m.get("name", "") for m in __import__("json").loads(resp.read()).get("models", [])]
            print(_check(f"Ollama {host} (модели: {', '.join(models[:3]) or 'нет'})", True, ""))
            if not models:
                print(_check("Модели Ollama", None, "ollama pull llama3 — иначе чат-ответы не работают"))
        except Exception as exc:
            problems += 1
            print(_check(f"Ollama {host}", False, f"не отвечает ({exc}) — запусти ollama serve"))
    else:
        key = os.getenv("OPENROUTER_API_KEY", "")
        if key:
            print(_check("OPENROUTER_API_KEY задан", True, ""))
        else:
            problems += 1
            print(_check("OPENROUTER_API_KEY", False,
                         "без ключа чат-ответы не работают; задай в .env или выбери Ollama"))

    # Twitch
    print("\nTwitch:")
    token = os.getenv("TWITCH_TOKEN", "")
    client_id = os.getenv("TWITCH_CLIENT_ID", "")
    client_secret = os.getenv("TWITCH_CLIENT_SECRET", "")
    if token:
        print(_check("OAuth-токен бота (TWITCH_TOKEN)", True, ""))
    else:
        print(_check("OAuth-токен бота", None,
                     "в .env не задан — это ок, если аккаунт уже подключён через панель (токен в БД)"))
    print(_check("TWITCH_CLIENT_ID/SECRET (Helix)", bool(client_id and client_secret),
                 "без них не работают: подписки/рейды/стрим-статус/Helix-запросы"))

    # TTS (опционально)
    print("\nTTS (опционально):")
    print(_check("ELEVENLABS_API_KEY", True if os.getenv("ELEVENLABS_API_KEY") else None,
                 "без ключа TTS упадёт на Piper/Web Speech — это ок, если они настроены"))
    print(_check("Piper (piper в PATH)", True if shutil.which("piper") else None,
                 "оффлайн-TTS недоступен; останется Web Speech в браузере"))

    print("\nИтог:", "есть проблемы — см. пометки ✗ выше" if problems else "всё критичное настроено ✓")
    return 1 if problems else 0


def main() -> None:
    if "--doctor" in sys.argv:
        sys.exit(run_doctor())

    fix_ssl_certificates()
    ensure_env_file()
    _load_dotenv()
    panel_host = resolve_panel_host()

    logger.info("=" * 50)
    logger.info("Twitch AI Bot Panel — запуск")
    logger.info("Лог-файл: %s", LOG_FILE.resolve())
    logger.info("=" * 50)

    try:
        import uvicorn
    except ImportError:
        # v10.4.7: пробуем поставить зависимости автоматически
        logger.warning("uvicorn не установлен — пробую автоматическую установку...")
        req_file = Path("requirements.txt")
        if req_file.exists():
            import subprocess
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(req_file)])
                logger.info("Зависимости установлены, продолжаю запуск...")
                import uvicorn  # повторная попытка
            except Exception as exc:
                logger.error("Автоустановка не удалась: %s", exc)
                logger.error("Запусти вручную:")
                logger.error("  Linux/Mac:  ./start.sh --reinstall")
                logger.error("  Windows:    start.bat --reinstall")
                logger.error("  Или:        %s -m pip install -r requirements.txt", sys.executable)
                input("Нажмите Enter для выхода...")
                sys.exit(1)
        else:
            logger.error("uvicorn не установлен и requirements.txt не найден!")
            logger.error("Запусти ./start.sh (Linux/Mac) или start.bat (Windows) — они установят зависимости автоматически.")
            input("Нажмите Enter для выхода...")
            sys.exit(1)

    if should_open_browser():
        threading.Thread(target=open_browser, daemon=True).start()

    try:
        uvicorn.run(
            "app.server:app",
            host=panel_host,
            port=8000,
            reload=False,
            log_level="info",
        )
    except Exception:
        logger.critical("КРИТИЧЕСКАЯ ОШИБКА ПРИ ЗАПУСКЕ:")
        logger.critical(traceback.format_exc())
        print(f"\n\n!!! ОШИБКА — смотрите лог: {LOG_FILE} !!!\n")
        input("Нажмите Enter для выхода...")
        sys.exit(1)


if __name__ == "__main__":
    main()
