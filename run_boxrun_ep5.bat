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
echo   NetRunner - boxrun bot (Episode 5)
echo   Mystery Box farm - buys Fast Start only, Fast Start
echo   precondition: Episode 5 selected on home
echo   unlimited cycles  ^|  stop: Ctrl+C
echo ============================================
echo.

%PY% main.py --config config/cookierun/boxrun_ep5.json --launch
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
    echo   bot exited with an error ^(code %RC%^).
    echo   The details were saved to logs\ - send today's log file.
) else (
    echo   bot stopped.
)
pause
