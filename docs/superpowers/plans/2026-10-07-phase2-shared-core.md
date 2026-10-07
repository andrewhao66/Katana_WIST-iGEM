# Phase 2: One Shared Core — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace eight independent `LOCK.tsv` parsers with one `core/` that every consumer imports, and fix `CODE-REPORT` findings 🔴A and 🔴B structurally in the process rather than by patch.

**Architecture:** A stdlib-only `core/` package holding the single definition of the hashing conventions and of LOCK reading, writing, resolution and verification. Consumers migrate one per commit so a regression bisects to a single parser. The two correctness fixes fall out of having one implementation: `verify_root()` recomputes each row hash from its fields instead of trusting the written column (🔴A), and `resolve()` selects by the Spec's pin rather than by `max(version)` (🔴B).

**Tech Stack:** Python 3.9+, standard library only plus the vendored YAML parser. `core/` must stay importable under Pyodide, so no `subprocess`, no `shutil.which`, no network, no platform assumptions.

**Spec:** `docs/superpowers/specs/2026-10-07-katana-unification-design.md` — this plan implements migration step 3 (§3.2) and the defects in §9.

## Global Constraints

- Python 3.9+ floor. No `match`, no runtime `X | Y` unions.
- **`core/` is stdlib-only.** It is the module set Pyodide loads in phase 4; an import of `subprocess` there would silently cost the web front end.
- The hashing conventions are frozen (spec §12): `seq_sha256 = sha256(seq.upper().encode("ascii"))`; `row_sha256` over the nine `FIELDS` in order, `"k=v"` joined by `\n`; `lock_root = sha256` of the row hashes joined by `\n`.
- `LOCK.tsv`, `LOCK.root`, sealed part filenames and the Design Spec schema stay byte-compatible. The shipped `parts-library/` is never modified.
- Verdict tokens `PASS` `FLAG` `FAIL` `REVIEW` `NOTE` `SKIP` `BLOCK` `SEALED` are API, not prose.
- The baseline to hold green at every step, with nothing installed and `blastn` hidden from `PATH`: `verify.py` 8/8, `test_determinism.py` ALL PASSED 10, `kagami/tests.py` 91/0, `kagami/test_identify.py` 58/0.
- Every task ends in a local commit on branch `unify`. **Nothing is pushed to `origin` (GitLab).**

## Review Focus

Five conditions the spec implies but no existing test exercises. Each gets its pinning test in the task that owns the code.

1. **A manifest row whose `source` was edited but whose `row_sha256` was not** — the engine must refuse the build. This is 🔴A, and it currently passes. → Task 1.
2. **A Spec pinned to an older sealed version of a part that still exists on disk** — the build must succeed and reproduce that older construct. This is 🔴B, and it is currently refused. → Task 2.
3. **A LOCK row with a non-numeric `version`** — `int(lver)` in `katana_build.resolve_parts` raises `ValueError` rather than producing a BLOCK message. → Task 3.
4. **A LOCK file with a missing or reordered column** — every parser indexes by header name, but they disagree about what is required. One definition must state it and refuse clearly. → Task 3.
5. **Two rows claiming the same `(id, version)`** — `katana_lock.resolve` already refuses this as AMBIGUOUS, but `katana_build.load_lock` silently keeps the last. → Task 3.

## File Structure

| File | Responsibility |
|---|---|
| `core/__init__.py` | **Create.** Package marker; re-exports nothing, so importers name what they use. |
| `core/hashing.py` | **Create.** `sha256_hex`, `seq_sha256`, `file_sha256`, `row_sha256`, `lock_root`, `FIELDS`. The single definition. |
| `core/lock.py` | **Create.** `LockRow`, `read`, `write`, `resolve`, `verify_root`, `verify_library`, `filename_sha12`. Replaces all eight parsers. |
| `core/parts.py` | **Create.** `extract_sequence` (GenBank ORIGIN or FASTA body), `render_genbank`. |
| `tests/test_core_lock.py` | **Create.** The RED tests for 🔴A, 🔴B and Review Focus 3–5. |
| `katana_lock.py` | **Modify.** Becomes a thin compatibility shim re-exporting from `core`, so `verify_library_v2.py` and `test_seal_gaps.py` keep working unchanged until their own tasks. |
| `katana_build.py` | **Modify.** `load_lock`, `verify_lock_root`, `resolve_parts` delegate to `core.lock`. |
| `add_part.py`, `katana_init.py`, `find_part.py` | **Modify.** Delete their private copies. |
| `verify_library_v2.py` | **Modify.** Delegate to `core.lock.verify_library`. |
| `kagami/kg_refs.py`, `kagami/kg_rebuild.py`, `kagami/kg_katana_tabs.py`, `kagami/build_refs.py` | **Modify.** Delete their private copies. |

---

## Task 1: 🔴A — the build gate must recompute row hashes (RED first)

**Files:**
- Create: `tests/test_core_lock.py`
- Create: `core/__init__.py`, `core/hashing.py`, `core/lock.py`

**Interfaces:**
- Produces:
  - `core.hashing.FIELDS -> list[str]` — the nine trust-bearing field names, in order.
  - `core.hashing.seq_sha256(seq: str) -> str`
  - `core.hashing.file_sha256(path) -> str`
  - `core.hashing.row_sha256(row: dict) -> str`
  - `core.hashing.lock_root(rows: list[dict]) -> str` — **recomputes** each row hash.
  - `core.lock.read(path) -> tuple[list[str], list[dict]]`
  - `core.lock.verify_root(lock_path, root_path, pinned=None) -> tuple[bool, str]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_core_lock.py`:

```python
"""Tests for the shared LOCK core. Run: python3 tests/test_core_lock.py

Plain asserts in the style of kagami/tests.py, so the suite needs nothing installed.
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from core import hashing, lock

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  [" + detail + "]") if detail else ""))


def sandbox():
    """A throwaway copy of the shipped parts library."""
    d = tempfile.mkdtemp(prefix="corelock_")
    shutil.copytree(os.path.join(ROOT, "parts-library", "ref_parts"),
                    os.path.join(d, "ref_parts"))
    return os.path.join(d, "ref_parts")


print("core.lock")

# ---- the conventions are frozen (spec section 12) ----
check("seq_sha256 uppercases before hashing",
      hashing.seq_sha256("acgt") == hashing.seq_sha256("ACGT"))
check("FIELDS is the nine trust-bearing fields in order",
      hashing.FIELDS == ["id", "version", "seq_sha256", "file_sha256", "length",
                         "source", "date", "class", "outfile"])

_shipped = os.path.join(ROOT, "parts-library", "ref_parts")
_hdr, _rows = lock.read(os.path.join(_shipped, "LOCK.tsv"))
check("the shipped manifest reads as 30 rows", len(_rows) == 30, str(len(_rows)))
check("lock_root over the shipped rows equals LOCK.root",
      hashing.lock_root(_rows) ==
      open(os.path.join(_shipped, "LOCK.root"), encoding="utf-8").read().strip())

# ---- CODE-REPORT finding A ----
# katana_build.verify_lock_root() hashed the row_sha256 COLUMN as written instead of
# recomputing each row hash from its fields. Editing a recorded accession without
# touching row_sha256 therefore passed the build gate: verified by building a construct
# against a library whose lacZ source said NC_000913.3:999999-999999 and getting exit 0.
# The sequence was still protected by stage 2, but the recorded ORIGIN was not -- and a
# claim drifting from its bases is the failure this project exists to prevent.
_d = sandbox()
_lock_path = os.path.join(_d, "LOCK.tsv")
_text = open(_lock_path, encoding="utf-8").read()
_edited = _text.replace("NC_000913.3:363231-366305", "NC_000913.3:999999-999999")
check("the sandbox manifest contains the row to edit", _edited != _text)
with open(_lock_path, "w", encoding="utf-8", newline="\n") as _f:
    _f.write(_edited)

_ok, _msg = lock.verify_root(_lock_path, os.path.join(_d, "LOCK.root"))
check("an edited source field with an untouched row_sha256 is REFUSED", not _ok, _msg)
check("and the refusal names the row that disagrees", "lacZ" in _msg, _msg)

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
```

- [ ] **Step 2: Run it and verify it fails for the right reason**

```bash
cd /Users/andrewhao/Desktop/katana && python3 tests/test_core_lock.py
```

Expected: `ModuleNotFoundError: No module named 'core'`.

- [ ] **Step 3: Create `core/hashing.py`**

