"""test_nested_claims.py — every claim in the file gets checked, nested ones included.

Run: python3 tests/test_nested_claims.py

Found by an independent Codex review, and it goes to the point of the whole tool.

B0015 is a double terminator; B0010 is the first of its two parts, so B0010's eighty
bases sit inside B0015's hundred and twenty-nine. Give the auditor a file annotating
B0015 at 1..129 correctly AND those same inner eighty bases as "B0034" -- a flat
falsehood, since they are B0010 -- and it reported:

    blocks:            [(1, 129, 'B0015', 'B0015')]
    identity findings: []

The inner claim VANISHED. Not contradicted, not skipped with a reason -- gone. A
submitted claim was never audited, and the report said nothing was wrong.

The cause is one line in kg_identify: a claim-only feature "fully covered by an identity
block" was skipped, three lines under a comment promising such features are "kept as
claim-only blocks so they are still audited".

Greedy decomposition deciding WHICH of the submitter's claims get verified is the wrong
shape. The tiling exists to describe what the construct is made of. Checking claims is a
separate job, and it has to cover all of them: the one claim a student most needs
checked is the one they were most confident about, and confidence is what puts a label on
a region someone else already labelled.
"""
import os
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
        print("  FAIL " + name + (("  [" + str(detail)[:300] + "]") if detail else ""))


FULL = list(kg_refs.REFERENCE_PARTS)
_by_id = {r["id"]: r["seq"] for r in FULL if r.get("seq")}
B15 = kg_refs.normalise(_by_id["B0015"])
B10 = kg_refs.normalise(_by_id.get("B0010") or "")


def pinned(ids):
    kg_refs.REFERENCE_PARTS[:] = [r for r in FULL if r["id"] in ids]
    if hasattr(kg_refs, "tier"):
        kg_refs.tier.__defaults__[0].clear()


def unpinned():
    kg_refs.REFERENCE_PARTS[:] = FULL
    if hasattr(kg_refs, "tier"):
        kg_refs.tier.__defaults__[0].clear()


def audit(seq, feats, topology="linear"):
    """feats: (start, end, kind, label)."""
    d = tempfile.mkdtemp(prefix="nested_")
    path = os.path.join(d, "t.gb")
    out = ["LOCUS       t %13d bp    DNA     %s   SYN" % (len(seq), topology),
           "FEATURES             Location/Qualifiers"]
    for start, end, kind, label in feats:
        out.append("     %-16s%d..%d" % (kind, start, end))
        out.append('                     /label="%s"' % label)
    out.append("ORIGIN")
    for i in range(0, len(seq), 60):
        out.append("%9d %s" % (i + 1, " ".join(seq[i + j:i + j + 10]
                                               for j in range(0, 60, 10))))
    out.append("//")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    record = kg_parse.parse(path)
    status = {}
    with tempfile.TemporaryDirectory() as wd:
        blocks = kg_identify.identify(record, wd, status=status)
    return record, blocks, kg_audit.audit(record, blocks,
                                          identify_status=status), status


print("nested claims")

check("B0010's bases really do sit inside B0015", B10 and B10 in B15,
      "B0010 %d bp, found at %d" % (len(B10), B15.find(B10)))

pinned({"B0015", "B0010", "B0034"})
try:
    pos = B15.find(B10)

    # ---- a FALSE nested claim must be caught ----
    _rec, _bl, _fs, _st = audit(B15, [
        (1, len(B15), "terminator", "B0015"),
        (pos + 1, pos + len(B10), "terminator", "B0034")])
    check("the file's two features both survive parsing", len(_rec.features) == 2,
          str([(f.start, f.end, f.label) for f in _rec.features]))
    _ident = [f for f in _fs if f.category.startswith("identity")]
    check("a false NESTED claim raises an identity finding", _ident,
          "blocks %s | findings %s"
          % ([(b.start, b.end, b.claim_label, b.ident_id) for b in _bl],
             [f.category for f in _fs]))
    check("and the finding names the inner label",
          any("B0034" in (f.summary or "") + (f.detail or "") for f in _ident),
          str([(f.category, f.summary) for f in _ident]))
    check("and it is a FLAG, so the verdict is not PASS",
          any(f.status == kg_audit.FLAG for f in _ident)
          and kg_audit.verdict_kind(_fs) == "REVIEW",
          "%s | %s" % ([(f.category, f.status) for f in _ident],
                       kg_audit.verdict(_fs)))
    check("and the outer, correct claim is NOT accused of anything",
          not any(f.category == "identity-mislabel" and '"B0015"' in (f.summary or "")
                  for f in _fs),
          str([(f.category, f.summary) for f in _fs]))

    # ---- a TRUE nested claim must stay quiet ----
    _rec, _bl, _fs, _st = audit(B15, [
        (1, len(B15), "terminator", "B0015"),
        (pos + 1, pos + len(B10), "terminator", "B0010")])
    check("a TRUE nested claim raises no mislabel",
          not [f for f in _fs if f.category == "identity-mislabel"],
          str([(f.category, f.summary) for f in _fs]))
    check("and its verdict is not REVIEW", kg_audit.verdict_kind(_fs) != "REVIEW",
          kg_audit.verdict(_fs))

    # ---- the tiling itself must stay a clean decomposition ----
    # Checking a nested claim must not add an overlapping block: the blocks table is
    # "what this construct is made of", and two rows covering the same bases makes it
    # unreadable.
    _rec, _bl, _fs, _st = audit(B15, [
        (1, len(B15), "terminator", "B0015"),
        (pos + 1, pos + len(B10), "terminator", "B0034")])
    _spans = sorted((b.start, b.end) for b in _bl)
    _overlap = any(_spans[i][1] >= _spans[i + 1][0] for i in range(len(_spans) - 1))
    check("the blocks still tile without overlapping (%s)" % str(_spans),
          not _overlap, str(_spans))

    # ---- and the nested check is recorded, not invented by the audit ----
    check("identify() reports the claims it could not place as blocks",
          _st.get("nested_claims"),
          str(sorted(_st.keys())))
    if _st.get("nested_claims"):
        _nc = _st["nested_claims"][0]
        check("  with the claim, its coordinates and what the bases actually are",
              all(k in _nc for k in ("claim", "start", "end", "ident_id")),
              str(_nc))

    # ---- a nested claim naming a synonym is still correct ----
    # B0010's bases are also registered under other numbers; naming any of them is right,
    # and this check must not re-introduce the false-mislabel bug the synonym fix removed.
    _alt = [pid for pid, s in _by_id.items()
            if kg_refs.normalise(s) == B10 and pid != "B0010"]
    if _alt:
        pinned({"B0015", "B0010", _alt[0]})
        _rec, _bl, _fs, _st = audit(B15, [
            (1, len(B15), "terminator", "B0015"),
            (pos + 1, pos + len(B10), "terminator", _alt[0])])
        check("a nested claim naming a synonym (%s) is not called a mislabel" % _alt[0],
              not [f for f in _fs if f.category == "identity-mislabel"],
              str([(f.category, f.summary) for f in _fs]))
    else:
        print("  ---- B0010 has no synonym in the set; that case MEASURED NOTHING")
