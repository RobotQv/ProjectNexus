@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "scripts\launch_local.py" %*
) else (
    where py >nul 2>nul
    if errorlevel 1 (
        python "scripts\launch_local.py" %*
    ) else (
        py -3 "scripts\launch_local.py" %*
    )
)
set "NEXUS_LAUNCH_EXIT=%errorlevel%"
if not "%NEXUS_LAUNCH_EXIT%"=="0" (
    echo.
    echo Startup failed. Read the error above and check Python 3.11+ and Node.js.
    pause
)
exit /b %NEXUS_LAUNCH_EXIT%
