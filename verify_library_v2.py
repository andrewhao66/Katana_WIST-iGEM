#!/usr/bin/env python3
"""Fail-closed Parts Library audit.

Checks every LOCK row: file present, file_sha256, seq_sha256, filename sha12, row
manifest. Then: no orphan part files without a row, and LOCK.root recomputed and matched.

Exit code 0 only if EVERYTHING passes. Any problem -> non-zero (BLOCK).

The audit itself lives in core.parts.verify_library, so the GUI, the web front end and
this script all run the same checks rather than one of them shelling out to another and
grepping its prose. This file stays as the CLI entry point its callers and CI expect.
"""
import sys

import katana_lock as K


def main(lock_path):
    problems = K.verify_library(lock_path)
    if problems:
        print("BLOCK — %d problem(s):" % len(problems))
        for p in problems:
            print("  -", p)
        return 1

    _header, rows = K.read_lock(lock_path)
    root = K.lock_root(rows)
    pending = K.count_pending(lock_path)
    print("SEALED — %d parts verified (file+seq+filename+manifest), root %s..., "
          "no orphans." % (len(rows), root[:16])
          + (" [%d file(s) in _incoming pending intake — OK]" % pending if pending else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "LOCK.tsv"))