```python
"""core.hashing — the single definition of this project's hashing conventions.

Reverse-engineered and confirmed against the live library on 2026-07-05, and frozen
since: every sealed part and every manifest row in existence was produced with these
exact rules, so changing one invalidates the library rather than improving it.

  seq_sha256   sha256 of the sequence, uppercased, letters only
  file_sha256  sha256 of the raw file bytes
  row_sha256   sha256 over the nine trust-bearing fields, "k=v" joined by newlines
  lock_root    sha256 over the row hashes, joined by newlines

These were previously defined in five places -- katana_lock.py, add_part.py,
katana_init.py, kagami/build_refs.py and test_determinism.py -- each with a comment
saying the duplication was deliberate and load-bearing, because a drift would make
every part that tool admitted unbuildable. The comments were right about the danger and
wrong about the remedy: one definition cannot drift from itself.

Standard library only. This module is loaded by Pyodide in the browser front end.
"""
import hashlib

# The order is part of the convention: row_sha256 is computed over these keys in this
# sequence. It must not contain row_sha256 itself, while the manifest HEADER does --
# a distinction that cost a build once.
FIELDS = ["id", "version", "seq_sha256", "file_sha256", "length",
          "source", "date", "class", "outfile"]

HEADER = FIELDS + ["row_sha256"]


def sha256_hex(data):
    """sha256 of bytes, as lowercase hex."""
    return hashlib.sha256(data).hexdigest()


def seq_sha256(seq):
    """The canonical sequence hash: uppercase, ASCII, nothing else.

    KATANA_SPEC v2 section 3.4 specifies UPPER+"|"+topology, but the existing LOCK and
    every sealed part and construct use plain UPPER. The engine follows the established
    convention, because the alternative is re-sealing the library.
    """
    return sha256_hex(seq.upper().encode("ascii"))


def file_sha256(path):
    """sha256 of a file's raw bytes. Never decoded -- line endings are part of the seal."""
    with open(path, "rb") as f:
        return sha256_hex(f.read())


def row_manifest(row):
    """The canonical string a row's hash is taken over."""
    return "\n".join("%s=%s" % (k, row.get(k, "")) for k in FIELDS)


def row_sha256(row):
    """Hash of a manifest row's trust-bearing fields.

    This is what seals the ROW rather than the sequence: editing a recorded accession,
    bumping a version, or repointing an outfile changes this value.
    """
    return sha256_hex(row_manifest(row).encode())


def lock_root(rows):
    """Merkle-style root over the rows.

    RECOMPUTES each row hash from its fields rather than reading the row_sha256 column.
    That difference is CODE-REPORT finding A: hashing the column as written let an
    edited `source` field pass the build engine's gate, because the column still agreed
    with itself. A root over values you did not verify is a root over nothing.
    """
    return sha256_hex("\n".join(row_sha256(r) for r in rows).encode())
```

- [ ] **Step 4: Create `core/__init__.py`**

```python
"""core — the shared, dependency-free heart of Katana.

Everything in this package is standard library only (plus the vendored YAML parser),
because it is the module set the browser front end loads through Pyodide. An import of
subprocess or shutil.which here would silently cost the web version, so there is a test
that asserts it does not happen.

  core.hashing   the hashing conventions, defined once
  core.lock      LOCK.tsv: read, write, resolve, verify
  core.parts     sealed part files: read a sequence, render a record
"""
```

- [ ] **Step 5: Create `core/lock.py` with `read` and `verify_root`**

```python
"""core.lock — the one implementation of the Parts Library manifest.

There were eight, in katana_lock.py, katana_build.py, add_part.py, find_part.py,
katana_init.py, kagami/kg_refs.py, kagami/kg_rebuild.py, kagami/kg_katana_tabs.py and
kagami/build_refs.py. katana_lock.py was meant to be the shared one and was imported by
exactly two files, both on the verifier path; everything else wrote its own. Nothing
forced convergence, and two of the copies disagreed about the two things that matter:
whether a row's hash is recomputed before the root is checked, and whether a Spec's pin
or the highest version number decides which part is loaded.

Standard library only. Loaded by Pyodide in the browser front end.
"""
import os

from . import hashing


class LockError(Exception):
    """The manifest cannot be trusted. Never swallowed -- it ends the caller's turn."""


def read(path):
    """Read a manifest. Returns (header, rows). Raises LockError if it is unusable.

    Blank lines are skipped. Every row is a dict keyed by the header's own names, so a
    reordered column is harmless; a MISSING one is not, and is refused here rather than
    surfacing as a KeyError three stages later.
    """
    with open(path, "r", encoding="utf-8") as f:
        lines = [ln.rstrip("\n") for ln in f if ln.strip() != ""]
    if not lines:
        raise LockError("%s is empty" % path)
    header = lines[0].split("\t")
    missing = [k for k in hashing.FIELDS if k not in header]
    if missing:
        raise LockError("%s is missing the column(s) %s, so its rows cannot be hashed"
                        % (path, ", ".join(missing)))
    rows = []
    for n, ln in enumerate(lines[1:], start=2):
        cells = ln.split("\t")
        if len(cells) < len(header):
            cells = cells + [""] * (len(header) - len(cells))
        rows.append(dict(zip(header, cells)))
    return header, rows


def verify_root(lock_path, root_path, pinned=None):
    """Verify the manifest is self-consistent, and optionally that it is THE library.

    Two independent checks, and the first is the one CODE-REPORT finding A was about:

    1. SELF-CONSISTENCY, always on. Every row's hash is RECOMPUTED from its fields and
       compared to the row_sha256 column, and the root is recomputed from those
       recomputed hashes. The engine used to hash the column as written, so editing a
       recorded accession without touching its row hash passed the gate -- the column
       still agreed with itself, and a root over unverified values is a root over
       nothing.
    2. EXTERNAL PIN, only when `pinned` is given. A library can be perfectly
       self-consistent and still be the wrong library: a stale sync, an old checkout, a
       second machine. Only a hash carried in from outside catches that.

    Returns (ok, message). The message names what disagrees, because "the manifest
    changed" is not a diagnosis.
    """
    if not os.path.exists(root_path):
        return False, "LOCK.root file missing"
    disk_root = open(root_path, "r", encoding="utf-8").read().strip()

    try:
        _header, rows = read(lock_path)
    except LockError as exc:
        return False, str(exc)

    # 1. Each row, from its fields.
    for row in rows:
        recomputed = hashing.row_sha256(row)
        written = row.get("row_sha256", "")
        if recomputed != written:
            return False, (
                "%s v%s: row_sha256 does not match the row's own fields "
                "(recomputed %s..., column says %s...). A trust field -- source, "
                "version, class or outfile -- was edited."
                % (row.get("id", "?"), row.get("version", "?"),
                   recomputed[:12], (written or "empty")[:12]))

    # 2. The root, from the recomputed hashes.
    computed = hashing.lock_root(rows)
    if computed != disk_root:
        return False, ("LOCK is not self-consistent: recomputed root %s... != LOCK.root "
                       "file %s... (rows added or removed?)"
                       % (computed[:16], disk_root[:16]))

    if pinned:
        pinned = pinned.strip()
        if disk_root != pinned:
            return False, ("LOCK.root mismatch: library=%s... pinned=%s... "
                           "(wrong or stale library)" % (disk_root[:16], pinned[:16]))
        return True, "self-consistent + matches pin %s..." % pinned[:16]

    return True, ("self-consistent (%s...); NO EXTERNAL PIN -- pass --expect-root to bind"
                  % disk_root[:16])
```

- [ ] **Step 6: Run the test — it must now pass**

```bash
cd /Users/andrewhao/Desktop/katana && python3 tests/test_core_lock.py
```

Expected: `0 failed`. In particular `an edited source field with an untouched row_sha256 is REFUSED` must pass, and its message must name `lacZ`.

- [ ] **Step 7: Prove `core/` stays importable without the standard library's process tools**

Append to `tests/test_core_lock.py`, before the final `print`:

```python
# core/ is what Pyodide loads in the browser front end, so an import of subprocess or
# shutil.which here would silently cost the web version. Assert it rather than trusting
# a convention nobody can see.
_banned = ("subprocess", "shutil", "socket", "urllib", "multiprocessing", "ctypes")
_core_dir = os.path.join(ROOT, "core")
_bad = []
for _fn in sorted(os.listdir(_core_dir)):
    if not _fn.endswith(".py"):
        continue
    _src = open(os.path.join(_core_dir, _fn), encoding="utf-8").read()
    for _mod in _banned:
        if ("import " + _mod) in _src:
            _bad.append("%s imports %s" % (_fn, _mod))
check("core/ imports nothing Pyodide cannot run (%s)" % (", ".join(_bad) or "clean"),
      not _bad)
```

- [ ] **Step 8: Run it**

```bash
cd /Users/andrewhao/Desktop/katana && python3 tests/test_core_lock.py | tail -3
```

Expected: `0 failed`.

- [ ] **Step 9: Commit**

```bash
git add core tests/test_core_lock.py
git commit -m "feat: core.hashing and core.lock, with the row hash actually recomputed

The hashing conventions had five definitions -- katana_lock, add_part, katana_init,
kagami/build_refs and test_determinism -- each carrying a comment saying the duplication
was deliberate and load-bearing because a drift would make every part that tool admitted
unbuildable. The comments were right about the danger and wrong about the remedy: one
definition cannot drift from itself.

core.lock.verify_root() RECOMPUTES every row hash from the row's own fields before
checking the root. katana_build hashed the row_sha256 COLUMN as written, so editing a
recorded accession without touching its row hash passed the build gate -- the column
still agreed with itself, and a root over unverified values is a root over nothing.
CODE-REPORT finding A, pinned by a test that edits lacZ's recorded coordinates in a
sandbox copy and requires the refusal to name lacZ.

core.lock.read() also refuses a manifest missing a hashable column, rather than letting
it surface as a KeyError three stages later, and tolerates a reordered one.

A test asserts core/ imports nothing Pyodide cannot run, because core/ is the module set
the browser front end will load and a stray subprocess import would cost it silently."
```