finally:
    unpinned()

# ---- the demo must not change ----
demo = os.path.join(ROOT, "kagami", "examples", "demo.gb")
if os.path.isfile(demo):
    record = kg_parse.parse(demo)
    status = {}
    with tempfile.TemporaryDirectory() as wd:
        dblocks = kg_identify.identify(record, wd, status=status)
    dfind = kg_audit.audit(record, dblocks, identify_status=status)
    _mis = [f for f in dfind if f.category == "identity-mislabel"]
    check("the demo still raises exactly its one planted mislabel", len(_mis) == 1,
          str([(f.category, f.summary) for f in dfind]))
    check("and its verdict is still REVIEW",
          kg_audit.verdict_kind(dfind) == "REVIEW", kg_audit.verdict(dfind))

# ---- an unchecked IDENTITY must reach the verdict, not just the rows ----
# Found by an independent review. An eight-base region labelled "B0015" produced
# `identity-unchecked: SKIP` in the findings and a verdict of PASS -- so the browser
# showed a green pill over a label nobody had verified. Surfacing a row does not stop a
# consumer treating the overall verdict as approval; the verdict has to carry it.
#
# Not every SKIP: host-homology skips whenever no host is given, which is the default on
# most runs, and escalating that would put REVIEW on nearly every audit. An unchecked
# identity is the one question this software exists to answer.
_short = _by_id["B0015"][:8] + _by_id["B0015"]
_rec3, _bl3, _fs3, _st3 = None, None, None, None
_d = tempfile.mkdtemp(prefix="unchecked_")
_p = os.path.join(_d, "t.gb")
_out = ["LOCUS       t %13d bp    DNA     linear   SYN" % len(_short),
        "FEATURES             Location/Qualifiers",
        "     terminator      1..8",
        '                     /label="B0015"', "ORIGIN"]
for _i in range(0, len(_short), 60):
    _out.append("%9d %s" % (_i + 1, " ".join(_short[_i + _j:_i + _j + 10]
                                             for _j in range(0, 60, 10))))
_out.append("//")
with open(_p, "w", encoding="utf-8") as _f:
    _f.write("\n".join(_out) + "\n")
_rec3 = kg_parse.parse(_p)
_st3 = {}
with tempfile.TemporaryDirectory() as _wd:
    _bl3 = kg_identify.identify(_rec3, _wd, status=_st3)
_fs3 = kg_audit.audit(_rec3, _bl3, identify_status=_st3)

check("a label too short to identify produces an identity-unchecked SKIP",
      any(f.category == "identity-unchecked" for f in _fs3),
      str([(f.category, f.status) for f in _fs3]))
check("and the VERDICT is REVIEW, not PASS",
      kg_audit.verdict_kind(_fs3) == "REVIEW", kg_audit.verdict(_fs3))
check("and the headline says labels could not be checked rather than '0 to resolve'",
      "could not be checked" in kg_audit.verdict(_fs3), kg_audit.verdict(_fs3))

# A host-homology SKIP on its own must NOT escalate, or every audit without a host
# becomes REVIEW and the warning stops meaning anything.
_only_host = [f for f in _fs3 if f.category == "host-homology"]
_fs_host = _only_host + [f for f in _fs3 if f.status == kg_audit.PASS]
check("a host-homology SKIP alone does not force REVIEW",
      _only_host and kg_audit.verdict_kind(_fs_host) == "PASS",
      "%s | %s" % ([(f.category, f.status) for f in _fs_host],
                   kg_audit.verdict_kind(_fs_host)))

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
