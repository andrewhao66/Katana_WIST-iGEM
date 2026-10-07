# Phase 1: Remove External Dependencies — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the engine and the auditor run with nothing installed — no NCBI BLAST+, no pip packages — without losing any identification capability.

**Architecture:** Replace `kg_identify`'s blastn shell-out with a pure-Python hybrid identifier (exact `str.find` for references ≤ 25 bp, k-mer seeded full-reference alignment above that), vendor PyYAML into `_vendor/`, and split `requirements.txt` so the core requires nothing. blastn becomes an explicit opt-in deep search rather than an automatic path, so results cannot differ between machines.

**Tech Stack:** Python 3.9+, standard library only. Vendored PyYAML 6.0.2 (pure Python). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-07-katana-unification-design.md` — this plan implements migration steps 1 and 2 plus the documentation defects in §9.

## Global Constraints

- Python 3.9+ floor. No f-string `=`, no `match`, no `X | Y` type unions at runtime.
- **Standard library only** in every module touched here. No `subprocess`, no `shutil.which` on the default path, no network.
- `seq_sha256 = sha256(seq.upper().encode("ascii"))` — the hashing convention is frozen (spec §12).
- `LOCK.tsv`, `LOCK.root`, sealed part filenames and the Design Spec schema are byte-compatible (spec §12).
- The shipped `parts-library/` is never modified.
- Verdict tokens `PASS` `FLAG` `FAIL` `REVIEW` `NOTE` `SKIP` `BLOCK` `SEALED` are API, not prose. Do not reword them.
- All 107 existing assertions stay green: `python3 verify.py` (8), `python3 test_determinism.py` (11), `python3 kagami/tests.py` (88).
- Every task ends in a local commit on branch `unify`. **Nothing is pushed to `origin` (GitLab) at any point.**
- Product name is **Katana** (spec §11).

## Review Focus

Five input classes the spec implies but no task's own happy-path tests exercise. Each has its pinning test assigned to the task that owns the code.

1. **A query shorter than k (12 bp)** — a student pastes a 10 bp sequence. Must return no hits and must not raise `ValueError` from an empty range. → Task 3, Steps 5–6.
2. **`N` and IUPAC ambiguity codes in the query** — `add_part.py` accepts `ACGTNRYKMSWBDHV`, so sealed parts can contain them. A k-mer containing `N` must simply not match rather than crash, and identity must be computed, not skipped. → Task 3, Steps 7–8.
3. **A reference longer than the query** — the 16,474 bp `bARGSer_operon` against a 300 bp query. Coverage must be the fraction of the reference actually covered (small), never 1.0. → Task 3, Steps 9–10.
4. **Lowercase input** — GenBank `ORIGIN` blocks are lowercase. Identification must normalise before comparing, or every real `.gb` file silently finds nothing. → Task 2, Steps 5–6.
5. **A 16 kb query against the full 18,538-reference set** — the stride filter must keep this under 30 s, or the GUI appears frozen on a real operon. → Task 4, Step 7.

---

## File Structure

| File | Responsibility |
|---|---|
| `kagami/kg_seedmatch.py` | **Create.** Pure-Python identification: `identify_hits(query, refs)` returning hits in `kg_identify._blast()`'s shape. Owns the k, stride, threshold and low-complexity constants. |
| `kagami/test_identify.py` | **Create.** Standalone runnable oracle suite for the identifier, in `kagami/tests.py`'s plain-assert style. |
| `kagami/kg_identify.py` | **Modify.** Default to `kg_seedmatch`; `identification` always runs; blastn demoted to opt-in deep search. |
| `kagami/kagami.py` | **Modify.** Add `--deep`; drop the "BLAST+ unavailable" startup line from the default path. |
| `kagami/kagami_gui.py` | **Modify.** Delete the missing-BLAST+ banner (no longer true). |
| `_vendor/yaml/` | **Create.** Vendored PyYAML 6.0.2, pure Python, `.so` removed. |
| `_vendor/__init__.py`, `core_path.py` | **Create.** One place that prepends `_vendor` to `sys.path`. |
| `katana_build.py`, `check_design.py` | **Modify.** Import yaml through the vendor shim. |
| `requirements.txt`, `requirements-optional.txt` | **Modify / create.** Core requires nothing; extras fully pinned. |
| `README.md`, `kagami/README.md`, `kagami/refs/ATTRIBUTION.md` | **Modify.** The §9 documentation defects. |
| `.gitlab-ci.yml` | **Modify.** Add `test_identify.py`; drop the no-blastn special-casing rationale. |

---

## Task 0: Working branch

**Files:** none (git only)

- [ ] **Step 1: Create the branch and commit the design documents**

```bash
cd /Users/andrewhao/Desktop/katana
git checkout -b unify
git add CODE-REPORT.md docs/
git commit -m "docs: code review report, unification spec, phase 1 plan

Baseline for the unification work. No source changes.

Spec:  docs/superpowers/specs/2026-10-07-katana-unification-design.md
Plan:  docs/superpowers/plans/2026-10-07-phase1-remove-external-dependencies.md
Review: CODE-REPORT.md"
```

- [ ] **Step 2: Record the baseline assertion counts**

Run each and note the number, so a later bisect can tell a regression from a pre-existing failure:

```bash
python3 verify.py            | tail -3
python3 kagami/tests.py      | tail -1
```

Expected: `OK — the library is intact…` with `8/8 checks passed`, and `88 passed, 0 failed`.

`test_determinism.py` needs PyYAML, which is not installed system-wide. Record it as deferred to Task 6, where the vendored parser makes it runnable with no venv.

- [ ] **Step 3: Commit nothing (verification only)**

No commit — this step produces a recorded number, not a change.

---

## Task 1: Oracle tests for the identifier (RED)

These tests are the safety net for the whole task group, so they come first and must fail first. They are **oracle** tests, not differential tests against blastn: the expected identity and coverage are derived from how the input was constructed, so they are correct whether or not blastn is installed.

**Files:**
- Create: `kagami/test_identify.py`

**Interfaces:**
- Consumes: `kg_refs.by_id()`, `kg_refs.normalise()` (existing).
- Produces: nothing importable; a runnable suite exiting non-zero on failure.

- [ ] **Step 1: Write the failing test file**

```python
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
```

- [ ] **Step 2: Run it and verify it fails for the right reason**

```bash
cd /Users/andrewhao/Desktop/katana/kagami && python3 test_identify.py
```

Expected: `ModuleNotFoundError: No module named 'kg_seedmatch'`. That is the correct failure — the module does not exist yet.

- [ ] **Step 3: Commit the failing test**

```bash
git add kagami/test_identify.py
git commit -m "test: oracle suite for pure-Python part identification (RED)

Expected identity and coverage are derived from how each input is constructed,
not from a blastn baseline, so the suite is correct on a machine with no BLAST+.

Covers: full-length, truncation at 60/80/90%, point mutations at 94.4/97.7/98.6%,
12 bp short parts, reverse strand, and the low-complexity rules — including that
B0034 (AAAGAGGAGAAA, A/G only) must NOT be rejected, because purine richness is
the Shine-Dalgarno function rather than noise.

