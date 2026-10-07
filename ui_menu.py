#!/usr/bin/env python3
"""ui_menu.py — the one front door.

Why this exists. There were thirteen Python entry points and four launchers, and the
root README mentioned neither the auditor nor the window. A reader was asked to choose
between them before knowing what any of them did, and the first command in the README
failed on macOS because it said `python` rather than `python3`. Not one member of this
team got through it.

So: one command. `katana` with a subcommand for people who know what they want, and with
no arguments a menu that asks one question at a time. The flags across the underlying
tools all still work and are passed straight through; nobody has to meet them.

`run()` takes stdin and stdout so the menu can be tested without a terminal, which is
also what makes the no-TTY case -- a double-click, a pipe, a CI step -- something the
tests pin rather than something a user discovers.
"""
import os
import re
import sys


# The floor the README promises, checked in Python rather than in the launchers. A .bat
# file cannot say this clearly and a shell script would have to parse a version string;
# here it is three lines. It runs before anything else imports, because a 3.9-only
# message is useless if the interpreter has already failed on newer syntax elsewhere.
if sys.version_info < (3, 9):
    sys.stderr.write(
        "\n  Katana needs Python 3.9 or newer. This is Python %d.%d.\n\n"
        "  macOS:          install from https://www.python.org/downloads/\n"
        "  Windows:        install from https://www.python.org/downloads/ and tick\n"
        "                  \"Add python.exe to PATH\" in the installer\n"
        "  Debian/Ubuntu:  sudo apt install python3 python3-tk\n\n"
        % sys.version_info[:2])
    raise SystemExit(2)

HERE = os.path.dirname(os.path.abspath(__file__))

COMMANDS = [
    ("check", "Check a sequence", "someone sent me a file; is the label true?"),
    ("build", "Build a construct", "Design Spec -> order-ready sequence"),
    ("verify", "Check the parts library",
     "re-hash everything, then try to break the checker"),
    ("add", "Add a part to my library", "from NCBI, the iGEM Registry, or a file"),
    ("gui", "Open the window", "the same things, with buttons"),
    ("web", "Open it in a browser", "the sequence check, with nothing to install"),
]


def _print(out, text=""):
    out.write(text + "\n")


# Everything else the front door dispatches. Deliberately NOT in the numbered menu: six
# entries is a menu somebody reads, twelve is a wall, and these are the ones you go
# looking for rather than stumble into. But --help listed only the six, so init, find,
# design, genome, bundle and deploy were invisible -- four of them documented in the
# README and all of them working.
MORE_COMMANDS = [
    ("init", "start a parts library of your own"),
    ("find", "look up a part, in your library or on NCBI"),
    ("design", "check a Design Spec without building it"),
    ("genome", "fetch a host genome for the off-target check"),
    ("bundle", "write the zip you hand to someone else"),
    ("deploy", "stage the browser version as a static site"),
]


def _usage(out):
    _print(out, "Katana - build DNA constructs you can check, and check ones you did not.")
    _print(out)
    _print(out, "  katana                      ask me what I want to do")
    for name, _title, hint in COMMANDS:
        _print(out, "  katana %-21s %s" % (name, hint))
    _print(out)
    _print(out, "Less often needed:")
    for name, hint in MORE_COMMANDS:
        _print(out, "  katana %-21s %s" % (name, hint))
    _print(out)
    _print(out, "Every underlying tool's own flags still work, for example")
    _print(out, "  katana build my.spec.yaml --dry-run --expect-root <sha256>")
    _print(out, "  katana check my.gb --host genome.fna --html report.html")
    _print(out)
    _print(out, "Nothing needs installing beyond Python 3.9 or newer.")


