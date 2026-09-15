"""
kg_audit.py — the AUDIT. This is Kagami's reason to exist: not "what parts are in
here" (annotation, already solved) but "is each part what it claims to be, and is
the construct actually buildable and clean" — with a reason and a fix per finding.

The checks reuse Katana's forward conventions verbatim so a Kagami PASS means the
same thing a katana-validate PASS does:
  - forbidden restriction / Type IIS site definitions  (forbid_sites_check.py)
  - >~40 bp host-homology recombination-substrate rule (host_homology_check.py)
  - junction rules: RBS→ATG spacing 5–9 nt, no spurious internal ATG/stop
"""
from kg_parse import revcomp
import kg_refs

# --- enzyme sites, copied from parts-library/_tools/forbid_sites_check.py ---
TYPEIIS = {"BsmBI": "CGTCTC", "BsaI": "GGTCTC", "SapI": "GCTCTTC"}
SIXCUT = {"NcoI": "CCATGG", "EcoRI": "GAATTC", "XbaI": "TCTAGA",
          "SpeI": "ACTAGT", "PstI": "CTGCAG"}
# RFC[10] BioBrick-incompatible sites: presence breaks BioBrick assembly.
BIOBRICK_FORBIDDEN = ("EcoRI", "XbaI", "SpeI", "PstI")

STOPS = {"TAA", "TAG", "TGA"}

PASS, FLAG, FAIL = "PASS", "FLAG", "FAIL"


class Finding:
    def __init__(self, category, status, summary, loc="", detail="", fix=""):
        self.category = category
        self.status = status      # PASS / FLAG / FAIL
        self.summary = summary
        self.loc = loc
        self.detail = detail
        self.fix = fix


def _site_positions(seq, site):
    rc = revcomp(site)
    L = len(site)
    pos = []
    for i in range(len(seq) - L + 1):
        w = seq[i:i + L]
        if w == site or w == rc:
            pos.append(i + 1)
    return pos


def _gc(seq):
    if not seq:
        return 0.0
    g = sum(seq.count(b) for b in "GC")
    return 100.0 * g / len(seq)


def _longest_homopolymer(seq):
    best, run, prev = 1, 1, ""
    for c in seq:
        if c == prev:
            run += 1
            best = max(best, run)
        else:
            run, prev = 1, c
    return best


