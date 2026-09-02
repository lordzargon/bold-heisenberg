@echo off
setlocal enabledelayedexpansion
title GamesMap Job Monitor - Status and Setup
cd /d "%~dp0"

echo ===================================================
echo   GamesMap Career Page Technical Artist Monitor
echo   Process and Scheduler Status Checker
echo ===================================================
echo.

:: 1. Check for Python installation
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

echo [*] Python environment detected: %PY_CMD%
echo.

:: 2. Check if Task Scheduler task exists
set "TASK_NAME=GamesMap_Career_JobMonitor"
schtasks /query /tn "%TASK_NAME%" >nul 2>&1

if %errorlevel% equ 0 (
    echo [OK] Scheduled Task '%TASK_NAME%' is REGISTERED in Windows Task Scheduler.
    echo.
    echo ----------------- Task Details -----------------
    schtasks /query /tn "%TASK_NAME%" /fo LIST | findstr /i /c:"TaskName" /c:"Next Run Time" /c:"Status" /c:"Last Run Time" /c:"Last Result"
    echo ------------------------------------------------
    echo.
    echo [OK] The automated job monitor is configured and scheduled to run at your configured times.
) else (
    echo [!] Scheduled Task '%TASK_NAME%' is NOT registered yet.
    echo [*] Setting up the scheduled task now via setup_scheduler.ps1...
    echo.
    powershell -ExecutionPolicy Bypass -File ".\setup_scheduler.ps1"
    
    :: Verify registration
    schtasks /query /tn "%TASK_NAME%" >nul 2>&1
    if !errorlevel! equ 0 (
        echo.
        echo [OK] Successfully registered '%TASK_NAME%'!
    ) else (
        echo.
        echo [WARNING] Could not verify scheduled task registration.
        echo You may need to run setup_scheduler.ps1 from an Administrator prompt.
    )
)

echo.
echo ===================================================
echo Options:
echo   [1] Open Web GUI Configuration & Live Search (web_app.py)
echo   [2] Run studio career pages check now (career_monitor.py)
echo   [3] Send a test notification
echo   [4] Update / Re-sync Windows Task Scheduler timers (setup_scheduler.ps1)
echo   [5] Refresh / enrich company websites (gamesmap_scraper.py --enrich)
echo   [6] Exit
echo ===================================================
set /p "USER_CHOICE=Enter choice (1-6, default is 1): "

if "%USER_CHOICE%"=="" set "USER_CHOICE=1"

if "%USER_CHOICE%"=="1" (
    echo.
    echo [*] Starting Web GUI Server...
    %PY_CMD% web_app.py
) else if "%USER_CHOICE%"=="2" (
    echo.
    echo [*] Running immediate career pages check...
    %PY_CMD% career_monitor.py
) else if "%USER_CHOICE%"=="3" (
    echo.
    echo [*] Running test notification...
    %PY_CMD% career_monitor.py --test-notify
) else if "%USER_CHOICE%"=="4" (
    echo.
    echo [*] Updating Windows Task Scheduler triggers from config.json...
    powershell -ExecutionPolicy Bypass -File ".\setup_scheduler.ps1"
) else if "%USER_CHOICE%"=="5" (
    echo.
    echo [*] Running scraper and enrichment...
    %PY_CMD% gamesmap_scraper.py --enrich
) else (
    echo.
    echo Exiting. The monitor will continue running on its scheduled timetable.
)

echo.
pause
