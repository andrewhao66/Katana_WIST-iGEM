"""
kg_identify.py — decompose a construct into blocks and IDENTIFY each block by
what its sequence ACTUALLY is (via blastn against the public reference seed set),
independent of what the construct's own annotation claims.

This is the "identify" half of Kagami. The audit (kg_audit) then compares the
identity to the claim — that comparison, not the identification, is the point.
"""
import os
import shutil
import subprocess
import tempfile

from kg_parse import revcomp
import kg_refs
import kg_seedmatch


class Block:
    def __init__(self, start, end, strand):
        self.start = start            # 1-based inclusive, on the given (+) strand
        self.end = end
        self.strand = strand          # +1/-1 : orientation the identified part sits in
        # claim (from the construct's own annotation) — may be None
        self.claim_label = None
        self.claim_role = None
        # identity (what blastn says the sequence really is) — may be None
        self.ident_id = None
        self.ident_name = None
        self.ident_role = None
        self.ident_variant = None
        self.ident_registry = None
        self.pident = None            # % identity of the match
        self.coverage = None          # matched_len / reference_len
        self.ref_len = None
        self.matched_len = None
        self.provenance = None
        # other references that fit these bases equally well (identical-sequence re-deposits)
        self.alternatives = []
        # for unidentified regions
        self.note = None

    @property
    def length(self):
        return self.end - self.start + 1

    def label(self):
        if self.ident_id:
            return self.ident_id
        if self.claim_label:
            return self.claim_label
        return "unidentified"


def _have_blast():
    return bool(shutil.which("blastn") and shutil.which("makeblastdb"))


def _write_ref_db(workdir):
    fa = os.path.join(workdir, "refs.fasta")
    with open(fa, "w", encoding="utf-8") as fh:
        for p in kg_refs.REFERENCE_PARTS:
            fh.write(f">{p['id']}\n{kg_refs.normalise(p['seq'])}\n")
    subprocess.run(
        ["makeblastdb", "-in", fa, "-dbtype", "nucl", "-out",
         os.path.join(workdir, "refs")],
        check=True, capture_output=True, text=True,
    )
    return os.path.join(workdir, "refs")


def _blast(construct_seq, dbpath, workdir):
    q = os.path.join(workdir, "query.fasta")
    with open(q, "w", encoding="utf-8") as fh:
        fh.write(f">construct\n{construct_seq}\n")
    cols = "qseqid sseqid pident length qstart qend sstart send evalue bitscore"
    out = subprocess.run(
        ["blastn", "-task", "blastn-short", "-query", q, "-db", dbpath,
         "-word_size", "7", "-dust", "no", "-soft_masking", "false",
         "-evalue", "1000", "-perc_identity", "80", "-strand", "both",
         # Default is 500. With ~18k references a genuine 18 bp hit need not make the top 500,
         # so a real part silently became "unidentified" as the set grew. The alignment was fine;
         # the reporting cap was not.
         "-max_target_seqs", "5000",
         "-outfmt", f"6 {cols}"],
        check=True, capture_output=True, text=True,
    )
    hits = []
    reflen = {p["id"]: len(kg_refs.normalise(p["seq"])) for p in kg_refs.REFERENCE_PARTS}
    for line in out.stdout.splitlines():
        f = line.split("\t")
        if len(f) < 10:
            continue
        sid = f[1]
        pid = float(f[2]); length = int(f[3])
        qs, qe = int(f[4]), int(f[5])
        ss, se = int(f[6]), int(f[7])
        bit = float(f[9])
        strand = 1 if se >= ss else -1
        qstart, qend = min(qs, qe), max(qs, qe)
        cov = length / reflen[sid] if reflen.get(sid) else 0.0
        hits.append(dict(sid=sid, pident=pid, length=length, qstart=qstart,
                         qend=qend, strand=strand, cov=cov, bit=bit))
    return hits


