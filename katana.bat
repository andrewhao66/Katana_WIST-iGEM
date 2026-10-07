@echo off
REM Katana - one command for everything.
REM
REM   katana                       ask me what I want to do
REM   katana check my.gb           is this sequence what its labels say?
REM   katana build my.spec.yaml    Design Spec -> order-ready sequence
REM   katana verify                check the parts library
REM
REM Nothing needs installing beyond Python 3.9 or newer. No pip, no NCBI BLAST+.
setlocal
cd /d "%~dp0"

if not exist "ui_menu.py" (
  echo(
  echo   Katana's own files are not in this folder, so it cannot run.
  echo   You probably ran this from INSIDE the downloaded .zip. Right-click the .zip,
  echo   choose "Extract All...", then run this from the extracted folder.
  echo(
  pause
  exit /b 2
)

REM Was this double-clicked? When cmd is started by Explorer it is invoked as
REM   cmd /c ""C:\path\katana.bat" "
REM so this file's name appears in %cmdcmdline%. Run from a terminal, it does not.
REM The difference matters at the end: a double-clicked window must be held open or the
REM report scrolls past and vanishes, and a terminal run must NOT pause or
REM `katana.bat check my.gb` in a script waits forever for a keypress.
set KATANA_HOLD=
echo %cmdcmdline% | find /i "%~nx0" >nul 2>&1 && set KATANA_HOLD=1

REM Windows ships a PLACEHOLDER python.exe -- an App Execution Alias that opens the
REM Microsoft Store instead of running anything -- and `where` finds it happily. So each
REM candidate is PROBED: it has to actually execute Python before it is used. Without
REM this, a student with the placeholder and no real Python got the Store page, no
REM explanation, and a script that carried on as though Python had run.
REM `py` first: it is the real launcher when Python is properly installed.
set KATANA_PY=
py -c "import sys" >nul 2>&1 && set KATANA_PY=py
if not defined KATANA_PY (
  python3 -c "import sys" >nul 2>&1 && set KATANA_PY=python3
)
if not defined KATANA_PY (
  python -c "import sys" >nul 2>&1 && set KATANA_PY=python
)

if not defined KATANA_PY (
  echo(
  echo   Python 3 was not found on this computer.
  echo(
  echo   Install it from  https://www.python.org/downloads/
  echo   and tick "Add python.exe to PATH" in the installer, then run this again.
  echo(
  echo   If a Microsoft Store page opened when you tried `python`, that is a
  echo   placeholder, not Python. The installer above is the real thing.
  echo(
  pause
  exit /b 2
)

REM ui_menu.py checks the version itself and says so clearly; a .bat file cannot.
%KATANA_PY% ui_menu.py %*

REM Hand the tool's own exit code back. The whole verdict model rests on it: 0 means
REM PASS, 5 means REVIEW, 1 means FAIL. A wrapper that loses it turns every verdict into
REM success for anything that checks.
set RC=%ERRORLEVEL%
if defined KATANA_HOLD (
  echo(
  echo   Finished. Press any key to close this window.
  pause >nul
)
endlocal & exit /b %RC%
