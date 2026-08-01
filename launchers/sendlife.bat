@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

rem numpy's bundled OpenBLAS can fail to allocate its thread-pool memory
rem on some machines ("Memory allocation still failed after 10 retries").
rem Capping threads to 1 avoids it; matchTemplate is single-frame work so
rem this costs no meaningful speed.
set "OPENBLAS_NUM_THREADS=1"
set "OMP_NUM_THREADS=1"

set "PY="
for %%V in ("py -3.10" "py -3.11" "py -3.12" "py -3" "py" "python") do (
    if not defined PY (
        %%~V -c "import cv2, numpy, dotenv" >nul 2>&1
        if not errorlevel 1 set "PY=%%~V"
    )
)

if not defined PY (
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
