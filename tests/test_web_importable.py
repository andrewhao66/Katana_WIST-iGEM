"""test_web_importable.py — the audit path must import in a browser.

Run: python3 tests/test_web_importable.py

The web front end loads the SAME modules through Pyodide rather than reimplementing
anything, because two implementations of one check drift and this project's whole thesis
is that drift is the enemy. That only works if those modules import without the process
tools a browser does not have.

Pyodide ships a `subprocess` that exists and raises when used, so a module-level
`import subprocess` happens to survive today. Relying on that is relying on a stub's
politeness. These tests block the modules outright, which is the stricter claim and the
one that keeps working if Pyodide changes its mind.
"""
import builtins
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "kagami"))

PASS = FAIL = 0

# What a browser does not have. shutil is in Pyodide, but shutil.which is meaningless
# there, so a module that reaches for it at import time is a module that has not thought
# about running anywhere but a shell.
BLOCKED = ("subprocess", "multiprocessing", "socket", "ctypes")

# core/ and the audit half of kagami/. This list IS the web front end's module set: if a
# name is added here it must also be added to the page's loader, and the deploy script
# copies exactly these.
WEB_MODULES = [
    "core.hashing", "core.lock", "core.parts", "core.result",
    "kg_parse", "kg_refs", "kg_seedmatch", "kg_identify", "kg_audit", "kg_bridge",
]


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  [" + str(detail)[:300] + "]") if detail else ""))


_real_import = builtins.__import__


def _blocking_import(name, *a, **k):
    root = name.split(".")[0]
    if root in BLOCKED:
        raise ImportError("%s is not available in a browser" % root)
    return _real_import(name, *a, **k)


print("web importability")

# Import each module fresh, with the browser-absent modules blocked.
for mod in WEB_MODULES:
    for cached in list(sys.modules):
        if cached == mod or cached.startswith(mod + "."):
            del sys.modules[cached]
    for b in BLOCKED:
        sys.modules.pop(b, None)

    builtins.__import__ = _blocking_import
    err = None
    try:
        _real_import(mod)
    except Exception as exc:
        err = "%s: %s" % (type(exc).__name__, exc)
    finally:
        builtins.__import__ = _real_import
    check("%s imports with subprocess blocked" % mod, err is None, err or "")

# And the audit actually RUNS, not merely imports. This is the path the page takes.
builtins.__import__ = _blocking_import
_err = None
try:
    import kg_audit
    import kg_identify
    import kg_parse
    import kg_refs

    # The LOCUS length is COMPUTED, not written down. It used to say 60 -- copied from
    # the 60-bases-per-line format, not from the sequence, which is 63 -- and the parser
    # read the LOCUS line for the name and the topology only, so nothing noticed. When
    # the parser started comparing the two, this fixture was the first thing it caught.
    _seq = (kg_refs.normalise(kg_refs.by_id()["J23116"]["seq"])
            + kg_refs.normalise(kg_refs.by_id()["B0034"]["seq"])
            + "CACAACACTTGCAACG")
    _gb = (
        "LOCUS       t %d bp DNA linear SYN\n" % len(_seq)
        + "FEATURES             Location/Qualifiers\n"
        + "     misc_feature    1..35\n"
        + '                     /label="B0032"\n'
        + "ORIGIN\n"
    )
    for _i in range(0, len(_seq), 60):
        _gb += "%9d %s\n" % (_i + 1, _seq[_i:_i + 60].lower())
    _gb += "//\n"

    import tempfile
    _d = tempfile.mkdtemp(prefix="web_")
    _p = os.path.join(_d, "c.gb")
    open(_p, "w", encoding="utf-8").write(_gb)
    _rec = kg_parse.parse(_p)
    _st = {}
    _blocks = kg_identify.identify(_rec, _d, status=_st)
    _findings = kg_audit.audit(_rec, _blocks, identify_status=_st)
    _verdict = kg_audit.verdict_kind(_findings)
except Exception as exc:
    import traceback
    _err = "%s: %s" % (type(exc).__name__, exc)
    _blocks, _findings, _verdict, _st = [], [], None, {}
finally:
    builtins.__import__ = _real_import

check("a full audit runs with subprocess blocked", _err is None, _err or "")
check("and identification reports that it RAN", _st.get("ran") is True, str(_st))
check("and it identified something", any(b.ident_id for b in _blocks),
      str([b.ident_id for b in _blocks]))
check("and it produced a verdict", _verdict in ("PASS", "REVIEW", "FAIL"),
      str(_verdict))

# The data the page must fetch. Sizes matter: this is a first-load cost on a school
# connection, and the page states them.
import gzip

for rel, limit_mb in (("kagami/refs/reference_parts.fasta", 4.0),
                      ("kagami/refs/reference_parts.tsv", 4.0),
                      ("kagami/genomes/MG1655_ecoli_NC_000913.3.fna", 2.0)):
    path = os.path.join(ROOT, rel)
    if not os.path.isfile(path):
        check("%s exists" % rel, False, "missing")
        continue
    raw = open(path, "rb").read()
    gz_mb = len(gzip.compress(raw, 9)) / 1e6
    check("%s compresses to under %.1f MB (%.1f MB)" % (rel, limit_mb, gz_mb),
          gz_mb < limit_mb, "%.1f MB" % gz_mb)

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
