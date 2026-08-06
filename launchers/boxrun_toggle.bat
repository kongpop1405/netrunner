@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
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
echo   NetRunner - boxrun bot (toggle)
echo   Mystery Box farm - pick which run actions to use
echo   precondition: an episode is selected on home
echo ============================================
echo.

set "FASTSTART=y"
set /p "FASTSTART=Fast Start? [y]: "
if "%FASTSTART%"=="" set "FASTSTART=y"

:askboost
set "BOOSTPICK="
set /p "BOOSTPICK=Boost? 0=none 1=magnet 2=speed 3=coins [0]: "
if "%BOOSTPICK%"=="" set "BOOSTPICK=0"
set "BOOST="
if "%BOOSTPICK%"=="0" set "BOOST=none"
if "%BOOSTPICK%"=="1" set "BOOST=magnet"
if "%BOOSTPICK%"=="2" set "BOOST=speed"
if "%BOOSTPICK%"=="3" set "BOOST=doublecoins"
if not defined BOOST (
    echo   [!] pick 0-3
    goto askboost
)

rem Jump/Slide prompt hidden for now - both run actions default ON.
rem Do NOT set this to n: with no jump/slide the hop states carry only a goto,
rem and the engine then keeps matching on the SAME cached frame until a pure-goto
rem chain has revisited every state (src/fsm.py). The Cookie Relay prompt only
rem lasts ~2-3s, so the relay chain would only ever see a stale pre-prompt frame
rem and never fire. Verified 2026-08-04.
rem Re-enable the prompt by uncommenting the two lines below.
set "JUMPSLIDE=y"
rem set /p "JUMPSLIDE=Jump + Slide? [y]: "
rem if "%JUMPSLIDE%"=="" set "JUMPSLIDE=y"
set "JUMP=%JUMPSLIDE%"
set "SLIDE=%JUMPSLIDE%"

rem Cookie Relay has no prompt: it is always on, same as any config run through
rem main.py. The relay states are detect-then-tap, so with no prompt on screen
rem they fall straight through and cost nothing.

:askrelic
set "RELICPICK="
set /p "RELICPICK=Relic? y=claim n=claim+stop [n]: "
if "%RELICPICK%"=="" set "RELICPICK=n"
set "RELICMODE="
if /i "%RELICPICK%"=="n" set "RELICMODE=stop"
if /i "%RELICPICK%"=="y" set "RELICMODE=claim"
if not defined RELICMODE (
    echo   [!] pick y or n
    goto askrelic
)

set "QUITBOXES=0"
set /p "QUITBOXES=Quit after N boxes? 0=off [0]: "
if "%QUITBOXES%"=="" set "QUITBOXES=0"

rem Idle prompt hidden for now - idling between games stays off.
rem Re-enable by uncommenting the two lines below.
set "IDLE=n"
rem set /p "IDLE=Idle? y=config n=off MIN-MAX [n]: "
rem if "%IDLE%"=="" set "IDLE=n"

echo.
echo   Fast Start=%FASTSTART%  Boost=%BOOST%  Jump=%JUMP%  Slide=%SLIDE%  Relay=always  RelicMode=%RELICMODE%  QuitAfterBoxes=%QUITBOXES%  Idle=%IDLE%
echo   unlimited cycles  ^|  stop: Ctrl+C
echo ============================================
echo.

%PY% tools\run_toggle.py --faststart %FASTSTART% --boost %BOOST% --jump %JUMP% --slide %SLIDE% --relic-mode %RELICMODE% --quit-after-boxes %QUITBOXES% --idle %IDLE% --launch
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
    echo   bot exited with an error ^(code %RC%^).
    echo   The details were saved to logs\ - send today's log file.
) else (
    echo   bot stopped.
)
pause
