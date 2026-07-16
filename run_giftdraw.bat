@echo off
chcp 65001 >nul
setlocal

set "REPO=%~dp0"
cd /d "%REPO%"

rem machine-specific settings come from .env (copy .env.example) — fallbacks below
if exist ".env" for /f "usebackq eol=# tokens=1,* delims==" %%a in (".env") do set "%%a=%%b"
if not defined ADB_PATH set "ADB_PATH=adb"
if not defined NETRUNNER_DEVICE set "NETRUNNER_DEVICE=127.0.0.1:5555"

echo ============================================
echo   NetRunner - Gift Draw box opener
echo   device %NETRUNNER_DEVICE%
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
rem chain + rescue (~8 extra cycles), so budget 5/box + a bigger buffer.
set /a CYCLES=BOXES*5+15

echo.
echo Opening %BOXES% box(es)  ^(cap %CYCLES% cycles^)  ^|  stop early: Ctrl+C
echo.

"%ADB_PATH%" connect %NETRUNNER_DEVICE%

python main.py --config config/cookierun/giftdraw.json --adb "%ADB_PATH%" --device %NETRUNNER_DEVICE% --max-cycles %CYCLES%

echo.
echo bot stopped.
pause
