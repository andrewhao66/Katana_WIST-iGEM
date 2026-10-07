@echo off
REM Kagami — reverse-Katana sequence auditor (Windows double-click wrapper).
REM Drag a .gb / .fasta onto this file, or:  run_kagami.bat mysequence.gb
REM Requires: Python 3.9+. Nothing else -- identification is pure Python.
REM
REM It only works from an EXTRACTED folder, not from inside a .zip (the check below explains).
setlocal
cd /d "%~dp0"

if not exist "kagami.py" (
  echo(
  echo   Kagami's own files are not in this folder, so it cannot run.
  echo   You probably ran this from INSIDE the downloaded .zip. Right-click the .zip,
  echo   choose "Extract All...", then run this from the extracted "kagami" folder.
  echo(
  pause
  exit /b 2
)

REM Windows ships a PLACEHOLDER python.exe in %LOCALAPPDATA%\Microsoft\WindowsApps (the "App
REM Execution Alias"). It is NOT Python: "where python" finds it, so a naive check thinks Python is
REM installed, but running it just opens the Microsoft Store. :findpy skips any candidate living in
REM WindowsApps and remembers that it saw one, so the message below can name the real problem.
set "PY="
set "STUB="
for %%C in (python py) do if not defined PY call :findpy %%C

if not defined PY (
  echo(
  if defined STUB (
    echo   The only "python" on this computer is the Microsoft Store placeholder, which is
    echo   not Python - running it just opens the Store. Real Python is not installed yet.
  ) else (
    echo   Python 3 was not found on this computer.
  )
  echo(
  echo   To fix it, copy the line below, paste it into Terminal or PowerShell, press Enter:
  echo(
  echo     winget install --id Python.Python.3.12 -e --source winget --accept-package-agreements --accept-source-agreements
  echo(
  echo   Then CLOSE that window, open a NEW one, and run this file again.
  echo   No administrator rights are needed.
  echo(
  echo   If winget is blocked on your computer, install from https://www.python.org/downloads/
  echo   and tick "Add Python to PATH" during setup.
  echo(
  pause
  exit /b 2
)

if "%~1"=="" (
  echo Usage: run_kagami.bat SEQUENCE.gb [--vendor Twist] [--host GENOME.fna]
  echo   Produces a report next to the input.
  pause
  exit /b 2
)

set "INPUT=%~1"
set "STEM=%~dpn1"

"%PY%" kagami.py audit "%INPUT%" --vendor Twist ^
  --html "%STEM%_kagami_report.html" ^
  --json "%STEM%_kagami.json" ^
  --emit-spec "%STEM%_recovered.spec.yaml" ^
  --emit-intake "%STEM%_intake.txt"

echo.
echo Report written next to the input file.
pause
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
