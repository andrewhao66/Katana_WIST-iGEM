# Architecture

This document is for someone who wants to **extend, adapt or argue with** the engine. If you only
want to run it, the README is enough.

---

## The one idea

> **The Design Spec and the sealed Parts Library are the source of truth. The construct file is a
> generated artifact.**

Almost everything else follows from that sentence.

If a construct is *generated*, then it can be regenerated, and two regenerations can be compared. A
construct file stops being a thing you have to trust and becomes a thing you can **check**. You no
longer ask "is this file right?" — you ask "does this file equal what the Spec and the library
produce?", which is a question a computer can answer.

The practical consequence is a rule that sounds severe and is actually liberating: **you never edit a
construct.** To change one you edit its Spec and rebuild. Hand-editing a `.gb` is how a sequence and
its label drift apart, and drift is the failure this whole project exists to prevent.

---

## Data model

### Design Spec (`specs/*.spec.yaml`)

Intent, never sequence. A Spec says *what* the construct is made of and *why*, in terms a human
argues about:

```yaml
id: pSense-Nit
version: 3
host: E_coli_MG1655
backbone: {vector: ..., ori: ..., marker: ...}
assembly: {method: ...}
constraints: {fragment_bp_max: 5000, forbid_sites: [NdeI, ...], host_context: E_coli_MG1655}
parts:
  - id: PyeaR
    role: promoter
    class: reference
    source: {db: NCBI, accession: NC_000913.3, coords: ..., strand: ...}
  - id: RBS_hrpS
    role: rbs
    class: designed
    design_record: {tool: design-rbs, engine: ..., target_TIR: ..., host: ...}
architecture:
  order: [PyeaR, RBS_hrpS, HrpS.Ec-opt, B0015]
  trims: {PyeaR: {3prime: ...}}
```

**There is no field in which a raw sequence can be written.** That is the single highest-value design
decision in the format. A part is named by id and resolved from the library; a mislabelled part is
therefore not "unlikely", it is *unrepresentable*. You cannot paste the wrong bases into a Spec
because there is nowhere to paste them.

The `class` fork matters and is load-bearing downstream:

| class | means | carries | provenance edge |
|---|---|---|---|
| `reference` | fetched from a primary source | `source:` (accession + coords, or Registry part) | `wasDerivedFrom` |
| `designed` | computed by a tool (codon optimisation, RBS tuning) | `design_record:` (tool, host, version) | `wasGeneratedBy` |
| `synthesised` | ordered as written | design record | `wasGeneratedBy` |

A designed part has no accession to point at. Recording it as "derived from" one would be false, so
the engine does not.

### Parts Library (`parts-library/ref_parts/`)

One file per sealed part, named `<id>__v<n>__<first 12 of the sequence hash>.gb`, plus a manifest:

- **`LOCK.tsv`** — one row per part: id, version, sequence hash, length, file, source, date, and a
  `row_sha256` over the row itself.
- **`LOCK.root`** — a hash over all the row hashes.

Three levels, each catching something different:

| hash | catches |
|---|---|
| sequence hash | the bases changed |
| file hash | the file changed (annotation, whitespace) without the bases changing |
| row hash + root | the *manifest* was edited — you cannot quietly rewrite a row's recorded source or length |

Parts are **immutable**. There is no in-place edit: a corrected part is a new version with a new
hash, and the old row stays. History is append-only, so a build from last month can still be
reproduced.

---

## The pipeline

```
      Design Spec  ─────────┐
                            │
   Parts Library ───────────┤
   (LOCK + .gb files)       │
                            v
  ┌───────────────────────────────────────────────────────────────┐
  │  1 SOURCE    resolve each part id -> library file             │
  │              verify the Spec's pin matches LOCK               │
  │  2 VERIFY    re-hash every part ON READ, compare to LOCK      │
  │  3 ASSEMBLE  concatenate in architecture.order, apply trims   │
  │  4 VALIDATE  length, locatability, junctions, RE sites, GC    │
  │  4b DRY-LAB  host off-target scan + codon quality (optional)  │
  │  5 SEAL      hash the result, write .gb/.fasta, round-trip it │
  │  6 DIFF      compare against a prior build                    │
  └───────────────────────────────────────────────────────────────┘
                            │
                            v
        .gb  +  .fasta  +  SBOL 3  +  seq_sha256
```

Stages 0 (authoring the Spec) and 7 (ordering from a vendor) are human process, not code, and are
not part of this release.

**Every stage is a BLOCK, not a warning.** A failure stops the build. This is deliberate and it is
the property most likely to annoy you while also being the reason the engine is worth having: a
warning in a long log is a warning nobody reads.

### Why stage 2 exists at all

Stage 1 already checked the pin. Stage 2 re-reads the file and re-hashes it anyway.

