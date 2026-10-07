"""test_drylab_gate.py — the off-target gate must run, and must say when it does not.

Run: python3 tests/test_drylab_gate.py

Three findings from an independent review, reproduced. They compound: each one hides the
next.

1. THE GATE NEVER RAN FOR ANYBODY USING THE BUNDLE. The 4.7 MB MG1655 genome ships at
   `kagami/genomes/`, put there for the web front end. `katana_drylab` looks only in
   `parts-library/ref_genomes/`, which is empty. So every build of every E. coli construct
   printed

       WARN Stage-4b: OFF-TARGET SKIPPED - no genome here for host E_coli_MG1655.
                      NOT enforced this run. Fetch one with: python3 get_genome.py

   and the remedy offered was a network download of a file already on the student's disk.
   The engine's most substantive dry-lab check was dead by default, and the BROWSER could
   scan a host the command line could not.

2. A CRASHED STAGE REPORTED PASS. Stage 4b records its StageResult inside the `try`; the
   outer `except Exception` printed "NOT enforced this run" and added no stage and no
   finding. Measured with a gate that raises:

       verdict PASS, exit_code 0, not_run() [], stages [library, source, assemble,
       validate] -- no 'drylab' at all, and from_result() said "Stages 1-4b passed"

   The SKIP tier was bypassed in the exact case it exists for. Root cause: the SKIP
   decision lived twice -- once by grepping `"NOT enforced" in _m`, which is prose used as
   a machine interface, and the outer handler emitted that same phrase into a channel the
   grep never read.

3. THE TWO VERDICT READINGS DISAGREED. A SKIP did not affect `verdict`, `exit_code` or
   --json, but `from_result()` escalated it to REVIEW. So a CI step gated on the exit code
   was told PASS on a build where a gate never ran, while the window beside it said a gate
   did not run. One of the two had to be wrong, and the project's own rule says which.

Fixing 1 first is what makes 3 safe to fix: with the gate actually running, a SKIP is rare
and worth surfacing, instead of firing on every build and becoming noise.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "kagami"))

SPEC = os.path.join(ROOT, "specs", "pSense-Nit.spec.yaml")

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  [" + str(detail)[:320] + "]") if detail else ""))


print("the dry-lab gate")

# ---- 1. the shipped genome must be found ----
_ship = os.path.join(ROOT, "kagami", "genomes", "MG1655_ecoli_NC_000913.3.fna")
check("the bundle ships an E. coli genome", os.path.isfile(_ship),
      "%s missing" % _ship)

p = subprocess.run([sys.executable, "katana_build.py", SPEC, "--dry-run"],
                   cwd=ROOT, capture_output=True, text=True, timeout=900)
out = p.stdout + p.stderr
check("a build of an E. coli construct does NOT skip the off-target check",
      "OFF-TARGET SKIPPED" not in out,
      [l.strip() for l in out.splitlines() if "OFF-TARGET" in l][:2])
check("and it does not tell the student to download a genome they already have",
      "get_genome.py" not in out or "OFF-TARGET SKIPPED" not in out,
      [l.strip() for l in out.splitlines() if "get_genome" in l][:2])
check("the off-target check reports something it actually measured",
      "off-target" in out.lower(), [l.strip() for l in out.splitlines()
                                    if "off-target" in l.lower()][:3])

# ---- 2. a gate that crashes must be recorded as not-run ----
import katana_build
import katana_drylab
import kg_verdict

_real = katana_drylab.run_drylab_gate


def _crash(*a, **k):
    raise RuntimeError("renamed helper")


katana_drylab.run_drylab_gate = _crash
try:
    r = katana_build.build(SPEC, dry_run=True)
    _names = [s.name for s in r.stages]
    check("a crashed gate still records a drylab stage", "drylab" in _names,
          str(_names))
    check("and it is recorded as not-run, by name", "drylab" in r.not_run(),
          str(r.not_run()))
    check("and the build does NOT report PASS", r.verdict != "PASS",
          "%s / exit %s" % (r.verdict, r.exit_code))
    check("and its exit code is not 0", r.exit_code != 0, r.exit_code)
    _kind, _head, _detail = kg_verdict.from_result(r)
    check("and the window does not say the stage passed",
          "1-4b passed" not in _head + _detail,
          "%s | %s" % (_head, _detail))
    check("and it says a gate did not run",
          "did not run" in (_head + _detail).lower(), "%s | %s" % (_head, _detail))
    check("the crash reason is kept, not discarded",
          "renamed helper" in (r.log or "")
          or any("renamed helper" in (f.detail or "") + f.summary
                 for s in r.stages for f in s.findings),
          (r.log or "")[-200:])
finally:
    katana_drylab.run_drylab_gate = _real

# ---- 3. the two verdict readings must agree about a SKIP ----
_real2 = katana_drylab.run_drylab_gate


def _skipping(*a, **k):
    return ([], ["WARN Stage-4b: OFF-TARGET SKIPPED - no genome here for host X. "
                 "NOT enforced this run."], [])


katana_drylab.run_drylab_gate = _skipping
try:
    r = katana_build.build(SPEC, dry_run=True)
    check("a skipped gate is recorded as not-run", r.not_run(), str(r.not_run()))
    _kind, _head, _detail = kg_verdict.from_result(r)
    check("and BuildResult.verdict agrees with what the window says (%s vs %s)"
          % (r.verdict, _kind), r.verdict == _kind,
          "verdict %s, exit %s, window %s" % (r.verdict, r.exit_code, _kind))
    check("and the exit code matches that verdict",
          r.exit_code == {"PASS": 0, "REVIEW": 5, "FAIL": 1}[r.verdict],
          "%s / %s" % (r.verdict, r.exit_code))
    check("and --json's verdict is the same one",
          r.to_dict().get("verdict") == r.verdict,
          "%s vs %s" % (r.to_dict().get("verdict"), r.verdict))
finally:
    katana_drylab.run_drylab_gate = _real2

# A clean build must still be a clean PASS, or all of the above is just noise.
# With every gate RUNNING, this spec reads REVIEW -- and that is the point. It carries
# 80 bp matches at 100%% identity to the host genome away from any expected locus:
# recombination substrates worth a human glance before ordering. Asserting PASS here is
# what asserting a dead gate looks like.
r = katana_build.build(SPEC, dry_run=True)
check("a build with every gate running reports REVIEW, for real findings",
      r.verdict == "REVIEW",
      "%s / exit %s / not_run %s" % (r.verdict, r.exit_code, r.not_run()))
check("and NOTHING is reported as not-run -- the gate ran", not r.not_run(),
      str(r.not_run()))
_flags = [f.summary for s in r.stages for f in s.findings if f.status == "FLAG"]
check("and the findings are off-target matches it measured", 
      any("off-target" in s for s in _flags), "; ".join(_flags)[:200])
_kind, _head, _detail = kg_verdict.from_result(r)
check("and the window agrees", _kind == "REVIEW", "%s | %s" % (_kind, _head))

p = subprocess.run([sys.executable, "katana_build.py", SPEC, "--dry-run"],
                   cwd=ROOT, capture_output=True, text=True, timeout=900)
check("and the CLI exits 5 on it, which a script can tell from a failure",
      p.returncode == 5, "exit %d" % p.returncode)

# ---- and 'Stage-4b PASS' must not print when 4b did not run ----
katana_drylab.run_drylab_gate = _skipping
try:
    r = katana_build.build(SPEC, dry_run=True)
    check("the log does not say 'Stage-4b PASS' when 4b was skipped",
          "Stage-4b PASS" not in (r.log or ""),
          [l.strip() for l in (r.log or "").splitlines() if "Stage-4b" in l][:3])
finally:
    katana_drylab.run_drylab_gate = _real2

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
