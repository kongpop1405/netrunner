@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================
echo   NetRunner - cookierun coin grinder
echo   unlimited cycles  ^|  stop: Ctrl+C
echo ============================================
echo.

python main.py --config config/cookierun/coinrun.json

echo.
echo bot stopped.
pause
