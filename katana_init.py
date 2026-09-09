#!/usr/bin/env python3
"""
katana_init.py — start your own Parts Library and your own Design Spec.

Why this exists. Until this tool, Katana could be run but not adopted. You could build our
construct, watch the gates fire, and break the manifest to prove the checker works — and then
you were stuck, because there was no way to add a part of your own. The only library the engine
could find was ours, and adding to ours would break its seal and make `verify.py` correctly
accuse you of tampering. A tool whose only supported use is running someone else's example is a
demonstration, not a tool.

So: this makes YOUR library. Ours stays sealed and verifiable as the reference it is meant to
be, and yours is the one you fill.

    python katana_init.py my-project

leaves you with

    my-project/
      parts-library/
        ref_parts/LOCK.tsv     empty manifest, correct root
        ref_parts/LOCK.root
        ref_genomes/           where get_genome.py puts your host
      specs/
        example.spec.yaml      a commented template to edit

Then add parts with add_part.py, and build with
    python katana_build.py my-project/specs/my.spec.yaml --library my-project/parts-library
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import date
from pathlib import Path

# Must match katana_lock.FIELDS exactly. The manifest header is not decoration: row_sha256 is
# computed over these keys in this order, so a header that disagrees with the hashing code
# produces rows whose hashes nobody can reproduce.
FIELDS = ["id", "version", "seq_sha256", "file_sha256", "length",
          "source", "date", "class", "outfile"]

# The manifest HEADER is FIELDS plus row_sha256. The distinction matters and cost a build:
# FIELDS is what row_sha256 is computed OVER, so it cannot contain row_sha256 itself, but the
# column still has to exist in the file or the engine cannot read the row back.
HEADER = FIELDS + ["row_sha256"]

# lock_root over zero rows: sha256 of the empty string. Written rather than hard-coded so it
# stays correct if the rule ever changes.
EMPTY_ROOT = hashlib.sha256("".join([]).encode()).hexdigest()

SPEC_TEMPLATE = '''\
# A Katana Design Spec: what you MEANT, not what the DNA is.
#
# Notice what this file cannot contain: there is no field anywhere for a DNA sequence.
# Parts are named, never pasted. That is deliberate - it is what makes a mislabelled part
# impossible to express rather than merely unlikely. The engine looks each part up in your
# sealed library by id, checks its fingerprint, and refuses if they disagree.
#
# Edit this file, then build it:
#   python katana_build.py {spec_rel} --library {lib_rel}

id:            my-construct
version:       1
track:         {track}
purpose:       "One sentence on what this construct is supposed to do."

host:          E_coli_MG1655        # fetch its genome with:  python get_genome.py
backbone:      {{ vector: pSB1C3, ori: pMB1, marker: CmR }}
assembly:      {{ method: single_fragment, decided: "{today}",
                 note: "Why this method. single_fragment means order it as one synthesised piece." }}
vendor:        Twist

constraints:
  fragment_bp_max: 5000              # your vendor's cap for a single synthesised fragment
  forbid_sites:    [EcoRI, XbaI, SpeI, PstI]
  host_context:    E_coli_MG1655     # the off-target scan runs against this genome
  output_gate:     none

# DISTINCT parts. Each one must already be in your library - add them with add_part.py first.
# `seal` is the pin: the engine refuses to build if the library's fingerprint has moved.
# add_part.py prints the exact seal line to paste here when it admits a part.
parts:
  - id: J23100
    role: promoter
    class: reference                 # reference = fetched from a database; designed = you made it
    source: {{ registry: iGEM, part: BBa_J23100 }}
    seal:   {{ status: SEALED, lib: "PASTE_FROM_add_part.gb",
              seq_sha256_12: PASTE_FROM_add_part, length: 0 }}

# The left-to-right order the parts are assembled in. Ids may repeat here if a part is reused.
architecture:
  order:      [J23100]
  topology:   linear-insert
  junction_rules:
    - "no forbidden RE site across any junction"
'''


def write_bytes(path: Path, text: str) -> None:
    """Write with explicit LF and no BOM.

    Byte-level determinism matters here: file_sha256 is taken over the bytes, so letting the
    platform choose a line ending would make the same library hash differently on Windows and
    Linux. .gitattributes keeps git from undoing this on checkout.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(text.encode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Create an empty Katana Parts Library and a Design Spec template.")
    ap.add_argument("directory", type=Path,
                    help="where to create the project (e.g. my-project)")
    ap.add_argument("--track", default="my-team",
                    help="a short label for your project, recorded in the Spec (default: my-team)")
    ap.add_argument("--force", action="store_true",
                    help="write into a directory that already has a library (refuses otherwise)")
    a = ap.parse_args()

    root = a.directory.expanduser().resolve()
    lib = root / "parts-library"
    ref_parts = lib / "ref_parts"
    lock = ref_parts / "LOCK.tsv"

    # Refuse to overwrite a library that already has parts in it. Silently resetting somebody's
    # manifest to empty would destroy provenance that cannot be reconstructed.
    if lock.exists() and not a.force:
        rows = [l for l in lock.read_text(encoding="utf-8").splitlines()[1:] if l.strip()]
        return _exit(f"BLOCK: {lock} already exists with {len(rows)} part(s).\n"
                     f"       Adding to it is add_part.py's job. Pass --force only if you\n"
                     f"       genuinely want to discard that manifest.")

    write_bytes(lock, "\t".join(HEADER) + "\n")
    write_bytes(ref_parts / "LOCK.root", EMPTY_ROOT + "\n")
    (lib / "ref_genomes").mkdir(parents=True, exist_ok=True)

    spec_path = root / "specs" / "example.spec.yaml"
    if not spec_path.exists() or a.force:
        write_bytes(spec_path, SPEC_TEMPLATE.format(
            today=date.today().isoformat(),
            track=a.track,
            spec_rel=_rel(spec_path),
            lib_rel=_rel(lib)))

    print()
    print(f"  Created {root}")
    print(f"    parts-library/ref_parts/LOCK.tsv   empty manifest (root {EMPTY_ROOT[:12]}…)")
    print(f"    parts-library/ref_genomes/         where get_genome.py will put your host")
    print(f"    specs/example.spec.yaml            a template to edit")
    print()
    print("  Next, put a part in your library. A reference part from NCBI:")
    print()
    print(f"      python add_part.py --library {_rel(lib)} --id lacZ \\")
    print( "          --accession NC_000913.3 --range 363231..366305 --strand -")
    print()
    print("  or a part you designed yourself, from a local FASTA or GenBank file:")
    print()
    print(f"      python add_part.py --library {_rel(lib)} --id my_rbs --file my_rbs.fasta")
    print()
    print("  Each one prints the `seal:` line to paste into your Spec.")
    print()
    return 0


def _rel(p: Path) -> str:
    """Show a path relative to the working directory when that is shorter and clearer."""
    try:
        return str(p.relative_to(Path.cwd()))
    except ValueError:
        return str(p)


def _exit(msg: str) -> int:
    print(msg)
    return 1


if __name__ == "__main__":
    sys.exit(main())
