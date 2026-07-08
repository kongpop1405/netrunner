@echo off
chcp 65001 >nul
setlocal

set "ADB=C:\LDPlayer\LDPlayer9\adb.exe"
set "REPO=%~dp0"
cd /d "%REPO%"

echo ============================================
echo   NetRunner - Send-Life to friends
echo   device 127.0.0.1:5555
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

"%ADB%" connect 127.0.0.1:5555

python main.py --config config/sendlife.json --adb "%ADB%" --max-cycles 300

echo.
echo bot stopped.
pause