---

## Task 2: 🔴B — resolve by the Spec's pin, not by `max(version)`

**Files:**
- Modify: `core/lock.py`
- Modify: `tests/test_core_lock.py`

**Interfaces:**
- Produces: `core.lock.resolve(rows, part_id, pin=None, version=None, lib=None) -> dict`
  Raises `LockError` when the request is ambiguous or unsatisfiable.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_core_lock.py`, before the `core/ imports nothing` block:

```python
# ---- CODE-REPORT finding B ----
# katana_build.resolve_parts() scanned LOCK for the HIGHEST version of an id and then
# compared the Spec's pin against only that row. So a Spec pinned to an older sealed
# version -- whose file is still on disk, whose row is still in the manifest -- was
# refused, with a message telling the reader to update the Spec to match the library.
# That contradicts ARCHITECTURE.md's promise that "history is append-only, so a build
# from last month can still be reproduced", and following the advice would change the
# construct. HrpS.Ec-opt has v1, v2 and v3 sealed; pAP-Logic v5 pinned v2.
_versions = sorted(r["version"] for r in _rows if r["id"] == "HrpS.Ec-opt")
check("HrpS.Ec-opt really has three sealed versions to choose between",
      _versions == ["1", "2", "3"], ",".join(_versions))

_v2 = [r for r in _rows if r["id"] == "HrpS.Ec-opt" and r["version"] == "2"][0]
_v3 = [r for r in _rows if r["id"] == "HrpS.Ec-opt" and r["version"] == "3"][0]

_got = lock.resolve(_rows, "HrpS.Ec-opt", pin=_v2["seq_sha256"][:12])
check("a pin selects the version it names, not the newest",
      _got["version"] == "2", "got v" + _got["version"])
check("the newest is still selected when its own pin is given",
      lock.resolve(_rows, "HrpS.Ec-opt",
                   pin=_v3["seq_sha256"][:12])["version"] == "3")
check("an explicit version selects that version",
      lock.resolve(_rows, "HrpS.Ec-opt", version=2)["version"] == "2")
check("the seal's lib filename also selects a version",
      lock.resolve(_rows, "HrpS.Ec-opt", lib=_v2["outfile"])["version"] == "2")


def _raises(fn):
    try:
        fn()
        return False
    except lock.LockError:
        return True


check("a pin that matches nothing raises rather than falling back",
      _raises(lambda: lock.resolve(_rows, "HrpS.Ec-opt", pin="ffffffffffff")))
check("an unknown id raises",
      _raises(lambda: lock.resolve(_rows, "NoSuchPart", pin="000000000000")))
check("a bare id with no pin and no version raises, because it is ambiguous",
      _raises(lambda: lock.resolve(_rows, "HrpS.Ec-opt")))
check("a bare id with only ONE sealed version resolves without a pin",
      lock.resolve(_rows, "lacZ")["version"] == "1")

# Review Focus 5: two rows claiming the same (id, version) must be refused, not
# silently resolved to the last one.
_dupe = list(_rows) + [dict(_v2)]
check("duplicate (id, version) rows are refused as ambiguous",
      _raises(lambda: lock.resolve(_dupe, "HrpS.Ec-opt", version=2)))

# Review Focus 3: a non-numeric version must not raise ValueError out of int().
_junk = [dict(_v2, version="two")]
check("a non-numeric version raises LockError, not ValueError",
      _raises(lambda: lock.resolve(_junk, "HrpS.Ec-opt")))

# The filename's embedded hash must agree with the row's. This is failure 5 from the
# README: a part file named ...__47c4687cca62.gb whose sequence hashed to 3c840d2b...
_liar = [dict(_v2, outfile="HrpS.Ec-opt__v2__ffffffffffff.gb")]
check("a row whose filename hash disagrees with its seq_sha256 is refused",
      _raises(lambda: lock.resolve(_liar, "HrpS.Ec-opt", version=2)))
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd /Users/andrewhao/Desktop/katana && python3 tests/test_core_lock.py 2>&1 | tail -16
```

Expected: `AttributeError: module 'core.lock' has no attribute 'resolve'`.

- [ ] **Step 3: Implement `resolve` and `filename_sha12`**

Append to `core/lock.py`:

```python
def filename_sha12(outfile):
    """The 12-hex fingerprint embedded in a sealed part's filename.

    Sealed parts are named <id>__v<N>__<first 12 of seq_sha256>.<ext>. Returns "" when
    the name does not carry one, so a caller can tell "absent" from "wrong".
    """
    base = os.path.basename(str(outfile)).rsplit(".", 1)[0]
    tail = base.split("__")[-1]
    if len(tail) == 12 and all(c in "0123456789abcdefABCDEF" for c in tail):
        return tail.lower()
    return ""


def resolve(rows, part_id, pin=None, version=None, lib=None):
    """Select exactly one manifest row for `part_id`. Raises LockError otherwise.

    Selection is by what the CALLER asked for -- the Spec's `pin`, an explicit
    `version`, or the seal's `lib` filename -- and NOT by the highest version number.
    That difference is CODE-REPORT finding B. resolve_parts() used to take max(version)
    and compare the pin against only that row, so a Spec pinned to an older sealed
    version was refused even though its row and its file were both still present, with
    a message advising the reader to update the Spec to match the library. Following
    that advice changes the construct, and it contradicts the append-only history the
    architecture promises: HrpS.Ec-opt has v1, v2 and v3 sealed, and pAP-Logic v5 pinned
    v2.

    A bare id with no pin resolves only when the library holds exactly one version of
    it. Guessing is what this function exists not to do.
    """
    candidates = [r for r in rows if r.get("id") == part_id]
    if not candidates:
        raise LockError("no sealed row for '%s'" % part_id)

    if lib is not None:
        want = os.path.basename(str(lib))
        candidates = [r for r in candidates
                      if os.path.basename(r.get("outfile", "")) == want]
        if not candidates:
            raise LockError("'%s': no sealed row whose file is %s" % (part_id, want))

    if version is not None:
        want = str(version)
        candidates = [r for r in candidates if str(r.get("version", "")) == want]
        if not candidates:
            raise LockError("no sealed row for %s v%s" % (part_id, want))

    if pin:
        pin = pin.lower()
        candidates = [r for r in candidates
                      if r.get("seq_sha256", "").lower().startswith(pin)]
        if not candidates:
            held = ", ".join("v%s=%s" % (r.get("version", "?"),
                                         r.get("seq_sha256", "")[:12])
                             for r in rows if r.get("id") == part_id)
            raise LockError(
                "'%s': no sealed version matches the pin %s. The library holds %s. "
                "One of the two has moved on; this is the check working, not a bug."
                % (part_id, pin, held or "nothing"))

    if len(candidates) > 1:
        seen = sorted(str(r.get("version", "?")) for r in candidates)
        raise LockError(
            "'%s' is ambiguous: %d rows match (versions %s). Pin it in the Spec's seal "
            "block, or give a version." % (part_id, len(candidates), ", ".join(seen)))

    row = candidates[0]

    # Numeric versions are a convention the rest of the code relies on; an int() three
    # stages away would raise ValueError instead of saying what is wrong.
    if not str(row.get("version", "")).isdigit():
        raise LockError("'%s': version %r is not a number" % (part_id, row.get("version")))

    # The filename carries the sequence hash. A disagreement here IS failure 5 from the
    # README: a part file named ...__47c4687cca62.gb whose sequence hashed to 3c840d2b,
    # same length and different bases, with a prepared manifest row claiming the name.
    fn12 = filename_sha12(row.get("outfile", ""))
    if fn12 and fn12 != row.get("seq_sha256", "")[:12].lower():
        raise LockError(
            "%s v%s: the filename says %s but the row's seq_sha256 is %s. Two sources "
            "disagree about which sequence this is -- report it, do not pick one."
            % (part_id, row.get("version"), fn12, row.get("seq_sha256", "")[:12]))

    return row
```

- [ ] **Step 4: Run the test**

```bash
cd /Users/andrewhao/Desktop/katana && python3 tests/test_core_lock.py 2>&1 | tail -18
```

Expected: `0 failed`.

- [ ] **Step 5: Commit**

```bash
git add core/lock.py tests/test_core_lock.py
git commit -m "feat: core.lock.resolve selects by pin, not by max(version)

resolve_parts() scanned the manifest for the HIGHEST version of an id and compared the
Spec's pin against only that row. A Spec pinned to an older sealed version -- whose row
is still in the manifest and whose file is still on disk -- was therefore refused, with
a message advising the reader to update the Spec to match the library. Following that
advice changes the construct, and it contradicts ARCHITECTURE.md's promise that history
is append-only so a build from last month can still be reproduced. HrpS.Ec-opt has v1,
v2 and v3 sealed; pAP-Logic v5 pinned v2. CODE-REPORT finding B.

resolve() now selects by what the caller asked for: the Spec's pin, an explicit version,
or the seal's lib filename. A bare id resolves only when the library holds exactly one
version, because guessing is what this function exists not to do.

