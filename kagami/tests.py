"""
tests.py — self-contained checks for Kagami. Run: python tests.py
No pytest dependency; plain asserts, exits non-zero on failure.
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import kg_parse
import kg_identify
import kg_audit
import kg_refs
import kg_bridge

N = kg_refs.normalise
# Pin the references these tests identify against. The suite tests KAGAMI, not the catalogue:
# when the shipped set grew to 18,256 parts, seven tests broke because a synthetic poly-A test
# construct started matching a real Registry part, splitting one block into two. A test that can
# be broken by adding data elsewhere is not measuring what it claims to.
#
# Test 15 is unaffected on purpose: it reads the shipped TSV from disk, because the composite
# check SHOULD track the real catalogue.
_PIN = {"J23116", "J23100", "J23106", "B0032", "B0034", "B0015", "sfGFP",
        "RBS_sfGFP_med", "amilCP", "lacZ", "KanR", "cat", "p15A", "pSC101_ori"}
_full = list(kg_refs.REFERENCE_PARTS)
kg_refs.REFERENCE_PARTS[:] = [p for p in _full if p["id"] in _PIN] or _full
if hasattr(kg_refs, "tier"):
    kg_refs.tier.__defaults__[0].clear()      # drop the tier cache built from the full set

R = kg_refs.by_id()
PASS = FLAG = FAIL = 0

# Is blastn actually installed on THIS machine? A handful of assertions below search sequence
# rather than check a claim, and searching is what BLAST+ does; they cannot pass without it. The
# CI image deliberately has no blastn - that is the machine a stranger actually has - so those
# assertions must skip there rather than fail, while everything that does not need the binary
# still runs. Guarding on this rather than on an import is the point: the binary is external.
HAVE_BLAST = bool(shutil.which("blastn") and shutil.which("makeblastdb"))


def check_blast(name, cond):
    """A check that cannot run without blastn installed. Skipped, never failed, when it is absent."""
    if not HAVE_BLAST:
        print(f"  skip {name} (needs BLAST+)")
        return
    check(name, cond)


def _audit_seq(gb_text):
    with tempfile.TemporaryDirectory() as wd:
        p = os.path.join(wd, "c.gb")
        open(p, "w", encoding="utf-8").write(gb_text)
        rec = kg_parse.parse(p)
        blocks = kg_identify.identify(rec, wd)
        finds = kg_audit.audit(rec, blocks)
        return rec, blocks, finds


def _gb(seq, feats):
    lines = ["LOCUS       t %d bp DNA linear SYN" % len(seq),
             "FEATURES             Location/Qualifiers"]
    for kind, label, s, e in feats:
        lines.append("     %-15s %d..%d" % (kind, s, e))
        lines.append('                     /label="%s"' % label)
    lines.append("ORIGIN")
    for i in range(0, len(seq), 60):
        lines.append("%9d %s" % (i + 1, seq[i:i + 60].lower()))
    lines.append("//")
    return "\n".join(lines) + "\n"


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}")


print("Kagami tests")

# 1. mislabel B0032/B0034 is caught
prom = N(R["J23116"]["seq"]); rbs = N(R["B0034"]["seq"]); term = N(R["B0015"]["seq"])
cds = "ATG" + "GCA" * 60 + "TAA"
seq = prom + rbs + "TACTAG" + "AATTAT" + cds + term
feats = [("promoter", "J23116", 1, len(prom)),
         ("RBS", "B0032", len(prom) + 1, len(prom) + len(rbs))]
rec, blocks, finds = _audit_seq(_gb(seq, feats))
mis = [f for f in finds if f.category == "identity-mislabel"]
check("mislabel B0032->B0034 flagged", any("B0034" in f.summary for f in mis))
check("mislabel is a FLAG", all(f.status == "FLAG" for f in mis))

# 2. internal stop -> FAIL
badcds = "ATG" + "AAA" * 4 + "TAA" + "AAA" * 4 + "TAA"
rec, blocks, finds = _audit_seq(_gb(badcds, [("CDS", "broken", 1, len(badcds))]))
check("internal stop -> FAIL", any(f.status == "FAIL" and f.category == "orf" for f in finds))
check("overall verdict FAIL", kg_audit.verdict(finds) == "FAIL")

# 3. clean CDS -> ORF pass, no FAIL
clean = "ATG" + "GCT" * 80 + "TAA"
rec, blocks, finds = _audit_seq(_gb(clean, [("CDS", "clean", 1, len(clean))]))
check("clean ORF passes", any(f.status == "PASS" and f.category == "orf" for f in finds))
check("clean CDS not FAIL", kg_audit.verdict(finds) != "FAIL")

# 4. EcoRI site flagged
seq = prom + "GAATTC" + term
rec, blocks, finds = _audit_seq(_gb(seq, []))
check("EcoRI flagged", any("EcoRI" in f.summary for f in finds if f.category == "restriction"))

# 5. identification independent of the (wrong) claim label
rec, blocks, finds = _audit_seq(_gb(prom + rbs + term,
                                    [("RBS", "TotallyWrongLabel", len(prom) + 1, len(prom) + len(rbs))]))
ids = {b.ident_id for b in blocks if b.ident_id}
check_blast("identity from sequence not label", "B0034" in ids and "J23116" in ids)

# 6. bridge never seals from the construct; unmatched -> unresolved
reqs = kg_bridge.intake_requests(blocks)
check("intake points to primary source", all("this construct" not in r["action"] for r in reqs))
spec_txt = kg_bridge.draft_spec(rec, blocks, finds)
check("draft spec holds no raw sequence",
      "ATGGCT" not in spec_txt and N(R["B0034"]["seq"]) not in spec_txt)

# 7. empty input -> FAIL invariant
rec, blocks, finds = _audit_seq("LOCUS t 0 bp DNA linear SYN\nORIGIN\n//\n")
check("empty sequence -> FAIL", any(f.status == "FAIL" for f in finds))

# 8. tandem stop codons are terminal, not internal.
#    From Caleb's submission, 2026-09-15: sfGFP ends ...CTG TAC AAA TGA TGA. Two stops in a row is
#    deliberate, belt and braces against readthrough. Treating only the LAST codon as terminal
#    reported the first of the pair as a premature stop, so a construct simultaneously reported at
#    100% identity to the reference was failed as truncated.
tandem = "ATG" + "GCT" * 80 + "TGA" + "TGA"
rec, blocks, finds = _audit_seq(_gb(tandem, [("CDS", "tandemstop", 1, len(tandem))]))
check("tandem stop codons are not an internal stop",
      not any(f.status == "FAIL" and f.category == "orf" for f in finds))
check("tandem-stop CDS still ORF-clean",
      any(f.status == "PASS" and f.category == "orf" for f in finds))

# 9. an unrecognised element next to a CDS must not be absorbed into it.
#    Same submission: the CDS ran 1..360 and ended properly with TGA, but 361..378 were the team's
#    S4 RBS, which is not in the public seed set. The gap filler labelled the WHOLE gap "cds", so
#    the block ran 18 bases past the real stop and happened to end on the RBS's last three bases,
#    TAG. A sound CDS was reported as truncated. The CDS block must span the ORF itself.
orf = "ATG" + "GCT" * 80 + "TGA"            # 246 bp, ends with its own stop
mystery = "ACAAAGGACAAATACTAG"              # 18 bp, unknown to the seed set, ends in TAG
tail_term = N(R["B0015"]["seq"])
rec, blocks, finds = _audit_seq(_gb(orf + mystery + tail_term, []))
cds_blocks = [b for b in blocks if b.ident_role == "cds"]
check_blast("CDS block stops at the ORF, not at the end of the gap",
            len(cds_blocks) == 1 and cds_blocks[0].start == 1 and cds_blocks[0].end == len(orf))
check_blast("the unrecognised neighbour becomes its own block",
            any(b.start == len(orf) + 1 and b.end == len(orf) + len(mystery) for b in blocks))
check("absorbed neighbour no longer causes a false internal stop",
      not any(f.status == "FAIL" and f.category == "orf" for f in finds))

# 10. RBS spacing is measured from the Shine-Dalgarno core, not the block edge.
#     Surfaced 2026-09-15 when RBS_sfGFP_med was seeded: Kagami identified it correctly and then
#     flagged "spacing 0 nt" on a construct whose LOCK row records 7. Katana seals an RBS as a
#     FUNCTIONAL UNIT (SD + spacer), so the block ends flush against the ATG and edge-arithmetic
#     returned zero for every RBS sealed that way, which is all of them.
rbs_unit = "ACAAAGGACAAATACTAG"        # RBS_sfGFP_med: SD core AGGACA, then its spacer
cds2 = "ATG" + "GCT" * 60 + "TAA"
rec, blocks, finds = _audit_seq(_gb(rbs_unit + cds2,
                                    [("RBS", "RBS_sfGFP_med", 1, len(rbs_unit)),
                                     ("CDS", "reporter", len(rbs_unit) + 1,
                                      len(rbs_unit) + len(cds2))]))
junc = [f for f in finds if f.category == "junction"]
check("RBS spacing measured from the SD, not the block edge",
      any(f.status == "PASS" and "spacing 8 nt" in f.summary for f in junc))
check("a functional-unit RBS does not report spacing 0",
      not any("spacing 0 nt" in f.summary for f in junc))

# 11. --library loads a Katana library through the same hash gate the library uses on itself.
#     A team running Katana has parts we never shipped. Without this they land in unidentified
#     blocks - and losing identity degrades the DECOMPOSITION, not just the names: with references
#     removed, a real 4-block construct read as one 344 aa minus-strand ORF spanning three parts.
import hashlib

TAB = "\t"
with tempfile.TemporaryDirectory() as _lib:
    _seq = "ATG" + "GCT" * 30 + "TAA"
    _sha = hashlib.sha256(_seq.encode()).hexdigest()
    _fn = "MyPart__v1__" + _sha[:12] + ".gb"
    with open(os.path.join(_lib, _fn), "w", encoding="utf-8") as _f:
        _f.write(_gb(_seq, [("CDS", "MyPart", 1, len(_seq))]))
    _hdr = TAB.join(["id", "version", "seq_sha256", "file_sha256",
                     "length", "source", "date", "class", "outfile"])
    _row = TAB.join(["MyPart", "1", _sha, "-", str(len(_seq)),
                     "in-house design", "2026-09-15", "designed", _fn])
    with open(os.path.join(_lib, "LOCK.tsv"), "w", encoding="utf-8") as _f:
        _f.write(_hdr + "\n" + _row + "\n")

    _parts, _probs = kg_refs.load_katana_library(_lib)
    check("--library loads a hash-verified part", len(_parts) == 1 and not _probs)

    # Flip one base. The recomputed seq_sha256 no longer matches LOCK, so it must be REFUSED
    # rather than loaded - a reference you cannot trust poisons every identification after it.
    with open(os.path.join(_lib, _fn), "w", encoding="utf-8") as _f:
        _f.write(_gb("ATG" + "GCA" + "GCT" * 29 + "TAA",
                     [("CDS", "MyPart", 1, len(_seq))]))
    _parts2, _probs2 = kg_refs.load_katana_library(_lib)
    check("--library refuses a part whose bytes no longer match LOCK",
          not _parts2 and any("seq_sha256" in _x for _x in _probs2))

# 12. --registry checks a CLAIMED label against the Registry. Network is monkeypatched out:
#      a suite that needs the internet fails for reasons unrelated to the code.
import kagami as _kag
import kg_registry as _reg

_REAL = "GGTCTATGAGTGGTTGCTGGATAACT"          # pretend this is what the Registry holds
_FAKE_DB = {"BBa_TEST1": dict(name="BBa_TEST1", uuid="abcdef0123456789", title="t",
                              seq=_REAL, so="SO:0000139", so_label="RBS", role="rbs", usage=1)}
_saved_fetch = _reg.fetch
_reg.fetch = lambda name: _FAKE_DB.get(name)
try:
    def _claim(seq_here):
        _gbt = _gb(seq_here, [("RBS", "BBa_TEST1", 1, len(seq_here))])
        with tempfile.TemporaryDirectory() as _wd:
            _p = os.path.join(_wd, "c.gb")
            open(_p, "w", encoding="utf-8").write(_gbt)
            _rec = kg_parse.parse(_p)
            _blocks = kg_identify.identify(_rec, _wd)
            return _kag.registry_findings(_rec, _blocks)

    _f = _claim(_REAL)
    check("--registry confirms a label that matches the Registry",
          any(x.status == "PASS" and "confirmed" in x.summary for x in _f))

    _f = _claim(_REAL[:14])
    check("--registry reports TRUNCATED, not a flat mismatch",
          any("TRUNCATED" in x.summary for x in _f))

    _f = _claim("TTTTTTTTTTTTTTTTTTTTTTTTTT")
    check("--registry reports a real mismatch",
          any("does NOT match" in x.summary for x in _f))

    _reg.fetch = lambda name: None
    _f = _claim(_REAL)
    check("--registry reports a label the Registry does not hold",
          any("no part called" in x.summary for x in _f))

    def _boom(name):
        raise _reg.RegistryUnavailable("simulated outage")
    _reg.fetch = _boom
    _f = _claim(_REAL)
    check("--registry says 'could not reach', never 'fine'",
          any("Could not reach" in x.summary for x in _f))
finally:
    _reg.fetch = _saved_fetch

# 13. Loose input. Students save .csv and .xlsx, not GenBank; anything unrecognised used to fall
#      through to the GenBank parser and yield garbage. A tool that reads only two formats a
#      beginner has never heard of is a tool beginners cannot use.
_A = "ATG" + "GCT" * 40 + "TAA"
_B = "TTGACAGCTAGCTCAGTCCTAGGTATTATGCTAGC"

with tempfile.TemporaryDirectory() as _d:
    _csv = os.path.join(_d, "s.csv")
    with open(_csv, "w", encoding="utf-8") as _f:
        _f.write("part,sequence,notes\n")
        _f.write("my cds,%s,built in Benchling\n" % _A)
        _f.write("a promoter,%s,from the registry\n" % _B)
    _r = kg_parse.parse(_csv)
    check("csv: DNA cells are found and joined", _r.seq == (_A + _B).upper())
    check("csv: the join is recorded so it can be announced",
          getattr(_r, "assembled_from", None) == [len(_A), len(_B)])
    check("csv: prose columns are not mistaken for DNA",
          "BENCHLING" not in _r.seq and "REGISTRY" not in _r.seq)

    _txt = os.path.join(_d, "s.txt")
    open(_txt, "w", encoding="utf-8").write(_A)
    _r2 = kg_parse.parse(_txt)
    check("txt: a bare pasted sequence parses", _r2.seq == _A.upper())
    check("txt: a single fragment is not announced as a join",
          not getattr(_r2, "assembled_from", []))

    # a real .xlsx, built with stdlib only - the format Casper says students actually use
    import zipfile as _zf
    _NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    _shared = ["part", "sequence", _A, _B]
    _si = "".join("<si><t>%s</t></si>" % _s for _s in _shared)
    _rows = ('<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
             '<row r="2"><c r="A2" t="s"><v>0</v></c><c r="B2" t="s"><v>2</v></c></row>'
             '<row r="3"><c r="A3" t="s"><v>0</v></c><c r="B3" t="s"><v>3</v></c></row>')
    _xl = os.path.join(_d, "s.xlsx")
    with _zf.ZipFile(_xl, "w") as _z:
        _z.writestr("xl/sharedStrings.xml",
                    '<?xml version="1.0"?><sst xmlns="%s">%s</sst>' % (_NS, _si))
        _z.writestr("xl/worksheets/sheet1.xml",
                    '<?xml version="1.0"?><worksheet xmlns="%s"><sheetData>%s</sheetData>'
                    '</worksheet>' % (_NS, _rows))
    _r3 = kg_parse.parse(_xl)
    check("xlsx: DNA cells are found and joined", _r3.seq == (_A + _B).upper())
    check("xlsx: header text is not mistaken for DNA", "SEQUENCE" not in _r3.seq)

# 14. A run that fetches nothing must not destroy what an earlier run fetched.
#      On 2026-09-15 a throttled re-run rewrote a 107-part reference set down to 26: the writer
#      treated every run as authoritative, so a BAD run outranked a GOOD one. For data that is
#      expensive to fetch and free to keep, that is backwards.
import build_refs as _br

with tempfile.TemporaryDirectory() as _rd:
    _tsv = os.path.join(_rd, "reference_parts.tsv")
    _fa = os.path.join(_rd, "reference_parts.fasta")
    TABC = "\t"
    with open(_tsv, "w", encoding="utf-8") as _f:
        _f.write(TABC.join(["id", "registry", "role", "variant", "name", "provenance"]) + "\n")
        _f.write(TABC.join(["FETCHED1", "BBa_X1", "promoter", "", "a fetched part",
                            "iGEM Registry BBa_X1 uuid=deadbeef fetched=2026-09-15"]) + "\n")
        _f.write(TABC.join(["OLDLIB", "", "cds", "", "a library part",
                            "parts-library OLDLIB__v1__aaaaaaaaaaaa.gb [seq_sha256 verified]"]) + "\n")
    with open(_fa, "w", encoding="utf-8") as _f:
        _f.write(">FETCHED1\nACGTACGTACGTACGT\n>OLDLIB\nTTTTTTTTTTTTTTTT\n")

    # this run produced only a library row, as a throttled run would
    _fresh = [("LIBONLY", "", "cds", "", "fresh library part", "parts-library x.gb", "GGGGGGGG")]
    _out, _n = _br._carry_forward_registry_rows(_rd, list(_fresh))
    _ids = {r[0] for r in _out}
    check("carry-forward keeps a previously fetched Registry part",
          "FETCHED1" in _ids and _n == 1)
    check("carry-forward does NOT resurrect a stale library part", "OLDLIB" not in _ids)
    check("carry-forward keeps this run's own rows", "LIBONLY" in _ids)

    # a fresh fetch of the same id must win over the carried copy
    _fresh2 = [("FETCHED1", "BBa_X1", "promoter", "", "refetched",
                "iGEM Registry BBa_X1 uuid=deadbeef fetched=2026-09-16", "CCCCCCCC")]
    _out2, _n2 = _br._carry_forward_registry_rows(_rd, list(_fresh2))
    _row = [r for r in _out2 if r[0] == "FETCHED1"][0]
    check("a freshly fetched row wins over the carried one",
          _row[6] == "CCCCCCCC" and _n2 == 0)

# 15. Composite devices must stay OUT of the reference set, or they swallow their own parts.
#      Measured 2026-09-15: growing the catalogue 60 -> 126 made a construct decompose WORSE.
#      BBa_I746909 ("superfolder GFP driven by T7 promoter", IGEM:0000007 Generator) matched
#      863 bp at 99% and outranked three exact atomic hits, collapsing RBS + sfGFP + terminator
#      into one block and taking the RBS-spacing and ORF checks with it.
check("a Generator is recognised as composite",
      _br._is_composite("iGEM Registry BBa_I746909 uuid=x | IGEM:0000007 Generator"))
check("a Translational Unit is recognised as composite",
      _br._is_composite("iGEM Registry BBa_E0021 uuid=x | IGEM:0000021 Translational Unit"))
check("an atomic part is NOT treated as composite",
      not _br._is_composite("iGEM Registry BBa_B0034 uuid=x | SO:0000139 Ribosome Entry Site"))
# Regulatory is a CATEGORY, not a device: promoters and operators are atomic and must stay in.
check("Regulatory is not excluded",
      not _br._is_composite("iGEM Registry BBa_R0010 uuid=x | IGEM:0000006 Regulatory"))

# and the shipped set must actually be clean of them
_shipped = os.path.join(HERE, "refs", "reference_parts.tsv")
if os.path.exists(_shipped):
    with open(_shipped, "r", encoding="utf-8") as _f:
        _f.readline()
        _bad = [l.split("\t")[0] for l in _f
                if len(l.split("\t")) > 5 and _br._is_composite(l.split("\t")[5])]
    check("the shipped reference set contains no composite devices", not _bad)

# 16. Verdict tiering (2026-09-15). A contextual finding is a NOTE, not a flag, so a genuinely
#      clean construct reads "PASS — N notes" rather than a CONDITIONAL that reads as a problem,
#      while the notes stay visible. Restriction-site severity depends on the chosen assembly;
#      host-homology severity depends on the host's recA status; a not-run check is SKIP and is
#      never counted. Built from the same real parts as Ellie Lin's construct: sfGFP carries one
#      SapI site (GAAGAGC), which is exactly the case that used to inflate a clean audit.
def _finds(seq_text, **kw):
    with tempfile.TemporaryDirectory() as _wd:
        _p = os.path.join(_wd, "c.gb")
        open(_p, "w", encoding="utf-8").write(_gb(seq_text, []))
        _rec = kg_parse.parse(_p)
        _blocks = kg_identify.identify(_rec, _wd)
        return kg_audit.audit(_rec, _blocks, **kw)

_reporter = N(R["J23116"]["seq"]) + N(R["sfGFP"]["seq"]) + N(R["B0015"]["seq"])
_syn = _finds(_reporter)                                   # synthesis (no assembly), no host
_ts = [f for f in _syn if f.category == "restriction" and "SapI" in f.summary]
check("a SapI site is a NOTE when not assembling with SapI",
      bool(_ts) and all(f.status == "NOTE" for f in _ts))
check("host check with no host selected is SKIP, not a flag",
      any(f.category == "host-homology" and f.status == "SKIP" for f in _syn))
check("NOTE + SKIP does not hold back a PASS",
      kg_audit.verdict_kind(_syn) == "PASS")
check("the verdict line reads 'PASS — N notes'",
      kg_audit.verdict(_syn).startswith("PASS — ") and "note" in kg_audit.verdict(_syn))

_sapi_asm = _finds(_reporter, assembly="SapI")
check("the same SapI site becomes an actionable FLAG under SapI assembly",
      any(f.category == "restriction" and f.status == "FLAG" and "SapI" in f.summary
          for f in _sapi_asm))
check("an actionable flag makes verdict_kind REVIEW, not PASS",
      kg_audit.verdict_kind(_sapi_asm) == "REVIEW")

_hostgenome = "AAAAAAAA" + N(R["sfGFP"]["seq"])[80:150] + "AAAAAAAA"   # shares a >40 bp stretch
_hh_plus = _finds(_reporter, host_seq=_hostgenome, host_reca=True)
_hh_minus = _finds(_reporter, host_seq=_hostgenome, host_reca=False)
check("host homology is a FLAG in a recA+ host",
      any(f.category == "host-homology" and f.status == "FLAG" for f in _hh_plus))
check("the same host homology is only a NOTE in a recA- host",
      any(f.category == "host-homology" and f.status == "NOTE" for f in _hh_minus)
      and not any(f.category == "host-homology" and f.status == "FLAG" for f in _hh_minus))
check("verdict_kind is PASS when the only non-pass item is a recA- host note",
      kg_audit.verdict_kind(_hh_minus) == "PASS")

# 17. The bundled host genome the GUI dropdown resolves to is actually present and readable.
_mg = kg_refs.host_genome_path(kg_refs.HOSTS[0][1]["file"])
check("the MG1655 host genome ships and resolves", bool(_mg) and os.path.getsize(_mg) > 1_000_000)

# 18. rebuild's plan() decides, per block, whether a part can be sealed from an independent primary
#     source. Registry parts are fetchable; a designed/non-Registry part or an unidentified block
#     STOPS the rebuild (a part with no independent source cannot be sealed — the core law).
import kg_rebuild


class _B:
    def __init__(self, ident_id=None, ident_registry="", ident_role=None, start=1, end=10):
        self.ident_id = ident_id
        self.ident_registry = ident_registry
        self.ident_role = ident_role
        self.claim_role = None
        self.start = start
        self.end = end
        self.length = end - start + 1


_bl = [_B("J23116", "BBa_J23116", "promoter"),          # fetchable from the Registry
       _B("RBS_sfGFP_med", "", "rbs"),                  # designed / non-Registry -> blocker
       _B(None, "", "cds", 50, 700)]                    # unidentified -> blocker
_parts, _blk = kg_rebuild.plan(_bl)
check("plan: a Registry part is marked fetch",
      any(p["id"] == "J23116" and p["how"] == "fetch" for p in _parts))
check("plan: a designed/non-Registry part blocks the rebuild",
      any(b["id"] == "RBS_sfGFP_med" for b in _blk))
check("plan: an unidentified block blocks the rebuild",
      any("UNRESOLVED" in b["id"] for b in _blk))
_parts2, _blk2 = kg_rebuild.plan(_bl, have={"RBS_sfGFP_med"})
check("plan: a part already in your library is reused, not re-fetched",
      any(p["id"] == "RBS_sfGFP_med" and p["how"] == "reuse" for p in _parts2)
      and not any(b["id"] == "RBS_sfGFP_med" for b in _blk2))
check("find_engine returns None when no engine sits beside Kagami",
      kg_rebuild.find_engine(os.path.join(HERE, "no_such_dir")) is None)

# 18. Identification must never fail SILENTLY (2026-09-24). Found by Andrew Hao's independent
#      test of the published wiki walkthrough: with BLAST+ absent, Kagami reported the demo
#      construct — which carries a PLANTED MISLABEL on purpose — as "PASS, clean to order",
#      exit 0, saying nothing about a skipped step. Two paths in identify() set the identity
#      result to an empty list and continued: BLAST+ missing, and BLAST+ raising. Downstream,
#      blocks read "unidentified", which is ALSO the honest word for a genuine no-match, so the
#      two were indistinguishable. The suite had zero tests mentioning blast in any casing,
#      which is why it survived. These tests fail if that silence ever comes back.
_ident_seq = N(R["J23116"]["seq"]) + N(R["sfGFP"]["seq"]) + N(R["B0015"]["seq"])


def _identify_with(gb_text, have_blast):
    """Run identify() with _have_blast forced, and return (blocks, status)."""
    _real = kg_identify._have_blast
    kg_identify._have_blast = lambda: have_blast
    try:
        with tempfile.TemporaryDirectory() as wd:
            p = os.path.join(wd, "c.gb")
            open(p, "w", encoding="utf-8").write(gb_text)
            rec = kg_parse.parse(p)
            st = {}
            blocks = kg_identify.identify(rec, wd, status=st)
            return rec, blocks, st
    finally:
        kg_identify._have_blast = _real


_gb_text = _gb(_ident_seq, [("misc_feature", "B0032", 1, 35)])
_r_no, _b_no, _st_no = _identify_with(_gb_text, False)
check("identify() reports ran=False when BLAST+ is absent", _st_no.get("ran") is False)
check("identify() names BLAST+ as the reason", "BLAST" in (_st_no.get("reason") or ""))

# Forcing _have_blast True only tells identify() it MAY search; the search then really shells out
# to blastn. On a machine without the binary that is a lie to the function, so the assertion only
# means anything where blastn is actually installed.
_r_yes, _b_yes, _st_yes = _identify_with(_gb_text, True)
check_blast("identify() reports ran=True when BLAST+ is present", _st_yes.get("ran") is True)

# The audit must raise it, and it must be a FLAG — not a SKIP. SKIP is for a check the user
# OPTED OUT of (no host chosen); this is a check they asked for and silently did not get.
# The Registry precedent already grades "could not reach" as FLAG, and identification is the
# more important of the two, so it cannot grade softer.
_f_no = kg_audit.audit(_r_no, _b_no, identify_status=_st_no)
_idf = [f for f in _f_no if f.category == "identification"]
check("audit raises a finding when identification did not run", len(_idf) == 1)
check("that finding is a FLAG, not a SKIP or NOTE", bool(_idf) and _idf[0].status == "FLAG")
check("the finding tells the user how to fix it", bool(_idf) and "BLAST" in _idf[0].fix)

# The verdict is the whole point: it must NOT read clean-to-order.
check("a construct whose identification never ran cannot be PASS",
      kg_audit.verdict_kind(_f_no) == "REVIEW")
check("the CLI exit code for that construct is 5 (REVIEW), not 0",
      {"PASS": 0, "REVIEW": 5, "FAIL": 1}[kg_audit.verdict_kind(_f_no)] == 5)

# A BLAST+ that IS installed but blows up is the same hole, and harder to notice.
_broken = kg_identify._write_ref_db
kg_identify._write_ref_db = lambda wd: (_ for _ in ()).throw(RuntimeError("simulated blast failure"))
try:
    _r_br, _b_br, _st_br = _identify_with(_gb_text, True)
finally:
    kg_identify._write_ref_db = _broken
check("identify() reports ran=False when BLAST+ is present but raises",
      _st_br.get("ran") is False)
check("a raising BLAST+ also cannot produce a PASS",
      kg_audit.verdict_kind(kg_audit.audit(_r_br, _b_br, identify_status=_st_br)) == "REVIEW")

# Callers that pass no status keep the old signature and must not be penalised.
_f_legacy = kg_audit.audit(_r_yes, _b_yes)
check("audit without identify_status raises no identification finding",
      not any(f.category == "identification" for f in _f_legacy))

# 19. The emitted Spec must be valid YAML (2026-09-24, same report). It previously wrote four
#      keys on one aligned line with no separators — `- id: X  role: Y  class: reference` is a
#      single scalar, not three keys — so handing the emitted Spec to forward Katana died on a
#      scanner error and the DOCUMENTED recovery path did not work.
_spec_text = kg_bridge.draft_spec(_r_yes, _b_yes, _f_legacy, vendor="Twist")
try:
    import yaml as _yaml
except ImportError:
    _yaml = None
if _yaml is None:
    check("emitted Spec is valid YAML (SKIPPED — PyYAML not installed)", True)
else:
    try:
        _spec = _yaml.safe_load(_spec_text)
        _ok = True
    except Exception:
        _spec, _ok = None, False
    check("the emitted draft Spec parses as YAML", _ok)
    check("the emitted Spec's parts are real mappings with id/role/class",
          _ok and isinstance(_spec.get("parts"), list) and bool(_spec["parts"])
          and all(isinstance(p, dict) and {"id", "role", "class"} <= set(p)
                  for p in _spec["parts"]))
    check("the emitted Spec carries no raw bases (INTENT only)",
          _ok and not any(isinstance(v, str) and len(v) > 40
                          and set(v.upper()) <= set("ACGTN")
                          for p in _spec["parts"] for v in p.values()))

# 20. The install link must not rot (2026-10-01). A WIST student hit the missing-BLAST+ message,
#      copied the URL out of it, and landed on a 404: the link added on 2026-09-24 pointed at
#      blast.ncbi.nlm.nih.gov/doc/blast-help/downloadblast.html, which NCBI had retired. The
#      message is only as useful as the one thing the reader copies out of it, so a dead link
#      wastes the entire finding. These checks are OFFLINE on purpose — this suite ships with no
#      dependencies and must pass on a machine with no network — so they guard the shape of the
#      link and the return of the known-dead one, not its live status.
_DEAD_URLS = ("doc/blast-help/downloadblast.html",)
# This file is excluded: it has to name the dead URL in order to test for it, and a scanner
# that trips over its own pattern reports a failure that is not there.
_src_files = [f for f in os.listdir(HERE) if f.endswith(".py") and f != "tests.py"]
_offenders = []
for _fn in _src_files:
    try:
        _txt = open(os.path.join(HERE, _fn), encoding="utf-8").read()
    except Exception:
        continue
    for _d in _DEAD_URLS:
        if _d in _txt:
            _offenders.append(f"{_fn}:{_d}")
check("no source file carries a known-dead BLAST+ URL", not _offenders)

_fix_text = (_idf[0].fix if _idf else "")
check("the missing-BLAST+ finding still hands the reader a URL", "http" in _fix_text)
check("that URL is the NCBI installer directory",
      "ftp.ncbi.nlm.nih.gov/blast/executables/blast+/LATEST" in _fix_text)
# A student with no terminal cannot act on "add it to PATH" or "re-run". The fix line is the
# instruction they follow, so it must name a file to click, not a shell concept.
check("the fix names which installer file to take, not a PATH edit",
      "win64.exe" in _fix_text and "PATH" not in _fix_text)

# 21. The not-run wording must match what actually happened (2026-10-01). Without blastn an
#      ANNOTATED record still gets its own claims checked by exact match, so blocks can carry an
#      identity even though identification did not fully run. The flat summary then printed
#      "this audit cannot catch a mislabel" directly above a caught mislabel on demo.gb — a
#      self-contradiction that teaches a reader to stop trusting the tool.
_ann_summary = (_idf[0].summary if _idf else "")
_ann_partial = any(b.ident_id for b in _b_no)
check("the annotated no-BLAST case does identify something by exact match", _ann_partial)
check("its summary does NOT claim a mislabel cannot be caught",
      "cannot catch a mislabel" not in _ann_summary)
check("its summary names the real gap (unlabelled regions)",
      "unlabelled" in _ann_summary)

# The unannotated case must keep the blunt wording, because there nothing was checked at all.
_bare = _gb(_ident_seq, [])          # same bases, no features to check claims against
_r_bare, _b_bare, _st_bare = _identify_with(_bare, False)
_f_bare = kg_audit.audit(_r_bare, _b_bare, identify_status=_st_bare)
_idf_bare = [f for f in _f_bare if f.category == "identification"]
check("an unannotated file identifies nothing without BLAST+",
      not any(b.ident_id for b in _b_bare))
check("and it keeps the blunt 'cannot catch a mislabel' wording",
      bool(_idf_bare) and "cannot catch a mislabel" in _idf_bare[0].summary)
check("both wordings still hold the verdict at REVIEW",
      kg_audit.verdict_kind(_f_bare) == "REVIEW" and kg_audit.verdict_kind(_f_no) == "REVIEW")

# ---- engine tabs: how a run is worded (kg_katana_tabs.classify) ------------------------------
# The Build tab must never call a run PASS when the engine said a gate did not run. classify is a
# pure function, so this needs no window; tkinter is imported at module level, so skip if absent.
print("\nengine tabs: verdict wording")
try:
    import kg_katana_tabs as _kt
except ImportError:
    _kt = None
    print("  skip tkinter not available")
if _kt:
    _sealed = "── Stage 5: Seal ──\n  SEALED: abc123def4567890\n"
    _warn = "  WARN Stage-4b: OFF-TARGET SKIPPED - no genome. NOT enforced this run.\n"
    check("a clean seal reads SEALED / PASS",
          _kt.classify(0, _sealed, False)[:2] == ("PASS", "SEALED"))
    check("a seal with a gate that did not run is REVIEW, not PASS",
          _kt.classify(0, _warn + _sealed, False)[0] == "REVIEW")
    check("...and the headline says so in words",
          "gate did not run" in _kt.classify(0, _warn + _sealed, False)[1])
    check("a dry run with an unenforced gate is REVIEW",
          _kt.classify(0, _warn, True)[0] == "REVIEW")
    check("a clean dry run says nothing was written",
          "nothing was written" in _kt.classify(0, "ok\n", True)[2])
    check("exit 0 with no SEALED line is not called sealed",
          _kt.classify(0, "ok\n", False)[0] == "REVIEW")
    check("a non-zero exit is BLOCKED and quotes the BLOCK line",
          _kt.classify(1, "x\nBLOCK: spec file not found\n", False)
          == ("FAIL", "BLOCKED", "BLOCK: spec file not found"))
    check("a crash with no BLOCK line still fails, quoting the last line",
          _kt.classify(1, "Traceback\nValueError: boom\n", False)[::2] == ("FAIL", "ValueError: boom"))

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
