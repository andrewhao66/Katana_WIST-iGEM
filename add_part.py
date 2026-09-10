#!/usr/bin/env python3
"""
add_part.py — admit one part to your Parts Library, through the gate.

This is the intake door. A part gets in exactly one way: fetched from a primary source (or
read from a file you point at), checked, written once, fingerprinted, and recorded in the
manifest with where it came from and when. Nothing is ever edited in place afterwards — a
corrected part becomes a new version with a new fingerprint, and the old row stays.

    # a reference part, straight from NCBI, by accession and coordinates
    python add_part.py --library my-project/parts-library --id lacZ \\
        --accession NC_000913.3 --range 363231..366305 --strand -

    # a part you designed, or one you saved from the iGEM Registry page
    python add_part.py --library my-project/parts-library --id my_rbs \\
        --file my_rbs.fasta --class designed --source "designed: OSTIR TIR 12000"

The iGEM Registry, corrected. An earlier version of this file said the Registry could not be
fetched. That was wrong, and the error is worth recording: two endpoints on parts.igem.org (the
cgi/XML one and the FASTA one) return 403, and testing only those two led to a conclusion about
the whole Registry. api.registry.igem.org/v1 is public, needs no account, and returns the
sequence along with a uuid and an SO role accession. A negative result about one route is not a
result about the destination.

    python add_part.py --library my-project/parts-library --registry BBa_B0015

Why the round-trip check at the end. It would be easy to compute a hash over the sequence in
memory, write a file, and record that hash — and be wrong, because the thing the engine will
later read is the FILE, not what was in memory. So after writing, this re-reads the file with
the same parser the build engine uses and recomputes the hash from that. If they disagree the
part is removed and nothing is recorded. Check the artifact, not the tool.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

# Must match katana_lock.FIELDS and the LOCK.tsv header, in this order: row_sha256 is computed
# over these keys in sequence, so any disagreement produces unreproducible rows.
FIELDS = ["id", "version", "seq_sha256", "file_sha256", "length",
          "source", "date", "class", "outfile"]

EFETCH = ("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
          "?db=nuccore&rettype=fasta&retmode=text&id={acc}")

VALID_DNA = set("ACGTNRYKMSWBDHV")   # IUPAC; N and the ambiguity codes are legal in a part
COMPLEMENT = str.maketrans("ACGTNRYKMSWBDHVacgtnrykmswbdhv",
                           "TGCANYRMKSWVHDBtgcanyrmkswvhdb")


# ── hashing: must match the build engine exactly ────────────────────────────
def sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def seq_sha256(seq: str) -> str:
    """The engine's canonical sequence hash: uppercase letters, ASCII, nothing else.

    Deliberately identical to katana_build.seq_sha256. If these two ever drift, every part this
    tool admits becomes unbuildable, so the duplication is on purpose and load-bearing.
    """
    return sha256_hex(seq.upper().encode("ascii"))


def row_sha256(row: dict) -> str:
    return sha256_hex("\n".join(f"{k}={row.get(k, '')}" for k in FIELDS).encode())


def lock_root(rows: list[dict]) -> str:
    """SHA-256 over the ordered row hashes, recomputed rather than read from the column."""
    return sha256_hex("\n".join(row_sha256(r) for r in rows).encode())


def extract_gb_sequence(text: str) -> str:
    """Byte-for-byte the same logic as katana_build.extract_gb_sequence."""
    in_origin, parts = False, []
    for line in text.splitlines():
        if line.startswith("ORIGIN"):
            in_origin = True
            continue
        if in_origin:
            if line.startswith("//"):
                break
            parts.append(re.sub(r"[^A-Za-z]", "", line))
    return "".join(parts).upper()


def read_fasta(text: str) -> str:
    return "".join(re.sub(r"[^A-Za-z]", "", l)
                   for l in text.splitlines() if not l.startswith(">")).upper()


# ── the manifest ────────────────────────────────────────────────────────────
def read_lock(path: Path) -> tuple[list[str], list[dict]]:
    lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    header = lines[0].split("\t")
    return header, [dict(zip(header, l.split("\t"))) for l in lines[1:]]


def write_lock(path: Path, header: list[str], rows: list[dict]) -> None:
    out = ["\t".join(header)]
    out += ["\t".join(r.get(k, "") for k in header) for r in rows]
    with open(path, "wb") as f:
        f.write(("\n".join(out) + "\n").encode("utf-8"))


# ── sources ─────────────────────────────────────────────────────────────────
def fetch_ncbi(acc: str, rng: str | None, strand: str,
               expect_org: str | None = None) -> tuple[str, str]:
    """Fetch from NCBI, letting the server do the sub-range and the reverse complement.

    Asking NCBI for the range is safer than fetching a whole genome and slicing it here: an
    off-by-one in local slicing is invisible, and coordinate conventions are exactly the thing
    that produced failure 3 in our own project.
    """
    url = EFETCH.format(acc=urllib.parse.quote(acc))
    start = end = None
    if rng:
        m = re.fullmatch(r"(\d+)\s*(?:\.\.|-)\s*(\d+)", rng.strip())
        if not m:
            raise SystemExit(f"BLOCK: --range must look like 363231..366305 (got {rng!r})")
        start, end = int(m.group(1)), int(m.group(2))
        if start > end:
            raise SystemExit(f"BLOCK: --range start {start} is after end {end}. "
                             f"For the reverse strand use --strand - and keep start < end.")
        url += f"&seq_start={start}&seq_stop={end}"
    if strand == "-":
        url += "&strand=2"

    req = urllib.request.Request(url, headers={"User-Agent": "katana-add-part/1.0"})
    try:
        data = urllib.request.urlopen(req, timeout=120).read().decode("utf-8", "replace")
    except Exception as e:
        raise SystemExit(f"BLOCK: NCBI download failed: {e!r}")

    heads = [l[1:].strip() for l in data.splitlines() if l.startswith(">")]
    if len(heads) != 1:
        raise SystemExit(f"BLOCK: expected exactly 1 record from NCBI, got {len(heads)}. "
                         f"NCBI may have returned an error page rather than sequence.")
    seq = read_fasta(data)
    if not seq:
        raise SystemExit("BLOCK: NCBI returned a record with no sequence in it.")

    # DEFECT 2: a range past the end of the record is CLIPPED by NCBI, and a shorter
    # sequence than you asked for is a truncation - the failure this project was built around.
    # Nothing else downstream can notice, because every hash will be self-consistent.
    if start is not None:
        want = end - start + 1
        if len(seq) != want:
            raise SystemExit(
                f"BLOCK: asked for {want} bp ({start}..{end}) but NCBI returned {len(seq)} bp.\n"
                f"       The record is shorter than the range, so this would seal a TRUNCATED\n"
                f"       part. Nothing was written. Check the coordinates against the record:\n"
                f"       https://www.ncbi.nlm.nih.gov/nuccore/{acc}")

    # DEFECT 1: the sequence being what NCBI sent is not the same claim as the sequence being
    # what you MEANT. Only the caller knows which organism they intended, so this can decide
    # only when they say - and when they do not, it says so loudly rather than nodding along.
    if expect_org:
        if expect_org.lower() not in heads[0].lower():
            raise SystemExit(
                f"BLOCK: expected {expect_org!r} but the record says:\n"
                f"       {heads[0][:96]}\n"
                f"       Nothing was written. A part whose label and record disagree is exactly\n"
                f"       the failure this software exists to prevent. If the record IS right and\n"
                f"       your expectation was worded differently, re-run with the wording above.")

    coords = f":{start}-{end}" if start else ""
    source = f"NCBI {acc}{coords}({strand})"
    print(f"  fetched {len(seq)} bp from NCBI")
    print(f"  record  {heads[0][:78]}")
    if expect_org:
        print(f"  checked the record names {expect_org!r} before keeping it")
    else:
        print()
        print("  NOTE: no --expect-organism given, so the LABEL was not checked against the")
        print("        record. The hash proves what you downloaded; it cannot prove you asked")
        print("        for the right thing. Read the record line above. To have this checked:")
        print(f"            --expect-organism \"<organism as NCBI names it>\"")
        print()
    return seq, source


REGISTRY_API = "https://api.registry.igem.org/v1"


def fetch_registry(name: str) -> tuple[str, str, str]:
    """Fetch a part from the iGEM Registry by its BBa_ name.

    Uses api.registry.igem.org, which is public and needs no account. The older
    parts.igem.org cgi/XML and FASTA endpoints return 403 and are not usable; testing only those
    two is how this tool previously came to claim the Registry could not be fetched at all.

    Returns (sequence, provenance, role_label). The role label is what the Registry SAYS the part
    is, reported so you can see it - not written into your Spec, because what a part is and what
    you are using it for are different questions and the second one is yours.
    """
    import json
    def _get(url: str):
        req = urllib.request.Request(url, headers={"User-Agent": "katana-add-part/1.0"})
        return json.loads(urllib.request.urlopen(req, timeout=60).read())

    try:
        hits = _get(f"{REGISTRY_API}/parts?name={urllib.parse.quote(name)}").get("data") or []
    except Exception as e:
        raise SystemExit(f"BLOCK: could not reach the iGEM Registry: {e!r}")
    if not hits:
        raise SystemExit(f"BLOCK: the Registry has no part called {name!r}.\n"
                         f"       Names look like BBa_B0015 or BBa_J23100. Check the spelling on\n"
                         f"       parts.igem.org, or use --accession for a part from NCBI.")
    uuid = hits[0]["uuid"]
    rec = _get(f"{REGISTRY_API}/parts/{uuid}")

    seq = (rec.get("sequence") or "").strip()
    if not seq:
        raise SystemExit(f"BLOCK: the Registry record for {name} carries no sequence.\n"
                         f"       Some entries are documentation only. Nothing was written.")

    role = ((rec.get("role") or {}).get("label") or "").strip()
    so = ((rec.get("role") or {}).get("accession") or "").strip()
    updated = ((rec.get("audit") or {}).get("updated") or "")[:10]
    title = (rec.get("title") or "").strip()

    # The uuid is an identity check independent of the sequence hash: it says the Registry means
    # THIS record, not merely something with the same bases.
    prov = f"iGEM Registry {name} (uuid {uuid}"
    if so:
        prov += f"; {so} {role}"
    if updated:
        prov += f"; record updated {updated}"
    prov += ")"

    print(f"  fetched {len(seq)} bp from the iGEM Registry")
    if title:
        print(f"  record  {title[:70]}")
    print(f"  uuid    {uuid}")
    return seq, prov, role


def read_local(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"BLOCK: no such file: {path}")
    text = path.read_text(encoding="utf-8", errors="strict")
    ext = path.suffix.lower()
    if ext in (".gb", ".gbk", ".genbank"):
        seq = extract_gb_sequence(text)
    elif ext in (".fa", ".fasta", ".fna", ".txt", ".seq"):
        seq = read_fasta(text)
    else:
        raise SystemExit(f"BLOCK: unknown file type {ext!r}. Use .fasta or .gb.")
    if not seq:
        raise SystemExit(f"BLOCK: no sequence found in {path}.")
    print(f"  read {len(seq)} bp from {path}")
    return seq


def copy_from_library(src: Path, pid: str) -> tuple[str, str, str]:
    """Take a part that is already sealed somewhere else, verifying it on the way out.

    The source row's hash is not trusted because it is written down. The part file is read and
    re-hashed, and a disagreement means the source library is damaged - which is worth knowing
    about loudly rather than propagating into a second library.

    Provenance travels with the part. The original source string is kept and annotated with the
    library it came through, because "copied from a sealed library that recorded NCBI x:y-z" and
    "fetched from NCBI x:y-z" are different claims and only one of them is true here.
    """
    src = src.expanduser().resolve()
    lock = src if src.name == "LOCK.tsv" else src / "LOCK.tsv"
    if not lock.exists():
        raise SystemExit(f"BLOCK: no LOCK.tsv at {lock}")

    rows = read_lock(lock)[1]
    hits = [r for r in rows if r["id"] == pid]
    if not hits:
        names = ", ".join(sorted({r["id"] for r in rows})[:12])
        raise SystemExit(f"BLOCK: no part called {pid!r} in {lock}.\n"
                         f"       That library holds: {names} ...\n"
                         f"       List them all with:  python find_part.py --have")
    row = hits[-1]   # the newest version of that id

    part_file = lock.parent / row["outfile"]
    if not part_file.exists():
        raise SystemExit(f"BLOCK: {lock} lists {row['outfile']} but the file is missing.")

    seq = extract_gb_sequence(part_file.read_text(encoding="utf-8"))
    if seq_sha256(seq) != row["seq_sha256"]:
        raise SystemExit(f"BLOCK: {pid} in the SOURCE library does not match its own hash. "
                         f"That library is damaged - do not copy from it. Run verify.py there.")

    print(f"  copied  {pid} v{row['version']}  {len(seq)} bp  from {lock.parent.name}/")
    print(f"  checked its hash against the source manifest before copying")
    return seq, f"{row['source']} [copied from {lock.parent.name}]", row.get("class", "reference")


# ── the GenBank the engine will read ────────────────────────────────────────
def render_genbank(pid: str, version: int, seq: str, source: str, klass: str) -> str:
    """A minimal, valid GenBank record.

    GenBank rather than FASTA on purpose: the build engine parses part files through its
    ORIGIN-block reader and only falls back to FASTA for the .faa protein case, so a .fasta
    part would be read as empty and blocked. Verified against katana_build.py rather than
    assumed.
    """
    today = date.today().strftime("%d-%b-%Y").upper()
    lines = [
        f"LOCUS       {pid:<24}{len(seq)} bp    DNA     linear   SYN {today}",
        f"DEFINITION  {pid} v{version}, admitted to a Katana Parts Library.",
        f"ACCESSION   {pid}",
        f"VERSION     {pid}.{version}",
        "KEYWORDS    .",
        f"SOURCE      {source}",
        "COMMENT     Admitted by add_part.py. The manifest row in LOCK.tsv, not this file,",
        "            is the record of provenance; this file is the sequence it points at.",
        f"            class: {klass}",
        "FEATURES             Location/Qualifiers",
        f"     source          1..{len(seq)}",
        f'                     /note="{source}"',
        f'                     /label="{pid}"',
        "ORIGIN",
    ]
    low = seq.lower()
    for i in range(0, len(low), 60):
        chunk = low[i:i + 60]
        blocks = " ".join(chunk[j:j + 10] for j in range(0, len(chunk), 10))
        lines.append(f"{i + 1:>9} {blocks}")
    lines.append("//")
    return "\n".join(lines) + "\n"


# ── main ────────────────────────────────────────────────────────────────────
def resolve_library(arg: Path) -> Path:
    root = arg.expanduser().resolve()
    for cand in (root / "ref_parts", root / "parts-library" / "ref_parts", root):
        if (cand / "LOCK.tsv").exists():
            return cand
    raise SystemExit(
        f"BLOCK: no ref_parts/LOCK.tsv under {root}.\n"
        f"       Create a library first:  python katana_init.py {arg}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Admit one part to a Katana Parts Library, with provenance and a seal.")
    ap.add_argument("--library", type=Path, required=True,
                    help="your library (the parts-library dir, or the project dir above it)")
    ap.add_argument("--id", help="the name you will refer to this part by. With --registry it "
                                 "defaults to the Registry name without its BBa_ prefix.")
    ap.add_argument("--accession", help="NCBI nucleotide accession, e.g. NC_000913.3")
    ap.add_argument("--range", dest="rng", help="sub-range within the accession, e.g. 363231..366305")
    ap.add_argument("--strand", choices=["+", "-"], default="+",
                    help="which strand of that range (default +)")
    ap.add_argument("--file", type=Path, help="a local .fasta or .gb to admit instead")
    ap.add_argument("--registry", metavar="BBa_XXXXX",
                    help="fetch a part from the iGEM Registry by name")
    ap.add_argument("--from", dest="from_lib", type=Path,
                    help="copy a part already sealed in another library "
                         "(give its LOCK.tsv, or the ref_parts dir holding it)")
    ap.add_argument("--class", dest="klass", choices=["reference", "designed", "synthesised"],
                    help="reference = fetched from a database; designed = you made it "
                         "(default: reference for --accession, designed for --file)")
    ap.add_argument("--source", help="provenance text (auto-filled for --accession)")
    ap.add_argument("--version", type=int, default=None,
                    help="version number (default: 1, or one past the highest already present)")
    ap.add_argument("--expect-organism",
                    help="refuse unless the fetched record names this organism - the one check "
                         "that catches a right-looking sequence under a wrong label")
    ap.add_argument("--expect-length", type=int,
                    help="refuse unless the sequence is exactly this long - a cheap guard "
                         "against a wrong accession or a wrong range")
    a = ap.parse_args()

    given = [bool(a.accession), bool(a.file), bool(a.from_lib), bool(a.registry)]
    if sum(given) != 1:
        return _block("give exactly one of --accession, --file, --from or --registry.")
    if not a.id:
        if a.registry:
            a.id = a.registry[4:] if a.registry.upper().startswith("BBA_") else a.registry
        else:
            return _block("--id is required (it is the name you will refer to this part by).")
    if not re.fullmatch(r"[A-Za-z0-9_.\-]+", a.id):
        return _block(f"--id {a.id!r} may only contain letters, digits, dot, dash, underscore.")

    lib = resolve_library(a.library)
    lock = lib / "LOCK.tsv"
    header, rows = read_lock(lock)
    # Defend against a manifest whose header lacks the row-hash column: every row written
    # against such a header is unreadable by the engine, and the failure surfaces as a
    # KeyError three stages later instead of here.
    if "row_sha256" not in header:
        header = header + ["row_sha256"]

    print()
    print(f"  library  {lib}  ({len(rows)} part(s) already sealed)")

    # ---- get the sequence
    if a.accession:
        seq, auto_source = fetch_ncbi(a.accession, a.rng, a.strand, a.expect_organism)
        klass = a.klass or "reference"
    elif a.registry:
        seq, auto_source, reg_role = fetch_registry(a.registry)
        klass = a.klass or "reference"
    elif a.from_lib:
        seq, auto_source, src_class = copy_from_library(a.from_lib, a.id)
        klass = a.klass or src_class
    else:
        seq = read_local(a.file)
        auto_source = f"local file {a.file.name}"
        klass = a.klass or "designed"
    source = a.source or auto_source

    # ---- check it before it gets anywhere near the manifest
    bad = sorted(set(seq.upper()) - VALID_DNA)
    if bad:
        return _block(f"sequence contains characters that are not DNA: {' '.join(bad)}")
    if a.expect_length and len(seq) != a.expect_length:
        return _block(f"length {len(seq)} != --expect-length {a.expect_length}. "
                      f"Nothing written. Check the accession and the range.")

    version = a.version
    same_id = [int(r["version"]) for r in rows if r["id"] == a.id and r["version"].isdigit()]
    if version is None:
        version = (max(same_id) + 1) if same_id else 1
    if version in same_id:
        return _block(f"{a.id} v{version} is already in this library. Parts are never edited "
                      f"in place - admit a new version instead (omit --version and it will "
                      f"use v{max(same_id) + 1}).")

    shex = seq_sha256(seq)
    outfile = f"{a.id}__v{version}__{shex[:12]}.gb"
    out_path = lib / outfile
    if out_path.exists():
        return _block(f"{outfile} already exists. Refusing to overwrite a sealed part file.")

    # ---- write, then read back and prove the file says what we think it says
    with open(out_path, "wb") as f:
        f.write(render_genbank(a.id, version, seq, source, klass).encode("utf-8"))

    reread = extract_gb_sequence(out_path.read_text(encoding="utf-8"))
    if seq_sha256(reread) != shex or len(reread) != len(seq):
        out_path.unlink(missing_ok=True)
        return _block("the file written does not read back as the sequence fetched. "
                      "Nothing was recorded and the file has been removed. This is a bug in "
                      "add_part.py - please report it.")

    row = {
        "id": a.id,
        "version": str(version),
        "seq_sha256": shex,
        "file_sha256": sha256_hex(out_path.read_bytes()),
        "length": str(len(seq)),
        "source": source,
        "date": date.today().isoformat(),
        "class": klass,
        "outfile": outfile,
    }
    row["row_sha256"] = row_sha256(row)
    rows.append(row)

    write_lock(lock, header, rows)
    new_root = lock_root(rows)
    with open(lib / "LOCK.root", "wb") as f:
        f.write((new_root + "\n").encode("utf-8"))

    print(f"  SEALED   {a.id} v{version}  {len(seq)} bp  {shex[:12]}")
    print(f"  wrote    {outfile}")
    print(f"  LOCK.root now {new_root[:12]}…  ({len(rows)} part(s))")
    print()
    print("  Paste this into the parts list in your Spec —")
    print()
    print(f"  - id: {a.id}")
    print(f"    role: SET_THIS          # promoter | rbs | cds | terminator | reporter")
    print(f"    class: {klass}")
    print(f"    source: {{ note: \"{source}\" }}")
    print(f"    seal:   {{ status: SEALED, lib: \"{outfile}\",")
    print(f"              seq_sha256_12: {shex[:12]}, length: {len(seq)} }}")
    print()
    print("  Then add its id to architecture.order, and build:")
    print()
    print(f"      python katana_build.py <your.spec.yaml> --library {a.library}")
    print()
    return 0


def _block(msg: str) -> int:
    print(f"\n  BLOCK: {msg}\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
