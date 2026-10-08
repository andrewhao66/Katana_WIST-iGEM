#!/usr/bin/env python3
"""make_bundle.py — build the zip a person downloads.

`katana bundle` lands here.

What goes in is decided by a list, not by "everything except": a zip assembled by
exclusion eventually ships somebody's working notes, their own parts library, or a
half-finished spec. The list below is the bundle, and a test asserts the result contains
exactly it.

What a person then does is:

    unzip katana.zip
    cd katana
    ./katana

Nothing to install. No pip, no NCBI BLAST+, no genome download. That is the whole of the
install instructions, and it is three lines because this phase removed the other twenty-
seven.
"""
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))

# Every entry is either a file or a directory to include whole. Nothing is included by
# wildcard across the repository root, so a new private file at the root is not
# published by accident.
INCLUDE_FILES = [
    "katana",
    "katana.bat",
    "ui_menu.py",
    "web_serve.py",
    "web_deploy.py",
    "vendor_path.py",
    "katana_build.py",
    "katana_drylab.py",
    "katana_lock.py",
    "katana_order_table.py",
    "katana_sbol.py",
    "katana_init.py",
    "add_part.py",
    "find_part.py",
    "get_genome.py",
    "check_design.py",
    "blast_offtarget.py",
    "verify.py",
    "verify_library_v2.py",
    "test_seal_gaps.py",
    "test_determinism.py",
    "requirements.txt",
    "requirements-optional.txt",
    "README.md",
    "ARCHITECTURE.md",
    "AGENTS.md",
    "CLAUDE.md",
    "LICENSE",
    "LICENSE.md",
]

INCLUDE_DIRS = [
    "core",
    "ui",
    "tests",
    "_vendor",
    "specs",
    "parts-library",
    "kagami",
]

# Inside the included directories. __pycache__ is machine-specific noise; .DS_Store is
# the Finder's. Neither belongs in something hashed and distributed.
SKIP_DIRS = {"__pycache__", ".git", ".superpowers", "outputs", "_site", ".venv", "venv"}
SKIP_SUFFIXES = (".pyc", ".pyo", ".so")
SKIP_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}


def manifest():
    """Every path that goes into the bundle, relative to the repository root."""
    out = []
    for rel in INCLUDE_FILES:
        if os.path.isfile(os.path.join(HERE, rel)):
            out.append(rel)
    for top in INCLUDE_DIRS:
        base = os.path.join(HERE, top)
        if not os.path.isdir(base):
            continue
        for root, dirs, files in os.walk(base):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            for name in sorted(files):
                if name in SKIP_NAMES or name.endswith(SKIP_SUFFIXES):
                    continue
                full = os.path.join(root, name)
                out.append(os.path.relpath(full, HERE))
    return sorted(out)


def missing():
    """Listed files that are not here. Empty means the bundle will be complete."""
    return [r for r in INCLUDE_FILES
            if not os.path.isfile(os.path.join(HERE, r))]


def build(out_path, prefix="katana"):
    """Write the zip. Returns (file count, uncompressed bytes, compressed bytes)."""
    paths = manifest()
    total = 0
    # ZIP_DEFLATED, and the sealed artifacts are stored byte-for-byte: a zip must not
    # translate anything. LOCK.tsv records a file_sha256 per part and verify.py
    # recomputes it on read, so a single rewritten byte makes the library report itself
    # as tampered -- which is exactly what happened to the first public clone of this
    # repository, when git converted line endings on checkout.
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel in paths:
            full = os.path.join(HERE, rel)
            total += os.path.getsize(full)
            info = zipfile.ZipInfo(prefix + "/" + rel.replace(os.sep, "/"))
            # A fixed timestamp, so the same tree produces the same zip. A bundle whose
            # bytes change every time it is built cannot be checksummed by whoever
            # publishes it.
            info.date_time = (2026, 1, 1, 0, 0, 0)
            mode = 0o755 if rel in ("katana",) or rel.endswith(".command") else 0o644
            info.external_attr = (0o100000 | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            with open(full, "rb") as f:
                z.writestr(info, f.read())
    return len(paths), total, os.path.getsize(out_path)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    out = os.path.join(HERE, "katana.zip")
    for i, tok in enumerate(argv):
        if tok == "--out" and i + 1 < len(argv):
            out = os.path.abspath(argv[i + 1])

    gaps = missing()
    if gaps:
        print("BLOCK: these files are listed for the bundle but are not here:")
        for g in gaps:
            print("  " + g)
        return 2

    n, raw, packed = build(out)
    print("Wrote %s" % out)
    print()
    print("  %d files, %.1f MB uncompressed, %.1f MB zipped"
          % (n, raw / 1e6, packed / 1e6))
    print()
    print("What someone does with it:")
    print()
    print("    unzip %s" % os.path.basename(out))
    print("    cd katana")
    print("    ./katana")
    print()
    print("Use `unzip`, not a double-click. The zip stores the launcher as executable and")
    print("`unzip` keeps that, but Finder's Archive Utility and some GUI tools drop it --")
    print("measured: Python's own zipfile module strips it too. Then `./katana` answers")
    print("\"Permission denied\" and nothing explains why. If that happens:")
    print()
    print("    bash katana            # works whatever the permissions are")
    print("    chmod +x katana        # or fix it once and use ./katana after")
    print()
    print("Nothing to install. On a Mac they must run it from Terminal rather than")
    print("double-clicking the launcher, because macOS blocks downloaded scripts that are")
    print("not code-signed -- the README says so, and so does the launcher itself.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
