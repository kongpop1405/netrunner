@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "PY=py -3.10"
where py >nul 2>&1 && py -3.10 -c "1" >nul 2>&1 || set "PY=python"

%PY% -c "import cv2, numpy, dotenv" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   [X] Not set up yet. Double-click install.bat first.
    echo.
    pause
    exit /b 1
)

echo ============================================
echo   NetRunner - Send-Life to friends
echo ============================================
echo.
echo Precondition: home screen, Friends tab open
echo (the leaderboard/friends list with Send-Life
echo  icons must already be visible).
echo.
echo Sends to every unsent friend, scrolling the
echo list as needed. Stops automatically at the
echo bottom of the list.  Stop early: Ctrl+C
echo.

%PY% main.py --config config/cookierun/sendlife.json --launch --max-cycles 300
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
    echo   bot exited with an error ^(code %RC%^).
    echo   The details were saved to logs\ - send today's log file.
) else (
    echo   bot stopped.
)
pause
