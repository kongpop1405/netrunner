@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================
echo   NetRunner - Gift Draw box opener
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

python main.py --config config/cookierun/giftdraw.json --max-cycles %CYCLES%

echo.
echo bot stopped.
pause
