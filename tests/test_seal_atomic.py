"""test_seal_atomic.py — a build that fails must leave no order files behind.

Run: python3 tests/test_seal_atomic.py

Found by making Stage 5 fail on its THIRD file instead of its first.

Stage 5 writes three things: the GenBank, the vendor FASTA, and the order CSV. They were
written straight into the output directory one after another, so a failure on the last one
left the first two sitting there:

    exit 1
    BLOCK Stage-5: order table not written (IsADirectoryError(21, 'Is a directory'))

    pSense-Nit_insert_v2_TWIST.fasta   1083 bytes
    pSense-Nit_insert_v2_2026-10-07.gb 2596 bytes

The build refused, correctly and with a usable reason. And it left an order-ready FASTA
from a build that failed — the exact file you paste into a vendor's order form. A student
who fixes the error and re-runs is fine; one who glances at the folder, sees a .fasta with
today's date in it and orders from it, is not. Disk full and a wrong permission are the
ordinary ways this happens, and neither announces itself.

"Seal" in this project means the artifact and its hash agree and were recorded together.
Two of three files is not a seal; it is a set of files with no complete record, and it
looks exactly like a successful build from the outside.

What must hold: Stage 5 is all or nothing. Every file is written somewhere else first and
moved into place only once all of them exist, so a failure leaves the output directory
exactly as it was. And the ordinary case -- a directory you cannot write to -- gets a
sentence rather than a Python traceback, because `PermissionError: [Errno 13]` over a
stack trace is where somebody who is not a programmer stops.
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

SPEC = os.path.join(ROOT, "specs", "pSense-Nit.spec.yaml")

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  [" + str(detail)[:300] + "]") if detail else ""))


def build(outdir):
    p = subprocess.run([sys.executable, "katana_build.py", SPEC, "--outdir", outdir],
                       cwd=ROOT, capture_output=True, text=True, timeout=900)
    return p.returncode, p.stdout + p.stderr


def files_in(d):
    if not os.path.isdir(d):
        return []
    return sorted(f for f in os.listdir(d)
                  if os.path.isfile(os.path.join(d, f)))


print("Stage 5 is all or nothing")

D = tempfile.mkdtemp(prefix="atomic_")

# ---- the happy path first, or nothing below means anything ----
_ok = os.path.join(D, "ok")
_rc, _out = build(_ok)
check("a normal build succeeds", _rc in (0, 5), "exit %d | %s" % (_rc, _out[-200:]))
_f = files_in(_ok)
check("and writes all three order files (%d)" % len(_f), len(_f) == 3, str(_f))
check("including the vendor FASTA", any(x.endswith("TWIST.fasta") for x in _f), str(_f))

# ---- failing on the LAST file must leave nothing ----
# A directory where the CSV belongs: opening it as a file cannot succeed, deterministically,
# and it happens after the GenBank and the FASTA have been written.
_mid = os.path.join(D, "mid")
os.makedirs(_mid)
os.makedirs(os.path.join(_mid, "pSense-Nit_insert_v2_ORDER.csv"))
_rc, _out = build(_mid)
check("a build that fails on its last output refuses", _rc != 0, "exit %d" % _rc)
check("and says what went wrong", "Stage-5" in _out or "order table" in _out,
      _out[-250:])
_left = files_in(_mid)
check("and leaves NO order files behind (%s)" % (", ".join(_left) or "none"),
      not _left, str(_left))
check("in particular no vendor FASTA from a failed build",
      not [x for x in _left if x.endswith(".fasta")], str(_left))

# ---- failing on the FIRST file must also leave nothing, and say so in words ----
_ro = os.path.join(D, "ro")
os.makedirs(_ro)
os.chmod(_ro, 0o555)
try:
    _rc, _out = build(_ro)
    check("a build into a read-only directory refuses", _rc != 0, "exit %d" % _rc)
    check("and leaves it empty", not files_in(_ro), str(files_in(_ro)))
    check("and explains it in a sentence rather than a traceback",
          "Traceback" not in _out, _out[-300:])
    check("and names the directory it could not write to", _ro in _out, _out[-300:])
    check("and says what to do about it",
          any(w in _out.lower() for w in ("writable", "permission", "another folder",
                                          "--outdir")),
          _out[-300:])
finally:
    os.chmod(_ro, 0o755)

# ---- a re-run after a failure must still work, and not trip over leftovers ----
shutil.rmtree(os.path.join(_mid, "pSense-Nit_insert_v2_ORDER.csv"),
              ignore_errors=True)
_rc, _out = build(_mid)
check("and a re-run once the obstruction is gone succeeds", _rc in (0, 5),
      "exit %d | %s" % (_rc, _out[-200:]))
check("writing all three files", len(files_in(_mid)) == 3, str(files_in(_mid)))

# ---- and rebuilding over an existing complete output must still replace it ----
_before = {f: os.path.getsize(os.path.join(_mid, f)) for f in files_in(_mid)}
_rc, _out = build(_mid)
check("building twice into the same directory works", _rc in (0, 5), "exit %d" % _rc)
check("and still leaves exactly three files", len(files_in(_mid)) == 3,
      str(files_in(_mid)))
_after = {f: os.path.getsize(os.path.join(_mid, f)) for f in files_in(_mid)}
check("with the same contents, since the build is deterministic",
      _before == _after, "%s vs %s" % (_before, _after))

# ---- nothing may be left lying around by a SUCCESSFUL build either ----
check("a successful build leaves no temporary directory behind",
      not [d for d in os.listdir(_mid)
           if os.path.isdir(os.path.join(_mid, d))],
      str([d for d in os.listdir(_mid) if os.path.isdir(os.path.join(_mid, d))]))

shutil.rmtree(D, ignore_errors=True)

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
