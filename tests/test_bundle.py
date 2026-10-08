"""test_bundle.py — the zip a person downloads, unzipped and run.

Run: python3 tests/test_bundle.py

This is the only suite that tests what a person actually receives. Everything else
tests the working tree, which has files the bundle does not ship and a PATH the bundle's
user does not have.

It builds the zip, extracts it into a temporary directory, and runs the three things
somebody does first -- verify, build, check -- with PATH cut back to the system
directories so no installed package and no blastn can be reached. If this suite passes,
"unzip it and run ./katana" is a true statement.

It found a real defect the first time it ran: a `str | None` annotation in
katana_build.py, a Python 3.10+ construct, crashed the engine on import on the Python 3.9
that macOS ships. See tests/test_py39.py, which now pins that separately.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import make_bundle

# Only the system directories. No Homebrew, no pyenv, no user site -- the PATH a
# borrowed school laptop has.
BARE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  [" + str(detail)[:300] + "]") if detail else ""))


print("the downloadable bundle")

check("every file the bundle lists is present", make_bundle.missing() == [],
      str(make_bundle.missing()))

_tmp = tempfile.mkdtemp(prefix="bundle_")
_zip = os.path.join(_tmp, "katana.zip")
_n, _raw, _packed = make_bundle.build(_zip)

check("the zip builds (%d files, %.1f MB)" % (_n, _packed / 1e6), _n > 80)
check("and is small enough to download on a school connection -- %.1f MB"
      % (_packed / 1e6), _packed < 25e6, "%.1f MB" % (_packed / 1e6))

# Building the same tree twice must give the same bytes, so whoever publishes a release
# can state its checksum and whoever downloads it can check.
_zip2 = os.path.join(_tmp, "katana2.zip")
make_bundle.build(_zip2)
with open(_zip, "rb") as f1, open(_zip2, "rb") as f2:
    check("building twice gives byte-identical zips, so a release can be checksummed",
          f1.read() == f2.read())

with zipfile.ZipFile(_zip) as z:
    names = z.namelist()
    _bad = [n for n in names if not n.startswith("katana/")]
    check("everything is under one top-level folder, so unzip cannot scatter files "
          "across someone's Downloads", not _bad, str(_bad[:4]))
    # Nothing machine-specific or private.
    for _pat in ("__pycache__", ".pyc", ".DS_Store", ".git/", ".superpowers",
                 "/outputs/", "_site/", ".so"):
        _hits = [n for n in names if _pat in n]
        check("the zip carries no %s" % _pat, not _hits, str(_hits[:3]))
    # And the launcher is executable, or ./katana fails with Permission denied.
    _info = z.getinfo("katana/katana")
    _mode = (_info.external_attr >> 16) & 0o777
    check("./katana is executable in the zip (mode %s)" % oct(_mode), _mode & 0o111,
          oct(_mode))

    _work = os.path.join(_tmp, "extracted")
    z.extractall(_work)

_app = os.path.join(_work, "katana")
# extractall does not honour the stored mode, which is why the stored mode is asserted
# above rather than tested through the extracted file.
os.chmod(os.path.join(_app, "katana"), 0o755)

_env = dict(os.environ)
_env["PATH"] = BARE_PATH
_env.pop("PYTHONPATH", None)


def run(args, cwd=None, timeout=600):
    return subprocess.run(args, cwd=cwd or _app, env=_env, capture_output=True,
                          text=True, timeout=timeout)


# Nothing is installed in the environment these run in. Assert that, rather than
# assuming it -- a check that measured nothing must say so.
_probe = run(["/usr/bin/python3", "-c",
              "import shutil\n"
              "print('blastn' if shutil.which('blastn') else 'no-blastn')\n"
              "try:\n"
              "    import yaml; print('yaml')\n"
              "except ImportError:\n"
              "    print('no-yaml')\n"])
check("the test environment really has no blastn and no PyYAML (%s)"
      % _probe.stdout.replace("\n", " ").strip(),
      "no-blastn" in _probe.stdout and "no-yaml" in _probe.stdout, _probe.stdout)

_p = run(["./katana", "--help"])
check("./katana --help runs from the unzipped folder", _p.returncode == 0,
      (_p.stdout + _p.stderr)[-250:])
check("and it leads with the front door", "katana check" in _p.stdout,
      _p.stdout[:160])

_p = run(["./katana", "verify"])
check("./katana verify runs with nothing installed", _p.returncode == 0,
      (_p.stdout + _p.stderr)[-300:])
check("and reports the library intact and the checker working",
      "8/8 checks passed" in _p.stdout, _p.stdout[-250:])

_p = run(["./katana", "build", "specs/pSense-Nit.spec.yaml", "--dry-run"])
# Exit 5 is REVIEW, not a failure, and it is the honest answer for this spec: the
# off-target gate now finds the genome the bundle ships, and reports 80 bp matches at
# 100% identity to the host genome away from any expected locus. It used to exit 0
# because that gate never ran at all.
check("./katana build runs with nothing installed", _p.returncode in (0, 5),
      (_p.stdout + _p.stderr)[-300:])
check("and the off-target gate RAN, rather than skipping for a missing genome",
      "OFF-TARGET SKIPPED" not in (_p.stdout + _p.stderr),
      [l.strip() for l in (_p.stdout + _p.stderr).splitlines()
       if "OFF-TARGET" in l][:2])
check("and reproduces the sealed construct hash",
      "796e94a0ea2452edd2ce59ca30b8f28fea232b37ab2a036714239069fd1196f5" in _p.stdout,
      _p.stdout[-250:])

_p = run(["./katana", "check", "kagami/examples/demo.gb"])
check("./katana check runs with nothing installed", _p.returncode in (0, 5),
      (_p.stdout + _p.stderr)[-300:])
check("and still catches the planted mislabel without blastn",
      "identity-mislabel" in _p.stdout, _p.stdout[-250:])
check("and exits 5, so a script can tell REVIEW from PASS", _p.returncode == 5,
      str(_p.returncode))

# The bundled parts library must survive the round trip through zip byte for byte. The
# first public clone of this repository reported itself as tampered because git
# converted line endings on checkout; a zip that rewrites a byte does the same thing.
_lock_src = os.path.join(ROOT, "parts-library", "ref_parts", "LOCK.tsv")
_lock_out = os.path.join(_app, "parts-library", "ref_parts", "LOCK.tsv")
if os.path.isfile(_lock_src):
    with open(_lock_src, "rb") as f1, open(_lock_out, "rb") as f2:
        check("LOCK.tsv survives the zip byte for byte", f1.read() == f2.read())

# ---- the zip must carry nothing platform-specific ----
# This is what makes "any machine with Python 3.9" true: there is no architecture to
# match, because there is nothing compiled in it. The vendored PyYAML had its .so removed
# for exactly this reason.
with zipfile.ZipFile(_zip) as z:
    _compiled = [n for n in z.namelist()
                 if n.endswith((".so", ".dll", ".dylib", ".pyd", ".exe", ".o", ".a"))]
    check("the zip contains no compiled artifact (%s)"
          % (", ".join(_compiled[:3]) or "none"), not _compiled)
    _magic = {}
    for _n in z.namelist():
        if _n.endswith("/"):
            continue
        _h = z.open(_n).read(4)
        if _h[:4] in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe"):
            _magic.setdefault("Mach-O", []).append(_n)
        elif _h[:4] == b"\x7fELF":
            _magic.setdefault("ELF", []).append(_n)
        elif _h[:2] == b"MZ":
            _magic.setdefault("PE", []).append(_n)
    check("and no executable binary of any format (%s)"
          % (", ".join(_magic) or "none"), not _magic)

    # Each launcher keeps the line endings its own interpreter needs. A .bat with bare
    # LF misbehaves in cmd; a shell script with CRLF fails with "bad interpreter".
    _sh = z.read("katana/katana")
    _bat = z.read("katana/katana.bat")
    check("the POSIX launcher is LF-only",
          _sh.count(b"\r\n") == 0 and b"\n" in _sh,
          "CRLF %d" % _sh.count(b"\r\n"))
    check("and the Windows launcher is CRLF-only",
          _bat.count(b"\n") == _bat.count(b"\r\n"),
          "CRLF %d of %d LF" % (_bat.count(b"\r\n"), _bat.count(b"\n")))

# ---- and the instructions must cover the extractor that drops the mode ----
# Measured: `unzip` keeps mode 0755, Python's zipfile strips it, and Finder's Archive
# Utility is in the second camp. Then ./katana answers "Permission denied" and nothing
# says why. `bash katana` works whatever the permissions are -- verified above on a copy
# with the bit removed -- so the way out has to be written down where somebody will see it.
_readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
check("the README explains Permission denied", "Permission denied" in _readme)
check("and gives a way out that needs no chmod", "bash katana" in _readme)
_mb = open(os.path.join(ROOT, "make_bundle.py"), encoding="utf-8").read()
check("and `katana bundle` says the same to whoever ships it",
      "Permission denied" in _mb and "bash katana" in _mb)

# The fallback is a real path, not just a launcher that starts: run it with the bit off.
_noexec = os.path.join(_tmp, "noexec")
with zipfile.ZipFile(_zip) as z:
    z.extractall(_noexec)          # zipfile does NOT preserve the mode -- that is the point
_app2 = os.path.join(_noexec, "katana")
check("extracting with Python's zipfile really does drop the executable bit",
      not os.access(os.path.join(_app2, "katana"), os.X_OK))
_p = subprocess.run(["bash", "katana", "verify"], cwd=_app2, env=_env,
                    capture_output=True, text=True, timeout=600)
check("and `bash katana verify` works anyway", _p.returncode == 0,
      (_p.stdout + _p.stderr)[-250:])
check("and reports the library intact", "8/8 checks passed" in _p.stdout,
      _p.stdout[-200:])

shutil.rmtree(_tmp, ignore_errors=True)

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
