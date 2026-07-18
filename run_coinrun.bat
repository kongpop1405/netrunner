@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "PY=python"
where py >nul 2>&1 && set "PY=py"

%PY% -c "import cv2, numpy, dotenv" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   [X] Not set up yet. Double-click install.bat first.
    echo.
    pause
    exit /b 1
)

echo ============================================
echo   NetRunner - cookierun coin grinder
echo   unlimited cycles  ^|  stop: Ctrl+C
echo ============================================
echo.

%PY% main.py --config config/cookierun/coinrun.json --launch
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
    echo   bot exited with an error ^(code %RC%^).
    echo   The details were saved to logs\ - send today's log file.
) else (
    echo   bot stopped.
)
pause
