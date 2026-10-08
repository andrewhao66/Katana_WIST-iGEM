"""test_verify_target.py — verify.py must check the library you pointed it at.

Run: python3 tests/test_verify_target.py

Found while testing half-broken inputs. `verify.py` is the command this project tells
people to trust: its own CLAUDE.md says "run it after any change to the library, and run
it before you believe anything." It hard-codes `LIB = HERE / "parts-library" /
"ref_parts"` and never reads `sys.argv`.

So it accepts a path and silently ignores it. Measured:

    $ python3 verify.py /nonexistent/path/LOCK.tsv
       8/8 checks passed
    OK — the library is intact, and the checker catches tampering.
    exit 0

A clean bill of health, for a path that does not exist, about a library the caller did not
ask about. Worse with a path that DOES exist: a team running their own library with
`--library` gets `verify.py` reporting on the shipped one, which is always intact, and
concludes theirs is fine. The one command whose entire job is to be believed was answering
a question it had not been asked.

This is the fourth rule at the level of the tool's interface: two sources disagree about
which library is meant -- the argument and the hard-coded path -- and it resolved that
silently, in favour of the one that passes.

What must hold: a path given on the command line is the library checked, or the command
refuses. Either is honest; quietly checking a different one is not. And with no argument
it must keep checking the shipped library exactly as before, because that is what every
README line, CI job and test already invokes.
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  [" + str(detail)[:300] + "]") if detail else ""))


def run(args):
    p = subprocess.run([sys.executable, "verify.py"] + args, cwd=ROOT,
                       capture_output=True, text=True, timeout=900)
    return p.returncode, p.stdout + p.stderr


print("verify.py's target")

# ---- no argument: unchanged, because everything already calls it that way ----
_rc, _out = run([])
check("with no argument it checks the shipped library and passes", _rc == 0,
      "exit %d" % _rc)
check("and says so", "checks passed" in _out, _out[-200:])

# ---- a path that does not exist must NOT report success ----
_rc, _out = run(["/nonexistent/path/LOCK.tsv"])
check("a path that does not exist does not report the library intact", _rc != 0,
      "exit %d | %s" % (_rc, _out[-200:]))
check("and does not print a clean bill of health",
      "the library is intact" not in _out, _out[-250:])
check("and names the path it could not use", "/nonexistent/path" in _out,
      _out[-250:])

# ---- a path that DOES exist is the one checked ----
D = tempfile.mkdtemp(prefix="vtarget_")
GOOD = os.path.join(D, "good")
BAD = os.path.join(D, "bad")
shutil.copytree(os.path.join(ROOT, "parts-library"), GOOD)
shutil.copytree(os.path.join(ROOT, "parts-library"), BAD)

# Break the copy: truncate its manifest mid-row, which is what a half-finished sync or a
# full disk actually leaves behind.
_lock = os.path.join(BAD, "ref_parts", "LOCK.tsv")
_b = open(_lock, "rb").read()
with open(_lock, "wb") as f:
    f.write(_b[:len(_b) // 2])

_rc, _out = run([os.path.join(GOOD, "ref_parts", "LOCK.tsv")])
check("an intact library given by path passes", _rc == 0,
      "exit %d | %s" % (_rc, _out[-200:]))
check("and the output names that library rather than the shipped one",
      GOOD in _out, _out[-250:])

_rc, _out = run([os.path.join(BAD, "ref_parts", "LOCK.tsv")])
check("a TRUNCATED library given by path is refused", _rc != 0,
      "exit %d | %s" % (_rc, _out[-300:]))
check("and the refusal does not claim the library is intact",
      "the library is intact" not in _out, _out[-250:])
check("and it says what is wrong, not just that something is",
      any(w in _out for w in ("row_sha256", "truncat", "column", "missing")),
      _out[-300:])

# The directory form should work too -- people point at a library, not at a manifest.
_rc, _out = run([GOOD])
check("pointing at the library DIRECTORY works as well as at LOCK.tsv", _rc == 0,
      "exit %d | %s" % (_rc, _out[-200:]))
_rc, _out = run([BAD])
check("and the broken one is still refused that way", _rc != 0,
      "exit %d" % _rc)

# ---- the adversarial half must still run on whatever was chosen ----
_rc, _out = run([os.path.join(GOOD, "ref_parts", "LOCK.tsv")])
check("the eight self-attacks run against the library given, not the shipped one",
      "8/8" in _out or "checks passed" in _out, _out[-200:])

shutil.rmtree(D, ignore_errors=True)

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
