# Design-layer defects fixed in Katana

Team WIST · iGEM 2026 · as of 2026-10-19

Of the 119 commits from the first one to now, 30 fixed a defect that was not a typo. Each
one required changing an assumption rather than changing a line. They collapse into twelve
wrong assumptions, and this report lists both.

---

## What counts, and how each entry was established

A **design-layer defect** is one where the code did what it was written to do and the
thing it was written to do was wrong. Spelling, a dead link, inaccurate help text, an
HTML-escaped apostrophe reaching a Windows batch file — those were fixed too, and they are
not in this list.

Every entry rests on three things, none of them memory:

1. **Git history.** Each entry names a commit. That commit's message carries the
   reproduction and the numbers measured at the time.
2. **Reproduction before acceptance.** A defect was reproduced before it was accepted as a
   defect. Review findings that did not reproduce were recorded as "measured, and correct"
   rather than fixed.
3. **Mutation testing.** After each fix, the fix was broken on purpose to see whether the
   test went red. A fix whose test stays green is not a verified fix.

Provenance is tracked separately, because not all of these were original sins. Some were
in the first design. Some were introduced when NCBI BLAST+ was replaced with pure Python.
A few were regressions in a fix of mine for an earlier defect on this list. All three
kinds are listed, marked in the **Origin** column.

---

## The twelve assumptions, and what broke them

No entry below is isolated. Each one is a consequence of one of these assumptions, and
each assumption had a reason behind it at the time.

| The original assumption | Why it was reasonable | What broke it |
| --- | --- | --- |
| A sequence is linear | The string in the file is linear; `topology` was read only to print the header | An iGEM construct *is* a plasmid. A plasmid has no start — the origin is whatever the person exporting the file happened to pick |
| One maximal-scoring diagonal is one alignment | Replacing BLAST+, a Kadane maximal-scoring segment is fast and exact | An insertion or deletion shifts the whole diagonal. An indel is the commonest cloning artifact there is |
| One sequence has one name | Parts in a library have IDs, and IDs are unique | The Registry holds the same bases under ten part numbers, and also deposits fragments of complete parts as parts in their own right |
| Checking identity is checking correctness | Checking "label vs. bases" is the reason this tool exists | A correctly named RBS pointed backwards does not initiate translation. Orientation and containment are separate claims |
| A reporting limit can double as the scope of a check | Truncating output beats printing twenty thousand rows | What got truncated included the thing that should have blocked. A number, once printed, does not look like a ceiling |
| A file's description of itself is trustworthy | A GenBank LOCUS line, the extension and the contents ought to agree | A truncated download, an interrupted write, and a student dropping in a photo all look like a file. None of them announces itself |
| The engine's refusal is a kind of exception | Implementing a refusal with `raise` is the shortest path | `except Exception` swallows it and then reports it as a missing tool: "gate unavailable — NOT enforced this run" |
| A module global can serve as configuration | A command-line tool runs once; reading `sys.argv` at import is natural | The same code is called as a library — by the GUI, by the web page, by `--json`, and by two threads at once |
| No bad news means it passed | A default has to be something, and PASS is the common case | "Nothing ran" and "everything ran and was fine" look identical on the way out |
| Writing the files successfully is finishing | Three output files are written in order; nobody loses power in between | A full disk, a wrong permission, a path that is a directory — the second file lands and the third fails |
| An ID appears once in a Spec | The whole point of the format: name parts only by ID and the name cannot drift from the bases | A YAML list permits a duplicate key. Two entries put two answers in the document |
| The tool will only be used correctly | The user is the person who wrote it | The user is a high-schooler. `deploy --out .` deletes the repository |

---

## The thirty defects

Grouped by assumption. Every number in "What was measured" was produced by running it at
the time, not estimated.

