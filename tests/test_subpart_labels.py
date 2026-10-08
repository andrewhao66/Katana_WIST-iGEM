"""test_subpart_labels.py — a label is not false because the Registry has a fragment of it.

Run: python3 tests/test_subpart_labels.py

Found by verifying a real audit the user had run, against the spec and the sealed library
rather than against the audit's own output.

The construct was `pSense-Nit`, built by Katana from its own sealed library — its sequence
hash is the ORACLE value this branch asserts everywhere. Its promoter is **PyeaR**, 162 bp
sealed, present as its first 146 bases. On the GenBank Katana itself wrote, carrying
Katana's own `/label="PyeaR"`, the auditor said:

    [FLAG] identity-mislabel  Block labelled "PyeaR" is actually K1799015 (BBa_K1799015)
           → fix: Re-label to K1799015, or swap in the real PyeaR sequence from the
             Registry via katana-parts-library

A false accusation, on the one check this software exists to perform, against the engine's
own sealed output — telling a student to change a label that was right.

Why it happened. `K1799015` is exactly `PyeaR[13:113]`: a 100 bp Registry re-deposit of a
*piece* of PyeaR. Both are in the public set, so both are hits:

    K1799015   100.0% id  cov 1.000  [14-113]      <- a fragment, matched end to end
    PyeaR       95.1% id  cov 0.969  [1-157]       <- the real part, nearly complete

`_tile` prefers completeness — for a good documented reason, so that a composite cannot
swallow the real parts inside it — and here that preference inverts: the complete match IS
the fragment. The identifier then named the fragment, and the mislabel check compared the
claim against that name and found them different.

The earlier synonym fix does not cover this. That one handles references with the SAME
sequence under several numbers, through `alternatives`. This is a sub-sequence
relationship, which `alternatives` does not and should not contain.

What must hold: before a claim is called false, it is checked against the FACTS — do the
block's bases actually occur in the sequence the claim names? If they do, the label is
true, whichever re-deposit the identifier happened to name. Measured first, implemented
second: reporting every longer reference that contains an identified one was tried and
abandoned, because the Registry is a dense web of nested re-deposits and it fired dozens
of times per construct.
"""
import os
import subprocess
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
from core import lock as _lock
from core import parts as _parts

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

print("sub-part labels")

# ---- the premise, measured ----
check("PyeaR is in the public reference set", "PyeaR" in REFS)
check("K1799015 is too", "K1799015" in REFS)
_pos = REFS.get("PyeaR", "").find(REFS.get("K1799015", "x"))
check("and K1799015's bases are exactly a slice of PyeaR's (at %d)" % _pos,
      _pos == 13, _pos)
check("PyeaR is the longer of the two (%d vs %d)"
      % (len(REFS.get("PyeaR", "")), len(REFS.get("K1799015", ""))),
      len(REFS["PyeaR"]) > len(REFS["K1799015"]))

# ---- build the construct from the spec, so this tests the engine's own output ----
_out = tempfile.mkdtemp(prefix="subpart_")
_p = subprocess.run([sys.executable, "katana_build.py",
                     os.path.join(ROOT, "specs", "pSense-Nit.spec.yaml"),
                     "--outdir", _out],
                    cwd=ROOT, capture_output=True, text=True, timeout=900)
_gb = [f for f in os.listdir(_out) if f.endswith(".gb")]
check("Katana builds pSense-Nit and writes a GenBank", _gb,
      (_p.stdout + _p.stderr)[-200:])

if _gb:
    _path = os.path.join(_out, _gb[0])
    _record = kg_parse.parse(_path)
    check("whose sequence is the ORACLE construct", len(_record.seq) == 1013,
          len(_record.seq))
    _labels = [f.label for f in _record.features if f.label]
    check("and which carries Katana's own PyeaR label", "PyeaR" in _labels,
          str(_labels))

    _status = {}
    with tempfile.TemporaryDirectory() as _wd:
        _blocks = kg_identify.identify(_record, _wd, status=_status)
    _findings = kg_audit.audit(_record, _blocks, identify_status=_status)

    # ---- the accusation must be gone ----
    _mis = [f for f in _findings if f.category == "identity-mislabel"]
    check("auditing Katana's OWN build raises no mislabel FLAG", not _mis,
          "; ".join(f.summary for f in _mis))
    check("and the verdict is not REVIEW on account of one",
          not any(f.category == "identity-mislabel" and f.status == kg_audit.FLAG
                  for f in _findings),
          kg_audit.verdict(_findings))

    # ---- but the two readings are both reported, not one silently chosen ----
    _sub = [f for f in _findings if f.category == "identity-subpart"]
    check("instead there is a sub-part NOTE", len(_sub) == 1,
          str([(f.category, f.status) for f in _findings]))
    if _sub:
        check("  and it is a NOTE, which never changes a PASS",
              _sub[0].status == kg_audit.NOTE, _sub[0].status)
        check("  and it names BOTH readings -- the claim and what was identified",
              "PyeaR" in _sub[0].summary + (_sub[0].detail or "")
              and "K1799015" in _sub[0].summary + (_sub[0].detail or ""),
              _sub[0].summary)
        # The wording moved from "is correct" to "names the right part" deliberately:
        # with a truncation FLAG beside it, "correct" reads as a verdict on the whole
        # block when it is only a verdict on the NAME. What is pinned is that it says
        # the label is right, not which words say it.
        check("  and says the label names the right part",
              "right part" in _sub[0].summary or "correct" in _sub[0].summary.lower(),
              _sub[0].summary)
        check("  and does NOT tell them to re-label anything",
              "re-label" not in (_sub[0].fix or "").lower(), _sub[0].fix)

