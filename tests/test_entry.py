"""test_entry.py — the single entry point. Run: python3 tests/test_entry.py"""
import io
import os
import subprocess
import sys

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
        print("  FAIL " + name + (("  [" + str(detail)[:200] + "]") if detail else ""))


def run(argv, stdin_text=""):
    out = io.StringIO()
    rc = ui_menu.run(argv, stdin=io.StringIO(stdin_text), stdout=out)
    return rc, out.getvalue()


print("entry point")

# ---- subcommands ----
_rc, _out = run(["--help"])
check("--help lists the subcommands", "check" in _out and "build" in _out, _out[:200])
check("and exits 0", _rc == 0, str(_rc))
check("--help says nothing needs installing", "Nothing needs installing" in _out)

_rc, _out = run(["verify"])
check("`verify` runs the library check",
      "checks passed" in _out or "parts verified" in _out, _out[-200:])
check("and exits 0 on a sealed library", _rc == 0, str(_rc))

_rc, _out = run(["build", os.path.join(ROOT, "specs", "pSense-Nit.spec.yaml"),
                 "--dry-run"])
check("`build` builds a Spec", "796e94a0ea2452ed" in _out, _out[-300:])

# kagami's modules import each other as siblings, so running them from the repository
# root needs their own directory on sys.path. Without it this was ModuleNotFoundError.
_rc, _out = run(["check", os.path.join(ROOT, "kagami", "examples", "demo.gb")])
check("`check` audits a sequence", "KAGAMI" in _out, _out[:200])
check("and catches the demo's planted mislabel", "identity-mislabel" in _out,
      _out[-300:])
check("and exits 5 for REVIEW, not 0", _rc == 5, str(_rc))

_rc, _out = run(["nonsense"])
check("an unknown subcommand is refused, not guessed", _rc != 0, str(_rc))
check("and the refusal lists what IS available", "katana check" in _out, _out[:200])

# ---- the menu ----
_rc, _out = run([], stdin_text="3\n")
check("no arguments opens the menu", "what do you want to do" in _out.lower(),
      _out[:200])
check("the menu numbers its choices", "1)" in _out and "5)" in _out, _out[:400])
check("choosing 3 runs the library check",
      "checks passed" in _out or "parts verified" in _out, _out[-200:])

_rc, _out = run([], stdin_text="\n")
check("an empty choice leaves without doing anything", "nothing was done" in _out.lower(),
      _out[-200:])
check("and exits 0, because leaving is not an error", _rc == 0, str(_rc))

_rc, _out = run([], stdin_text="9\n")
check("an out-of-range choice says so rather than crashing",
      "not one of the numbers" in _out.lower(), _out[-200:])
check("and exits non-zero", _rc != 0, str(_rc))

_rc, _out = run([], stdin_text="1\n")
check("choosing 'check' then giving nothing does nothing",
      "nothing given" in _out.lower(), _out[-200:])

_rc, _out = run([], stdin_text="1\n%s\n"
                % os.path.join(ROOT, "kagami", "examples", "demo.gb"))
check("choosing 'check' and naming a file audits it", "KAGAMI" in _out, _out[-300:])


# Review Focus 1: no TTY. A double-click, a CI step or a pipe gives no input at all.
# input()/readline() raises EOFError, and the menu must print how to use the subcommands
# rather than a traceback.
class _NoInput(io.StringIO):
    def readline(self, *a):
        raise EOFError("no tty")


_out2 = io.StringIO()
_raised = None
try:
    _rc2 = ui_menu.run([], stdin=_NoInput(), stdout=_out2)
except Exception as exc:
    _rc2, _raised = None, "%s: %s" % (type(exc).__name__, exc)
check("no TTY does not raise", _raised is None, _raised or "")
check("and it exits 0 rather than failing", _rc2 == 0, str(_rc2))
check("and it tells the reader how to run it non-interactively",
      "katana check" in _out2.getvalue(), _out2.getvalue()[-300:])

# Review Focus 2: the menu offers the window. Where tkinter is absent -- common on a
# minimal Linux -- it must say so and stay usable, not crash.
_real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) \
    else __builtins__.__import__


def _no_tkinter(name, *a, **k):
    if name == "tkinter":
        raise ImportError("no tkinter here")
    return _real_import(name, *a, **k)


if isinstance(__builtins__, dict):
    __builtins__["__import__"] = _no_tkinter
else:
    __builtins__.__import__ = _no_tkinter
try:
    _out3 = io.StringIO()
    _rc3 = ui_menu.run(["gui"], stdin=io.StringIO(""), stdout=_out3)
    _g = _out3.getvalue()
finally:
    if isinstance(__builtins__, dict):
        __builtins__["__import__"] = _real_import
    else:
        __builtins__.__import__ = _real_import
check("without tkinter, `gui` explains rather than crashing", _rc3 == 0, str(_rc3))
check("and says nothing is wrong", "Nothing is wrong" in _g, _g[:200])
check("and gives the command-line equivalent", "katana check" in _g, _g[:300])
check("and says how to get the window", "python3-tk" in _g, _g[:300])

# ---- the launcher scripts themselves ----
_launcher = os.path.join(ROOT, "katana")
check("the katana launcher exists", os.path.isfile(_launcher))
check("and is executable", os.access(_launcher, os.X_OK))
_p = subprocess.run(["bash", "-n", _launcher], capture_output=True, text=True)
check("and is valid shell", _p.returncode == 0, _p.stderr[:200])
_src = open(_launcher, encoding="utf-8").read()
check("it looks for python3 before python",
      _src.index("python3") < _src.index("python ") if "python " in _src else True)
