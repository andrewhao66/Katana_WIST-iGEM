#!/usr/bin/env python3
"""
Katana Stage-4b -- dry-lab AUTO-GATE. Runs inside every katana_build.py build, between
Stage-4 (validate) and Stage-5 (seal), so off-target + codon-quality are ENFORCED, not
asked-for. Returns (blocks, warns, infos); a BLOCK stops the seal.

OFF-TARGET (blastn vs the host genome from constraints.host_context, via blast_offtarget's
pure-Python seed-extend -- no BLAST+/makeblastdb, robust on the Drive mount):
  - Expected = a hit within +/-2kb of a host-derived part's genome locus (spec source coords,
    host accession). Reported, not blocked.
  - BLOCK  = a >=95% id, >=100 bp host hit NOT at any expected locus (a long high-identity host
    match that no intended host part explains = misassembly / wrong part / recode reconstructing
    a host gene). Long high-id hits are ~never coincidental.
  - WARN   = a 40-100 bp unexpected hit (native terminator / coincidental codon homology -- surfaced
    for eyeball, not blocked).

CODON QUALITY (real E. coli CAI via python_codon_tables) for every class=designed CDS:
  - BLOCK below 0.75, WARN below 0.80.

Missing dep/genome -> LOUD WARN (surfaced, never silently skipped). Tighten thresholds in
KATANA_SPEC as the expected-locus map matures.
"""
import sys, re
from pathlib import Path

HOST_GENOME = {"E_coli_MG1655": "MG1655_ecoli_NC_000913.3.fna",
               "E_coli_K12":    "MG1655_ecoli_NC_000913.3.fna"}
HOST_ACCESSION = {"E_coli_MG1655": "NC_000913.3", "E_coli_K12": "NC_000913.3"}
CAI_BLOCK, CAI_WARN = 0.75, 0.80
SCAN_ID, SCAN_LEN = 80.0, 40
BLOCK_ID, BLOCK_LEN = 95.0, 100

def _find_ref_parts(here):
    """Walk up from `here` to find parts-library/ref_parts, at any depth.
    (Depth-independent on purpose: a fixed parents[N] overshoots in a published
    repo layout, and an absolute fallback would hard-code one machine's paths.)"""
    for c in (q / "parts-library" / "ref_parts" for q in (here, *here.parents)):
        if c.is_dir():
            return c
    return None

def _expected_loci(spec):
    """Genome loci (start,end) of host-derived reference parts (source db=NCBI, host accession)."""
    host = str(spec.get("constraints", {}).get("host_context") or spec.get("host"))
    acc = HOST_ACCESSION.get(host)
    loci = []
    if not acc: return loci
    for p in spec.get("parts", []):
        src = p.get("source", {}) or {}
        if str(src.get("accession", "")).startswith(acc):
            co = str(src.get("coords", ""))
            m = re.search(r"(\d+)\D+(\d+)", co)
            if m:
                a, b = int(m.group(1)), int(m.group(2))
                loci.append((min(a, b), max(a, b), p.get("id", "?")))
    return loci

def _cai_weights():
    try:
        import python_codon_tables as pct
        tbl = pct.get_codons_table("e_coli_316407"); W = {}
        for aa, d in tbl.items():
            mx = max(d.values()) or 1.0
            for c, f in d.items(): W[c.upper().replace("U", "T")] = f / mx if mx else 0.0
        return W
    except Exception:
        return None

def run_drylab_gate(insert_seq, features, spec, resolved, here):
    from math import exp, log
    blocks, warns, infos = [], [], []
    print("── Stage 4b: dry-lab gate (off-target + codon quality) ──")
    ref_parts = _find_ref_parts(here)

    # ---------- OFF-TARGET ----------
    host = str(spec.get("constraints", {}).get("host_context") or spec.get("host"))
    gfile = HOST_GENOME.get(host)
    genome = (ref_parts.parent / "ref_genomes" / gfile) if (ref_parts and gfile) else None
    if not genome or not genome.exists():
        warns.append("WARN Stage-4b: OFF-TARGET SKIPPED — no genome for host '%s'. NOT enforced this run "
                     "(add to katana_drylab.HOST_GENOME + ref_genomes/)." % host)
    else:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import blast_offtarget as B  # vendored alongside this module
            g = B.read_fasta(str(genome))[1]
            rows = B.fallback(insert_seq.upper(), g, SCAN_ID, SCAN_LEN, 13)
            loci = _expected_loci(spec)
            if not rows:
                infos.append("INFO Stage-4b: off-target — no host homology >= %g%%/%dbp." % (SCAN_ID, SCAN_LEN))
            for (ln, idp, gs, ge, st) in rows[:40]:
                lo, hi = min(gs, ge), max(gs, ge)
                exp_hit = next((pid for (a, b, pid) in loci if not (hi < a - 2000 or lo > b + 2000)), None)
                if exp_hit:
                    infos.append("INFO Stage-4b: off-target %dbp %.1f%% @%d-%d = expected host part '%s'." % (ln, idp, gs, ge, exp_hit))
                elif ln >= BLOCK_LEN and idp >= BLOCK_ID:
                    blocks.append("BLOCK Stage-4b: UNEXPECTED host homology %dbp %.1f%% @%d-%d — not any intended host part "
                                  "(misassembly / wrong part / recode artifact)." % (ln, idp, gs, ge))
                else:
                    warns.append("WARN Stage-4b: off-target %dbp %.1f%% @%d-%d not at an expected locus "
                                 "(likely native terminator / coincidental) — REVIEW." % (ln, idp, gs, ge))
        except Exception as e:
            warns.append("WARN Stage-4b: off-target scan error (%r). NOT enforced this run." % e)

    # ---------- CODON QUALITY (designed CDS) ----------
    W = _cai_weights()
    cls = {p.get("id"): (p.get("class", ""), p.get("role", "")) for p in spec.get("parts", [])}
    designed_cds = [pid for pid, (c, r) in cls.items() if c == "designed" and r in ("cds", "reporter")]
    if not designed_cds:
        infos.append("INFO Stage-4b: no designed CDS to codon-check.")
    elif W is None:
        warns.append("WARN Stage-4b: CAI SKIPPED — python_codon_tables not installed (py -m pip install "
                     "python_codon_tables). NOT enforced this run.")
    else:
        for pid in designed_cds:
            seq = (resolved.get(pid, {}) or {}).get("seq", "").upper()
            if len(seq) < 6: continue
            cs = [seq[i:i+3] for i in range(0, len(seq)-2, 3)]
            ws = [W.get(c, 0.01) or 0.01 for c in cs]
            cai = exp(sum(log(w) for w in ws) / len(ws))
            if cai < CAI_BLOCK:
                blocks.append("BLOCK Stage-4b: designed CDS '%s' real CAI %.3f < %.2f floor — re-optimise (optimize-codons)." % (pid, cai, CAI_BLOCK))
            elif cai < CAI_WARN:
                warns.append("WARN Stage-4b: designed CDS '%s' real CAI %.3f < %.2f — consider re-optimising." % (pid, cai, CAI_WARN))
            else:
                infos.append("INFO Stage-4b: designed CDS '%s' real CAI %.3f (ok)." % (pid, cai))
    return blocks, warns, infos
