#!/bin/bash
# Kagami — reverse-Katana sequence auditor (macOS command-line wrapper).
# Usage from Terminal:  ./run_kagami.command mysequence.gb
# (Most students want the window instead: open run_kagami_gui.command.)
#
# Requires: Python 3.9+ and, for the full audit, NCBI BLAST+ (blastn, makeblastdb) on PATH.
# Works only from an EXTRACTED folder, not from inside a .zip.

cd "$(dirname "${0}")" || exit 1

if [ ! -f kagami.py ]; then
  echo
  echo "  Kagami's own files are not in this folder, so it cannot run."
  echo "  Unzip the download first, then run this from the extracted 'kagami' folder."
  echo
  exit 2
fi

PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo
  echo "  Python 3 was not found. Install it from https://www.python.org/downloads/ and try again."
  echo
  exit 2
fi

if [ -z "${1}" ]; then
  echo "Usage: ./run_kagami.command SEQUENCE.gb [--vendor Twist]"
  echo "  Produces a report next to the input file."
  exit 2
fi

INPUT="${1}"
STEM="${INPUT%.*}"

"$PY" kagami.py audit "$INPUT" --vendor Twist \
  --html "${STEM}_kagami_report.html" \
  --json "${STEM}_kagami.json" \
  --emit-spec "${STEM}_recovered.spec.yaml" \
  --emit-intake "${STEM}_intake.txt"

echo
echo "Report written next to the input file."
