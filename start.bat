@echo off
chcp 65001 >nul 2>&1
title Twitch AI Bot Panel
echo ================================
echo   Twitch AI Bot Panel
echo ================================
echo.

REM v10.4.7 — self-healing venv + auto-install.
REM Перед первым запуском скопируй .env.example в .env и заполни токены:
REM   copy .env.example .env
REM Flags: --reinstall   (recreate venv)
REM        --skip-install (just activate and run)
REM        --ml          (install optional Whisper/SpeechBrain stack)

set REINSTALL=0
set SKIP_INSTALL=0
set INSTALL_ML=0
for %%a in (%*) do (
    if /I "%%a"=="--reinstall" set REINSTALL=1
    if /I "%%a"=="--skip-install" set SKIP_INSTALL=1
    if /I "%%a"=="--ml" set INSTALL_ML=1
)

cd /d "%~dp0"

REM ---------- Step 1: detect Python ----------
set PYTHON_BIN=
for %%P in (python python3 py) do (
    if not defined PYTHON_BIN (
        %%P --version >nul 2>&1
        if not errorlevel 1 (
            set PYTHON_BIN=%%P
        )
    )
)

if not defined PYTHON_BIN (
    echo [ERROR] Python not found!
    echo Install Python 3.10+: https://www.python.org/downloads/
    echo IMPORTANT: check "Add Python to PATH" during install.
    pause
    exit /b 1
)
echo [*] Python: 
%PYTHON_BIN% --version

REM ---------- Step 2: --reinstall ----------
if "%REINSTALL%"=="1" (
    if exist venv (
        echo [*] --reinstall: removing old venv...
        rmdir /s /q venv
    )
)

REM ---------- Step 3: create venv if missing ----------
set NEED_INSTALL=0
set VENV_PY=venv\Scripts\python.exe
if not exist "%VENV_PY%" (
    echo [*] Creating virtual environment...
    %PYTHON_BIN% -m venv venv
    if errorlevel 1 (
        echo [ERROR] python -m venv failed. Reinstall Python with full options.
        pause
        exit /b 1
    )
    set NEED_INSTALL=1
)

REM ---------- Step 4: check deps + install if missing ----------
if "%SKIP_INSTALL%"=="1" goto SKIP_DEPS

"%VENV_PY%" -c "import uvicorn, fastapi, twitchio, aiosqlite" >nul 2>&1
if errorlevel 1 set NEED_INSTALL=1

if "%NEED_INSTALL%"=="1" (
    echo [*] Installing dependencies (1-3 minutes)...
    "%VENV_PY%" -m pip install --upgrade pip --quiet
    "%VENV_PY%" -m pip install -r requirements.lock
    if errorlevel 1 (
        echo.
        echo [ERROR] Install failed. Try:
        echo   1^) Check internet
        echo   2^) start.bat --reinstall
        pause
        exit /b 1
    )
    echo [*] Dependencies installed.
)

REM Repair environments created before the lock started pinning TwitchIO v2.
"%VENV_PY%" -m pip show twitchio 2>nul | findstr /C:"Version: 3." >nul 2>&1
if not errorlevel 1 (
    echo [!] Detected twitchio v3, restoring core lock...
    "%VENV_PY%" -m pip install -r requirements.lock --quiet
)

if "%INSTALL_ML%"=="1" (
    echo [*] Installing optional ML/audio dependencies...
    "%VENV_PY%" -m pip install -r requirements-ml.txt
    if errorlevel 1 (
        echo [ERROR] requirements-ml.txt install failed. Core panel is already installed.
        exit /b 1
    )
)

:SKIP_DEPS

REM ---------- Step 5: final check ----------
"%VENV_PY%" -c "import uvicorn, fastapi" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Dependencies still missing. Run: start.bat --reinstall
    pause
    exit /b 1
)

REM ---------- Step 6: run ----------
echo.
echo [*] Starting panel: http://localhost:8000
echo [*] Browser will open automatically.
echo [*] Ctrl+C to stop.
echo.

"%VENV_PY%" run.py

pause
