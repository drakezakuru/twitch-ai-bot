#!/bin/bash
# v10.4.7 — улучшенный запуск с self-healing venv + автоустановкой.
#
# Флаги:
#   --reinstall   удалить venv и переустановить всё с нуля
#   --skip-install  пропустить проверку/установку зависимостей
#   --no-browser  не открывать браузер автоматически
#   --ml          установить optional Whisper/SpeechBrain stack
#
# Примеры:
#   ./start.sh                  # обычный запуск (auto-install при необходимости)
#   ./start.sh --reinstall      # пересоздать venv с нуля
#   ./start.sh --skip-install   # быстрый старт (если знаешь что всё установлено)
#   ./start.sh --ml             # добавить локальные ML/audio возможности
#   ./start.sh --no-tts         # не устанавливать optional XTTS/Coqui

set -e

echo "================================"
echo "  Twitch AI Bot Panel"
echo "================================"
echo ""

cd "$(dirname "$0")"

REINSTALL=0
SKIP_INSTALL=0
NO_BROWSER=0
INSTALL_TTS="${INSTALL_TTS:-1}"
INSTALL_F5=0
INSTALL_ML=0
for arg in "$@"; do
    case "$arg" in
        --reinstall) REINSTALL=1 ;;
        --skip-install) SKIP_INSTALL=1 ;;
        --no-browser) NO_BROWSER=1 ;;
        --no-tts) INSTALL_TTS=0 ;;
        --f5) INSTALL_F5=1 ;;
        --ml) INSTALL_ML=1 ;;
    esac
done

# ---------- Step 1: detect Python ----------

PYTHON_BIN=""
for cand in python3 python python3.12 python3.11 python3.10; do
    if command -v "$cand" &>/dev/null; then
        # Проверяем что версия >= 3.10
        ver=$("$cand" -c 'import sys; print(sys.version_info[0]*100+sys.version_info[1])' 2>/dev/null || echo "0")
        if [ "$ver" -ge 310 ]; then
            PYTHON_BIN="$cand"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo "[ERROR] Python 3.10+ не найден!"
    echo ""
    echo "Установи Python:"
    echo "  Arch/SteamOS: sudo pacman -S python"
    echo "  Ubuntu/Debian: sudo apt install python3 python3-venv python3-pip"
    echo "  Fedora: sudo dnf install python3 python3-pip"
    echo ""
    read -p "Нажми Enter для выхода..."
    exit 1
fi
echo "[*] Python: $($PYTHON_BIN --version) → $PYTHON_BIN"

# ---------- Step 2: --reinstall пересоздаёт venv ----------

if [ "$REINSTALL" = "1" ] && [ -d "venv" ]; then
    echo "[*] --reinstall: удаляю старую venv..."
    rm -rf venv
fi

# ---------- Step 3: создание venv если её нет ----------

VENV_PY="venv/bin/python"

if [ ! -d "venv" ] || [ ! -x "$VENV_PY" ]; then
    echo "[*] Создаю virtual environment..."
    if ! "$PYTHON_BIN" -m venv venv 2>/tmp/venv_err.log; then
        echo "[ERROR] python -m venv не сработал. Возможно нужен python3-venv:"
        echo ""
        cat /tmp/venv_err.log
        echo ""
        echo "Установи venv-модуль:"
        echo "  Ubuntu/Debian: sudo apt install python3-venv"
        echo "  Fedora: sudo dnf install python3-venv (входит в python3)"
        echo "  Arch/SteamOS: уже в python"
        read -p "Нажми Enter для выхода..."
        exit 1
    fi
    # принудительно ставим зависимости после создания
    SKIP_INSTALL=0
    NEED_INSTALL=1
else
    NEED_INSTALL=0
fi

# ---------- Step 4: проверяем что ключевые пакеты есть, ставим если нет ----------

check_deps() {
    "$VENV_PY" -c "import uvicorn, fastapi, twitchio, aiosqlite" 2>/dev/null
}

