"""test_circular.py — a plasmid is circular, and a part may sit across its origin.

Run: python3 tests/test_circular.py

Two findings from an independent Codex review, reproduced.

1. CIRCULAR TOPOLOGY WAS IGNORED. identify() read record.seq linearly whatever the record
   said. Measured on B0015 as a 129 bp circle: rotating the origin by 26 bases produced
   two hits -- coverage 0.798 and 0.202 -- so the whole part was present and the audit
   raised a truncation FLAG saying 80% of it was there. Rotating by 65 gave two
   half-length pieces.

   This is not an edge case. An iGEM construct IS a plasmid, and where the origin falls
   is an arbitrary choice made by whoever exported the file -- often the cloning site,
   which sits right next to the parts. A false truncation FLAG on a correct plasmid, for
   a reason the student cannot see, is the cry-wolf failure again: once they learn the
   warnings are noise, the real one goes past them too.

2. THE FIFTH OCCURRENCE WAS DROPPED IN SILENCE. MAX_LOCI is 4. Five tandem copies of
   B0015 returned hits at 1-129, 130-258, 259-387 and 388-516; 517-645 was simply
   missing, so a wrong label on that fifth copy received no identity comparison at all.

   Raising the cap is not the fix -- any cap drops the next one. The fix is to SAY SO.
   That is this project's own SKIP principle: "we did not check" must never read as
   "checked and fine".
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
import kg_seedmatch as sm

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
L = len(B15)
ONLY15 = [r for r in FULL if r["id"] == "B0015"]


def pinned(ids):
    """Restrict the reference set, so a test measures one thing."""
    kg_refs.REFERENCE_PARTS[:] = [r for r in FULL if r["id"] in ids]
    if hasattr(kg_refs, "tier"):
        kg_refs.tier.__defaults__[0].clear()


def unpinned():
    kg_refs.REFERENCE_PARTS[:] = FULL
    if hasattr(kg_refs, "tier"):
        kg_refs.tier.__defaults__[0].clear()


def audit_seq(seq, topology="linear", feats=()):
    d = tempfile.mkdtemp(prefix="circ_")
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


print("circular topology and repeated parts")

# ---- the premise ----
_rec, _bl, _fs, _st = audit_seq(B15, topology="circular")
check("a circular record is parsed as circular", _rec.topology == "circular",
      _rec.topology)

# ---- a part split across the origin must be found whole ----
pinned({"B0015"})
try:
    for rot in (26, 65, 100):
        rotated = B15[rot:] + B15[:rot]
        hits = sm.identify_hits(rotated, ONLY15, circular=True)
        best = max(hits, key=lambda h: h["cov"]) if hits else None
        check("origin rotated by %3d: B0015 is found at full coverage" % rot,
              best is not None and best["cov"] > 0.99,
              str([(h["pident"], round(h["cov"], 3), h["qstart"], h["qend"])
                   for h in hits]))
        if best:
            check("  and at full identity", best["pident"] > 99.0, best["pident"])

    # A linear record must NOT get the wrap treatment: a linear fragment that happens to
    # end where it began is not a circle, and claiming the part is whole would be a
    # different false statement.
    rotated = B15[26:] + B15[:26]
    lin = sm.identify_hits(rotated, ONLY15, circular=False)
    check("a LINEAR record is still read linearly, so the split is reported",
          lin and max(h["cov"] for h in lin) < 0.99,
          str([(h["pident"], round(h["cov"], 3)) for h in lin]))

    # End to end, through the audit: no false truncation on a correct plasmid.
    _rec, _bl, _fs, _st = audit_seq(B15[26:] + B15[:26], topology="circular")
    _trunc = [f for f in _fs if f.category == "truncation"]
    check("a correct circular plasmid raises NO truncation FLAG", not _trunc,
          "; ".join(f.summary for f in _trunc))
    _ident = [b for b in _bl if b.ident_id == "B0015"]
    check("and B0015 is identified on it", _ident,
          str([(b.ident_id, b.coverage) for b in _bl]))
    if _ident:
        check("  at full coverage", _ident[0].coverage > 0.99, _ident[0].coverage)
        check("  and the block says it crosses the origin",
              getattr(_ident[0], "wraps_origin", False) is True,
              str(getattr(_ident[0], "wraps_origin", "absent")))

    # A genuinely truncated part on a circular plasmid must still be caught -- the wrap
    # must not become a way of excusing a short part.
    _rec, _bl, _fs, _st = audit_seq("T" * 200 + B15[:103] + "T" * 200,
                                    topology="circular")
    check("a genuinely truncated part on a circular plasmid IS still flagged",
          [f for f in _fs if f.category == "truncation"],
          str([(f.category, f.summary) for f in _fs]))

    # ---- the cap on reported occurrences must be stated, not silent ----
    for n in (4, 5, 7):
        hits = sm.identify_hits(B15 * n, ONLY15)
        fwd = [h for h in hits if h["strand"] == 1]
        capped = any(h.get("loci_capped") for h in hits)
        check("%d tandem copies: %d reported, cap reached = %s"
              % (n, len(fwd), capped),
              (len(fwd) == n and not capped) or (n > sm.MAX_LOCI and capped),
              "%d hits, capped=%s" % (len(fwd), capped))

    _rec, _bl, _fs, _st = audit_seq(B15 * 6, topology="linear")
    _part = [f for f in _fs if f.category == "identification-partial"]
    check("six tandem copies raise a finding saying not all were examined",
          len(_part) == 1, str([(f.category, f.status) for f in _fs]))
    if _part:
        check("  and it is a FLAG or a SKIP, never a PASS",
              _part[0].status in (kg_audit.FLAG, kg_audit.SKIP), _part[0].status)
        check("  and it names the part and how many it reported",
              "B0015" in _part[0].summary or "B0015" in (_part[0].detail or ""),
              _part[0].summary)

    _rec, _bl, _fs, _st = audit_seq(B15 * 3, topology="linear")
    check("three copies -- under the cap -- raise no such finding",
          not [f for f in _fs if f.category == "identification-partial"],
          str([f.category for f in _fs]))
finally:
    unpinned()

# ---- the demo and the oracle must be untouched ----
demo = os.path.join(ROOT, "kagami", "examples", "demo.gb")
if os.path.isfile(demo):
    record = kg_parse.parse(demo)
    status = {}
    with tempfile.TemporaryDirectory() as wd:
        dblocks = kg_identify.identify(record, wd, status=status)
    dfind = kg_audit.audit(record, dblocks, identify_status=status)
    check("the demo still catches its planted mislabel",
          any(f.category == "identity-mislabel" for f in dfind),
          str([f.category for f in dfind]))
    check("and gains no spurious partial-identification finding",
          not [f for f in dfind if f.category == "identification-partial"],
          str([f.category for f in dfind]))

import subprocess

p = subprocess.run([sys.executable, "katana_build.py",
                    "specs/pSense-Nit.spec.yaml", "--dry-run"],
                   cwd=ROOT, capture_output=True, text=True, timeout=600)
check("the sealed construct hash is unchanged",
      "796e94a0ea2452edd2ce59ca30b8f28fea232b37ab2a036714239069fd1196f5" in p.stdout,
      p.stdout[-200:])

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
