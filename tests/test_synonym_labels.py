"""test_synonym_labels.py — an honest label must not be called a mislabel.

Run: python3 tests/test_synonym_labels.py

The iGEM Registry holds the same bases under several part numbers. B0034's twelve bases,
AAAGAGGAGAAA, are also registered as K1325011, J34801, J70591, K1045010 and five more.
They are not similar sequences; they are the SAME sequence.

So a student who labels a block B0034 correctly, whose bases really are B0034's, was
told:

    FLAG  Block labelled "B0034" is actually K1325011 (BBa_K1325011)
          Sequence matches BBa_K1325011 at 100.0% identity, 100% coverage.

That is an accusation of the one thing this tool exists to detect, levelled at a
construct that is correct. B0034 was sitting in the block's own `alternatives` list at
the time -- the engine knew the claim was among the equally-good matches and said "is
actually" anyway.

It matters more than an ordinary false positive. A student who sees a mislabel FLAG on
every correct RBS learns that mislabel FLAGs are noise, and the one real mislabel then
goes past them too. The check that cries wolf is worse than no check.

And it lands exactly where the project cares most: CLAUDE.md's own worked example of the
failure this software exists to prevent is the B0032/B0034 RBS mislabel.

What must hold: a claim that names ANY of the identical-sequence matches is correct, and
reads as correct. The synonyms are still worth saying -- so it is a NOTE, which by
design never makes a construct anything other than a PASS.
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


def genbank(seq, feats):
    """A GenBank file carrying `feats` as (start, end, kind, label), 1-based inclusive."""
    out = ["LOCUS       synonym_test          %7d bp    DNA     linear   SYN" % len(seq),
           "FEATURES             Location/Qualifiers"]
    for start, end, kind, label in feats:
        out.append("     %-16s%d..%d" % (kind, start, end))
        out.append('                     /label="%s"' % label)
    out.append("ORIGIN")
    for i in range(0, len(seq), 60):
        out.append("%9d %s" % (i + 1,
                               " ".join(seq[i + j:i + j + 10] for j in range(0, 60, 10))))
    out.append("//")
    return "\n".join(out) + "\n"


def audit(seq, feats):
    d = tempfile.mkdtemp(prefix="syn_")
    path = os.path.join(d, "t.gb")
    with open(path, "w", encoding="utf-8") as f:
        f.write(genbank(seq, feats))
    record = kg_parse.parse(path)
    status = {}
    with tempfile.TemporaryDirectory() as wd:
        blocks = kg_identify.identify(record, wd, status=status)
    findings = kg_audit.audit(record, blocks, identify_status=status)
    return blocks, findings


def by_cat(findings, cat):
    return [f for f in findings if f.category == cat]


print("synonym labels")

# ---- the premise: B0034's bases really are registered under other numbers ----
b34 = REFS["B0034"]
same = sorted(pid for pid, s in REFS.items() if s == b34)
check("B0034's bases are registered under several part numbers (%d: %s)"
      % (len(same), ", ".join(same[:5])), len(same) > 1, str(same))

# ---- an honest B0034 label must not be called a mislabel ----
seq = b34 + REFS["B0015"]
feats = [(1, len(b34), "misc_feature", "B0034"),
         (len(b34) + 1, len(seq), "terminator", "B0015")]
blocks, findings = audit(seq, feats)

mis = by_cat(findings, "identity-mislabel")
check("an honest B0034 label raises NO mislabel finding", not mis,
      "; ".join(f.summary for f in mis))

check("the verdict is not REVIEW, because nothing needs resolving",
      kg_audit.verdict_kind(findings) != "REVIEW",
      kg_audit.verdict(findings))

# The synonyms are still worth telling someone about -- just not as an accusation.
syn = by_cat(findings, "identity-synonym")
check("instead there is a synonym NOTE", len(syn) == 1,
      "; ".join("%s/%s" % (f.category, f.status) for f in findings))
if syn:
    check("the note is a NOTE, which never makes a construct anything but a PASS",
          syn[0].status == kg_audit.NOTE, syn[0].status)
    check("it names the claim as correct", "B0034" in syn[0].summary, syn[0].summary)
    check("and says how many other numbers share the bases",
          any(ch.isdigit() for ch in (syn[0].detail or "")), syn[0].detail)

# ---- the same, claiming one of the OTHER synonyms ----
other = [p for p in same if p != "B0034"][0]
blocks2, findings2 = audit(seq, [(1, len(b34), "misc_feature", other),
                                 (len(b34) + 1, len(seq), "terminator", "B0015")])
check("claiming %s instead is equally correct" % other,
      not by_cat(findings2, "identity-mislabel"),
      "; ".join(f.summary for f in by_cat(findings2, "identity-mislabel")))

# ---- and a REAL mislabel must still be caught ----
# B0032 and B0034 are different sequences; that swap is CLAUDE.md's worked example of the
# failure this software exists to prevent. It must still FLAG.
b32 = REFS.get("B0032")
check("B0032 and B0034 are genuinely different sequences", b32 and b32 != b34)
if b32:
    seq3 = b32 + REFS["B0015"]
    _, findings3 = audit(seq3, [(1, len(b32), "misc_feature", "B0034"),
                                (len(b32) + 1, len(seq3), "terminator", "B0015")])
    mis3 = by_cat(findings3, "identity-mislabel")
    check("B0032 bases labelled B0034 STILL raise a mislabel FLAG", len(mis3) >= 1,
          "; ".join("%s/%s" % (f.category, f.status) for f in findings3))
    if mis3:
        check("and it is a FLAG, not a note", mis3[0].status == kg_audit.FLAG,
              mis3[0].status)
        check("and the verdict is REVIEW",
              kg_audit.verdict_kind(findings3) == "REVIEW",
              kg_audit.verdict(findings3))

# ---- a claim that matches nothing in the set is still a mislabel ----
_, findings4 = audit(seq, [(1, len(b34), "misc_feature", "B0015"),
                           (len(b34) + 1, len(seq), "terminator", "B0015")])
check("labelling the RBS B0015 -- a real part, wrong bases -- still FLAGs",
      len(by_cat(findings4, "identity-mislabel")) >= 1,
      "; ".join("%s/%s" % (f.category, f.status) for f in findings4))

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