It also refuses what the old parsers waved through: duplicate (id, version) rows
(katana_build.load_lock keyed a dict and silently kept the last), a non-numeric version
(int() raised ValueError three stages later), and a row whose filename fingerprint
disagrees with its seq_sha256 -- which is failure 5 from the README, the part file named
...__47c4687cca62.gb whose sequence hashed to 3c840d2b."
```

---

## Task 3: `core.parts`, and `katana_lock` becomes a shim

**Files:**
- Create: `core/parts.py`
- Modify: `katana_lock.py`

**Interfaces:**
- Produces:
  - `core.parts.extract_sequence(text, suffix="") -> str`
  - `core.parts.read_sequence(path) -> str`
  - `core.parts.render_genbank(part_id, version, seq, source, klass) -> str`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_core_lock.py`, before the `core/ imports nothing` block:

```python
# ---- core.parts: one sequence reader ----
from core import parts as core_parts

_gb_path = os.path.join(_shipped, "B0015__v1__696c73e5a7a8.gb")
_seq = core_parts.read_sequence(_gb_path)
check("a sealed GenBank part reads back as its sealed length", len(_seq) == 129,
      str(len(_seq)))
check("and hashes to the fingerprint in its own filename",
      hashing.seq_sha256(_seq)[:12] == "696c73e5a7a8",
      hashing.seq_sha256(_seq)[:12])
check("the extracted sequence is uppercase", _seq == _seq.upper())
check("a FASTA body reads too",
      core_parts.extract_sequence(">x\nacgt\nACGT\n", ".fasta") == "ACGTACGT")
check("an unknown extension still finds an ORIGIN block",
      core_parts.extract_sequence("ORIGIN\n  1 acgt\n//\n") == "ACGT")
check("a rendered record round-trips to the sequence it was given",
      core_parts.extract_sequence(
          core_parts.render_genbank("t", 1, "ACGTACGTACGT", "test", "designed")
      ) == "ACGTACGTACGT")
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd /Users/andrewhao/Desktop/katana && python3 tests/test_core_lock.py 2>&1 | tail -8
```

Expected: `ImportError: cannot import name 'parts' from 'core'`.

- [ ] **Step 3: Create `core/parts.py`**

```python
"""core.parts — reading and writing sealed part files.

One reader, because there were four: katana_build.extract_gb_sequence,
katana_lock.parse_sequence, add_part.extract_gb_sequence (whose docstring said "byte-for-
byte the same logic as katana_build" -- a promise maintained by hand) and
add_part.read_fasta. They agreed, which is the point: four implementations of one
convention agree only until one of them is edited.

Standard library only. Loaded by Pyodide in the browser front end.
"""
import os
import re
from datetime import date

from . import hashing

_GENBANK = (".gb", ".gbk", ".genbank")
_FASTA = (".faa", ".fa", ".fasta", ".fna", ".txt", ".seq")


def extract_sequence(text, suffix=""):
    """The sequence a part file holds, uppercase, letters only.

    Dispatches on `suffix` when given, and otherwise on content: a GenBank ORIGIN block
    if there is one, else a FASTA body. Content-based fallback matters because a part
    file's extension is a naming convention, not a guarantee.
    """
    low = suffix.lower()
    if low in _GENBANK or (not low and "ORIGIN" in text):
        out, in_origin = [], False
        for line in text.splitlines():
            if line.startswith("ORIGIN"):
                in_origin = True
                continue
            if in_origin:
                if line.startswith("//"):
                    break
                out.append(re.sub(r"[^A-Za-z]", "", line))
        return "".join(out).upper()
    return "".join(re.sub(r"[^A-Za-z]", "", ln)
                   for ln in text.splitlines() if not ln.startswith(">")).upper()


def read_sequence(path):
    """The sequence a sealed part file on disk holds."""
    with open(path, "r", encoding="utf-8") as f:
        return extract_sequence(f.read(), os.path.splitext(path)[1])


def render_genbank(part_id, version, seq, source, klass):
    """A minimal, valid GenBank record for a part entering a library.

    GenBank rather than FASTA on purpose: the build engine reads part files through an
    ORIGIN-block reader, so a .fasta part would read as empty and be blocked.
    """
    today = date.today().strftime("%d-%b-%Y").upper()
    lines = [
        "LOCUS       %-24s%d bp    DNA     linear   SYN %s" % (part_id, len(seq), today),
        "DEFINITION  %s v%s, admitted to a Katana Parts Library." % (part_id, version),
        "ACCESSION   %s" % part_id,
        "VERSION     %s.%s" % (part_id, version),
        "KEYWORDS    .",
        "SOURCE      %s" % source,
        "COMMENT     Admitted by add_part.py. The manifest row in LOCK.tsv, not this file,",
        "            is the record of provenance; this file is the sequence it points at.",
        "            class: %s" % klass,
        "FEATURES             Location/Qualifiers",
        "     source          1..%d" % len(seq),
        '                     /note="%s"' % source,
        '                     /label="%s"' % part_id,
        "ORIGIN",
    ]
    low = seq.lower()
    for i in range(0, len(low), 60):
        chunk = low[i:i + 60]
        blocks = " ".join(chunk[j:j + 10] for j in range(0, len(chunk), 10))
        lines.append("%9d %s" % (i + 1, blocks))
    lines.append("//")
    return "\n".join(lines) + "\n"


def verify_library(lock_path):
    """Audit a whole library: every row's file, bytes, sequence, filename and row hash,
    plus orphan files and the root. Returns a list of problems; empty means sealed.

    Fail-closed: a file it cannot read is a problem, never a skip.
    """
    from . import lock as _lock

    d = os.path.dirname(os.path.abspath(lock_path))
    problems = []
    try:
        _header, rows = _lock.read(lock_path)
    except _lock.LockError as exc:
        return [str(exc)]

    seen = set()
    for row in rows:
        rid = "%s v%s" % (row.get("id", "?"), row.get("version", "?"))
        outfile = row.get("outfile", "")
        path = os.path.join(d, outfile.replace("\\", os.sep))
        if not os.path.exists(path):
            problems.append("%s: file MISSING (%s)" % (rid, outfile))
            continue
        seen.add(os.path.normpath(path))

        if hashing.file_sha256(path) != row.get("file_sha256"):
            problems.append("%s: file_sha256 MISMATCH (bytes changed)" % rid)
        try:
            if hashing.seq_sha256(read_sequence(path)) != row.get("seq_sha256"):
                problems.append("%s: seq_sha256 MISMATCH (sequence changed)" % rid)
        except Exception as exc:
            problems.append("%s: seq parse error: %s" % (rid, exc))

        fn12 = _lock.filename_sha12(outfile)
        if fn12 and fn12 != row.get("seq_sha256", "")[:12].lower():
            problems.append("%s: filename sha12 != seq_sha256" % rid)

        if hashing.row_sha256(row) != row.get("row_sha256"):
            problems.append("%s: row_sha256 MISMATCH (a trust field -- source, version, "
                            "class or outfile -- was edited)" % rid)

    # Orphans: a part file with no row is trust by dropping a file into the store.
    exts = (".gb", ".gbk", ".faa", ".fa", ".fasta")
    pending = 0
    for root, dirs, files in os.walk(d):
        # Staging directories (names starting with "_", e.g. _incoming) hold raw
        # pre-seal fetches, which legitimately have no row and are NOT orphans.
        pruned = [x for x in dirs if x.startswith("_")]
        dirs[:] = [x for x in dirs if not x.startswith("_")]
        for pd in pruned:
            for _r, _ds, fs in os.walk(os.path.join(root, pd)):
                pending += sum(1 for f in fs if f.lower().endswith(exts))
        for fn in files:
            if fn.lower().endswith(exts):
                fp = os.path.normpath(os.path.join(root, fn))
                if fp not in seen:
                    problems.append("ORPHAN part file with no LOCK row: %s"
                                    % os.path.relpath(fp, d))

    ok, msg = _lock.verify_root(lock_path, os.path.join(d, "LOCK.root"))
    if not ok:
        problems.append(msg)

    return problems
```

- [ ] **Step 4: Run the test**

```bash
cd /Users/andrewhao/Desktop/katana && python3 tests/test_core_lock.py 2>&1 | tail -10
```

Expected: `0 failed`.

- [ ] **Step 5: Turn `katana_lock.py` into a shim**

Replace the whole of `katana_lock.py` with:

