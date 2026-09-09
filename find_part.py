#!/usr/bin/env python3
"""
find_part.py — find a part you have decided you want, and get the exact command to admit it.

The gap this fills. add_part.py needs an accession and coordinates. A student who has decided
"I need the lactate-responsive repressor from E. coli" has no way to turn that decision into
NC_000913.3:3779054-3779830(+). That lookup is mechanical, it is boring, and it is exactly where
a sequence and its label come apart - so it should be done by a machine that shows its working,
not by a person squinting at a genome browser at midnight.

    python find_part.py lldR
    python find_part.py lacZ --organism "E. coli Nissle 1917"
    python find_part.py --have            # what is already in the library next to you

What this does NOT do, deliberately. It will not tell you WHICH part you want. Choosing a
promoter, deciding whether you need the repressor or the activator, judging whether a part from
one strain will behave in another - those are design decisions and they are yours. This finds a
part you have already named. That boundary is the same one the rest of Katana keeps.

The coordinate trap, handled here rather than left to you. NCBI's summary endpoint returns
chrstart/chrstop as ZERO-based, while the accession ranges everyone quotes - and the ones
add_part.py wants - are ONE-based inclusive. Off-by-one in exactly this conversion is the third
of the five failures this project was built around. The conversion below was checked against two
parts already sealed in our library months ago (lacZ 363231-366305(-) and lldR
3779054-3779830(+)) and reproduces both exactly.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
UA = {"User-Agent": "katana-find-part/1.0"}

# A default worth having: most iGEM teams asking for "lldR" mean the one in the standard chassis.
DEFAULT_ORG = "Escherichia coli str. K-12 substr. MG1655"


def get_json(url: str, timeout: int = 60):
    req = urllib.request.Request(url, headers=UA)
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def find_local_library(here: Path) -> Path | None:
    """The same walk-up the engine does, so 'what do I already have' means the same library."""
    for c in (q / "parts-library" / "ref_parts" for q in (here, *here.parents)):
        if (c / "LOCK.tsv").is_file():
            return c
    return None


def read_rows(lock: Path) -> list[dict]:
    lines = [l for l in lock.read_text(encoding="utf-8").splitlines() if l.strip()]
    head = lines[0].split("\t")
    return [dict(zip(head, l.split("\t"))) for l in lines[1:]]


def show_have(lock: Path, needle: str = "") -> int:
    rows = read_rows(lock)
    if needle:
        rows = [r for r in rows if needle.lower() in r["id"].lower()]
    if not rows:
        return 0
    print()
    print(f"  Already sealed in {lock.parent.name}/ next to you:")
    print()
    for r in rows:
        print(f"    {r['id']:<20} {r['length']:>6} bp  {r['class']:<12} {r['source'][:46]}")
    print()
    print("  These are verified and carry their provenance already, so copy them rather than")
    print("  fetching them again:")
    print()
    print(f"      python add_part.py --library <your-library> --from {lock} --id {rows[0]['id']}")
    print()
    return len(rows)


def search_ncbi(gene: str, organism: str, limit: int) -> list[dict]:
    term = f'{gene}[gene] AND "{organism}"[orgn]'
    url = (EUTILS + "esearch.fcgi?db=gene&retmode=json&retmax=" + str(limit)
           + "&term=" + urllib.parse.quote(term))
    ids = get_json(url)["esearchresult"]["idlist"]
    if not ids:
        return []
    res = get_json(EUTILS + "esummary.fcgi?db=gene&retmode=json&id=" + ",".join(ids))["result"]

    out = []
    for i in ids:
        g = res.get(i) or {}
        info = (g.get("genomicinfo") or [{}])[0]
        acc = info.get("chraccver")
        if not acc or info.get("chrstart") is None:
            continue  # a record with no genomic placement is no use to add_part
        s, e = int(info["chrstart"]), int(info["chrstop"])
        # ZERO-based from NCBI -> ONE-based inclusive, and the ordering encodes the strand.
        strand = "+" if s <= e else "-"
        lo, hi = min(s, e) + 1, max(s, e) + 1
        out.append({
            "name": g.get("name", gene),
            "desc": g.get("description", ""),
            "org": (g.get("organism") or {}).get("scientificname", ""),
            "acc": acc, "lo": lo, "hi": hi, "strand": strand, "length": hi - lo + 1,
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Find a named part in NCBI and print the command that admits it.")
    ap.add_argument("gene", nargs="?", help="the gene or part name you want, e.g. lldR")
    ap.add_argument("--organism", default=DEFAULT_ORG,
                    help=f"which organism to look in (default: {DEFAULT_ORG})")
    ap.add_argument("--library", type=Path, default=None,
                    help="your library, used to write the ready-made command (default: my-project/parts-library)")
    ap.add_argument("--have", action="store_true",
                    help="just list what is already sealed in the library beside you")
    ap.add_argument("--limit", type=int, default=6, help="how many candidates to show (default 6)")
    a = ap.parse_args()

    local = find_local_library(Path.cwd().resolve())
    yours = a.library or Path("my-project/parts-library")

    if a.have or not a.gene:
        if not local:
            print("\n  No parts-library found beside you. Run this from inside the katana folder,\n"
                  "  or make your own library first:  python katana_init.py my-project\n")
            return 1
        show_have(local / "LOCK.tsv")
        if not a.gene:
            print("  To search NCBI for something else:  python find_part.py <gene name>\n")
            return 0

    # Say so if they already have it, before sending them to the internet for a second copy.
    if local:
        rows = [r for r in read_rows(local / "LOCK.tsv")
                if a.gene.lower() in r["id"].lower()]
        if rows:
            print(f"\n  You already have {len(rows)} part(s) matching '{a.gene}' beside you:")
            for r in rows:
                print(f"    {r['id']:<20} {r['length']:>6} bp  {r['source'][:52]}")
            print("\n  Copy one instead of fetching it again:")
            print(f"\n      python add_part.py --library {yours} --from {local / 'LOCK.tsv'} "
                  f"--id {rows[0]['id']}")
            print("\n  Still want to search NCBI as well? Continuing.\n")

    print(f"  Searching NCBI for '{a.gene}' in {a.organism} ...")
    try:
        hits = search_ncbi(a.gene, a.organism, a.limit)
    except Exception as e:
        print(f"\n  Search failed: {e!r}")
        print("  NCBI may be busy. Wait a moment and try again.\n")
        return 1

    if not hits:
        print(f"\n  Nothing found for '{a.gene}' in {a.organism}.")
        print("  Try a different spelling, or widen the organism:")
        print(f"      python find_part.py {a.gene} --organism \"Escherichia coli\"\n")
        return 1

    print()
    for n, h in enumerate(hits, 1):
        print(f"  {n})  {h['name']}  —  {h['desc'][:56]}")
        print(f"      {h['org'][:66]}")
        print(f"      {h['acc']}:{h['lo']}-{h['hi']}({h['strand']})   {h['length']} bp")
        print()

    top = hits[0]
    print("  Coordinates above are 1-based inclusive, converted from NCBI's 0-based summary")
    print("  and checked against parts this project sealed months ago. To admit the first one:")
    print()
    print(f"      python add_part.py --library {yours} --id {top['name']} \\")
    print(f"          --accession {top['acc']} --range {top['lo']}..{top['hi']} "
          f"--strand {top['strand']} --expect-length {top['length']} \\")
    print(f"          --expect-organism \"{top['org']}\"")
    print()
    print("  Read the organism line before you run it. More than one strain will match a common")
    print("  gene name, and a part from the wrong strain is the kind of mistake that survives")
    print("  all the way to a synthesis order.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
