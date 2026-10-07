"""test_build_api.py — the structured build API must not report success for a refusal.

Run: python3 tests/test_build_api.py

Three defects found by an independent Codex review of the branch, reproduced here before
being accepted and fixed. All three share one shape: a refusal that a caller cannot see.

1. `build(library=...)` was IGNORED. The pipeline read the module-level LIB that was
   resolved at import, so build(spec, library="/definitely/nonexistent") assembled 1,013
   bases from the shipped library, reported PASS, and recorded "/definitely/nonexistent"
   as the library it used. The GUI passes the user's chosen parts library through exactly
   this argument -- so someone could select their own library, get a construct built from
   a different one, and be told it passed. That is the name and the fact drifting apart,
   at the point where the whole project says it must not.

2. `python3 katana_build.py --json` EXITED 0 ON A FAIL. `main()` returned the right code
   and `if __name__ == "__main__": main()` threw it away. The JSON said
   verdict FAIL, exit_code 1, and the process exited 0. --json is the machine-readable
   path -- the one a script or CI uses -- so a LOCK.root mismatch, the single most
   important block in the system, reported success to anything that checks.

3. `write_text(..., newline=)` is PYTHON 3.10+. On the 3.9 that macOS ships with the
   Xcode command line tools, a real build raised TypeError at the sealing step. The
   README promises 3.9. tests/test_py39.py did not catch it because it only ran
   --dry-run, which never reaches the write -- a hole in the test, not just in the code.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

SPEC = os.path.join(ROOT, "specs", "pSense-Nit.spec.yaml")
WRONG_ROOT = "0" * 64

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  [" + str(detail)[:300] + "]") if detail else ""))


def run(args, py=None):
    return subprocess.run([py or sys.executable, "katana_build.py"] + args,
                          cwd=ROOT, capture_output=True, text=True, timeout=600)


print("the structured build API")

# ---- 1. a library that is not there must not build a PASS ----
import katana_build

res = katana_build.build(SPEC, library="/definitely/nonexistent", dry_run=True)
check("build() with a nonexistent library does NOT report PASS",
      res.verdict != "PASS", "%s / exit %s" % (res.verdict, res.exit_code))
check("and its exit code is non-zero", res.exit_code != 0, res.exit_code)
_blocking = [f.summary for s in res.stages for f in s.findings
             if f.status == "FAIL"]
check("and it says the library is the problem",
      any("librar" in s.lower() for s in _blocking), "; ".join(_blocking)[:200])

# The shipped library must still build, through the same argument.
res_ok = katana_build.build(SPEC, library=os.path.join(ROOT, "parts-library",
                                                       "ref_parts"),
                            dry_run=True)
check("build() with the real library still passes", res_ok.verdict == "PASS",
      "%s / exit %s" % (res_ok.verdict, res_ok.exit_code))
check("and passing no library at all still passes",
      katana_build.build(SPEC, dry_run=True).verdict == "PASS")

# A library directory that exists but holds no manifest is a different error, and must
# also not pass.
_empty = tempfile.mkdtemp(prefix="emptylib_")
res_empty = katana_build.build(SPEC, library=_empty, dry_run=True)
check("build() with an empty library directory does not report PASS",
      res_empty.verdict != "PASS",
      "%s / exit %s" % (res_empty.verdict, res_empty.exit_code))
shutil.rmtree(_empty, ignore_errors=True)

# ---- 2. the CLI must exit with the code it computed ----
p = run([SPEC, "--dry-run", "--json", "--expect-root", WRONG_ROOT])
report = {}
try:
    report = json.loads(p.stdout)
except Exception:
    pass
check("--json on a LOCK.root mismatch reports FAIL in its JSON",
      report.get("verdict") == "FAIL", report.get("verdict"))
check("and the PROCESS exits non-zero, so a script can tell",
      p.returncode != 0, "exit %d, json said exit_code %s"
      % (p.returncode, report.get("exit_code")))
check("and the two agree", p.returncode == report.get("exit_code"),
      "process %d vs json %s" % (p.returncode, report.get("exit_code")))

p = run([SPEC, "--dry-run", "--json"])
ok_report = json.loads(p.stdout)
check("--json on a clean dry run reports PASS", ok_report.get("verdict") == "PASS",
      ok_report.get("verdict"))
check("and exits 0", p.returncode == 0, p.returncode)

# The plain text path already exited correctly; it must keep doing so.
p = run([SPEC, "--dry-run", "--expect-root", WRONG_ROOT])
check("the plain path still exits non-zero on a root mismatch", p.returncode != 0,
      p.returncode)
p = run([SPEC, "--dry-run"])
check("and 0 on a clean dry run", p.returncode == 0, p.returncode)

# ---- 3. a REAL build -- not a dry run -- on the oldest promised Python ----
# The README promises 3.9. --dry-run never reaches the file writes, which is exactly why
# this went unnoticed, so this writes real output.
def old_python():
    for cand in ("/usr/bin/python3", "python3.9", "python3.10"):
        try:
            v = subprocess.check_output(
                [cand, "-c", "import sys;print('%d.%d' % sys.version_info[:2])"],
                text=True, stderr=subprocess.DEVNULL).strip()
        except Exception:
            continue
        if tuple(int(x) for x in v.split(".")) < (3, 11):
            return cand, v
    return None, None


_old, _ver = old_python()
_outdir = tempfile.mkdtemp(prefix="realbuild_")
p = run([SPEC, "--outdir", _outdir])
check("a real build (not a dry run) succeeds on this interpreter", p.returncode == 0,
      (p.stdout + p.stderr)[-300:])
_files = os.listdir(_outdir) if os.path.isdir(_outdir) else []
check("and it wrote its output files (%d)" % len(_files), len(_files) >= 2,
      ", ".join(_files))
shutil.rmtree(_outdir, ignore_errors=True)

if _old is None:
    print("  ---- no interpreter below 3.11 here: the 3.9 build check MEASURED NOTHING")
else:
    print("  ---- using %s (Python %s) for the old-interpreter build" % (_old, _ver))
    _outdir = tempfile.mkdtemp(prefix="realbuild39_")
    p = run([SPEC, "--outdir", _outdir], py=_old)
    check("a real build succeeds on Python %s" % _ver, p.returncode == 0,
          (p.stdout + p.stderr)[-300:])
    check("and it is not a TypeError from a 3.10-only keyword",
          "TypeError" not in (p.stdout + p.stderr),
          [l for l in (p.stdout + p.stderr).splitlines() if "TypeError" in l][:1])
    _files = os.listdir(_outdir) if os.path.isdir(_outdir) else []
    check("and the output files exist on Python %s (%d)" % (_ver, len(_files)),
          len(_files) >= 2, ", ".join(_files))
    # The order files must be byte-identical whichever interpreter wrote them: a seal
    # that depends on the Python version is not a seal.
    _outdir2 = tempfile.mkdtemp(prefix="realbuild313_")
    run([SPEC, "--outdir", _outdir2])
    _same, _diff = [], []
    for name in sorted(set(os.listdir(_outdir)) & set(os.listdir(_outdir2))):
        a = open(os.path.join(_outdir, name), "rb").read()
        b = open(os.path.join(_outdir2, name), "rb").read()
        (_same if a == b else _diff).append(name)
    check("the order files are byte-identical across Python versions (%s)"
          % (", ".join(_diff) or "all identical"), not _diff and _same)
    shutil.rmtree(_outdir, ignore_errors=True)
    shutil.rmtree(_outdir2, ignore_errors=True)

# ---- a stage that REFUSES must never come back as a pass ----
# The worst defect this review found. _Refused subclassed Exception, and the dry-lab
# gate's own `except Exception` caught it -- so the engine's refusal was reported as
# "dry-lab gate unavailable ... NOT enforced this run" and the build carried on to
# Stage 5 and sealed. Measured: a 240 bp off-target hit at 99.1% identity to the host
# genome, which the engine's own comment calls "never chance", came back as
#     verdict PASS, exit_code 0, no FAIL finding
# through the exact path the GUI, the web page and --json all use. The CLI escaped it
# only because _block() there raises SystemExit, which the handler re-raised.
#
# A refusal is CONTROL FLOW, not an error -- the same category as SystemExit and
# KeyboardInterrupt, and for the same reason. So _Refused must not be reachable by a
# generic handler at all, present or future.
check("a refusal is not catchable by `except Exception`",
      not issubclass(katana_build._Refused, Exception),
      katana_build._Refused.__mro__[1].__name__)
check("and it is still raisable", issubclass(katana_build._Refused, BaseException))


def _caught_by_generic():
    try:
        raise katana_build._Refused("x", "y")
    except Exception:
        return True
    except katana_build._Refused:
        return False


check("proved by raising one through a generic handler", _caught_by_generic() is False)

import katana_drylab

_real_gate = katana_drylab.run_drylab_gate


def _blocking_gate(*a, **k):
    return (["BLOCK OFF-TARGET: 240 bp at 99.1% identity to the host genome"], [], [])


katana_drylab.run_drylab_gate = _blocking_gate
try:
    _r = katana_build.build(SPEC, dry_run=True)
    check("a blocking dry-lab result does NOT report PASS", _r.verdict != "PASS",
          "%s / exit %s" % (_r.verdict, _r.exit_code))
    check("and its exit code is non-zero", _r.exit_code != 0, _r.exit_code)
    _fails = [f.summary for s in _r.stages for f in s.findings if f.status == "FAIL"]
    check("and there is a FAIL finding carrying the reason", _fails,
          str([(s.name, [f.status for f in s.findings]) for s in _r.stages]))
    check("and the reason is the off-target hit, not a missing tool",
          any("OFF-TARGET" in f or "dry-lab" in f for f in _fails)
          and "unavailable" not in (_r.log or ""),
          "; ".join(_fails)[:200])
    check("and blocked_stage() names the stage that refused",
          _r.blocked_stage() == "drylab", str(_r.blocked_stage()))

    # The --json path cannot be tested with this injection: it runs in a SUBPROCESS,
    # which does not inherit a monkeypatched gate. Rather than add a test hook to the
    # engine for it, the same guarantee is covered twice over by real refusals a
    # subprocess CAN see: the LOCK.root mismatch earlier in this file, which reports FAIL
    # in its JSON and exits non-zero, and the structural assertion below.
    _src = open(os.path.join(ROOT, "katana_build.py"), encoding="utf-8").read()
    check("main()'s --json path catches _Refused explicitly, as build() does",
          _src.count("except _Refused as refusal:") == 2,
          "%d handler(s)" % _src.count("except _Refused as refusal:"))
    check("and every handler that could sit between a stage and those two re-raises it",
          "except (SystemExit, _Refused):" in _src,
          "no re-raising handler found")
finally:
    katana_drylab.run_drylab_gate = _real_gate

# A gate that genuinely cannot run is still a SKIP, not a block and not a pass.
def _unavailable_gate(*a, **k):
    raise RuntimeError("blastn exploded")


katana_drylab.run_drylab_gate = _unavailable_gate
try:
    _r = katana_build.build(SPEC, dry_run=True)
    check("a dry-lab gate that genuinely fails is reported, not silently passed",
          "unavailable" in (_r.log or "") or _r.verdict != "PASS",
          "%s | log has 'unavailable': %s"
          % (_r.verdict, "unavailable" in (_r.log or "")))
finally:
    katana_drylab.run_drylab_gate = _real_gate

_r = katana_build.build(SPEC, dry_run=True)
check("and with the real gate the build still passes", _r.verdict == "PASS",
      "%s / exit %s" % (_r.verdict, _r.exit_code))

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
