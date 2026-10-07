"""Tests for core.result. Run: python3 tests/test_build_result.py"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from core import result as R

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  [" + str(detail)[:200] + "]") if detail else ""))


print("core.result")

check("the five status tokens exist and are the audit's own",
      (R.PASS, R.FLAG, R.FAIL, R.NOTE, R.SKIP) ==
      ("PASS", "FLAG", "FAIL", "NOTE", "SKIP"))

_r = R.BuildResult()
check("an empty result is PASS", _r.verdict == "PASS", _r.verdict)
check("and exits 0", _r.exit_code == 0, str(_r.exit_code))

_r.add(R.StageResult("validate", True, [R.Finding("gc", R.PASS, "GC 51.2%")]))
check("a PASS finding keeps the verdict PASS", _r.verdict == "PASS", _r.verdict)

_r.add(R.StageResult("drylab", True, [R.Finding("offtarget", R.NOTE, "a note")]))
check("a NOTE does not hold back PASS", _r.verdict == "PASS", _r.verdict)
check("but it is counted", _r.count(R.NOTE) == 1, str(_r.count(R.NOTE)))

_r.add(R.StageResult("drylab", True, [R.Finding("cai", R.SKIP, "not run")]))
check("a SKIP does not hold back PASS either", _r.verdict == "PASS", _r.verdict)

_r.add(R.StageResult("validate", True, [R.Finding("hp", R.FLAG, "homopolymer 11")]))
check("a FLAG makes the verdict REVIEW", _r.verdict == "REVIEW", _r.verdict)
check("and REVIEW exits 5", _r.exit_code == 5, str(_r.exit_code))

_r.add(R.StageResult("source", False, [R.Finding("pin", R.FAIL, "pin mismatch")]))
check("a FAIL makes the verdict FAIL", _r.verdict == "FAIL", _r.verdict)
check("and FAIL exits 1", _r.exit_code == 1, str(_r.exit_code))

_r2 = R.BuildResult()
_r2.add(R.StageResult("drylab", True,
                      [R.Finding("offtarget", R.SKIP, "no genome for this host")]))
check("a skipped gate is recorded as not-run, not as passed",
      _r2.stage("drylab").findings[0].status == R.SKIP)
check("and the result can say which gates did not run",
      _r2.not_run() == ["offtarget"], str(_r2.not_run()))

_r3 = R.BuildResult()
_r3.construct_id = "pSense-Nit"
_r3.version = 2
_r3.insert_len = 1013
_r3.seq_sha256 = "796e94a0" + "0" * 56
_r3.outputs = {"gb": "/tmp/x.gb", "fasta": "/tmp/x.fasta"}
_r3.add(R.StageResult("seal", True))
_d = _r3.to_dict()
check("to_dict is JSON-serialisable", json.dumps(_d)[:1] == "{")
for _k in ("construct_id", "version", "insert_len", "seq_sha256", "verdict",
           "exit_code", "stages", "outputs", "findings"):
    check("to_dict carries %s" % _k, _k in _d, ", ".join(sorted(_d)))
check("the verdict in the dict matches the property", _d["verdict"] == _r3.verdict)
check("stages are named in the order they ran",
      [s["name"] for s in _d["stages"]] == ["seal"], str(_d["stages"]))

_r4 = R.BuildResult()
_r4.add(R.StageResult("source", False,
                      [R.Finding("pin", R.FAIL, "part 'sfGFP': pin does not match")]))
_d4 = _r4.to_dict()
check("a blocked build still serialises", json.dumps(_d4)[:1] == "{")
check("and names the stage that refused", _r4.blocked_stage() == "source",
      str(_r4.blocked_stage()))
check("and the reason is in the findings", "pin does not match" in json.dumps(_d4))

# ---- build() returns a result instead of exiting ----
import katana_build

_spec = os.path.join(ROOT, "specs", "pSense-Nit.spec.yaml")
_res = katana_build.build(_spec, dry_run=True)
check("build() returns a BuildResult", isinstance(_res, R.BuildResult),
      type(_res).__name__)
check("it carries the construct id", _res.construct_id == "pSense-Nit",
      _res.construct_id)
check("it carries the sealed hash",
      _res.seq_sha256 ==
      "796e94a0ea2452edd2ce59ca30b8f28fea232b37ab2a036714239069fd1196f5",
      _res.seq_sha256)
check("it carries the insert length", _res.insert_len == 1013, str(_res.insert_len))
check("it records the stages it ran in order",
      [s.name for s in _res.stages][:4] == ["library", "source", "assemble", "validate"],
      str([s.name for s in _res.stages]))
check("a clean dry run does not read FAIL", _res.verdict != "FAIL", _res.verdict)
check("the off-target gate with no genome is recorded as NOT RUN, not as passed",
      "offtarget" in _res.not_run(), str(_res.not_run()))
check("build() prints nothing -- it captures its own log",
      len(_res.log) > 100, str(len(_res.log)))
check("and the log still contains the line other tools grep",
      "seq_sha256:" in _res.log)

# Review Focus 5: an architecture.order naming a part absent from parts: must come back
# as a FAIL in the result, NOT as a SystemExit escaping into a GUI worker thread.
import shutil
import tempfile

_d = tempfile.mkdtemp(prefix="br_")
_bad = os.path.join(_d, "bad.spec.yaml")
_src = open(_spec, encoding="utf-8").read()
open(_bad, "w", encoding="utf-8").write(
    _src.replace("order:          [PyeaR, RBS_sfGFP_med, sfGFP, B0015]",
                 "order:          [PyeaR, RBS_sfGFP_med, sfGFP, B0015, NoSuchPart]"))
_raised = None
try:
    _r5 = katana_build.build(_bad, dry_run=True)
except SystemExit as exc:
    _r5, _raised = None, "SystemExit(%s)" % exc
except Exception as exc:
    _r5, _raised = None, "%s: %s" % (type(exc).__name__, exc)
check("an order naming an unknown part returns a result, not an exception",
      _r5 is not None, _raised or "")
check("and that result reads FAIL", _r5 is not None and _r5.verdict == "FAIL",
      _r5.verdict if _r5 else "")
check("and names the stage that refused",
      _r5 is not None and _r5.blocked_stage() == "assemble",
      str(_r5.blocked_stage()) if _r5 else "")
check("and the reason mentions the part",
      _r5 is not None and "NoSuchPart" in json.dumps(_r5.to_dict()))

# A missing spec file runs before any stage exists, and must still come back as data.
_r6 = katana_build.build(os.path.join(_d, "nope.spec.yaml"), dry_run=True)
check("a missing spec file returns a result too", isinstance(_r6, R.BuildResult))
check("and it reads FAIL", _r6.verdict == "FAIL", _r6.verdict)
shutil.rmtree(_d, ignore_errors=True)

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