```python
#!/usr/bin/env python3
"""katana_lock.py — compatibility shim over core.lock and core.hashing.

This module WAS the Parts Library integrity core. It is now a thin forwarding layer, so
that `verify_library_v2.py`, `test_seal_gaps.py` and anything outside this repository
that imported it keep working while the implementation lives in one place.

The move is the point. This file was meant to be the shared core and was imported by
exactly two files, both on the verifier path; the build engine, the intake gate, the
finder and four Kagami modules each wrote their own manifest parser. Two of those copies
disagreed about the two things that matter -- whether a row's hash is recomputed before
the root is checked (CODE-REPORT finding A) and whether a Spec's pin or the highest
version number decides which part is loaded (finding B). Nothing forced convergence
until core/ existed.

New code imports core.lock and core.hashing directly.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.hashing import (FIELDS, file_sha256, lock_root as _core_lock_root,
                          row_manifest, row_sha256, seq_sha256, sha256_hex)
from core.lock import LockError, filename_sha12, read as _core_read, resolve as _resolve
from core.parts import read_sequence, verify_library


class ResolveError(LockError):
    """Kept so `except katana_lock.ResolveError` in older callers still catches."""


def sha256_bytes(b):
    return sha256_hex(b)


def parse_sequence(path):
    return read_sequence(path)


def file_hash(path):
    return file_sha256(path)


def seq_hash(path):
    return seq_sha256(read_sequence(path))


def read_lock(path):
    return _core_read(path)


def lock_root(rows):
    return _core_lock_root(rows)


def resolve(rows, id, version=None, expected_seq_sha12=None):
    """Historic signature: positional `version`, `expected_seq_sha12` as the pin.

    The old implementation REQUIRED a version and refused id-only resolution, which was
    correct and is preserved: core.lock.resolve accepts a bare id only when the library
    holds exactly one version, and this wrapper keeps the stricter rule its callers were
    written against.
    """
    if version is None:
        raise ResolveError("id-only resolution is banned (Gap 2): pass a version for '%s'"
                           % id)
    try:
        return _resolve(rows, id, pin=expected_seq_sha12, version=version)
    except LockError as exc:
        raise ResolveError(str(exc))
```

- [ ] **Step 6: The two existing consumers must still pass unchanged**

```bash
cd /Users/andrewhao/Desktop/katana
python3 verify_library_v2.py parts-library/ref_parts/LOCK.tsv
python3 test_seal_gaps.py parts-library/ref_parts
python3 verify.py | tail -4
```

Expected: `SEALED — 30 parts verified…`, `8/8 checks passed`, and `OK — the library is intact`.

- [ ] **Step 7: Run everything**

```bash
cd /Users/andrewhao/Desktop/katana
SAFE=/usr/bin:/bin:/usr/sbin:/sbin
python3 tests/test_core_lock.py | tail -2
python3 verify.py | grep -oE '[0-9]+/[0-9]+ checks passed'
python3 test_determinism.py | tail -1
(cd kagami && PATH="$SAFE" /usr/bin/python3 tests.py | tail -1)
(cd kagami && PATH="$SAFE" /usr/bin/python3 test_identify.py | tail -1)
```

Expected: `0 failed`, `8/8`, `ALL PASSED — 10 checks`, `91 passed, 0 failed`, `58 passed, 0 failed`.

- [ ] **Step 8: Commit**

```bash
git add core/parts.py katana_lock.py tests/test_core_lock.py
git commit -m "feat: core.parts; katana_lock becomes a shim over core

One sequence reader, because there were four: katana_build.extract_gb_sequence,
katana_lock.parse_sequence, add_part.extract_gb_sequence (whose docstring promised it
was 'byte-for-byte the same logic as katana_build' -- a promise maintained by hand) and
add_part.read_fasta. They agreed, which is the point: four implementations of one
convention agree only until one of them is edited.

core.parts.verify_library() is the whole-library audit, moved out of
verify_library_v2.py so the GUI, the web front end and the CLI can all call it rather
than shelling out to a script and grepping its prose.

katana_lock.py keeps its public names as a forwarding layer, so verify_library_v2.py,
test_seal_gaps.py and anything outside this repository that imported it keep working.
Its historic resolve() signature is preserved including the rule that refused id-only
resolution -- that rule was right, and core.lock.resolve is stricter still.

Verified: verify_library_v2 reports SEALED 30 parts, test_seal_gaps 8/8, and the full
suite is green with nothing installed."
```

---

## Task 4: migrate `katana_build.py` — and fix 🔴A and 🔴B in the engine

**Files:**
- Modify: `katana_build.py`
- Modify: `tests/test_core_lock.py`

- [ ] **Step 1: Write the failing end-to-end tests**

Create `tests/test_engine_gates.py`:

```python
"""test_engine_gates.py — the build engine's two integrity gates, end to end.

Run: python3 tests/test_engine_gates.py

These drive katana_build.py as a subprocess against sandbox copies of the library,
because the gates are what the engine does when a real user builds a real Spec, and a
unit test of core.lock would not have caught either of the defects below: both lived in
the engine's own copy of the logic.
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  [" + detail[:300] + "]") if detail else ""))


def sandbox():
    """A copy of the repository's engine, library and specs, in a temp directory."""
    d = tempfile.mkdtemp(prefix="gates_")
    shutil.copytree(os.path.join(ROOT, "parts-library"),
                    os.path.join(d, "parts-library"),
                    ignore=shutil.ignore_patterns("ref_genomes"))
    shutil.copytree(os.path.join(ROOT, "specs"), os.path.join(d, "specs"))
    shutil.copytree(os.path.join(ROOT, "core"), os.path.join(d, "core"),
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(os.path.join(ROOT, "_vendor"), os.path.join(d, "_vendor"),
                    ignore=shutil.ignore_patterns("__pycache__"))
    for f in ("katana_build.py", "katana_drylab.py", "blast_offtarget.py",
              "katana_order_table.py", "katana_sbol.py", "katana_lock.py",
              "vendor_path.py"):
        shutil.copyfile(os.path.join(ROOT, f), os.path.join(d, f))
    return d


def build(d, spec_name, *extra):
    return subprocess.run(
        [sys.executable, os.path.join(d, "katana_build.py"),
         os.path.join(d, "specs", spec_name), "--dry-run"] + list(extra),
        capture_output=True, text=True, encoding="utf-8", errors="replace")


print("engine integrity gates")

# ---- a sandbox builds cleanly, or nothing below measures anything ----
_d = sandbox()
_p = build(_d, "pSense-Nit.spec.yaml")
check("the sandboxed engine builds a Spec at all", _p.returncode == 0,
      _p.stdout + _p.stderr)

# ---- CODE-REPORT finding A, through the engine ----
# Edit a RECORDED ACCESSION and leave row_sha256 alone. The engine used to hash the
# row_sha256 column as written, so this passed: a falsified provenance claim built to
# completion with exit 0 while verify_library_v2.py reported two problems. The sequence
# was still protected by stage 2; the recorded ORIGIN of that sequence was not.
_d = sandbox()
_lock = os.path.join(_d, "parts-library", "ref_parts", "LOCK.tsv")
_t = open(_lock, encoding="utf-8").read()
_t2 = _t.replace("NC_000913.3:363231-366305", "NC_000913.3:999999-999999")
check("the sandbox manifest contains the accession to falsify", _t2 != _t)
open(_lock, "w", encoding="utf-8", newline="\n").write(_t2)

_p = build(_d, "pSense-Lac-lacZ.spec.yaml")
_out = _p.stdout + _p.stderr
check("a falsified accession BLOCKS the build", _p.returncode != 0,
      "exit %d" % _p.returncode)
check("and the refusal names the row that disagrees", "lacZ" in _out, _out[-400:])
check("and says a trust field was edited", "row_sha256" in _out, _out[-400:])

# ---- CODE-REPORT finding B, through the engine ----
# Re-pin a Spec to an OLDER sealed version whose row and file are both still present.
# The engine used to take max(version) and refuse, telling the reader to update the Spec
# to match the library -- which would change the construct, and contradicts the
# append-only history the architecture promises.
_d = sandbox()
_spec = os.path.join(_d, "specs", "pAP-Logic.spec.yaml")
_s = open(_spec, encoding="utf-8").read()
_s2 = (_s.replace("designed/acoustic/HrpS.Ec-opt__v3__5093ea792057.gb",
                  "designed/acoustic/HrpS.Ec-opt__v2__cc3f6c1ec6ef.gb")
         .replace("seq_sha256_12: 5093ea792057", "seq_sha256_12: cc3f6c1ec6ef"))
check("the Spec contains the v3 pin to downgrade", _s2 != _s)
open(_spec, "w", encoding="utf-8").write(_s2)

_p = build(_d, "pAP-Logic.spec.yaml")
_out = _p.stdout + _p.stderr
check("a Spec pinned to an older sealed version BUILDS", _p.returncode == 0,
      _out[-500:])
check("and it loads v2, not v3",
      "cc3f6c1ec6ef" in _out and "5093ea792057" not in _out, _out[-500:])
check("and the construct hash DIFFERS from the v3 build, as it must",
      "1d99b7be2c513b19" not in _out, _out[-500:])

# ---- the pin must still be enforced, or the fix would be a hole ----
_d = sandbox()
_spec = os.path.join(_d, "specs", "pSense-Nit.spec.yaml")
_s = open(_spec, encoding="utf-8").read()
open(_spec, "w", encoding="utf-8").write(
    _s.replace("seq_sha256_12: 08a1e654bd76", "seq_sha256_12: ffffffffffff"))
_p = build(_d, "pSense-Nit.spec.yaml")
check("a pin matching NO sealed version is still refused", _p.returncode != 0,
      "exit %d" % _p.returncode)

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
```

- [ ] **Step 2: Run it and read which gates currently fail**

```bash
cd /Users/andrewhao/Desktop/katana && python3 tests/test_engine_gates.py
```

Expected: the two finding-A checks and the three finding-B checks FAIL; the sandbox-builds and pin-still-enforced checks pass. That failure set is the two defects, measured through the engine.

- [ ] **Step 3: Delegate the engine's manifest handling to `core.lock`**

In `katana_build.py`:

Add after the `_library_override()` block, where `LOCK_PATH` is set:

