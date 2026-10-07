"""test_engine_gates.py — the build engine's two integrity gates, end to end.

Run: python3 tests/test_engine_gates.py

These drive katana_build.py as a subprocess against sandbox copies of the library,
because the gates are what the engine does when a real user builds a real Spec, and a
unit test of core.lock would not have caught either of the defects below: both lived in
the engine's own copy of the logic.
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
        print("  FAIL " + name + (("  [" + detail[:300] + "]") if detail else ""))


def sandbox():
    """A copy of the repository's engine, library and specs, in a temp directory."""
    d = tempfile.mkdtemp(prefix="gates_")
    shutil.copytree(os.path.join(ROOT, "parts-library"),
                    os.path.join(d, "parts-library"),
                    ignore=shutil.ignore_patterns("ref_genomes"))
    shutil.copytree(os.path.join(ROOT, "specs"), os.path.join(d, "specs"))
    shutil.copytree(os.path.join(ROOT, "core"), os.path.join(d, "core"),
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(os.path.join(ROOT, "_vendor"), os.path.join(d, "_vendor"),
                    ignore=shutil.ignore_patterns("__pycache__"))
    for f in ("katana_build.py", "katana_drylab.py", "blast_offtarget.py",
              "katana_order_table.py", "katana_sbol.py", "katana_lock.py",
              "vendor_path.py"):
        shutil.copyfile(os.path.join(ROOT, f), os.path.join(d, f))
    return d


def build(d, spec_name, *extra):
    return subprocess.run(
        [sys.executable, os.path.join(d, "katana_build.py"),
         os.path.join(d, "specs", spec_name), "--dry-run"] + list(extra),
        capture_output=True, text=True, encoding="utf-8", errors="replace")


print("engine integrity gates")

# ---- a sandbox builds cleanly, or nothing below measures anything ----
_d = sandbox()
_p = build(_d, "pSense-Nit.spec.yaml")
# 0 or 5. The sandbox copies the engine, not the 4.7 MB genome, so the off-target gate
# reports itself as not-run and the verdict is REVIEW -- which is the correct answer for a
# sandbox and exactly what the SKIP tier is for. This suite tests PIN REFUSALS; the gate's
# own behaviour is tests/test_drylab_gate.py's job. The assertion read == 0 before, which
# passed only because the gate was dead everywhere.
check("the sandboxed engine builds a Spec at all", _p.returncode in (0, 5),
      _p.stdout + _p.stderr)

# ---- CODE-REPORT finding A, through the engine ----
# Edit a RECORDED ACCESSION and leave row_sha256 alone. The engine used to hash the
# row_sha256 column as written, so this passed: a falsified provenance claim built to
# completion with exit 0 while verify_library_v2.py reported two problems. The sequence
# was still protected by stage 2; the recorded ORIGIN of that sequence was not.
_d = sandbox()
_lock = os.path.join(_d, "parts-library", "ref_parts", "LOCK.tsv")
_t = open(_lock, encoding="utf-8").read()
_t2 = _t.replace("NC_000913.3:363231-366305", "NC_000913.3:999999-999999")
check("the sandbox manifest contains the accession to falsify", _t2 != _t)
with open(_lock, "w", encoding="utf-8", newline="\n") as _f:
    _f.write(_t2)

_p = build(_d, "pSense-Lac-lacZ.spec.yaml")
_out = _p.stdout + _p.stderr
check("a falsified accession BLOCKS the build", _p.returncode != 0,
      "exit %d" % _p.returncode)
check("and the refusal names the row that disagrees", "lacZ" in _out, _out[-400:])
check("and says a trust field was edited", "row_sha256" in _out, _out[-400:])

# ---- CODE-REPORT finding B, through the engine ----
# Re-pin a Spec to an OLDER sealed version whose row and file are both still present.
# The engine used to take max(version) and refuse, telling the reader to update the Spec
# to match the library -- which would change the construct, and contradicts the
# append-only history the architecture promises.
_d = sandbox()
_spec = os.path.join(_d, "specs", "pAP-Logic.spec.yaml")
_s = open(_spec, encoding="utf-8").read()
_s2 = (_s.replace("designed/acoustic/HrpS.Ec-opt__v3__5093ea792057.gb",
                  "designed/acoustic/HrpS.Ec-opt__v2__cc3f6c1ec6ef.gb")
         .replace("seq_sha256_12: 5093ea792057", "seq_sha256_12: cc3f6c1ec6ef"))
check("the Spec contains the v3 pin to downgrade", _s2 != _s)
with open(_spec, "w", encoding="utf-8") as _f:
    _f.write(_s2)

_p = build(_d, "pAP-Logic.spec.yaml")
_out = _p.stdout + _p.stderr
check("a Spec pinned to an older sealed version BUILDS", _p.returncode in (0, 5),
      _out[-500:])
check("and it loads v2, not v3",
      "cc3f6c1ec6ef" in _out and "5093ea792057" not in _out, _out[-500:])
check("and the construct hash DIFFERS from the v3 build, as it must",
      "1d99b7be2c513b19" not in _out, _out[-500:])

# ---- the pin must still be enforced, or the fix would be a hole ----
_d = sandbox()
_spec = os.path.join(_d, "specs", "pSense-Nit.spec.yaml")
_s = open(_spec, encoding="utf-8").read()
with open(_spec, "w", encoding="utf-8") as _f:
    _f.write(_s.replace("seq_sha256_12: 08a1e654bd76", "seq_sha256_12: ffffffffffff"))
_p = build(_d, "pSense-Nit.spec.yaml")
check("a pin matching NO sealed version is still refused", _p.returncode != 0,
      "exit %d" % _p.returncode)

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
