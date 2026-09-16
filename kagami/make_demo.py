"""
make_demo.py — build examples/demo.gb from the seed reference set so the demo is
internally self-consistent (identification is guaranteed correct) while still
demonstrating the real catches:
  * an RBS annotated "B0032" whose sequence is actually B0034 (the signature bug)
  * a clean CDS (ORF-clean, in frame)
  * an EcoRI site in a junction (BioBrick-incompatible flag)
  * an intact B0015 terminator
Expected verdict: CONDITIONAL.
"""
import os
import random
import kg_refs

random.seed(7)
refs = kg_refs.by_id()

CODONS = [a + b + c for a in "ACGT" for b in "ACGT" for c in "ACGT"
          if (a + b + c) not in ("TAA", "TAG", "TGA")]


def make_orf(aa=218):
    body = "".join(random.choice(CODONS) for _ in range(aa - 2))
    seq = "ATG" + body + "TAA"
    # scrub accidental EcoRI/XbaI/SpeI/PstI inside the CDS to keep it clean
    for site in ("GAATTC", "TCTAGA", "ACTAGT", "CTGCAG"):
        seq = seq.replace(site, site[:3] + "A" + site[4:])
    return seq


def norm(pid):
    return kg_refs.normalise(refs[pid]["seq"])


promoter = norm("J23116")                 # weak Anderson promoter
# The RBS FEATURE is exactly B0034 (strong), but we LABEL it B0032 (weak): the signature mislabel.
# It must be exactly B0034 with nothing appended - an earlier version appended a "TACTAG" scar, and
# B0034+TACTAG is itself a real 18 bp Registry part (BBa_K2066527), so at full catalogue scale the
# auditor correctly named THAT instead of B0034 and the demo stopped teaching its own lesson.
rbs_seq = norm("B0034")                   # B0034 (strong) - but LABELLED B0032 below
spacer = "CACAACA"                        # 7 nt benign spacer (no part collision, no RE site)
cds = make_orf(218)
junction = "GAATTC"                        # EcoRI site in the CDS→terminator junction (flag)
term = norm("B0015")

parts = [
    ("promoter", "J23116", promoter),
    ("RBS", "B0032", rbs_seq),            # <-- deliberate mislabel: seq is B0034
    ("spacer", "", spacer),
    ("CDS", "reporter_cds", cds),
    ("misc_feature", "EcoRI_junction", junction),
    ("terminator", "B0015", term),
]

seq = ""
feats = []
pos = 1
for kind, label, s in parts:
    start = pos
    end = pos + len(s) - 1
    if label:
        feats.append((kind, label, start, end))
    seq += s
    pos = end + 1

os.makedirs(os.path.join(os.path.dirname(__file__), "examples"), exist_ok=True)
out = os.path.join(os.path.dirname(__file__), "examples", "demo.gb")

with open(out, "w", encoding="utf-8") as f:
    f.write(f"LOCUS       demo_pSense_dual        {len(seq)} bp    DNA     linear   SYN\n")
    f.write("DEFINITION  Kagami demo construct (contains a deliberate B0032/B0034 mislabel).\n")
    f.write("FEATURES             Location/Qualifiers\n")
    for kind, label, s, e in feats:
        f.write(f"     {kind:<15} {s}..{e}\n")
        f.write(f'                     /label="{label}"\n')
    f.write("ORIGIN\n")
    for i in range(0, len(seq), 60):
        chunk = seq[i:i + 60].lower()
        blocks = " ".join(chunk[j:j + 10] for j in range(0, len(chunk), 10))
        f.write(f"{i+1:>9} {blocks}\n")
    f.write("//\n")

print(f"wrote {out}  ({len(seq)} bp)")
