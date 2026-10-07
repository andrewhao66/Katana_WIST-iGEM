"""test_web.py — the browser front end, as far as a terminal can check it.

Run: python3 tests/test_web.py

What this CAN check, and does: the local server serves exactly the files the page asks
for and nothing else; the page's own Python block, extracted from index.js verbatim, runs
and produces the JSON shape the JavaScript reads; the module list the page loads matches
the one tests/test_web_importable.py pins; and the deploy manifest covers everything.

What it does not check, because other suites do: that the modules work compiled to
WebAssembly (tests/test_web_pyodide.py loads them into a real Pyodide) and that the
rendering is honest (tests/test_web_render.py calls render() under node). What nothing
here covers is pixels in a real Chrome, and that is stated rather than assumed.
"""
import json
import os
import shutil
import re
import sys
import tempfile
import threading
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "kagami"))

import web_serve

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  [" + str(detail)[:250] + "]") if detail else ""))


print("web front end")

# ---- the files the page needs are all here ----
check("every file the page needs is present", web_serve.missing_files() == [],
      str(web_serve.missing_files()))

# ---- the page's module list and the server's allow-list agree ----
js = open(os.path.join(ROOT, "ui", "web", "index.js"), encoding="utf-8").read()
js_modules = re.findall(r'"((?:core|kagami)/[\w./]+\.py)"', js)
served = set(web_serve.SERVE)
missing_from_server = [m for m in js_modules if m not in served]
check("every module the page fetches is served (%s)"
      % (", ".join(missing_from_server) or "all"), not missing_from_server)

# And the page's list matches what the importability suite actually pins, so a module
# added in one place cannot be forgotten in the other.
imp = open(os.path.join(HERE, "test_web_importable.py"), encoding="utf-8").read()
pinned = re.findall(r'"((?:core\.[\w.]+|kg_\w+))"', imp)
pinned_files = set()
for name in pinned:
    pinned_files.add(name.replace(".", "/") + ".py" if name.startswith("core")
                     else "kagami/" + name + ".py")
page_files = set(js_modules) - {"core/__init__.py"}
check("the page loads exactly the modules the importability suite pins (%s)"
      % (", ".join(sorted(pinned_files ^ page_files)) or "same set"),
      pinned_files == page_files)

# ---- the server serves what it should and refuses the rest ----
port = 8799
srv_thread = threading.Thread(
    target=lambda: web_serve.serve(port=port, open_browser=False), daemon=True)
import io
_real_stdout = sys.stdout
sys.stdout = io.StringIO()
srv_thread.start()
import time
time.sleep(0.6)
sys.stdout = _real_stdout


