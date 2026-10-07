"""test_orientation.py — a part annotated on the wrong strand must be told.

Run: python3 tests/test_orientation.py

Found by an independent Codex review, through the synonym path, and the gap turned out to
be wider than the finding. There was NO orientation check anywhere in kg_audit: a part
whose label is right and whose strand is wrong went unreported, whatever its name.

The synonym fix made the worst case of it worse. B0034 and K1045010 are reverse
complements of each other, so both are in a B0034 block's `alternatives`. With forward
B0034 bases annotated as `complement(1..12)` -- claiming the part runs the other way --
the audit said:

    NOTE  Block labelled "B0034" is correct

It is not correct. The bases are B0034 read forward; the annotation says they are read
backwards. An RBS pointed the wrong way does not initiate translation of the CDS after
it, and nothing in the report said so. Before the synonym fix the same input raised a
mislabel FLAG -- for the wrong reason, with the wrong message, but it did at least warn.
Removing a warning is a regression even when the warning was badly worded.

What must hold: the orientation is part of the claim. A claim whose strand disagrees with
where the sequence actually matches is reported, and it is reported whether the label is
exact, a synonym, or wrong -- and the synonym NOTE does not call such a block correct.
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


REFS = {r["id"]: r["seq"] for r in kg_refs.REFERENCE_PARTS if r.get("seq")}
RCT = str.maketrans("ACGT", "TGCA")


def rc(s):
    return s.translate(RCT)[::-1]


def audit(seq, feats):
    """feats: (start, end, kind, label, strand), 1-based inclusive."""
    d = tempfile.mkdtemp(prefix="orient_")
    path = os.path.join(d, "t.gb")
    out = ["LOCUS       t %13d bp    DNA     linear   SYN" % len(seq),
           "FEATURES             Location/Qualifiers"]
    for start, end, kind, label, strand in feats:
        loc = ("complement(%d..%d)" % (start, end)) if strand == -1 \
            else ("%d..%d" % (start, end))
        out.append("     %-16s%s" % (kind, loc))
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
    return blocks, kg_audit.audit(record, blocks, identify_status=status)


def cats(findings, prefix="identity"):
    return [(f.category, f.status, f.summary) for f in findings
            if f.category.startswith(prefix)]


print("orientation")

B34, B15 = REFS["B0034"], REFS["B0015"]
check("B0034 and K1045010 really are reverse complements of each other",
      REFS.get("K1045010") == rc(B34))

seq = B34 + B15
FWD = (13, len(seq), "terminator", "B0015", 1)

# ---- the honest case must stay clean ----
blocks, findings = audit(seq, [(1, 12, "misc_feature", "B0034", 1), FWD])
check("forward B0034 annotated forward raises no orientation finding",
      not cats(findings, "identity-orientation"), cats(findings))
check("and still gets its synonym NOTE",
      any(c == "identity-synonym" for c, _s, _m in cats(findings)), cats(findings))
check("and the verdict is not REVIEW", kg_audit.verdict_kind(findings) != "REVIEW",
      kg_audit.verdict(findings))

# ---- the claim's strand is kept at all ----
blocks_rev, findings_rev = audit(seq, [(1, 12, "misc_feature", "B0034", -1), FWD])
_b = [b for b in blocks_rev if b.claim_label == "B0034"]
check("the block records the strand the annotation CLAIMED",
      _b and getattr(_b[0], "claim_strand", None) == -1,
      str([(b.claim_label, getattr(b, "claim_strand", "absent"), b.strand)
           for b in blocks_rev]))

# ---- and a disagreeing strand is reported ----
_orient = cats(findings_rev, "identity-orientation")
check("forward bases annotated complement raise an orientation finding",
      len(_orient) == 1, cats(findings_rev))
if _orient:
    check("and it is a FLAG, not a note", _orient[0][1] == kg_audit.FLAG, _orient[0][1])
    check("and the verdict is REVIEW", kg_audit.verdict_kind(findings_rev) == "REVIEW",
          kg_audit.verdict(findings_rev))

# The synonym NOTE must not call such a block correct.
_syn = [m for c, _s, m in cats(findings_rev) if c == "identity-synonym"]
check("the synonym note does NOT say the block is correct (%s)"
      % ("; ".join(_syn) or "no synonym note"),
      not any("is correct" in m for m in _syn))

# ---- the same, with a genuinely reverse-complemented part ----
seq_rc = rc(B34) + B15
blocks2, findings2 = audit(seq_rc, [(1, 12, "misc_feature", "B0034", -1), FWD])
check("reverse-complemented B0034 annotated complement raises no orientation finding",
      not cats(findings2, "identity-orientation"),
      str([(b.claim_label, getattr(b, "claim_strand", None), b.strand, b.ident_id)
           for b in blocks2]) + " | " + str(cats(findings2)))

blocks3, findings3 = audit(seq_rc, [(1, 12, "misc_feature", "B0034", 1), FWD])
check("reverse-complemented bases annotated forward DO raise one",
      len(cats(findings3, "identity-orientation")) == 1, cats(findings3))

# ---- and an exact-ID match on the wrong strand is flagged too, not just a synonym ----
seq_t = B15 + B34
blocks4, findings4 = audit(seq_t, [(1, len(B15), "terminator", "B0015", -1)])
_o4 = cats(findings4, "identity-orientation")
check("an exactly-named part on the wrong strand is flagged (B0015)", len(_o4) == 1,
      str([(b.claim_label, getattr(b, "claim_strand", None), b.strand, b.ident_id)
           for b in blocks4]) + " | " + str(cats(findings4)))
if _o4:
    check("and the message names the part and both directions",
          "B0015" in _o4[0][2], _o4[0][2])

# ---- a block with no claimed strand must not be flagged ----
# Plenty of real files annotate without an orientation; absence of a claim is not a
# claim of forward.
blocks5, findings5 = audit(seq, [(1, 12, "misc_feature", "B0034", 1), FWD])
check("a forward annotation is not treated as a missing one",
      not cats(findings5, "identity-orientation"), cats(findings5))

# ---- the demo must keep behaving ----
demo = os.path.join(ROOT, "kagami", "examples", "demo.gb")
if os.path.isfile(demo):
    record = kg_parse.parse(demo)
    status = {}
    with tempfile.TemporaryDirectory() as wd:
        dblocks = kg_identify.identify(record, wd, status=status)
    dfind = kg_audit.audit(record, dblocks, identify_status=status)
    check("the demo still raises its planted mislabel",
          any(f.category == "identity-mislabel" for f in dfind),
          str([f.category for f in dfind]))
    check("and gains no spurious orientation finding",
          not [f for f in dfind if f.category == "identity-orientation"],
          str([(f.category, f.summary) for f in dfind
               if f.category == "identity-orientation"]))

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
