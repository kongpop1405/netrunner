@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================
echo   NetRunner - Send-Life to friends
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

python main.py --config config/cookierun/sendlife.json --max-cycles 300

echo.
echo bot stopped.
pause