def _run_module(path, argv, stdout):
    """Run one of the tools in-process, so its output lands in `stdout`.

    In-process rather than as a subprocess: one interpreter, no startup cost, and the
    output goes where the caller asked -- which is what lets the menu be tested.
    """
    import runpy
    old_argv, old_stdout, old_path = sys.argv, sys.stdout, list(sys.path)
    sys.argv = [path] + list(argv)
    sys.stdout = stdout
    # The tool's own directory goes on sys.path, because kagami's modules import each
    # other as siblings (`import kg_parse`) and expect to be run from inside kagami/.
    # Running them from the repository root without this gets ModuleNotFoundError.
    tool_dir = os.path.dirname(os.path.abspath(path))
    if tool_dir not in sys.path:
        sys.path.insert(0, tool_dir)
    try:
        runpy.run_path(path, run_name="__main__")
        return 0
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        # sys.exit("a message") -- the tools use this for BLOCK text. Print it where the
        # caller is looking rather than letting it vanish into the exception.
        stdout.write(str(code) + "\n")
        return 1
    finally:
        sys.argv, sys.stdout, sys.path[:] = old_argv, old_stdout, old_path


def _dispatch(name, argv, stdout):
    if name == "check":
        return _run_module(os.path.join(HERE, "kagami", "kagami.py"),
                           ["audit"] + list(argv), stdout)
    if name == "build":
        return _run_module(os.path.join(HERE, "katana_build.py"), list(argv), stdout)
    if name == "verify":
        return _run_module(os.path.join(HERE, "verify.py"), list(argv), stdout)
    if name == "add":
        return _run_module(os.path.join(HERE, "add_part.py"), list(argv), stdout)
    if name == "design":
        return _run_module(os.path.join(HERE, "check_design.py"), list(argv), stdout)
    if name == "genome":
        return _run_module(os.path.join(HERE, "get_genome.py"), list(argv), stdout)
    if name == "find":
        return _run_module(os.path.join(HERE, "find_part.py"), list(argv), stdout)
    if name == "init":
        return _run_module(os.path.join(HERE, "katana_init.py"), list(argv), stdout)
    if name == "web":
        return _run_module(os.path.join(HERE, "web_serve.py"), list(argv), stdout)
    if name == "bundle":
        return _run_module(os.path.join(HERE, "make_bundle.py"), list(argv), stdout)
    if name == "deploy":
        return _run_module(os.path.join(HERE, "web_deploy.py"), list(argv), stdout)
    if name == "gui":
        try:
            import tkinter  # noqa: F401
        except ImportError:
            _print(stdout, "This machine has no tkinter, so the window cannot open.")
            _print(stdout, "Nothing is wrong, and everything the window does is here:")
            _print(stdout, "    katana check YOURFILE.gb")
            _print(stdout, "    katana build YOURSPEC.spec.yaml")
            _print(stdout, "To get the window: on Debian or Ubuntu, "
                           "sudo apt install python3-tk")
            return 0
        return _run_module(os.path.join(HERE, "kagami", "kagami_gui.py"),
                           list(argv), stdout)
    _print(stdout, "There is no `katana %s`. What there is:" % name)
    _print(stdout)
    _usage(stdout)
    return 2


def _clean_path(line):
    """Turn whatever the terminal gave us into a path we can actually open.

    macOS Terminal inserts a DRAGGED path with its spaces backslash-escaped, not quoted --
    and the prompt above tells people to drag. So a file in a folder called "My Drive",
    "Google Drive" or "iGEM 2026" produced `input not found` on a path that was right,
    which is the most likely first-contact failure in the whole flow and was caused by the
    instruction the prompt itself gives.

    Also handles the file:// URL some applications drop, and the quotes other terminals
    add.
    """
    s = (line or "").strip()
    if not s:
        return ""
    if s[:1] in "\"'" and s[-1:] == s[:1]:
        s = s[1:-1]
    else:
        s = s.strip('"').strip("'")
    if s.lower().startswith("file://"):
        from urllib.parse import unquote
        s = unquote(s[7:])
    # A backslash before anything means "this character is literal", which is what the
    # shell would have done with it.
    s = re.sub(r"\\(.)", r"\1", s)
    return s.strip()