# ---- a REAL mislabel must still be caught ----
# B0032's bases labelled B0034 is CLAUDE.md's own worked example. B0032 is not a
# sub-sequence of B0034 -- they are different sequences -- so the FLAG must stand.
def audit_gb(seq, feats):
    d = tempfile.mkdtemp(prefix="subpart2_")
    path = os.path.join(d, "t.gb")
    out = ["LOCUS       t %13d bp    DNA     linear   SYN" % len(seq),
           "FEATURES             Location/Qualifiers"]
    for a, b, kind, label in feats:
        out.append("     %-16s%d..%d" % (kind, a, b))
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
    return bl, kg_audit.audit(rec, bl, identify_status=st)


_b32, _b34, _b15 = REFS.get("B0032"), REFS["B0034"], REFS["B0015"]
check("B0032 is not a sub-sequence of B0034, nor the reverse",
      _b32 and _b32 not in _b34 and _b34 not in _b32)
if _b32:
    _seq = _b32 + _b15
    _bl, _fs = audit_gb(_seq, [(1, len(_b32), "misc_feature", "B0034"),
                               (len(_b32) + 1, len(_seq), "terminator", "B0015")])
    check("B0032's bases labelled B0034 STILL raise a mislabel FLAG",
          [f for f in _fs if f.category == "identity-mislabel"],
          str([(f.category, f.status) for f in _fs]))

# And a claim naming a part that is nowhere near the bases is still a mislabel.
_seq2 = _b15 + _b34
_bl2, _fs2 = audit_gb(_seq2, [(1, len(_b15), "terminator", "B0034")])
check("a label naming a part whose bases are elsewhere still FLAGs",
      [f for f in _fs2 if f.category == "identity-mislabel"],
      str([(f.category, f.summary) for f in _fs2]))

# A claim naming something not in any reference set at all must not silently pass as a
# sub-part: there is nothing to check it against, which is a SKIP.
_bl3, _fs3 = audit_gb(_b15 + _b34, [(1, len(_b15), "terminator", "NotAPartAnywhere")])
_cats3 = [f.category for f in _fs3]
check("a claim naming nothing in the set is not treated as a correct sub-part",
      "identity-subpart" not in _cats3, str(_cats3))

# ---- the label being right does not mean the part is all there ----
# Found by an independent Codex review, on the fix two commits above this one. Accepting
# the containment and stopping there traded a false accusation for a MISSED TRUNCATION:
# with only PyeaR[13:113] present and labelled PyeaR, the report said
#
#   NOTE  Block labelled "PyeaR" is correct
#   VERDICT: PASS — 2 notes
#
# and never mentioned that 62 of PyeaR's 162 bases were absent. The coverage beside the
# identification reads 1.000 because K1799015 -- the shorter Registry entry the identifier
# named -- covers exactly the stretch that IS here. Both things have to be said: the label
# names the right part, and the part is not all there.
_PY = REFS.get("PyeaR", "")
check("PyeaR is long enough for a fragment to be a real shortfall (%d bp)" % len(_PY),
      len(_PY) > 150, len(_PY))

_frag = _PY[13:113]
_bl4, _fs4 = audit_gb(_frag + REFS["B0015"],
                      [(1, len(_frag), "promoter", "PyeaR"),
                       (len(_frag) + 1, len(_frag) + len(REFS["B0015"]),
                        "terminator", "B0015")])
_tr = [f for f in _fs4 if f.category == "truncation"]
check("a fragment of PyeaR labelled PyeaR raises a truncation FLAG", _tr,
      str([(f.category, f.status) for f in _fs4]))
if _tr:
    check("  and it counts the bases that are missing",
          "62" in _tr[0].summary and "162" in _tr[0].summary, _tr[0].summary)
    check("  and it is a FLAG, so the verdict is not PASS",
          _tr[0].status == kg_audit.FLAG
          and kg_audit.verdict_kind(_fs4) == "REVIEW",
          "%s | %s" % (_tr[0].status, kg_audit.verdict(_fs4)))
    check("  and it says the LABEL is still right, so nobody re-labels a correct part",
          "label is right" in (_tr[0].detail or ""), (_tr[0].detail or "")[:160])
check("and the sub-part NOTE is still there beside it",
      [f for f in _fs4 if f.category == "identity-subpart"],
      str([f.category for f in _fs4]))

# The whole part must not collect either finding.
_bl5, _fs5 = audit_gb(_PY + REFS["B0015"],
                      [(1, len(_PY), "promoter", "PyeaR"),
                       (len(_PY) + 1, len(_PY) + len(REFS["B0015"]),
                        "terminator", "B0015")])
check("the whole of PyeaR labelled PyeaR raises no truncation",
      not [f for f in _fs5 if f.category == "truncation"],
      str([(f.category, f.summary) for f in _fs5]))
check("and no mislabel", not [f for f in _fs5 if f.category == "identity-mislabel"],
      str([f.category for f in _fs5]))

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
