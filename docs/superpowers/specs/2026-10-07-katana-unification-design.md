# Katana / Kagami Unification — Design Spec

**Date:** 2026-10-07
**Status:** Draft for review
**Scope:** Merge the forward engine (Katana) and the reverse auditor (Kagami) into one product
with a shared stdlib-only core, remove every hard external dependency, and ship three front ends
(CLI, desktop GUI, static web page) over one implementation.

This document is written in English, matching the repository convention and the decision that the
product is English-only.

---

## 1. Why

### 1.1 The observed failure

Zero of the non-software team members asked to install and use this project succeeded, including
after hours of effort and after asking an AI assistant for help. That is the problem this design
exists to solve. The engine itself is not the problem: its 107 assertions pass, it is
deterministic, it fails closed, and it produced the constructs this team ordered from a synthesis
vendor.

### 1.2 Measured causes

Every item below was reproduced on a clean macOS 27.0 machine, not inferred.

| Cause | Evidence |
|---|---|
| **macOS Gatekeeper rejects the downloaded launcher** | `spctl -a -vv -t open run_kagami_gui.command` → `rejected, source=no usable signature` once the file carries `com.apple.quarantine`, which every browser download sets. The launcher's own comment recommends "Right-click → Open", a bypass Apple removed in macOS 15. |
| **The team cannot reproduce it** | `git clone` does not set the quarantine attribute; browser downloads do. Developers clone, testers download. The same acquisition-path asymmetry is already recorded in `.gitattributes` for the CRLF incident. |
| **Every README command fails on stock macOS** | README uses `python` 12 times and `python3` zero times. `python` does not exist on macOS, even with a python.org install. The `BLOCK: PyYAML is missing` recovery message also says `python3 -m pip install pyyaml`. |
| **The documented install pulls 15 packages / 36 MB** | `pip install -r requirements.txt` resolves to 15 packages including `rdflib`, `pyshacl` and `owlrl` (an OWL reasoner), to support one optional exporter. The core needs PyYAML alone (888 KB). Atomic failure: one unavailable package fails the whole command. |
| **The "exact pins" are 3 of 15** | `requirements.txt` claims exact pins make the build reproducible. Only the 3 direct dependencies are pinned; `pyshacl` drifted 0.28.1 → 0.40.1 within one session. |
| **The Windows BLAST+ install commands are corrupt** | `README.md` is the only file in the repository containing `0x08` (backspace) bytes — 6 of them on 3 lines. `"$env:TEMP\blast.exe"` was written as `"$env:TEMP"` + BACKSPACE + `last.exe`. Both PowerShell one-liners are broken for their only audience. |
| **No front door** | 13 Python entry points plus 4 launchers. The root README mentions Kagami zero times and the GUI zero times — the zero-dependency, double-clickable, working window is invisible to anyone reading the front page. |
| **55 flags across 7 tools** | `katana_build` 10, `add_part` 13, `find_part` 7, `get_genome` 5, `katana_init` 3, `check_design` 1, `kagami` 16. |
| **The core workflow requires hand-copying a hash** | `add_part.py` prints a YAML `seal:` block for the user to paste into a Spec, change `role: SET_THIS`, and add the id to `architecture.order`. Half of `check_design.py` exists to catch failures of those three manual steps. The project's own `katana_order_table.py` states that retyping is where a sequence and its label come apart. |

### 1.3 Why not a rewrite

A previous rewrite attempt produced repeated crashes and carried latent problems forward. The
value in this codebase is not its structure but roughly twenty post-mortems encoded in its
comments and tests: tandem stop codons are terminal not premature, composite devices swallow their
own parts, RBS spacing must be measured from the Shine-Dalgarno core not the block edge, `.bat`
files must be CRLF or `GOTO` resumes on the wrong line, SBOL must be written as explicit UTF-8
bytes, identification must never fail silently. A rewrite reproduces the structure and loses the
post-mortems.

None of the changes in this document require rewriting the engine. All of the measured failures
live in a thin shell above it.

---

## 2. Goals, non-goals, success criteria

### 2.1 Goals

1. A non-technical high-school student can install and run the tool by following a few steps that
   do not include installing Python, installing git, installing pip packages, or choosing between
   entry points.
2. One product, one name, one shared core — not two tools with eight copies of the same manifest
   parser.