# A reference matched this much of its length counts as matched END TO END. Not 1.0, because a
# single base of vendor scar or a one-off trim should not demote a real identification.
COMPLETE_COV = 0.97


def _tile(hits, min_cov=0.6):
    """Greedy non-overlapping selection, preferring references matched end to end.

    Ranking by bitscore alone is what let one composite swallow three exact parts: bitscore grows
    with alignment length, so an 863 bp hit at 99.4% identity beat a 720 bp hit at 100% and then
    blocked it by overlap. The construct decomposed into 2 blocks instead of 4 and the RBS-spacing
    and ORF checks silently stopped running.

    Completeness comes first instead. A reference matched end to end is an identification; one
    matched at 81% is a FRAGMENT of something larger, which is what a composite looks like when the
    real parts are present too. Labels cannot be trusted to mark devices - thousands of authors over
    twenty years, and many entries carry no useful type at all - but this is structural and needs no
    label.

    It only bites when hits compete for the same bases. A genuinely truncated part with no rival
    still wins its region and is still reported as truncated.
    """
    kept = [h for h in hits if h["cov"] >= min_cov]
    # Completeness, then identity, then how much we trust the reference's origin, then bitscore.
    # The tier matters because identical sequences are common: fifteen references carry the exact
    # B0015 sequence, and without a deterministic tie-break the reported name changed run to run.
    kept.sort(key=lambda h: (h["cov"] >= COMPLETE_COV, h["pident"],
                             kg_refs.tier(h["sid"]), h["bit"]), reverse=True)
    chosen = []
    for h in kept:
        overlap = False
        for c in chosen:
            lo = max(h["qstart"], c["qstart"])
            hi = min(h["qend"], c["qend"])
            ov = max(0, hi - lo + 1)
            shorter = min(h["qend"] - h["qstart"] + 1, c["qend"] - c["qstart"] + 1)
            if ov > 0.5 * shorter:
                overlap = True
                break
        if not overlap:
            chosen.append(h)

    # Say when other references fit the same bases equally well. Naming one of fifteen identical
    # candidates with no hint that the rest exist is the tool sounding more certain than it is.
    for c in chosen:
        rivals = [h["sid"] for h in kept
                  if h["sid"] != c["sid"]
                  and abs(h["qstart"] - c["qstart"]) <= 2 and abs(h["qend"] - c["qend"]) <= 2
                  and h["pident"] >= c["pident"] - 0.01 and h["cov"] >= COMPLETE_COV]
        c["alternatives"] = sorted(set(rivals))

    chosen.sort(key=lambda h: h["qstart"])
    return chosen


def _find_orfs(seq, min_aa=50):
    """Return (start,end,strand) of the longest clean ORF in each strand region,
    to label unidentified stretches that look like a CDS."""
    stops = {"TAA", "TAG", "TGA"}
    found = []
    for strand, s in ((1, seq), (-1, revcomp(seq))):
        n = len(s)
        for frame in range(3):
            i = frame
            while i < n - 2:
                if s[i:i+3] == "ATG":
                    j = i + 3
                    while j < n - 2:
                        if s[j:j+3] in stops:
                            aa = (j - i) // 3
                            if aa >= min_aa:
                                if strand == 1:
                                    found.append((i + 1, j + 3, 1, aa))
                                else:
                                    found.append((n - (j + 3) + 1, n - i, -1, aa))
                            i = j
                            break
                        j += 3
                i += 3
    found.sort(key=lambda t: t[3], reverse=True)
    return found


_EXACT_MIN = 8


def _exact_index():
    """Map every reference sequence to the ids that carry it, forward strand only.

    Built from the same refs/ set blastn searches, so this path introduces no second
    catalogue and no new provenance question. Identical re-deposits are common - fifteen
    references can share one sequence - so the value is a sorted LIST of ids, never one id.
    """
    idx = {}
    for r in kg_refs.by_id().values():
        seq = kg_refs.normalise(r.get("seq") or "")
        if len(seq) < _EXACT_MIN:
            continue
        idx.setdefault(seq, set()).add(r["id"])
    return {k: sorted(v) for k, v in idx.items()}


