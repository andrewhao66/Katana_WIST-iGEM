@echo off
REM Kagami — reverse-Katana sequence auditor (Windows double-click wrapper).
REM Drag a .gb / .fasta onto this file, or:  run_kagami.bat mysequence.gb
REM Requires: Python 3.9+ and NCBI BLAST+ (blastn, makeblastdb) on PATH.
setlocal
cd /d "%~dp0"

if "%~1"=="" (
  echo Usage: run_kagami.bat SEQUENCE.gb [--vendor Twist] [--host GENOME.fna]
  echo   Produces a report next to the input.
  pause
  exit /b 2
)

set "INPUT=%~1"
set "STEM=%~dpn1"

python kagami.py audit "%INPUT%" --vendor Twist ^
  --html "%STEM%_kagami_report.html" ^
  --json "%STEM%_kagami.json" ^
  --emit-spec "%STEM%_recovered.spec.yaml" ^
  --emit-intake "%STEM%_intake.txt"

echo.
echo Report written next to the input file.
pause