3. A web front end requiring no installation at all.
4. Reliability: no silently floating dependency versions, no silently skipped checks, no
   prose-greping between components.

### 2.2 Non-goals

- **The engine's correctness is not in scope.** The staged pipeline, the validation rules, the
  audit checks and the hashing conventions are preserved exactly.
- **The data formats do not change.** `LOCK.tsv`, `LOCK.root`, the sealed part filename convention,
  and the Design Spec schema are unchanged. The shipped parts library stays sealed.
- **No internationalisation.** The product is English-only. This was considered and dropped; the
  codebase is already 100% English, so the decision removes planned work rather than adding it.
- **No new science.** No sequence generation, no optimisation, no assembly planning.

### 2.3 Success criteria

| Criterion | Measurement |
|---|---|
| Install succeeds for non-technical members | A majority of members who previously failed now reach a verdict screen unaided, on their own machine, with a screen recording of each attempt. The recordings are the primary artifact: the current 0/N has no recorded error messages, so the diagnosis in §1.2 is reproduced rather than observed |
| Construct hashes unchanged | `test_determinism.py` ORACLE passes for all 7 bundled Specs |
| No regression | All 107 existing assertions stay green at every migration step |
| Zero hard external dependencies | A build and an audit both succeed on a machine with no pip packages and no BLAST+ |
| Identification parity | The truncation and point-mutation suite (§4.1) matches the blastn baseline |

---

## 3. Architecture

### 3.1 Repository structure

```
katana/
  katana                    # single entry point (.command / .bat); no args → interactive menu
  core/                     # ★ stdlib only, plus _vendor/yaml. MUST run under Pyodide.
    hashing.py              #   seq_sha256 / file_sha256 / row_sha256 / lock_root — one definition
    lock.py                 #   LOCK read / write / resolve / verify — replaces all 8 parsers
    spec.py                 #   Design Spec load + validate
    parts.py                #   GenBank / FASTA read + write
    seqops.py               #   revcomp, GC, homopolymer, repeats, RE sites — shared both directions
  forward/                  # was Katana
    build.py                #   stages 1–6, exposes build() -> BuildResult
    drylab.py  sbol.py  order_table.py
    intake.py               #   was add_part.py
    find.py                 #   was find_part.py
    genome.py               #   was get_genome.py
    design_check.py         #   was check_design.py
  reverse/                  # was Kagami
    parse.py  identify.py  audit.py  refs.py  registry.py  bridge.py  rebuild.py
  ui/
    cli.py                  #   argparse + interactive menu
    gui.py                  #   tkinter; merge of kagami_gui.py + kg_katana_tabs.py
    web/                    #   static site: index.html + Pyodide loader
  data/
    refs/                   #   reference_parts.tsv + .fasta
    genomes/                #   MG1655 (gzipped)
  parts-library/            # unchanged, sealed
  specs/                    # unchanged
  _vendor/yaml/             # vendored PyYAML, pure Python
  tests/
```

### 3.2 The constraint that makes the design work

`core/` must run under Pyodide, so it may use only the standard library plus the vendored YAML
parser. No `subprocess`, no `shutil.which`, no platform assumptions, no network.

This is not a cost imposed by the web requirement — it is the discipline the current codebase
lacks. There are presently **8 independent `LOCK.tsv` parsers** (`katana_lock.py`,
`katana_build.py`, `add_part.py`, `find_part.py`, `kg_refs.py`, `kg_rebuild.py`,
`kg_katana_tabs.py`, `build_refs.py`). `katana_lock.py` is the intended shared core, has the
correct API, and is imported by only two files — both on the verifier path. Nothing forced
convergence. The Pyodide constraint does.

### 3.3 Web compatibility, audited

| Module | Non-stdlib or non-portable use |
|---|---|
| `kg_parse` `kg_refs` `kg_audit` `kg_bridge` `katana_build` `katana_drylab` `katana_lock` `verify_library_v2` | none — portable as-is |
| `kg_identify` `blast_offtarget` | `subprocess`, `shutil.which` — both removed by §4 |
| `kg_registry` | `urllib` — needs a `pyodide.http` shim; affects only the optional `--registry` check |
| external | `yaml` (vendored), `sbol3` + `python_codon_tables` (optional) |

