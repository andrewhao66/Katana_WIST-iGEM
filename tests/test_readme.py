"""test_readme.py — every command the README documents must actually run.

Run: python3 tests/test_readme.py

A README whose first command fails is what produced the result this whole rewrite
exists for: zero of the non-software team members who followed it got the tool working.
The old front page opened with `python verify.py`, and `python` does not exist on macOS.

So: extract every `./katana ...` line from the README and run it. Commands containing a
placeholder (`my-design.spec.yaml`, `YOUR_ACCESSION`) are shape examples and are skipped
by name. Commands that WAIT FOR INPUT get an empty stdin and must still exit cleanly --
a documented command that hangs is as broken as one that fails, and harder to diagnose.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

PASS = FAIL = 0

# Shape examples: they show the form of a command, and the reader supplies the rest.
PLACEHOLDERS = ("my-design", "someones-plasmid", "<your", "my-project", "YOUR_",
                "my_rbs", "<yours>", "my.spec", "my.gb", "<gene", "a_name",
                "YourHost", "<path-to-your", "<sha256>", "out.ttl", "genome.fna",
                "report.html", "YOURFILE", "YOURSPEC")

# Commands that reach the network. Running them in a test would be slow, flaky, and
# rude to a public service.
NETWORK = ("katana add", "katana find", "katana genome")

# Opens a window and waits for the person to close it. Headless-testable only through
# ui_menu.run, which tests/test_entry.py already does.
INTERACTIVE = ("katana gui",)

# Longer than this and something is waiting for input that will never come.
TIMEOUT = 240


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  [" + str(detail)[:200] + "]") if detail else ""))


def documented_commands(path):
    text = open(path, encoding="utf-8").read()
    found = re.findall(r'^\s*(\./katana[^\n#]*)$', text, re.M)
    out = []
    for raw in found:
        # The README aligns an explanation after some commands, with spaces rather than
        # a # -- "./katana verify        check the library". Everything from two or more
        # spaces on is prose, not an argument, and passing it along is how this test
        # first ran `./katana verify check the library`.
        out.append(re.split(r"\s{2,}", raw.strip())[0])
    return out


print("README commands")

cmds = documented_commands(os.path.join(ROOT, "README.md"))
check("the README documents some ./katana commands", len(cmds) >= 5, str(len(cmds)))
check("and it leads with the front door rather than a tool name",
      "./katana\n" in open(os.path.join(ROOT, "README.md"), encoding="utf-8").read())

ran = skipped = 0
for cmd in cmds:
    if any(p in cmd for p in PLACEHOLDERS):
        skipped += 1
        continue
    if any(n in cmd for n in NETWORK) or any(i in cmd for i in INTERACTIVE):
        skipped += 1
        continue
    ran += 1
    # Empty stdin, not inherited: a documented command that waits for input it will
    # never get is as broken as one that fails, and much harder to diagnose.
    try:
        p = subprocess.run(["bash", "-c", cmd], cwd=ROOT, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=TIMEOUT)
        rc, why = p.returncode, (p.stdout + p.stderr)[-200:]
    except subprocess.TimeoutExpired:
        rc, why = None, "timed out after %ds -- it is waiting for input" % TIMEOUT
    # 0 is clean, 5 is REVIEW from the auditor, which is a legitimate documented outcome.
    check("`%s` runs" % cmd, rc in (0, 5), "exit %s: %s" % (rc, why))

print()
print("  %d run, %d skipped as placeholders or network" % (ran, skipped))
print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
