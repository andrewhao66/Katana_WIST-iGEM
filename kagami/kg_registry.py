"""
kg_registry.py — the iGEM Registry, live.

One client, two callers, because they are the same operation at different times:

  * build_refs.py --registry-bulk   fetches a standard-parts set ONCE, offline, and bakes it into
                                    the shipped reference file. Every team benefits, no network
                                    needed at audit time.
  * kagami audit --registry         checks a single claim against the Registry during a run, for
                                    the part that is not in anybody's library.

WHAT THIS CAN AND CANNOT DO. The Registry API is addressed BY NAME, not by sequence: there is no
public sequence search behind it. So it can answer "is the part called BBa_B0034 really this
sequence?" and it CANNOT answer "what is this 360 bp of DNA?". That distinction is load-bearing and
the CLI is worded to match it - an unidentified block with no claimed name stays unidentified, and
Kagami says so rather than implying the Registry was asked and had no answer.

What it is genuinely good at is checking the author's own label against the authoritative source.
A Benchling export whose feature says BBa_B0034 can be confirmed or refuted against the Registry
itself, rather than only against whatever we happened to ship.

Endpoints (public, anonymous, confirmed working 2026-09-15):
    /v1/parts?name=<NAME>   -> search; 0 hits for a name that does not exist
    /v1/parts/<uuid>        -> detail, carrying `sequence` and an SO-coded `role`

The Registry rate-limits, so every call backs off and retries rather than surfacing a raw
exception. add_part.py learned this the hard way: two calls per part means a handful of parts in a
row is enough to trip 429.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

SEARCH_URL = "https://api.registry.igem.org/v1/parts?name={name}"
DETAIL_URL = "https://api.registry.igem.org/v1/parts/{uuid}"
UA = "kagami/1.0 (WIST iGEM; sequence auditor)"

# The Sequence Ontology terms the Registry uses, mapped to the role vocabulary Kagami speaks.
# Reporting a recorded fact, not deciding one: the Registry states the role and gives an accession.
# Anything not on this list leaves the role unset rather than guessed.
SO_TO_ROLE = {
    "SO:0000167": "promoter",
    "SO:0000141": "terminator",
    "SO:0000139": "rbs",
    "SO:0000316": "cds",
    "SO:0000704": "cds",         # gene
    "SO:0000552": "rbs",         # Shine-Dalgarno

    # The Registry mixes its OWN vocabulary in with SO, so a map of SO alone leaves a third of
    # fetched parts with no role - which silently disables the ORF and junction checks on them.
    "IGEM:0000005": "reporter",  # Reporter: the fluorescent proteins and chromoproteins
}

# DELIBERATELY NOT MAPPED, and this is a safety decision rather than an omission.
# IGEM:0000007 Generator, IGEM:0000021 Translational Unit and IGEM:0000009 Intermediate are
# COMPOSITE parts - a Generator is promoter + RBS + CDS + terminator in one entry. Giving a
# composite a coding role would run the ORF check across the whole thing and report the CDS's own
# terminal stop as premature: exactly the false FAIL that was fixed on 2026-09-15. A composite has
# no single role, so it gets none, and only the reference-free checks apply to it.
# IGEM:0000006 Regulatory and IGEM:0000037 Miscellaneous are categories, not roles.
COMPOSITE_TERMS = {"IGEM:0000007", "IGEM:0000021", "IGEM:0000009"}


class RegistryUnavailable(Exception):
    """The Registry could not be reached. Distinct from 'the part does not exist'."""


# A bulk run is ~90 calls back to back, which the Registry will throttle. Be patient rather
# than loud: the alternative is a half-built reference set, and a reference set that is
# silently incomplete is worse than one that took a minute longer.
def _get(url, timeout=30, pauses=(0, 2, 5, 15, 30, 60)):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    last = None
    for attempt, pause in enumerate(pauses):
        if pause:
            if attempt == 1:
                print(f"  the Registry is rate-limiting; waiting {pause}s and retrying ...")
            time.sleep(pause)
        try:
            return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code != 429:
                raise RegistryUnavailable(f"HTTP {e.code} from {url}")
            last = e
        except Exception as e:                       # DNS, TLS, offline, timeout
            raise RegistryUnavailable(str(e))
    raise RegistryUnavailable(f"rate-limited after {len(pauses)} attempts ({last})")


def _rows(payload):
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    for key in ("parts", "data", "items", "results"):
        if isinstance(payload.get(key), list):
            return payload[key]
    return []


def fetch(name):
    """Look a part up by Registry name. Returns a dict, or None if the Registry has no such part.

    Raises RegistryUnavailable if the Registry could not be reached, which is deliberately NOT the
    same as a miss: "we could not ask" and "we asked and it does not exist" must not be reported
    with the same words.
    """
    hits = _rows(_get(SEARCH_URL.format(name=urllib.parse.quote(name))))
    if not hits:
        return None
    hit = hits[0]
    uuid = hit.get("uuid")
    if not uuid:
        return None
    detail = _get(DETAIL_URL.format(uuid=uuid))
    if not detail:
        return None
    seq = (detail.get("sequence") or "").strip().upper()
    if not seq:
        return None                                  # a record with no sequence is not usable
    role_obj = detail.get("role") or hit.get("role") or {}
    accession = role_obj.get("accession") if isinstance(role_obj, dict) else None
    return dict(
        name=detail.get("name") or name,
        uuid=uuid,
        title=(detail.get("title") or "").strip(),
        seq="".join(c for c in seq if c.isalpha()),
        so=accession or "",
        so_label=(role_obj.get("label") if isinstance(role_obj, dict) else "") or "",
        role=SO_TO_ROLE.get(accession or "", ""),
        usage=hit.get("usageCount") or detail.get("usageCount") or 0,
    )