After §4 and §5, essentially the whole engine runs in the browser unmodified. The web front end is
not a port; it loads the same `.py` files.

### 3.4 Naming

Product: **Katana**. Two verbs: `check` (the former Kagami audit) and `build` (the former Katana
pipeline). Kagami is credited in documentation as the origin of the check engine. One name on the
wiki, one name in the download.

---

## 4. Remove the BLAST+ dependency

### 4.1 Measured justification

`kg_identify.identify()` requires `blastn` and `makeblastdb` on `PATH`, and rebuilds a BLAST
database of 18,538 sequences in a temporary directory **on every run**. Database construction
dominates the cost.

A pure-Python identifier was prototyped (throwaway, in a scratch directory) and compared
block-by-block against blastn through the same `_tile()`, on real files.

**Capability — identical:**

| Case | blastn | pure Python |
|---|---|---|
| Full part (B0015 129 bp / sfGFP 720 bp) | 100.0% id, 100% cov | identical |
| Truncated to 90% | 100.0% id, 90% cov | identical |
| Truncated to 80% | 100.0% id, 80% cov | identical |
| Truncated to 60% | 100.0% id, 60% cov | identical |
| +3 point mutations | 97.7% id, 100% cov | identical |
| +10 point mutations | 98.6% id, 100% cov | identical |
| +40 point mutations | 94.4% id, 100% cov | identical |

8/8 agreement. Truncation detection (the `cov < 0.95` truncation FLAG) and point-mutation
identification — the audit's two most valuable checks — lose nothing.

**Speed — roughly 2× faster:**

| Input | blastn | pure Python |
|---|---|---|
| `demo.gb` (843 bp) | 6.5 s | 3.3 s |
| `pSense-Nit` insert (1013 bp) | 7.5 s | 3.6 s |
| `pAP-Logic` insert (3517 bp) | 6.9 s | 3.7 s |

**Boundary accuracy — pure Python is better on the diverged case.** `HrpR.Ec-opt`, a
codon-optimised designed CDS matching Registry part `K1014001` at ~85% identity:

| | Block | 5′ error |
|---|---|---|
| True (computed from LOCK lengths and the Spec's trims) | 1293–2237 | — |
| blastn | 1407–2224 | **114 bp** |
| pure Python | 1293–2240 | **0 bp** |

Block boundaries decide which bases the ORF check and the RBS→ATG junction check run on, so this
matters. blastn performs local-alignment optimisation and pulls boundaries inward to maximise
score; fixed full-reference alignment is more faithful to the question "which part is this block".

### 4.2 Algorithm

Hybrid, forced by the reference length distribution (894 of 18,538 references are < 25 bp, 123 are
< 12 bp, and short RBS parts are exactly where the B0032/B0034 class of mislabel occurs):

- **References ≤ 25 bp:** direct `str.find` exact match against the query and its reverse
  complement. C-speed, and stricter than blastn.
- **References > 25 bp:** index the query's k-mers (k = 12), stream each reference with q-gram
  stride filtering, group seeds by diagonal, then **align the full reference against the
  corresponding query window** and compute identity over the whole reference length.

The full-reference alignment is load-bearing. An earlier prototype extended only to the last seed,
which under-reported coverage when a mutation fell near the end of a part — `B0015 + 3 mutations`
read 99.1% id / 89% cov and would have raised a **false truncation FLAG** on a full-length part.
Aligning the whole reference fixed it to exactly blastn's 97.7% / 100%.

### 4.3 Low-complexity filtering

`kg_identify._blast()` currently passes `-dust no -soft_masking false`, explicitly disabling
blastn's low-complexity filter. Consequently a reference such as `I735001` (`AAAAAAAAAA`, ten A's)
matches anywhere, and 61 references are shorter than 10 bp. Both engines produce this noise; it is
a reference-set quality problem, and filtering it improves both.

Rules:
- Reject references shorter than 12 bp as non-identifying (random-match expectation above the
  noise floor).
- Reject pure homopolymers (one distinct base) and sequences where a single base exceeds 80%.

**Do not reject sequences merely for containing ≤ 2 distinct bases.** A prototype rule of
`len(set(s)) <= 2` deleted **B0034 = `AAAGAGGAGAAA`**, which contains only A and G — because
purine richness is the Shine-Dalgarno sequence's function, not noise. RBS parts are the single
most important class for the mislabel bug this project was built around.

