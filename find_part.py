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


def rel(p: Path) -> str:
    """Show a path relative to where the reader is standing, when that is shorter."""
    try:
        return str(Path(p).resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(p)


def list_rows(lock: Path, title: str, note: str = "") -> int:
    """Print one library's contents under a heading."""
    rows = read_rows(lock)
    print(f"  {title} - {len(rows)} part(s)")
    if note:
        print(f"  {note}")
    print()

    # An id can appear more than once: a corrected part becomes a NEW version and the old row
    # stays, so the history remains legible. That storage rule is right; rendering it without the
    # version and the fingerprint is not, because those are the only two things that tell the
    # rows apart. One id here has two versions of the same length, and one of those is
    # byte-identical to a different part - picking it back up would reintroduce a repeat hazard
    # this project already hit.
    newest = {}
    for r in rows:
        v = int(r["version"]) if str(r.get("version", "")).isdigit() else 0
        if v >= newest.get(r["id"], (-1, None))[0]:
            newest[r["id"]] = (v, r["seq_sha256"])

    multi = {i for i in newest if sum(1 for r in rows if r["id"] == i) > 1}
    for r in rows:
        v = str(r.get("version", "?"))
        mark = ""
        if r["id"] in multi:
            mark = "  <- newest" if newest[r["id"]][1] == r["seq_sha256"] else "  (older)"
        print(f"    {r['id']:<20} v{v:<3} {r['length']:>5} bp  {r['seq_sha256'][:12]}  "
              f"{r['class']:<11} {r['source'][:30]}{mark}")
    print()
    # Two DIFFERENT ids holding the same bases is worth saying out loud. Using both in one
    # construct makes an exact direct repeat, and a repeat over ~40 bp is a recombination
    # substrate in the cell and a flag at most synthesis vendors. This project has already been
    # bitten by exactly that: two RBS parts came out byte-identical and produced a 43 bp repeat
    # that forced a construct revision. The information was always in the manifest; nothing ever
    # looked.
    by_hash = {}
    for r in rows:
        by_hash.setdefault(r["seq_sha256"], set()).add(r["id"])
    twins = [ids for ids in by_hash.values() if len(ids) > 1]
    if twins:
        print("  NOTE: different names, identical sequence -")
        for ids in twins:
            print(f"        {' = '.join(sorted(ids))}")
        print("        Using two of these in one construct creates an exact direct repeat.")
        print("        Over about 40 bp that is a recombination substrate in the cell and a")
        print("        flag at most synthesis vendors. Worth knowing before you design, not after.")
        print()

    if multi:
        print(f"  {len(multi)} id(s) above appear more than once. Those are versions of the same")
        print("  part, kept rather than overwritten so the history stays readable. Use the newest")
        print("  unless you have a reason not to, and pin the fingerprint in your Spec so the")
        print("  engine can tell which one you meant.")
        print()
    return len(rows)


def show_have(yours: Path, shipped: Path | None) -> int:
    """Show YOUR library and, separately, the one shipped here to copy from.

    Showing only one of them is how the trap worked: a reader with their own library saw our
    thirty parts, wrote a Spec against them, and the build refused parts they had never added.
    Your library and the reference library are different things, and saying so is the point of
    the whole design - yours is the one you fill, ours stays sealed so it can go on being
    checkable.
    """
    total = 0
    yours_lock = yours / "LOCK.tsv" if yours else None
    if yours_lock and yours_lock.exists():
        total += list_rows(yours_lock, f"YOUR library: {rel(yours)}")
        if total == 0:
            print("    (empty so far - nothing has been admitted yet)")
            print()

    if shipped and shipped.exists() and shipped != yours_lock:
        n = list_rows(
            shipped,
            "AVAILABLE TO COPY, from the library shipped with this repository",
            "These are already verified and carry their provenance, so copy them "
            "rather than fetching them again.")
        if yours_lock and yours_lock.exists():
            first = read_rows(shipped)[0]["id"]
            print("  To copy one across:")
            print()
            print(f"      python add_part.py --library {rel(yours.parent)} "
                  f"--from {rel(shipped.parent)} --id {first}")
            print()
        total += n
    return total


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
        # --library, when given, names YOUR library. Before this it was used only to write the
        # example command, while the listing always showed the shipped one.
        mine = None
        if a.library:
            r = a.library.expanduser().resolve()
            mine = next((c for c in (r / "ref_parts", r / "parts-library" / "ref_parts", r)
                         if (c / "LOCK.tsv").exists()), None)
        elif (Path("my-project/parts-library/ref_parts/LOCK.tsv")).exists():
            mine = Path("my-project/parts-library/ref_parts").resolve()
        show_have(mine, (local / "LOCK.tsv") if local else None)
        if not a.gene:
            print("  To search NCBI for something else:  python find_part.py <gene name>\n")
            return 0

    # Say so if they already have it, before sending them to the internet for a second copy.
    # An EXACT id match and a name that merely CONTAINS the search term are different findings:
    # searching "lldR" turns up RBS_lldR_strong, which is a different part, and calling those
    # "matches" invites someone to take the wrong one.
    # Check YOUR library first. Reporting only the shipped one told a reader who had just added
    # a part that they still needed to add it, and recommended copying something they already
    # held. The tool was reporting on a different library than the one it kept pointing at.
    mine_lock = None
    if a.library:
        r = a.library.expanduser().resolve()
        mine_lock = next((c / "LOCK.tsv" for c in
                          (r / "ref_parts", r / "parts-library" / "ref_parts", r)
                          if (c / "LOCK.tsv").exists()), None)
    elif Path("my-project/parts-library/ref_parts/LOCK.tsv").exists():
        mine_lock = Path("my-project/parts-library/ref_parts/LOCK.tsv")

    already_mine = []
    if mine_lock:
        already_mine = [r for r in read_rows(mine_lock)
                        if r["id"].lower() == a.gene.lower()]
    if already_mine:
        print()
        print(f"  '{a.gene}' is ALREADY IN YOUR LIBRARY. Nothing more to do for this part:")
        for r in already_mine:
            print(f"    {r['id']:<20} v{str(r.get('version','?')):<3} {r['length']:>5} bp  "
                  f"{r['seq_sha256'][:12]}  added {r.get('date', '?')}")
        print()
        print("  Put its seal: block into your Spec and build. Adding it again would only make")
        print("  a second version of a part you already hold.")
        print()

    if local:
        all_rows = read_rows(local / "LOCK.tsv")
        exact = [r for r in all_rows if r["id"].lower() == a.gene.lower()]
        near = [r for r in all_rows
                if a.gene.lower() in r["id"].lower() and r not in exact]

        def _show(rs):
            for r in rs:
                print(f"    {r['id']:<20} v{str(r.get('version','?')):<3} {r['length']:>5} bp  "
                      f"{r['seq_sha256'][:12]}  {r['source'][:34]}")

        if exact and not already_mine:
            best = max(exact, key=lambda r: int(r["version"]) if r["version"].isdigit() else 0)
            print(f"\n  You already have '{a.gene}' in the library beside you:")
            _show(exact)
            print()
            print("  COPYING IT IS THE EASIER ROUTE and the one to take unless you have a reason")
            print("  not to. It needs no internet, and it gives you the exact bases already")
            print("  verified here, with their provenance carried across:")
            print()
            print(f"      python add_part.py --library {rel(yours)} "
                  f"--from {rel(local)} --id {best['id']}")
            print()
            print("  Fetching from NCBI instead gives you whatever the record says TODAY. That is")
            print("  usually the same sequence, and when it is not, you want to meet that")
            print("  deliberately rather than by accident. The search below runs either way.")
        if near:
            print(f"\n  Also present, with names containing '{a.gene}' but NOT the same part:")
            _show(near)
        if exact or near:
            print()

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
    # Lead with the ACTION. The provenance note is worth keeping but it is not what the reader
    # came for, so it goes underneath rather than in front of the command.
    if len(hits) > 1:
        print(f"  {len(hits)} matches. Number 1 is the one below - check its organism line is the")
        print("  strain you actually work in, then run this to add it to your library:")
    else:
        print("  That is the one. Run this to add it to your library:")
    print()
    # One line, deliberately. A trailing backslash continues a command in bash but is a SYNTAX
    # ERROR in PowerShell, where the continuation is a backtick - and most people reading this
    # are on Windows. A long line wraps in the terminal; pasting a wrapped line still works,
    # because the wrap is visual rather than a newline.
    print(f"      python add_part.py --library {yours} --id {top['name']} "
          f"--accession {top['acc']} --range {top['lo']}..{top['hi']} "
          f"--strand {top['strand']} --expect-length {top['length']} "
          f"--expect-organism \"{top['org']}\"")
    print()
    print()
    print("  It will fetch the sequence, check the record really is that organism, fingerprint it,")
    print("  and print a seal: block to paste into your Design Spec. Then you can build.")
    print()
    if len(hits) > 1:
        # Only worth saying when it actually happened. A caution about a thing that did not
        # occur is boilerplate, and boilerplate teaches people to skim the next one.
        print("  Why the organism matters: a common gene name matches several strains, and a part")
        print("  from the wrong one is the kind of mistake that survives all the way to a")
        print("  synthesis order. The --expect-organism above is what stops that.")
        print()
    print("  Coordinates are 1-based inclusive, converted from NCBI's 0-based summary and checked")
    print("  against parts this project sealed months ago.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
