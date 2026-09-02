@echo off
setlocal
title GamesMap Job Monitor - Test Notification
cd /d "%~dp0"

echo ===================================================
echo   GamesMap Career Page Technical Artist Monitor
echo   Test Notification Runner
echo ===================================================
echo.

:: Check for python
where python >nul 2>&1
if %errorlevel% neq 0 (
    where py >nul 2>&1
    if %errorlevel% neq 0 (
        echo [ERROR] Python was not found in your PATH.
        echo Please install Python or ensure it is added to your PATH.
        echo.
        pause
        exit /b 1
    )
    set "PY_CMD=py -3"
) else (
    set "PY_CMD=python"
)

echo [*] Triggering test notification via: %PY_CMD% career_monitor.py --test-notify
echo.
%PY_CMD% career_monitor.py --test-notify
set "EXIT_CODE=%errorlevel%"

echo.
if "%EXIT_CODE%"=="0" (
    echo [OK] Test notification dispatched successfully!
) else (
    echo [ERROR] Failed to dispatch test notification [Exit code: %EXIT_CODE%].
)
echo.
pause