### 4.4 Identification threshold

Matches below ~90% identity are reported as **unidentified**, with a note that a diverged homolog
may be present and that installing BLAST+ enables a deeper search. Rationale: an 85% match is not
the part it resembles, and reporting it as that part with partial coverage generates a confusing
false truncation FLAG — which is what blastn does on `HrpR.Ec-opt` today.

Note the interaction with §4.1: once this threshold is in place, the `HrpR.Ec-opt` block becomes
"unidentified" rather than a boundary-accurate identification of `K1014001`, so the 114 bp boundary
comparison no longer applies to it. The win there is not better boundaries on diverged homologs —
it is ceasing to emit a false truncation FLAG on a full-length designed part. The boundary-accuracy
property still matters for every block in the 90–100% band, where identifications are reported.
The threshold is stated as "~90%" because it needs calibration against the bundled Specs before
being fixed; that calibration is part of migration step 1.

### 4.5 blastn's residual role

`blastn` remains an **optional accelerator and deepener**: used when present for gapped,
distant-homology search, never required. This is already the pattern in `blast_offtarget.py`
(`real_blast if shutil.which("blastn") else fallback`); only `kg_identify` never received it. Note
that `katana_drylab.py:114` already calls `B.fallback` directly and never calls `real_blast`, so
the forward engine's off-target gate has never used BLAST+ — contrary to the README's "Installing
BLAST+" section, which must be corrected.

### 4.6 Consequences

- Install loses 136–400 MB, the `PATH` concept, and the terminal-restart step.
- The two corrupt PowerShell one-liners are deleted outright.
- The GUI's opening "One feature needs a free add-on" banner is deleted — no longer true.
- `identification did NOT RUN` loses its most common trigger, so **identification always runs**,
  structurally closing the hole that let a planted mislabel read `PASS — clean to order`.
- The `check_blast()` skips in `kagami/tests.py` and the dedicated no-blastn CI job lose their
  reason to exist.

---

## 5. Remove the PyYAML dependency

PyYAML is pure Python and vendors cleanly. Verified: copying the installed `yaml/` package into
`_vendor/`, deleting the optional `_yaml*.so` C extension, and prepending `_vendor` to `sys.path`
gives a working `yaml.safe_load` under the system `python3` with nothing installed (888 KB with the
`.so`, ~700 KB without).

Do **not** write a YAML subset parser. `katana_build.load_yaml_simple`'s docstring claims to be a
"Minimal YAML-subset loader (avoids PyYAML dependency)" but its body imports `yaml` and exits if
missing — the function was never written. For a project whose thesis is the absence of subtle bugs,
hand-writing a YAML parser is the wrong trade. Vendor the real one.

`requirements.txt` splits:

- `requirements.txt` → empty, with a comment stating the engine needs nothing.
- `requirements-optional.txt` → `sbol3`, `python-codon-tables`, fully pinned via `pip freeze`
  including transitive dependencies, so the "exact pins" claim becomes true.

In a packaged bundle the optional extras are included, because bundle size is not a constraint.

---

## 6. One implementation, three renderers

### 6.1 The problem

The GUI runs the engine as a subprocess and greps its English prose:

| Consumer | Greps | Location |
|---|---|---|
| `kg_verdict.classify()` | `"BLOCK"`, `"NOT enforced"`, `"SEALED:"` | `kg_verdict.py:18-30` |
| `kg_rebuild.rebuild()` | `".gb:"`, `".fasta:"`, `".csv:"`, `"Output:"` | `kg_rebuild.py:212` |
| `test_determinism.py` | `seq_sha256:\s*([0-9a-f]{64})`, `"not self-consistent"` | `:96`, `:229` |

The engine's human-readable output is therefore a machine interface. Rewording any message breaks
the GUI's verdict **silently**: `classify()` failing to find `SEALED:` falls through to "exited
cleanly but printed no SEALED line" and reports REVIEW — a successful build presented as a problem.

### 6.2 The fix

```python
# forward/build.py
def build(spec_path, library, opts) -> BuildResult:   # the only implementation
    ...
```

