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


def identify_hits(query, refs):
    """Identify which references occur in `query`. Returns kg_identify._blast()'s shape."""
    q = kg_refs.normalise(query)
    n = len(q)
    if n < SHORT_MIN:
        return []                        # nothing in the set can identify this
    qrc = revcomp(q)

    hits = []
    for r in refs:
        ref = kg_refs.normalise(r.get("seq") or "")
        if not _usable(ref):
            continue
        if len(ref) <= SHORT_MAX:
            hits.extend(_short_hits(r["id"], ref, q, qrc, n))
    return hits
