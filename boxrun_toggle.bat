@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

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

set "FASTSTART=n"
set "BOOST="
set "JUMP=n"
set "SLIDE=n"

set /p "FASTSTART=Fast Start tap? (y/n) [y]: "
if "%FASTSTART%"=="" set "FASTSTART=y"

:askboost
set "BOOST="
set /p "BOOST=Which boost to buy? (magnet/speed/doublecoins/none) [magnet]: "
if "%BOOST%"=="" set "BOOST=magnet"
if /i "%BOOST%"=="magnet" goto boostok
if /i "%BOOST%"=="speed" goto boostok
if /i "%BOOST%"=="doublecoins" goto boostok
if /i "%BOOST%"=="none" goto boostok
echo   [!] pick one of: magnet, speed, doublecoins, none
goto askboost
:boostok

set /p "JUMP=Jump over pits? (y/n) [y]: "
if "%JUMP%"=="" set "JUMP=y"

set /p "SLIDE=Slide under bars? (y/n) [y]: "
if "%SLIDE%"=="" set "SLIDE=y"

set /p "RELAY=Cookie Relay Boost tap? (y/n) [y]: "
if "%RELAY%"=="" set "RELAY=y"

set "QUITBOXES="
set /p "QUITBOXES=Quit a run after how many boxes banked? (0=never quit early) [0]: "
if "%QUITBOXES%"=="" set "QUITBOXES=0"

echo.
echo   Fast Start=%FASTSTART%  Boost=%BOOST%  Jump=%JUMP%  Slide=%SLIDE%  Relay=%RELAY%  QuitAfterBoxes=%QUITBOXES%
echo   unlimited cycles  ^|  stop: Ctrl+C
echo ============================================
echo.

%PY% tools\run_toggle.py --faststart %FASTSTART% --boost %BOOST% --jump %JUMP% --slide %SLIDE% --relay %RELAY% --quit-after-boxes %QUITBOXES% --launch
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
    echo   bot exited with an error ^(code %RC%^).
    echo   The details were saved to logs\ - send today's log file.
) else (
    echo   bot stopped.
)
pause