`ui/cli.py` renders `BuildResult` as text, `ui/gui.py` as widgets, `ui/web/` as HTML, and `--json`
serialises it. The same shape applies to `reverse/audit.py`, which already returns
`list[Finding]` — the pattern exists, it simply is not used across the subprocess boundary.

`kg_katana_tabs.py`'s stated reason for shelling out is sound: "each button runs the engine's own
CLI tool as a child process, so there is exactly one implementation of every gate and the window
cannot disagree with the command line." Calling one function achieves that goal more strongly —
one literal code path returning a structured object, rather than two paths agreeing by discipline.
It also removes subprocess startup cost and the flashing console window on Windows.

---

## 7. Front ends

### 7.1 CLI and interactive menu

```
./katana                         # interactive menu
./katana check my.gb
./katana build my.spec.yaml
./katana verify
./katana add --registry BBa_B0015
./katana gui
```

With no arguments:

```
Katana — what do you want to do?

  1) Check a sequence         someone sent me a file; is the label true?
  2) Build a construct        Design Spec → order-ready sequence
  3) Check the parts library  re-hash everything, then try to break the checker
  4) Add a part to my library
  5) Open the window

Choose (1-5):
```

The menu asks one question at a time with defaults. All 55 flags remain available for CI and
technical members; nobody is required to meet them.

### 7.2 Desktop GUI

`kagami_gui.py` + `kg_katana_tabs.py` merge into `ui/gui.py` with tabs **Check / Build / Library**.
It calls functions directly per §6. Existing properties are preserved: colour never carries meaning
alone, work runs on a thread, every Tk variable is read on the main thread before the worker
starts.

### 7.3 Web

**Hosting.** Static files only — no server, no database, no recurring cost, and nothing to maintain
after the team dissolves. Three delivery routes, not mutually exclusive:

| Route | Mechanism | Where it is pushed | Status |
|---|---|---|---|
| **Local** (required) | The web front end ships inside the zip. `./katana web` starts a `http.server` on localhost and opens the browser | nowhere — it is a file in the bundle | always available, works offline |
| **Public link** (decided) | GitHub Pages | `https://github.com/andrewhao66/iGEM-katana-webtest.git` — a separate repository, **not** the iGEM GitLab project | decided; this is the only remote anything is pushed to |

The iGEM GitLab project (`origin`) is **never pushed to** as part of this work. The only outward
push is the static web bundle to the GitHub repository above.

**What gets pushed.** The published site is not just `ui/web/` — Pyodide fetches the engine modules
and the data files over HTTP, so the deployable artifact is a staging directory containing
`ui/web/` plus `core/`, `reverse/`, `_vendor/yaml/`, `data/refs/`, `data/genomes/` and the sealed
`parts-library/`. A build script assembles that staging directory and pushes it to the web
repository's default branch; the main repository keeps the sources. The script is the single
supported way to publish, so the published site can never be a hand-assembled variant of the
engine — the same rule the rest of the project applies to constructs.

Note that `file://` is not sufficient: Pyodide fetches the `.py` modules and data files over HTTP,
and browsers block those requests from `file://` origins. Hence `./katana web` starts a local
server rather than just opening the HTML. That is one command, which the project's constraints
allow.

The local route is implemented first, because it has no external dependency and makes the web
front end testable in CI. A public link is added once the hosting question above is answered.

**Execution:** the user's browser, via Pyodide, loading the same `core/` and `reverse/` modules.

**First load:** ~10 MB Pyodide runtime + 3.0 MB gzipped reference set + 1.4 MB gzipped genome +
~200 KB sealed library. Browser-cached thereafter.

| Capability | Web |
|---|---|
| `check` a sequence (drag a file in) | full |
| Verify the sealed parts library | full, read-only |
| Read-only demo build from the shipped library | yes |
| `add_part` / build against your own library | **no** |
| `--registry` live claim check | needs a `pyodide.http` shim; optional |

The exclusion is deliberate. A parts library must persist and live in git — sealed, versioned,
`git log`-able. Holding it in browser storage would contradict the project's central premise. A
library you cannot audit over time is not what Katana is about.

**Privacy:** execution is client-side, so `blast_offtarget.py`'s stated property — no sequence
leaves the machine — is preserved rather than traded away.

---

## 8. Packaging

