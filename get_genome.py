#!/usr/bin/env python3
"""
get_genome.py — fetch the host genome you need, when you need it.

WHY THIS EXISTS INSTEAD OF SHIPPING GENOMES

The off-target check compares your construct against the whole genome of the organism you
are putting it into, looking for stretches that accidentally match the host. That needs a
genome file, and genomes are big: E. coli is about 4.5 MB, yeast 12 MB. Shipping a handful
would bloat the repository for everyone, and would still be the wrong handful for the team
working in Vibrio, or cyanobacteria, or something nobody thought of.

So nothing is bundled. You fetch the one you actually use, once, and it lands where the
checker looks. No team is ever blocked because we failed to guess their chassis.

  python get_genome.py                 pick from a menu
  python get_genome.py --list          show the menu and exit
  python get_genome.py --host ecoli    fetch one without the menu
  python get_genome.py --accession M77789.2 --name pUC19 --key pUC19
                                       fetch anything else in NCBI nucleotide

Requires only Python's standard library, plus an internet connection for the fetch itself.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

EFETCH = ("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
          "?db=nuccore&id={ids}&rettype=fasta&retmode=text")

# key -> (menu letter, group, display name, expected-organism substring, approx MB, accessions)
#
# EVERY ACCESSION HERE WAS VERIFIED against NCBI on 2026-09-09, by fetching the record and
# reading the organism name back out of its header. None is typed from memory. That pass
# caught three traps worth knowing if you extend this list:
#
#   * NCBI has RENAMED familiar organisms. Lactobacillus plantarum is now
#     Lactiplantibacillus, Agrobacterium tumefaciens C58 is now A. fabrum, and Bacillus
#     megaterium is now Priestia. The expected-organism strings below match what NCBI
#     actually returns, not what the textbook calls them.
#   * Guessing a consecutive accession range is unsafe. NC_012967.1 sits immediately after
#     the four Komagataella chromosomes and is an unrelated E. coli genome.
#   * Some organisms are several records. Yeast is 16 chromosomes and Komagataella is 4;
#     fetching only the first would silently scan a fraction of the genome.
#
# The `key` is what a Design Spec's `host` / `constraints.host_context` field says.
#
# Everything listed is compatible with the iGEM White List as it stood on 2026-09-09 (Risk
# Group 1 microorganisms, S. cerevisiae, K. phaffii, disarmed Agrobacterium, and the named
# phages). The White List changes — check it yourself at responsibility.igem.org rather
# than trusting this comment, and remember that a genome being downloadable here says
# nothing about whether your institution or your team's division permits the work.
GENOMES: dict[str, tuple] = {
    "E_coli_MG1655":     ("a", "Bacteria", "E. coli K-12 MG1655 - the default iGEM chassis",
                          "Escherichia coli", 4.6, ["NC_000913.3"]),
    "E_coli_Nissle":     ("b", "Bacteria", "E. coli Nissle 1917 - probiotic chassis",
                          "Escherichia coli", 5.4, ["CP007799.1"]),
    "E_coli_BL21":       ("c", "Bacteria", "E. coli BL21(DE3) - protein expression",
                          "Escherichia coli", 4.6, ["CP001509.3"]),
    "B_subtilis_168":    ("d", "Bacteria", "Bacillus subtilis 168 - Gram-positive workhorse",
                          "Bacillus subtilis", 4.2, ["NC_000964.3"]),
    "L_lactis_IL1403":   ("e", "Bacteria", "Lactococcus lactis IL1403 - food-grade",
                          "Lactococcus lactis", 2.4, ["NC_002662.1"]),
    "L_plantarum_WCFS1": ("f", "Bacteria", "Lactiplantibacillus plantarum WCFS1 - probiotic",
                          "Lactiplantibacillus plantarum", 3.3, ["NC_004567.2"]),
    "P_putida_KT2440":   ("g", "Bacteria", "Pseudomonas putida KT2440 - robust soil bacterium",
                          "Pseudomonas putida", 6.2, ["NC_002947.4"]),
    "Synechocystis_6803": ("h", "Bacteria", "Synechocystis sp. PCC 6803 - photosynthetic",
                          "Synechocystis", 3.6, ["NC_000911.1"]),
    "V_natriegens":      ("i", "Bacteria", "Vibrio natriegens - very fast growing",
                          "Vibrio natriegens", 5.2, ["NZ_CP009977.1"]),
    "C_glutamicum":      ("j", "Bacteria", "Corynebacterium glutamicum ATCC 13032 - amino acids",
                          "Corynebacterium glutamicum", 3.3, ["NC_003450.3"]),
    "A_fabrum_C58":      ("k", "Bacteria", "Agrobacterium fabrum C58, aka A. tumefaciens - plants",
                          "Agrobacterium fabrum", 2.9, ["NC_003062.2"]),
    "S_coelicolor":      ("l", "Bacteria", "Streptomyces coelicolor A3(2) - natural products",
                          "Streptomyces coelicolor", 8.7, ["NC_003888.3"]),
    "Z_mobilis_ZM4":     ("m", "Bacteria", "Zymomonas mobilis ZM4 - ethanol producer",
                          "Zymomonas mobilis", 2.1, ["NC_006526.2"]),
    "P_megaterium":      ("n", "Bacteria", "Priestia megaterium DSM319, aka Bacillus megaterium",
                          "Priestia megaterium", 5.1, ["NC_014103.1"]),
    "S_cerevisiae":      ("o", "Fungi", "Saccharomyces cerevisiae S288C - baker's yeast",
                          "Saccharomyces cerevisiae", 12.2,
                          ["NC_001133.9", "NC_001134.8", "NC_001135.5", "NC_001136.10",
                           "NC_001137.3", "NC_001138.5", "NC_001139.9", "NC_001140.6",
                           "NC_001141.2", "NC_001142.9", "NC_001143.9", "NC_001144.5",
                           "NC_001145.3", "NC_001146.8", "NC_001147.6", "NC_001148.4"]),
    "K_phaffii":         ("p", "Fungi", "Komagataella phaffii GS115, aka Pichia pastoris",
                          "Komagataella phaffii", 9.3,
                          ["NC_012963.1", "NC_012964.1", "NC_012965.1", "NC_012966.1"]),
    "Phage_lambda":      ("q", "Phage", "Phage lambda", "phage lambda", 0.05, ["NC_001416.1"]),
    "Phage_T7":          ("r", "Phage", "Phage T7", "phage T7", 0.04, ["NC_001604.1"]),
    "Phage_T4":          ("s", "Phage", "Phage T4", "phage T4", 0.17, ["NC_000866.4"]),
    "Phage_T2":          ("t", "Phage", "Phage T2", "phage T2", 0.17, ["NC_054931.1"]),
    "Phage_M13":         ("u", "Phage", "Phage M13", "phage M13", 0.01, ["NC_003287.2"]),
    "Phage_PhiX174":     ("v", "Phage", "Phage PhiX174", "phiX174", 0.01, ["NC_001422.1"]),
    "Phage_P1":          ("w", "Phage", "Phage P1", "phage P1", 0.09, ["NC_005856.1"]),
}
BY_LETTER = {v[0]: k for k, v in GENOMES.items()}
ALIASES = {"ecoli": "E_coli_MG1655", "e_coli_k12": "E_coli_MG1655",
           "yeast": "S_cerevisiae", "subtilis": "B_subtilis_168",
           "pichia": "K_phaffii", "lambda": "Phage_lambda"}


def resolve(choice: str) -> str:
    """Accept a menu letter, a host key, or a friendly alias. Returns '' if unknown."""
    if not choice:
        return ""
    c = choice.strip()
    if c.lower() in BY_LETTER:
        return BY_LETTER[c.lower()]
    if c in GENOMES:
        return c
    return ALIASES.get(c.lower(), "")


def find_ref_genomes() -> Path:
    """Put genomes beside the parts library, which is where the checker looks."""
    here = Path(__file__).resolve().parent
    for base in (here, *here.parents):
        lib = base / "parts-library"
        if lib.is_dir():
            d = lib.parent / "ref_genomes" if (lib.parent / "ref_genomes").is_dir() else lib / "ref_genomes"
            d.mkdir(parents=True, exist_ok=True)
            return d
    d = here / "ref_genomes"
    d.mkdir(parents=True, exist_ok=True)
    return d


def show_list() -> None:
    print()
    print("  Which organism are you working in?  Type its LETTER and press Enter.")
    print()
    group = None
    for key, (letter, grp, label, _org, mb, accs) in GENOMES.items():
        if grp != group:
            group = grp
            print(f"    -- {grp} --")
        n = f"   [{len(accs)} records]" if len(accs) > 1 else ""
        size = f"{mb:>5.1f} MB" if mb >= 0.1 else "  < 1 MB"
        print(f"     {letter})  {label:<52} {size}{n}")
    print()
    print("     other)  something else - any accession in NCBI nucleotide")
    print("     quit )  leave without downloading anything")
    print()


def fetch(accessions: list[str], expect_org: str, out: Path) -> tuple[bool, str]:
    """Download, then verify the record headers BEFORE keeping the file.

    A silently wrong genome makes the off-target check pass for the wrong reason, which is
    worse than not running it at all. So a download whose headers do not match the organism
    that was asked for is refused, not saved.
    """
    url = EFETCH.format(ids=",".join(accessions))
    try:
        data = urllib.request.urlopen(url, timeout=180).read().decode("utf-8", "replace")
    except Exception as e:
        return False, f"download failed: {e!r}"

    heads = [l[1:].strip() for l in data.splitlines() if l.startswith(">")]
    if len(heads) != len(accessions):
        return False, (f"expected {len(accessions)} record(s), got {len(heads)} - NOT saved. "
                       f"NCBI may have returned an error page instead of sequence.")
    if expect_org:
        wrong = [h for h in heads if expect_org.lower() not in h.lower()]
        if wrong:
            return False, (f"a record does not mention '{expect_org}' - NOT saved. "
                           f"First mismatch: {wrong[0][:70]}")
    bases = sum(len(l.strip()) for l in data.splitlines() if not l.startswith(">"))
    if bases < 1000:
        return False, f"only {bases} bases returned - NOT saved."

    out.write_text(data, encoding="utf-8", newline="\n")
    sha = hashlib.sha256(data.encode("utf-8")).hexdigest()
    return True, f"{len(heads)} record(s), {bases:,} bases, sha256 {sha[:16]}"


def register(ref_dir: Path, key: str, filename: str, accessions: list[str], note: str) -> None:
    """Record what was fetched, so the checker finds it and a human can audit it.

    The same discipline every part in the library gets: an accession, a date, and a hash.
    A genome you cannot trace is no better than a sequence you cannot trace.
    """
    reg = ref_dir / "genomes.tsv"
    header = "host_key\tfilename\taccessions\tfetched\tnote\n"
    rows = {}
    if reg.exists():
        for line in reg.read_text(encoding="utf-8").splitlines()[1:]:
            if line.strip():
                rows[line.split("\t")[0]] = line
    rows[key] = f"{key}\t{filename}\t{','.join(accessions)}\t{date.today().isoformat()}\t{note}"
    reg.write_text(header + "\n".join(rows[k] for k in sorted(rows)) + "\n",
                   encoding="utf-8", newline="\n")


def specs_by_host(here: Path) -> dict:
    """Which host does each Design Spec beside us declare?

    Read with a deliberately dumb line scan rather than a YAML parser: this tool's whole point is
    that it works with nothing installed, and pulling in PyYAML to print a hint would break that.
    A Spec whose host cannot be read this way simply does not appear, which is the safe direction.
    """
    out = {}
    for p in sorted((here / "specs").glob("*.spec.yaml")):
        try:
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                s = line.strip()
                if s.startswith("host:"):
                    h = s.split(":", 1)[1].split("#")[0].strip().strip("\"'")
                    if h:
                        out.setdefault(h, []).append(p.name)
                    break
        except Exception:
            continue
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch a host genome for the off-target check.")
    ap.add_argument("--list", action="store_true", help="show the menu and exit")
    ap.add_argument("--host", help="menu letter, host key, or alias (e.g. a, E_coli_MG1655, ecoli)")
    ap.add_argument("--accession", help="any NCBI nucleotide accession(s), comma-separated")
    ap.add_argument("--name", help="filename stem, used with --accession")
    ap.add_argument("--key", help="host key to register it under, used with --accession")
    args = ap.parse_args()

    if args.list:
        show_list()
        return 0

    ref_dir = find_ref_genomes()

    if args.accession:
        accs = [a.strip() for a in args.accession.split(",") if a.strip()]
        key = args.key or (args.name or accs[0])
        stem = args.name or accs[0].replace(".", "_")
        expect = ""
        print(f"\n  Fetching {len(accs)} record(s) from NCBI ...")
    else:
        key = resolve(args.host) if args.host else ""
        if not key:
            show_list()
            try:
                choice = input("  Letter (or 'other' / 'quit'): ").strip()
            except EOFError:
                choice = ""
            low = choice.lower()
            # An empty line used to exit printing NOTHING at all, which looked exactly like
            # it had silently done something. Always say what happened.
            if low in ("", "q", "quit", "exit"):
                print("\n  Nothing selected, so nothing was downloaded.")
                print("  Run this again when you know which organism you need.\n")
                return 0
            if low == "other":
                print("\n  For anything not on the menu, pass the accession directly:\n")
                print("    python get_genome.py --accession <ACCESSION> --name <filename> --key <HostKey>")
                print("    e.g. python get_genome.py --accession M77789.2 --name pUC19 --key pUC19\n")
                print("  The key is whatever your Design Spec's host field says.\n")
                return 0
            key = resolve(choice)
            if not key:
                print(f"\n  '{choice}' is not one of the letters above, so nothing was downloaded.")
                print("  Run this again and type a single letter, or 'quit' to leave.\n")
                return 1
        if key not in GENOMES:
            print(f"\n  BLOCK: '{key}' is not a host I know. Run --list for the menu, "
                  f"or use --accession for anything else.")
            return 1
        _letter, _grp, label, expect, mb, accs = GENOMES[key]
        stem = key
        print(f"\n  {label}")
        print(f"  about {mb:.1f} MB, {len(accs)} record(s) from NCBI. Fetching ...")

    out = ref_dir / f"{stem}.fna"
    t0 = time.time()
    ok, msg = fetch(accs, expect, out)
    if not ok:
        print(f"  REFUSED: {msg}\n")
        return 1

    register(ref_dir, key, out.name, accs, msg)
    print(f"  OK - {msg}")
    print(f"  saved  {out}")
    print(f"  took   {time.time() - t0:.1f}s")
    print()
    print(f"  The off-target check will now use it for host '{key}'.")
    print()

    # Only promise the SKIPPED warning will go away for a Spec that actually uses this host.
    # Saying it unconditionally was a lie whenever the reader picked a chassis the example does
    # not use, and it sent them to a build that still reported SKIPPED after a 5 MB download.
    here = Path(__file__).resolve().parent
    hosts = specs_by_host(here)
    mine = hosts.get(key, [])

    if mine:
        print(f"  {len(mine)} Design Spec(s) here use host '{key}'. For those, Stage 4b will")
        print("  now run the off-target scan for real instead of reporting SKIPPED:")
        print()
        print(f"      python katana_build.py specs/{mine[0]}")
        print()
    elif hosts:
        others = ", ".join(sorted(hosts))
        print(f"  NOTE: none of the Design Specs here use host '{key}'.")
        print(f"        That is perfectly fine if you are building your own construct in it.")
        print(f"        But if you are following the worked example, its host is {others},")
        print(f"        and Stage 4b will still report OFF-TARGET SKIPPED until you fetch that")
        print(f"        one too. Nothing you have done is wrong, and the genome you just")
        print(f"        downloaded is kept - a library can hold several.")
        print()
        for h, names in sorted(hosts.items()):
            print(f"        {h:<22} needed by {names[0]}"
                  + (f" (+{len(names) - 1} more)" if len(names) > 1 else ""))
        print()
        print("        To fetch it:   python get_genome.py")
        print()
    else:
        print("      python katana_build.py <path-to-your-spec>.spec.yaml")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