if [ "$SKIP_INSTALL" != "1" ]; then
    if [ "$NEED_INSTALL" = "1" ] || ! check_deps; then
        echo "[*] Устанавливаю зависимости (это может занять 1-3 минуты)..."
        # обновляем pip без шума если можем
        "$VENV_PY" -m pip install --upgrade pip --quiet 2>/dev/null || true
        if ! "$VENV_PY" -m pip install -r requirements.lock; then
            echo ""
            echo "[ERROR] Не удалось установить зависимости."
            echo "Попробуй:"
            echo "  1) Проверь интернет: ping pypi.org"
            echo "  2) Запусти с force-reinstall: ./start.sh --reinstall"
            echo "  3) Ручной запуск: source venv/bin/activate && pip install -r requirements.lock"
            read -p "Нажми Enter для выхода..."
            exit 1
        fi
        echo "[*] Зависимости установлены."
    fi

    # Repair environments created before the lock started pinning TwitchIO v2.
    TWITCHIO_VER=$("$VENV_PY" -m pip show twitchio 2>/dev/null | grep -E "^Version:" | awk '{print $2}' || echo "")
    if [[ "$TWITCHIO_VER" == 3.* ]]; then
        echo "[!] Найден twitchio v3 ($TWITCHIO_VER), восстанавливаю core lock..."
        "$VENV_PY" -m pip install -r requirements.lock --quiet
    fi
fi

# Whisper/SpeechBrain pull the local Torch stack, so install them only when
# the operator explicitly enables local transcription or voice verification.
if [ "$SKIP_INSTALL" != "1" ] && [ "$INSTALL_ML" = "1" ]; then
    echo "[*] Устанавливаю optional ML/audio зависимости..."
    if ! "$VENV_PY" -m pip install -r requirements-ml.txt; then
        echo "[ERROR] Не удалось установить requirements-ml.txt. Core-панель уже установлена."
        exit 1
    fi
fi

# XTTS/Coqui is optional and installed automatically once. It is deliberately
# non-fatal: Piper/Web Speech remain available on unsupported Python/OS builds.
# §2.1: Coqui TTS требует Python 3.9–3.11 — на 3.12+ пропускаем с подсказкой
# про F5-TTS (работает на 3.10+); ставится явно через './start.sh --f5'.
if [ "$SKIP_INSTALL" != "1" ] && [ "$INSTALL_TTS" = "1" ] && ! "$VENV_PY" -c "import TTS" &>/dev/null; then
    VENV_PY_VER=$("$VENV_PY" -c 'import sys;print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
    if [ "$(printf '%s\n3.12' "$VENV_PY_VER" | sort -V | head -1)" = "3.12" ]; then
        echo "[i] Python $VENV_PY_VER: Coqui XTTS требует Python 3.9–3.11 — пропускаю авто-установку."
        echo "    Локальный клон голоса на этом Python — F5-TTS:"
        echo "      ./start.sh --f5   (или вручную: venv/bin/pip install f5-tts)"
        echo "      затем в панели: TTS бота → провайдер xtts, настройка tts_clone_engine = f5tts"
        echo "    Piper и Web Speech доступны как раньше."
    else
        echo "[*] Устанавливаю optional XTTS/Coqui (может занять несколько минут)..."
        if ! "$VENV_PY" -m pip install -r requirements-tts.txt; then
            echo "[WARN] XTTS/Coqui не установлен. Piper и Web Speech доступны. Используйте --no-tts, чтобы пропустить это позже."
        fi
    fi
fi

# F5-TTS (§2.1): явная опция './start.sh --f5' — локальный клон из образца.
if [ "$INSTALL_F5" = "1" ] && ! "$VENV_PY" -c "import f5_tts" &>/dev/null; then
    echo "[*] Устанавливаю F5-TTS (torch и модели скачаются при первом синтезе)..."
    if ! "$VENV_PY" -m pip install f5-tts; then
        echo "[WARN] F5-TTS не установлен. См. venv/bin/pip install f5-tts."
    fi
fi

# ---------- Step 5: финальная проверка ----------

if ! check_deps; then
    echo "[ERROR] Зависимости всё ещё отсутствуют. Запусти: ./start.sh --reinstall"
    read -p "Нажми Enter для выхода..."
    exit 1
fi

# ---------- Step 6: запуск ----------

if [ "$NO_BROWSER" = "1" ]; then
    export TWITCH_BOT_NO_BROWSER=1
fi

echo ""
echo "[*] Запускаю панель: http://localhost:8000"
echo "[*] Ctrl+C для остановки"
echo ""

# Используем venv python напрямую (не нужно source активацию)
"$VENV_PY" run.py