One zip per OS, containing a bundled Python runtime, the vendored YAML parser, the data directory,
and no BLAST+.

```
download katana-mac.zip → extract → cd katana → ./katana
```

| Launch path | macOS Gatekeeper |
|---|---|
| `./katana` from Terminal (a shell script) | **not blocked** (measured) |
| Double-click | blocked unless signed **and** notarised **and** stapled |

Gatekeeper's block is a LaunchServices (double-click) behaviour. Executing a shell script from a
terminal is unaffected because the kernel execs the signed system `/bin/bash`; the script is data.
Measured: a quarantined `.command` runs correctly via both `bash script` and `./script`, while
`spctl` rejects it for `open`.

Therefore the documentation makes the Terminal path primary and double-click a bonus, and the
Apple Developer Program ($99/year) becomes **optional** rather than required. If a frictionless
double-click is wanted later, all three steps are required — signing alone is insufficient on
macOS 10.15+ — and an organisation account is preferable to an individual Apple ID, because iGEM
teams dissolve annually and the account must be handed over. Already-notarised and stapled builds
keep working after a membership lapses.

**Unresolved risk.** Whether a bundled Python Mach-O binary is Gatekeeper-killed when exec'd from
the launcher script was **not** measured — the test machine's clang/SDK is broken, so no test
binary could be compiled. This must be tested during packaging, not assumed. Fallback: the
`katana` script detects the condition and uses the system `python3`.

Good news measured on the target platform: `codesign`, `notarytool`, `spctl` and `stapler` are
already present, and the installed `python3` is `universal2` (x86_64 + arm64), so one bundle serves
both Intel and Apple Silicon Macs.

---

## 9. Defects fixed as a consequence

The refactor fixes three findings from `CODE-REPORT.md` structurally rather than by patch:

| ID | Defect | Fixed by |
|---|---|---|
| **🔴0** | Gatekeeper rejects the downloaded launcher; the documented "Right-click → Open" bypass no longer exists | §8 — Terminal path documented as primary; stale advice removed |
| **🔴A** | `katana_build.verify_lock_root()` hashes the `row_sha256` column as written instead of recomputing it from the fields, so editing a recorded accession passes the build gate. Verified: a falsified `source` field built to completion with exit 0, while `verify_library_v2.py` reported two problems | §3.2 — one `core/lock.py` that recomputes row hashes; `katana_lock.row_sha256()` already exists |
| **🔴B** | `resolve_parts()` selects `max(version)` and compares the Spec's pin only against that row, so a Spec pinned to an older sealed version is refused — contradicting `ARCHITECTURE.md`'s "a build from last month can still be reproduced". Verified by re-pinning `HrpS.Ec-opt` to its sealed v2 | §3.2 — resolve by pin or `seal.lib`; `katana_lock.resolve()` already has the correct semantics |

Documentation defects to correct in the same pass: the 6 backspace bytes in `README.md`; `python` →
`python3` throughout including BLOCK messages; the README's claim that the off-target gate shells
out to BLAST+; `kagami/README.md`'s "25 public parts" (actual 18,538) and "11 self-contained
checks" (actual 88); `ATTRIBUTION.md`'s reference to `build_synbiohub_refs.py` and
`convert_synbiohub_refs.py`, neither of which is in the repository.

---

## 10. Migration order

Every step must leave all 107 existing assertions green. Step 3 is the only genuinely dangerous
one; each parser migrates in its own commit so a regression can be bisected.

| # | Step | Risk | Safety net |
|---|---|---|---|
| 1 | Remove BLAST+: rewrite `kg_identify` on the pure-Python identifier | medium | Add the truncation and point-mutation regression suite (§4.1) **before** touching the module |
| 2 | Vendor PyYAML; split `requirements.txt` | low | 107 assertions |
| 3 | Extract `core/`; migrate the 8 LOCK parsers one at a time | **high** | 107 assertions; fixes 🔴A and 🔴B; one commit per parser |
| 4 | `build()` returns `BuildResult`; CLI renders it; add `--json` | medium | Tests for the JSON output itself |
| 5 | GUI calls functions instead of subprocesses | low | Port `kg_verdict.classify`'s 8 assertions to `BuildResult` |
| 6 | Single `katana` entry point plus interactive menu | low | New tests |
| 7 | Web front end (local route first, per §7.3) | low — additive | Browser smoke test |
| 8 | Packaging; measure the Gatekeeper risk in §8 | medium | CI builds and smoke-tests both OS bundles |
| 9 | **Final review gate** (§10.2) | — | three independent review passes |