```python
sys.path.insert(0, str(HERE))
import vendor_path
vendor_path.ensure()
from core import hashing as _hashing
from core import lock as _lock
from core import parts as _parts
```

Replace `sha256_hex`, `seq_sha256` and `extract_gb_sequence` bodies with delegations:

```python
def sha256_hex(data: bytes) -> str:
    return _hashing.sha256_hex(data)


def seq_sha256(seq: str, topology: str = "linear") -> str:
    """Normalised sequence hash. `topology` is accepted and ignored: KATANA_SPEC v2
    section 3.4 specifies a topology tag, the sealed library predates it, and the
    convention lives in core.hashing now."""
    return _hashing.seq_sha256(seq)


def extract_gb_sequence(text: str) -> str:
    return _parts.extract_sequence(text, ".gb")
```

Replace `load_lock` with:

```python
def load_lock(lock_path: Path) -> list:
    """The manifest as a list of rows. A list, not a dict keyed by (id, version):
    keying silently kept the LAST of two rows claiming the same identity, where
    core.lock.resolve refuses the ambiguity."""
    try:
        return _lock.read(lock_path)[1]
    except _lock.LockError as exc:
        sys.exit("BLOCK: %s" % exc)
```

Replace `verify_lock_root` with:

```python
def verify_lock_root(lock_path: Path, lock_root_path: Path, pinned=None):
    """Delegates to core.lock.verify_root, which RECOMPUTES every row hash from the
    row's own fields before checking the root. This function used to hash the
    row_sha256 column as written, so editing a recorded accession without touching its
    row hash passed the gate -- CODE-REPORT finding A."""
    return _lock.verify_root(lock_path, lock_root_path, pinned)
```

In `resolve_parts`, replace the lock-key search and the pin comparison:

```python
        try:
            lock_row = _lock.resolve(lock, pid, pin=expected_sha12, lib=lib_file)
        except _lock.LockError as exc:
            sys.exit("BLOCK Stage-1: %s\n"
                     "       See what the library holds:  python3 find_part.py %s\n"
                     "       Add a part you are missing:  python3 add_part.py --help"
                     % (exc, pid))
        lock_sha = lock_row["seq_sha256"]
```

and delete the now-dead `if not lock_sha.startswith(expected_sha12):` block below it —
`resolve` enforces the pin, and enforcing it twice in two places is how the two copies
came to disagree in the first place.

- [ ] **Step 4: Run the gate tests**

```bash
cd /Users/andrewhao/Desktop/katana && python3 tests/test_engine_gates.py
```

Expected: `0 failed`.

- [ ] **Step 5: Run everything, including the oracle hashes**

```bash
cd /Users/andrewhao/Desktop/katana
SAFE=/usr/bin:/bin:/usr/sbin:/sbin
python3 tests/test_core_lock.py | tail -2
python3 tests/test_engine_gates.py | tail -2
python3 verify.py | grep -oE '[0-9]+/[0-9]+ checks passed'
python3 test_determinism.py | tail -1
(cd kagami && PATH="$SAFE" /usr/bin/python3 tests.py | tail -1)
(cd kagami && PATH="$SAFE" /usr/bin/python3 test_identify.py | tail -1)
```

Expected: `0 failed`, `0 failed`, `8/8`, `ALL PASSED — 10 checks`, `91 passed, 0 failed`,
`58 passed, 0 failed`. The ORACLE hashes are the critical ones: the refactor must not
change a single construct.

- [ ] **Step 6: Commit**

```bash
git add katana_build.py tests/test_engine_gates.py
git commit -m "fix!: the engine's two integrity gates, via core.lock

CODE-REPORT findings A and B, both fixed by deleting the engine's private copy of the
manifest logic rather than by patching it.

A. verify_lock_root() hashed the row_sha256 COLUMN as written, so editing a recorded
   accession without touching its row hash passed the gate: a falsified provenance claim
   built to completion with exit 0 while verify_library_v2.py reported two problems. The
   sequence was protected by stage 2; the recorded ORIGIN of that sequence was not, and
   a claim drifting from its bases is the failure this project exists to prevent.

B. resolve_parts() took max(version) and compared the Spec's pin against only that row,
   so a Spec pinned to an older sealed version -- row still in the manifest, file still
   on disk -- was refused, with advice to update the Spec to match the library. That
   advice changes the construct, and it contradicts ARCHITECTURE.md's promise that
   history is append-only so a build from last month can still be reproduced.

Both are now pinned END TO END, by driving katana_build.py as a subprocess against
sandbox copies: a unit test of core.lock would not have caught either, because both
lived in the engine's own copy. The suite also asserts the fix did not open a hole --
a pin matching no sealed version is still refused.

load_lock() returns a list rather than a dict keyed by (id, version): the dict silently
kept the LAST of two rows claiming one identity, where core.lock.resolve refuses the
ambiguity. The duplicate pin check in resolve_parts is deleted -- resolve enforces it,
and enforcing one rule in two places is how the copies came to disagree.

All 7 ORACLE construct hashes still reproduce. parts-library/ and specs/ untouched."
```

---

## Task 5: migrate `verify_library_v2.py`, `add_part.py`, `katana_init.py`, `find_part.py`

One commit each, so a regression bisects to a single consumer. Each follows the same
shape: delete the private copy, import from `core`, run the full suite, commit.

**Files:** `verify_library_v2.py`, `add_part.py`, `katana_init.py`, `find_part.py`

- [ ] **Step 1: `verify_library_v2.py` delegates to `core.parts.verify_library`**

Replace its `main()` body with:

```python
def main(lock_path):
    problems = K.verify_library(lock_path)
    if problems:
        print("BLOCK — %d problem(s):" % len(problems))
        for p in problems:
            print("  -", p)
        return 1
    _header, rows = K.read_lock(lock_path)
    root = K.lock_root(rows)
    print("SEALED — %d parts verified (file+seq+filename+manifest), root %s..., "
          "no orphans." % (len(rows), root[:16]))
    return 0
```

- [ ] **Step 2: Verify the adversarial suite still catches all eight**

```bash
cd /Users/andrewhao/Desktop/katana && python3 verify.py | tail -16
```

Expected: `8/8 checks passed` and `OK — the library is intact`. These eight are the
project's own proof that the checker works; if any stops being caught, the delegation is
wrong.

- [ ] **Step 3: Commit**

```bash
git add verify_library_v2.py
git commit -m "refactor: verify_library_v2 delegates to core.parts.verify_library

The audit logic moves into core/ so the GUI, the web front end and the CLI can all call
it directly instead of shelling out to this script and grepping its prose. The script
stays as the CLI entry point its callers and CI expect.

Verified: all eight adversarial checks in test_seal_gaps.py still catch what they are
meant to catch, which is the project's own proof that the checker works."
```

- [ ] **Step 4: `add_part.py` — delete its private hashing, manifest and render copies**

Remove `FIELDS`, `sha256_hex`, `seq_sha256`, `row_sha256`, `lock_root`,
`extract_gb_sequence`, `read_fasta`, `read_lock`, `write_lock` and `render_genbank`, and
import instead:

```python
sys.path.insert(0, str(Path(__file__).resolve().parent))
import vendor_path
vendor_path.ensure()
from core.hashing import FIELDS, HEADER, file_sha256, lock_root, row_sha256, seq_sha256, sha256_hex
from core.lock import LockError, read as read_lock
from core.parts import extract_sequence, render_genbank
```

Keep a local `write_lock` — writing is add_part's job, and `core.lock` is a reader in
phase 2. Replace `extract_gb_sequence(text)` calls with
`extract_sequence(text, ".gb")` and `read_fasta(text)` with
`extract_sequence(text, ".fasta")`.

- [ ] **Step 5: Admit a part into a scratch library and verify it**

```bash
cd /Users/andrewhao/Desktop/katana
rm -rf /tmp/apcheck && python3 katana_init.py /tmp/apcheck >/dev/null
python3 add_part.py --library /tmp/apcheck/parts-library \
    --from parts-library/ref_parts --id B0015 | tail -14
python3 verify_library_v2.py /tmp/apcheck/parts-library/ref_parts/LOCK.tsv
```

Expected: the `SEALED B0015 v1 129 bp 696c73e5a7a8` line, a pasteable `seal:` block, and
`SEALED — 1 parts verified`. This is the round trip that matters: a part admitted by the
migrated intake gate must verify under the migrated verifier.

- [ ] **Step 6: Commit**

```bash
git add add_part.py
git commit -m "refactor: add_part uses core for hashing, manifest and rendering

Deletes its private copies of seq_sha256, row_sha256, lock_root, extract_gb_sequence,
read_fasta, read_lock and render_genbank. Its own comment said the duplication of
seq_sha256 was 'deliberate and load-bearing' because a drift would make every part this
tool admits unbuildable. The danger was real; one definition is the remedy.

Verified by round trip: a part admitted into a fresh library by the migrated intake gate
verifies under the migrated verifier."
```

- [ ] **Step 7: `katana_init.py` — use `core.hashing.HEADER` and `EMPTY_ROOT`**

Replace its `FIELDS`, `HEADER` and `EMPTY_ROOT` with:

