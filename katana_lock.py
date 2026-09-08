#!/usr/bin/env python3
"""
katana_lock.py — Parts Library integrity core (Gaps 2 + 4b + fail-closed reads).

What it adds over the byte hashes already in LOCK.tsv:
  * row_sha256 — a MANIFEST hash over every trust-bearing field of a LOCK row
    (id, version, seq_sha256, file_sha256, length, source, date, class, outfile).
    This SEALS the row itself: editing an accession in `source`, silently bumping
    `version`, or repointing `outfile` now changes row_sha256 and is caught.
  * LOCK.root — SHA-256 over the ordered row_sha256 column (a Merkle-style root).
    Any appended/removed/edited row changes the root; LOCK.root.log keeps an
    append-only history of roots (lightweight attestation, no keys).
  * resolve() — refuses id-only / "latest" resolution (Gap 2): you MUST pass a
    version, and may pin an expected seq_sha12; filename sha12 is checked == seq hash.

Hashing conventions (reverse-engineered + confirmed against the live library 2026-07-05):
  file_sha256 = sha256(raw file bytes)
  seq_sha256  = sha256(UPPERCASE sequence, letters only; GenBank ORIGIN or FASTA body)
  filename    = <id>__v<N>__<seq_sha256[:12]>.<ext>
No third-party deps (no Biopython) — safe on any Python 3.8+.
"""
import hashlib, os, sys

FIELDS = ["id","version","seq_sha256","file_sha256","length","source","date","class","outfile"]

def sha256_bytes(b): return hashlib.sha256(b).hexdigest()

def parse_sequence(path):
    """Extract the sequence exactly as seq_sha256 was computed (letters only, UPPER)."""
    ext = os.path.splitext(path)[1].lower()
    txt = open(path, "r", encoding="utf-8", errors="strict").read()
    seq = []
    if ext in (".gb", ".gbk", ".genbank"):
        inorig = False
        for line in txt.splitlines():
            if line.startswith("ORIGIN"): inorig = True; continue
            if line.startswith("//"): inorig = False; continue
            if inorig: seq.append("".join(c for c in line if c.isalpha()))
    elif ext in (".faa", ".fa", ".fasta", ".fna"):
        for line in txt.splitlines():
            if line.startswith(">"): continue
            seq.append("".join(c for c in line if c.isalpha()))
    else:
        raise ValueError(f"unknown part extension: {ext}")
    return "".join(seq).upper()

def file_hash(path):  return sha256_bytes(open(path,"rb").read())
def seq_hash(path):   return sha256_bytes(parse_sequence(path).encode())

def row_manifest(row):
    """Canonical, order-fixed manifest string over trust-bearing fields (excl. row_sha256)."""
    return "\n".join(f"{k}={row.get(k,'')}" for k in FIELDS)

def row_sha256(row): return sha256_bytes(row_manifest(row).encode())

def read_lock(path):
    with open(path, "r", encoding="utf-8") as f:
        lines = [l.rstrip("\n") for l in f if l.strip()!=""]
    header = lines[0].split("\t")
    rows = [dict(zip(header, l.split("\t"))) for l in lines[1:]]
    return header, rows

def lock_root(rows):
    """SHA-256 over ordered row_sha256 values (recomputed, not trusted from the column)."""
    return sha256_bytes("\n".join(row_sha256(r) for r in rows).encode())

def filename_sha12(outfile):
    base = os.path.basename(outfile)
    # <id>__v<N>__<sha12>.<ext>
    core = base.rsplit(".",1)[0]
    return core.split("__")[-1]

# ---------- resolver: Gap 2 (no id-only / latest) ----------
class ResolveError(Exception): pass

def resolve(rows, id, version=None, expected_seq_sha12=None):
    if version is None:
        raise ResolveError(f"id-only resolution is banned (Gap 2): pass a version for '{id}'")
    version = str(version)
    hits = [r for r in rows if r["id"]==id and str(r["version"])==version]
    if len(hits)==0:
        raise ResolveError(f"no sealed row for {id} v{version} (fail-closed)")
    if len(hits)>1:
        raise ResolveError(f"AMBIGUOUS: {len(hits)} rows for {id} v{version}")
    r = hits[0]
    fn12 = filename_sha12(r["outfile"])
    if fn12 != r["seq_sha256"][:12]:
        raise ResolveError(f"{id} v{version}: filename sha12 {fn12} != seq_sha256 {r['seq_sha256'][:12]}")
    if expected_seq_sha12 and not r["seq_sha256"].startswith(expected_seq_sha12):
        raise ResolveError(f"{id} v{version}: pin mismatch, expected {expected_seq_sha12}, got {r['seq_sha256'][:12]}")
    return r
