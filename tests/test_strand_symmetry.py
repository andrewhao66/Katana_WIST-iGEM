"""test_strand_symmetry.py — reverse-complementing a construct must not change its verdict.

Run: python3 tests/test_strand_symmetry.py

Found by an independent Codex review, reproduced before being accepted.

A plasmid's parts run in both directions; which strand a gene sits on is an ordinary
design choice, not a defect. So a finding that appears on one strand and not the other is
a finding about the checker, and this one was a FALSE ACCUSATION on a junction that is
correct:

    forward   FLAG  RBS→ATG spacing 2 nt (outside 5–9, measured from the SD)
    reverse   FLAG  No ATG found downstream of RBS at 841-852

Same construct, reverse-complemented. The ATG search walked the forward sequence whatever
the strand said, so for a reverse-strand RBS it looked AWAY from the CDS -- which sits
upstream in forward coordinates. The SD search a few lines below already
reverse-complements the block, so the two halves of one check disagreed about which way
the gene runs.

Spacing is a distance. It is the same number read from either end, and both strands now
report it.

Also measured here and found CORRECT, so it is recorded rather than changed: a true
palindrome from the reference set -- there are 21 of them at 25 bp or longer, including
J37012 at 84 bp -- placed forward and labelled forward raises NO orientation FLAG, though
it matches its own reverse complement exactly.
"""
import os
import random
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "kagami"))

import kg_audit
import kg_identify
import kg_parse
import kg_refs

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  [" + str(detail)[:320] + "]") if detail else ""))


REFS = {r["id"]: kg_refs.normalise(r.get("seq") or "")
        for r in kg_refs.REFERENCE_PARTS if r.get("seq")}
RC = {"A": "T", "C": "G", "G": "C", "T": "A", "N": "N"}


def rc(s):
    return "".join(RC[c] for c in reversed(s))


def audit_gb(seq, feats):
    d = tempfile.mkdtemp(prefix="strandsym_")
    path = os.path.join(d, "t.gb")
    out = ["LOCUS       t %13d bp    DNA     linear   SYN" % len(seq),
           "FEATURES             Location/Qualifiers"]
    for a, b, kind, label, strand in feats:
        loc = ("complement(%d..%d)" % (a, b)) if strand == -1 else ("%d..%d" % (a, b))
        out.append("     %-16s%s" % (kind, loc))
        out.append('                     /label="%s"' % label)
    out.append("ORIGIN")
    for i in range(0, len(seq), 60):
        out.append("%9d %s" % (i + 1, " ".join(seq[i + j:i + j + 10]
                                               for j in range(0, 60, 10))))
    out.append("//")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    rec = kg_parse.parse(path)
    st = {}
    with tempfile.TemporaryDirectory() as wd:
        bl = kg_identify.identify(rec, wd, status=st)
    return kg_audit.audit(rec, bl, identify_status=st)


def junctions(findings):
    return sorted((f.status, f.summary) for f in findings if f.category == "junction")


R, G = REFS["B0034"], REFS["sfGFP"]
random.seed(9)
FL = "".join(random.choice("ACGT") for _ in range(120))

print("strand symmetry")

# ---- the defect: a bad spacing must read the same from either side ----
_fwd = audit_gb(FL + R + G + FL,
                [(121, 120 + len(R), "RBS", "B0034", 1),
                 (121 + len(R), 120 + len(R) + len(G), "CDS", "sfGFP", 1)])
_rev = audit_gb(FL + rc(R + G) + FL,
                [(121 + len(G), 120 + len(G) + len(R), "RBS", "B0034", -1),
                 (121, 120 + len(G), "CDS", "sfGFP", -1)])
check("the forward construct reports an RBS spacing at all", junctions(_fwd),
      str([(f.category, f.summary) for f in _fwd]))
check("the reverse construct reports one too", junctions(_rev),
      str([(f.category, f.summary) for f in _rev]))
check("and neither says the ATG is missing",
      not [f for f in _fwd + _rev if "No ATG" in f.summary],
      str([f.summary for f in _fwd + _rev if "No ATG" in f.summary]))
check("and the two strands report the SAME spacing",
      junctions(_fwd) == junctions(_rev),
      "forward %s | reverse %s" % (junctions(_fwd), junctions(_rev)))

# ---- a CORRECT spacing must also read the same, and must PASS on both ----
_sp = "TTAATTA"
_fwd2 = audit_gb(FL + R + _sp + G + FL, [(121, 120 + len(R), "RBS", "B0034", 1)])
_rev2 = audit_gb(FL + rc(R + _sp + G) + FL,
                 [(121 + len(G) + len(_sp), 120 + len(G) + len(_sp) + len(R),
                   "RBS", "B0034", -1)])
check("a deliberate in-window spacer PASSES on the forward strand",
      [f for f in _fwd2 if f.category == "junction" and f.status == kg_audit.PASS],
      str(junctions(_fwd2)))
check("and PASSES on the reverse strand too",
      [f for f in _rev2 if f.category == "junction" and f.status == kg_audit.PASS],
      str(junctions(_rev2)))
check("with the same number", junctions(_fwd2) == junctions(_rev2),
      "forward %s | reverse %s" % (junctions(_fwd2), junctions(_rev2)))
check("and that number is inside 5-9",
      junctions(_fwd2) and any("9 nt" in s or "8 nt" in s or "7 nt" in s
                               or "6 nt" in s or "5 nt" in s
                               for _, s in junctions(_fwd2)),
      str(junctions(_fwd2)))

# ---- measured and correct: a palindrome is not an orientation error ----
_pals = [pid for pid, s in REFS.items() if len(s) >= 25 and s == rc(s)]
check("the reference set contains true palindromes at 25 bp or more (%d)" % len(_pals),
      len(_pals) >= 1, str(_pals[:5]))
if _pals:
    _pid = max(_pals, key=lambda p: len(REFS[p]))
    _S = REFS[_pid]
    check("  the longest is %s at %d bp, equal to its own reverse complement"
          % (_pid, len(_S)), _S == rc(_S))
    _fs = audit_gb(FL + _S + FL, [(121, 120 + len(_S), "misc_feature", _pid, 1)])
    check("  and placed forward, labelled forward, it raises no orientation FLAG",
          not [f for f in _fs if f.category == "identity-orientation"],
          str([(f.category, f.summary) for f in _fs
               if f.category.startswith("identity")]))

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
