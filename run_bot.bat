@echo off
chcp 65001 >nul
setlocal

set "ADB=C:\LDPlayer\LDPlayer9\adb.exe"
set "REPO=%~dp0"
cd /d "%REPO%"

echo ============================================
echo   NetRunner - cookierun bot
echo   device 127.0.0.1:5555  ^|  unlimited cycles
echo   stop: Ctrl+C
echo ============================================
echo.

"%ADB%" connect 127.0.0.1:5555

python main.py --config config/cookierun.json --adb "%ADB%"

echo.
echo bot stopped.
pause
