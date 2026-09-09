#!/usr/bin/env python3
"""
katana_order_table.py — write the build as a vendor order table (CSV).

Why a fourth output format. The same construct has to be handed to different people in
different shapes: a synthesis vendor's bulk-upload form wants a spreadsheet with one row
per orderable piece, a different vendor wants FASTA, a colleague wants an annotated
GenBank map, and another tool wants SBOL. None of those is more "real" than the others —
they are the same sealed bases, and the engine emits all of them from one build so nobody
is retyping a sequence into a web form. Retyping is exactly where a sequence and its label
drift apart, which is the failure this whole project exists to prevent.

The table carries `seq_sha256` alongside every sequence deliberately. When the synthesised
DNA comes back, that column is what you check the vendor's returned sequence against.

One row per orderable piece: the whole insert, plus one row per fragment when the insert
is too long for a vendor's single-fragment cap and has been split.
"""
from __future__ import annotations

import csv
from pathlib import Path

# Excel refuses to display a cell longer than this, and silently truncates on some import
# paths. Worth saying out loud rather than letting someone paste a truncated sequence.
EXCEL_CELL_LIMIT = 32767

COLUMNS = [
    "name",             # what to call this piece on the order form
    "role",             # insert | fragment
    "length_bp",
    "sequence",         # the bases themselves, uppercase (matches the hashed form)
    "seq_sha256",       # check the vendor's returned sequence against this
    "construct",
    "version",
    "host",
    "vector",
    "assembly_method",
    "note",
]


def write_order_csv(records: list[dict], spec: dict, out_path: Path) -> list[str]:
    """Write the order table. Returns a list of messages for the caller to print."""
    msgs: list[str] = []
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    backbone = spec.get("backbone", {}) or {}
    assembly = spec.get("assembly", {}) or {}
    common = {
        "construct": spec.get("id", ""),
        "version": spec.get("version", ""),
        "host": spec.get("host", ""),
        "vector": backbone.get("vector", ""),
        "assembly_method": assembly.get("method", ""),
    }

    # newline="" is required by the csv module; Excel is happiest with CRLF line endings.
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, dialect="excel")
        w.writeheader()
        for rec in records:
            row = dict(common)
            row.update(rec)
            w.writerow({k: row.get(k, "") for k in COLUMNS})

    oversize = [r["name"] for r in records
                if len(str(r.get("sequence", ""))) > EXCEL_CELL_LIMIT]
    if oversize:
        msgs.append(f"WARN CSV: {len(oversize)} sequence(s) exceed Excel's {EXCEL_CELL_LIMIT}-character "
                    f"cell limit and may display truncated ({', '.join(oversize)}). The CSV itself is "
                    f"complete — use the FASTA for those, or check the file in a text editor.")
    return msgs
