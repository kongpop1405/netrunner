@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================
echo   NetRunner - Add Friends (Find tab)
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

python main.py --config config/cookierun/addfriend.json --max-cycles %CYCLES%

echo.
echo bot stopped.
pause
