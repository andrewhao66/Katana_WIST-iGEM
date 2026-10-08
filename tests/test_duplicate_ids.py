"""test_duplicate_ids.py — one id named twice is a contradiction, not a preference.

Run: python3 tests/test_duplicate_ids.py

Found by an independent reliability review, which called it the worst of the seven cases
it measured. I reproduced it before accepting it.

`HrpS.Ec-opt` is sealed in the shipped library at three versions, all 909 bases and all
different sequences. Take `specs/pAP-Logic.spec.yaml`, which pins v3, and add a second
entry for the same id pinned to v1. Both pins are legitimate; both files are in the
library; both verify. The build does not complain:

    Stage-1/2 PASS: HrpS.Ec-opt (909 bp, 5093ea792057)     <- v3
    Stage-1/2 PASS: HrpS.Ec-opt (909 bp, 4c7642e360ba)     <- v1
    All 14 distinct parts resolved and verified.
    seq_sha256: ae486f3c35e329d6...

Fifteen entries counted as fourteen parts, with no note saying two were collapsed. And
`ae486f3c…` is byte-identical to a control spec pinned to v1 ALONE, while the shipped
spec pinned to v3 alone gives `1d99b7be…`. So the LAST entry wins the bases, and
`assemble_insert` takes the role and metadata from the FIRST.

The artifact is therefore sealed, hash-consistent, and annotated with v3's record over
v1's bases. That is precisely the thing this project's design exists to make
unrepresentable -- "if the only way to name a part is by ID, then the ID and the bases
cannot disagree, because there is only one of them in the document" -- and the engine
produced one itself, from a Spec that passes every other gate.

Two entries naming one part with different pins is two sources disagreeing about which
sequence is meant. Rule four: report it, do not resolve it. So it blocks.

What must still work: the same id twice with the SAME pin, which is a harmless
duplication rather than a contradiction, and every shipped Spec, none of which does this.
"""
import os
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


def build(spec):
    p = subprocess.run([sys.executable, "katana_build.py", spec, "--dry-run"],
                       cwd=ROOT, capture_output=True, text=True, timeout=900)
    return p.returncode, p.stdout + p.stderr


def entry_bounds(lines, pid):
    start = next(i for i, l in enumerate(lines) if l.strip() == "- id: %s" % pid)
    end = start + 1
    while end < len(lines) and not lines[end].lstrip().startswith("- id:"):
        end += 1
    return start, end


SPEC = os.path.join(ROOT, "specs", "pAP-Logic.spec.yaml")
LINES = open(SPEC, encoding="utf-8").read().split("\n")
D = tempfile.mkdtemp(prefix="dupid_")


def write(name, lines):
    path = os.path.join(D, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


print("duplicate part ids")

# ---- the premise: three sealed versions of one id, all different ----
from core import lock as _lock

_rows = _lock.read(os.path.join(ROOT, "parts-library", "ref_parts", "LOCK.tsv"))[1]
_hrps = [r for r in _rows if r["id"] == "HrpS.Ec-opt"]
check("HrpS.Ec-opt is sealed at more than one version (%d)" % len(_hrps),
      len(_hrps) >= 2, str([(r["version"], r["seq_sha256"][:12]) for r in _hrps]))
check("and those versions are DIFFERENT sequences",
      len({r["seq_sha256"] for r in _hrps}) == len(_hrps),
      str([r["seq_sha256"][:12] for r in _hrps]))

# ---- the shipped spec must keep building ----
_rc, _out = build(SPEC)
check("the shipped pAP-Logic spec still builds", _rc in (0, 5),
      "exit %d | %s" % (_rc, _out[-200:]))
_shipped_hash = ""
for _tok in _out.split():
    if len(_tok) == 64 and all(c in "0123456789abcdef" for c in _tok):
        _shipped_hash = _tok
        break
check("and records a sealed hash", len(_shipped_hash) == 64, _shipped_hash)

# ---- the same id twice with DIFFERENT pins must block ----
_s, _e = entry_bounds(LINES, "HrpS.Ec-opt")
_v1 = [l.replace("HrpS.Ec-opt__v3__5093ea792057.gb",
                 "HrpS.Ec-opt__v1__4c7642e360ba.gb")
        .replace("5093ea792057", "4c7642e360ba")
        .replace("@v3@", "@v1@") for l in LINES[_s:_e]]
_dup = write("dup.spec.yaml", LINES[:_e] + _v1 + LINES[_e:])

_rc, _out = build(_dup)
# A BLOCK, not merely a non-zero exit. 5 is REVIEW -- "glance at this before ordering" --
# and a Spec that contradicts itself about which sequence a part is must not be buildable
# at all. Treating 5 as a refusal is what let the first version of this assertion pass
# while the artifact was still being produced.
check("a spec naming one id twice with different pins is REFUSED (exit %d)" % _rc,
      _rc == 1 and "BLOCK" in _out, "exit %d | %s" % (_rc, _out[-250:]))
check("and says which id is doubled", "HrpS.Ec-opt" in _out, _out[-300:])
check("and names both pins, so the reader can see what disagrees",
      "5093ea792057" in _out and "4c7642e360ba" in _out, _out[-400:])
check("and does NOT print a sealed hash for it",
      not [t for t in _out.split()
           if len(t) == 64 and all(c in "0123456789abcdef" for t2 in [t] for c in t2)
           and t != _shipped_hash],
      [t for t in _out.split() if len(t) == 64][:2])

# The specific harm: it must not silently produce the v1-only artifact.
_only_v1 = write("only_v1.spec.yaml", LINES[:_s] + _v1 + LINES[_e:])
_rc1, _out1 = build(_only_v1)
_v1_hash = ""
for _tok in _out1.split():
    if len(_tok) == 64 and all(c in "0123456789abcdef" for c in _tok):
        _v1_hash = _tok
        break
check("pinning v1 alone is legitimate and builds", _rc1 in (0, 5), "exit %d" % _rc1)
check("and gives a DIFFERENT hash from v3 alone", _v1_hash and _v1_hash != _shipped_hash,
      "%s vs %s" % (_v1_hash[:16], _shipped_hash[:16]))
check("so the duplicate spec must not quietly produce the v1 artifact",
      _v1_hash not in _out, "the duplicate build emitted the v1-only hash")

# ---- the same id twice with the SAME pin is harmless and must still build ----
_same = write("same.spec.yaml", LINES[:_e] + LINES[_s:_e] + LINES[_e:])
_rc, _out = build(_same)
check("the same id twice with the SAME pin still builds", _rc in (0, 5),
      "exit %d | %s" % (_rc, _out[-250:]))
check("and gives the shipped hash, because nothing disagrees",
      _shipped_hash in _out, _out[-250:])

# ---- and every shipped spec must be unaffected ----
import glob

_broken = []
for _spec in sorted(glob.glob(os.path.join(ROOT, "specs", "*.spec.yaml"))):
    _rc, _out = build(_spec)
    if _rc not in (0, 5):
        _broken.append("%s exit %d" % (os.path.basename(_spec), _rc))
check("all shipped specs still build (%s)" % ("; ".join(_broken) or "all of them"),
      not _broken)

import shutil

shutil.rmtree(D, ignore_errors=True)

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
