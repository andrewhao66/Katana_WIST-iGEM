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
- **Nothing else.** Identification is pure Python, so the full audit runs on a machine
  with nothing installed. NCBI BLAST+ is optional: with `blastn` and `makeblastdb` on
  your `PATH`, `--deep` adds gapped search for homologs below about 90% identity.

## Usage

From the bundle root, one command:

```bash
./katana check INPUT.gb
```

That is the whole of it for most people. Nothing needs installing beyond Python 3.9 or
newer — identification is pure Python.

Every flag still works, and all of them are optional:

```bash
./katana check INPUT.gb \
    --vendor Twist \            # apply a vendor per-fragment size cap
    --host MG1655.fna \         # run the >40 bp host off-target scan
    --host-reca neg \           # recA- cloning strain: a host match drops to a note
    --assembly BsaI \           # only flag sites the chosen enzyme would cut
    --registry \                # check BBa_* labels against the iGEM Registry (network)
    --library PATH \            # also identify against your own sealed parts library
    --deep \                    # also use NCBI BLAST+, if installed, for distant homologs
    --html report.html \        # visual report
    --json findings.json \      # machine-readable
    --emit-spec recovered.spec.yaml \   # draft Katana Spec (rebuild bridge)
    --emit-intake intake.txt            # per-part library intake requests
```

Input may be **GenBank** (annotations are read as the construct's *claims* and checked
against the sequence), **FASTA**, a **spreadsheet**, or a sequence **pasted** into a text
file. Dispatch is on content, not on the extension.

Try it on the bundled demo (contains a deliberate B0032/B0034 mislabel):

```bash
python3 make_demo.py
python3 kagami.py audit examples/demo.gb --vendor Twist --html examples/demo_report.html
```

Run the tests:

```bash
python3 tests.py
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
`reference_parts.fasta`), currently **18,538 public parts** — a filtered mirror of the
iGEM Registry via SynBioHub, plus parts projected from this project's own sealed library
and parts fetched live from the Registry API. `refs/ATTRIBUTION.md` records where each
one came from and what was filtered out.

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
python3 build_refs.py --library path/to/your/parts-library
```

`build_refs.py` pulls **only** the public `class=reference` parts on its allowlist —
never `designed` or otherwise non-public parts (the IP boundary). To widen coverage,
add a part id to the `ALLOWLIST` in `build_refs.py` once it is sealed in the library,
or add a canonical public part to `HAND_SEED`, then re-run. Unmatched blocks are
always still fully audited (ORF, sites, composition) and reported as unidentified —
identification breadth only changes what can be named.

## Known limitations (v1)

- Identification depth is bounded by the reference set. A match below about 90% identity
  is reported as unidentified rather than named, because an 85% match is not the part it
  resembles; `--deep` hands those to blastn's gapped search when it is installed.
- Repeat detection is a coarse exact-k-mer probe, not a full aligner.
- Host off-target uses a bounded exact-match net; it is a coarse recombination-substrate
  probe, not an aligner.
- The draft-spec rebuild is a *bridge*; the actual seal/hash/assemble is forward
  Katana's job, on purpose.

## Files

```
kagami.py        CLI + orchestration + text/JSON/HTML report
kg_parse.py      FASTA / GenBank reader (claims = features)
kg_refs.py       loads the public reference set from refs/
kg_identify.py   decomposition → blocks (pure Python; --deep adds blastn)
kg_seedmatch.py  the pure-Python identifier: exact for short refs, seeded for long
kg_audit.py      the checks (Katana conventions reused)
kg_bridge.py     draft Spec + intake requests (the round-trip, law-abiding)
build_refs.py    (re)generate refs/ from the sealed parts-library (public only)
refs/            reference_parts.tsv + .fasta (the bundled reference set)
make_demo.py     builds examples/demo.gb from the reference set
tests.py         87 self-contained checks
test_identify.py oracle tests for the identifier (truncation, mutation, edge inputs)
run_kagami.bat   Windows double-click wrapper
```
