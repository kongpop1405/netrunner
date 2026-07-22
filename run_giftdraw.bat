@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

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
echo   NetRunner - Gift Draw box opener
echo ============================================
echo.
echo Precondition: Gift Draw popup must already be open
echo (home -^> tap the Rewards gift-box icon).
echo.

set /p BOXES="How many boxes to open? "

echo %BOXES%| findstr /r "^[1-9][0-9]*$" >nul
if errorlevel 1 (
    echo Invalid input: "%BOXES%" is not a positive whole number.
    pause
    exit /b 1
)

rem 3 cycles/box happy path; a rare treasure popup routes through the retry
rem chain + rescue (~8 extra cycles), so budget 4/box + 1 rescue-chain buffer.
set /a CYCLES=BOXES*4+8

echo.
echo Opening %BOXES% box(es)  ^(cap %CYCLES% cycles^)  ^|  stop early: Ctrl+C
echo.

%PY% main.py --config config/cookierun/giftdraw.json --launch --max-cycles %CYCLES%
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
    echo   bot exited with an error ^(code %RC%^).
    echo   The details were saved to logs\ - send today's log file.
) else (
    echo   bot stopped.
)
pause