| Group | Defect | What was measured | Origin | Commit |
| --- | --- | --- | --- | --- |
| Linearity | Circular topology was ignored entirely; `identify()` read the sequence linearly whatever the record said | B0015 as a 129 bp circle, origin rotated by 26 bases → split into two hits (coverage 0.798 / 0.202) plus a truncation FLAG that was false. Rotated by 65 → two half-length pieces | Original design | `aeec04f` |
| Linearity | `record.sub()` was a plain linear slice, so a block crossing the origin silently got the truncated front half | sfGFP identified at 650–1369 on a 1049-base circular record came back 400 bases long, and the ORF check reported "length is not a multiple of 3" for a complete, intact 720 bp gene. The same molecule written from six origins gave three verdicts: PASS ×2, REVIEW ×2, FAIL ×1 | Original design | `2f859f0` |
| Linearity | The seam de-duplication keyed on the reference ID alone, so once any copy of a reference reached full coverage every other copy was discarded | A plasmid with a whole copy across the origin and a **truncated** copy in the middle reported only the whole one. The truncated part vanished from the report entirely | Regression in my own circular fix | `f67faf1` |
| One diagonal | A single indel destroyed identification outright — the two pieces each covered about half the reference and both fell under the 0.6 coverage floor | Real AmCyan bases labelled "sfGFP": intact, the mislabel FLAG fired at coverage 1.000; with **one base deleted**, identification came back empty and the mislabel count went to zero | Introduced in the rewrite (BLAST+ handled gaps) | `1fe0a38` |
| One diagonal | The indel merge counted overlapping bases twice, so identity exceeded 100% — and `pident` is `_tile`'s sort key | Across 60 references of 200–1200 bases with one base deleted at the midpoint, 21 of 60 reported over 100%, up to 104.9%. A sequence containing verbatim I741025 was reported as K1365999 at 100.2% with a FLAG for an indel it did not have | Regression in my own indel fix | `dc0fe6a` |
| One diagonal | Overlap was subtracted as an estimate (overlap × density), but the reference and query overlaps differ | 200 references, one base deleted at the midpoint: the estimate reported exactly 100.0 for 70/200 and an over-long aligned length for 134/200. After exact recounting, 0/200 of each | Regression in my own fix | `ec5f4ff` |
| One diagonal | A diverged end read as a perfect match, because Kadane clips a terminal run of mismatches | A full-length B0015 with its last eight bases substituted reported identity 100.0% and coverage 0.938 — both wrong, in opposite directions | Introduced in the rewrite | `b578712` |
| Name ↔ sequence | Identical sequences under different names were reported as mislabels | B0034's twelve bases, AAAGAGGAGAAA, are also J34801, J70591, K1325011 and six more. A student who labelled a block B0034 correctly was told "is actually K1325011" | Original design | `f76b0ed` |
| Name ↔ sequence | A fragment of a part outranked the complete part in `_tile`, because the fragment's coverage is 1.000 | The pSense-Nit GenBank that Katana itself wrote, carrying Katana's own `/label="PyeaR"`, was accused by Katana of a mislabel (K1799015 is exactly PyeaR[13:113]) | Original design | `2195c2e` |
| Name ↔ sequence | Accepting the containment and stopping there hid a genuine truncation | With only PyeaR[13:113] present and labelled PyeaR: NOTE "is correct", verdict PASS, and nothing said that 62 of PyeaR's 162 bases were absent | Regression in my own mislabel fix | `60f6d2a` |
| Beyond identity | There was no orientation check anywhere in `kg_audit`, for any label | Forward B0034 bases annotated as `complement(1..12)` → "Block labelled B0034 is correct". An RBS pointed the wrong way does not initiate translation of the CDS after it | Original design | `a4f0a9b` |
| Beyond identity | A nested claim was never audited — the tiler's "already covered" branch skipped it | B0015 annotated correctly at 1..129 plus the same inner bases annotated "B0034" (they are B0010): identity findings empty, verdict PASS. The claim did not disagree and was not skipped with a reason. It was gone | Original design | `254e426` |
| Limit as scope | The host off-target match length was capped at 60 bp, and the cap was printed as though it were the measurement | pSense-Nit's real value is 147 bp and it printed 60. 3000 bp of verbatim host chromosome also printed 60, with advice to "recode the host-identical stretch" | Original design | `b38b145` |
| Limit as scope | The off-target gate classified only the first 40 hits: `rows[:40]` had quietly become an enforcement limit | Rows are sorted by length, so 40 longer expected-locus hits can precede an unexpected 100-base 100%-identity match. That blocking hit was never inspected, and sealing proceeded | Original design | `4d40421` |
| Limit as scope | `MAX_LOCI` dropped the fifth and later occurrences in silence | Five tandem copies of B0015 returned four hits; the one at 517–645 was simply missing, so a wrong label on that copy got no identity comparison at all | Original design | `aeec04f` |
| Limit as scope | The browser version could only ever check against MG1655; both presets loaded the same bundled file | `get_genome.py` fetches 23 host genomes including *E. coli* Nissle 1917. A team whose chassis is Nissle was reading an answer about a different organism, with nothing on the page saying so | Original design | `b38b145` |
| File self-report | The length declared on the LOCUS line was never compared against the bases present | A file whose LOCUS said 129 bp with 60 bases present was audited as though whole. Every per-base finding is then a finding about a fragment, with nothing saying which it is | Original design | `cf49285` |
| File self-report | A file that is not a sequence was audited as a 0 bp sequence | Dropping in a PNG produced a formal audit header — "photo · 0 bp · linear" — and `[FAIL] Empty sequence`. None of those three claims was read from the file | Original design | `09ac586` |
| File self-report | `file_sha256` was not checked at the point of use | The build checked only `seq_sha256`, so a part file whose annotations had been edited — a label, a role — was used as-is. This is rule 3 of the project's own CLAUDE.md | Original design | `cf49285` |
| Refusal as exception | `_Refused` subclassed `Exception` and was swallowed by the dry-lab gate's `except Exception` | A blocking off-target hit of 240 bp at 99.1% identity to the host genome → verdict PASS, exit 0, no FAIL at all, and a log line reading "gate unavailable … NOT enforced this run". With dry-run off it would have gone on to write order files | Original design | `de36fb9` |
| Module globals | `build(library=...)` was ignored outright, because `LOCK_PATH` is resolved at import time | `build(spec, library="/definitely/nonexistent")` assembled 1,013 bases from the shipped library, reported PASS, and recorded the nonexistent path as the library it had used. The GUI passes the user's chosen library through exactly that argument | Original design | `4b7e8a4` |
| Module globals | Two concurrent builds interfered: `LIB`, `LOCK_PATH`, `sys.stdout` and `_REFUSE` are all process-global | Ten pairs of threads, 9 of 10 rounds wrong in both directions — including a construct the engine could not assemble coming back as REVIEW. In half the rounds `sys.stdout` was left pointing at an abandoned buffer | Original design | `4f07a3e` |
| Module globals | `verify.py` hard-coded its library path and never looked at `sys.argv` | `verify.py /nonexistent/path/LOCK.tsv` → `8/8 checks passed`, exit 0. This is the command the project's own CLAUDE.md tells people to run "before you believe anything" | Original design | `ff5f7e9` |
| No bad news | A `BuildResult` with no stages reported PASS and exit 0 | "Nothing ran" presented as "everything ran and was fine". An existing assertion, `check("an empty result is PASS")`, had pinned the defect as the guarantee | Original design | `9c234e9` |
| No bad news | `katana_build.py --json` exited 0 on a FAIL: `main()`'s return value was thrown away | On a LOCK.root mismatch the JSON said verdict FAIL, exit_code 1, and the process exited 0 — and `--json` is the path CI and scripts use | Original design | `4b7e8a4` |
| No bad news | The web page chose the verdict pill's colour by string-sniffing the human headline instead of reading `report.kind` | The ternary chain fell through the optimistic way, so a reworded FAIL headline rendered green. An unrecognised status also sorted below PASS via `?? 9`, burying it where nobody scrolls | New web front end, this round | `afe6392` |
| Write atomicity | A failed Stage 5 left the first two order files behind | An obstruction where only the CSV belonged left a 1083-byte vendor FASTA with that day's date on it — the exact file you paste into a vendor's order form | Original design | `56c5b8d` |
| Write atomicity | Intake re-sealed a damaged library, destroying the evidence | On a library with its last row removed, adding one part re-sealed the remaining rows under a fresh root. The library then verifies clean forever, and the proof that rows went missing is destroyed by the act of adding to it | Original design | `4d40421` |
| Spec format | One ID named twice produced a mislabelled sealed artifact | `HrpS.Ec-opt` pinned at v1 beside the real v3 entry: 15 entries counted as 14 parts with no note. The last entry won the bases while the first supplied the role and metadata. Sealed, hash-consistent, and wrong | Original design | `7273c84` |
| Misuse | `stage()` ran `rmtree()` on whatever `--out` named, and `--remote` was unrestricted while `publish()` force-pushes | Measured in a sandbox: a directory holding one unrelated file came back holding eighteen staged ones, the unrelated file gone. `deploy --out .` deletes the repository. `--remote` could replace any writable repository's main branch — including the iGEM GitLab project this deploy is under standing instruction never to touch | New deploy, this round | `45d5fa6` |

