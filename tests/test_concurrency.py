"""test_concurrency.py — two builds at once must not produce a wrong answer.

Run: python3 tests/test_concurrency.py

Found by looking for latent failures rather than present ones. An earlier ruling said
concurrent builds in one process would interfere and that nothing does it — the GUI runs
one build at a time in one worker thread, and Pyodide is single-threaded. That was true of
the shipped front ends and false as an argument for leaving it, because `build()` is a
library function: a server, a batch script or a CI harness can call it from two threads,
and the failure is silent.

Measured, ten pairs of threads building the same spec against two different libraries, one
of them deliberately missing sfGFP so it MUST fail:

    round 0: A verdict=FAIL   <- the COMPLETE library failed
    round 5: B verdict=REVIEW <- the INCOMPLETE library came back near-clean
    ... 10 of 10 rounds wrong, in both directions

The second line is the cardinal failure of this whole project: a construct the engine
could not assemble, reported as clean. Plus `sys.stdout` was left pointing at an abandoned
buffer in 10 of 10 rounds — so every `print` in the process afterwards vanished, including
the test's own — and `res.log` came back empty most of the time.

Two causes, both process-global state that `build()` rebinds:

  * LIB / LOCK_PATH / LOCK_ROOT_PATH, so each build can read the other's library.
  * `sys.stdout`, which `build()` replaces to capture its own log.

The fix is a lock, not thread-safety. Threading the library through every stage would
touch resolve_parts and the GenBank reader for no behavioural gain, and `sys.stdout` is
process-global whatever you do. Serialising means the worst case is that one build waits;
the alternative is a wrong answer that looks right, and for this tool that trade is not
close.
"""
import os
import shutil
import sys
import threading
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import katana_build

SPEC = os.path.join(ROOT, "specs", "pSense-Nit.spec.yaml")
# build() captures stdout by rebinding it, and under the very defect this suite measures
# it leaves stdout pointing somewhere else -- so the diagnostics go to a file descriptor
# duplicated before any of that, which nothing in the engine can reach.
ERR = os.fdopen(os.dup(2), "w", buffering=1)

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   " + name, file=ERR)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  [" + str(detail)[:300] + "]") if detail else ""),
              file=ERR)


print("concurrency", file=ERR)

# ---- two libraries, one of them unable to build the spec ----
D = tempfile.mkdtemp(prefix="conc_")
LIB_OK = os.path.join(D, "libA")
LIB_BAD = os.path.join(D, "libB")
shutil.copytree(os.path.join(ROOT, "parts-library"), LIB_OK)
shutil.copytree(os.path.join(ROOT, "parts-library"), LIB_BAD)

_lock_path = os.path.join(LIB_BAD, "ref_parts", "LOCK.tsv")
_rows = open(_lock_path, encoding="utf-8").read().splitlines()
_kept = [r for r in _rows[1:] if r.split("\t")[0] != "sfGFP"]
check("the spec's sfGFP row exists to remove", len(_kept) == len(_rows) - 2,
      "%d -> %d" % (len(_rows) - 1, len(_kept)))
with open(_lock_path, "w", encoding="utf-8") as f:
    f.write("\n".join([_rows[0]] + _kept) + "\n")
import glob

for _f in glob.glob(os.path.join(LIB_BAD, "ref_parts", "sfGFP__*")):
    os.remove(_f)

# The detector must work before it can detect anything.
_a = katana_build.build(SPEC, library=LIB_OK, dry_run=True)
_b = katana_build.build(SPEC, library=LIB_BAD, dry_run=True)
check("the complete library builds on its own (%s)" % _a.verdict,
      _a.verdict == "REVIEW", _a.verdict)
check("and the incomplete one refuses on its own (%s)" % _b.verdict,
      _b.verdict == "FAIL", "%s / blocked %s" % (_b.verdict, _b.blocked_stage()))

# ---- and now both at once, repeatedly ----
_real_stdout = sys.stdout
_rounds = 10
_wrong = []
_stdout_lost = 0
_log_empty = 0

for _i in range(_rounds):
    _out = {}

    def _run(tag, lib):
        try:
            r = katana_build.build(SPEC, library=lib, dry_run=True)
            _out[tag] = (r.verdict, str(r.library), len(r.log or ""))
        except BaseException as exc:          # noqa: BLE001 - a refusal is BaseException
            _out[tag] = ("EXC:" + type(exc).__name__, "", 0)

    _t1 = threading.Thread(target=_run, args=("A", LIB_OK))
    _t2 = threading.Thread(target=_run, args=("B", LIB_BAD))
    _t1.start()
    _t2.start()
    _t1.join()
    _t2.join()

    _va, _la, _loga = _out.get("A", ("?", "", 0))
    _vb, _lb, _logb = _out.get("B", ("?", "", 0))
    _why = []
    if _va != "REVIEW":
        _why.append("complete library reported %s" % _va)
    if _vb != "FAIL":
        _why.append("INCOMPLETE library reported %s" % _vb)
    if "libA" not in _la:
        _why.append("A recorded %s" % _la)
    if "libB" not in _lb:
        _why.append("B recorded %s" % _lb)
    if _why:
        _wrong.append((_i, "; ".join(_why)))
    if sys.stdout is not _real_stdout:
        _stdout_lost += 1
        sys.stdout = _real_stdout            # put it back so the next round is measurable
    if _loga == 0:
        _log_empty += 1

check("no round produced a wrong verdict (%d of %d wrong)" % (len(_wrong), _rounds),
      not _wrong, "; ".join("round %d: %s" % w for w in _wrong[:3]))
check("in particular, an incomplete library is never reported as near-clean",
      not [w for w in _wrong if "INCOMPLETE" in w[1]],
      "; ".join(w[1] for w in _wrong if "INCOMPLETE" in w[1])[:200])
check("sys.stdout is restored every time (%d of %d lost)" % (_stdout_lost, _rounds),
      _stdout_lost == 0, _stdout_lost)
check("and each build captures its own log (%d of %d empty)" % (_log_empty, _rounds),
      _log_empty == 0, _log_empty)

# ---- a single build must still behave exactly as before ----
sys.stdout = _real_stdout
_r = katana_build.build(SPEC, library=LIB_OK, dry_run=True)
check("a single build still works", _r.verdict == "REVIEW", _r.verdict)
check("and still captures its log", len(_r.log or "") > 100, len(_r.log or ""))
check("and still records the library it used", "libA" in str(_r.library), _r.library)
check("and sys.stdout survives it", sys.stdout is _real_stdout)

# ---- nested calls must not deadlock ----
# Nothing does this today, but a lock that deadlocks on re-entry is a worse failure than
# the one it replaces: the process stops with no message at all.
_nested = {}


def _outer():
    try:
        _nested["inner"] = katana_build.build(SPEC, library=LIB_OK,
                                              dry_run=True).verdict
        _nested["ok"] = True
    except BaseException as exc:             # noqa: BLE001
        _nested["ok"] = False
        _nested["exc"] = type(exc).__name__


_t = threading.Thread(target=_outer)
_t.start()
_t.join(timeout=300)
check("a build from a worker thread completes rather than hanging",
      not _t.is_alive() and _nested.get("ok"),
      "alive=%s %s" % (_t.is_alive(), _nested))

shutil.rmtree(D, ignore_errors=True)

print("\n%d passed, %d failed" % (PASS, FAIL), file=ERR)
sys.exit(1 if FAIL else 0)
