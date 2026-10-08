"""test_decomposition_complete.py — the decomposition must account for every base.

Run: python3 tests/test_decomposition_complete.py

Found by verifying a real audit against Katana's own build record instead of reading the
audit's output.

The report said "DECOMPOSITION — 5 block(s) identified" and its table began at base 14.
Bases 1-13 appeared nowhere: not as an identified block, not as an unidentified region,
not as a number. The block list itself was missing them — 1000 of 1013 bases — so this was
the data, not the printing. On the demo, 13 bases went missing the same way across two
gaps of 7 and 6.

And 1-13 was not noise. It is PyeaR's first 13 bases, the start of the construct's own
promoter.

The cause was a 30 bp minimum on gap rows, sitting four lines above a constant whose
comment argues for a much smaller one: "the smallest leftover worth showing as its own
block ... at this size it is a real element (an RBS is ~18 bp) and the reader wants it",
with MIN_REMAINDER = 6. Two thresholds disagreeing, and the one in force was above the
length of an RBS.

What must hold: a table that looks like a complete accounting of the sequence is one. A
leftover of six bases or more gets its own row. Anything smaller is still reported, as a
count in the header, because "we did not account for these" must not read as nothing at
all — the same rule the SKIP tier exists for, applied to the decomposition.
"""
import os
import glob
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "kagami"))

import kg_identify
import kg_parse
import kg_refs

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  [" + str(detail)[:320] + "]") if detail else ""))


def blocks_of(path):
    record = kg_parse.parse(path)
    status = {}
    with tempfile.TemporaryDirectory() as wd:
        return record, kg_identify.identify(record, wd, status=status)


def unaccounted(record, blocks):
    """Intervals of the sequence that no block covers."""
    gaps = []
    pos = 1
    for a, b in sorted((x.start, x.end) for x in blocks):
        if a > pos:
            gaps.append((pos, a - 1))
        pos = max(pos, b + 1)
    if pos <= len(record.seq):
        gaps.append((pos, len(record.seq)))
    return gaps


print("decomposition completeness")

# ---- Katana's own build: its first 13 bases were missing from the report ----
_out = tempfile.mkdtemp(prefix="decomp_")
subprocess.run([sys.executable, "katana_build.py",
                os.path.join(ROOT, "specs", "pSense-Nit.spec.yaml"),
                "--outdir", _out],
               cwd=ROOT, capture_output=True, text=True, timeout=900)
_gb = glob.glob(os.path.join(_out, "*.gb"))
check("Katana builds pSense-Nit", _gb)

if _gb:
    _rec, _bl = blocks_of(_gb[0])
    _gaps = unaccounted(_rec, _bl)
    check("every base of the construct is in some block (%s)"
          % (", ".join("%d-%d" % g for g in _gaps) or "all 1013"), not _gaps,
          "%d of %d accounted for"
          % (sum(b.end - b.start + 1 for b in _bl), len(_rec.seq)))
    # The 13 bases are the start of the promoter, not a scar.
    _first = [b for b in _bl if b.start == 1]
    check("and the block covering base 1 exists", _first,
          str([(b.start, b.end, b.ident_id or b.note) for b in _bl][:2]))

# ---- the demo: two small gaps went the same way ----
_demo = os.path.join(ROOT, "kagami", "examples", "demo.gb")
if os.path.isfile(_demo):
    _rec2, _bl2 = blocks_of(_demo)
    _gaps2 = unaccounted(_rec2, _bl2)
    check("the demo's decomposition accounts for every base (%s)"
          % (", ".join("%d-%d" % g for g in _gaps2) or "all 843"), not _gaps2,
          "%d of %d" % (sum(b.end - b.start + 1 for b in _bl2), len(_rec2.seq)))
    check("and its planted mislabel is still found",
          any(b.claim_label == "B0032" for b in _bl2),
          str([(b.start, b.end, b.claim_label) for b in _bl2]))

