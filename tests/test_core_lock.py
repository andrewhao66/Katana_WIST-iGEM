"""Tests for the shared LOCK core. Run: python3 tests/test_core_lock.py

Plain asserts in the style of kagami/tests.py, so the suite needs nothing installed.
"""
import os
import shutil
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

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
