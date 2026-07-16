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
echo   NetRunner - boxrun bot (Episode 3)
echo   Mystery Box farm - buys +17%% speed, Fast Start
echo   precondition: Episode 3 selected on home
echo   device %NETRUNNER_DEVICE%  ^|  unlimited cycles
echo   stop: Ctrl+C
echo ============================================
echo.

"%ADB_PATH%" connect %NETRUNNER_DEVICE%

python main.py --config config/cookierun/boxrun_ep3.json --adb "%ADB_PATH%" --device %NETRUNNER_DEVICE%

echo.
echo bot stopped.
pause
