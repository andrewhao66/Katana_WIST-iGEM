"""kg_seedmatch.py — pure-Python part identification.

Replaces the blastn shell-out in kg_identify. Measured against blastn on real
constructs: identical identity and coverage on full-length parts, on truncation at
60/80/90%, and on point mutations at 94.4/97.7/98.6% identity; roughly twice as fast,
because kg_identify rebuilt a BLAST database of 18,538 sequences on every single run.

Hybrid, because the reference length distribution forces it. Of 18,538 references, 894
are shorter than 25 bp and 123 are shorter than 12 bp, and short RBS parts are exactly
where the B0032/B0034 class of mislabel happens:

  references <= SHORT_MAX   direct exact match, C-speed via str.find, stricter than blastn
  references >  SHORT_MAX   k-mer seeding with stride filtering, then FULL-REFERENCE
                            alignment on the best diagonal

The full-reference alignment is load-bearing. Extending only to the last seed
under-reports coverage when a mutation falls near a part's end, which raised a FALSE
truncation FLAG on a full-length part (B0015 with 3 mutations read 89% coverage instead
of 100%). Aligning the whole reference against its query window fixes it exactly.

Output shape is identical to kg_identify._blast() so _tile() and everything downstream
are unchanged.
"""
import sys
from collections import defaultdict

try:
    import kg_refs
except ImportError:                      # running from another directory
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import kg_refs

K = 12                  # seed length for the long path
SHORT_MAX = 25          # references this long or shorter take the exact path
SHORT_MIN = 12          # shorter than this carries no identifying information
MIN_HIT = 25            # shortest alignment the long path guarantees to find
MIN_IDENT = 80.0        # below this, not reported at all
MAX_LOCI = 4            # distinct diagonals extended per reference per strand

_COMP = str.maketrans("ACGTNacgtn", "TGCANtgcan")


def revcomp(s):
    return s.translate(_COMP)[::-1]


def low_complexity(s):
    """True when a sequence carries no identifying information.

    Deliberately NOT "two or fewer distinct bases": B0034 is AAAGAGGAGAAA, which
    contains only A and G, and purine richness is the Shine-Dalgarno sequence's
    FUNCTION — it base-pairs with the pyrimidine-rich 16S rRNA anti-SD. A rule that
    rejects two-base sequences deletes the most important part class for the mislabel
    bug this project exists to catch.
    """
    if not s:
        return True
    if len(set(s)) == 1:
        return True                      # pure homopolymer: AAAAAAAAAA
    top = max(s.count(b) for b in set(s))
    return top / float(len(s)) > 0.8     # one base overwhelmingly dominant


def _usable(ref):
    """A reference that can identify something."""
    return len(ref) >= SHORT_MIN and not low_complexity(ref)


def _short_hits(sid, ref, query, qrc, n):
    """Exact occurrences of a short reference, on both strands.

    Exact rather than approximate on purpose. For a 12 bp RBS, 'these are the same
    bases' and 'these are nearly the same bases' are different claims, and the audit's
    job is the first one.
    """
    out = []
    L = len(ref)
    for strand, hay in ((1, query), (-1, qrc)):
        start = hay.find(ref)
        while start >= 0:
            if strand == 1:
                qs, qe = start + 1, start + L
            else:
                qs, qe = n - (start + L) + 1, n - start
            out.append(dict(sid=sid, pident=100.0, length=L, qstart=qs, qend=qe,
                            strand=strand, cov=1.0, bit=2.0 * L))
            start = hay.find(ref, start + 1)
    return out


def _query_index(q, k):
    """k-mer -> positions in q. Built once per query; the query is small."""
    idx = defaultdict(list)
    for i in range(len(q) - k + 1):
        idx[q[i:i + k]].append(i)
    return idx


