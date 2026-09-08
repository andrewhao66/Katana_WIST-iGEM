#!/usr/bin/env python3
"""Check this parts library, and prove the checker actually works.

    python verify.py

No arguments, no setup, no dependencies beyond a standard Python 3.9+.

It does two things:

  1. Verifies every part in parts-library/ref_parts against LOCK.tsv — file hash,
     sequence hash, the hash embedded in the filename, and the manifest row.
  2. Runs the adversarial suite, which deliberately corrupts a scratch copy of the
     library eight ways and checks that each one is caught.

Step 2 matters more than step 1. Anyone can print "verified". The suite is the
evidence that the verifier would have told you if something were wrong.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIB = HERE / "parts-library" / "ref_parts"
LOCK = LIB / "LOCK.tsv"
VERIFIER = HERE / "verify_library_v2.py"
SUITE = HERE / "test_seal_gaps.py"

for _s in (sys.stdout, sys.stderr):
    try:
        if (_s.encoding or "").lower().replace("-", "") != "utf8":
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def run(script: Path, *args: str) -> tuple[int, str]:
    # Force the child to emit UTF-8. Piped Python defaults to the locale encoding
    # (cp1252 on Windows), so its em-dashes arrive as mojibake when decoded as UTF-8.
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, str(script), *args], env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    print("Katana parts library — integrity check\n" + "─" * 42)

    for p, what in ((LIB, "parts-library/ref_parts"), (LOCK, "LOCK.tsv"),
                    (VERIFIER, "verify_library_v2.py"), (SUITE, "test_seal_gaps.py")):
        if not p.exists():
            print(f"\nMissing: {what}\nRun this from the folder that contains it.")
            return 2

    n_parts = sum(1 for _ in LOCK.read_text(encoding="utf-8").splitlines()) - 1
    root = (LIB / "LOCK.root").read_text(encoding="utf-8").strip() if (LIB / "LOCK.root").exists() else "?"
    print(f"library : {n_parts} parts")
    print(f"root    : {root[:32]}…\n")

    print("1. Verifying every part against the manifest…")
    rc1, out1 = run(VERIFIER, str(LOCK))
    print("   " + (out1.strip().splitlines() or ["(no output)"])[-1])

    print("\n2. Trying to break the checker, eight ways…")
    rc2, out2 = run(SUITE, str(LIB))
    for line in out2.strip().splitlines():
        if line.startswith(("PASS", "FAIL")) or "checks passed" in line:
            print("   " + line)

    ok = rc1 == 0 and rc2 == 0
    print("\n" + "─" * 42)
    if ok:
        print("OK — the library is intact, and the checker catches tampering.")
        print("\nWhat this means: every sequence here matches the hash it was sealed")
        print("with, and each hash traces to a primary source recorded in LOCK.tsv.")
        print("Read that file to see where any part came from.")
    else:
        print("PROBLEM — see the output above.")
        print("\nA failure here is the tool working. Something does not match what it")
        print("was sealed as; do not use the affected part until you know why.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
