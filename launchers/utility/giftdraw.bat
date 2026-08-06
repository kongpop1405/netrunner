@echo off
chcp 65001 >nul
setlocal
rem Find the repo root by walking up until main.py appears, instead of
rem hardcoding how many ..\ it takes. Moving this file needs no edit.
set "ROOT=%~dp0"
:findroot
if exist "%ROOT%main.py" goto gotroot
set "PREV=%ROOT%"
for %%I in ("%ROOT%..") do set "ROOT=%%~fI\"
if "%ROOT%"=="%PREV%" goto noroot
goto findroot
:noroot
echo.
echo   [X] Could not find the project root ^(no main.py above "%~dp0"^).
echo       Keep this file inside the netrunner folder.
echo.
pause
exit /b 1
:gotroot
cd /d "%ROOT%"

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
