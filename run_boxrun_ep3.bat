@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================
echo   NetRunner - boxrun bot (Episode 3)
echo   Mystery Box farm - buys +17%% speed, Fast Start
echo   precondition: Episode 3 selected on home
echo   unlimited cycles  ^|  stop: Ctrl+C
echo ============================================
echo.

python main.py --config config/cookierun/boxrun_ep3.json

echo.
echo bot stopped.
pause
