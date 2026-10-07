"""test_one_core.py — assert the duplication this phase removed cannot come back.

Run: python3 tests/test_one_core.py

Eight modules each parsed LOCK.tsv and five each defined the hashing conventions, every
one with a comment explaining why its copy was necessary. The comments were sincere and
the copies still drifted: two of them disagreed about whether a row's hash is recomputed
before the root is checked, and about whether a Spec's pin or the highest version number
decides which part is loaded. Those were CODE-REPORT findings A and B, and they cost a
falsified accession that built cleanly and a Spec that could not rebuild last month's
construct.

A convention cannot be enforced by a comment. This enforces it.
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
    """Tracked Python outside core/, tests/ and the vendored upstream."""
    out = subprocess.check_output(["git", "ls-files", "*.py"], cwd=ROOT, text=True)
    return [f for f in out.split()
            if not f.startswith(("_vendor/", "core/", "tests/"))]


print("one core")

_files = tracked_py()
check("there is tracked Python to check", len(_files) > 10, str(len(_files)))

# The hashing conventions: one definition. A module may CALL them from anywhere, and
# may define a FALLBACK for a standalone unzip -- Kagami ships on its own -- but the
# forward engine, which always has core/ beside it, must not.
# katana_lock.py is a deliberate compatibility shim whose entire job is to forward the
# old public names to core/, so that verify_library_v2.py, test_seal_gaps.py and anything
# outside this repository keep working. Exempt by name, with the reason, rather than by a
# pattern that would also exempt a real copy.
_SHIMS = {"katana_lock.py"}
_engine = [f for f in _files
           if not f.startswith("kagami/") and f not in _SHIMS]
_defs = []
for f in _engine:
    with open(os.path.join(ROOT, f), encoding="utf-8") as fh:
        src = fh.read()
    for fn in ("def seq_sha256", "def row_sha256", "def lock_root", "def row_manifest"):
        if fn in src:
            _defs.append("%s: %s" % (f, fn))
check("only core/ defines the hashing conventions in the engine (%s)"
      % (", ".join(_defs) or "clean"), not _defs)

# The manifest: nobody re-implements the parse in the engine. Splitting a LOCK line on
# tabs and zipping it against a header IS the parser, however few lines it takes.
_parsers = []
for f in _engine:
    with open(os.path.join(ROOT, f), encoding="utf-8") as fh:
        src = fh.read()
    # "LOCK.tsv", not "LOCK": the bare substring matches BLOCK and CAI_BLOCK, which is
    # why katana_drylab.py -- which splits tabs to read genomes.tsv -- was flagged.
    if 'split("\t")' in src and "LOCK.tsv" in src:
        _parsers.append(f)
check("no engine module splits a LOCK line on tabs outside core/ (%s)"
      % (", ".join(_parsers) or "clean"), not _parsers)

# Kagami's fallbacks are allowed, but each must be reached through _import_core() so
# there is exactly one decision about where core/ comes from.
_kagami = [f for f in _files if f.startswith("kagami/")]
_rogue = []
for f in _kagami:
    with open(os.path.join(ROOT, f), encoding="utf-8") as fh:
        src = fh.read()
    if 'split("\t")' in src and "LOCK.tsv" in src and "_import_core" not in src:
        _rogue.append(f)
check("every Kagami module that reads a manifest goes through _import_core (%s)"
      % (", ".join(_rogue) or "clean"), not _rogue)

# core/ must stay loadable by Pyodide: it is the module set the browser front end loads.
_banned = ("subprocess", "shutil", "socket", "urllib", "multiprocessing", "ctypes")
_bad = []
for f in sorted(os.listdir(os.path.join(ROOT, "core"))):
    if f.endswith(".py"):
        with open(os.path.join(ROOT, "core", f), encoding="utf-8") as fh:
            src = fh.read()
        _bad += ["%s imports %s" % (f, m) for m in _banned if ("import " + m) in src]
check("core/ imports nothing Pyodide cannot run (%s)" % (", ".join(_bad) or "clean"),
      not _bad)

# And core/ must not reach back into the engine or into Kagami: a shared core that
# imports its own consumers is not shared, it is a cycle waiting to be discovered.
_up = []
for f in sorted(os.listdir(os.path.join(ROOT, "core"))):
    if f.endswith(".py"):
        with open(os.path.join(ROOT, "core", f), encoding="utf-8") as fh:
            src = fh.read()
        for mod in ("katana_build", "katana_lock", "add_part", "find_part",
                    "kg_refs", "kg_parse", "vendor_path"):
            if ("import " + mod) in src:
                _up.append("%s imports %s" % (f, mod))
check("core/ imports none of its own consumers (%s)" % (", ".join(_up) or "clean"),
      not _up)

# ---- every test suite in the repository is actually run by CI ----
# test_seal_gaps.py -- the adversarial self-test that reproduces eight sealing exploits
# and asserts each is blocked -- was in the repository and in NO CI job. A test nobody
# runs is a test that rots, and this one had: its default library path was ".", so a bare
# run failed at its first assertion and crashed on a missing LOCK.tsv. That is confusing
# enough to explain why it was quietly left out, which is how an adversarial self-test
# stops being run at all.
#
# So the coverage is checked rather than remembered. A suite added later and forgotten
# here fails this assertion instead of going unnoticed for months.
sys.path.append(os.path.join(ROOT, "_vendor"))
import yaml as _yaml

_ci = _yaml.safe_load(open(os.path.join(ROOT, ".gitlab-ci.yml"), encoding="utf-8"))
_cwd = ""
_run = set()
for _job, _cfg in _ci.items():
    if not isinstance(_cfg, dict) or "script" not in _cfg:
        continue
    _cwd = ""
    for _line in _cfg["script"]:
        _s = str(_line).strip()
        if _s.startswith("cd "):
            _cwd = _s[3:].strip().strip("/") + "/"
            continue
        for _m in re.findall(r"python3?\s+(\S+\.py)", _s):
            _run.add(_cwd + _m if not _m.startswith(("tests/", "kagami/")) else _m)

_suites = set()
for _f in sorted(os.listdir(os.path.join(ROOT, "tests"))):
    if _f.startswith("test_") and _f.endswith(".py"):
        _suites.add("tests/" + _f)
for _f in ("verify.py", "test_determinism.py", "test_seal_gaps.py"):
    if os.path.isfile(os.path.join(ROOT, _f)):
        _suites.add(_f)
for _f in ("tests.py", "test_identify.py"):
    if os.path.isfile(os.path.join(ROOT, "kagami", _f)):
        _suites.add("kagami/" + _f)

_unrun = sorted(_suites - _run)
check("every test suite in the repository is run by CI (%s)"
      % (", ".join(_unrun) or "all %d of them" % len(_suites)), not _unrun)

_phantom = sorted(n for n in _run
                  if n.endswith(".py") and n.startswith(("tests/", "kagami/"))
                  and not os.path.isfile(os.path.join(ROOT, n)))
check("and CI names no suite that does not exist (%s)"
      % (", ".join(_phantom) or "none"), not _phantom)

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