### The four worst

If only four are remembered, these four. They share one shape: **the engine had already
found the problem, and then reported PASS.**

1. **`de36fb9`** — the dry-lab gate refused, the exception was swallowed, the output was
   PASS and exit 0. Through the path `build()`, the GUI, the web page and `--json` all
   share. The command line escaped it only by accident.
2. **`1fe0a38`** — one indel destroyed identification, and a block with no identity is
   never compared against its claim. The single check this software exists to perform,
   skipped by the commonest cloning artifact there is.
3. **`7273c84`** — the Spec format's central promise (an ID and its bases cannot disagree,
   because there is only one of them in the document) broken by a duplicate key, with the
   engine producing the mislabel itself.
4. **`4f07a3e`** — 9 of 10 concurrent rounds wrong, including a construct that could not
   be assembled coming back as REVIEW. Latent: the shipped front ends are
   single-threaded, but `build()` is a public function.

---

## Measured, and deliberately not fixed

These four are limits, not defects. Each was measured, each has its numbers written in the
README, and none of them lets the program report something it did not check as checked.

| Limit | The number | Why it stands |
| --- | --- | --- |
| References between 26 and 42 bp cannot reach full coverage | `MIN_HIT = 25` | Lowering MIN_HIT makes short repetitive sequences hit in every construct, which is the cry-wolf failure |
| The stride prefilter misses a 40 bp reference carrying 3 substitutions | About 15 times in 200 | Closing it means abandoning the stride, and the cost is everybody's runtime |
| `MAX_LOCI` is still 4 | The fifth and later occurrences are not checked | Any cap drops the next one, so the cap is **reported** instead of raised |
| An insertion plus a compensating deletion does not merge into one finding | Within one Kadane segment | Two findings are better than one wrong finding |

