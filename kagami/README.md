# Kagami — the reverse-Katana sequence auditor

Katana builds a construct **forward** from intent (Spec → sealed parts → assemble →
seal → order). **Kagami runs it backward:** take any sequence, identify the parts
inside it against **public** references, and return a **pass / flag / fail** verdict
per block — with the *reason* and the *fix* for every finding.

> **Kagami's edge is the audit, not the annotation.** Identifying what parts are in
> a plasmid is already solved (pLannotate, SnapGene, Benchling). Kagami's value is
> the **QC verdict + reasons + fixes** layered on top — the check you run *before*
> you spend the sponsor DNA budget.

> **Community-side by design.** It uses only public references (iGEM Registry parts,
> RefSeq host genomes) and public checking machinery, so it ships under the **WIST
> iGEM** team, decoupled from anything on a private research track. No proprietary
> parts are embedded or required.

---

## What it catches

Grouped by what actually goes wrong in an iGEM build:

| Group | Checks |
|---|---|
| **Identity** | label ≠ sequence (the B0032↔B0034 class), truncated parts, ORF-clean (no internal stop / frame break) |
| **Junctions** | RBS→ATG spacing 5–9 nt, spurious internal ATG/stop |
| **Integrity** | GC outliers, homopolymer runs, direct repeats (misassembly), size vs vendor cap |
| **Safety / FTO-lite** | forbidden RE sites (EcoRI·XbaI·SpeI·PstI = RFC[10]), Type IIS (BsaI/BsmBI/SapI), >40 bp host homology (recombination substrate) |

Every check reuses Katana's **forward** conventions verbatim (enzyme site
definitions from `forbid_sites_check.py`, the 40 bp rule from
`host_homology_check.py`, the 5–9 nt junction rule from `katana-validate`), so a
Kagami PASS means the same thing a `katana-validate` PASS does.

Verdict roll-up: **FAIL** (any hard error) › **CONDITIONAL** (flags, no fail) ›
**PASS**. Exit codes `1 / 5 / 0` respectively (`2` = error).

## Requirements

- **Python 3.9+**
- **NCBI BLAST+** on PATH (`blastn`, `makeblastdb`) — used for identification.
  If BLAST is absent, Kagami still runs the invariant + composition checks and an
  annotated GenBank's claim-based checks; identification is skipped.

## Usage

```bash
python kagami.py audit INPUT.gb \
    --vendor Twist \            # apply a vendor per-fragment size cap
    --host MG1655.fna \         # run the >40 bp host off-target scan
    --html report.html \        # visual report (mirrors the concept one-pager)
    --json findings.json \      # machine-readable
    --emit-spec recovered.spec.yaml \   # draft Katana Spec (rebuild bridge)
    --emit-intake intake.txt            # per-part library intake requests
```

Input may be **GenBank** (annotations are read as the construct's *claims* and
checked against the sequence) or **FASTA** (blocks are discovered by BLAST).

Try it on the bundled demo (contains a deliberate B0032/B0034 mislabel):

```bash
python make_demo.py
python kagami.py audit examples/demo.gb --vendor Twist --html examples/demo_report.html
```

Run the tests:

```bash
python tests.py
```

## Closing the loop: can it save parts and rebuild?

Yes — but **not** by hashing the blocks out of the pasted construct and sealing
them. That is the **circular-provenance anti-pattern** Katana explicitly forbids
(law 3: *"every part has an independent, primary source that predates the
construct; verifying a construct against the same bank it was built from is
circular and forbidden"*). Sealing a part from the construct you are auditing would
launder an unverified sequence into a trusted one.

So Kagami emits two handoff artifacts and lets the **existing forward skills** do
the sealing/hashing/rebuild correctly:

1. **`--emit-intake`** → `katana-parts-library`. One request per block, naming the
   **primary source to fetch** (Registry id / accession), never the construct bytes.
   The library fetches fresh, verifies, seals, and hashes (`seq_sha256`,
   `file_sha256`) independently. A block with no reference match is marked
   **UNRESOLVED** — it cannot be sealed until its primary source is identified.
2. **`--emit-spec`** → `katana-spec` → `katana-assemble`. A draft Design Spec
   (INTENT only, **no base pairs**) with the audit's fixes already applied (correct
   label, corrected order). Forward Katana regenerates a clean, deterministic `.gb`
   from the freshly-sealed parts — the "working one".
