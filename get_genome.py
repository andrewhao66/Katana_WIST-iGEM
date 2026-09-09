#!/usr/bin/env python3
"""
get_genome.py — fetch the host genome you need, when you need it.

WHY THIS EXISTS INSTEAD OF SHIPPING GENOMES

The off-target check compares your construct against the whole genome of the organism you
are putting it into, looking for stretches that accidentally match the host. That needs a
genome file, and genomes are big: E. coli is 4.5 MB, yeast is 12 MB. Shipping a handful
would bloat the repository for everyone, and would still be the wrong handful for the team
working in Vibrio or Synechocystis.

So nothing is bundled. You fetch the one you actually use, once, and it lands where the
checker looks. A team is never blocked because we failed to guess their chassis.

  python get_genome.py                 pick from a list
  python get_genome.py --list          show the list and exit
  python get_genome.py --host ecoli    fetch one non-interactively
  python get_genome.py --accession NC_045512.2 --name my_virus --key MyHost
                                       fetch anything else in NCBI nucleotide

EVERY ACCESSION BELOW WAS VERIFIED against NCBI on 2026-09-09 by fetching it and reading
the organism name back out of the record header. None of them is typed from memory. The
download is verified the same way before it is kept: a file whose headers do not match the
organism you asked for is rejected rather than saved, because a silently wrong genome makes
the off-target check pass for the wrong reason, which is worse than not running it at all.

Requires only Python's standard library, and an internet connection for the fetch itself.
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

# key -> (display name, expected organism substring, ~MB, [accessions])
# The `key` is what a Design Spec's `host` / `constraints.host_context` field says.
GENOMES: dict[str, tuple] = {
    "E_coli_MG1655": ("E. coli K-12 MG1655 - the default iGEM chassis",
                      "Escherichia coli", 4.6, ["NC_000913.3"]),
    "E_coli_Nissle": ("E. coli Nissle 1917 - probiotic chassis",
                      "Escherichia coli", 5.4, ["CP007799.1"]),
    "E_coli_BL21":   ("E. coli BL21(DE3) - protein expression",
                      "Escherichia coli", 4.6, ["CP001509.3"]),
    "B_subtilis_168":("Bacillus subtilis 168 - Gram-positive workhorse",
                      "Bacillus subtilis", 4.2, ["NC_000964.3"]),
    "S_cerevisiae":  ("S. cerevisiae S288C - baker's yeast, all 16 chromosomes",
                      "Saccharomyces cerevisiae", 12.2,
                      ["NC_001133.9","NC_001134.8","NC_001135.5","NC_001136.10",
                       "NC_001137.3","NC_001138.5","NC_001139.9","NC_001140.6",
                       "NC_001141.2","NC_001142.9","NC_001143.9","NC_001144.5",
                       "NC_001145.3","NC_001146.8","NC_001147.6","NC_001148.4"]),
    "P_putida_KT2440":("Pseudomonas putida KT2440 - robust soil bacterium",
                      "Pseudomonas putida", 6.2, ["NC_002947.4"]),
    "Synechocystis_6803":("Synechocystis sp. PCC 6803 - photosynthetic",
                      "Synechocystis", 3.6, ["NC_000911.1"]),
    "L_lactis_IL1403":("Lactococcus lactis IL1403 - food-grade",
                      "Lactococcus lactis", 2.4, ["NC_002662.1"]),
    "V_natriegens":  ("Vibrio natriegens - very fast growing",
                      "Vibrio natriegens", 5.2, ["NZ_CP009977.1"]),
    "C_glutamicum":  ("Corynebacterium glutamicum ATCC 13032 - amino-acid producer",
                      "Corynebacterium glutamicum", 3.3, ["NC_003450.3"]),
}
ALIASES = {"ecoli": "E_coli_MG1655", "E_coli_K12": "E_coli_MG1655",
           "yeast": "S_cerevisiae", "subtilis": "B_subtilis_168"}


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
    print("\nHost genomes this tool knows about:\n")
    print(f"  {'key':<20} {'approx':>7}  organism")
    print("  " + "-" * 74)
    for key, (label, _org, mb, accs) in GENOMES.items():
        n = f" ({len(accs)} records)" if len(accs) > 1 else ""
        print(f"  {key:<20} {mb:>5.1f} MB  {label}{n}")
    print("\n  Anything else:  python get_genome.py --accession <ACC[,ACC2,...]> "
          "--name <filename> --key <HostKey>\n")


def fetch(accessions: list[str], expect_org: str, out: Path) -> tuple[bool, str]:
    """Download, then verify the record headers before keeping the file."""
    url = EFETCH.format(ids=",".join(accessions))
    try:
        data = urllib.request.urlopen(url, timeout=180).read().decode("utf-8", "replace")
    except Exception as e:
        return False, f"download failed: {e!r}"

    heads = [l[1:].strip() for l in data.splitlines() if l.startswith(">")]
    if len(heads) != len(accessions):
        return False, (f"expected {len(accessions)} record(s), got {len(heads)} — "
                       f"NOT saved. NCBI may have returned an error page.")
    if expect_org:
        wrong = [h for h in heads if expect_org.lower() not in h.lower()]
        if wrong:
            return False, (f"record header does not mention '{expect_org}' — NOT saved. "
                           f"First mismatch: {wrong[0][:80]}")
    bases = sum(len(l.strip()) for l in data.splitlines() if not l.startswith(">"))
    if bases < 1000:
        return False, f"only {bases} bases returned — NOT saved."

    out.write_text(data, encoding="utf-8", newline="\n")
    sha = hashlib.sha256(data.encode("utf-8")).hexdigest()
    return True, (f"{len(heads)} record(s), {bases:,} bases, sha256 {sha[:16]}…")


def register(ref_dir: Path, key: str, filename: str, accessions: list[str], note: str) -> None:
    """Record what was fetched, so the checker can find it and a human can audit it.

    Same discipline the parts library uses: an accession, a date, and a hash. A genome you
    cannot trace is no better than a sequence you cannot trace.
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


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch a host genome for the off-target check.")
    ap.add_argument("--list", action="store_true", help="show known genomes and exit")
    ap.add_argument("--host", help="key from --list (e.g. E_coli_MG1655)")
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
        print(f"\nFetching {len(accs)} record(s) from NCBI …")
    else:
        key = ALIASES.get(args.host or "", args.host or "")
        if not key:
            show_list()
            try:
                choice = input("Which host are you working in? (type a key, or q to quit): ").strip()
            except EOFError:
                return 1
            if choice.lower() in ("q", "quit", ""):
                return 0
            key = ALIASES.get(choice, choice)
        if key not in GENOMES:
            print(f"\nBLOCK: '{key}' is not a key I know. Run --list to see them, or use "
                  f"--accession to fetch anything else.")
            return 1
        label, expect, mb, accs = GENOMES[key]
        stem = key
        print(f"\n{label}\n  about {mb:.1f} MB, {len(accs)} record(s) from NCBI. Fetching …")

    out = ref_dir / f"{stem}.fna"
    t0 = time.time()
    ok, msg = fetch(accs, expect, out)
    if not ok:
        print(f"  BLOCK: {msg}")
        return 1

    register(ref_dir, key, out.name, accs, msg)
    print(f"  OK — {msg}")
    print(f"  saved  {out}")
    print(f"  took   {time.time() - t0:.1f}s")
    print(f"\nThe off-target check will now use it for host '{key}'. Re-run your build "
          f"and Stage 4b should stop reporting OFF-TARGET SKIPPED.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
