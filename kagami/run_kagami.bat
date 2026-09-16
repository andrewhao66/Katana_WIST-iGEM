@echo off
REM Kagami — reverse-Katana sequence auditor (Windows double-click wrapper).
REM Drag a .gb / .fasta onto this file, or:  run_kagami.bat mysequence.gb
REM Requires: Python 3.9+ and NCBI BLAST+ (blastn, makeblastdb) on PATH.
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

set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY ( where py >nul 2>&1 && set "PY=py" )
if not defined PY (
  echo(
  echo   Python 3 was not found on this computer. Install it from
  echo   https://www.python.org/downloads/ , tick "Add Python to PATH", then try again.
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

%PY% kagami.py audit "%INPUT%" --vendor Twist ^
  --html "%STEM%_kagami_report.html" ^
  --json "%STEM%_kagami.json" ^
  --emit-spec "%STEM%_recovered.spec.yaml" ^
  --emit-intake "%STEM%_intake.txt"

echo.
echo Report written next to the input file.
pause
