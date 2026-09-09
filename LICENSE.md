# Licence

This bundle contains three kinds of thing, under three sets of terms. They are separated
deliberately: a single licence covering all of it would be wrong for at least one of them.

## 1. Code — Apache License 2.0

Every `.py` file in this repository: the build engine (`katana_build.py`), the optional gates
(`katana_drylab.py`, `blast_offtarget.py`, `katana_sbol.py`), the verifier (`verify.py`,
`verify_library_v2.py`, `test_seal_gaps.py`, `katana_lock.py`) and the test suite
(`test_determinism.py`).

The full text is in **`LICENSE`** at the root of this repository, unmodified.

Copyright 2026 Team WIST (iGEM 2026).

Apache-2.0 rather than a licence that is silent on patents, for one concrete reason: section 3 grants
you an **express patent licence** covering the patent claims necessarily infringed by what is
contributed here. You can adopt this code without having to price in patent risk from us, which is
exactly the friction that stops institutions picking up student projects. It is also the licence iGEM
provisions these repositories with, and it is OSI-approved, as the Best Software requirements ask.

Note that CC BY 4.0 is **not** used for the code: Creative Commons themselves advise against applying
CC licences to software, and it is not OSI-approved.

## 2. Team-authored content — CC BY 4.0

`README.md`, `AGENTS.md` / `CLAUDE.md`, this file, and the Design Specs in `specs/`.

Released under [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/),
matching the iGEM wiki licence. Use it, adapt it, put it in your own repository; just say where it
came from.

## 3. The sequences — third-party, see `LOCK.tsv`

The DNA sequences in `parts-library/ref_parts/` are **not ours to license.** Each one carries its
source accession and coordinates in `parts-library/ref_parts/LOCK.tsv`, and the terms of that source
apply to it:

- Addgene deposits are subject to their UBMTA and to the depositing lab's terms.
- NCBI records are public.
- iGEM Registry parts are under the Registry's terms.

We are redistributing verbatim third-party sequence with its provenance attached. If you intend to
use a part, follow the accession in `LOCK.tsv` back to its source and check the terms there. That is
what the accession is for.
