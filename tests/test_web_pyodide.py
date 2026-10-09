"""test_web_pyodide.py — the browser path, in a real WebAssembly Python.

Run: python3 tests/test_web_pyodide.py
Needs: node, and `npm install pyodide@0.26.4` somewhere node can resolve.

tests/test_web.py runs the page's Python block on CPython. That proves the call
signatures but not that the modules work compiled to WebAssembly -- a module-level
`import subprocess`, a C extension, a filesystem assumption or a memory ceiling would all
pass there and fail in a browser.

So this loads the same module list index.js loads, into a real Pyodide, and runs the
audit block extracted from index.js verbatim. Measured on this machine: Pyodide up in
0.7 s, 18,255 reference parts loaded in 1.6 s, the demo audited in 5.8 s.

Where pyodide is not installed this suite says it measured nothing, rather than passing
silently -- a green line that checked nothing is worse than a missing one.
"""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

print("the browser path, under WebAssembly")

node = shutil.which("node")
if not node:
    print("  ---- no node on this machine: THIS CHECK MEASURED NOTHING.")
    print("\n0 passed, 0 failed")
    sys.exit(0)

env = dict(os.environ)
# Let a pyodide installed in a scratch directory be found, so this does not require
# adding a node_modules tree to the repository.
# ESM does not honour NODE_PATH, so the harness takes an explicit module path. If the
# caller did not supply one, look where this project's own scratch install would be.
if not env.get("KATANA_PYODIDE"):
    for cand in (os.path.join(HERE, "node_modules", "pyodide", "pyodide.mjs"),
                 os.path.join(os.path.dirname(HERE), "node_modules", "pyodide",
                              "pyodide.mjs")):
        if os.path.isfile(cand):
            env["KATANA_PYODIDE"] = cand
            break

p = subprocess.run([node, os.path.join(HERE, "web_pyodide_harness.mjs")],
                   capture_output=True, text=True, timeout=900, env=env)

out = p.stdout.strip()
if not out:
    print("  FAIL the harness produced no output")
    print("       " + (p.stderr.strip().splitlines() or [""])[-1][:300])
    print("\n0 passed, 1 failed")
    sys.exit(1)

data = json.loads(out)

if isinstance(data, dict) and "unavailable" in data:
    # The variable this names has to be the one that is read. It used to say NODE_PATH
    # or KATANA_NODE_PATH, neither of which this file looks at -- ESM does not honour
    # NODE_PATH, which is why the harness takes an explicit path instead. Following the
    # instruction left the suite still measuring nothing, with the same green zero.
    print("  ---- pyodide is not installed for node: THIS CHECK MEASURED NOTHING.")
    print("       Install it with:  npm install pyodide@0.26.4")
    print("       then either run it from a directory where tests/node_modules/pyodide")
    print("       exists, or point KATANA_PYODIDE at the installed pyodide.mjs:")
    print("         KATANA_PYODIDE=/path/to/node_modules/pyodide/pyodide.mjs \\")
    print("           python3 tests/test_web_pyodide.py")
    print("\n0 passed, 0 failed")
    sys.exit(0)

npass = nfail = 0
for r in data:
    if r["ok"]:
        npass += 1
        print("  ok   " + r["name"])
    else:
        nfail += 1
        print("  FAIL " + r["name"] + (("  [" + r["detail"][:250] + "]")
                                       if r["detail"] else ""))

print("\n%d passed, %d failed" % (npass, nfail))
sys.exit(1 if nfail else 0)
