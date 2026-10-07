"""test_identify.py — oracle tests for pure-Python part identification.

Run: python3 test_identify.py

These are ORACLE tests, not a differential comparison against blastn. Each input is
built from a known reference with a known number of bases removed or mutated, so the
expected identity and coverage follow from the construction. That makes the suite
correct on a machine with no BLAST+ installed, which is every machine this software
is meant to run on.
"""
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import kg_refs
import kg_seedmatch

N = kg_refs.normalise
R = kg_refs.by_id()
PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  [" + detail + "]") if detail else ""))


def mutate(seq, n, seed):
    """Change exactly n bases. Seeded, so the expected identity is exact."""
    rng = random.Random(seed)
    out = list(seq)
    for pos in rng.sample(range(len(out)), n):
        out[pos] = rng.choice([c for c in "ACGT" if c != out[pos]])
    return "".join(out)


def best(hits, part_id):
    """The hit for part_id with the greatest coverage, or None."""
    same = [h for h in hits if h["sid"] == part_id]
    if not same:
        return None
    return max(same, key=lambda h: (h["cov"], h["pident"]))


# A promoter plus a neutral pad, so the part under test is never at position 1 and
# the surrounding context is realistic.
LEAD = N(R["J23116"]["seq"]) + "CACAACACTTGCAACGTTACGATCAGTTGCAACGTAC"

print("Katana identifier — oracle tests")

B0015 = N(R["B0015"]["seq"])          # 129 bp terminator
SFGFP = N(R["sfGFP"]["seq"])          # 720 bp reporter

# ---- full-length parts are found at 100% / 100% ----
hits = kg_seedmatch.identify_hits(LEAD + B0015, kg_refs.REFERENCE_PARTS)
h = best(hits, "B0015")
check("full-length B0015 is found", h is not None)
check("full-length B0015 is 100% identity", h is not None and h["pident"] == 100.0)
check("full-length B0015 is 100% coverage", h is not None and abs(h["cov"] - 1.0) < 0.005)

hits = kg_seedmatch.identify_hits(LEAD + SFGFP, kg_refs.REFERENCE_PARTS)
h = best(hits, "sfGFP")
check("full-length sfGFP is found", h is not None)
check("full-length sfGFP is 100%/100%",
      h is not None and h["pident"] == 100.0 and abs(h["cov"] - 1.0) < 0.005)

# ---- truncation: coverage must report the fraction present ----
for keep, want_cov in ((103, 103 / 129.0), (77, 77 / 129.0)):
    hits = kg_seedmatch.identify_hits(LEAD + B0015[:keep], kg_refs.REFERENCE_PARTS)
    h = best(hits, "B0015")
    check("B0015 truncated to %d bp is found" % keep, h is not None)
    check("B0015 truncated to %d bp reports cov %.2f" % (keep, want_cov),
          h is not None and abs(h["cov"] - want_cov) < 0.02,
          "got %.3f" % h["cov"] if h else "no hit")
    check("B0015 truncated to %d bp is still 100%% identity" % keep,
          h is not None and h["pident"] == 100.0)

hits = kg_seedmatch.identify_hits(LEAD + SFGFP[:648], kg_refs.REFERENCE_PARTS)
h = best(hits, "sfGFP")
check("sfGFP truncated to 90% reports cov 0.90",
      h is not None and abs(h["cov"] - 0.90) < 0.02)

# ---- point mutations: identity must drop, coverage must NOT ----
# A full-length part with mutations is not truncated. Reporting reduced coverage here
# raises a false truncation FLAG, which is the bug the full-reference alignment fixes.
for part, seq, nmut in (("B0015", B0015, 3), ("sfGFP", SFGFP, 10), ("sfGFP", SFGFP, 40)):
    want_id = round(100.0 * (len(seq) - nmut) / len(seq), 1)
    hits = kg_seedmatch.identify_hits(LEAD + mutate(seq, nmut, seed=nmut),
                                      kg_refs.REFERENCE_PARTS)
    h = best(hits, part)
    check("%s +%d mutations is found" % (part, nmut), h is not None)
    check("%s +%d mutations reports %.1f%% identity" % (part, nmut, want_id),
          h is not None and abs(h["pident"] - want_id) < 0.3,
          "got %.1f" % h["pident"] if h else "no hit")
    check("%s +%d mutations keeps 100%% coverage (not truncated)" % (part, nmut),
          h is not None and abs(h["cov"] - 1.0) < 0.02,
          "got %.3f" % h["cov"] if h else "no hit")

