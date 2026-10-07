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
      lock.resolve(_rows, "HrpS.Ec-opt", pin=_v3["seq_sha256"][:12])["version"] == "3")
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
