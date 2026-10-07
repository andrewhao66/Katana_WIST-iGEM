"""test_py39.py — the README promises Python 3.9, so check it on Python 3.9.

Run: python3 tests/test_py39.py

Found by unzipping the bundle and running it with a restricted PATH, which picked up the
Python 3.9 that macOS ships with the Xcode command line tools. `katana_build.py` had one
`str | None` annotation -- a Python 3.10+ construct, evaluated at runtime -- so the
engine crashed on import with "unsupported operand type(s) for |". The README said 3.9+
and the floor was really 3.10, and nothing noticed because the development interpreter
is 3.13.

This suite runs the real thing on a real old interpreter when one is present. Where it
is not, it falls back to a syntax-level scan, which catches the same class of mistake
without needing the interpreter -- so it is useful on every machine rather than only on
a Mac.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# The floor the README promises. Raising it is a decision to make deliberately, in the
# README and here together.
FLOOR = (3, 9)

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  [" + str(detail)[:300] + "]") if detail else ""))


def tracked_py():
    out = subprocess.check_output(["git", "ls-files", "*.py"], cwd=ROOT, text=True)
    return [f for f in out.split() if not f.startswith("_vendor/")]


def find_old_interpreter():
    """A Python at or near the floor, if this machine has one."""
    candidates = ["/usr/bin/python3", "python3.9", "python3.10",
                  "/usr/local/bin/python3.9", "/opt/homebrew/bin/python3.9"]
    for cand in candidates:
        try:
            out = subprocess.check_output(
                [cand, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
                text=True, stderr=subprocess.DEVNULL).strip()
        except Exception:
            continue
        major, minor = (int(x) for x in out.split("."))
        if (major, minor) < (3, 11):
            return cand, (major, minor)
    return None, None


print("Python %d.%d floor" % FLOOR)

# ---- the README must promise what the code supports ----
readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
check("the README names the floor it promises",
      "3.9" in readme, "no 3.9 in README")

# ---- a runtime union annotation is a 3.10+ construct ----
# Only a problem where annotations are EVALUATED. A module with
# `from __future__ import annotations` stores them as strings and is fine.
UNION = re.compile(
    r'(?:def\s+\w+\([^)]*|->\s*|:\s*)'
    r'[\w\[\], .]*\b(?:str|int|bool|float|bytes|Path|dict|list|tuple|set)\s*\|')
offenders = []
for rel in tracked_py():
    src = open(os.path.join(ROOT, rel), encoding="utf-8").read()
    if "from __future__ import annotations" in src:
        continue
    for n, line in enumerate(src.splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        if UNION.search(line):
            offenders.append("%s:%d" % (rel, n))
check("no module evaluates an X | Y annotation without __future__ annotations (%s)"
      % (", ".join(offenders) or "clean"), not offenders)

# ---- and run the real thing on a real old interpreter, when there is one ----
old, ver = find_old_interpreter()
if old is None:
    print("  ---- no interpreter below 3.11 on this machine; the scan above is the check")
else:
    print("  ---- using %s (Python %d.%d)" % (old, ver[0], ver[1]))
    # Importing every module is the cheap, broad check: a syntax or annotation error
    # anywhere surfaces here rather than when a student runs that one command.
    mods = [("katana_build", ROOT), ("katana_lock", ROOT), ("add_part", ROOT),
            ("find_part", ROOT), ("check_design", ROOT), ("katana_init", ROOT),
            ("katana_drylab", ROOT), ("katana_sbol", ROOT),
            ("katana_order_table", ROOT), ("verify_library_v2", ROOT),
            ("ui_menu", ROOT), ("web_serve", ROOT), ("web_deploy", ROOT),
            ("make_bundle", ROOT),
            ("core.hashing", ROOT), ("core.lock", ROOT), ("core.parts", ROOT),
            ("core.result", ROOT),
            ("kg_parse", os.path.join(ROOT, "kagami")),
            ("kg_refs", os.path.join(ROOT, "kagami")),
            ("kg_seedmatch", os.path.join(ROOT, "kagami")),
            ("kg_identify", os.path.join(ROOT, "kagami")),
            ("kg_audit", os.path.join(ROOT, "kagami")),
            ("kg_bridge", os.path.join(ROOT, "kagami")),
            ("kg_verdict", os.path.join(ROOT, "kagami")),
            ("kg_rebuild", os.path.join(ROOT, "kagami")),
            ("kagami", os.path.join(ROOT, "kagami"))]
    broke = []
    for mod, cwd in mods:
        p = subprocess.run(
            [old, "-c", "import sys; sys.path.insert(0, %r); sys.path.insert(0, %r);"
                        " import %s" % (ROOT, cwd, mod)],
            cwd=cwd, capture_output=True, text=True)
        if p.returncode != 0:
            broke.append("%s: %s" % (mod, (p.stderr.strip().splitlines() or [""])[-1]))
    check("every module imports on Python %d.%d (%s)"
          % (ver[0], ver[1], ", ".join(broke) or "all import"), not broke)

    # And the engine actually BUILDS, which is what a student does first.
    p = subprocess.run([old, "katana_build.py",
                        "specs/pSense-Nit.spec.yaml", "--dry-run"],
                       cwd=ROOT, capture_output=True, text=True)
    check("a construct builds on Python %d.%d" % ver, p.returncode == 0,
          (p.stdout + p.stderr)[-250:])
    check("and it reproduces the sealed hash",
          "796e94a0ea2452edd2ce59ca30b8f28fea232b37ab2a036714239069fd1196f5"
          in p.stdout, p.stdout[-200:])

    # And an audit runs, which is what the other kind of student does first.
    p = subprocess.run([old, "kagami.py", "audit", "examples/demo.gb"],
                       cwd=os.path.join(ROOT, "kagami"),
                       capture_output=True, text=True)
    check("an audit runs on Python %d.%d" % ver, p.returncode in (0, 5),
          (p.stdout + p.stderr)[-250:])
    check("and it still catches the planted mislabel",
          "identity-mislabel" in p.stdout, p.stdout[-200:])

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