# ---- short parts: the B0032/B0034 class, found by exact match ----
B0034 = N(R["B0034"]["seq"])          # 12 bp, A/G only
check("B0034 is 12 bp as assumed by this suite", len(B0034) == 12)
hits = kg_seedmatch.identify_hits(LEAD + B0034 + "TTGCAACGTTACGATCAG",
                                  kg_refs.REFERENCE_PARTS)
ids = set(h["sid"] for h in hits)
check("a 12 bp RBS is identified at all", "B0034" in ids or
      any(N(R[i]["seq"]) == B0034 for i in ids if i in R))

# B0034 contains only A and G. Purine richness IS the Shine-Dalgarno function, so a
# low-complexity rule of "<= 2 distinct bases" deletes the single most important part
# class for the mislabel bug this project was built around.
check("B0034 is NOT rejected as low complexity",
      not kg_seedmatch.low_complexity(B0034))

# ---- low-complexity references must be rejected ----
check("a pure homopolymer IS rejected as low complexity",
      kg_seedmatch.low_complexity("AAAAAAAAAA"))
check("a 95%-one-base run IS rejected as low complexity",
      kg_seedmatch.low_complexity("AAAAAAAAAAAAAAAAAAAG"))

poly = "ATG" + "A" * 36 + "TAA"
hits = kg_seedmatch.identify_hits(poly, kg_refs.REFERENCE_PARTS)
homopolymer_ids = [h["sid"] for h in hits
                   if len(set(N(R[h["sid"]]["seq"]))) == 1]
check("no homopolymer reference is reported for a poly-A query",
      not homopolymer_ids, ", ".join(homopolymer_ids[:4]))

# ---- reverse strand ----
rc_b0015 = kg_seedmatch.revcomp(B0015)
hits = kg_seedmatch.identify_hits(LEAD + rc_b0015, kg_refs.REFERENCE_PARTS)
h = best(hits, "B0015")
check("B0015 on the reverse strand is found", h is not None)
check("B0015 on the reverse strand is marked strand -1",
      h is not None and h["strand"] == -1)
check("B0015 on the reverse strand is 100%/100%",
      h is not None and h["pident"] == 100.0 and abs(h["cov"] - 1.0) < 0.005)

# ---- Review Focus 4: GenBank ORIGIN blocks are lowercase ----
# Two vehicles on purpose: a 12 bp reference exercises the exact path and a 129 bp one
# exercises the seeded path, and case handling lives in different code in each.
_lc_short = set(x["sid"] for x in kg_seedmatch.identify_hits(
    ("TTTT" + B0034 + "TTTT").lower(), kg_refs.REFERENCE_PARTS))
check("a lowercase query is identified on the exact path",
      "B0034" in _lc_short or any(N(R[i]["seq"]) == B0034 for i in _lc_short if i in R))

hits = kg_seedmatch.identify_hits((LEAD + B0015).lower(), kg_refs.REFERENCE_PARTS)
h = best(hits, "B0015")
check("a lowercase query is identified on the seeded path",
      h is not None and h["pident"] == 100.0 and abs(h["cov"] - 1.0) < 0.005)

# A short reference matches when its sequence OR its reverse complement occurs, so the
# set of ids reported for a 12 bp RBS is the identical re-deposits plus their revcomp
# twins. Naming one of them silently would claim more certainty than the evidence has.
_b34_rc = kg_seedmatch.revcomp(B0034)
_ids = set(x["sid"] for x in
           kg_seedmatch.identify_hits("TTTT" + B0034 + "TTTT", kg_refs.REFERENCE_PARTS))
check("every short-path match is the reference or its reverse complement",
      _ids and all(N(R[i]["seq"]) in (B0034, _b34_rc) for i in _ids if i in R))

