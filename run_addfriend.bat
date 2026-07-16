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
echo   NetRunner - Add Friends (Find tab)
echo   device %NETRUNNER_DEVICE%
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

"%ADB_PATH%" connect %NETRUNNER_DEVICE%

python main.py --config config/cookierun/addfriend.json --adb "%ADB_PATH%" --device %NETRUNNER_DEVICE% --max-cycles %CYCLES%

echo.
echo bot stopped.
pause
