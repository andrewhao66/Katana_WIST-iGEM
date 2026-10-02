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
REM
REM Windows ships a PLACEHOLDER python.exe in %LOCALAPPDATA%\Microsoft\WindowsApps (the "App
REM Execution Alias"). It is NOT Python: "where python" finds it, so a naive check thinks Python
REM is installed, but running it just opens the Microsoft Store and nothing else happens. That is
REM the most common reason this file appears to do nothing at all, so :findpy skips any candidate
REM living in WindowsApps and remembers that it saw one.
set "PY="
set "STUB="
for %%C in (pythonw pyw py python) do if not defined PY call :findpy %%C

if not defined PY (
  echo(
  if defined STUB (
    echo   The only "python" on this computer is the Microsoft Store placeholder, which is
    echo   not Python - running it just opens the Store. Real Python is not installed yet.
  ) else (
    echo   Python 3 was not found on this computer.
  )
  echo(
  where winget >nul 2>nul
  if errorlevel 1 goto :manual
  echo   Kagami needs Python, which is free. This window can install it for you now.
  echo   It takes a minute or two, needs no administrator rights, and asks nothing else.
  echo(
  choice /c YN /m "  Install Python now"
  if errorlevel 2 goto :manual
  echo(
  winget install --id Python.Python.3.12 -e --source winget --accept-package-agreements --accept-source-agreements
  REM The new Python is not on THIS window's PATH yet, so look where the installer puts it.
  call :findnew
  if not defined PY goto :manual
  echo(
  echo   Python is installed. Starting Kagami...
)

:run
start "" "%PY%" kagami_gui.py %*
goto :eof

:findpy
REM %1 = command to look for. Sets PY to the first hit that is NOT the Store placeholder.
for /f "delims=" %%P in ('where %1 2^>nul') do (
  set "CAND=%%~fP"
  call :checkcand
  if defined PY goto :eof
)
goto :eof

:checkcand
REM Deliberately no "find"/"findstr" here: on a machine with Git Bash (or any other POSIX
REM toolkit) earlier on PATH, "find" is GNU find, which fails on these arguments and would make
REM the test pass open - accepting the placeholder as if it were Python. This substring trick is
REM pure cmd: deleting \WindowsApps\ changes the string only if it was actually in it.
if /i "%CAND:\WindowsApps\=%"=="%CAND%" ( set "PY=%CAND%" ) else ( set "STUB=1" )
goto :eof

:manual
echo(
echo   To install Python yourself, copy the line below, paste it into Terminal or PowerShell,
echo   press Enter:
echo(
echo     winget install --id Python.Python.3.12 -e --source winget --accept-package-agreements --accept-source-agreements
echo(
echo   Then CLOSE that window, open a NEW one, and double-click this file again.
echo   No administrator rights are needed.
echo(
echo   If winget is blocked on your computer, install from https://www.python.org/downloads/
echo   and tick "Add Python to PATH" during setup.
echo(
pause
goto :eof

:findnew
for %%V in (313 312 311 310 39) do if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\pythonw.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python%%V\pythonw.exe"
goto :eof