# ---- an INTERNAL truncation must report the truncation, not 100% coverage ----
# Found by the Codex review pass, 2026-10-07, and it is the project's cardinal failure:
# a truncated part reported as full-length. Every truncation case above puts the
# truncated part at the END of the query, where the alignment window clamps against the
# query boundary and coverage comes out right by accident. Put unrelated sequence after
# it instead and the window spans the reference's full length regardless, so coverage
# read 1.000 for a part that was 80% present -- and the truncation FLAG (cov < 0.95)
# never fired.
_unrelated = "CGTACGTACGTTGCAACGATCAGTTGCAACGTACGATCAGT" * 2      # 82 bp, not a part
for _keep in (103, 77):
    _want_cov = _keep / 129.0
    hits = kg_seedmatch.identify_hits(LEAD + B0015[:_keep] + _unrelated,
                                      kg_refs.REFERENCE_PARTS)
    h = best(hits, "B0015")
    check("an internal B0015 truncated to %d bp is still found" % _keep, h is not None)
    check("an internal truncation to %d bp reports cov %.2f, not 1.0" % (_keep, _want_cov),
          h is not None and abs(h["cov"] - _want_cov) < 0.06,
          "got %.3f" % h["cov"] if h else "no hit")
    check("an internal truncation to %d bp is below the 0.95 truncation threshold" % _keep,
          h is not None and h["cov"] < 0.95,
          "got %.3f" % h["cov"] if h else "no hit")

# The guard on the above: clipping unrelated flanks must NOT clip a genuinely
# full-length part whose bases are merely mutated. If it did, every mutated part would
# be reported as truncated -- the opposite error, and just as wrong.
for _part, _seq, _nmut in (("B0015", B0015, 3), ("sfGFP", SFGFP, 40)):
    hits = kg_seedmatch.identify_hits(
        LEAD + mutate(_seq, _nmut, seed=_nmut) + _unrelated, kg_refs.REFERENCE_PARTS)
    h = best(hits, _part)
    check("a mutated full-length %s followed by unrelated sequence keeps cov 1.0 (+%d mut)"
          % (_part, _nmut),
          h is not None and abs(h["cov"] - 1.0) < 0.02,
          "got %.3f" % h["cov"] if h else "no hit")

# ---- a part used TWICE must be identified twice ----
# architecture.order explicitly permits a repeated id, and pAP-Logic's own version
# history is about a repeated RBS that formed a 43 bp direct repeat. Reporting the
# second occurrence as an unidentified block means a mislabel on it is never checked:
# the identity comparison skips blocks with no ident_id.
_pad2 = "CGTACGTTGCAACGATCAGTTGCAACGTACGATCAGT" * 3          # 111 bp, not a part
hits = kg_seedmatch.identify_hits(B0015 + _pad2 + B0015, kg_refs.REFERENCE_PARTS)
# Forward strand, full coverage only. B0015 is a terminator, so its hairpin is partly
# self-complementary and the reverse strand yields a partial match at a third position;
# counting that would let this assertion pass for the wrong reason.
_b15 = sorted((h for h in hits
               if h["sid"] == "B0015" and h["strand"] == 1 and h["cov"] > 0.95),
              key=lambda h: h["qstart"])
check("a reference used twice is reported twice on the forward strand", len(_b15) == 2,
      "reported %d full forward hit(s): %s"
      % (len(_b15), ", ".join("%d-%d cov %.2f" % (h["qstart"], h["qend"], h["cov"])
                              for h in hits if h["sid"] == "B0015")))
check("the two occurrences are at the two expected positions",
      len(_b15) == 2 and _b15[0]["qstart"] == 1
      and _b15[1]["qstart"] == len(B0015) + len(_pad2) + 1,
      ", ".join(str(h["qstart"]) for h in _b15))

# ---- coverage must be right wherever the part sits ----
# The maximal-scoring-segment extension computes coordinates four ways at once (query
# window clamping, reference offset, strand, and the clipped segment's own bounds), and
# an error in any one of them shows up as a wrong coverage. These pin each case
# separately, so a future change that breaks one of them names which.
_UN = "CGTACGTTGCAACGATCAGTTGCAACGTACGATCAGT" * 3          # 111 bp, not a part


def _cov(query, part_id, strand=None):
    """Greatest coverage reported for part_id, optionally on one strand."""
    got = [h for h in kg_seedmatch.identify_hits(query, kg_refs.REFERENCE_PARTS)
           if h["sid"] == part_id and (strand is None or h["strand"] == strand)]
    return max((h["cov"] for h in got), default=None)