```python
sys.path.insert(0, str(Path(__file__).resolve().parent))
import vendor_path
vendor_path.ensure()
from core.hashing import HEADER, lock_root

# lock_root over zero rows. Computed rather than written down, so it stays correct if
# the rule ever changes.
EMPTY_ROOT = lock_root([])
```

- [ ] **Step 8: A fresh library must be verifiable and buildable**

```bash
cd /Users/andrewhao/Desktop/katana
rm -rf /tmp/initcheck && python3 katana_init.py /tmp/initcheck | tail -6
python3 verify_library_v2.py /tmp/initcheck/parts-library/ref_parts/LOCK.tsv
python3 check_design.py /tmp/initcheck/specs/example.spec.yaml | tail -8
```

Expected: the creation summary, `SEALED — 0 parts verified`, and `check_design` reporting
the template's placeholder seal as a PROBLEM — which is the behaviour that stops a
beginner reading "nothing to report" over an unfilled template.

- [ ] **Step 9: Commit**

```bash
git add katana_init.py
git commit -m "refactor: katana_init uses core.hashing for the header and empty root

Its comment warned that FIELDS 'must match katana_lock.FIELDS exactly' because
row_sha256 is computed over those keys in that order, and that a header disagreeing with
the hashing code produces rows nobody can reproduce. That is now structurally impossible.

Verified: a fresh library verifies as SEALED with 0 parts, and check_design still reports
the template's placeholder seal as a problem rather than 'nothing to report'."
```

- [ ] **Step 10: `find_part.py` — delete `read_rows`**

Replace its `read_rows` with `from core.lock import read as _read_lock` and
`read_rows = lambda p: _read_lock(p)[1]` expressed as a named function:

```python
def read_rows(lock):
    """The manifest's rows. core.lock.read refuses a manifest missing a hashable
    column, which this function used to accept and then index into blindly."""
    return _read_lock(lock)[1]
```

- [ ] **Step 11: Verify the listing still works, including its twin detection**

```bash
cd /Users/andrewhao/Desktop/katana && python3 find_part.py --have 2>&1 | tail -22
```

Expected: the 30-part listing, the `NOTE: different names, identical sequence` block
naming `RBS_hrpS = RBS_lldR_strong`, and the multiple-version note. That twin detection
is a real incident this project hit; it must survive the migration.

- [ ] **Step 12: Run everything and commit**

```bash
cd /Users/andrewhao/Desktop/katana
SAFE=/usr/bin:/bin:/usr/sbin:/sbin
for t in tests/test_core_lock.py tests/test_engine_gates.py; do python3 $t | tail -1; done
python3 verify.py | grep -oE '[0-9]+/[0-9]+ checks passed'
python3 test_determinism.py | tail -1
(cd kagami && PATH="$SAFE" /usr/bin/python3 tests.py | tail -1)
(cd kagami && PATH="$SAFE" /usr/bin/python3 test_identify.py | tail -1)
git add find_part.py
git commit -m "refactor: find_part reads the manifest through core.lock

Verified: the 30-part listing still works, and it still reports
RBS_hrpS = RBS_lldR_strong as different names holding identical sequence. That twin
detection exists because two RBS parts came out byte-identical here and produced a 43 bp
direct repeat that forced a construct revision; it must survive any refactor."
```

---

## Task 6: migrate the four Kagami consumers

**Files:** `kagami/kg_refs.py`, `kagami/kg_rebuild.py`, `kagami/kg_katana_tabs.py`, `kagami/build_refs.py`

One commit each. Kagami reaches `core/` by walking up to the repository root, the same
way it already finds the forward engine in `kg_rebuild.find_engine`.

- [ ] **Step 1: Add the import helper to `kagami/kg_refs.py`**

```python
def _import_core():
    """core/ lives at the repository root, one level above kagami/.

    Kagami deliberately imports NOTHING from the forward engine and drives it as
    subprocesses instead, so that the two stay decoupled. core/ is different: it is not
    the engine, it is the shared definition of what a manifest and a part file ARE.
    Four Kagami modules each had their own copy, and the point of core/ is that there is
    one.
    """
    import os
    import sys
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if os.path.isdir(os.path.join(root, "core")) and root not in sys.path:
        sys.path.insert(0, root)
    try:
        from core import hashing, lock, parts
        return hashing, lock, parts
    except ImportError:
        return None, None, None


_hashing, _lock, _core_parts = _import_core()
```

- [ ] **Step 2: Use it in `load_katana_library`**

Replace its hand-rolled header/row parsing and its `hashlib.sha256(...)` call with
`_lock.read(lock)` and `_hashing.seq_sha256(seq)`, keeping the fail-closed behaviour and
the per-part problem messages exactly as they are. When `_lock` is None (Kagami unzipped
on its own, without the bundle) fall back to the existing inline parsing, and say so in a
comment — Kagami must keep working standalone.

- [ ] **Step 3: Verify the hash gate still refuses a tampered part**

```bash
cd /Users/andrewhao/Desktop/katana/kagami && python3 tests.py 2>&1 | grep -iE 'library|passed,'
```

Expected: `--library loads a hash-verified part`, `--library refuses a part whose bytes
no longer match LOCK`, and `91 passed, 0 failed`. That refusal is the gate that stops a
drifted part becoming a reference and poisoning every identification after it.

- [ ] **Step 4: Commit**

```bash
git add kagami/kg_refs.py
git commit -m "refactor: kg_refs reads a Katana library through core.lock

Kagami imports nothing from the forward ENGINE and drives it as subprocesses, which
keeps the two decoupled. core/ is a different thing: not the engine, but the shared
definition of what a manifest and a part file are. Four Kagami modules each had a copy.

Falls back to inline parsing when core/ is absent, so Kagami unzipped on its own still
works -- it is the tool the wiki invites a stranger to download.

Verified: the --library hash gate still refuses a part whose bytes no longer match LOCK,
which is what stops a drifted part becoming a reference and poisoning every
identification after it."
```

- [ ] **Step 5: `kagami/kg_rebuild.py` — replace `_lock_rows`**

```python
def _lock_rows(library):
    """The target library's rows, keyed by id. Reads through core.lock when the bundle
    is present, so a manifest missing a hashable column is refused here rather than
    producing a half-built Spec."""
    lock = _lock_path(library)
    if not lock:
        return {}
    hashing, core_lock, _parts = kg_refs._import_core()
    if core_lock is not None:
        try:
            rows = core_lock.read(lock)[1]
        except core_lock.LockError:
            return {}
        return {r["id"]: {"version": r["version"], "seq_sha256": r["seq_sha256"],
                          "length": r["length"], "outfile": r["outfile"]}
                for r in rows}
    return _lock_rows_inline(lock)
```

Keep the existing body as `_lock_rows_inline(lock)`.

- [ ] **Step 6: Verify `plan()` still blocks what it must**

```bash
cd /Users/andrewhao/Desktop/katana/kagami && python3 tests.py 2>&1 | grep -E 'plan:|passed,'
```

Expected: the four `plan:` assertions pass and `91 passed, 0 failed`. Those encode the
core law — a part with no independent primary source cannot be sealed.

- [ ] **Step 7: Commit**

```bash
git add kagami/kg_rebuild.py
git commit -m "refactor: kg_rebuild reads the target library through core.lock

Verified: plan() still marks a Registry part fetchable, still blocks a designed or
non-Registry part, still blocks an unidentified block, and still reuses a part already
in the library. Those four encode the law the whole system rests on -- a part with no
independent primary source cannot be sealed."
```

- [ ] **Step 8: `kagami/kg_katana_tabs.py` — replace `read_lock`**

```python
def read_lock(lock):
    """LOCK.tsv -> list of dict rows, for the Library tab's table. Returns [] if
    unreadable: a tab that cannot list parts must not take the window down with it."""
    _h, core_lock, _p = kg_refs._import_core()
    if core_lock is not None:
        try:
            return core_lock.read(lock)[1]
        except Exception:
            return []
    try:
        with open(lock, encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh, delimiter="\t"))
    except Exception:
        return []
```

- [ ] **Step 9: Verify the tabs still import and classify**

```bash
cd /Users/andrewhao/Desktop/katana/kagami && python3 tests.py 2>&1 | grep -E 'engine tabs|SEALED|BLOCKED|gate did not run|passed,'
```

Expected: the eight `classify` assertions pass and `91 passed, 0 failed`.

- [ ] **Step 10: Commit**

```bash
git add kagami/kg_katana_tabs.py
git commit -m "refactor: the Library tab reads the manifest through core.lock

Still returns [] rather than raising when a manifest is unreadable: a tab that cannot
list parts must not take the window down with it.

Verified: the eight classify() assertions still pass, including the one that matters --
a run that exited 0 while saying a gate did not run is REVIEW, never PASS."
```

- [ ] **Step 11: `kagami/build_refs.py` — delete its four hashing copies**

Remove `LOCK_FIELDS`, `_sha`, `seq_sha256_of`, `_row_sha`, `_lock_root`, `read_lock` and
`_filename_sha12`; import from `core` through `kg_refs._import_core()`, keeping the
fail-closed per-part gate and the `LOCK.root.log` attestation check exactly as they are.

- [ ] **Step 12: Verify the reference set still rebuilds from the sealed library**

