"""test_terminal_divergence.py — a diverged end must not read as a perfect match.

Run: python3 tests/test_terminal_divergence.py

Found by an independent Codex review, reproduced, and worse than the finding said.

A full-length B0015 with its last eight bases substituted was reported as:

    100.0% identity, coverage 0.938

Both numbers are wrong, in opposite directions. The part IS full length -- the coverage
says truncated. The part is NOT a perfect match -- the identity says it is. And the
second error is the dangerous one: the eight substitutions become INVISIBLE. A student
whose terminator picked up a cloning scar or a mis-designed primer at its 3' end is told
the part matches the reference perfectly.

The cause is inherent to the maximal-scoring segment: under +1 match / -1 mismatch, a
trailing run of mismatches always lowers the score, so Kadane clips it. Then identity is
measured over what survived the clip, which by construction matches well.

My Phase 1 commit claimed "a full-length part with scattered mutations keeps its whole
span". That was true, and it was tested only with SCATTERED mutations -- the one
distribution the clip handles. The same blind spot as the bug before it: I tested the
easy case and wrote the general claim.

What cannot be fixed, and is not pretended otherwise: sequence alone does not distinguish
"the last eight bases were substituted" from "the last eight bases were replaced by eight
unrelated ones". They are the same observation. So the tool reports what it can defend --
the reference's first 121 bases match, its last 8 do not, and the construct has bases
there -- and does not claim a perfect match.

The design: ACCEPTANCE still uses the clipped score, which is what keeps a genuinely
truncated part from vanishing under the identity floor (the Phase 1 defect). The REPORTED
identity is measured over the reference's own span, so a diverged end lowers it.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "kagami"))

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


REFS = kg_refs.REFERENCE_PARTS
_by_id = {r["id"]: r["seq"] for r in REFS if r.get("seq")}
B15 = kg_refs.normalise(_by_id["B0015"])
L = len(B15)
SUB = {"A": "C", "C": "G", "G": "T", "T": "A"}
PAD = "T" * 120


def hits(query, sid="B0015"):
    return [h for h in sm.identify_hits(query, REFS) if h["sid"] == sid]


def mutate(seq, positions):
    out = list(seq)
    for i in positions:
        out[i] = SUB[out[i]]
    return "".join(out)


print("terminal divergence")
check("B0015 is %d bp" % L, L == 129, L)

# ---- substitutions at the END must lower the reported identity ----
for n in (2, 4, 8, 12):
    seq = mutate(B15, range(L - n, L))
    true_id = 100.0 * (L - n) / L
    h = hits(PAD + seq + PAD)
    check("%2d substitutions at the 3' end: identity reads about %.1f%%, not 100%%"
          % (n, true_id),
          h and abs(h[0]["pident"] - true_id) < 1.5,
          "%.1f%% id, cov %.3f" % (h[0]["pident"], h[0]["cov"]) if h else "no hit")

# ---- and at the START ----
for n in (4, 8):
    seq = mutate(B15, range(n))
    true_id = 100.0 * (L - n) / L
    h = hits(PAD + seq + PAD)
    check("%2d substitutions at the 5' end: identity reads about %.1f%%"
          % (n, true_id),
          h and abs(h[0]["pident"] - true_id) < 1.5,
          "%.1f%% id, cov %.3f" % (h[0]["pident"], h[0]["cov"]) if h else "no hit")

# ---- scattered mutations must keep working exactly as before ----
import random

random.seed(3)
for n in (2, 6, 12):
    seq = mutate(B15, random.sample(range(L), n))
    true_id = 100.0 * (L - n) / L
    h = hits(PAD + seq + PAD)
    check("%2d scattered mutations still read %.1f%% at full coverage"
          % (n, true_id),
          h and abs(h[0]["pident"] - true_id) < 1.5 and h[0]["cov"] > 0.99,
          "%.1f%% id, cov %.3f" % (h[0]["pident"], h[0]["cov"]) if h else "no hit")

# ---- a perfect part must still read perfectly ----
h = hits(PAD + B15 + PAD)
check("an unmutated B0015 still reads 100% identity at full coverage",
      h and h[0]["pident"] == 100.0 and h[0]["cov"] > 0.99,
      "%.1f%% id, cov %.3f" % (h[0]["pident"], h[0]["cov"]) if h else "no hit")

# ---- the clipped extent is still reported, because it is what finds truncation ----
# This is the Phase 1 defect's guard: a part present at 103 of 129 bases mid-construct
# must NOT read as full coverage.
for keep in (0.9, 0.8, 0.7, 0.6):
    n = int(L * keep)
    h = hits(PAD + B15[:n] + PAD)
    check("truncated to %d/%d bases still reports coverage near %.2f"
          % (n, L, keep),
          h and abs(h[0]["cov"] - keep) < 0.04,
          "%.1f%% id, cov %.3f" % (h[0]["pident"], h[0]["cov"]) if h else "no hit")

# ---- and the two measures are both available, so the audit can tell them apart ----
_end = hits(PAD + mutate(B15, range(L - 8, L)) + PAD)
_trunc = hits(PAD + B15[:121] + PAD)
_fmt = lambda h: {k: h[0].get(k) for k in ("pident", "core_pident", "cov")} if h else None
check("both measures are present in the hit record",
      _end and _trunc and _end[0].get("core_pident") is not None
      and _trunc[0].get("core_pident") is not None,
      "end: %s | trunc: %s" % (_fmt(_end), _fmt(_trunc)))
check("the clipped segment never matches WORSE than the whole span",
      _end and _trunc
      and _end[0]["core_pident"] >= _end[0]["pident"]
      and _trunc[0]["core_pident"] >= _trunc[0]["pident"],
      "end: %s | trunc: %s" % (_fmt(_end), _fmt(_trunc)))
# The gap between the two is what tells the shapes apart: a diverged end matches
# PERFECTLY over the part that is left, so the gap is wide. A truncation matches about as
# well either way, so the gap is narrow. Neither reading is a guess about the cause.
_gap_end = _end[0]["core_pident"] - _end[0]["pident"] if _end else 0
_gap_trunc = _trunc[0]["core_pident"] - _trunc[0]["pident"] if _trunc else 0
check("the gap between them is wider for a diverged end than for a truncation "
      "(%.1f vs %.1f)" % (_gap_end, _gap_trunc), _gap_end > _gap_trunc,
      "end: %s | trunc: %s" % (_fmt(_end), _fmt(_trunc)))

# ---- a part at the very edge of the query, where the reference runs off ----
# Only part of the reference can be compared at all, and that must not be read as
# divergence of the part.
h = hits(B15[40:] + PAD)
check("a part whose 5' end runs off the start of the query is still found",
      bool(h), "no hit")
if h:
    check("and it is reported as partial coverage, not low identity",
          h[0]["pident"] > 95.0 and h[0]["cov"] < 0.75,
          "%.1f%% id, cov %.3f" % (h[0]["pident"], h[0]["cov"]))

# ---- and the message a person reads must say which reading is which ----
# The old one said "Only 121/129 bp present", which is a claim about the construct, and
# for a diverged end it is false: those bases ARE present, they just differ. Rule 4 of
# this project: report both readings and label which is which, do not resolve it.
import tempfile

sys.path.insert(0, os.path.join(ROOT, "kagami"))
import kg_audit
import kg_identify
import kg_parse

_FULL = list(kg_refs.REFERENCE_PARTS)


def truncation_finding(seq):
    """Audit `seq` against B0015 alone, and return its truncation Finding or None."""
    kg_refs.REFERENCE_PARTS[:] = [r for r in _FULL if r["id"] == "B0015"]
    if hasattr(kg_refs, "tier"):
        kg_refs.tier.__defaults__[0].clear()
    try:
        d = tempfile.mkdtemp(prefix="trunc_")
        path = os.path.join(d, "t.fasta")
        with open(path, "w", encoding="utf-8") as f:
            f.write(">t\n" + seq + "\n")
        record = kg_parse.parse(path)
        status = {}
        with tempfile.TemporaryDirectory() as wd:
            blocks = kg_identify.identify(record, wd, status=status)
        found = kg_audit.audit(record, blocks, identify_status=status)
        hit = [f for f in found if f.category == "truncation"]
        return (hit[0] if hit else None,
                [b for b in blocks if b.ident_id == "B0015"])
    finally:
        kg_refs.REFERENCE_PARTS[:] = _FULL
        if hasattr(kg_refs, "tier"):
            kg_refs.tier.__defaults__[0].clear()


# A: substitutions at the end, mid-construct. The bases are there and differ.
_f, _bl = truncation_finding(PAD + mutate(B15, range(L - 8, L)) + PAD)
check("a diverged end raises a truncation FLAG", _f is not None)
if _f:
    check("and it says how many bases match and how many do not",
          "121 of its 129" in _f.summary and "8 do not" in _f.summary, _f.summary)
    check("and that those bases are PRESENT but differ",
          "present in your sequence but differ" in _f.detail, _f.detail[:120])
    check("and it gives both identity readings",
          "93.8% identity" in _f.detail and "100.0%" in _f.detail, _f.detail[:200])
    check("and it says the cause cannot be told from the sequence",
          "cannot be told from the sequence" in _f.detail, _f.detail[-120:])
    check("and it does NOT claim the bases are missing",
          "present." not in _f.detail.replace("present in your", ""), _f.detail[:150])

# B: the part runs off the end of the submitted sequence. The bases really are absent.
_f, _bl = truncation_finding(PAD + B15[:103])
check("a part running off the end of the sequence raises a truncation FLAG",
      _f is not None)
if _f:
    check("and that one DOES say the bases are not in the sequence at all",
          "in this sequence at all" in _f.detail, _f.detail[:150])
    check("and says the rest runs past its end", "runs past its end" in _f.detail,
          _f.detail[-80:])
    check("and the block records that the reference did not fit",
          _bl and _bl[0].ref_in_query is False,
          str([(b.ident_id, b.ref_in_query) for b in _bl]))

# C: internal truncation mid-construct -- the Phase 1 defect's own case.
_f, _bl = truncation_finding(PAD + B15[:103] + PAD)
check("an internally truncated part still raises a truncation FLAG", _f is not None)
if _f:
    check("and its coverage is still about 0.80, not 1.0",
          _bl and abs(_bl[0].coverage - 0.80) < 0.03,
          str([(b.ident_id, b.coverage) for b in _bl]))
    check("and its reported identity is no longer a perfect score",
          _bl and _bl[0].pident < 95.0, str([(b.ident_id, b.pident) for b in _bl]))

# ---- the oracle construct hashes must not move ----
# Identity and coverage are reported numbers, not inputs to the seal. If any of this had
# changed a built sequence, that would be a different and much worse problem.
import subprocess

p = subprocess.run([sys.executable, "katana_build.py",
                    "specs/pSense-Nit.spec.yaml", "--dry-run"],
                   cwd=ROOT, capture_output=True, text=True, timeout=600)
check("the sealed construct hash is unchanged by all of this",
      "796e94a0ea2452edd2ce59ca30b8f28fea232b37ab2a036714239069fd1196f5" in p.stdout,
      p.stdout[-200:])

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
