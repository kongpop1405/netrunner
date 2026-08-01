@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem numpy 2.x's bundled OpenBLAS can fail to allocate its thread-pool memory
rem on some machines ("Memory allocation still failed after 10 retries") the
rem moment numpy is imported, well before any real work happens. Capping the
rem thread pool to 1 avoids that allocation entirely; matchTemplate calls are
rem tiny single-frame ops so this costs no meaningful speed.
set "OPENBLAS_NUM_THREADS=1"
set "OMP_NUM_THREADS=1"

set "LOG=%~dp0install-log.txt"
echo NetRunner install log  %DATE% %TIME%> "%LOG%"
echo repo: %~dp0>> "%LOG%"

echo ============================================
echo   NetRunner - one-click installer
echo ============================================
echo.
echo This installs everything you need - including Python if it's
echo missing. A full log is written to install-log.txt
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

rem Try candidates in order; accept the first that prints a real "Python 3.x".
rem A Microsoft Store stub is on PATH as py/python but prints nothing, so we
rem verify the version string rather than trusting `where`.
call :locate_python
if not defined PY (
    echo   Python not found - downloading and installing it now...
    echo   [3] python not found, attempting auto-install>> "%LOG%"
    call :auto_install_python
    call :locate_python
)

if not defined PY (
    echo   [X] Could not install Python automatically.
    call :python_help
    echo   AUTO-INSTALL FAILED; last version string: [!PYVER!]>> "%LOG%"
    echo   FIX: install from python.org, tick "Add python.exe to PATH",>> "%LOG%"
    echo        disable Store aliases, re-run install.bat>> "%LOG%"
    set "FAIL=1"
    goto :done
)
echo   [OK] !PYVER!  ^(!PY!^)
echo   OK !PYVER! via !PY!>> "%LOG%"

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
    echo   IMPORTANT: set the LDPlayer instance to 1920x1080 or the bot
    echo   will not recognize the game. See docs\PLAY_SETUP.md.
    echo.
    echo   Next: open LDPlayer + CookieRun on the home screen, then
    echo   double-click coinrun.bat ^(or another run_*.bat^).
) else (
    echo   INSTALL DID NOT FINISH - see the [X] above.
    echo   Send install-log.txt to whoever set this up.
)
echo ============================================
echo.
pause
exit /b %FAIL%

rem ---------------------------------------------------------------------------
rem Find a real Python: try py/python on PATH, then common install dirs.
:locate_python
set "PY="
set "PYVER="
for %%C in ("py" "python") do call :try_python %%~C
if not defined PY (
    for /d %%D in ("%LocalAppData%\Programs\Python\Python3*") do call :try_python "%%D\python.exe"
    for /d %%D in ("C:\Python3*") do call :try_python "%%D\python.exe"
    for /d %%D in ("%ProgramFiles%\Python3*") do call :try_python "%%D\python.exe"
)
exit /b 0

rem ---------------------------------------------------------------------------
rem Probe one python candidate; on success set PY + PYVER. No-op if PY already set.
:try_python
if defined PY exit /b 0
set "CAND=%~1"
set "V="
for /f "delims=" %%V in ('"%CAND%" --version 2^>^&1') do set "V=%%V"
echo   try %CAND% -^> [!V!]>> "%LOG%"
echo !V! | findstr /i "Python 3" >nul
if errorlevel 1 exit /b 0
set "PY=%CAND%"
set "PYVER=!V!"
exit /b 0

rem ---------------------------------------------------------------------------
rem Download + install Python unattended. Tries winget first (built into Win 10/11),
rem then falls back to fetching the official installer and running it silently.
:auto_install_python
where winget >nul 2>&1
if not errorlevel 1 (
    echo   Using winget ^(this can take a few minutes^)...
    echo   winget install Python.Python.3.12>> "%LOG%"
    winget install --id Python.Python.3.12 -e --source winget ^
        --accept-package-agreements --accept-source-agreements ^
        --silent --scope user >> "%LOG%" 2>&1
    call :refresh_path
    call :locate_python
    if defined PY exit /b 0
    echo   winget did not yield a working Python; trying direct download...>> "%LOG%"
)

rem --- fallback: download the official installer with PowerShell ---
set "PYURL=https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe"
set "PYEXE=%TEMP%\python-netrunner-setup.exe"
echo   Downloading %PYURL%...
echo   download %PYURL%>> "%LOG%"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "try { Invoke-WebRequest -Uri '%PYURL%' -OutFile '%PYEXE%' -UseBasicParsing } catch { exit 1 }" >> "%LOG%" 2>&1
if errorlevel 1 (
    echo   [X] Download failed ^(no internet?^).>> "%LOG%"
    exit /b 1
)
echo   Installing Python ^(silent, per-user, adding to PATH^)...
echo   run installer silent>> "%LOG%"
"%PYEXE%" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_pip=1 >> "%LOG%" 2>&1
del "%PYEXE%" >nul 2>&1
call :refresh_path
exit /b 0

rem ---------------------------------------------------------------------------
rem Re-read PATH from the registry so a just-installed Python is visible without
rem reopening the terminal.
:refresh_path
for /f "tokens=2,*" %%A in ('reg query "HKCU\Environment" /v PATH 2^>nul ^| findstr /i "PATH"') do set "USERPATH=%%B"
for /f "tokens=2,*" %%A in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v PATH 2^>nul ^| findstr /i "PATH"') do set "SYSPATH=%%B"
set "PATH=%SYSPATH%;%USERPATH%"
exit /b 0

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
