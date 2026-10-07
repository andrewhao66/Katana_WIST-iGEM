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

REM Windows ships a PLACEHOLDER python.exe that opens the Microsoft Store instead of
REM running anything. `py` is the real launcher when Python is properly installed.
where /q py.exe && (py ui_menu.py %* & goto :done)
where /q python.exe && (python ui_menu.py %* & goto :done)
echo(
echo   Python 3 was not found. Install it from https://www.python.org/downloads/
echo   and tick "Add python.exe to PATH" in the installer, then run this again.
echo(
pause
exit /b 2

:done
REM Hand the tool's own exit code back. cmd usually preserves ERRORLEVEL across
REM goto and endlocal, but "usually" is not a guarantee, and the whole verdict
REM model rests on it: 0 means PASS, 5 means REVIEW, 1 means FAIL. A wrapper that
REM loses that turns every verdict into success for anything that checks.
set RC=%ERRORLEVEL%
endlocal & exit /b %RC%
