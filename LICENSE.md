# Licence

This bundle contains three kinds of thing, under three sets of terms. They are separated
deliberately: a single licence covering all of it would be wrong for at least one of them.

## 1. Code — MIT

`verify.py`, `verify_library_v2.py`, `test_seal_gaps.py`, `katana_lock.py`.

```
MIT License

Copyright (c) 2026 Team WIST (iGEM 2026)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

MIT is an OSI-approved licence, which CC BY 4.0 is not — Creative Commons themselves advise against
using CC licences for software.

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