def _ask_and_run(name, stdin, stdout):
    """Ask for what the chosen command needs, one question at a time."""
    if name in ("verify", "gui", "web"):
        return _dispatch(name, [], stdout)

    # No --dry-run on build. The entry says "Design Spec -> order-ready sequence" and it
    # used to silently add --dry-run, so the run ended "Dry run - no output files", with
    # no sequence, no file, and no line saying how to get one. The menu promised the
    # opposite of what it delivered, to the one person least able to work out why. The
    # engine refuses to seal anything that fails a gate, so a real build is the safe
    # thing as well as the honest one.
    prompts = {
        "check": ("Which file? (drag it onto this window, then press Return)", []),
        "build": ("Which Design Spec? (drag it on, then press Return)", []),
        "add": ("Which iGEM Registry part? e.g. BBa_B0015", []),
    }
    question, extra = prompts[name]

    demo = os.path.join(HERE, "kagami", "examples", "demo.gb")
    offer_demo = name == "check" and os.path.isfile(demo)

    for attempt in (1, 2):
        stdout.write(question + "\n")
        if offer_demo:
            # Somebody who has just unzipped this has no sequence of their own, and the
            # very first menu entry asks for one. The bundle ships an 843 bp example with
            # a planted B0032 mislabel -- the README's own worked example -- and nothing
            # mentioned it, so nobody knew it was there.
            stdout.write("(or press Return to try the bundled example, "
                         "kagami/examples/demo.gb)\n")
        stdout.write("> ")
        try:
            line = stdin.readline()
        except EOFError:
            line = ""
        answer = _clean_path(line)

        if not answer:
            if offer_demo:
                _print(stdout)
                _print(stdout, "Using the bundled example: kagami/examples/demo.gb")
                _print(stdout)
                return _dispatch(name, [demo] + extra, stdout)
            _print(stdout)
            _print(stdout, "Nothing given, so nothing was done.")
            return 0

        if name == "add":
            return _dispatch("add", ["--registry", answer], stdout)

        if os.path.exists(answer):
            return _dispatch(name, [answer] + extra, stdout)

        # A wrong path used to print one line on stderr and exit, so the person was back
        # at the shell and had to re-run ./katana and re-navigate the menu for every
        # attempt. Ask again, once, and say what was actually looked for.
        _print(stdout)
        _print(stdout, "  There is no file at:")
        _print(stdout, "    " + answer)
        if attempt == 1:
            _print(stdout)
            _print(stdout, "  Let us try again. Drag the file onto this window rather "
                           "than typing the path,")
            _print(stdout, "  then press Return.")
            _print(stdout)
        else:
            _print(stdout)
            _print(stdout, "  Nothing was done. Run ./katana again when you have the "
                           "file to hand.")
            return 2
    return 2


def _menu(stdin, stdout):
    _print(stdout, "Katana - what do you want to do?")
    _print(stdout)
    for n, (_name, title, hint) in enumerate(COMMANDS, 1):
        _print(stdout, "  %d) %-26s %s" % (n, title, hint))
    _print(stdout)
    _print(stdout, "  (press Return to leave)")
    _print(stdout)
    stdout.write("Choose (1-%d): " % len(COMMANDS))
    try:
        raw = stdin.readline()
    except EOFError:
        raw = None

    if raw is None:
        # No terminal: a double-click, a pipe, or a CI step. Say how to run it without
        # one rather than dying on a traceback nobody can act on.
        _print(stdout)
        _print(stdout, "Nothing is reading the keyboard here, so the menu cannot ask.")
        _print(stdout, "Name what you want instead:")
        _print(stdout)
        _usage(stdout)
        return 0

    choice = raw.strip()
    if not choice:
        _print(stdout)
        _print(stdout, "Nothing selected, so nothing was done.")
        _print(stdout, "Run it again when you know which one you need.")
        return 0
    if not choice.isdigit() or not (1 <= int(choice) <= len(COMMANDS)):
        _print(stdout)
        _print(stdout, "'%s' is not one of the numbers above, so nothing was done."
                       % choice)
        _print(stdout, "Run it again and type a single number from 1 to %d."
                       % len(COMMANDS))
        return 1

    name = COMMANDS[int(choice) - 1][0]
    _print(stdout)
    return _ask_and_run(name, stdin, stdout)


def run(argv=None, stdin=None, stdout=None):
    """Dispatch a subcommand, or ask. Returns an exit code; never raises for input."""
    argv = list(sys.argv[1:] if argv is None else argv)
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout

    if not argv:
        return _menu(stdin, stdout)
    if argv[0] in ("-h", "--help", "help"):
        _usage(stdout)
        return 0
    return _dispatch(argv[0], argv[1:], stdout)


if __name__ == "__main__":
    sys.exit(run())