Fails with ModuleNotFoundError: kg_seedmatch does not exist yet. Step 1 of phase 1."
```

---

## Task 2: The short-reference exact path

**Files:**
- Create: `kagami/kg_seedmatch.py`
- Test: `kagami/test_identify.py` (already written)

**Interfaces:**
- Consumes: `kg_refs.normalise(seq) -> str`.
- Produces:
  - `revcomp(s: str) -> str`
  - `low_complexity(s: str) -> bool`
  - `identify_hits(query: str, refs: list[dict]) -> list[dict]` where each dict has keys
    `sid, pident, length, qstart, qend, strand, cov, bit` — identical to `kg_identify._blast()`'s
    output shape, with `qstart`/`qend` 1-based inclusive.

- [ ] **Step 1: Create the module with the constants and helpers**

```python
"""kg_seedmatch.py — pure-Python part identification.

Replaces the blastn shell-out in kg_identify. Measured against blastn on real
constructs: identical identity and coverage on full-length parts, on truncation at
60/80/90%, and on point mutations at 94.4/97.7/98.6% identity; roughly twice as fast,
because kg_identify rebuilt a BLAST database of 18,538 sequences on every single run.

Hybrid, because the reference length distribution forces it. Of 18,538 references, 894
are shorter than 25 bp and 123 are shorter than 12 bp, and short RBS parts are exactly
where the B0032/B0034 class of mislabel happens:

  references <= SHORT_MAX   direct exact match, C-speed via str.find, stricter than blastn
  references >  SHORT_MAX   k-mer seeding with stride filtering, then FULL-REFERENCE
                            alignment on the best diagonal

The full-reference alignment is load-bearing. Extending only to the last seed
under-reports coverage when a mutation falls near a part's end, which raised a FALSE
truncation FLAG on a full-length part (B0015 with 3 mutations read 89% coverage instead
of 100%). Aligning the whole reference against its query window fixes it exactly.

Output shape is identical to kg_identify._blast() so _tile() and everything downstream
are unchanged.
"""
import sys
from collections import defaultdict

try:
    import kg_refs
except ImportError:                      # running from another directory
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import kg_refs

K = 12                  # seed length for the long path
SHORT_MAX = 25          # references this long or shorter take the exact path
SHORT_MIN = 12          # shorter than this carries no identifying information
MIN_HIT = 25            # shortest alignment the long path guarantees to find
MIN_IDENT = 80.0        # below this, not reported at all

_COMP = str.maketrans("ACGTNacgtn", "TGCANtgcan")


def revcomp(s):
    return s.translate(_COMP)[::-1]


def low_complexity(s):
    """True when a sequence carries no identifying information.

    Deliberately NOT "two or fewer distinct bases": B0034 is AAAGAGGAGAAA, which
    contains only A and G, and purine richness is the Shine-Dalgarno sequence's
    FUNCTION — it base-pairs with the pyrimidine-rich 16S rRNA anti-SD. A rule that
    rejects two-base sequences deletes the most important part class for the mislabel
    bug this project exists to catch.
    """
    if not s:
        return True
    if len(set(s)) == 1:
        return True                      # pure homopolymer: AAAAAAAAAA
    top = max(s.count(b) for b in set(s))
    return top / float(len(s)) > 0.8     # one base overwhelmingly dominant


def _usable(ref):
    """A reference that can identify something."""
    return len(ref) >= SHORT_MIN and not low_complexity(ref)
```

- [ ] **Step 2: Add the exact path for short references**

Append to `kagami/kg_seedmatch.py`:

```python
def _short_hits(sid, ref, query, qrc, n):
    """Exact occurrences of a short reference, on both strands.

    Exact rather than approximate on purpose. For a 12 bp RBS, 'these are the same
    bases' and 'these are nearly the same bases' are different claims, and the audit's
    job is the first one.
    """
    out = []
    L = len(ref)
    for strand, hay in ((1, query), (-1, qrc)):
        start = hay.find(ref)
        while start >= 0:
            if strand == 1:
                qs, qe = start + 1, start + L
            else:
                qs, qe = n - (start + L) + 1, n - start
            out.append(dict(sid=sid, pident=100.0, length=L, qstart=qs, qend=qe,
                            strand=strand, cov=1.0, bit=2.0 * L))
            start = hay.find(ref, start + 1)
    return out


def identify_hits(query, refs):
    """Identify which references occur in `query`. Returns kg_identify._blast()'s shape."""
    q = kg_refs.normalise(query)
    n = len(q)
    if n < SHORT_MIN:
        return []                        # nothing in the set can identify this
    qrc = revcomp(q)

    hits = []
    for r in refs:
        ref = kg_refs.normalise(r.get("seq") or "")
        if not _usable(ref):
            continue
        if len(ref) <= SHORT_MAX:
            hits.extend(_short_hits(r["id"], ref, q, qrc, n))
    return hits
