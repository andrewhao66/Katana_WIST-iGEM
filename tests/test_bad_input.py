"""test_bad_input.py — a file that is not a sequence must be told apart from an empty one.

Run: python3 tests/test_bad_input.py

Dropping the wrong file on this tool is one of the most likely first actions of someone
who has never used it. A photo. A Word document. The PDF of the paper. An empty file they
made with the wrong editor.

Before this suite, every one of those produced a formal sequence audit:

    ========================================================================
    KAGAMI · sequence audit   ·   photo   ·   0 bp   · linear
    ========================================================================
    DECOMPOSITION — 0 block(s) identified against the public seed set:
    AUDIT:
      [FAIL] invariant        Empty sequence

The header is a claim: that this is a sequence, that it is 0 bp, and that it is linear.
None of that was read from the file -- the parser could not read the file at all and
returned an empty record. "Empty sequence" sends a student to debug their sequence when
what they need to debug is which file they picked.

That is the project's fourth rule applied to input. Parsing a PNG into an empty record
resolves "I cannot read this" into "this is empty", silently, and the information that
there was a discrepancy is destroyed. Report it instead.

What must hold: a file that is not a sequence file says so, and says what to do. An empty
sequence file says THAT, which is a different thing. And a real sequence still parses --
including the loose formats the parser deliberately accepts, because a beginner's "sequence
file" is often a .txt with bases pasted into it.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "kagami"))

import kg_parse

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  [" + str(detail)[:300] + "]") if detail else ""))


D = tempfile.mkdtemp(prefix="badinput_")


def write(name, data):
    path = os.path.join(D, name)
    mode = "wb" if isinstance(data, bytes) else "w"
    with open(path, mode) as f:
        f.write(data)
    return path


def parse_err(path):
    """Returns the refusal message, or None if parse() returned a record."""
    try:
        kg_parse.parse(path)
        return None
    except kg_parse.NotASequenceFile as exc:
        return str(exc)


print("files that are not sequences")

# ---- the things a person actually drops by mistake ----
CASES = [
    ("photo.png", b"\x89PNG\r\n\x1a\n" + b"\x00\x01\x02" * 40, "PNG image"),
    ("paper.pdf", b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n" + b"\x00" * 40, "PDF"),
    ("notes.docx", b"PK\x03\x04\x14\x00\x06\x00" + b"\x00" * 40, "Word"),
    ("scan.jpg", b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 40, "JPEG image"),
    ("archive.zip", b"PK\x03\x04" + b"\x00" * 60, "zip"),
]
for name, data, what in CASES:
    msg = parse_err(write(name, data))
    check("a %s is refused, not read as an empty sequence" % what, msg is not None,
          "parsed without complaint")
    if msg:
        check("  and the message names the file rather than the sequence",
              name in msg, msg[:140])

# A refusal must tell them what to do next. Being told "no" without being told "instead"
# is where somebody gives up.
msg = parse_err(write("photo2.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 40))
check("the refusal says what a sequence file looks like",
      msg and any(w in msg for w in ("FASTA", "GenBank")), msg)

# ---- an EMPTY sequence file is a different thing, and must read differently ----
empty = write("empty.fasta", "")
msg = parse_err(empty)
check("an empty file is refused too", msg is not None)
check("but its message is about the file being empty, not about its format",
      msg and "empty" in msg.lower(), msg)

header_only = write("header.fasta", ">my_construct\n")
msg = parse_err(header_only)
check("a FASTA header with no bases is refused", msg is not None)
check("and says the file has no bases in it",
      msg and ("no " in msg.lower() or "empty" in msg.lower()), msg)

# ---- text with no DNA in it ----
prose = write("readme.txt", "These are my notes about the project.\n"
                            "Remember to ask about the plasmid on Tuesday.\n")
msg = parse_err(prose)
check("a text file with no bases in it is refused", msg is not None, "parsed as a sequence")

# ---- and everything that IS a sequence must still parse ----
good = {
    "plain.fasta": ">c1\nATGCATGCATGCATGCATGCATGCATGC\n",
    # A beginner's "sequence file": bases pasted into a .txt, no header at all. The
    # parser deliberately accepts this, and must keep accepting it.
    "pasted.txt": "atgcatgcatgcatgcatgcatgcatgc\n",
    # With the line numbers a sequence viewer copies along.
    "numbered.txt": "   1 ATGCATGCAT GCATGCATGC\n  21 ATGCATGCAT GCATGCATGC\n",
    # And one with whitespace and blank lines through it.
    "spaced.fasta": ">c2\nATGC ATGC\n\n  ATGCATGC  \nATGCATGCATGC\n",
}
for name, text in good.items():
    path = write(name, text)
    try:
        rec = kg_parse.parse(path)
        check("%s still parses (%d bp)" % (name, len(rec.seq)), len(rec.seq) >= 20,
              "%d bp" % len(rec.seq))
    except Exception as exc:
        check("%s still parses" % name, False, "%s: %s" % (type(exc).__name__, exc))

# A real GenBank file from the repository, as the strongest regression guard.
demo = os.path.join(ROOT, "kagami", "examples", "demo.gb")
if os.path.isfile(demo):
    rec = kg_parse.parse(demo)
    check("the demo GenBank still parses at 843 bp with its features",
          len(rec.seq) == 843 and len(rec.features) >= 4,
          "%d bp, %d features" % (len(rec.seq), len(rec.features)))

# ---- and the command line must say it clearly, not print an audit of nothing ----
p = subprocess.run([sys.executable, "kagami.py", "audit",
                    os.path.join(D, "photo.png")],
                   cwd=os.path.join(ROOT, "kagami"), capture_output=True, text=True)
out = p.stdout + p.stderr
check("`kagami audit` on a PNG does not print a sequence audit header",
      "sequence audit" not in out, out[:200])
check("it says the file is not a sequence file", "not a sequence" in out.lower(),
      out[:200])
check("and it does not claim the sequence is empty",
      "Empty sequence" not in out, out[:200])
check("and it exits non-zero so a script can tell", p.returncode != 0,
      str(p.returncode))

import shutil
shutil.rmtree(D, ignore_errors=True)

# ---- a file that disagrees with itself about its own length ----
# Found by an independent Codex review. The LOCUS line declares the length, and it was
# read for the name and the topology and not for that. A file whose ORIGIN block had been
# cut off -- LOCUS saying 129 bp with 60 bases present -- parsed as a 60-base sequence and
# was audited as though it were whole. Every per-base finding is then a finding about a
# FRAGMENT, reported as a finding about the construct, with nothing saying which it is.
#
# This is what a truncated download, an interrupted write or a partial copy looks like,
# and the honest answer is to refuse: the audit cannot report on a construct from a piece
# of it. Rule four -- say which two things disagree and what each says.
_D9 = tempfile.mkdtemp(prefix="locuslen_")
_trunc = os.path.join(_D9, "cut.gb")
with open(_trunc, "w", encoding="utf-8") as _f:
    _f.write("LOCUS       cut      129 bp    DNA     linear   SYN\n"
             "FEATURES             Location/Qualifiers\n"
             "     misc_feature    1..129\n"
             '                     /label="whatever"\n'
             "ORIGIN\n"
             "        1 atgcatgcat gcatgcatgc atgcatgcat gcatgcatgc atgcatgcat "
             "gcatgcatgc\n"
             "//\n")
_raised = None
try:
    kg_parse.parse(_trunc)
except kg_parse.NotASequenceFile as _e:
    _raised = str(_e)
except Exception as _e:               # anything else is the wrong failure
    _raised = "WRONG EXCEPTION: %r" % _e
check("a file whose LOCUS length disagrees with its bases is REFUSED",
      _raised and not _raised.startswith("WRONG"), _raised or "parsed happily")
if _raised and not _raised.startswith("WRONG"):
    check("  and both numbers are quoted", "129" in _raised and "60" in _raised,
          _raised[:200])
    check("  and it says nothing was audited", "Nothing was audited" in _raised,
          _raised[:200])
    check("  and it names what this looks like",
          "truncated" in _raised or "partial copy" in _raised, _raised[:240])

# Every intact file must still parse -- the whole sealed library and the demo.
import glob as _glob

_bad = []
for _f2 in ([os.path.join(ROOT, "kagami", "examples", "demo.gb")]
            + sorted(_glob.glob(os.path.join(ROOT, "parts-library", "ref_parts",
                                             "*", "*", "*.gb")))):
    try:
        kg_parse.parse(_f2)
    except Exception as _e:
        _bad.append("%s: %r" % (os.path.basename(_f2), _e))
check("every sealed part file and the demo still parse (%d checked)"
      % (1 + len(_glob.glob(os.path.join(ROOT, "parts-library", "ref_parts",
                                         "*", "*", "*.gb")))),
      not _bad, "; ".join(_bad[:3]))

# A file with NO declared length is not an error -- plenty of real GenBank lacks it.
_nolen = os.path.join(_D9, "nolen.gb")
with open(_nolen, "w", encoding="utf-8") as _f:
    _f.write("LOCUS       nolen\nORIGIN\n        1 atgcatgcatgcatgcatgcatgca\n//\n")
try:
    _r9 = kg_parse.parse(_nolen)
    check("a LOCUS line with no declared length still parses", len(_r9.seq) == 25,
          len(_r9.seq))
except Exception as _e:
    check("a LOCUS line with no declared length still parses", False, repr(_e))

import shutil as _sh9

_sh9.rmtree(_D9, ignore_errors=True)

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