The line is clear: these are limits on what is **detected**, written down where someone can
find them. The thirty above were cases of detecting it and then reporting it wrongly. The
second kind is a bug. The first is not.

---

## Still open

`kagami/examples/fail.gb` declares `100 bp` on its LOCUS line and holds 39 bases. Nothing
in the repository references it.

The new length check (`cf49285`) refuses the file, which is correct for a file in that
state. What has not been done is choosing a reading for it:

- Edit the header down to 39 — that asserts the file was always meant to be 39 bp.
- Pad the sequence up to 100 — that means writing 61 bases by hand.

The second breaks rule 1 of CLAUDE.md (never write a sequence from memory, including for a
test fixture). The first follows rule 4: when two sources disagree, return both readings
and do not decide for the human which one is true. So it is left exactly as it is, waiting
for someone who knows what the file was for.

---

## How these fixes were shown to be real

The current numbers: **984 assertions across 34 suites, 0 failures**, plus `verify.py` 8/8,
`test_seal_gaps.py` 8/8, `test_determinism.py` 10/10, and `test_web_pyodide.py` 24/0 —
that last one running in a real WebAssembly Python, not a stand-in.

The count by itself proves nothing. Each fix had to fall over once: reproduce the defect,
fix it, then break the fix on purpose and watch the tests go red. Some of those mutations:

| Mutation | Assertions that went red |
| --- | --- |
| Restore the string-sniffing verdict colour | 3 |
| Disable the identical-sequence synonym branch | 4 (widen it to swallow every claim: 3) |
| Disable the orientation check | 3 (make it fire for every block: 8) |
| Ignore the record's topology | 3 |
| Drop the cap notice | 3 |
| Restore the reference-ID de-dup key | 3 (remove the de-dup entirely: 8) |
| Put the host cap back to 60 | 12 |
| Restore the substring-search extension | 13 |

### Three things that make this list believable

**Tests lie too, and that was caught repeatedly.**
`check("a >5 kb reference exists to test against (SKIPPED)", True)` printed "ok" for
something the suite never checked (`254e426`). `check("an empty result is PASS")` had
pinned a defect as a guarantee (`9c234e9`). An indel assertion read `identity > 95%`, and
102.3 satisfies that (`dc0fe6a`). In the most recent round, three more assertions passed
for the wrong reason because they searched a whole file instead of the sentence in it —
including a recA− help-text check that found "500" elsewhere in `kagami.py` and went green
while the text was still false.

**CI and the filesystem now check each other.**
`test_seal_gaps.py` — the self-test that reproduces eight sealing exploits and asserts each
is blocked — was tracked in git and run by no CI job at all (`9f4d8e1`). Its default
library path was `.`, so a bare run failed at its first assertion, which is enough to
explain why it was quietly left out. Both halves were fixed, and `test_one_core.py` now
compares the CI script against the suites on disk in both directions: a suite that is
present but not run fails an assertion, and so does a suite named in CI that does not
exist.

**Findings that measured out correct were recorded as correct, not fixed.**
A multi-record FASTA genome is read in full — *S. cerevisiae* ships as 16 records and
*K. phaffii* as 4, and a reader that kept only the first chromosome would have checked a
construct against a sixteenth of a genome and called it clean. Measured; already correct.
A cp950 console was expected to crash the audit on a `UnicodeEncodeError`; measured, it
does not, because `kagami.py` already reconfigures its streams. Both are on record as
measured-and-correct with no code change.

---

> Names are claims. Hashes are facts. Never let a model supply either.
