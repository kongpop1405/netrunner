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
echo   NetRunner - Add Friends (Find tab)
echo ============================================
echo.
echo Entry is automated: works from home (taps the
echo Friends icon then the Find tab), or from the
echo Find tab already open.
echo.
echo Loop: Request x4 visible -^> Refresh -^> repeat.
echo.

set /p FRIENDS="How many friend requests to send? "

echo %FRIENDS%| findstr /r "^[1-9][0-9]*$" >nul
if errorlevel 1 (
    echo Invalid input: "%FRIENDS%" is not a positive whole number.
    pause
    exit /b 1
)

set /a CYCLES=FRIENDS*5/4+8

echo.
echo Sending %FRIENDS% request(s)  ^(cap %CYCLES% cycles^)  ^|  stop early: Ctrl+C
echo.

%PY% main.py --config config/cookierun/addfriend.json --launch --max-cycles %CYCLES%
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
    echo   bot exited with an error ^(code %RC%^).
    echo   The details were saved to logs\ - send today's log file.
) else (
    echo   bot stopped.
)
pause