check("it says to run it from Terminal on a Mac, not to double-click",
      "RUN THIS FROM TERMINAL" in _src.upper())

_bat = os.path.join(ROOT, "katana.bat")
check("the Windows launcher exists", os.path.isfile(_bat))
_bsrc = open(_bat, "rb").read()
check("and is CRLF, which cmd.exe needs for GOTO to resume on the right line",
      b"\r\n" in _bsrc)
# The property, not the spelling: `py` is tried before bare `python`, because bare
# python on Windows is the Store placeholder when Python is not properly installed.
# (This used to grep for the literal "py.exe", which stopped matching when the launcher
# started probing interpreters instead of asking `where` about them.)
check("and prefers the py launcher over bare python",
      b"py -c" in _bsrc and _bsrc.index(b"py -c") < _bsrc.index(b"python -c"))

# No HTML entities. The first error message a Windows user could meet read
# "Katana&apos;s own files are not in this folder" -- an escaped apostrophe that reached
# a batch file, where there is no HTML to escape it for. It is the kind of thing nobody
# reads twice, and nobody on this team runs Windows to notice.
_entities = [e for e in (b"&apos;", b"&quot;", b"&amp;", b"&lt;", b"&gt;", b"&#")
             if e in _bsrc]
check("the Windows launcher has no HTML entities in its text (%s)"
      % (b", ".join(_entities).decode() or "none"), not _entities)

# It must hand the tool's exit code back. The whole verdict model rests on it: 0 means
# PASS, 5 means REVIEW, 1 means FAIL. cmd usually preserves ERRORLEVEL across goto and
# endlocal, but a wrapper that loses it turns every verdict into success for anything
# that checks -- and "usually" is not something to rest a verdict on.
check("it hands the tool's exit code back explicitly",
      b"exit /b %RC%" in _bsrc and b"set RC=%ERRORLEVEL%" in _bsrc)

# ASCII only. A batch file is read in the console's code page, and a stray non-ASCII byte
# in cp950 or cp1252 renders as mojibake in the one message somebody needs to read.
_high = sorted({x for x in _bsrc if x > 127})
check("and it is pure ASCII, so no code page can mangle it (%s)"
      % (", ".join(hex(x) for x in _high) or "ascii"), not _high)

# The POSIX launcher, for the same reasons.
_ssrc = open(os.path.join(ROOT, "katana"), "rb").read()
check("the POSIX launcher has no HTML entities",
      not any(e in _ssrc for e in (b"&apos;", b"&quot;", b"&#")))
check("it execs rather than forking, so the exit code is the tool's own",
      b"exec " in _ssrc)
# `python` is Python 2 on an older Mac and a Store placeholder on Windows, so bare
# `python` must be the LAST candidate, never the first.
_cands = _ssrc.decode().split("for c in ", 1)[1].split(";")[0].split()
check("the interpreter search tries python3 first and bare python last (%s)"
      % " ".join(_cands), _cands and _cands[0] == "python3" and _cands[-1] == "python",
      " ".join(_cands))

# ---- Windows: the two things that make it unusable there ----
# NOT VERIFIED ON WINDOWS. Nobody on this team runs it, and this session has no Windows
# machine, so these pin the SHAPE of the launcher rather than its behaviour. That is
# weaker than a run, and it is said here rather than left to be assumed.
#
# 1. A double-clicked window closed as soon as the report finished. `pause` was only on
#    the two error paths, so the one case that WORKED was the one you could not read --
#    and double-clicking is how somebody who is not comfortable with a terminal runs it.
check("the Windows launcher detects a double-click", b"cmdcmdline" in _bsrc)
check("and holds the window open only in that case",
      b"KATANA_HOLD" in _bsrc and b"if defined KATANA_HOLD" in _bsrc)
check("so a terminal run does not wait for a keypress -- `pause` is inside the guard",
      _bsrc.count(b"pause") >= 2
      and _bsrc.index(b"if defined KATANA_HOLD") < _bsrc.rindex(b"pause"))

# 2. Windows ships a PLACEHOLDER python.exe -- an App Execution Alias that opens the
#    Microsoft Store -- and `where python.exe` finds it. The launcher used `where`, so a
#    student with the placeholder and no real Python got a Store page, no explanation,
#    and a script that carried on as though Python had run.
check("it PROBES each interpreter instead of trusting `where`",
      b'-c "import sys"' in _bsrc)
check("and no longer decides on `where` alone", b"where /q" not in _bsrc)
check("and it tries py first, which is the real launcher when Python is installed",
      _bsrc.index(b"py -c") < _bsrc.index(b"python3 -c")
      < _bsrc.index(b"python -c"))
check("and its not-found message names the Store placeholder, since that is what the "
      "student will have seen", b"placeholder" in _bsrc)

# The version floor is checked in Python, where it can be said clearly, not in the .bat.
_menu = open(os.path.join(ROOT, "ui_menu.py"), encoding="utf-8").read()
check("the front door refuses an interpreter below the promised floor",
      "sys.version_info < (3, 9)" in _menu)
check("and its message says which version was found",
      "This is Python %d.%d" in _menu)
check("and the guard runs before anything that could need a newer Python",
      _menu.index("sys.version_info < (3, 9)") < _menu.index("def "))

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
