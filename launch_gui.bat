@echo off
setlocal enabledelayedexpansion
title Game Dev Job Monitor - Web GUI
cd /d "%~dp0"

echo ===================================================
echo   Game Dev Automated Job Monitor
echo   Interactive Configuration ^& Live Search GUI
echo ===================================================
echo.

:: Detect Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    where py >nul 2>&1
    if %errorlevel% neq 0 (
        echo [ERROR] Python was not found in your PATH.
        echo Please install Python 3.8+ or add it to your PATH.
        echo.
        pause
        exit /b 1
    )
    set "PY_CMD=py -3"
) else (
    set "PY_CMD=python"
)

echo [*] Starting Web GUI Server with %PY_CMD%...
echo [*] Opening browser to http://127.0.0.1:8765
echo.

%PY_CMD% web_app.py

if %errorlevel% neq 0 (
    echo.
    echo [!] Server stopped or exited with error.
    pause
)