def get(path):
    try:
        r = urllib.request.urlopen("http://127.0.0.1:%d/%s" % (port, path), timeout=10)
        return r.status, r.read(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        return exc.code, b"", ""
    except Exception as exc:
        return None, str(exc).encode(), ""


_st, _body, _ct = get("")
check("the server answers / with the page", _st == 200 and b"<html" in _body.lower(),
      str(_st))
check("and as text/html", "text/html" in _ct, _ct)

_st, _body, _ct = get("index.js")
check("it serves index.js at the root, where the page asks for it", _st == 200, str(_st))
check("and as javascript", "javascript" in _ct, _ct)

for rel in ("core/hashing.py", "core/result.py", "kagami/kg_audit.py",
            "kagami/kg_seedmatch.py", "kagami/refs/reference_parts.tsv"):
    _st, _body, _ = get(rel)
    check("it serves %s" % rel, _st == 200 and len(_body) > 100, str(_st))

# Only what the page needs. A convenience command must not expose whatever else is in
# the folder -- somebody's unpublished specs, their own library, their notes.
for rel in ("katana_build.py", "parts-library/ref_parts/LOCK.tsv", "CODE-REPORT.md",
            "specs/pAP-Logic.spec.yaml", "../../etc/passwd"):
    _st, _, _ = get(rel)
    check("it refuses %s" % rel, _st == 404, str(_st))

# ---- startup must be fast ----
# http.server's server_bind() calls socket.getfqdn(), a REVERSE DNS lookup on the bind
# address. On a resolver that is slow to answer for loopback -- a school network behind a
# captive portal, a laptop on a VPN -- that blocks for seconds before the socket starts
# answering, so the page appears to load and then fail. Measured here before the fix:
# the first four requests timed out and the fifth succeeded.
_t0 = time.time()
_srv_cls = web_serve._server_class()
_probe = _srv_cls(("127.0.0.1", 0), web_serve._handler_class())
_elapsed = time.time() - _t0
_probe.server_close()
check("binding the server takes under 0.5 s (no reverse DNS) -- %.3f s" % _elapsed,
      _elapsed < 0.5, "%.3f s" % _elapsed)

# ---- the page's own Python runs and returns the shape the JavaScript reads ----
_m = re.search(r"json = await pyodide\.runPythonAsync\(`\n(.*?)`\);", js, re.S)
check("index.js contains the audit block", _m is not None)
if _m:
    code = _m.group(1)
    import shutil

    _d = tempfile.mkdtemp(prefix="webtest_")
    _p = os.path.join(_d, "demo.gb")
    shutil.copyfile(os.path.join(ROOT, "kagami", "examples", "demo.gb"), _p)
    g = {"_in_path": _p, "_host_file": "", "_host_reca": None,
         "_assembly": None, "_vendor": "Twist", "_cap": 5000}
    lines = code.rstrip().split("\n")
    tail = next(i for i, l in enumerate(lines) if l.startswith("json.dumps("))
    _err = None
    try:
        exec("\n".join(lines[:tail]), g)
        report = json.loads(eval("\n".join(lines[tail:]), g))
    except Exception as exc:
        _err, report = "%s: %s" % (type(exc).__name__, exc), {}
    check("the page's Python block runs unmodified", _err is None, _err or "")

    for key in ("name", "length", "topology", "joined", "verdict", "kind",
                "identification_ran", "blocks", "findings"):
        check("its result carries %s, which the JavaScript reads" % key,
              key in report, ", ".join(sorted(report)))

    check("it reports the demo at 843 bp", report.get("length") == 843,
          str(report.get("length")))
    check("identification RAN -- no BLAST+ needed in a browser",
          report.get("identification_ran") is True)
    check("and the planted mislabel is caught",
          any(f["category"] == "identity-mislabel"
              for f in report.get("findings", [])))
    check("so the verdict is not PASS", report.get("kind") == "REVIEW",
          str(report.get("kind")))
    _blocks = report.get("blocks", [])
    check("blocks carry the fields the table renders",
          _blocks and all(k in _blocks[0] for k in
                          ("start", "end", "strand", "claim", "identity", "role",
                           "pident", "coverage", "note", "alternatives")),
          ", ".join(sorted(_blocks[0])) if _blocks else "none")
    shutil.rmtree(_d, ignore_errors=True)

# ---- the page says the two things it must ----
html = open(os.path.join(ROOT, "ui", "web", "index.html"), encoding="utf-8").read()
check("the page says nothing is uploaded", "Nothing is uploaded" in html)
check("the page says it does not seal, because a library must live in git",
      "does not seal" in html)
check("the loader explains the file:// restriction rather than failing silently",
      "file://" in js)

# ---- the deploy staging produces a site that is the engine, byte for byte ----
import hashlib

import web_deploy

_stage_dir = tempfile.mkdtemp(prefix="deploy_")
_files, _total = web_deploy.stage(_stage_dir)
check("staging produces the whole served set", len(_files) == len(web_serve.SERVE),
      "%d vs %d" % (len(_files), len(web_serve.SERVE)))
check("the page lands at the root, where GitHub Pages serves it",
      os.path.isfile(os.path.join(_stage_dir, "index.html"))
      and os.path.isfile(os.path.join(_stage_dir, "index.js")))
check("and .nojekyll is written, so Jekyll cannot skip an underscore path",
      os.path.isfile(os.path.join(_stage_dir, ".nojekyll")))


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# The published site must BE the engine, not a hand-assembled variant of it. That is the
# same rule this project applies to a construct, applied to a web page.
_drift = []
for _rel in ("core/hashing.py", "core/lock.py", "core/parts.py", "core/result.py",
             "kagami/kg_audit.py", "kagami/kg_seedmatch.py", "kagami/kg_identify.py",
             "kagami/kg_parse.py", "kagami/kg_refs.py", "kagami/kg_bridge.py"):
    if _sha(os.path.join(_stage_dir, _rel)) != _sha(os.path.join(ROOT, _rel)):
        _drift.append(_rel)
check("every published module is byte-identical to the bundle's (%s)"
      % (", ".join(_drift) or "all identical"), not _drift)

# And nothing that is not the page's business goes out with it.
for _bad in ("parts-library", "specs", "CODE-REPORT.md", "katana_build.py",
             "_vendor", "docs", ".superpowers"):
    check("staging does not publish %s" % _bad,
          not os.path.exists(os.path.join(_stage_dir, _bad)))

check("staging reports a first-load size the page's README can state",
      1e7 < _total < 1e8, "%.1f MB" % (_total / 1e6))
check("the deploy default remote is the separate GitHub repo, never the iGEM GitLab",
      "github.com/andrewhao66/iGEM-katana-webtest" in web_deploy.DEFAULT_REMOTE
      and "gitlab" not in web_deploy.DEFAULT_REMOTE.lower(),
      web_deploy.DEFAULT_REMOTE)

_deploy_src = open(os.path.join(ROOT, "web_deploy.py"), encoding="utf-8").read()
check("deploy stages by default and only publishes with --push",
      'if not do_push:' in _deploy_src and 'Nothing was published' in _deploy_src)

shutil.rmtree(_stage_dir, ignore_errors=True)

print()
print("  Covered elsewhere: tests/test_web_pyodide.py runs these same modules in a real")
print("  Pyodide, and tests/test_web_render.py calls the page's render() for real. What")
print("  no suite here covers is pixels in Chrome.")
print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