def _longest_direct_repeat(seq, kmin=20, cap=4000):
    """Cheap direct-repeat probe: does any k-mer occur twice? Binary search k.
    Capped for speed on large inputs (a coarse misassembly flag, not an aligner)."""
    s = seq[:cap] if len(seq) > cap else seq
    lo, hi, found = kmin, min(len(s) // 2, 200), 0
    while lo <= hi:
        k = (lo + hi) // 2
        seen = set()
        hit = False
        for i in range(len(s) - k + 1):
            km = s[i:i + k]
            if km in seen:
                hit = True
                break
            seen.add(km)
        if hit:
            found = k
            lo = k + 1
        else:
            hi = k - 1
    return found


def _next_atg(seq, from_idx, window=40):
    for i in range(from_idx, min(len(seq) - 2, from_idx + window)):
        if seq[i:i + 3] == "ATG":
            return i
    return -1


SD_CONSENSUS = "AGGAGG"


def _find_sd(block_seq):
    """Best Shine-Dalgarno core inside an RBS block: (start, end) 0-based, end exclusive.

    Katana seals an RBS as a functional unit, SD plus spacer, so the block's own end is NOT the SD's
    end and cannot be used to measure spacing. Score every 6-mer against AGGAGG; on a tie prefer the
    3'-most, since that is the one the ribosome reads. Returns None if nothing scores well enough to
    be called an SD, which is honest rather than guessing.
    """
    if len(block_seq) < len(SD_CONSENSUS):
        return None
    best, best_score = None, 0
    for i in range(len(block_seq) - len(SD_CONSENSUS) + 1):
        window = block_seq[i:i + len(SD_CONSENSUS)]
        score = sum(1 for a, b in zip(window, SD_CONSENSUS) if a == b)
        if score >= best_score:            # >= so later (3'-most) wins a tie
            best, best_score = i, score
    # 4 of 6 is the floor for calling something an SD. Below that it is just purine-ish noise.
    if best is None or best_score < 4:
        return None
    return best, best + len(SD_CONSENSUS)


def audit(record, blocks, vendor=None, fragment_bp_max=None, host_seq=None):
    seq = record.seq
    findings = []

    # ---- POSITIVE INVARIANTS FIRST (Katana §4.1: never PASS by absence-of-bad) ----
    if not seq:
        findings.append(Finding("invariant", FAIL, "Empty sequence",
                                fix="Provide a non-empty FASTA/GenBank."))
        return findings
    if not blocks:
        findings.append(Finding("invariant", FLAG,
                                "No blocks identified against the reference seed set",
                                detail="Sequence parsed but nothing matched the public "
                                       "seed parts. Expand the reference set (fetch from "
                                       "the Registry) or supply an annotated GenBank.",
                                fix="Add the relevant parts to the seed set via "
                                    "katana-parts-library intake, then re-run."))

    # ---- IDENTITY: claim vs sequence (the headline check) ----
    for b in blocks:
        if not b.claim_label or not b.ident_id:
            continue
        claim = b.claim_label.strip()
        claim_norm = claim.replace("BBa_", "").upper()
        ident = b.ident_id.upper()
        if claim_norm and claim_norm != ident and ident not in claim_norm:
            # Is it a strength-class change? (the B0032→B0034 case)
            claim_ref = kg_refs.by_id().get(claim_norm)
            extra = ""
            if claim_ref and claim_ref.get("variant") and b.ident_variant:
                cs = kg_refs.STRENGTH_ORDER.get(claim_ref["variant"].split("-")[-1])
                is_ = kg_refs.STRENGTH_ORDER.get(b.ident_variant.split("-")[-1])
                if cs and is_ and cs != is_:
                    direction = "stronger" if is_ > cs else "weaker"
                    extra = (f" Strength class differs "
                             f"({claim_ref['variant']}→{b.ident_variant}): expression "
                             f"will be markedly {direction} than the label implies.")
            findings.append(Finding(
                "identity-mislabel", FLAG,
                f'Block labelled "{claim}" is actually {b.ident_id} '
                f'({b.ident_name})',
                loc=f"{b.start}-{b.end}",
                detail=f"Sequence matches {b.ident_registry or b.ident_id} at "
                       f"{b.pident}% identity, {int(b.coverage*100)}% coverage." + extra,
                fix=f"Re-label to {b.ident_id}, or swap in the real {claim} sequence "
                    f"from the Registry via katana-parts-library."))

    # ---- FULL-LENGTH: truncated reference parts ----
    for b in blocks:
        if b.ident_id and b.coverage is not None and b.coverage < 0.95:
            findings.append(Finding(
                "truncation", FLAG,
                f"{b.ident_id} appears truncated ({int(b.coverage*100)}% of reference)",
                loc=f"{b.start}-{b.end}",
                detail=f"Only {b.matched_len}/{b.ref_len} bp of {b.ident_id} present.",
                fix="Confirm the full-length part; a truncated promoter/terminator/RBS "
                    "often loses function."))

    # ---- ORF CLEAN: CDS-like blocks translate without internal stop ----
    for b in blocks:
        role = b.ident_role or b.claim_role
        if role not in ("cds", "reporter", "gene"):
            continue
        sub = record.sub(b.start, b.end)
        if b.strand == -1:
            sub = revcomp(sub)
        clean_len = len(sub) - (len(sub) % 3)
        codons = [sub[i:i+3] for i in range(0, clean_len, 3)]
        # A RUN of stops at the end is terminal, not internal. Two in a row (…AAA TGA TGA) is
        # deliberate practice, belt and braces against readthrough, and sfGFP ships that way.
        # Treating only the final codon as terminal reported the first of the pair as a premature
        # stop, and failed a construct that was simultaneously reported as 100% identical to the
        # reference - a contradiction that is the tell for this bug.
        last = len(codons)
        while last > 0 and codons[last - 1] in STOPS:
            last -= 1
        internal_stop = any(c in STOPS for c in codons[:last])
        starts_atg = sub[:3] in ("ATG", "GTG", "TTG")
        if internal_stop:
            findings.append(Finding(
                "orf", FAIL,
                f"CDS at {b.start}-{b.end} has an internal stop codon",
                loc=f"{b.start}-{b.end}",
                detail="Premature stop in the reading frame — the protein is truncated.",
                fix="Fix the frame/sequence; re-check the upstream junction and any scar."))
        elif len(sub) % 3 != 0:
            findings.append(Finding(
                "orf", FLAG,
                f"CDS at {b.start}-{b.end} length is not a multiple of 3",
                loc=f"{b.start}-{b.end}",
                detail=f"{len(sub)} bp — frame is ambiguous; a fusion may be out of frame.",
                fix="Confirm the intended frame and junction spacing."))
        elif not starts_atg:
            findings.append(Finding(
                "orf", FLAG, f"CDS at {b.start}-{b.end} does not start with a start codon",
                loc=f"{b.start}-{b.end}",
                fix="Confirm the CDS boundary / start codon."))
        else:
            findings.append(Finding("orf", PASS,
                                    f"CDS at {b.start}-{b.end} ORF-clean",
                                    loc=f"{b.start}-{b.end}"))

    # ---- JUNCTIONS: RBS → ATG spacing 5–9 nt ----
    for i, b in enumerate(blocks):
        role = b.ident_role or b.claim_role
        if role != "rbs":
            continue
        # look at the sequence just downstream of the RBS block for the start codon
        atg_rel = _next_atg(seq, b.end, window=40)
        if atg_rel < 0:
            findings.append(Finding(
                "junction", FLAG, f"No ATG found downstream of RBS at {b.start}-{b.end}",
                loc=f"{b.start}-{b.end}",
                fix="Check the RBS is followed by a CDS start within ~30 nt."))
            continue
        # Measure from the SD core, not the block edge. A sealed RBS is a functional unit (SD plus
        # spacer), so its block ends flush against the ATG and edge-arithmetic always returns 0.
        block_seq = record.sub(b.start, b.end)
        if b.strand == -1:
            block_seq = revcomp(block_seq)
        sd = _find_sd(block_seq)
        if sd is None:
            findings.append(Finding(
                "junction", FLAG,
                f"No Shine-Dalgarno core found in the RBS at {b.start}-{b.end}",
                loc=f"{b.start}-{b.end}",
                detail="Spacing is measured from the SD, so it cannot be checked without one.",
                fix="Confirm this block really is a ribosome binding site."))
            continue
        sd_abs_end = b.start + sd[1] - 1          # 1-based, inclusive, of the SD's last base
        spacing = (atg_rel + 1) - sd_abs_end - 1  # nt between the SD and the A of ATG
        if 5 <= spacing <= 9:
            findings.append(Finding("junction", PASS,
                                    f"RBS→ATG spacing {spacing} nt (in 5–9, measured from the SD)",
                                    loc=f"{b.start}-{b.end}"))
        else:
            findings.append(Finding(
                "junction", FLAG,
                f"RBS→ATG spacing {spacing} nt (outside 5–9, measured from the SD)",
                loc=f"{b.start}-{b.end}",
                detail="Spacing outside the 5–9 nt window shifts translation initiation "
                       "rate and can silence the downstream CDS.",
                fix="Adjust the spacer between the RBS and the start codon to 5–9 nt."))

    # ---- RESTRICTION SITES ----
    for name in BIOBRICK_FORBIDDEN:
        pos = _site_positions(seq, SIXCUT[name])
        if pos:
            findings.append(Finding(
                "restriction", FLAG,
                f"{name} site present ({len(pos)}×) — BioBrick (RFC[10]) incompatible",
                loc=", ".join(str(p) for p in pos[:6]) + ("…" if len(pos) > 6 else ""),
                detail=f"{name} = {SIXCUT[name]}. Blocks standard BioBrick assembly and "
                       f"any digest using it.",
                fix=f"Domesticate the {name} site (synonymous change in a CDS) if BioBrick "
                    f"or that enzyme is needed."))
    ts_report = []
    for name, site in TYPEIIS.items():
        n = len(_site_positions(seq, site))
        if n:
            ts_report.append(f"{name}×{n}")
    if ts_report:
        findings.append(Finding(
            "restriction", FLAG,
            "Type IIS site(s) present: " + ", ".join(ts_report),
            detail="Relevant if a Golden Gate / MoClo assembly uses that enzyme "
                   "(BsaI/BsmBI/SapI).",
            fix="Domesticate if the assembly enzyme matches; otherwise informational."))

    # ---- GC / HOMOPOLYMER ----
    gc = _gc(seq)
    if gc < 25 or gc > 65:
        findings.append(Finding("composition", FLAG, f"Global GC {gc:.1f}% (outside 25–65%)",
                                fix="Extreme GC raises synthesis failure risk; consider "
                                    "codon/UTR adjustment."))
    else:
        findings.append(Finding("composition", PASS, f"Global GC {gc:.1f}%"))
    hp = _longest_homopolymer(seq)
    if hp >= 9:
        findings.append(Finding("composition", FLAG,
                                f"Homopolymer run of {hp} nt",
                                detail="Runs ≥9 nt are a synthesis + sequencing-slippage risk.",
                                fix="Break up the homopolymer (synonymous change if in a CDS)."))

    # ---- REPEATS / MISASSEMBLY ----
    dr = _longest_direct_repeat(seq)
    if dr >= 30:
        findings.append(Finding("repeats", FLAG,
                                f"Direct repeat ≥{dr} bp detected",
                                detail="Long exact repeats misassemble and cannot be PCR'd "
                                       "across reliably (cf. the bARGSer tandem gvpA region).",
                                fix="Excise on non-repeat flanks; avoid PCR across the repeat."))

    # ---- HOST OFF-TARGET (optional; >~40 bp exact = recombination substrate) ----
    if host_seq:
        longest = _longest_shared(seq, host_seq)
        if longest > 40:
            findings.append(Finding("host-homology", FLAG,
                                    f"{longest} bp exact match to host chromosome (>40 bp)",
                                    detail="A recA+ recombination substrate.",
                                    fix="Recode/replace the host-identical stretch, or accept "
                                        "with a logged override (recA− host)."))
        else:
            findings.append(Finding("host-homology", PASS,
                                    f"Longest host match {longest} bp (≤40)"))
    else:
        findings.append(Finding("host-homology", FLAG,
                                "Host off-target scan skipped (no host genome supplied)",
                                detail="Pass --host <genome.fna> to run the >40 bp "
                                       "recombination-substrate check with real blastn.",
                                fix="Supply the host genome (e.g. MG1655) to complete the scan."))

    # ---- SIZE vs VENDOR ----
    if fragment_bp_max:
        if len(seq) > fragment_bp_max:
            findings.append(Finding("size", FLAG,
                                    f"{len(seq)} bp > {vendor or 'vendor'} cap "
                                    f"{fragment_bp_max} bp/fragment",
                                    fix="Split into fragments under the cap for synthesis."))
        else:
            findings.append(Finding("size", PASS,
                                    f"{len(seq)} bp ≤ {vendor or 'vendor'} cap {fragment_bp_max} bp"))

    return findings


def _longest_shared(seq, genome, cap=60):
    """Longest exact contiguous match (either strand) up to `cap` bp. Coarse net;
    the real Stage-4/intake check uses full blastn. Bounded for speed."""
    best = 0
    for s in (seq, revcomp(seq)):
        lo, hi = 0, min(len(s), cap)
        while lo < hi:
            k = (lo + hi + 1) // 2
            if any(s[i:i+k] in genome for i in range(0, len(s) - k + 1, max(1, k // 2))):
                lo = k
            else:
                hi = k - 1
        best = max(best, lo)
    return best


def verdict(findings):
    if any(f.status == FAIL for f in findings):
        return FAIL
    if any(f.status == FLAG for f in findings):
        return "CONDITIONAL"
    return PASS
