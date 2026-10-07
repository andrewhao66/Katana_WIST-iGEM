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

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