```

- [ ] **Step 3: Run the suite — the short and low-complexity tests must now pass**

```bash
cd /Users/andrewhao/Desktop/katana/kagami && python3 test_identify.py
```

Expected: the four low-complexity checks, `B0034 is 12 bp`, `a 12 bp RBS is identified at all`, and `no homopolymer reference is reported` all pass. Every full-length, truncation, mutation and reverse-strand check still **fails** — the long path does not exist yet.

- [ ] **Step 4: Verify the short path is genuinely exact, not accidental**

```bash
cd /Users/andrewhao/Desktop/katana/kagami && python3 -c "
import kg_refs, kg_seedmatch as S
N = kg_refs.normalise
b34 = N(kg_refs.by_id()['B0034']['seq'])
hits = S.identify_hits('TTTT' + b34 + 'TTTT', kg_refs.REFERENCE_PARTS)
ids = sorted(set(h['sid'] for h in hits))
print('refs matching B0034\\'s bases:', len(ids))
print('all are exactly that sequence:',
      all(N(kg_refs.by_id()[i]['seq']) == b34 for i in ids))
"
```

Expected: several ids (the sequence has identical re-deposits in the Registry mirror) and `all are exactly that sequence: True`.

- [ ] **Step 5: Confirm lowercase input works (Review Focus 4)**

Add to `kagami/test_identify.py`, immediately before the `print("\n%d passed` line:

```python
# ---- Review Focus 4: GenBank ORIGIN blocks are lowercase ----
hits = kg_seedmatch.identify_hits((LEAD + B0015).lower(), kg_refs.REFERENCE_PARTS)
h = best(hits, "B0015")
check("a lowercase query is identified identically",
      h is not None and h["pident"] == 100.0 and abs(h["cov"] - 1.0) < 0.005)
```

- [ ] **Step 6: Run and verify the lowercase test passes**

```bash
cd /Users/andrewhao/Desktop/katana/kagami && python3 test_identify.py 2>&1 | grep -i lowercase
```

Expected: `ok   a lowercase query is identified identically`. It passes because `identify_hits` calls `kg_refs.normalise`, which uppercases.

- [ ] **Step 7: Commit**

```bash
git add kagami/kg_seedmatch.py kagami/test_identify.py
git commit -m "feat: pure-Python identification, short-reference exact path

References <= 25 bp are matched exactly with str.find on both strands. Exact rather
than approximate on purpose: for a 12 bp RBS, 'the same bases' and 'nearly the same
bases' are different claims and the audit asks the first.

Low-complexity rejection drops pure homopolymers and sequences where one base exceeds
80%, but deliberately NOT 'two or fewer distinct bases' -- that rule deletes
B0034 (AAAGAGGAGAAA, A/G only), and purine richness is the Shine-Dalgarno function.

Short, low-complexity and lowercase assertions pass; long-path assertions still red.
Step 1 of phase 1."
```

---

## Task 3: The long-reference seeded path

**Files:**
- Modify: `kagami/kg_seedmatch.py`
- Test: `kagami/test_identify.py`

**Interfaces:**
- Consumes: everything from Task 2.
- Produces: no new public names; `identify_hits` gains the long-reference branch.

- [ ] **Step 1: Add the diagonal seeding and full-reference alignment**

Insert into `kagami/kg_seedmatch.py`, after `_short_hits` and before `identify_hits`:

```python
def _query_index(q, k):
    """k-mer -> positions in q. Built once per query; the query is small."""
    idx = defaultdict(list)
    for i in range(len(q) - k + 1):
        idx[q[i:i + k]].append(i)
    return idx


def _long_hits(sid, ref, q, qidx, n, k, stride):
    """Seed on a stride, then align the WHOLE reference on the best diagonal.

    Stride filtering is a q-gram guarantee: an exact match of length >= MIN_HIT
    contains (MIN_HIT - k + 1) consecutive k-mer start positions, so sampling that
    often cannot miss it. Halved, to stay robust when mismatches break up the run.
    """
    out = []
    L = len(ref)
    get = qidx.get
    for strand, s in ((1, ref), (-1, revcomp(ref))):
        # cheap rejection: does any sampled seed hit at all?
        seeded = False
        for i in range(0, L - k + 1, stride):
            if get(s[i:i + k]):
                seeded = True
                break
        if not seeded:
            continue

        # full scan of this one reference, grouping seeds by diagonal
        diags = defaultdict(int)
        for i in range(L - k + 1):
            h = get(s[i:i + k])
            if h:
                for qp in h:
                    diags[qp - i] += 1
        if not diags:
            continue
        d = max(diags.items(), key=lambda kv: kv[1])[0]   # d = qpos - refpos

        # The diagonal fixes the correspondence, so compare the whole reference
        # against its query window. Stopping at the last seed under-reports coverage
        # when a mutation sits near an end, which raises a false truncation FLAG.
        ws, we = d, d + L
        cs, ce = max(0, ws), min(n, we)
        span = ce - cs
        if span < MIN_HIT:
            continue
        qseg = q[cs:ce]
        sseg = s[cs - ws:ce - ws]
        matches = 0
        for a, b in zip(qseg, sseg):
            if a == b:
                matches += 1
        pident = 100.0 * matches / span
        if pident < MIN_IDENT:
            continue
        out.append(dict(sid=sid, pident=round(pident, 1), length=span,
                        qstart=cs + 1, qend=ce, strand=strand,
                        cov=span / float(L), bit=2.0 * matches))
    return out
```

- [ ] **Step 2: Wire the long path into `identify_hits` and de-duplicate**

Replace the body of `identify_hits` in `kagami/kg_seedmatch.py` with:

```python
def identify_hits(query, refs, k=K):
    """Identify which references occur in `query`. Returns kg_identify._blast()'s shape."""
    q = kg_refs.normalise(query)
    n = len(q)
    if n < SHORT_MIN:
        return []                        # nothing in the set can identify this
    qrc = revcomp(q)

    qidx = _query_index(q, k) if n >= k else {}
    stride = max(1, (MIN_HIT - k + 1) // 2)

    hits = []
    for r in refs:
        ref = kg_refs.normalise(r.get("seq") or "")
        if not _usable(ref):
            continue
        if len(ref) <= SHORT_MAX:
            hits.extend(_short_hits(r["id"], ref, q, qrc, n))
        elif qidx:
            hits.extend(_long_hits(r["id"], ref, q, qidx, n, k, stride))

    # One reference can seed on both strands at the same place (a palindrome, or a
    # self-complementary terminator). Keep the better reading rather than reporting
    # the same block twice.
    keep = {}
    for h in hits:
        key = (h["sid"], h["qstart"] // 10, h["qend"] // 10)
        cur = keep.get(key)
        if cur is None or (h["pident"], h["cov"]) > (cur["pident"], cur["cov"]):
            keep[key] = h
    return list(keep.values())
```

- [ ] **Step 3: Run the suite — everything must pass**

```bash
cd /Users/andrewhao/Desktop/katana/kagami && python3 test_identify.py
```

Expected: `0 failed`. In particular `B0015 +3 mutations keeps 100% coverage (not truncated)` must pass — that is the assertion that pins the full-reference alignment.

- [ ] **Step 4: Commit the working identifier**

```bash
git add kagami/kg_seedmatch.py
git commit -m "feat: pure-Python identification, long-reference seeded path

k-mer seeding with q-gram stride filtering, then FULL-REFERENCE alignment on the best
diagonal. Aligning the whole reference rather than extending to the last seed is what
keeps a full-length part with end-adjacent mutations at 100% coverage; the earlier
approach read 89% and would have raised a false truncation FLAG.

Oracle suite green: full-length, truncation 60/80/90%, mutations at 94.4/97.7/98.6%,
12 bp short parts, reverse strand, low complexity, lowercase. Step 1 of phase 1."
```

- [ ] **Step 5: Add the Review Focus 1 test — a query shorter than k**

Append to `kagami/test_identify.py`, before the final `print`:

```python
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
```

- [ ] **Step 6: Run it**

```bash
cd /Users/andrewhao/Desktop/katana/kagami && python3 test_identify.py 2>&1 | grep 'bp query returns'
```

Expected: four `ok` lines. They pass because of the `n < SHORT_MIN` guard added in Task 2.

- [ ] **Step 7: Add the Review Focus 2 test — `N` and IUPAC codes**

Append to `kagami/test_identify.py`, before the final `print`:

```python
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
```

- [ ] **Step 8: Run it**

```bash
cd /Users/andrewhao/Desktop/katana/kagami && python3 test_identify.py 2>&1 | grep -E 'IUPAC|one N'
```

Expected: both `ok`. The `N` breaks the k-mers covering it, but the surrounding seeds still fix the diagonal, and the full-reference alignment then scores `N` as one mismatch — so identity drops to 128/129 = 99.2% while coverage stays 1.0.

- [ ] **Step 9: Add the Review Focus 3 test — a reference longer than the query**

Append to `kagami/test_identify.py`, before the final `print`:

```python
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
```

- [ ] **Step 10: Run the whole suite**

```bash
cd /Users/andrewhao/Desktop/katana/kagami && python3 test_identify.py
```

Expected: `0 failed`.

- [ ] **Step 11: Commit the Review Focus tests**

```bash
git add kagami/test_identify.py
git commit -m "test: pin the identifier's edge inputs

Four input classes the happy path does not reach:
  - queries shorter than the 12 bp seed length return [] rather than raising
  - N and IUPAC codes reduce identity without crashing or inflating coverage
  - a reference longer than the query reports the covered fraction, never 1.0
  - lowercase GenBank ORIGIN input identifies identically

Step 1 of phase 1."
```

---

## Task 4: Wire `kg_identify` to the pure-Python path

**Files:**
- Modify: `kagami/kg_identify.py`
- Modify: `kagami/kagami.py`
- Test: `kagami/tests.py` (existing 88 assertions must stay green)

**Interfaces:**
- Consumes: `kg_seedmatch.identify_hits(query, refs) -> list[dict]`.
- Produces: `kg_identify.identify(record, workdir, status=None, deep=False) -> list[Block]`. The
  `deep` parameter is new and defaults to `False`; existing two- and three-argument callers are
  unaffected.

**Deliberate refinement of the spec.** Spec §4.5 says blastn is "used when present". Making it
automatic means two machines produce different findings for the same file, which is the
works-on-my-machine failure the engine's own `--expect-root` flag exists to prevent. So blastn
becomes an **explicit opt-in** (`--deep`), not an ambient one. One default path, one documented
escape hatch.

- [ ] **Step 1: Replace the identification branch**

In `kagami/kg_identify.py`, replace the `id_hits = []` block in `identify()` (currently lines
282–312, from `id_hits = []` down to the end of the `else:` clause) with:

```python
    id_hits = []
    if len(seq) < 8:
        # Not a failure: there is nothing to identify. ran stays True so a 4 bp input
        # does not produce an alarming "identification did not run" on top of its real
        # findings.
        pass
    elif deep and _have_blast():
        # Opt-in deep search. blastn does gapped local alignment, so it can find
        # distant homologs the seeded path cannot. It is NOT the default: an ambient
        # dependency makes two machines disagree about the same file.
        try:
            db = _write_ref_db(workdir)
            id_hits = _tile(_blast(seq, db, workdir))
        except Exception as exc:
            id_hits = _tile(kg_seedmatch.identify_hits(seq, kg_refs.REFERENCE_PARTS))
            if status is not None:
                status["deep_failed"] = (
                    "--deep was requested but BLAST+ failed to run (%s: %s); the "
                    "built-in identifier ran instead." % (type(exc).__name__, exc))
    else:
        if deep and not _have_blast():
            if status is not None:
                status["deep_failed"] = (
                    "--deep was requested but NCBI BLAST+ is not installed "
                    "(blastn/makeblastdb are not on PATH); the built-in identifier "
                    "ran instead.")
        id_hits = _tile(kg_seedmatch.identify_hits(seq, kg_refs.REFERENCE_PARTS))
```

- [ ] **Step 2: Change the signature and import, and make `ran` always true**

In `kagami/kg_identify.py`:

Add after `import kg_refs`:

```python
import kg_seedmatch
```

Change the signature:

```python
def identify(record, workdir, status=None, deep=False):
```

The `_not_run()` helper becomes unused on the default path. Leave the function defined (the
deep-search failure path above sets `status["deep_failed"]` instead, and a later phase removes the
dead helper) but delete its two call sites, which are inside the block replaced in Step 1.

Update the docstring's `status` paragraph to:

```python
    """Return an ordered list[Block] covering the construct, with claim + identity.

    status: an optional dict the caller passes in. Filled with {"ran": True, "reason": ""}.
    Identification now ALWAYS runs: it is pure Python with no external dependency, so
    the old "BLAST+ is missing" path -- which let a construct carrying a planted
    mislabel report PASS, clean to order, exit 0 -- cannot occur. When the caller asked
    for --deep and BLAST+ was unavailable or failed, status["deep_failed"] carries a
    sentence saying so; the built-in identifier ran regardless.

    deep: opt in to blastn's gapped local alignment for distant homologs. Not automatic:
    an ambient dependency makes two machines disagree about the same file.
    """
```

- [ ] **Step 3: Run the existing 88 assertions**

```bash
cd /Users/andrewhao/Desktop/katana/kagami && python3 tests.py 2>&1 | tail -20
```

Expected: `88 passed, 0 failed`.

The assertions that previously read `skip … (needs BLAST+)` now run, because identification no
longer needs the binary. The three tests at `tests.py:445-514` that force `_have_blast` to `False`
and assert `ran is False` will now **fail** — correctly, because the behaviour they pin is gone.
Fix them in Step 4 rather than weakening them.

- [ ] **Step 4: Update the tests that pinned the old silent-failure behaviour**

In `kagami/tests.py`, replace the block from `check("identify() reports ran=False when BLAST+ is
absent", …)` through `check("a raising BLAST+ also cannot produce a PASS", …)` with:

```python
# 18. Identification must never fail silently (2026-09-24), and as of phase 1 it can no
#      longer fail at all: it is pure Python with no external dependency. The hole this
#      group of tests was written for -- BLAST+ absent, a planted mislabel reported as
#      "PASS, clean to order", exit 0 -- is now closed by construction rather than by a
#      FLAG. These assertions pin that it stays closed.
_r_no, _b_no, _st_no = _identify_with(_gb_text, False)
check("identification runs with no BLAST+ installed", _st_no.get("ran") is True)
check("and it actually identifies the planted block",
      any(b.ident_id for b in _b_no))

_f_no = kg_audit.audit(_r_no, _b_no, identify_status=_st_no)
check("no identification FLAG is raised when identification ran",
      not any(f.category == "identification" for f in _f_no))
check("the planted mislabel is still caught",
      any(f.category == "identity-mislabel" for f in _f_no))
check("a construct with a mislabel cannot be PASS",
      kg_audit.verdict_kind(_f_no) == "REVIEW")
check("the CLI exit code for that construct is 5 (REVIEW), not 0",
      {"PASS": 0, "REVIEW": 5, "FAIL": 1}[kg_audit.verdict_kind(_f_no)] == 5)

# --deep asks for blastn. When it is unavailable the built-in identifier still runs and
# the caller is told, rather than silently getting a thinner answer.
_st_deep = {}
with tempfile.TemporaryDirectory() as _wd:
    _p = os.path.join(_wd, "c.gb")
    open(_p, "w", encoding="utf-8").write(_gb_text)
    _rec_d = kg_parse.parse(_p)
    _real = kg_identify._have_blast
    kg_identify._have_blast = lambda: False
    try:
        _b_deep = kg_identify.identify(_rec_d, _wd, status=_st_deep, deep=True)
    finally:
        kg_identify._have_blast = _real
check("--deep without BLAST+ still identifies", any(b.ident_id for b in _b_deep))
check("--deep without BLAST+ says so", "deep_failed" in _st_deep)
check("--deep without BLAST+ still reports ran=True", _st_deep.get("ran") is True)
```

Also delete the now-meaningless `check_blast` guard from the assertions at `tests.py:121` and
`tests.py:156-159` by replacing `check_blast(` with `check(` on those three lines — identification
no longer needs the binary, so they must run everywhere.

That leaves `check_blast()` and `HAVE_BLAST` with no call sites. Delete both definitions
(`tests.py:38-51`, the `HAVE_BLAST = ...` line and the `def check_blast` block) and the comment
above them. Leaving a helper that nothing calls invites someone to reintroduce the skip.

- [ ] **Step 5: Run the suite again**

```bash
cd /Users/andrewhao/Desktop/katana/kagami && python3 tests.py 2>&1 | tail -6
```

Expected: `0 failed`, with a count of 88 or higher (three `skip` lines became real assertions and
the `--deep` group adds three).

- [ ] **Step 6: Add `--deep` to the CLI and drop the default-path BLAST+ messaging**

In `kagami/kagami.py`:

Add to the `audit` parser, after the `--registry` argument:

```python
    a.add_argument("--deep", action="store_true",
                   help="also run NCBI BLAST+ (if installed) for gapped, distant-homology "
                        "search. The built-in identifier runs either way; this only adds "
                        "sensitivity for homologs below about 90% identity.")
```

In `run()`, change the identification call:

```python
    ident_status = {}
    with tempfile.TemporaryDirectory() as wd:
        blocks = kg_identify.identify(record, wd, status=ident_status,
                                      deep=getattr(args, "deep", False))
    if ident_status.get("deep_failed"):
        print("deep     : %s" % ident_status["deep_failed"])
```

Delete the `if not ident_status.get("ran", True):` block that printed
`identify : NOT RUN — …` and the two following lines — identification always runs now.

Make the same change in `run_rebuild()`: replace its `_rb_status`-based `NOT RUN` block with the
`deep_failed` line.

- [ ] **Step 7: Verify end to end on the bundled demo, and time a 16 kb input (Review Focus 5)**

```bash
cd /Users/andrewhao/Desktop/katana/kagami
python3 kagami.py audit examples/demo.gb --vendor Twist; echo "exit=$?"
python3 - <<'PY'
import time, sys, os, tempfile
sys.path.insert(0, ".")
import kg_refs, kg_seedmatch
N = kg_refs.normalise
big = max((N(r["seq"]) for r in kg_refs.REFERENCE_PARTS), key=len)
print("largest reference: %d bp" % len(big))
t0 = time.time()
kg_seedmatch.identify_hits(big, kg_refs.REFERENCE_PARTS)
print("16 kb query against 18,538 references: %.1f s" % (time.time() - t0))
PY
```

Expected: the demo reports `VERDICT: REVIEW` with the `identity-mislabel` finding present and
`exit=5`, and **no** `identify : NOT RUN` line. The timing must be under 30 s; if it is not, raise
`stride` and re-run Task 3's suite to confirm nothing regressed.

- [ ] **Step 8: Commit**

```bash
git add kagami/kg_identify.py kagami/kagami.py kagami/tests.py
git commit -m "feat!: identification no longer requires NCBI BLAST+

kg_identify now defaults to kg_seedmatch. Measured on real constructs: identical
identity and coverage to blastn on full-length parts, truncation at 60/80/90% and
point mutations at 94.4/97.7/98.6%; about twice as fast, because the old path rebuilt
a BLAST database of 18,538 sequences on every run; and exact on the 5' boundary of a
~85% diverged CDS where blastn was 114 bp out.

blastn becomes an explicit --deep opt-in rather than used-when-present. An ambient
dependency makes two machines disagree about the same file, which is the
works-on-my-machine failure --expect-root exists to prevent.

Consequence: identification ALWAYS runs, so the hole that let a construct carrying a
planted mislabel report 'PASS, clean to order' with exit 0 is closed by construction
rather than by a FLAG. The three tests that pinned the old silent-failure behaviour are
replaced by tests pinning the new guarantee, and three assertions that used to skip
without the binary now run everywhere.

BREAKING: identify() gains a keyword-only-in-practice 'deep' parameter (default False).
Existing two- and three-argument callers are unaffected.

Step 1 of phase 1. Assertions: kagami 91 passed, identifier oracle suite 0 failed."
```

---

## Task 5: Remove the BLAST+ install path from the user-facing surface

**Files:**
- Modify: `kagami/kagami_gui.py`
- Modify: `kagami/tests.py`
- Modify: `.gitlab-ci.yml`

**Interfaces:** none changed.

- [ ] **Step 1: Delete the GUI's missing-BLAST+ banner**

In `kagami/kagami_gui.py`, delete the whole `if not (shutil.which("blastn") and
shutil.which("makeblastdb")):` block in `__init__` — from that line through the final
`self._say("If Kagami still shows this message after installing, …")` call. Replace it with
nothing.

Then remove the now-unused import: delete the `import shutil` line.

- [ ] **Step 2: Verify the GUI still imports**

```bash
cd /Users/andrewhao/Desktop/katana/kagami && python3 -c "
import sys; sys.path.insert(0, '.')
import kagami_gui
print('GUI imports with no BLAST+ reference:', 'shutil' not in dir(kagami_gui))
"
```

Expected: `GUI imports with no BLAST+ reference: True`.

- [ ] **Step 3: Retarget the dead-URL scanner**

`kagami/tests.py:544-572` guards a BLAST+ install URL that no longer appears anywhere. The scanner
itself is worth keeping — it caught a real 404 a student hit — but it must now guard a URL that
exists. Replace the block from `# 20. The install link must not rot` through the
`check("the fix names which installer file to take, not a PATH edit", …)` call with:

```python
# 20. No source file may carry a known-dead URL (2026-10-01). A WIST student copied a
#      BLAST+ link out of a finding and landed on a 404. As of phase 1 the BLAST+
#      install instructions are gone entirely -- identification needs no binary -- so
#      this scanner now guards that they have not crept back, plus the dead URL itself.
_DEAD_URLS = ("doc/blast-help/downloadblast.html",)
_src_files = [f for f in os.listdir(HERE) if f.endswith(".py") and f != "tests.py"]
_offenders = []
for _fn in _src_files:
    try:
        _txt = open(os.path.join(HERE, _fn), encoding="utf-8").read()
    except Exception:
        continue
    for _d in _DEAD_URLS:
        if _d in _txt:
            _offenders.append("%s:%s" % (_fn, _d))
check("no source file carries a known-dead BLAST+ URL", not _offenders,
      ", ".join(_offenders))

# The install instructions must not come back: identification is pure Python now, and
# telling a student to download 400 MB for a feature they already have is the install
# barrier this phase removed.
_install_hints = []
for _fn in _src_files:
    try:
        _txt = open(os.path.join(HERE, _fn), encoding="utf-8").read()
    except Exception:
        continue
    if "ftp.ncbi.nlm.nih.gov/blast/executables" in _txt:
        _install_hints.append(_fn)
check("no source file tells the user to install BLAST+", not _install_hints,
      ", ".join(_install_hints))
```

- [ ] **Step 4: Run the suite**

```bash
cd /Users/andrewhao/Desktop/katana/kagami && python3 tests.py 2>&1 | tail -4
```

Expected: `0 failed`.

- [ ] **Step 5: Update CI**

In `.gitlab-ci.yml`, replace the `kagami` job with:

```yaml
# Kagami is the tool the wiki invites a visitor to download and run. This image has no
# blastn, which is the point - it is the machine a stranger actually has. As of phase 1
# that is no longer a degraded mode: identification is pure Python, so the full audit
# runs here, including the one that matters - a GenBank whose feature is labelled B0032
# while its bases are B0034 is caught.
kagami:
  stage: test
  script:
    - cd kagami
    - python tests.py
    - python test_identify.py
```

- [ ] **Step 6: Commit**

```bash
git add kagami/kagami_gui.py kagami/tests.py .gitlab-ci.yml
git commit -m "refactor: remove the BLAST+ install path from the user surface

The GUI's opening 'One feature needs a free add-on' banner is deleted -- it is no
longer true, and it was the first thing a student saw.

The dead-URL scanner is retargeted: it still guards the 404 a student hit, and now
also asserts that BLAST+ install instructions have not crept back into any source
file. Telling someone to download 400 MB for a capability they already have is the
install barrier this phase exists to remove.

CI's kagami job now runs the full suite plus the identifier oracle suite on an image
with no blastn, because that is no longer a degraded mode.

Step 1 of phase 1."
```

---

## Task 6: Vendor PyYAML

**Files:**
- Create: `_vendor/README.md`, `_vendor/yaml/` (copied), `vendor_path.py`
- Modify: `katana_build.py`, `check_design.py`
- Modify: `requirements.txt`; create `requirements-optional.txt`

**Interfaces:**
- Produces: `vendor_path.ensure()` — idempotently prepends the repository's `_vendor` directory to
  `sys.path`. Call it before `import yaml`.

- [ ] **Step 1: Copy PyYAML in and strip the C extension**

```bash
cd /Users/andrewhao/Desktop/katana
V=/private/tmp/claude-501/-Users-andrewhao-Desktop-katana/a0a79770-032e-4e4b-a9d6-776d8b5bc307/scratchpad/venv
Y=$("$V/bin/python" -c "import yaml, os; print(os.path.dirname(yaml.__file__))")
mkdir -p _vendor
cp -R "$Y" _vendor/
rm -rf _vendor/yaml/__pycache__
rm -f _vendor/yaml/*.so
du -sh _vendor/yaml
"$V/bin/python" -c "import yaml; print('vendored version:', yaml.__version__)"
```

Expected: roughly `700K` and `vendored version: 6.0.2`.

If that venv no longer exists, create it first:
`python3 -m venv /tmp/vy && /tmp/vy/bin/pip install PyYAML==6.0.2` and use `/tmp/vy` as `$V`.

- [ ] **Step 2: Write the vendor note**

Create `_vendor/README.md`:

```markdown
# Vendored dependencies

## Why anything is vendored at all

The engine's one hard dependency used to be a YAML parser, and `pip install` was the
first step of the install instructions. On a school machine that step fails in a dozen
ways — no `pip`, an externally-managed Python, a proxy, no network, a version conflict
with another project — and when it fails the engine cannot read a Design Spec at all.

A vendored pure-Python parser removes the step. Nothing to install, nothing to pin,
nothing to fail.

## What is here

### `yaml/` — PyYAML 6.0.2

Copied verbatim from the PyPI wheel `PyYAML==6.0.2`, with two deletions:

- `_yaml*.so` — the optional libyaml C extension. PyYAML works without it; the pure-
  Python loader is slower, which is irrelevant for files of this size. Keeping it would
  tie the repository to one platform and one Python minor version, which is the opposite
  of the point.
- `__pycache__/`

Licence: MIT. Copyright (c) 2017-2021 Ingy döt Net, (c) 2006-2016 Kirill Simonov.
Upstream: <https://github.com/yaml/pyyaml>

### Why not a hand-written YAML subset parser

`katana_build.load_yaml_simple`'s docstring once claimed to be a "Minimal YAML-subset
loader (avoids PyYAML dependency)". That function was never written — its body imports
`yaml` and exits if it is missing. Writing it would be the wrong trade: this project's
entire thesis is the absence of subtle bugs, and a bespoke parser for a format with
flow mappings, block mappings, nested lists, comments and quoted colons is a generator
of subtle bugs. Vendor the real one.

## Updating

Replace the directory from a fresh wheel, delete `*.so` and `__pycache__`, run
`python3 verify.py && python3 test_determinism.py && python3 kagami/tests.py`, and
record the new version here.
```

- [ ] **Step 3: Write the path shim**

Create `vendor_path.py` at the repository root:

```python
"""vendor_path.py — put the repository's vendored packages on sys.path.

One place, so there is exactly one answer to "where does `import yaml` come from".
Called before any vendored import. Idempotent, and a no-op when a real installed
PyYAML is already importable, so a developer with it in a venv keeps using theirs.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_VENDOR = os.path.join(_HERE, "_vendor")


def ensure():
    """Make the vendored packages importable. Returns the path added, or None."""
    if not os.path.isdir(_VENDOR):
        return None
    if _VENDOR in sys.path:
        return _VENDOR
    # Appended, not prepended: an installed PyYAML wins, so a developer's venv is
    # authoritative and the vendored copy is the fallback that makes a bare machine work.
    sys.path.append(_VENDOR)
    return _VENDOR
```

- [ ] **Step 4: Use it in the two YAML readers**

In `katana_build.py`, inside `load_yaml_simple`, replace:

```python
    try:
        import yaml
    except ImportError:
        sys.exit("BLOCK: PyYAML is missing. It is the one thing this engine cannot run without.\n"
                 "       Install it with:   python -m pip install pyyaml\n"
                 "       If you made a workspace with python -m venv .venv, switch to it first,\n"
                 "       or the install goes somewhere this build cannot see.")
```

with:

```python
    try:
        import yaml
    except ImportError:
        try:
            sys.path.insert(0, str(HERE))
            import vendor_path
            vendor_path.ensure()
            import yaml
        except ImportError:
            sys.exit("BLOCK: no YAML parser available, and the vendored copy in _vendor/\n"
                     "       is missing. If you cloned this repository, the simplest repair\n"
                     "       is a fresh copy of it.")
```

In `check_design.py`, inside `load_spec`, make the identical replacement, with the
`BLOCK: PyYAML is missing, and this reads YAML.` message replaced by the same text. `check_design.py`
has no `HERE` constant, so add one after the imports:

```python
HERE = Path(__file__).resolve().parent
```

- [ ] **Step 5: Prove it works with nothing installed**

```bash
cd /Users/andrewhao/Desktop/katana
python3 -c "import yaml" 2>&1 | tail -1
python3 katana_build.py specs/pSense-Nit.spec.yaml --dry-run 2>&1 | tail -6
```

Expected: the first command reports `ModuleNotFoundError: No module named 'yaml'`, and the second
nonetheless reaches `Stage-4b PASS` and `── Dry run — no output files ──` using the vendored parser.

- [ ] **Step 6: Run the full determinism suite with the system Python**

```bash
cd /Users/andrewhao/Desktop/katana && python3 test_determinism.py 2>&1 | tail -12
```

Expected: `ALL PASSED`. SBOL is skipped (`sbol3` not installed), so the count is 10 rather than 11.
That is the correct behaviour — an optional exporter that is absent reports as skipped.

- [ ] **Step 7: Split requirements**

Replace `requirements.txt` with:

```
# Katana engine — dependencies.
#
# THERE ARE NONE. The engine needs nothing installed.
#
# Its one hard dependency used to be a YAML parser, and `pip install` was the first
# step of the install instructions. On a school machine that step fails in a dozen ways,
# and when it fails the engine cannot read a Design Spec at all. PyYAML is now vendored
# in _vendor/yaml/ (pure Python, MIT) and loaded by vendor_path.py. See _vendor/README.md.
#
# Python 3.9 or newer is the only requirement.
#
# Two OPTIONAL extras are in requirements-optional.txt. Without them the engine still
# builds and still audits; it says loudly which checks it therefore did not run, because
# an optional check that vanishes silently is worse than no check at all.
```

Create `requirements-optional.txt`:

```
# Katana — OPTIONAL extras. The engine runs without these and says so when they are absent.
#
#   python-codon-tables   real E. coli CAI for designed CDSs in the Stage-4b dry-lab gate
#   sbol3                 validated SBOL 3 export (`--sbol out.ttl`)
#
# Install with:  python3 -m pip install -r requirements-optional.txt
#
# INSTALL THIS INSIDE A VIRTUAL ENVIRONMENT. These are exact pins, and against a
# system-wide Python they will replace newer versions you already had, silently, for
# every other project on that machine.
#
# Every version here is pinned, INCLUDING transitive dependencies. The previous file
# pinned only the three direct ones and claimed that made builds reproducible; it did
# not. pyshacl drifted 0.28.1 -> 0.40.1 between two installs in a single afternoon, and
# a future resolution could pick a combination that breaks the SBOL round-trip test for
# reasons unrelated to this code. Regenerate this file with `pip freeze`, never by hand.

python-codon-tables==0.1.12
sbol3==1.2.0.post0

# --- transitive, pinned by pip freeze ---
html5lib==1.1
isodate==0.6.1
owlrl==6.0.2
packaging==26.3
prettytable==3.18.0
pyparsing==3.3.3
pyshacl==0.28.1
python-dateutil==2.9.0.post0
rdflib==6.3.2
six==1.17.0
wcwidth==0.9.2
webencodings==0.6.1
```

- [ ] **Step 8: Verify the optional set still resolves and the full suite passes**

```bash
cd /Users/andrewhao/Desktop/katana
rm -rf /tmp/optcheck && python3 -m venv /tmp/optcheck
/tmp/optcheck/bin/pip install -q -r requirements-optional.txt && echo "optional extras install cleanly"
/tmp/optcheck/bin/python test_determinism.py 2>&1 | tail -4
```

Expected: `optional extras install cleanly` and `ALL PASSED — 11 checks`.

- [ ] **Step 9: Update CI to prove the no-dependency claim**

In `.gitlab-ci.yml`, replace the `.full` anchor's `before_script` and the `minimal-deps` job:

```yaml
.full: &full
  stage: test
  before_script:
    - python --version
    - pip install --no-cache-dir -r requirements-optional.txt

# No extras at all. This is the claim that matters now: the engine must build a
# construct and audit a sequence with NOTHING installed. PyYAML is vendored, and the
# optional gates must degrade to a loud warning rather than dying.
no-deps:
  stage: test
  script:
    - python verify.py
    - python test_determinism.py
    - cd kagami && python tests.py && python test_identify.py
```

Delete the old `minimal-deps` job.

- [ ] **Step 10: Commit**

```bash
git add _vendor vendor_path.py katana_build.py check_design.py \
        requirements.txt requirements-optional.txt .gitlab-ci.yml
git commit -m "feat: vendor PyYAML; the engine now needs nothing installed

PyYAML 6.0.2 (pure Python, MIT) is vendored in _vendor/yaml/ with the optional libyaml
.so removed, and loaded through vendor_path.ensure(). An installed PyYAML still wins,
so a developer's venv stays authoritative; the vendored copy is what makes a bare
machine work.

Not a hand-written YAML subset parser. load_yaml_simple's docstring claimed to be one
for months while its body imported yaml and exited -- the function was never written,
and writing it would be the wrong trade for a project whose thesis is the absence of
subtle bugs.

requirements.txt is now empty with an explanation. The two optional extras move to
requirements-optional.txt, pinned INCLUDING transitive dependencies: the old file
pinned 3 of 15 and claimed that made builds reproducible, while pyshacl drifted
0.28.1 -> 0.40.1 between two installs in one afternoon.

CI's minimal-deps job becomes no-deps and runs the whole suite with nothing installed.

Verified: test_determinism.py ALL PASSED under the system python3 with no yaml
importable. Step 2 of phase 1."
```

---

## Task 7: Fix the documentation defects

**Files:**
- Modify: `README.md`, `kagami/README.md`, `kagami/refs/ATTRIBUTION.md`
- Modify: every `.py` whose user-facing text says `python` where it means `python3`

**Interfaces:** none.

- [ ] **Step 1: Delete the corrupt Windows BLAST+ commands and the whole section**

`README.md` is the only file in the repository containing `0x08` backspace bytes — six of them, all
inside the Windows BLAST+ install commands, where `"$env:TEMP\blast.exe"` was written as
`"$env:TEMP"` + BACKSPACE + `last.exe`. Both PowerShell one-liners are therefore broken for their
only audience.

Identification no longer needs BLAST+, so the correct fix is to delete the section rather than
repair it. Remove the entire `### Installing BLAST+` section (from that heading through the
`sudo apt update && sudo apt install -y ncbi-blast+` block).

In the `## Turning on the off-target check` section, replace the paragraph beginning
`The check shells out to BLAST+.` with:

```markdown
The check is pure Python and needs nothing installed. It is a seed-and-extend scan, good
enough to catch a long high-identity host match that no intended part explains — which is
the misassembly signal it is there for — and not a substitute for a real alignment tool in
a publication. If you have NCBI BLAST+ on your `PATH`, `kagami check --deep` will also use
it for gapped, distant-homology search.
```

- [ ] **Step 2: Verify no backspace bytes remain anywhere**

```bash
cd /Users/andrewhao/Desktop/katana
for f in $(git ls-files); do
  n=$(LC_ALL=C grep -c $'\x08' "$f" 2>/dev/null || echo 0)
  [ "$n" != "0" ] && echo "STILL PRESENT: $f ($n lines)"
done
echo "backspace scan complete"
```

Expected: only `backspace scan complete`.

- [ ] **Step 3: Replace `python` with `python3` in user-facing text**

`README.md` uses `python` 12 times and `python3` zero times. `python` does not exist on macOS, even
with a python.org install, so every documented command fails with `command not found`.

```bash
cd /Users/andrewhao/Desktop/katana
python3 - <<'PY'
import re, subprocess
files = subprocess.check_output(["git", "ls-files"], text=True).split()
targets = [f for f in files if f.endswith((".md", ".py")) and "_vendor/" not in f]
pat = re.compile(r'(?<![\w.-])python(?!3)(?=[ "\'])')
changed = []
for f in targets:
    try:
        t = open(f, encoding="utf-8").read()
    except Exception:
        continue
    new = pat.sub("python3", t)
    if new != t:
        open(f, "w", encoding="utf-8").write(new)
        changed.append((f, len(pat.findall(t))))
for f, n in changed:
    print("  %-34s %d occurrence(s)" % (f, n))
PY
```

- [ ] **Step 4: Check the substitution did not corrupt anything**

```bash
cd /Users/andrewhao/Desktop/katana
git diff --stat
grep -rn 'python3 3\|python33\|python3-codon' --include=*.md --include=*.py . | grep -v _vendor || echo "no double substitution"
grep -c 'python3 ' README.md
```

Expected: `no double substitution`, and a non-zero count in README. `python-codon-tables` and
`python_codon_tables` must be untouched — the pattern requires a following space or quote, so they
are safe; the grep above confirms it.

- [ ] **Step 5: Run everything, because the substitution touched `.py` files**

```bash
cd /Users/andrewhao/Desktop/katana
python3 verify.py | tail -3
python3 test_determinism.py 2>&1 | tail -3
cd kagami && python3 tests.py 2>&1 | tail -2 && python3 test_identify.py 2>&1 | tail -2
```

Expected: `OK`, `ALL PASSED`, `0 failed`, `0 failed`.

- [ ] **Step 6: Correct the stale counts in `kagami/README.md`**

Replace `currently **25 public parts** across promoters, RBS, terminators, reporters, markers, and
origins` with:

```markdown
currently **18,538 public parts** — a filtered mirror of the iGEM Registry via SynBioHub,
plus parts projected from this project's own sealed library and fetched live from the
Registry API. `refs/ATTRIBUTION.md` records where each one came from and what was filtered out.
```

Replace `tests.py        11 self-contained checks` with:

```markdown
tests.py         91 self-contained checks
test_identify.py oracle tests for the pure-Python identifier
kg_seedmatch.py  pure-Python part identification (no BLAST+ needed)
```

In the `## Requirements` section, replace the `**NCBI BLAST+** on PATH …` bullet with:

```markdown
- **Nothing else.** Identification is pure Python. NCBI BLAST+ is optional: with it on
  your `PATH`, `--deep` adds gapped search for homologs below about 90% identity.
```

- [ ] **Step 7: Correct `ATTRIBUTION.md`'s unreproducible rebuild instructions**

`kagami/refs/ATTRIBUTION.md` tells the reader to run `build_synbiohub_refs.py` and
`convert_synbiohub_refs.py`. Neither file is in the repository, so the section headed
`Nothing here is hand-edited. To reproduce:` cannot be followed.

Replace that code block and its introduction with:

```markdown
## Rebuilding it

The library-derived and live-Registry rows regenerate from the sealed parts library:

```
python3 build_refs.py --registry-bulk
```

The SynBioHub mirror does **not** regenerate from anything in this repository. It was
harvested once, on 2017-04-03 as the collection itself is dated, by two scripts
(`build_synbiohub_refs.py` and `convert_synbiohub_refs.py`) that were **not** published
here — they needed a SynBioHub login, and they are not part of this bundle. The mirror
is therefore a fixed input, and the `provenance` column on every row records the exact
per-part URI so any sequence can be re-checked against its source record independently.

Saying so explicitly rather than listing commands that do not exist: an instruction you
cannot follow is worse than an acknowledged gap.
```

- [ ] **Step 8: Fix the macOS launcher's stale Gatekeeper advice (CODE-REPORT 🔴0)**

Spec §8 places this in phase 5 with packaging, but it is a zero-cost documentation change and it is
the only finding measurably blocking users right now, so it lands here.

A `.command` carrying `com.apple.quarantine` — which every browser download sets — is rejected:
`spctl -a -vv -t open run_kagami_gui.command` → `rejected, source=no usable signature`. The
launcher's own comment recommends "Right-click → Open", a bypass Apple removed in macOS 15. The
measured fact that makes this cheap to fix: a quarantined shell script run **from a terminal** is
not blocked, because the kernel execs the signed system `/bin/bash` and the script is only data.

In both `kagami/run_kagami_gui.command` and `kagami/run_kagami.command`, replace the
`# First-time Gatekeeper note:` comment block with:

```bash
# macOS will refuse to run this if you DOUBLE-CLICK it after downloading, because every
# browser marks downloaded files as quarantined and this file is not code-signed. The
# "Right-click -> Open" trick that used to get past that was removed in macOS 15.
#
# Run it from Terminal instead, which is not affected: the quarantine check applies to
# double-clicking, not to a script a shell runs. Open Terminal, then type `bash ` (with
# the space), drag this file onto the window, and press Return:
#
#     bash /path/to/kagami/run_kagami_gui.command
#
# Or, equivalently:  cd into this folder and run  python3 kagami_gui.py
```

Then add the same guidance to `README.md`, in a new subsection immediately after
`## Try it first, read second`:

```markdown
### On a Mac, run it from Terminal, not by double-clicking

macOS refuses to open a downloaded script that is not code-signed, and this one is not.
That block applies to double-clicking only — a script a shell runs is unaffected. So open
Terminal, type `bash ` (with the space), drag the file onto the window and press Return.

This is not a sign that anything is wrong, and it is why the commands in this README are
written to be run in a terminal rather than clicked.
```

- [ ] **Step 9: Verify the stale advice is gone**

```bash
cd /Users/andrewhao/Desktop/katana
grep -rn 'Right-click' kagami/*.command README.md || echo "stale Gatekeeper advice removed"
grep -c 'bash ' kagami/run_kagami_gui.command
```

Expected: `stale Gatekeeper advice removed`, and a non-zero count.

- [ ] **Step 10: Commit**

```bash
git add README.md kagami/README.md kagami/refs/ATTRIBUTION.md \
        kagami/run_kagami.command kagami/run_kagami_gui.command
git add -u
git commit -m "docs: fix the install instructions that could not work

README.md was the only file in the repository containing 0x08 backspace bytes -- six of
them, all inside the Windows BLAST+ commands, where \"\$env:TEMP\\\\blast.exe\" had been
written as \"\$env:TEMP\" + BACKSPACE + \"last.exe\". Both PowerShell one-liners were
broken for their only audience. The section is deleted rather than repaired:
identification no longer needs the binary.

'python' -> 'python3' across all user-facing text, including BLOCK messages. README used
'python' 12 times and 'python3' zero times, and 'python' does not exist on macOS even
with a python.org install -- so every documented command, including the first one, failed
with 'command not found'. The recovery advice inside the PyYAML BLOCK message had the
same defect.

Corrected claims: kagami/README said 25 reference parts (actual 18,538) and 11 tests
(actual 91); the off-target gate was described as shelling out to BLAST+ when
katana_drylab has always called the pure-Python fallback directly; ATTRIBUTION.md told
the reader to run two scripts that are not in the repository.

macOS launchers: the stale 'Right-click -> Open' advice is replaced with the Terminal
route. A downloaded .command carrying com.apple.quarantine is rejected by Gatekeeper
(measured: spctl reports 'rejected, source=no usable signature'), and the right-click
bypass it recommended was removed in macOS 15 -- so the file documented a workaround
that no longer exists. Running the same script from a terminal is NOT blocked, because
the check applies to double-clicking. Fixes CODE-REPORT finding 0.

Step 2 of phase 1."
```

---

## Task 8: Phase 1 verification

**Files:** none (verification only)

- [ ] **Step 1: Assert every invariant from spec §10.3 on a bare interpreter**

```bash
cd /Users/andrewhao/Desktop/katana
echo "=== nothing installed? ==="
python3 -c "import yaml" 2>&1 | tail -1
python3 -c "import sbol3" 2>&1 | tail -1
command -v blastn || echo "blastn: not on PATH (or ignore it; --deep is opt-in)"
echo "=== library integrity ==="
python3 verify.py | tail -4
echo "=== construct hashes ==="
python3 test_determinism.py 2>&1 | grep -E 'PASS|FAIL|ALL'
echo "=== audit ==="
cd kagami && python3 tests.py | tail -2 && python3 test_identify.py | tail -2
```

Expected: `verify.py` reports 30 parts sealed and `8/8`; `test_determinism.py` reproduces all
7 ORACLE hashes; both audit suites report `0 failed`.

- [ ] **Step 2: Confirm the parts library was not touched**

```bash
cd /Users/andrewhao/Desktop/katana && git diff --stat main -- parts-library/ specs/
```

Expected: no output. `parts-library/` and `specs/` are byte-identical to `main`.

- [ ] **Step 3: Record what phase 1 delivered**

```bash
cd /Users/andrewhao/Desktop/katana && git log --oneline main..unify
```

Expected: the commits from Tasks 0–7, in order.

- [ ] **Step 4: Commit the phase marker**

```bash
git commit --allow-empty -m "chore: phase 1 complete -- zero hard external dependencies

The engine and the auditor now run with nothing installed. Verified on a system
python3 with no yaml and no sbol3 importable, and with blastn irrelevant:

  verify.py              30 parts sealed, 8/8 adversarial checks caught
  test_determinism.py    all 7 ORACLE construct hashes reproduced
  kagami/tests.py        0 failed
  kagami/test_identify.py 0 failed

parts-library/ and specs/ are byte-identical to main.

Removed from the install path: NCBI BLAST+ (136-400 MB, PATH, terminal restart, and two
corrupt PowerShell one-liners) and 15 pip packages / 36 MB. What remains is Python 3.9+.

Next: phase 2 (spec step 3) extracts core/ and migrates the eight LOCK parsers, which
structurally fixes CODE-REPORT findings A and B."
```

---

## Follow-on plans

Each gets its own plan document, written when its predecessor lands, because each depends on
interfaces the previous phase creates.

| Phase | Spec steps | Deliverable | Why it waits |
|---|---|---|---|
| 2 | 3 | `core/` extracted; the 8 LOCK parsers consolidated; 🔴A and 🔴B fixed | Highest-risk step; needs phase 1's stdlib-only guarantee so `core/` can be verified Pyodide-clean |
| 3 | 4, 5, 6 | `build() -> BuildResult`; GUI calls functions; single `katana` entry + interactive menu | Needs `core/` to exist |
| 4 | 7 | Web front end: local `./katana web`, then GitHub Pages at `andrewhao66/iGEM-katana-webtest` | Needs the stdlib-only core and `BuildResult` |
| 5 | 8, 9 | OS bundles; the three-pass review gate (self / subagent / Codex `codex-cli 0.154.0`) | Reviews the whole branch |