def _long_hits(sid, ref, q, qidx, n, k, stride):
    """Find where a long reference occurs in the query. Returns a list of hits.

    Two stages. A stride prefilter rejects references with no seed at all, then every
    surviving reference is scanned fully and its seeds grouped by diagonal; each of the
    best MAX_LOCI diagonals is extended and scored.

    The stride prefilter's guarantee is narrower than it looks, and the limit is worth
    stating rather than glossing: an EXACT run of >= MIN_HIT bases contains
    (MIN_HIT - k + 1) consecutive k-mer starts, so sampling every (MIN_HIT - k + 1)//2
    positions must land inside one. That guarantee does NOT extend to approximate
    matches. A 40 bp reference at 92.5% identity with substitutions at positions 11, 24
    and 37 has a substitution inside every sampled window (0, 7, 14, 21, 28) while the
    exactly-matching windows at 12 and 25 are never sampled -- so it is rejected before
    the full scan can find it. Halving the stride improves sensitivity; it does not make
    high-identity detection certain. Use --deep for that.
    """
    out = []
    L = len(ref)
    get = qidx.get
    for strand, s in ((1, ref), (-1, revcomp(ref))):
        # cheap rejection: does any sampled seed hit at all?
        seeded = False
        for i in range(0, L - k + 1, stride):
            if get(s[i:i + k]):
                seeded = True
                break
        if not seeded:
            continue

        # full scan of this one reference, grouping seeds by diagonal
        diags = defaultdict(int)
        for i in range(L - k + 1):
            h = get(s[i:i + k])
            if h:
                for qp in h:
                    diags[qp - i] += 1
        if not diags:
            continue

        # Several diagonals, not just the best one. A part used TWICE in one construct
        # sits on two different diagonals, and architecture.order explicitly permits a
        # repeated id -- pAP-Logic's own version history is about a repeated RBS that
        # formed a 43 bp direct repeat. Taking only max(diags) reported the second
        # occurrence as an unidentified block, and a mislabel on it would then never be
        # checked, because the identity comparison skips blocks with no ident_id.
        #
        # Bounded at MAX_LOCI by seed count: unbounded would mean a full extension per
        # diagonal per reference across 18,538 references.
        for d, _seeds in sorted(diags.items(), key=lambda kv: kv[1],
                                reverse=True)[:MAX_LOCI]:
            hit = _extend(sid, q, s, d, L, n, strand)
            if hit is not None:
                out.append(hit)
    return out


def _extend(sid, q, s, d, L, n, strand):
    """Score one diagonal and return a hit dict, or None. d = query pos - reference pos.

    The diagonal fixes the correspondence between reference and query positions, so the
    whole reference is laid against its query window -- and then the part of it that is
    actually SUPPORTED is found.

    Taking the whole window was wrong in a way that matters more than it looks. The span
    then measured how much CONSTRUCT was available rather than how much REFERENCE
    aligned, so a part present at 103 of its 129 bases followed by unrelated sequence
    reported cov=1.000 and never raised the truncation FLAG; at 77 of 129 the unrelated
    tail dragged identity under the 80% floor and the part vanished from the report
    altogether. A truncated part reported as full-length, or not reported at all, is
    this project's cardinal failure.

    Maximal-scoring segment (+1 match, -1 mismatch) -- ungapped local extension.
    Unrelated flanks score about -0.5 per base and are clipped, while a full-length part
    with scattered mutations scores positive throughout and keeps its whole span, so a
    mutated part is not mistaken for a truncated one. That would be the opposite error
    and just as wrong.
    """
    ws, we = d, d + L
    cs, ce = max(0, ws), min(n, we)
    if ce - cs < MIN_HIT:
        return None
    qseg = q[cs:ce]
    sseg = s[cs - ws:ce - ws]

    best_score = cur = 0
    best_lo = best_hi = cur_lo = 0
    for i, (a, b) in enumerate(zip(qseg, sseg)):
        cur += 1 if a == b else -1
        if cur <= 0:
            cur, cur_lo = 0, i + 1
        elif cur > best_score:
            best_score, best_lo, best_hi = cur, cur_lo, i + 1
    if best_score <= 0:
        return None

    span = best_hi - best_lo
    if span < MIN_HIT:
        return None
    matches = sum(1 for a, b in zip(qseg[best_lo:best_hi], sseg[best_lo:best_hi])
                  if a == b)
    pident = 100.0 * matches / span
    if pident < MIN_IDENT:
        return None
    return dict(sid=sid, pident=round(pident, 1), length=span,
                qstart=cs + best_lo + 1, qend=cs + best_hi, strand=strand,
                cov=span / float(L), bit=2.0 * matches)


def identify_hits(query, refs, k=K):
    """Identify which references occur in `query`. Returns kg_identify._blast()'s shape."""
    q = kg_refs.normalise(query)
    n = len(q)
    if n < SHORT_MIN:
        return []                        # nothing in the set can identify this
    qrc = revcomp(q)

    qidx = _query_index(q, k) if n >= k else {}
    stride = max(1, (MIN_HIT - k + 1) // 2)

    hits = []
    for r in refs:
        ref = kg_refs.normalise(r.get("seq") or "")
        if not _usable(ref):
            continue
        if len(ref) <= SHORT_MAX:
            hits.extend(_short_hits(r["id"], ref, q, qrc, n))
        elif qidx:
            hits.extend(_long_hits(r["id"], ref, q, qidx, n, k, stride))

    # One reference can seed on both strands at the same place (a palindrome, or a
    # self-complementary terminator). Keep the better reading rather than reporting
    # the same block twice.
    keep = {}
    for h in hits:
        key = (h["sid"], h["qstart"] // 10, h["qend"] // 10)
        cur = keep.get(key)
        if cur is None or (h["pident"], h["cov"]) > (cur["pident"], cur["cov"]):
            keep[key] = h
    return list(keep.values())