3. Then `katana-diff` compares `regenerate(draft spec)` against the pasted input to
   show exactly what was fixed.

**Kagami reports; it does not seal.** That division is the point.

## The reference set (`refs/` + `build_refs.py`)

Kagami loads its references from a bundled data file (`refs/reference_parts.tsv` +
`reference_parts.fasta`), currently **25 public parts** across promoters, RBS,
terminators, reporters, markers, and origins.

Most are a **projection of the verified, sealed public reference parts in the
Synbio parts-library** — primary-sourced and LOCK-hash-checked — so their sequences
are trustworthy, not hand-typed. Each entry carries a `provenance` string:

- `parts-library <source> [seq_sha256 verified vs LOCK]` — the sequence came from a
  sealed library part **whose `seq_sha256` `build_refs.py` recomputed and matched
  against LOCK at build time** (the real NCBI/Registry/Addgene source is recorded).
- `seed — verify vs ...` — a hand-seeded canonical public sequence still to be
  confirmed against its primary source. Kagami surfaces this tag.

**Trust nothing on read (the build gate).** `build_refs.py` does not copy library
sequences on faith. For every library part it recomputes
`seq_sha256 = sha256(UPPER, letters-only)` — the exact `katana_lock.py` convention —
and requires it to equal both the part's `seq_sha256` in `LOCK.tsv` and the sha12 in
the sealed filename; it also recomputes `LOCK.root` (the Merkle root over the row
hashes) and checks it against the last attested root in `LOCK.root.log`. Any mismatch
is **fail-closed**: the part is not written and the build exits non-zero (a tampered
or drifted part can never silently become a Kagami reference). So a Kagami reference
is a sequence that *reproduced its seal at build time*, not one read on trust.

**To expand it the right way, re-run the builder** (never paste a sequence out of a
construct you are auditing — that is circular provenance):

```bash
python build_refs.py --library path/to/your/parts-library
```

`build_refs.py` pulls **only** the public `class=reference` parts on its allowlist —
never `designed` or otherwise non-public parts (the IP boundary). To widen coverage,
add a part id to the `ALLOWLIST` in `build_refs.py` once it is sealed in the library,
or add a canonical public part to `HAND_SEED`, then re-run. Unmatched blocks are
always still fully audited (ORF, sites, composition) and reported as unidentified —
identification breadth only changes what can be named.

## Known limitations (v1)

- Identification depth is bounded by the seed set + BLAST; a rich CDS library (GFP
  variants, common enzymes) is the obvious next expansion.
- Repeat detection is a coarse exact-k-mer probe, not a full aligner.
- Host off-target uses a bounded exact-match net unless `--host` is given (then use
  the project's real blastn DB for full sensitivity).
- The draft-spec rebuild is a *bridge*; the actual seal/hash/assemble is forward
  Katana's job, on purpose.

## Files

```
kagami.py        CLI + orchestration + text/JSON/HTML report
kg_parse.py      FASTA / GenBank reader (claims = features)
kg_refs.py       loads the public reference set from refs/
kg_identify.py   BLAST-based decomposition → blocks
kg_audit.py      the checks (Katana conventions reused)
kg_bridge.py     draft Spec + intake requests (the round-trip, law-abiding)
build_refs.py    (re)generate refs/ from the sealed parts-library (public only)
refs/            reference_parts.tsv + .fasta (the bundled reference set)
make_demo.py     builds examples/demo.gb from the reference set
tests.py         11 self-contained checks
run_kagami.bat   Windows double-click wrapper
```
