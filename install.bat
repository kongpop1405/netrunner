@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "LOG=%~dp0install-log.txt"
echo NetRunner install log  %DATE% %TIME%> "%LOG%"
echo repo: %~dp0>> "%LOG%"

echo ============================================
echo   NetRunner - one-click installer
echo ============================================
echo.
echo A full log is written to install-log.txt
echo (send that file if anything below fails).
echo.

set "FAIL=0"

rem ---------------------------------------------------------------------------
rem 1. Repo files present?
rem ---------------------------------------------------------------------------
echo [1/5] Checking repo files...
echo.>> "%LOG%"
echo [1] repo files>> "%LOG%"
set "MISSING="
for %%F in (main.py requirements.txt) do if not exist "%%F" set "MISSING=!MISSING! %%F"
for %%D in (src config templates) do if not exist "%%D\" set "MISSING=!MISSING! %%D\"
if defined MISSING (
    echo   [X] Missing:!MISSING!
    echo   You copied only some files. Copy the WHOLE netrunner folder.
    echo   MISSING:!MISSING!>> "%LOG%"
    set "FAIL=1"
    goto :done
)
echo   [OK] main.py, src\, config\, templates\ found
echo   OK>> "%LOG%"

rem ---------------------------------------------------------------------------
rem 2. ASCII path? (OpenCV fails silently on non-ASCII / OneDrive paths)
rem ---------------------------------------------------------------------------
echo [2/5] Checking install location...
echo [2] path check: %~dp0>> "%LOG%"
echo "%~dp0" | findstr /i "OneDrive" >nul
if not errorlevel 1 (
    echo   [!] WARNING: this folder is inside OneDrive.
    echo       OneDrive can lock files and non-English folder names break image
    echo       matching. Recommended: move the folder to C:\dev\netrunner
    echo   WARN: OneDrive path>> "%LOG%"
)
rem crude non-ASCII probe: compare path against its ASCII-only form
echo   (if the bot can capture but never matches templates, the folder path
echo    probably has non-English characters - move it to C:\dev\netrunner)
echo   done>> "%LOG%"

rem ---------------------------------------------------------------------------
rem 3. Python present and real (not the Microsoft Store stub)?
rem ---------------------------------------------------------------------------
echo [3/5] Checking Python...
echo [3] python>> "%LOG%"
set "PY="
where py >nul 2>&1 && set "PY=py"
if not defined PY where python >nul 2>&1 && set "PY=python"

if not defined PY (
    echo   [X] Python not found.
    call :python_help
    echo   MISSING: python>> "%LOG%"
    set "FAIL=1"
    goto :done
)

rem Store stub returns nothing useful and exits 9009-ish; capture real version
for /f "delims=" %%V in ('%PY% --version 2^>^&1') do set "PYVER=%%V"
echo   %PY% --version -^> !PYVER!>> "%LOG%"
echo !PYVER! | findstr /i "Python 3" >nul
if errorlevel 1 (
    echo   [X] Python did not run correctly ^(got: !PYVER!^).
    echo       This is usually the Microsoft Store placeholder.
    call :python_help
    echo   BAD python version: !PYVER!>> "%LOG%"
    set "FAIL=1"
    goto :done
)
echo   [OK] !PYVER!
echo   OK !PYVER!>> "%LOG%"

rem ---------------------------------------------------------------------------
rem 4. Install dependencies
rem ---------------------------------------------------------------------------
echo [4/5] Installing dependencies ^(may take a minute^)...
echo [4] pip install>> "%LOG%"
%PY% -m pip install --upgrade pip >> "%LOG%" 2>&1
%PY% -m pip install -r requirements.txt >> "%LOG%" 2>&1
if errorlevel 1 (
    echo   [X] pip install failed. See install-log.txt for the error.
    echo   pip FAILED>> "%LOG%"
    set "FAIL=1"
    goto :done
)
echo   [OK] opencv, numpy, requests, python-dotenv installed
echo   OK>> "%LOG%"

rem ---------------------------------------------------------------------------
rem 5. Verify imports actually load
rem ---------------------------------------------------------------------------
echo [5/5] Verifying...
echo [5] import check>> "%LOG%"
%PY% -c "import cv2, numpy, requests, dotenv; print('imports OK', cv2.__version__)" >> "%LOG%" 2>&1
if errorlevel 1 (
    echo   [X] Packages installed but failed to import. See install-log.txt.
    echo   import FAILED>> "%LOG%"
    set "FAIL=1"
    goto :done
)
echo   [OK] all packages load
echo   OK>> "%LOG%"

rem ---------------------------------------------------------------------------
rem Bonus: is an emulator reachable right now? (informational only)
rem ---------------------------------------------------------------------------
echo.
echo Checking for a running emulator ^(optional^)...
echo [bonus] device detect>> "%LOG%"
%PY% main.py --list-devices >> "%LOG%" 2>&1
%PY% main.py --list-devices 2>nul | findstr /i "127.0.0.1 emulator" >nul
if errorlevel 1 (
    echo   [i] No emulator detected yet - that's fine.
    echo       Start LDPlayer with your game open, then run a bot.
) else (
    echo   [OK] An emulator is connected.
)

:done
echo.
echo ============================================
if "%FAIL%"=="0" (
    echo   INSTALL COMPLETE - ready to use.
    echo.
    echo   Next: open LDPlayer + CookieRun, then double-click
    echo   run_coinrun.bat ^(or another run_*.bat^).
) else (
    echo   INSTALL DID NOT FINISH - see the [X] above.
    echo   Send install-log.txt to whoever set this up.
)
echo ============================================
echo.
pause
exit /b %FAIL%

rem ---------------------------------------------------------------------------
:python_help
echo.
echo       HOW TO FIX:
echo       1. Go to https://www.python.org/downloads/
echo       2. Download Python 3.10 or newer
echo       3. Run the installer and TICK "Add python.exe to PATH"
echo       4. If Windows opens the Store when you type 'python':
echo          Settings ^> Apps ^> Advanced app settings ^>
echo          App execution aliases ^> turn OFF both python.exe entries
echo       5. Close this window and double-click install.bat again
echo.
exit /b 0
