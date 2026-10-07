"""test_first_five_minutes.py — what happens to somebody who has never used this.

Run: python3 tests/test_first_five_minutes.py

Findings from an independent reviewer who unzipped the real bundle and walked the menu.
These are not polish. For a cohort where 0 of N got the previous version running, the
first five minutes is the whole product.

1. THE PROMPT TAUGHT AN ACTION IT COULD NOT READ. "Which file? (drag it onto this window,
   then press Return)" -- and macOS Terminal inserts a dragged path with spaces
   BACKSLASH-ESCAPED, not quoted. `_ask_and_run` stripped quotes and did no unescaping, so
   any file in a folder called "My Drive", "Google Drive" or "iGEM 2026" produced:

       > /Users/.../My\\ Drive/demo.gb
       ERROR: input not found: /Users/.../My\\ Drive/demo.gb

   One line, on stderr, no suggestion, and the function does not loop -- so they are back
   at the shell and must re-run ./katana and re-navigate the menu for each attempt. The
   most likely first-contact failure in the whole flow, caused by the instruction the
   prompt itself gives.

2. "BUILD A CONSTRUCT -- DESIGN SPEC -> ORDER-READY SEQUENCE" SILENTLY ADDED --dry-run.
   The run ended "-- Dry run - no output files --". No sequence, no file, and no line
   saying how to get one. The menu promised the opposite of what it delivered.

3. NOTHING TO PRESS. The first and most prominent menu entry is "Check a sequence --
   someone sent me a file; is the label true?" and a student who just unzipped this has no
   such file. `kagami/examples/demo.gb` -- 843 bp with a planted B0032 mislabel, the
   README's own worked example -- ships in the bundle and is tracked in git. The
   reviewer's claim that it does not ship was wrong. But it is in no menu entry and in no
   help text, so nobody knows it is there, which comes to the same thing.

4. `--help` LISTED 6 OF 12 COMMANDS. init, find, design, genome, bundle and deploy all
   work and four are documented in the README, and none of them appeared.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import ui_menu

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  [" + str(detail)[:300] + "]") if detail else ""))


import io


def menu(keys):
    """Drive the menu headlessly. Returns (exit code, everything it printed)."""
    out = io.StringIO()
    rc = ui_menu.run([], stdin=io.StringIO("".join(k + "\n" for k in keys)),
                     stdout=out)
    return rc, out.getvalue()


print("the first five minutes")

# ---- 1. a dragged path must be readable ----
D = tempfile.mkdtemp(prefix="drag_")
SPACED = os.path.join(D, "My Drive")
os.makedirs(SPACED)
TARGET = os.path.join(SPACED, "demo.gb")
import shutil

shutil.copyfile(os.path.join(ROOT, "kagami", "examples", "demo.gb"), TARGET)

ESCAPED = TARGET.replace(" ", "\\ ")
rc, out = menu(["1", ESCAPED])
check("a backslash-escaped path, exactly as macOS drag-and-drop produces it, is read",
      "input not found" not in out, [l for l in out.splitlines()
                                     if "not found" in l][:1])
check("and the audit actually runs on it", "identity-mislabel" in out or rc == 5,
      "rc %s | %s" % (rc, out[-200:]))

# A quoted path must keep working, and a plain one.
rc, out = menu(["1", '"%s"' % TARGET])
check("a quoted path still works", "input not found" not in out,
      [l for l in out.splitlines() if "not found" in l][:1])
rc, out = menu(["1", TARGET])
check("and a plain path with real spaces still works", "input not found" not in out,
      [l for l in out.splitlines() if "not found" in l][:1])

# Some apps drop a file:// URL.
rc, out = menu(["1", "file://" + TARGET.replace(" ", "%20")])
check("a file:// URL is read too", "input not found" not in out,
      [l for l in out.splitlines() if "not found" in l][:1])

# ---- and a wrong path must not dump them back at the shell ----
rc, out = menu(["1", os.path.join(D, "nope.gb"), TARGET])
check("a path that is wrong gets a second try instead of exiting",
      "input not found" not in out.split("try again")[-1]
      if "try again" in out.lower() else False,
      out[-300:])
check("and the retry prompt says what went wrong",
      "could not" in out.lower() or "no file" in out.lower(), out[-250:])

# ---- 2. the menu must do what its entry says ----
_src = open(os.path.join(ROOT, "ui_menu.py"), encoding="utf-8").read()
check("the menu's build entry does not silently add --dry-run",
      '"--dry-run"' not in _src.split("prompts = ")[1].split("}")[0],
      _src.split("prompts = ")[1].split("}")[0])

_spec = os.path.join(ROOT, "specs", "pSense-Nit.spec.yaml")
rc, out = menu(["2", _spec])
check("choosing Build writes the order files it promised",
      "Dry run" not in out, [l for l in out.splitlines() if "Dry run" in l][:1])
check("and says where they went", "outputs" in out or ".csv" in out, out[-300:])

# ---- 3. there must be something to press ----
check("the bundled example exists",
      os.path.isfile(os.path.join(ROOT, "kagami", "examples", "demo.gb")))
import make_bundle

check("and it ships in the bundle",
      "kagami/examples/demo.gb" in make_bundle.manifest())
rc, out = menu(["1", ""])
check("pressing Return at the file prompt offers the bundled example",
      "demo" in out.lower(), out[-400:])
check("and running it finds the planted mislabel, so the first try shows the point",
      "identity-mislabel" in out or "B0032" in out, out[-500:])

# ---- 4. help must list what exists ----
rc, out = menu([])
_help = subprocess.run([sys.executable, "ui_menu.py", "--help"], cwd=ROOT,
                       capture_output=True, text=True).stdout
_dispatched = set(re.findall(r'if name == "(\w+)"', _src)) | \
    set(re.findall(r'if name in \(([^)]*)\)', _src)[0].replace('"', "").split(", ")
        if re.findall(r'if name in \(([^)]*)\)', _src) else [])
_listed = set(re.findall(r'^\s*\("(\w+)"', _src, re.M))
_missing = sorted(n for n in _dispatched if n and n not in _help)
check("every command the front door dispatches appears in --help (%s)"
      % (", ".join(_missing) or "all of them"), not _missing)

shutil.rmtree(D, ignore_errors=True)

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
