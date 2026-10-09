"""test_host_scan.py — the host off-target number must be the length, not a ceiling.

Run: python3 tests/test_host_scan.py

Found by reading the host dropdown after the user asked whether its two options were
enough. The options were a symptom; the measurement underneath was the defect.

`_longest_shared(seq, genome, cap=60)` stopped counting at 60. Measured, against the
bundled MG1655 chromosome:

    3000 bp of verbatim host DNA  ->  reported  60 bp   (50x understated)
     500 bp of verbatim host DNA  ->  reported  60 bp   ( 8x understated)

and the finding printed that ceiling as though it were a measurement:

    [FLAG] host-homology    60 bp exact match to the host chromosome (>40 bp)
           -> fix: Recode/replace the host-identical stretch, or clone/propagate in a
              recA- strain.

The verdict was in the safe direction -- over 40 bp is a FLAG either way -- so this is
not a missed finding. It is a misstated one, and the fix line is advice for 60 bp.
Three thousand bases of verbatim chromosome is not a stretch to recode; it is a question
about whether the right part is in the construct at all.

It was not hypothetical. The project's own flagship construct, pSense-Nit -- the ORACLE
this branch asserts everywhere -- has a 147 bp exact match to MG1655, reported as 60.

Two things this pins. The number is the length, up to a stated cap, and when the cap is
reached the text says "at least". And above gene scale the recA- downgrade stops
applying: recA governs whether a short homology is a recombination substrate, and that
is the wrong question to ask about a kilobase of verbatim chromosome.

Also here: the browser can reach a genome other than the bundled one. The build side
offers 23 hosts (get_genome.py, including E. coli Nissle 1917), the desktop audit can
browse to any file, and the browser could only ever check against MG1655 -- with nothing
saying so.

No sequence in this file was written by hand. Every test sequence is a slice of the
bundled primary-source genome, so a fixture here cannot become a false claim about a
part.
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

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  [" + str(detail)[:320] + "]") if detail else ""))


print("host off-target scan")

# ---- the premise: one bundled genome, read from the file, not from memory ----
_gpath = kg_refs.host_genome_path("MG1655_ecoli_NC_000913.3.fna")
check("the bundled host genome is present", bool(_gpath), _gpath)
if not _gpath:
    print("\n%d passed, %d failed" % (PASS, FAIL))
    sys.exit(1)

GENOME = "".join(l.strip() for l in open(_gpath, encoding="utf-8")
                 if not l.startswith(">")).upper()
check("and is chromosome-sized (%d bp)" % len(GENOME), len(GENOME) > 4000000, len(GENOME))

# A locus to cut verbatim slices from. Any locus works; this one is fixed so the
# numbers below are reproducible.
P = 1000000


def slice_of(n):
    """n bases taken verbatim from the bundled chromosome."""
    return GENOME[P:P + n]


# ---- the number must be the length ----
# A slice of n bases cannot report more than n, so an exact answer here IS n.
for _n in (41, 61, 100, 147, 300, 499):
    _got = kg_audit._longest_shared(slice_of(_n), GENOME)
    check("%d bp of verbatim host DNA reports %d, not a ceiling" % (_n, _n),
          _got == _n, "reported %d" % _got)

# ---- above the cap, the text must say so rather than state the cap as a fact ----
CAP = kg_audit.HOST_MATCH_CAP
check("there is a stated cap, and it is far above the old 60 (%d)" % CAP,
      CAP >= 500, CAP)
_big = kg_audit._longest_shared(slice_of(CAP + 2000), GENOME)
check("a match past the cap is reported as the cap, not silently more",
      _big == CAP, _big)


def audit_seq(seq, **kw):
    """Audit a bare sequence with no feature claims."""
    d = tempfile.mkdtemp(prefix="hostscan_")
    path = os.path.join(d, "t.gb")
    out = ["LOCUS       t %13d bp    DNA     linear   SYN" % len(seq),
           "FEATURES             Location/Qualifiers", "ORIGIN"]
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
    return kg_audit.audit(rec, bl, identify_status=st, **kw)


def host_finding(findings):
    hs = [f for f in findings if f.category == "host-homology"]
    return hs[0] if hs else None


# ---- the reported text ----
_f = host_finding(audit_seq(slice_of(147), host_seq=GENOME, host_reca=True))
check("the finding states the measured length", _f and "147" in _f.summary,
      _f and _f.summary)
check("and does not state the old ceiling", _f and "60 bp" not in _f.summary,
      _f and _f.summary)

_f = host_finding(audit_seq(slice_of(CAP + 2000), host_seq=GENOME, host_reca=True))
check("a capped measurement is reported as a floor, not a fact",
      _f and ("at least" in _f.summary.lower()), _f and _f.summary)

# ---- gene scale: recA stops being the question ----
SCALE = kg_audit.HOST_GENE_SCALE
check("gene scale is defined and above the substrate threshold (%d)" % SCALE,
      SCALE > 40, SCALE)

_f = host_finding(audit_seq(slice_of(SCALE + 100), host_seq=GENOME, host_reca=False))
check("a kilobase of verbatim chromosome is a FLAG even in a recA- strain",
      _f and _f.status == kg_audit.FLAG, _f and "%s | %s" % (_f.status, _f.summary))
check("and says it is not a recombination question",
      _f and "recombin" not in (_f.summary + (_f.detail or "")).lower().split("recA")[0]
      or (_f and "which part" in (_f.detail or "").lower()
          or "intended" in (_f.detail or "").lower()),
      _f and (_f.detail or "")[:200])
check("and does not tell them to recode it",
      _f and "recode" not in (_f.fix or "").lower(), _f and _f.fix)

# ---- below gene scale, the recA- downgrade is unchanged ----
_f = host_finding(audit_seq(slice_of(60), host_seq=GENOME, host_reca=False))
check("a 60 bp match in a recA- strain is still only a NOTE",
      _f and _f.status == kg_audit.NOTE, _f and "%s | %s" % (_f.status, _f.summary))
_f = host_finding(audit_seq(slice_of(60), host_seq=GENOME, host_reca=True))
check("and still a FLAG in a recA+ host",
      _f and _f.status == kg_audit.FLAG, _f and _f.status)

# ---- under the threshold: PASS, without claiming a precision it does not have ----
# A 12-base seed search cannot report the exact longest match when that match is
# shorter than the seed, so the PASS must not print a number as though it could.
_far = GENOME[3000000:3000400]
_f = host_finding(audit_seq(_far, host_seq=GENOME[:2000000], host_reca=True))
check("an unrelated sequence passes the host check",
      _f and _f.status == kg_audit.PASS, _f and "%s | %s" % (_f.status, _f.summary))
check("and the PASS states the threshold, not a precise short length",
      _f and "40" in _f.summary, _f and _f.summary)

# ---- no host selected is still a visible SKIP, never a pass ----
_f = host_finding(audit_seq(slice_of(200)))
check("no host selected is a SKIP", _f and _f.status == kg_audit.SKIP,
      _f and _f.status)
check("and the SKIP says what to do about it",
      _f and "choose a host" in ((_f.detail or "") + (_f.fix or "")).lower(),
      _f and ((_f.detail or "") + (_f.fix or ""))[:160])

# ---- the real construct: this was not hypothetical ----
_out = tempfile.mkdtemp(prefix="hostreal_")
_p = subprocess.run([sys.executable, "katana_build.py",
                     os.path.join(ROOT, "specs", "pSense-Nit.spec.yaml"),
                     "--outdir", _out],
                    cwd=ROOT, capture_output=True, text=True, timeout=900)
_gb = [f for f in os.listdir(_out) if f.endswith(".gb")]
check("Katana builds pSense-Nit", _gb, (_p.stdout + _p.stderr)[-200:])
if _gb:
    _seq = kg_parse.parse(os.path.join(_out, _gb[0])).seq
    check("whose sequence is the ORACLE construct", len(_seq) == 1013, len(_seq))
    _real = kg_audit._longest_shared(_seq, GENOME)
    check("its host match is longer than the old ceiling reported (%d bp > 60)" % _real,
          _real > 60, _real)

# ---- the browser must be able to reach a genome other than the bundled one ----
_html = open(os.path.join(ROOT, "ui", "web", "index.html"), encoding="utf-8").read()
_js = open(os.path.join(ROOT, "ui", "web", "index.js"), encoding="utf-8").read()

# Asserted against the host <select> itself, not the page. "upload" alone passes on the
# page's own privacy copy ("Nothing is uploaded"), which is a promise the genome keeps
# too -- it is read into the in-browser filesystem and never sent anywhere -- so the
# control is named for a local file rather than an upload.
_sel = _html.split('<select id="host"')[1].split("</select>")[0] if \
    '<select id="host"' in _html else ""
check("the browser has a host <select>", bool(_sel))
_opts = [o.split(">")[1] if ">" in o else "" for o in _sel.split("<option ")[1:]]
check("whose menu offers a genome file from this computer (%d options)" % len(_opts),
      'value="local"' in _sel, _sel.strip()[:300])
check("and there is a file input to supply it",
      'id="genomefile"' in _html and "genomefile" in _js)
check("the chosen genome is written into the engine's own filesystem",
      "writeFile" in _js and "LOCAL_GENOME" in _js)
check("a genome chosen this way assumes recA+, the worst case, as the desktop does",
      "UPLOAD_RECA = null" in _js,
      [l.strip() for l in _js.splitlines() if "UPLOAD_RECA" in l][:2] or "absent")
check("and the page says where to get a genome file for another host",
      "get_genome" in _html or "get_genome" in _js)
check("and still promises nothing leaves the machine", "Nothing is uploaded" in _html)

# A genome the engine cannot read must say it was the GENOME. The sequence under audit
# and the genome are two files, the error only ever names one, and "_local_genome: the
# LOCUS line declares 100 bp" tells a student nothing about which of their two files is
# the problem.
_fn = _js.split("async function ensureLocalGenome")[1].split("\n}")[0] \
    if "async function ensureLocalGenome" in _js else ""
check("the genome is written under the person's OWN filename, not a fixed path",
      "writeFile" in _fn and "localGenomePath" in _fn
      and "f.name.replace" in _fn, _fn[:400] or "absent")
# index.js has more than one embedded Python block (boot, then audit); the host read is
# in whichever one mentions it, so look at all of them.
_blocks = [b.split("`)")[0] for b in _js.split("runPythonAsync(`")[1:]]
_pyblock = next((b for b in _blocks if "_host_file" in b), "")
check("the audit's Python block reads the chosen genome", bool(_pyblock),
      "%d embedded blocks, none mentioning _host_file" % len(_blocks))
check("and a genome that cannot be read is reported as the genome, not the sequence",
      "host genome" in _pyblock.lower()
      and "was not the problem" in _pyblock.lower(),
      [l.strip() for l in _pyblock.splitlines() if "host_file" in l or "genome" in l][:4])

# ---- a genome in many records must be searched in full ----
# The off-target haystack is the whole genome. S. cerevisiae ships as 16 records and
# K. phaffii as 4, so a reader that kept only the first chromosome would quietly check
# a construct against a sixteenth of the genome and call it clean.
_d = tempfile.mkdtemp(prefix="multifa_")
_multi = os.path.join(_d, "two_records.fna")
_r1, _r2 = GENOME[200000:200600], GENOME[2500000:2500600]
with open(_multi, "w", encoding="utf-8") as _f:
    for _nm, _r in (("chrA", _r1), ("chrB", _r2)):
        _f.write(">%s a slice of the bundled chromosome\n" % _nm)
        for _i in range(0, len(_r), 60):
            _f.write(_r[_i:_i + 60] + "\n")
_read = kg_parse.parse(_multi).seq
check("a multi-record FASTA genome keeps every record (%d bp of %d)"
      % (len(_read), len(_r1) + len(_r2)),
      len(_read) == len(_r1) + len(_r2), len(_read))
check("so a construct matching the SECOND record is still found",
      kg_audit._longest_shared(_r2[:300], _read) == 300,
      kg_audit._longest_shared(_r2[:300], _read))
check("and one matching only the first is found too",
      kg_audit._longest_shared(_r1[:300], _read) == 300,
      kg_audit._longest_shared(_r1[:300], _read))

# The desktop already had this; the two front ends must not disagree about the presets.
_gui = open(os.path.join(ROOT, "kagami", "kagami_gui.py"), encoding="utf-8").read()
check("desktop and browser offer the same number of preset hosts",
      _html.count("mg1655-") == len(kg_refs.HOSTS),
      "%d in the page vs %d in kg_refs" % (_html.count("mg1655-"), len(kg_refs.HOSTS)))
check("both presets still name the one bundled genome",
      len({m["file"] for _, m in kg_refs.HOSTS}) == 1,
      str([m["file"] for _, m in kg_refs.HOSTS]))

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
