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
    for ln in lines[1:]:
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
    with open(root_path, "r", encoding="utf-8") as f:
        disk_root = f.read().strip()

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