```bash
cd /Users/andrewhao/Desktop/katana/kagami
cp refs/reference_parts.tsv /tmp/refs-before.tsv
python3 build_refs.py --library ../parts-library 2>&1 | tail -8
diff <(cut -f1 /tmp/refs-before.tsv | sort) <(cut -f1 refs/reference_parts.tsv | sort) \
  && echo "the reference set's part ids are unchanged"
git checkout refs/ 2>/dev/null || true
```

Expected: the `LOCK.root OK` line, a `wrote N parts` summary, and the id sets identical.
The `git checkout refs/` restores the shipped set, because `build_refs` without
`--registry-bulk` legitimately produces a smaller file and this step is a behaviour
check, not a regeneration.

- [ ] **Step 13: Commit**

```bash
git add kagami/build_refs.py
git commit -m "refactor: build_refs hashes through core.hashing

Deletes the fifth copy of the conventions. Its header comment said the hashing was
'byte-for-byte per parts-library/_tools/katana_lock.py' -- a file that is not in this
repository, which is exactly how a hand-maintained copy drifts.

The fail-closed gate is unchanged: every part still has its seq_sha256 recomputed and
matched against BOTH the LOCK row and the sha12 in its filename, and LOCK.root is still
checked against the last attested root, before any sequence is written.

Verified: the reference set rebuilds from the sealed library with the same part ids."
```

---

## Task 7: prove there is only one implementation left

**Files:** Create `tests/test_one_core.py`

- [ ] **Step 1: Write the test**

```python
"""test_one_core.py — assert the duplication this phase removed cannot come back.

Run: python3 tests/test_one_core.py

Eight modules each parsed LOCK.tsv and five each defined the hashing conventions, every
one with a comment explaining why its copy was necessary. The comments were sincere and
the copies still drifted: two of them disagreed about whether a row's hash is recomputed
before the root is checked, and about whether a Spec's pin or the highest version number
decides which part is loaded. Those were CODE-REPORT findings A and B.

A convention cannot be enforced by a comment. This asserts it.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  [" + detail + "]") if detail else ""))


def tracked_py():
    out = subprocess.check_output(["git", "ls-files", "*.py"], cwd=ROOT, text=True)
    return [f for f in out.split() if not f.startswith(("_vendor/", "core/", "tests/"))]


print("one core")

# The hashing conventions: one definition. A module may CALL them from anywhere.
_defs = []
for f in tracked_py():
    src = open(os.path.join(ROOT, f), encoding="utf-8").read()
    for fn in ("def seq_sha256", "def row_sha256", "def lock_root"):
        if fn in src:
            _defs.append("%s: %s" % (f, fn))
check("only core/ defines the hashing conventions (%s)" % (", ".join(_defs) or "clean"),
      not _defs)

# The manifest: nobody re-implements the parse. Splitting a LOCK line on tabs and
# zipping it against a header IS the parser, however few lines it takes.
_parsers = []
for f in tracked_py():
    src = open(os.path.join(ROOT, f), encoding="utf-8").read()
    if 'split("\\t")' in src and ("LOCK" in src or "lock" in src):
        _parsers.append(f)
check("nobody splits a LOCK line on tabs outside core/ (%s)"
      % (", ".join(_parsers) or "clean"), not _parsers)

# core/ must stay loadable by Pyodide.
_banned = ("subprocess", "shutil", "socket", "urllib", "multiprocessing", "ctypes")
_bad = []
for f in sorted(os.listdir(os.path.join(ROOT, "core"))):
    if f.endswith(".py"):
        src = open(os.path.join(ROOT, "core", f), encoding="utf-8").read()
        _bad += ["%s imports %s" % (f, m) for m in _banned if ("import " + m) in src]
check("core/ imports nothing Pyodide cannot run (%s)" % (", ".join(_bad) or "clean"),
      not _bad)

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
```

- [ ] **Step 2: Run it**

```bash
cd /Users/andrewhao/Desktop/katana && python3 tests/test_one_core.py
```

Expected: `0 failed`. If it names a file, that consumer was missed in Task 5 or 6 — fix
the consumer, not the test.

- [ ] **Step 3: Add the new suites to CI**

In `.gitlab-ci.yml`, add to the `no-deps` job's script, after `python3 verify.py`:

```yaml
      - python3 tests/test_core_lock.py
      - python3 tests/test_engine_gates.py
      - python3 tests/test_one_core.py
```

and to the `verify` job's script the same three lines.

- [ ] **Step 4: Validate the CI file the way that actually checks it**

```bash
cd /Users/andrewhao/Desktop/katana && python3 -c "
import sys; sys.path.append('_vendor'); import yaml
d = yaml.safe_load(open('.gitlab-ci.yml'))
bad = [(j, i) for j, c in d.items() if isinstance(c, dict) and 'script' in c
       for i in c['script'] if not isinstance(i, str)]
print('non-string script entries:', bad or 'none')
"
```

Expected: `none`. Asserting the entries are strings, not merely that the file parses —
the mistake that let a YAML mapping into the `no-deps` script in phase 1.

- [ ] **Step 5: Commit**

```bash
git add tests/test_one_core.py .gitlab-ci.yml
git commit -m "test: assert the duplication cannot come back

Eight modules each parsed LOCK.tsv and five each defined the hashing conventions, every
one with a comment explaining why its copy was necessary. The comments were sincere and
the copies still drifted: two disagreed about whether a row's hash is recomputed before
the root is checked, and about whether a Spec's pin or the highest version decides which
part is loaded. Those were CODE-REPORT findings A and B, and they cost a falsified
accession that built cleanly and a Spec that could not rebuild last month's construct.

A convention cannot be enforced by a comment. Three assertions enforce it: only core/
defines the hashing functions, nobody splits a LOCK line on tabs outside core/, and
core/ imports nothing Pyodide cannot run.

CI runs the three new suites in both the no-deps and the full job."
```

---

## Task 8: Phase 2 verification

- [ ] **Step 1: Every suite, on a bare interpreter with blastn hidden**

```bash
cd /Users/andrewhao/Desktop/katana
SAFE=/usr/bin:/bin:/usr/sbin:/sbin
python3 -c "import yaml" 2>&1 | tail -1
for t in tests/test_core_lock.py tests/test_engine_gates.py tests/test_one_core.py; do
  printf "%-32s " "$t"; python3 "$t" | tail -1
done
printf "%-32s " verify.py;          python3 verify.py | grep -oE '[0-9]+/[0-9]+ checks passed'
printf "%-32s " test_determinism.py; python3 test_determinism.py | tail -1
printf "%-32s " kagami/tests.py;     (cd kagami && PATH="$SAFE" /usr/bin/python3 tests.py | tail -1)
printf "%-32s " kagami/test_identify.py; (cd kagami && PATH="$SAFE" /usr/bin/python3 test_identify.py | tail -1)
```

Expected: `ModuleNotFoundError: No module named 'yaml'`, then `0 failed` three times,
`8/8 checks passed`, `ALL PASSED — 10 checks`, `91 passed, 0 failed`, `58 passed, 0 failed`.

- [ ] **Step 2: The library and the Specs are untouched**

```bash
cd /Users/andrewhao/Desktop/katana && git diff --stat main..HEAD -- parts-library/ specs/
```

Expected: no output.

- [ ] **Step 3: Count what was removed**

```bash
cd /Users/andrewhao/Desktop/katana && git diff --stat $(git log --format=%H -n1 --grep='phase 1 complete')..HEAD -- . ':(exclude)docs' | tail -3
```

- [ ] **Step 4: Commit the phase marker**

```bash
git commit --allow-empty -m "chore: phase 2 complete -- one shared core

Eight LOCK.tsv parsers and five definitions of the hashing conventions are now one
core/ package that every consumer imports, and the two defects that lived in the
disagreement between copies are fixed structurally:

  A. a falsified accession no longer builds. verify_lock_root recomputed nothing and
     hashed the row_sha256 column as written; core.lock.verify_root recomputes every
     row hash from the row's own fields.
  B. a Spec pinned to an older sealed version builds again, and reproduces that older
     construct. resolve_parts took max(version); core.lock.resolve selects by the pin.

Both pinned end to end by driving the engine as a subprocess against sandbox libraries,
because a unit test of core.lock would have caught neither -- both lived in the engine's
own copy. tests/test_one_core.py asserts the duplication cannot return.

Verified with nothing installed and blastn hidden: three new suites 0 failed, verify.py
8/8, test_determinism.py ALL PASSED 10 with all 7 ORACLE hashes reproduced,
kagami/tests.py 91/0, test_identify.py 58/0. parts-library/ and specs/ byte-identical
to main.

Next: phase 3 (spec steps 4-6) -- build() returns a BuildResult, the GUI calls functions
instead of greping subprocess prose, and a single `katana` entry point with an
interactive menu."
```

---

## Deferred to a later phase, deliberately

The spec's §3.1 shows a target tree with `forward/` and `reverse/` packages. **This phase
does not move files.** The migration order (spec §10) asks step 3 for the `core/`
extraction, and renaming directories at the same time would double the risk on the step
the spec already grades `high` while serving none of the stated goals — it breaks every
documented command path, both launchers, CI, and the engine's own walk-up library
discovery, in exchange for tidier names. The shared core is the substance; the directory
layout is cosmetics, and it can follow once `BuildResult` (phase 3) has settled what the
module boundaries actually are.
