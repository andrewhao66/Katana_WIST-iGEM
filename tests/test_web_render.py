"""test_web_render.py — the page's rendering, run for real.

Run: python3 tests/test_web_render.py

The rendering path decides what colour a verdict gets and what glyph a finding gets.
Those are the two places where "we did not check" could come out looking like "checked
and fine", which is the single thing this project exists to prevent -- so they are tested
against the real JavaScript rather than by reading it.

tests/web_render_harness.js stubs enough DOM for ui/web/index.js to load, then calls
render() with crafted reports. This file runs it and reports.

Needs node. Where there is no node this suite says it measured nothing, rather than
passing silently -- a green line that checked nothing is worse than a missing one.
"""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

print("the page's rendering")

node = shutil.which("node")
if not node:
    print("  ---- no node on this machine: THIS CHECK MEASURED NOTHING.")
    print("       The verdict colour and the SKIP glyph are unverified here.")
    print("\n0 passed, 0 failed")
    sys.exit(0)

p = subprocess.run([node, os.path.join(HERE, "web_render_harness.js")],
                   capture_output=True, text=True, timeout=120)
if p.returncode != 0:
    print("  FAIL the harness did not run")
    print("       " + (p.stderr.strip().splitlines() or [""])[-1][:300])
    print("\n0 passed, 1 failed")
    sys.exit(1)

results = json.loads(p.stdout)
npass = nfail = 0
for r in results:
    if r["ok"]:
        npass += 1
        print("  ok   " + r["name"])
    else:
        nfail += 1
        print("  FAIL " + r["name"] + (("  [" + r["detail"][:220] + "]")
                                       if r["detail"] else ""))

print("\n%d passed, %d failed" % (npass, nfail))
sys.exit(1 if nfail else 0)