def _exact_hits_from_features(record):
    """Identify annotated features by exact sequence match, without blastn.

    Only for a record that names its own parts. An annotated file is a CLAIM to be
    checked, which is an exact comparison; an unannotated one is a SEARCH, which is what
    blastn is for. This path therefore cannot see truncations, point mutations or
    fragments, and a feature it cannot match exactly is left unidentified rather than
    called clean.

    Returns hits in the same shape _blast() produces, so everything downstream - block
    construction, the claim-versus-identity comparison, the verdict - is unchanged.
    """
    idx = _exact_index()
    if not idx:
        return []

    seq = kg_refs.normalise(record.seq)
    hits = []
    for feat in record.features:
        if feat.kind in ("source",):
            continue
        start, end = feat.start, feat.end
        if not start or not end or end < start or end > len(seq):
            continue
        bases = seq[start - 1:end]
        if len(bases) < _EXACT_MIN:
            continue

        ids, strand = idx.get(bases), 1
        if not ids:
            ids, strand = idx.get(kg_refs.normalise(revcomp(bases))), -1
        if not ids:
            continue

        # If the construct's own claim is among the exact matches, report THAT id: the
        # feature is confirmed, and naming a synonym instead would invent a mismatch.
        # Otherwise the first id is reported and the rest ride along as alternatives, so
        # no true name is dropped on the way to a FAIL.
        claim = (feat.label or "").strip()
        primary = claim if claim in ids else ids[0]
        hits.append({
            "sid": primary,
            "qstart": start,
            "qend": end,
            "strand": strand,
            "pident": 100.0,
            "cov": 1.0,
            "length": len(bases),
            "alternatives": [i for i in ids if i != primary],
        })
    return hits