This is not redundant. Stage 1 verifies a *claim in the Spec* against a *claim in the manifest* —
two pieces of metadata agreeing with each other. Stage 2 verifies the **actual bytes on disk**
against the manifest. A file that was replaced, truncated, re-saved by an editor, or corrupted in
sync passes stage 1 and fails stage 2.

The general rule, which is worth stealing whether or not you use this code: **trust nothing on read.**
Verification is not a thing you did once when the part was admitted; it happens at the point of use,
every time.

---

## The integrity model, and its one honest limit

`verify_lock_root()` performs two independent checks:

1. **Self-consistency — always on.** Recompute the root from the row hashes; it must equal
   `LOCK.root`. This catches an *edited manifest*: you cannot change a row without changing the root.
2. **External pin — only when you supply `--expect-root`.** The root must also equal a hash you
   provided out of band.

The second exists because the first has a real limit: a library can be **internally consistent and
still be the wrong library.** A stale sync, an old checkout, a second machine — each gives you a
perfectly self-consistent manifest describing parts you did not mean to build against. Only a pin
carried outside the library can catch that.

So the engine refuses to pretend: with no pin it says so explicitly, on every run, rather than
printing a reassuring tick. **Pin your builds in CI.**

---

## SBOL 3 export

`--sbol out.ttl` writes the build as SBOL 3 (Turtle, N-Triples, JSON-LD or RDF/XML).

SBOL 3 is RDF and carries PROV-O, which means the provenance this engine tracks internally has a
natural home in the standard rather than being flattened into a text note:

- `Component` per part, roles as Sequence Ontology terms, plus `SubComponent`s in build order with
  `meets` constraints expressing adjacency
- **reference part → `wasDerivedFrom`** a dereferenceable URI (an `identifiers.org` accession, or the
  iGEM Registry part page)
- **designed part → `wasGeneratedBy`** an `Activity`, with the design tool as an `Agent`

Two properties are deliberate and should survive any refactor:

**Sequences are emitted uppercase**, the engine's canonical form, so `seq_sha256` recomputes
*directly from the SBOL file* and matches the seal. Exporting to a standard must not cost you the
ability to verify what you exported.

**The file is encoded UTF-8 explicitly, then re-read and asserted.** RDF requires UTF-8, but the
underlying library serialises through the platform default encoding — so on a Windows console a
single non-ASCII character produces a file that parses locally and fails everywhere else. We shipped
that bug briefly, from one em dash in our own description text, and the assertion is what now stops
it recurring.

Identifiers are sanitised, not renamed: SBOL requires `^[a-zA-Z_][a-zA-Z0-9_]*$`, and real part names
contain `-` and `.`. Those become `_`, and the original id is preserved verbatim in `name`.

---

## Extension points

| You want to | Change |
|---|---|
| add a restriction site | `RE_SITES` in `katana_build.py` |
| forbid sites per construct | `constraints.forbid_sites` in the Spec — no code change |
| support another host for off-target scanning | `HOST_GENOME` / `HOST_ACCESSION` in `katana_drylab.py`, and drop the genome FASTA in `parts-library/ref_genomes/` |
| change codon-quality thresholds | `CAI_BLOCK` / `CAI_WARN` in `katana_drylab.py` |
| map a new part role | `feature_key_map` in `katana_build.py`, and `_role_for` in `katana_sbol.py` |
| emit another output format | follow `write_genbank` / `write_fasta`; keep the round-trip hash check |
| use a different assembly method | `gibson_split` is the worked example; splitting is driven by `architecture.gibson_split_after_index` |

The dry-lab gate (stage 4b) is imported defensively: if the module or its optional dependencies are
absent, the build continues and says loudly that the gate did **not** run. Optional checks that
vanish silently are worse than no checks, because they leave you believing you were covered.

---

## What this does not do

- **It does not design anything.** No sequence generation, no optimisation. It checks that what you
  think you have is what you actually have.
- **It does not replace sequencing.** It verifies the design side, before any DNA exists. Tools that
  verify physical DNA afterwards answer a different question; you want both.
- **The off-target scan is a pure-Python seed-and-extend**, not BLAST+. It is good enough to catch a
  long high-identity host match that no intended part explains — which is the misassembly signal it
  is there for — and it is not a substitute for a real alignment tool in a publication.
- **The tests test the engine, not your biology.** A passing suite means builds are deterministic and
  tampering is refused. It says nothing about whether your construct will work.

---

## Testing

`test_determinism.py` asserts the engine's central claim five ways: **oracle** (every Spec rebuilds
to a recorded hash from a real ordered construct), **repeatable**, **pin** (a wrong `--expect-root`
is refused), **tamper** (an edited manifest row is refused), and **SBOL** (the export is valid UTF-8,
reloads, revalidates, and its hash recomputes to the same seal).

Note what the suite deliberately does *not* pin: the library root. This bundle ships a curated subset
of a larger working library, and the two have different roots by construction, so the root is read
from whichever library is resolved. The **construct** hashes are the real invariant — they are
identical under both libraries, because the part sequences are.
