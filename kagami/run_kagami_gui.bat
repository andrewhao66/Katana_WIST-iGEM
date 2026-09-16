@echo off
REM Kagami in a window. Double-click this file. You can also drag a sequence file onto it.
REM
REM It only works from an EXTRACTED folder, not from inside a .zip: double-clicking it while it
REM is still inside the downloaded zip makes Windows unpack ONLY this one file to a temp folder,
REM so the rest of Kagami is not there and nothing happens. The check below catches exactly that.
setlocal
cd /d "%~dp0"

if not exist "kagami_gui.py" (
  echo(
  echo   Kagami's own files are not in this folder, so it cannot start.
  echo(
  echo   This almost always means you ran it from INSIDE the downloaded .zip. Windows only
  echo   unpacked this one file. To fix it:
  echo     1^) Right-click the .zip and choose "Extract All..."
  echo     2^) Open the extracted folder and go into the "kagami" folder
  echo     3^) Double-click run_kagami_gui.bat in there
  echo(
  pause
  goto :eof
)

REM Find a Python. pythonw / pyw give a clean window with no console behind it; py / python
REM still work but leave a console open. If none is found, say so instead of failing silently.
set "PY="
where pythonw >nul 2>&1 && set "PY=pythonw"
if not defined PY ( where pyw    >nul 2>&1 && set "PY=pyw" )
if not defined PY ( where py     >nul 2>&1 && set "PY=py" )
if not defined PY ( where python >nul 2>&1 && set "PY=python" )

if not defined PY (
  echo(
  echo   Python 3 was not found on this computer.
  echo   Install it from https://www.python.org/downloads/ , tick "Add Python to PATH"
  echo   during setup, then double-click this file again.
  echo(
  pause
  goto :eof
)

start "" %PY% kagami_gui.py %*