def identify(record, workdir, status=None, deep=False):
    """Return an ordered list[Block] covering the construct, with claim + identity.

    status: an optional dict the caller passes in. Filled with {"ran": True, "reason": ""}.
    Identification now ALWAYS runs: it is pure Python with no external dependency, so
    the old "BLAST+ is missing" path -- which let a construct carrying a planted
    mislabel report PASS, clean to order, exit 0 -- cannot occur. When the caller asked
    for --deep and BLAST+ was unavailable or failed, status["deep_failed"] carries a
    sentence saying so; the built-in identifier ran regardless.

    deep: opt in to blastn's gapped local alignment for distant homologs. Not automatic:
    an ambient dependency makes two machines disagree about the same file, which is the
    works-on-my-machine failure the engine's own --expect-root flag exists to prevent.
    """
    seq = record.seq
    blocks = []

    if status is not None:
        status.clear()
        status.update({"ran": True, "reason": ""})

    def _deep_failed(reason):
        if status is not None:
            status["deep_failed"] = reason

    id_hits = []
    if len(seq) < 8:
        # Not a failure: there is nothing to identify. Left as ran=True so a 4 bp input does not
        # produce an alarming "identification did not run" on top of its real findings.
        pass
    elif deep and _have_blast():
        # Opt-in deep search. blastn does gapped local alignment, so it can find
        # distant homologs the seeded path cannot. It is NOT the default.
        try:
            db = _write_ref_db(workdir)
            id_hits = _tile(_blast(seq, db, workdir))
        except Exception as exc:
            id_hits = _tile(kg_seedmatch.identify_hits(seq, kg_refs.REFERENCE_PARTS))
            _deep_failed("--deep was requested but BLAST+ failed to run (%s: %s); the "
                         "built-in identifier ran instead."
                         % (exc.__class__.__name__, exc))
    else:
        if deep and not _have_blast():
            _deep_failed("--deep was requested but NCBI BLAST+ is not installed "
                         "(blastn/makeblastdb are not on PATH); the built-in "
                         "identifier ran instead.")
        id_hits = _tile(kg_seedmatch.identify_hits(seq, kg_refs.REFERENCE_PARTS))

    refs = kg_refs.by_id()

    def make_ident_block(h):
        b = Block(h["qstart"], h["qend"], h["strand"])
        r = refs[h["sid"]]
        b.ident_id = r["id"]; b.ident_name = r["name"]; b.ident_role = r["role"]
        b.ident_variant = r.get("variant"); b.ident_registry = r.get("registry")
        b.pident = round(h["pident"], 1); b.coverage = round(h["cov"], 2)
        b.alternatives = h.get("alternatives") or []
        b.ref_len = len(kg_refs.normalise(r["seq"])); b.matched_len = h["length"]
        b.provenance = r.get("provenance")
        return b

    # Attach the construct's own claims (features) to identity blocks by overlap.
    used_features = set()

    for h in id_hits:
        b = make_ident_block(h)
        best_f, best_ov = None, 0
        for fi, feat in enumerate(record.features):
            if feat.kind in ("source",):
                continue
            lo = max(b.start, feat.start); hi = min(b.end, feat.end)
            ov = max(0, hi - lo + 1)
            if ov > best_ov:
                best_ov, best_f = ov, fi
        if best_f is not None and best_ov > 0.3 * b.length:
            feat = record.features[best_f]
            b.claim_label = feat.label or feat.kind
            b.claim_role = feat.kind
            used_features.add(best_f)
        blocks.append(b)

    # Features with no identity block (e.g. a CDS not in the seed set): keep as
    # claim-only blocks so they are still audited.
    for fi, feat in enumerate(record.features):
        if fi in used_features or feat.kind in ("source", "misc"):
            continue
        # skip a claim-only feature fully covered by an identity block
        covered = any(b.start <= feat.start and b.end >= feat.end for b in blocks)
        if covered:
            continue
        b = Block(feat.start, feat.end, feat.strand)
        b.claim_label = feat.label or feat.kind
        b.claim_role = feat.kind
        blocks.append(b)

    blocks.sort(key=lambda b: b.start)

    # Fill large unidentified gaps; label CDS-like ones via ORF scan.
    covered = [(b.start, b.end) for b in blocks]
    gaps = []
    cursor = 1
    for s, e in sorted(covered):
        if s - cursor >= 30:
            gaps.append((cursor, s - 1))
        cursor = max(cursor, e + 1)
    if len(seq) - cursor + 1 >= 30:
        gaps.append((cursor, len(seq)))

    # The smallest leftover worth showing as its own block. Below this it is a scar or a couple
    # of spare bases; at this size it is a real element (an RBS is ~18 bp) and the reader wants it.
    MIN_REMAINDER = 6

    def _unidentified(a, b_):
        blk = Block(a, b_, 1)
        blk.note = "unidentified region (no reference match)"
        return blk

    for gs, ge in gaps:
        sub = seq[gs - 1:ge]
        orfs = _find_orfs(sub)
        if orfs and orfs[0][3] * 3 >= 0.7 * len(sub):
            os_, oe_, ostr, aa = orfs[0]
            # The CDS block is the ORF ITSELF, not the whole gap it was found in. Anything left
            # over on either side becomes its own unidentified block rather than being absorbed.
            # Absorbing it used to run the CDS past its own stop codon and report a sound
            # construct as truncated - see the S4 RBS case in the commit message.
            a_start, a_end = gs + os_ - 1, gs + oe_ - 1
            if a_start - gs >= MIN_REMAINDER:
                blocks.append(_unidentified(gs, a_start - 1))
            b = Block(a_start, a_end, ostr)
            b.ident_role = "cds"
            b.note = f"unannotated CDS-like ORF ({aa} aa, {'+' if ostr==1 else '-'} strand)"
            blocks.append(b)
            if ge - a_end >= MIN_REMAINDER:
                blocks.append(_unidentified(a_end + 1, ge))
        else:
            blocks.append(_unidentified(gs, ge))

    blocks.sort(key=lambda b: b.start)
    return blocks
