#!/bin/bash
# Kagami in a window (macOS). Double-click this file in Finder to open the GUI.
#
# It only works from an EXTRACTED folder, not from inside a .zip. On a Mac, double-clicking the
# downloaded .zip already unpacks it into a folder next to it; open that folder, then open "kagami"
# and double-click this file.
#
# First-time Gatekeeper note: macOS may say this file "cannot be opened because it is from an
# unidentified developer." If so, either Right-click -> Open (then Open again), OR skip this file
# entirely and run  python3 kagami_gui.py  in Terminal from this folder. Both do the same thing.

cd "$(dirname "${0}")" || exit 1

if [ ! -f kagami_gui.py ]; then
  echo
  echo "  Kagami's own files are not in this folder, so it cannot start."
  echo "  This usually means it ran from inside the downloaded .zip. Unzip the .zip first,"
  echo "  open the extracted folder, go into the 'kagami' folder, and open this file there."
  echo
  read -n 1 -s -r -p "Press any key to close."
  exit 2
fi

# python3 is the macOS/Linux command (there is no bare 'python' on a modern Mac).
PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done

if [ -z "$PY" ]; then
  echo
  echo "  Python 3 was not found on this computer."
  echo
  echo "  To fix it, copy the line below, paste it into Terminal, and press Return. It"
  echo "  downloads the official installer and opens it; click through it, then open this"
  echo "  file again. No administrator password is needed to download it."
  echo
  echo "    curl -L -o ~/Downloads/python-3.12.10.pkg https://www.python.org/ftp/python/3.12.10/python-3.12.10-macos11.pkg && open ~/Downloads/python-3.12.10.pkg"
  echo
  read -n 1 -s -r -p "Press any key to close."
  exit 2
fi

exec "$PY" kagami_gui.py "$@"
