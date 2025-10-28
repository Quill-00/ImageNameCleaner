@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul

title ImageNameCleaner - QUILL v1.0
echo =========================================
echo ImageNameCleaner
echo Version: v1.0
echo Author: QUILL
echo License: Apache-2.0
echo =========================================
echo.

REM Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python 3.7+ not found. Please install Python.
    echo https://www.python.org/downloads/
    pause
    exit /b 1
)

REM Ensure we run from script directory (safe for non-ASCII paths)
cd /d "%~dp0"

REM Check main program
if not exist "cleaner.py" (
    echo [ERROR] cleaner.py not found.
    pause
    exit /b 1
)

REM Check config (optional)
if not exist "config.ini" (
    echo [WARN ] config.ini not found, using defaults.
)

echo [INFO ] Launching ImageNameCleaner...
echo.

REM Run main program
python "%~dp0cleaner.py"

echo.
echo [INFO ] Done.
pause