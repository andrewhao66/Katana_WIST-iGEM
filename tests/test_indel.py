"""test_indel.py — one inserted or deleted base must not hide a mislabel.

Run: python3 tests/test_indel.py

Found by an independent reviewer, and it refuted this branch's central claim.

The design document said deleting NCBI BLAST+ lost nothing. For indels that was false, and
consequentially so. `_extend` scores ONE diagonal with a maximal-scoring segment, and an
insertion or deletion shifts the diagonal — so the true alignment splits into two pieces,
each covering about half the reference, and `_tile`'s `min_cov = 0.6` floor dropped both.

Measured end to end on real AmCyan bases labelled "sfGFP":

    intact:            cov 1.000, FLAG identity-mislabel -- caught
    one base deleted:  ident None, cov None, mislabel findings: 0 -- SILENTLY LOST

The part became one "unidentified region", and a block with no identity is never compared
against its claim. blastn, whose task opens a gap for 5 and extends for 2, scores that as
a single HSP at about 99.9% identity and reports it, so the mislabel fires.

Indels are the most common cloning and synthesis artifact, and they were the one operation
blastn performs that the replacement could not represent at all.

It got through for a reason worth recording: kagami/test_identify.py has 58 assertions --
truncation at three depths, substitutions at three densities, reverse strand, lowercase,
N, IUPAC, repeated parts, low-complexity traps -- and NOT ONE insertion or deletion. The
suite written to prove the removal lost nothing omitted the only thing it lost. One
assertion here would have caught it before it shipped.

The fix joins pieces of one gapped alignment before the coverage floor is applied: two
hits of the same reference whose diagonals differ by a small offset, whose query intervals
are adjacent, and whose reference intervals are complementary, are one alignment with an
indel in it. Two separate occurrences of a part differ in diagonal by the distance between
them, which is far larger than any indel, so they are not merged.
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "kagami"))

import kg_audit
import kg_identify
import kg_parse
import kg_refs
import kg_seedmatch as sm

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  [" + str(detail)[:300] + "]") if detail else ""))


FULL = list(kg_refs.REFERENCE_PARTS)
_by_id = {r["id"]: kg_refs.normalise(r["seq"]) for r in FULL if r.get("seq")}
AM = _by_id["AmCyan"]
B15 = _by_id["B0015"]
PAD = "T" * 40


def hits(query, sid, refs=None, **kw):
    return [h for h in sm.identify_hits(query, refs or FULL, **kw) if h["sid"] == sid]


def delete(seq, at, n=1):
    return seq[:at] + seq[at + n:]


def insert(seq, at, bases="A"):
    return seq[:at] + bases + seq[at:]


print("indels")
check("AmCyan is %d bp" % len(AM), len(AM) == 687, len(AM))

# ---- a deletion must not split the part out of existence ----
for at in (100, 300, 500):
    _h = hits(PAD + delete(AM, at) + PAD, "AmCyan")
    _best = max(_h, key=lambda h: h["cov"]) if _h else None
    check("1 bp deleted at %d: AmCyan is still found whole (cov %s)"
          % (at, round(_best["cov"], 3) if _best else "none"),
          _best is not None and _best["cov"] > 0.95,
          str([(h["pident"], round(h["cov"], 3)) for h in _h]))
    if _best:
        check("  and its identity reflects one missing base, not a half-match",
              _best["pident"] > 95.0, _best["pident"])
        check("  and the hit says there is an indel in it",
              _best.get("indel"), str(_best.get("indel")))

# ---- and an insertion ----
for at in (100, 300, 500):
    _h = hits(PAD + insert(AM, at) + PAD, "AmCyan")
    _best = max(_h, key=lambda h: h["cov"]) if _h else None
    check("1 bp inserted at %d: AmCyan is still found whole (cov %s)"
          % (at, round(_best["cov"], 3) if _best else "none"),
          _best is not None and _best["cov"] > 0.95,
          str([(h["pident"], round(h["cov"], 3)) for h in _h]))

# ---- a larger indel, still within cloning range ----
for n in (3, 9):
    _h = hits(PAD + delete(AM, 300, n) + PAD, "AmCyan")
    _best = max(_h, key=lambda h: h["cov"]) if _h else None
    check("%d bp deleted: still found whole (cov %s)"
          % (n, round(_best["cov"], 3) if _best else "none"),
          _best is not None and _best["cov"] > 0.95,
          str([(h["pident"], round(h["cov"], 3)) for h in _h]))

# ---- the end to end case the reviewer demonstrated ----
def audit(seq, label, start, end):
    d = tempfile.mkdtemp(prefix="indel_")
    path = os.path.join(d, "t.gb")
    out = ["LOCUS       t %13d bp    DNA     linear   SYN" % len(seq),
           "FEATURES             Location/Qualifiers",
           "     CDS             %d..%d" % (start, end),
           '                     /label="%s"' % label, "ORIGIN"]
    for i in range(0, len(seq), 60):
        out.append("%9d %s" % (i + 1, " ".join(seq[i + j:i + j + 10]
                                               for j in range(0, 60, 10))))
    out.append("//")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    record = kg_parse.parse(path)
    status = {}
    with tempfile.TemporaryDirectory() as wd:
        blocks = kg_identify.identify(record, wd, status=status)
    return blocks, kg_audit.audit(record, blocks, identify_status=status)


for name, body in (("intact", AM), ("one base deleted", delete(AM, 300))):
    _seq = PAD + body + PAD
    _bl, _fs = audit(_seq, "sfGFP", len(PAD) + 1, len(PAD) + len(body))
    _mis = [f for f in _fs if f.category == "identity-mislabel"]
    check("%s: AmCyan bases labelled sfGFP STILL raise the mislabel FLAG" % name,
          len(_mis) >= 1,
          "blocks %s | findings %s"
          % ([(b.ident_id, b.coverage) for b in _bl],
             [f.category for f in _fs]))

# ---- an indel must be REPORTED, not smoothed over ----
_seq = PAD + delete(AM, 300) + PAD
_bl, _fs = audit(_seq, "AmCyan", len(PAD) + 1, len(PAD) + len(AM) - 1)
_ind = [f for f in _fs if f.category == "indel"]
check("a part with a deleted base raises an indel finding", len(_ind) == 1,
      str([(f.category, f.status) for f in _fs]))
if _ind:
    check("  and it is a FLAG, so the verdict is not PASS",
          _ind[0].status == kg_audit.FLAG, _ind[0].status)
    check("  and it names the part and the size of the gap",
          "AmCyan" in _ind[0].summary and "1" in _ind[0].summary, _ind[0].summary)
    check("  and the detail says a frameshift is the thing to check",
          "frame" in (_ind[0].detail or "").lower(), (_ind[0].detail or "")[:150])

_bl, _fs = audit(PAD + AM + PAD, "AmCyan", len(PAD) + 1, len(PAD) + len(AM))
check("an intact part raises NO indel finding",
      not [f for f in _fs if f.category == "indel"],
      str([(f.category, f.summary) for f in _fs if f.category == "indel"]))

# ---- what must NOT be merged ----
# Two separate occurrences of a part differ in diagonal by the distance between them,
# which is far larger than any indel. Merging them would invent one part where there are
# two, and lose a mislabel on the second.
_two = hits(PAD + B15 + "A" * 200 + B15 + PAD, "B0015", [r for r in FULL
                                                         if r["id"] == "B0015"])
_fwd = [h for h in _two if h["strand"] == 1]
check("two separate copies of a part are NOT merged into one (%d)" % len(_fwd),
      len(_fwd) == 2, str([(h["qstart"], h["qend"], round(h["cov"], 3))
                           for h in _fwd]))

# Adjacent copies, with no padding between them: the diagonal difference is the part
# length, still far above any indel.
_adj = [h for h in hits(PAD + B15 + B15 + PAD, "B0015",
                        [r for r in FULL if r["id"] == "B0015"])
        if h["strand"] == 1]
check("two ADJACENT copies are not merged either (%d)" % len(_adj), len(_adj) == 2,
      str([(h["qstart"], h["qend"], round(h["cov"], 3)) for h in _adj]))

# And a genuinely truncated part must still read as truncated, not be "completed" by
# merging it with something unrelated nearby.
_tr = hits(PAD + B15[:100] + PAD, "B0015", [r for r in FULL if r["id"] == "B0015"])
_tb = max(_tr, key=lambda h: h["cov"]) if _tr else None
check("a truncated part is still truncated, not merged up to full coverage",
      _tb is not None and 0.7 < _tb["cov"] < 0.85,
      str([(h["pident"], round(h["cov"], 3)) for h in _tr]))

# ---- nothing that already worked may change ----
check("an intact part still reads 100% at full coverage",
      hits(PAD + AM + PAD, "AmCyan")[0]["pident"] == 100.0,
      str(hits(PAD + AM + PAD, "AmCyan")[:1]))

import random

random.seed(11)
_SUB = {"A": "C", "C": "G", "G": "T", "T": "A"}
_q = list(AM)
for _i in random.sample(range(len(AM)), 20):
    _q[_i] = _SUB[_q[_i]]
_h = hits(PAD + "".join(_q) + PAD, "AmCyan")
check("20 scattered substitutions still read full coverage and no indel",
      _h and _h[0]["cov"] > 0.99 and not _h[0].get("indel"),
      str([(h["pident"], round(h["cov"], 3), h.get("indel")) for h in _h]))

import subprocess

p = subprocess.run([sys.executable, "katana_build.py",
                    "specs/pSense-Nit.spec.yaml", "--dry-run"],
                   cwd=ROOT, capture_output=True, text=True, timeout=600)
check("the sealed construct hash is unchanged",
      "796e94a0ea2452edd2ce59ca30b8f28fea232b37ab2a036714239069fd1196f5" in p.stdout,
      p.stdout[-200:])

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
