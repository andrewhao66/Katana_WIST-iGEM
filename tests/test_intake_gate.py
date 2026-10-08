"""test_intake_gate.py — adding a part must not re-seal a damaged library.

Run: python3 tests/test_intake_gate.py

Found by an independent Codex review, reproduced before being accepted.

`add_part.py` read the destination manifest and never checked it, then replaced both the
manifest and LOCK.root at the end. So if complete rows had been lost -- a truncated sync,
a partial copy, a disk that filled during a write -- admitting one more part re-sealed
whatever rows were LEFT under a fresh root.

The library then verifies clean forever afterwards, and the evidence that rows went
missing is destroyed by the act of adding to it. That is the fourth rule inverted: a
discrepancy must end the turn, and this one ended it by overwriting the thing that proved
there was a discrepancy.

Measured before the fix: a library with its last row removed accepted a new part and
wrote a new root over the mismatch. After: it refuses, quotes the root mismatch, and says
why adding now would be worse than not adding at all.

Also here: `kg_rebuild` treated exit code 5 as a build failure. 0 is PASS and 5 is REVIEW
-- both are completed builds with sealed outputs -- so rebuild reported `build-failed` for
a build that had succeeded and written its three order files. The engine's exit contract
gained REVIEW earlier in this branch and this consumer was not updated with it.
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  [" + str(detail)[:300] + "]") if detail else ""))


def add_part(lib, pid):
    p = subprocess.run([sys.executable, "add_part.py", "--library", lib,
                        "--id", pid, "--file",
                        os.path.join(ROOT, "kagami", "examples", "demo.gb"),
                        "--class", "designed"],
                       cwd=ROOT, capture_output=True, text=True, timeout=600)
    return p.returncode, p.stdout + p.stderr


def verify(lib):
    p = subprocess.run([sys.executable, "verify.py", lib], cwd=ROOT,
                       capture_output=True, text=True, timeout=900)
    return p.returncode, p.stdout + p.stderr


D = tempfile.mkdtemp(prefix="intake_")
print("intake gate")

# ---- an intact library still accepts a part ----
_ok_lib = os.path.join(D, "ok")
shutil.copytree(os.path.join(ROOT, "parts-library"), _ok_lib)
_n_before = len(open(os.path.join(_ok_lib, "ref_parts", "LOCK.tsv"),
                     encoding="utf-8").read().splitlines()) - 1

_rc, _out = add_part(_ok_lib, "TestPartOne")
check("an intact library accepts a new part", _rc == 0, (_out)[-250:])
_n_after = len(open(os.path.join(_ok_lib, "ref_parts", "LOCK.tsv"),
                    encoding="utf-8").read().splitlines()) - 1
check("and the manifest grew by one (%d -> %d)" % (_n_before, _n_after),
      _n_after == _n_before + 1)
_rc, _out = verify(_ok_lib)
check("and the library still verifies afterwards", _rc == 0, _out[-250:])
check("with the new count", "%d parts verified" % _n_after in _out, _out[-250:])

# ---- a library that has LOST a row must be refused ----
_bad = os.path.join(D, "bad")
shutil.copytree(os.path.join(ROOT, "parts-library"), _bad)
_lp = os.path.join(_bad, "ref_parts", "LOCK.tsv")
_rows = open(_lp, encoding="utf-8").read().splitlines()
with open(_lp, "w", encoding="utf-8") as _f:
    _f.write("\n".join(_rows[:-1]) + "\n")
_root_before = open(os.path.join(_bad, "ref_parts", "LOCK.root"),
                    encoding="utf-8").read().strip()

_rc, _out = add_part(_bad, "TestPartTwo")
check("a library with a row missing REFUSES a new part", _rc != 0, "exit %d" % _rc)
check("and quotes the root mismatch", "LOCK.root" in _out or "root" in _out,
      _out[-300:])
check("and says that adding now would destroy the evidence",
      "evidence" in _out.lower() or "re-seal" in _out.lower(), _out[-300:])

# The point of the fix: the root must be untouched.
_root_after = open(os.path.join(_bad, "ref_parts", "LOCK.root"),
                   encoding="utf-8").read().strip()
check("and LOCK.root is NOT rewritten", _root_after == _root_before,
      "%s -> %s" % (_root_before[:16], _root_after[:16]))
_rows_after = open(_lp, encoding="utf-8").read().splitlines()
check("and no row was added", len(_rows_after) == len(_rows) - 1,
      "%d -> %d" % (len(_rows) - 1, len(_rows_after)))
_rc, _out = verify(_bad)
check("so the damage is still visible afterwards", _rc != 0, "exit %d" % _rc)

# ---- a library with no root at all is a different case and proceeds ----
# katana_init writes a root, so this is a hand-made library with nothing to contradict.
_noroot = os.path.join(D, "noroot")
shutil.copytree(os.path.join(ROOT, "parts-library"), _noroot)
os.remove(os.path.join(_noroot, "ref_parts", "LOCK.root"))
_rc, _out = add_part(_noroot, "TestPartThree")
check("a library with no LOCK.root yet still accepts a part", _rc == 0, _out[-250:])
check("and gets one written", os.path.isfile(os.path.join(_noroot, "ref_parts",
                                                          "LOCK.root")))

# ---- rebuild must not read REVIEW as a failure ----
_src = open(os.path.join(ROOT, "kagami", "kg_rebuild.py"), encoding="utf-8").read()
check("rebuild accepts exit 5 (REVIEW) as a completed build",
      "returncode in (0, 5)" in _src,
      [l.strip() for l in _src.splitlines() if "returncode" in l][:2])
check("and still treats 1 as a refusal", "returncode in (0, 5)" in _src
      and "returncode == 0" not in _src)

# ---- and the off-target gate must classify every row, not the first forty ----
# The cap was a reporting limit that had silently become an enforcement limit: forty
# longer expected-locus hits can precede an unexpected 100-base 100%-identity match, and
# that blocking hit was never inspected, so sealing proceeded while the scan had already
# found it.
_dl = open(os.path.join(ROOT, "katana_drylab.py"), encoding="utf-8").read()
check("the off-target classification loop is not truncated",
      "rows[:40]" not in _dl,
      [l.strip() for l in _dl.splitlines() if "[:40]" in l][:2])
check("only the printing is capped", "_shown <= 40" in _dl)
check("and the number held back is stated",
      "further off-target" in _dl)

shutil.rmtree(D, ignore_errors=True)

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
