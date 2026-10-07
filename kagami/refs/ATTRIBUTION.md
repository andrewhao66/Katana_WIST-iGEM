# Where the reference parts come from

Kagami identifies parts by comparing a sequence against a set of references. Most of those
references are not ours. This file says whose they are, under what terms, and how to check them.

## iGEM Registry of Standard Biological Parts

The bulk of `reference_parts.fasta` and `reference_parts.tsv` is a filtered mirror of the
**iGEM Registry of Standard Biological Parts**.

> All Registry content falls under **Creative Commons Attribution-ShareAlike**.
> — <https://parts.igem.org/Registry_API>

This work is therefore redistributed under the same terms: **CC BY-SA**. If you reuse this reference
set, attribute the iGEM Registry and share your derivative alike.

The parts were obtained from **SynBioHub** (Newcastle University and the University of Utah), which
hosts the Registry as SBOL, by querying its SPARQL endpoint. Each row's `provenance` column records
the exact per-part URI, so any sequence here can be traced back to its source record and re-checked
independently. The collection is a point-in-time snapshot dated **2017-04-03**, which is stated on
the collection itself, and every row says so.

- iGEM Registry: <https://parts.igem.org/>
- SynBioHub: <https://synbiohub.org/public/igem/igem_collection/1>

## What was filtered out, and why

This is a filtered mirror, not a complete one. From 36,001 parts carrying sequences:

| dropped | why |
|---|---|
| 16,722 | **composite devices** (Generator, Composite, Device, Translational Unit, Intermediate, Plasmid, Project). A reference that is itself several parts outranks the individual parts on match length and collapses the decomposition, which is the one thing this tool exists to do. |
| 569 | **primers**. A ~20 bp laboratory tool matches wherever its target sits and turns a construct into a cloud of spurious hits. |
| 214 | sequences too short to be a safe reference. |
| 1 | a name that collides with a part on a private research track, excluded by the publication gate. |

What remains is **18,419 atomic parts**, plus references drawn from this project's own sealed parts
library and from the live Registry API.

## The other sources in this file

The `provenance` column distinguishes them, strongest first:

| prefix | meaning |
|---|---|
| `parts-library …` | this project's sealed library; the sequence was re-hashed and matched against `LOCK.tsv` at build time |
| `iGEM Registry … uuid=… fetched=…` | fetched live from `api.registry.igem.org`, carrying the part's Registry uuid and the date |
| `SynBioHub … [iGEM collection snapshot 2017-04-03]` | the mirror described above |
| `seed — verify vs …` | typed in and **not yet confirmed** against a primary source; the weakest tier, and it says so |

## Rebuilding it

The library-derived and live-Registry rows regenerate from the sealed parts library:

```
python3 build_refs.py --registry-bulk
```

The SynBioHub mirror does **not** regenerate from anything in this repository. It was harvested
once — on 2017-04-03, as the collection itself is dated — by two scripts
(`build_synbiohub_refs.py` and `convert_synbiohub_refs.py`) that are **not** published here: they
needed a SynBioHub login and are not part of this bundle. The mirror is therefore a fixed input,
and the `provenance` column on every row records the exact per-part URI, so any sequence here can
be traced to its source record and re-checked independently.

Saying so plainly rather than listing commands that do not exist: an instruction you cannot
follow is worse than an acknowledged gap.