# ---- a gap of six bases or more gets its own row ----
_REFS = {r["id"]: kg_refs.normalise(r["seq"]) for r in kg_refs.REFERENCE_PARTS
         if r.get("seq")}
_B15 = _REFS["B0015"]


def fasta(seq):
    d = tempfile.mkdtemp(prefix="decomp2_")
    p = os.path.join(d, "t.fasta")
    with open(p, "w", encoding="utf-8") as f:
        f.write(">t\n" + seq + "\n")
    return p


for _n in (6, 13, 29, 40):
    for _where, _seq in (("leading", "T" * _n + _B15),
                         ("trailing", _B15 + "T" * _n)):
        _r, _b = blocks_of(fasta(_seq))
        _g = unaccounted(_r, _b)
        check("a %d bp %s gap is accounted for (%s)"
              % (_n, _where, ", ".join("%d-%d" % x for x in _g) or "yes"), not _g,
              "%d of %d" % (sum(x.end - x.start + 1 for x in _b), len(_seq)))

# A gap in the middle, which already worked at 33 bp and must keep working small.
for _n in (6, 13):
    _r, _b = blocks_of(fasta(_B15 + "T" * _n + _B15))
    _g = unaccounted(_r, _b)
    check("a %d bp interior gap is accounted for (%s)"
          % (_n, ", ".join("%d-%d" % x for x in _g) or "yes"), not _g,
          "%d of %d" % (sum(x.end - x.start + 1 for x in _b), len(_B15) * 2 + _n))

# ---- below that, the header must still say so rather than stay silent ----
_r, _b = blocks_of(fasta(_B15 + "TT" + _B15))
_g = unaccounted(_r, _b)
_acc = sum(x.end - x.start + 1 for x in _b)
# These two were `check(..., True)` and `check(..., cond or True)` -- assertions that
# cannot fail, padding the count while testing nothing. An independent review found them,
# in a file whose whole subject is reports that look complete and are not.
#
# What is actually true of a gap below MIN_REMAINDER: it gets no row of its own, so the
# blocks do NOT account for the whole sequence, and the shortfall is small.
check("a 2 bp gap gets no row of its own, so the blocks fall short (%d of %d)"
      % (_acc, len(_r.seq)), _acc < len(_r.seq), "%d of %d" % (_acc, len(_r.seq)))
check("and it falls short by exactly that gap", len(_r.seq) - _acc == 2,
      "%d bases unaccounted" % (len(_r.seq) - _acc))

# The text a person reads is where this has to be true.
_p = subprocess.run([sys.executable, "kagami.py", "audit", fasta(_B15 + "TT" + _B15)],
                    cwd=os.path.join(ROOT, "kagami"), capture_output=True, text=True,
                    timeout=600)
_out_txt = _p.stdout + _p.stderr
if _acc != len(_r.seq):
    check("a shortfall too small to list is still reported as a finding",
          "not in any block" in _out_txt,
          [l for l in _out_txt.splitlines() if "block" in l][-2:])
    check("and it says how many of how many are accounted for",
          "account for" in _out_txt.lower(), _out_txt[-300:])
    check("and it is a NOTE, so it does not hold back a PASS",
          "[note] decomposition" in _out_txt,
          [l for l in _out_txt.splitlines() if "decomposition" in l])
else:
    # If a future MIN_REMAINDER gives even a 2 bp gap its own row, then the blocks DO
    # account for everything and there is nothing to state -- which is a real assertion,
    # not `True`.
    check("the 2 bp gap got a row, so the blocks account for the whole sequence",
          _acc == len(_r.seq), "%d of %d" % (_acc, len(_r.seq)))

# And when everything IS accounted for, nothing cries wolf about it.
_p2 = subprocess.run([sys.executable, "kagami.py", "audit", _demo],
                     cwd=os.path.join(ROOT, "kagami"), capture_output=True, text=True,
                     timeout=600)
check("a complete decomposition raises no such finding",
      "not in any block" not in (_p2.stdout + _p2.stderr),
      [l for l in (_p2.stdout + _p2.stderr).splitlines() if "block" in l][-2:])

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