### 10.1 Commits

**Every step ends in a local commit, on a working branch, never on `main`.** Nothing is pushed to
GitLab at any point in this plan; publication is a separate decision the team makes afterwards.

Within step 3, each of the eight LOCK parsers migrates in its own commit, so a regression can be
bisected to a single parser.

Each commit message states which step it belongs to and records the assertion count that passed,
so a later bisect can tell a genuine regression from a step that was always red.

### 10.2 Final review gate

After step 8, before the work is considered done, three independent review passes run. They are
independent on purpose: each has a different failure mode, and the point is that no single reviewer
— including the one who wrote the code — is load-bearing.

| Pass | What it is | What it is looking for |
|---|---|---|
| **1. Self review** | A full read of the diff against this spec, section by section | Scope drift; anything in §12 that changed; any invariant in §10.3 no longer asserted; placeholders; dead code left from the migration |
| **2. Subagent review** | Dispatched reviewers with no memory of writing the code, one per dimension (correctness, the `core/` extraction, the identifier's numerical behaviour, the UI front ends, packaging) | Defects the author is blind to, especially in step 3's parser migration. Findings are verified before being reported, not listed speculatively |
| **3. Codex review** | The Codex plugin. Confirmed available on the development machine: `codex-cli 0.154.0`. Re-check with `codex:setup` before the gate runs | A second model's independent diagnosis. Skipped with an explicit note if the CLI is unavailable — never silently omitted |

The review gate asserts the full invariant set in §10.3 one final time, plus:

- the five success criteria in §2.3, each with its measurement recorded
- that no finding from §9 has regressed
- that the identifier still reproduces the 8/8 parity table in §4.1

A review pass that cannot run is reported as not-run, never as passed. That rule is the project's own
(`katana_drylab.py`'s loud `NOT enforced this run`, and `kg_audit`'s `SKIP` tier): "we did not check" must never read as "we checked and
it is fine".

### 10.3 Invariants to assert at every step

- The 7 bundled Specs reproduce their recorded ORACLE hashes.
- `verify.py` reports 30 parts sealed and 8/8 adversarial checks caught.
- `LOCK.tsv`, `LOCK.root`, part filenames and the Spec schema are byte-compatible.
- The shipped parts library is not modified.

---

## 11. Decisions

All three previously open decisions are settled.

| Decision | Resolution |
|---|---|
| **Product name** | **Katana.** Two verbs: `check` (the former Kagami audit) and `build`. Kagami is credited in documentation as the origin of the check engine. |
| **Web boundary** | As specified in §7.3: no `add_part`, no builds against a user's own library. A parts library must stay in git. |
| **Apple Developer account** | **Not purchased.** The Terminal launch path is not Gatekeeper-blocked (§8), so signing is unnecessary. Double-click will show a warning; the documentation directs users to the Terminal path. |

---

## 12. What is explicitly not changing

The staged pipeline and every gate in it. The hashing conventions. `LOCK.tsv` / `LOCK.root` /
sealed filenames. The Design Spec schema, including the deliberate absence of any field in which a
raw sequence can be written. The shipped sealed parts library. The audit's five-tier verdict model.
The rule that a part enters a library only from its primary source, and that Kagami reports but
never seals.

---

## 13. What was built, and what the review found

Added after implementation. This section records the outcome, including the parts that
turned out differently from the plan and the defects the review gate caught — because a
spec that only describes the intention is a spec that cannot be checked against the thing
that got built.

### 13.1 Delivered

| Step | Outcome |
|---|---|
| 1. Zero external dependencies | `kagami/kg_seedmatch.py` replaces blastn; PyYAML vendored at `_vendor/yaml/` (248 KB, `.so` removed). `pip install` is no longer part of using Katana. BLAST+ survives as an opt-in `--deep`. |
| 2. Shared core | `core/hashing.py`, `core/lock.py`, `core/parts.py`, `core/result.py`. One implementation of the manifest, the hashes and the result object. |
| 3. One front door | `./katana` and `katana.bat`, with a menu when asked nothing. 13 entry points became 1. |
| 4. Browser front end | `ui/web/` runs the engine's own `.py` modules through Pyodide. `./katana web` serves it locally; `./katana deploy` stages the static site. |
| 5. Packaging | `./katana bundle` writes a 5.3 MB zip: unzip, `cd`, `./katana`. Byte-identical across builds, so a release can be checksummed. |
| 6. Review gate | Self-review and a Codex review, both acted on. See §13.3. |

### 13.2 Measured, not asserted

- **655 assertions across 25 suites**, all of them run by CI, with a test that checks that
  claim against the filesystem in both directions.
- Every suite passes on a bare interpreter with `blastn` hidden from `PATH` and no pip
  packages installed, and on the **Python 3.9** that macOS ships.
- All **7 bundled Specs reproduce their recorded ORACLE hashes**, and the order files are
  **byte-identical between Python 3.9 and 3.13** — a seal that depends on the interpreter
  is not a seal.
- The browser path is verified in a **real Pyodide**, not a mock: 18,255 reference parts
  load in 1.6 s and the demo audits in 5.8 s, catching its planted mislabel.
- `parts-library/` and `specs/` are **byte-identical to `main`**.

### 13.3 Defects the review gate found

Twenty in total — four by self-review, sixteen by Codex. Every one was reproduced before
being accepted. The six that would have mattered most to somebody using this:

1. **A stage that refused came back as a PASS, and sealed.** `_Refused` subclassed
   `Exception`, so the dry-lab gate's own `except Exception` caught the engine's refusal
   and reported it as a missing tool. A blocking off-target hit of 240 bp at 99.1%
   identity returned verdict PASS, exit code 0, and no FAIL finding — through the path the
   GUI, the web page and `--json` all use. A refusal is control flow, not an error; it is
   a `BaseException` now.
2. **Circular topology was ignored.** A part sitting across a plasmid's origin read as two
   truncated pieces, so a correct plasmid collected a false truncation FLAG. An iGEM
   construct is a plasmid; this was the normal case, not an edge case.
3. **An honest label was called a mislabel.** One sequence is registered under several
   Registry numbers, and a correct `B0034` was told it "is actually K1325011". The check
   that cries wolf is worse than no check, and it landed on the exact part family
   `CLAUDE.md` uses as its worked example.
4. **A nested claim was never audited.** A region labelled falsely inside a correctly
   identified part disappeared from the report entirely, and the verdict read PASS. Greedy
   decomposition must not decide which of the submitter's claims get verified.
5. **A diverged end read as a perfect match.** Terminal substitutions were clipped by the
   maximal-scoring segment, so a part mutated in its last eight bases reported 100%
   identity — making the mutations invisible.
6. **`deploy` could delete the repository and push to the iGEM GitLab.** `--out .`
   recursively deleted whatever it was given, and `--remote` was unrestricted while
   `publish()` force-pushes.

Each is fixed, each fix is pinned by a test that was watched to fail first, and each was
confirmed by mutation — reverting the fix turns the test red.

### 13.4 Deliberately not fixed

- **The dedup key** buckets coordinates by ten and ignores strand. The strand-agnostic
  half is deliberate: one reference seeds on both strands at the same place for a
  palindrome or a self-complementary terminator. Two occurrences within ten bases overlap
  almost entirely and are far more likely one site found on two diagonals.
- **`MAX_LOCI` is still 4.** Any cap drops the next one, so the cap is reported instead of
  raised.
- **The `forward/` and `reverse/` directory move** sketched in §6. The imports were
  unified without it; moving files would have made every commit in this branch harder to
  review for no behavioural gain.

### 13.5 Not verified

Stated rather than left to be assumed:

- **Windows.** Nobody on the team runs it and this session had no Windows machine. The
  launcher's double-click detection and interpreter probing are pinned by tests that
  assert the *shape* of `katana.bat`, which is weaker than a run.
- **Pixels in a browser.** The engine is verified in a real Pyodide and the rendering
  functions are called for real under node, but no browser was driven.
- **The subagent review pass.** Three subagents were dispatched across the session and
  none delivered a report. The gate ran as self-review plus Codex; the third pass is
  missing, and that is a gap against §10's three-pass requirement rather than a pass that
  found nothing.