for _name, _query, _part, _strand, _want in (
        ("at the very start of the query", B0015 + _UN, "B0015", 1, 1.0),
        ("with its 5' end cut off", B0015[26:] + _UN, "B0015", 1, 103 / 129.0),
        ("cut off by the end of the query", _UN + B0015[:90], "B0015", 1, 90 / 129.0),
        ("truncated on the reverse strand",
         _UN + kg_seedmatch.revcomp(B0015[:103]) + _UN, "B0015", -1, 103 / 129.0),
        ("that is long and truncated internally", _UN + SFGFP[:500] + _UN, "sfGFP", 1,
         500 / 720.0),
        ("full length with unrelated sequence on both sides", _UN + B0015 + _UN,
         "B0015", 1, 1.0)):
    _got = _cov(_query, _part, _strand)
    check("coverage is right for a part %s" % _name,
          _got is not None and abs(_got - _want) < 0.06,
          "want %.3f got %s" % (_want, "none" if _got is None else "%.3f" % _got))

# Identity must fall as mutations accumulate while coverage stays pinned at 1.0. A part
# that is merely mutated is not truncated, and conflating the two is the error the
# maximal-scoring segment exists to avoid in both directions.
_prev_id = 101.0
_grad_ok = True
for _nmut in (0, 5, 15, 30, 60, 100):
    _hits = [h for h in kg_seedmatch.identify_hits(
        _UN + mutate(SFGFP, _nmut, seed=_nmut) + _UN, kg_refs.REFERENCE_PARTS)
        if h["sid"] == "sfGFP"]
    if not _hits:
        _grad_ok = False
        break
    _h = max(_hits, key=lambda h: h["cov"])
    if abs(_h["cov"] - 1.0) > 0.02 or _h["pident"] > _prev_id + 0.1:
        _grad_ok = False
        break
    _prev_id = _h["pident"]
check("identity falls with mutations while coverage stays 1.0", _grad_ok)

# ---- Review Focus 1: a query shorter than the seed length ----
for tiny in ("", "A", "ATGC", "ATGCATGCA"):
    try:
        got = kg_seedmatch.identify_hits(tiny, kg_refs.REFERENCE_PARTS)
        ok = got == []
        why = "returned %d hits" % len(got)
    except Exception as exc:
        ok = False
        why = "raised %s: %s" % (type(exc).__name__, exc)
    check("a %d bp query returns no hits without raising" % len(tiny), ok, why)

# ---- Review Focus 2: N and IUPAC ambiguity codes ----
# add_part.py admits ACGTNRYKMSWBDHV, so a sealed part can legitimately carry them.
# An ambiguity code must reduce identity, never crash and never be scored as a match.
ambiguous = B0015[:40] + "N" + B0015[41:]
try:
    hits = kg_seedmatch.identify_hits(LEAD + ambiguous, kg_refs.REFERENCE_PARTS)
    h = best(hits, "B0015")
    ok = h is not None and h["pident"] < 100.0 and abs(h["cov"] - 1.0) < 0.02
    why = ("id %.1f cov %.3f" % (h["pident"], h["cov"])) if h else "no hit"
except Exception as exc:
    ok, why = False, "raised %s: %s" % (type(exc).__name__, exc)
check("one N reduces identity but not coverage, without raising", ok, why)

try:
    kg_seedmatch.identify_hits("ACGTRYKMSWBDHVN" * 4, kg_refs.REFERENCE_PARTS)
    ok, why = True, ""
except Exception as exc:
    ok, why = False, "raised %s: %s" % (type(exc).__name__, exc)
check("an all-IUPAC query does not raise", ok, why)

# ---- Review Focus 3: a reference much longer than the query ----
# bARGSer_operon is 16,474 bp. A 300 bp query containing part of it must report the
# small fraction of the reference it covers, never 1.0.
long_ref = None
for r in kg_refs.REFERENCE_PARTS:
    if len(N(r["seq"])) > 5000:
        long_ref = r
        break
if long_ref is None:
    check("a >5 kb reference exists to test against (SKIPPED)", True)
else:
    piece = N(long_ref["seq"])[1000:1300]
    hits = kg_seedmatch.identify_hits(piece, kg_refs.REFERENCE_PARTS)
    h = best(hits, long_ref["id"])
    check("a 300 bp slice of a long reference is found", h is not None)
    check("its coverage is the covered fraction, not 1.0",
          h is not None and h["cov"] < 0.1,
          "got %.3f" % h["cov"] if h else "no hit")

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
