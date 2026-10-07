#!/usr/bin/env python3
"""
katana_build.py — Katana deterministic build engine (Stages 1–6).

Takes a Design Spec (.spec.yaml) and the sealed Parts Library, assembles a
construct insert deterministically, validates it, and emits an order-ready
GenBank + FASTA.  Same Spec + same sealed parts → byte-identical output.

Deterministic: the same Spec + the same sealed parts always produce a
byte-identical construct. Verify that with --oracle <expected sha256>.

KATANA_SPEC v2 gates enforced:
  Stage 1  — resolve pins, fail-closed on hash mismatch vs LOCK
  Stage 2  — verify-on-read (recompute seq_sha256 vs LOCK)
  Stage 3  — assemble deterministically, record consumed_inputs
  Stage 4  — validate: positive invariants first, junctions, RE, GC
  Stage 5  — seal: hash the result, write .gb + certificate
  Stage 6  — diff vs prior (if prior path provided)

Usage:
  py katana_build.py specs/pSense-Nit-dual.spec.yaml
  py katana_build.py specs/pSense-Nit-dual.spec.yaml --oracle f93cd751...
  py katana_build.py specs/pSense-Lac-dual.spec.yaml --gibson-overlap 30
"""
import argparse, hashlib, json, re, sys, textwrap, csv, io
from pathlib import Path
from datetime import datetime

# ── console encoding ────────────────────────────────────────────────────────
# This file prints box-drawing and status glyphs. On a default Windows console
# (cp1252) that raises UnicodeEncodeError on the very first banner line, before
# any work happens. Only one of the RUN_*.bat wrappers sets `chcp 65001`, so
# anyone invoking the script directly hits it. Fix it here rather than relying
# on the caller.
for _stream in (sys.stdout, sys.stderr):
    try:
        if (_stream.encoding or "").lower().replace("-", "") != "utf8":
            _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── locate the Parts Library ────────────────────────────────────────────────
HERE = Path(__file__).resolve().parent
# Walk UP from this file until parts-library is found, rather than assuming a fixed depth.
# parents[2] only resolved because katana/ happens to sit three levels down in this tree;
# it overshoots in any other layout (e.g. katana/ at the root of a published repo).
# (An absolute fallback used to sit here. It is redundant now the walk-up is
# depth-independent, and it hard-coded a username into a file meant to be published.)
# A team building their OWN constructs points the engine at their OWN library, with
#   --library <dir>   (or KATANA_LIBRARY in the environment)
# read here, before argparse runs, because LOCK_PATH below is resolved at import time.
# Without this the only library reachable is the one shipped in this bundle, so adopting
# Katana would mean editing OUR sealed library - which breaks its root and makes verify.py
# correctly report tampering. The shipped library stays sealed; yours is the one you fill.
def _library_override():
    import os
    argv = sys.argv[1:]
    for n, tok in enumerate(argv):
        if tok == "--library" and n + 1 < len(argv):
            return argv[n + 1]
        if tok.startswith("--library="):
            return tok.split("=", 1)[1]
    return os.environ.get("KATANA_LIBRARY")

_LIB_OVERRIDE = _library_override()
if _LIB_OVERRIDE:
    _r = Path(_LIB_OVERRIDE).expanduser().resolve()
    LIB = next((c for c in (_r / "ref_parts", _r / "parts-library" / "ref_parts", _r)
                if (c / "LOCK.tsv").exists()), None)
    if LIB is None:
        sys.exit(f"BLOCK: --library {_LIB_OVERRIDE} has no ref_parts/LOCK.tsv.\n"
                 f"       Create one with:  python3 katana_init.py {_LIB_OVERRIDE}")
else:
    CANDIDATES = [q / "parts-library" / "ref_parts" for q in (HERE, *HERE.parents)]
    LIB = next((p for p in CANDIDATES if p.is_dir()), None)
    if LIB is None:
        sys.exit("BLOCK: cannot find parts-library/ref_parts. Checked:\n  " +
                 "\n  ".join(str(c) for c in CANDIDATES))

sys.path.insert(0, str(HERE))
import vendor_path
vendor_path.ensure()
from core import hashing as _hashing
from core import result as _result
from core import lock as _lock
from core import parts as _parts

LOCK_PATH = LIB / "LOCK.tsv"
LOCK_ROOT_PATH = LIB / "LOCK.root"
# The expected LOCK root is a DEPLOYMENT pin, not a property of the engine.
# Supply it with --expect-root <sha256> to bind this build to one exact library state.
#
# Without a pin the engine STILL fails closed on library self-consistency: the row
# hashes are recomputed and must equal the LOCK.root file. The pin adds a second,
# external guard that catches a stale-but-internally-consistent copy of the library
# (e.g. an out-of-date sync of a shared drive). Pin your builds in CI.
DEFAULT_EXPECT_ROOT = None

# ── refusal: a stage stopping, as data rather than as an exit ────────────────
# The stage functions called sys.exit, which is right for a CLI and wrong for everything
# else: a GUI worker thread got SystemExit and a web page got nothing at all. _block()
# raises instead when a caller asked for a result, and still exits when the CLI is the
# caller -- so the terminal output is unchanged to the byte.
_REFUSE = False


class _Refused(Exception):
    """A stage refused to continue. Carries the stage name and the message."""

    def __init__(self, stage, message):
        Exception.__init__(self, message)
        self.stage = stage
        self.message = message


def _block(stage, message):
    """Refuse. Raises for build(), exits for main()."""
    if _REFUSE:
        raise _Refused(stage, message)
    sys.exit(message)


# ── helpers ─────────────────────────────────────────────────────────────────

def sha256_hex(data: bytes) -> str:
    return _hashing.sha256_hex(data)

def extract_gb_sequence(text: str) -> str:
    """Delegates to core.parts, which is the one reader. There were four."""
    return _parts.extract_sequence(text, ".gb")


def load_yaml_simple(path: Path) -> dict:
    """Minimal YAML-subset loader for spec files (avoids PyYAML dependency).
    Handles the flat + nested structure of Katana spec YAML.
    Falls back to PyYAML if available."""
    try:
        import yaml
    except ImportError:
        # Fall back to the vendored copy. An installed PyYAML wins (vendor_path appends,
        # never prepends), so a developer's venv stays authoritative; this is what makes a
        # machine with nothing installed work.
        try:
            sys.path.insert(0, str(HERE))
            import vendor_path
            vendor_path.ensure()
            import yaml
        except ImportError:
            sys.exit("BLOCK: no YAML parser available, and the vendored copy in _vendor/\n"
                     "       is missing. If you cloned this repository, the simplest repair\n"
                     "       is a fresh copy of it.")
    # A malformed Spec used to escape as a raw Python traceback ending in a scanner error,
    # while check_design.py — given the SAME file — printed a clear message. Two entry points
    # handling one failure two different ways is the defect; a traceback is not a verdict.
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as e:
        msg = [f"BLOCK: could not read {path} as YAML.",
               f"       {e}"]
        # PyYAML records where it gave up. Quote that line back: "line 12, column 30" is a
        # coordinate, but the line itself is the answer.
        mark = getattr(e, "problem_mark", None)
        if mark is not None:
            try:
                src = path.read_text(encoding="utf-8").splitlines()
                if 0 <= mark.line < len(src):
                    msg.append("")
                    msg.append(f"       line {mark.line + 1}:  {src[mark.line].rstrip()}")
                    msg.append("       " + " " * (len(f"line {mark.line + 1}:  ") + mark.column) + "^")
            except Exception:
                pass
        msg += ["",
                "       Usually this is an indentation slip, or a missing quote around a value",
                "       that contains a colon.",
                "       To see the whole Spec checked at once, run:",
                "           python3 check_design.py " + str(path)]
        sys.exit("\n".join(msg))

def load_lock(lock_path: Path) -> list:
    """The manifest as a list of rows.

    A list, not a dict keyed by (id, version): keying silently kept the LAST of two rows
    claiming the same identity, where core.lock.resolve refuses the ambiguity.
    """
    try:
        return _lock.read(lock_path)[1]
    except _lock.LockError as exc:
        sys.exit("BLOCK: %s" % exc)


def verify_lock_root(lock_path: Path, lock_root_path: Path, pinned: str | None = None):
    """Delegates to core.lock.verify_root, which RECOMPUTES every row hash from the
    row's own fields before checking the root.

    This function used to hash the row_sha256 COLUMN as written, so editing a recorded
    accession without touching its row hash passed the gate: a falsified provenance
    claim built to completion with exit 0 while verify_library_v2.py reported two
    problems. The sequence was protected by stage 2; the recorded ORIGIN of that
    sequence was not. CODE-REPORT finding A.
    """
    return _lock.verify_root(lock_path, lock_root_path, pinned)


# ── Stage 1+2: resolve + verify parts ──────────────────────────────────────

def resolve_parts(spec: dict, lock: dict) -> dict:
    """Resolve each part in spec.parts from LOCK, verify pins, load sequences.
    Returns {part_id: {seq, length, sha256, lib_path, ...}}"""
    resolved = {}
    parts_list = spec.get("parts", [])
    for part in parts_list:
        pid = part["id"]
        seal = part.get("seal", {})
        lib_file = seal.get("lib")
        expected_sha12 = seal.get("seq_sha256_12")
        expected_len = seal.get("length")

        if not lib_file or not expected_sha12:
            _block("source", f"BLOCK Stage-1: part '{pid}' has no seal/pin — bare id rejected (v2)\n"
                     f"       Your Spec names this part but does not say WHICH version of it,\n"
                     f"       so the engine cannot check it is the one you meant.\n"
                     f"       Every part needs a seal block. add_part.py prints the exact one\n"
                     f"       to paste when it admits a part. To see what you already have:\n"
                     f"           python3 find_part.py --have")

        # Resolve by the Spec's PIN, not by the highest version number.
        #
        # This loop used to scan for max(version) and then compare the pin against only
        # that row, so a Spec pinned to an OLDER sealed version -- row still in the
        # manifest, file still on disk -- was refused, with advice to update the Spec to
        # match the library. Following that advice changes the construct, and it
        # contradicts ARCHITECTURE.md's promise that history is append-only so a build
        # from last month can still be reproduced. HrpS.Ec-opt has v1, v2 and v3 sealed;
        # pAP-Logic v5 pinned v2. CODE-REPORT finding B.
        #
        # core.lock.resolve enforces the pin itself, so the separate check that used to
        # follow is gone: enforcing one rule in two places is how the engine's copy and
        # katana_lock's copy came to disagree in the first place.
        if not any(r.get("id") == pid for r in lock):
            _block("source", f"BLOCK Stage-1: part '{pid}' is not in your Parts Library yet.\n"
                     f"       Your Spec asks for it, but the library has never been given it.\n"
                     f"       Nothing is broken - you just need to add it first.\n"
                     f"       See what you have:      python3 find_part.py --have\n"
                     f"       Find it on NCBI:        python3 find_part.py {pid}\n"
                     f"       Copy one we ship:       python3 add_part.py --library <yours> "
                     f"--from parts-library/ref_parts --id {pid}")
        try:
            lock_row = _lock.resolve(lock, pid, pin=expected_sha12, lib=lib_file)
        except _lock.LockError as exc:
            _block("source", f"BLOCK Stage-1: {exc}\n"
                     f"       This is the check doing its job, not a bug.\n"
                     f"       Look at what the library actually holds:\n"
                     f"           python3 find_part.py {pid}\n"
                     f"       then correct whichever of the two is wrong.")
        lock_sha = lock_row["seq_sha256"]

        # Load the .gb file
        gb_path = LIB / lib_file
        if not gb_path.exists():
            # Try the outfile from LOCK
            gb_path = LIB / lock_row["outfile"]
        if not gb_path.exists():
            _block("source", f"BLOCK Stage-1: part '{pid}' file not found: {gb_path}\n"
                     f"       The manifest lists this part but its file is missing, so the\n"
                     f"       library is incomplete. If you cloned this repository, the\n"
                     f"       simplest repair is a fresh copy of it.")

        gb_text = gb_path.read_text(encoding="utf-8")
        raw_seq = extract_gb_sequence(gb_text)

        if not raw_seq:
            # Try FASTA format (protein parents are .faa)
            if gb_path.suffix == ".faa":
                lines = gb_text.strip().splitlines()
                raw_seq = "".join(l.strip() for l in lines if not l.startswith(">")).upper()

        # Stage 2: verify-on-read — recompute seq_sha256
        # Parts are always linear. The topology tag KATANA_SPEC v2 section 3.4
        # specifies is not part of the sealed convention -- see core.hashing.seq_sha256.
        computed = _hashing.seq_sha256(raw_seq)
        if computed != lock_sha:
            _block("source", f"BLOCK Stage-2: part '{pid}' recomputed hash {computed[:12]} ≠ LOCK {lock_sha[:12]}\n"
                     f"       The part file on disk does not match what the manifest sealed it\n"
                     f"       as. Something edited it after it was sealed.\n"
                     f"       This is exactly what the engine is for, so it has stopped.\n"
                     f"       If you edited it on purpose, undo that. If not, take a fresh\n"
                     f"       copy of the library and run:  python3 verify.py")

        # Length check
        if expected_len and len(raw_seq) != int(expected_len):
            _block("source", f"BLOCK Stage-2: part '{pid}' length {len(raw_seq)} ≠ expected {expected_len}\n"
                     f"       Your Spec says this part is {expected_len} bases; the library\n"
                     f"       holds {len(raw_seq)}. A part that changed length is a different\n"
                     f"       part. Check the length in the Spec's seal block against:\n"
                     f"           python3 find_part.py {pid}")

        resolved[pid] = {
            "seq": raw_seq,
            "length": len(raw_seq),
            "seq_sha256": computed,
            "lib_path": str(gb_path.relative_to(LIB)),
            "lock_row": lock_row,
        }
        print(f"  Stage-1/2 PASS: {pid} ({len(raw_seq)} bp, {computed[:12]})")

    return resolved

# ── Stage 3: assemble ──────────────────────────────────────────────────────

def apply_trims(seq: str, trims_for_part: dict) -> str:
    """Apply 5' and/or 3' trims to a part sequence."""
    if not trims_for_part:
        return seq
    trim_3p = trims_for_part.get("3prime", "").upper()
    trim_5p = trims_for_part.get("5prime", "").upper()
    if trim_3p:
        if seq.upper().endswith(trim_3p):
            seq = seq[:-len(trim_3p)]
        else:
            _block("assemble", f"BLOCK Stage-3: 3' trim '{trim_3p}' not found at end of sequence")
    if trim_5p:
        if seq.upper().startswith(trim_5p):
            seq = seq[len(trim_5p):]
        else:
            _block("assemble", f"BLOCK Stage-3: 5' trim '{trim_5p}' not found at start of sequence")
    return seq

def assemble_insert(spec: dict, resolved: dict) -> tuple:
    """Assemble the insert cassette from resolved parts per architecture.order.
    Returns (insert_seq, features_list, consumed_inputs)."""
    arch = spec.get("architecture", {})
    order = arch.get("order", [])
    trims = arch.get("trims", {})
    topology = arch.get("topology", "linear-insert")

    if not order:
        _block("assemble", "BLOCK Stage-3: architecture.order is empty.\n"
                 "       You have listed parts, but not the ORDER they go in. The engine\n"
                 "       will not guess an arrangement of DNA for you.\n"
                 "       Add the ids, left to right, e.g.\n"
                 "           architecture:\n"
                 "             order: [my_promoter, my_rbs, my_gene, my_terminator]\n"
                 "       Then check it reads sensibly:  python3 check_design.py <your.spec.yaml>")

    insert_parts = []
    features = []
    pos = 0
    consumed = {}

    for pid in order:
        if pid not in resolved:
            _block("assemble", f"BLOCK Stage-3: '{pid}' appears in architecture.order but is not in your\n"
                     f"       Spec's parts list. Usually this is a typo in one of the two, or a\n"
                     f"       part you meant to add and did not.\n"
                     f"       This and other Spec problems are all reported at once by:\n"
                     f"           python3 check_design.py <your.spec.yaml>")

        part_data = resolved[pid]
        seq = part_data["seq"]
        consumed[pid] = part_data["seq_sha256"]

        # Apply trims if specified
        part_trims = trims.get(pid, {})
        seq_trimmed = apply_trims(seq, part_trims)

        # Record feature
        start = pos + 1  # 1-based GenBank coordinates
        end = pos + len(seq_trimmed)

        # Look up role from spec.parts
        role = "misc_feature"
        label = pid
        note = ""
        for p in spec.get("parts", []):
            if p["id"] == pid:
                role = p.get("role", "misc_feature")
                label = pid
                seal = p.get("seal", {})
                lib = seal.get("lib", "")
                note_parts = [f"{pid} {lib}"]
                src = p.get("source", {})
                if src:
                    if "registry" in src:
                        note_parts.append(f"iGEM {src.get('part', '')}")
                    elif "db" in src:
                        note_parts.append(f"{src['db']} {src.get('accession', '')}:{src.get('coords', '')}({src.get('strand', '')})")
                note = "; ".join(note_parts)
                break

        # Map role to GenBank feature key
        feature_key_map = {
            "promoter": "promoter",
            "rbs": "RBS",
            "cds": "CDS",
            "reporter": "CDS",
            "terminator": "terminator",
            "ori": "rep_origin",
            "marker": "CDS",
        }
        feat_key = feature_key_map.get(role, "misc_feature")

        trim_note = ""
        if part_trims:
            t3 = part_trims.get("3prime", "")
            t5 = part_trims.get("5prime", "")
            if t3:
                trim_note = f"; trimmed 3' {len(t3)} nt ({t3})"
            if t5:
                trim_note = f"; trimmed 5' {len(t5)} nt ({t5})"

        features.append({
            "key": feat_key,
            "start": start,
            "end": end,
            "label": label,
            "note": note + trim_note,
            "role": role,
            "trimmed_len": len(seq_trimmed),
            "original_len": len(part_data["seq"]),
        })

        insert_parts.append(seq_trimmed.lower())
        pos = end

    insert_seq = "".join(insert_parts)
    return insert_seq, features, consumed

# ── Stage 4: validate ──────────────────────────────────────────────────────

RE_SITES = {
    "EcoRI": "GAATTC",
    "XbaI": "TCTAGA",
    "SpeI": "ACTAGT",
    "PstI": "CTGCAG",
    "NdeI": "CATATG",
    "BsaI": "GGTCTC",
    "BbsI": "GAAGAC",
}

def find_re_sites(seq: str, sites: list) -> list:
    """Find all RE site positions in sequence."""
    findings = []
    seq_upper = seq.upper()
    for name in sites:
        motif = RE_SITES.get(name)
        if not motif:
            continue
        # Check both strands
        rc_motif = motif[::-1].translate(str.maketrans("ACGT", "TGCA"))
        for m in re.finditer(motif, seq_upper):
            findings.append((name, m.start(), "fwd"))
        for m in re.finditer(rc_motif, seq_upper):
            findings.append((name, m.start(), "rev"))
    return findings

def validate_insert(insert_seq: str, features: list, spec: dict, resolved: dict) -> list:
    """Stage 4: validate the assembled insert. Returns list of issues (empty = PASS)."""
    issues = []
    seq_upper = insert_seq.upper()
    constraints = spec.get("constraints", {})

    # Positive invariant 1: non-empty
    if not insert_seq:
        issues.append("BLOCK: assembled insert is empty")
        return issues

    # Positive invariant 2: length within expected bounds
    arch = spec.get("architecture", {})
    trims = arch.get("trims", {})
    expected_len = 0
    for pid in arch.get("order", []):
        if pid in resolved:
            part_trims = trims.get(pid, {})
            plen = resolved[pid]["length"]
            t3 = part_trims.get("3prime", "")
            t5 = part_trims.get("5prime", "")
            plen -= len(t3) + len(t5)
            expected_len += plen
    if len(insert_seq) != expected_len:
        issues.append(f"BLOCK: insert length {len(insert_seq)} ≠ expected {expected_len} (Σ trimmed parts)")

    # Positive invariant 3: every part's (trimmed) subsequence locatable
    order = arch.get("order", [])
    for pid in set(order):
        if pid not in resolved:
            continue
        part_seq = resolved[pid]["seq"]
        part_trims = trims.get(pid, {})
        trimmed = apply_trims(part_seq, part_trims).upper()
        if trimmed not in seq_upper:
            issues.append(f"BLOCK: part '{pid}' trimmed sequence not found in insert")

    # Junction checks: RBS→ATG spacing
    for feat in features:
        if feat["role"] == "rbs":
            rbs_end = feat["end"]
            # Find next feature (should be CDS/reporter)
            for f2 in features:
                if f2["start"] == rbs_end + 1 and f2["role"] in ("cds", "reporter"):
                    # Check ATG at start of CDS
                    cds_start_idx = f2["start"] - 1  # 0-based
                    codon = seq_upper[cds_start_idx:cds_start_idx+3]
                    if codon != "ATG":
                        issues.append(f"WARN: {f2['label']} CDS does not start with ATG (found {codon} at pos {f2['start']})")
                    break

    # Forbidden RE sites (check but note internal vs junction-crossing)
    forbid = constraints.get("forbid_sites", [])
    if forbid:
        re_hits = find_re_sites(insert_seq, forbid)
        # Classify: junction-crossing sites are BLOCKs, internal are informational
        junction_positions = set()
        for feat in features:
            junction_positions.add(feat["start"] - 1)  # 0-based start of each part
            junction_positions.add(feat["end"])  # 0-based position after part
        for name, pos, strand in re_hits:
            motif_len = len(RE_SITES[name])
            crosses_junction = any(pos < jp < pos + motif_len for jp in junction_positions)
            if crosses_junction:
                issues.append(f"BLOCK: forbidden RE {name} ({strand}) at pos {pos+1} CROSSES a junction")
            # Internal sites are informational, not blocking for synthesis

    # GC content
    gc = (seq_upper.count("G") + seq_upper.count("C")) / len(seq_upper)
    if gc < 0.25 or gc > 0.65:
        issues.append(f"WARN: GC content {gc:.1%} outside 25-65% range")

    # Max homopolymer
    max_hp = 0
    for base in "ACGT":
        for m in re.finditer(base + "+", seq_upper):
            max_hp = max(max_hp, m.end() - m.start())
    if max_hp > 10:
        issues.append(f"WARN: max homopolymer run {max_hp} bp (>10)")

    # Size vs fragment cap
    frag_cap = constraints.get("fragment_bp_max", 5000)
    if len(insert_seq) > frag_cap:
        issues.append(f"INFO: insert {len(insert_seq)} bp > fragment cap {frag_cap} → requires multi-fragment split")

    return issues

# ── Stage 5: seal ──────────────────────────────────────────────────────────

def write_genbank(insert_seq: str, features: list, spec: dict, seal_hash: str,
                  output_path: Path):
    """Write a GenBank file for the insert."""
    sid = spec["id"]
    version = spec.get("version", 1)
    date_str = datetime.now().strftime("%d-%b-%Y").upper()
    length = len(insert_seq)

    lines = []
    lines.append(f"LOCUS       {sid}_insert {length} bp    DNA     linear   SYN {date_str}")
    lines.append(f"DEFINITION  Katana insert cassette (INSERT scope) for {sid} v{version} - SEALED build.")
    lines.append(f"COMMENT     Regenerated deterministically from sealed Parts Library (Katana Stage 3).")
    lines.append(f"COMMENT     Same Spec + sealed parts => byte-identical.")

    # Add backbone reference
    bb = spec.get("backbone", {})
    if bb:
        lines.append(f"COMMENT     Backbone = Twist vendor vector ({bb.get('vector','')}, {bb.get('ori','')}/{bb.get('marker','')}) -")
        lines.append(f"COMMENT     referenced, NOT sealed, out of insert seal scope.")

    # Assembly method
    asm = spec.get("assembly", {})
    method = asm.get("method") or "single-fragment de-novo synthesis"
    lines.append(f"COMMENT     Assembly = {method} ({length} bp).")

    lines.append(f"COMMENT     seq_sha256={seal_hash}")

    lines.append("FEATURES             Location/Qualifiers")

    for feat in features:
        loc = f"{feat['start']}..{feat['end']}"
        lines.append(f"     {feat['key']:<16}{loc}")
        lines.append(f'                     /label="{feat["label"]}"')
        if feat.get("note"):
            lines.append(f'                     /note="{feat["note"]}"')

    lines.append("ORIGIN")

    # Format sequence in GenBank style: 10-char groups, 6 groups per line
    for i in range(0, length, 60):
        chunk = insert_seq[i:i+60]
        groups = [chunk[j:j+10] for j in range(0, len(chunk), 10)]
        line_num = i + 1
        lines.append(f"{line_num:>9} {' '.join(groups)}")

    lines.append("//")
    lines.append("")  # trailing newline

    output_path.write_text("\n".join(lines), encoding="utf-8", newline="\n")

def write_fasta(insert_seq: str, spec: dict, seal_hash: str, output_path: Path):
    """Write order-ready FASTA for the insert."""
    sid = spec["id"]
    version = spec.get("version", 1)
    header = f">{sid}_insert_v{version} {len(insert_seq)}bp seq_sha256={seal_hash[:16]}"
    wrapped = "\n".join(insert_seq[i:i+80] for i in range(0, len(insert_seq), 80))
    output_path.write_text(f"{header}\n{wrapped}\n", encoding="utf-8", newline="\n")

def gibson_split(insert_seq: str, features: list, spec: dict, overlap: int = 30) -> list:
    """Split an insert into Gibson fragments with overlaps.
    Uses gibson_split_after_index from spec to determine split point.
    Returns list of (frag_name, frag_seq, start, end) tuples."""
    arch = spec.get("architecture", {})
    split_idx = arch.get("gibson_split_after_index")

    if split_idx is not None and split_idx < len(features):
        best_split = features[split_idx]["end"]
    else:
        # Fallback: split at the feature boundary nearest the middle
        mid = len(insert_seq) // 2
        boundaries = sorted(set(f["end"] for f in features))
        best_split = min(boundaries, key=lambda b: abs(b - mid)) if boundaries else mid

    frag_a_seq = insert_seq[:best_split + overlap]
    frag_b_seq = insert_seq[best_split - overlap:]

    sid = spec["id"]
    return [
        (f"{sid}_FRAG-A", frag_a_seq, 1, best_split + overlap),
        (f"{sid}_FRAG-B", frag_b_seq, best_split - overlap + 1, len(insert_seq)),
    ]

# ── Stage 6: diff ──────────────────────────────────────────────────────────

def diff_vs_prior(insert_seq: str, prior_path: Path) -> list:
    """Compare current insert against a prior .gb file. Returns delta list."""
    if not prior_path or not prior_path.exists():
        return [f"INFO: no prior file at {prior_path} — skip diff"]

    prior_text = prior_path.read_text(encoding="utf-8")
    prior_seq = extract_gb_sequence(prior_text)

    if insert_seq.upper() == prior_seq.upper():
        return ["MATCH: insert sequence identical to prior"]

    deltas = []
    deltas.append(f"MISMATCH: current {len(insert_seq)} bp vs prior {len(prior_seq)} bp (Δ {len(insert_seq)-len(prior_seq):+d})")

    # Find specific differences
    min_len = min(len(insert_seq), len(prior_seq))
    mismatches = 0
    first_diff = None
    for i in range(min_len):
        if insert_seq[i].upper() != prior_seq[i].upper():
            mismatches += 1
            if first_diff is None:
                first_diff = i + 1
    if len(insert_seq) != len(prior_seq):
        mismatches += abs(len(insert_seq) - len(prior_seq))
    deltas.append(f"  {mismatches} differing positions; first at pos {first_diff or 'N/A'}")

    return deltas

# ── main ────────────────────────────────────────────────────────────────────

def _parse_args(argv=None):
    """The CLI's own argument parsing. Separate from the pipeline, so build() can be
    called with keyword arguments instead of a fabricated namespace."""
    parser = argparse.ArgumentParser(description="Katana deterministic build engine (Stages 1-6)")
    parser.add_argument("spec", type=Path, help="Path to .spec.yaml file")
    parser.add_argument("--oracle", type=str, default=None,
                        help="Expected seq_sha256 for oracle validation")
    parser.add_argument("--gibson-overlap", type=int, default=30,
                        help="Gibson overlap length (default 30)")
    parser.add_argument("--prior", type=Path, default=None,
                        help="Prior .gb file for Stage-6 diff")
    parser.add_argument("--outdir", type=Path, default=None,
                        help="Output directory (default: katana/outputs/)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run stages 1-4 only, no file output")
    parser.add_argument("--library", type=Path, default=None,
                        help="build against your own Parts Library (see katana_init.py). Read before argparse; declared here so it is documented and accepted.")
    parser.add_argument("--expect-root", type=str, default=None,
                        help="Expected Parts Library LOCK root (sha256). Binds this build to "
                             "one exact library state; omit to enforce self-consistency only.")
    parser.add_argument("--sbol", type=Path, default=None,
                        help="Also write the build as SBOL 3 to this path (needs `pip install "
                             "sbol3`). Skipped under --dry-run, like every other output.")
    parser.add_argument("--sbol-format", type=str, default="turtle",
                        choices=["turtle", "nt", "jsonld", "rdfxml"],
                        help="SBOL serialisation (default: turtle)")
    parser.add_argument("--json", action="store_true",
                        help="emit the whole result as JSON instead of text. Everything "
                             "the text output says, in a form a wrapper can read "
                             "without parsing sentences.")
    args = parser.parse_args(argv)
    return args


def _run_pipeline(args, res):
    """The pipeline. Prints as it goes, and records what happened into `res`.

    ONE implementation. main() renders the printing; build() captures it and reads the
    result. The printed lines are unchanged to the byte, because this IS the code that
    always printed them -- test_determinism greps seq_sha256:, kg_rebuild greps .gb:,
    and anyone reading a log reads all of it.
    """


    if not args.spec.exists():
        sys.exit(f"BLOCK: spec file not found: {args.spec}\n"
                 f"       Check the spelling and that you are in the right folder.\n"
                 f"       To see the Design Specs next to you:   ls specs")

    print(f"═══ Katana Build Engine ═══")
    print(f"Spec: {args.spec}")
    print(f"Library: {LIB}")
    print()

    # ── Load spec ───────────────────────────────────────────────────────────
    spec = load_yaml_simple(args.spec)
    sid = spec["id"]
    version = spec.get("version", 1)
    print(f"Construct: {sid} v{version}")
    print(f"Track: {spec.get('track', '?')}")
    print()

    # ── Verify LOCK.root ────────────────────────────────────────────────────
    print("── LOCK.root verification ──")
    expect_root = args.expect_root or DEFAULT_EXPECT_ROOT
    ok, msg = verify_lock_root(LOCK_PATH, LOCK_ROOT_PATH, expect_root)
    if not ok:
        sys.exit(f"BLOCK: {msg}")
    print(f"  LOCK.root {msg}")
    try:
        res.library_root = LOCK_ROOT_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        res.library_root = ""
    res.pinned = bool(expect_root)
    res.add(_result.StageResult("library", True, data={"message": msg}))
    if not expect_root:
        print("  NOTE: no --expect-root given. Library integrity is enforced, but this build")
        print("        is not bound to a specific library state. Pin it for reproducible CI.")
    print()

    # ── Stage 1+2: resolve and verify parts ─────────────────────────────────
    print("── Stage 1+2: Source + Verify ──")
    lock = load_lock(LOCK_PATH)
    resolved = resolve_parts(spec, lock)
    print(f"  All {len(resolved)} distinct parts resolved and verified.")
    res.add(_result.StageResult("source", True,
                                data={"parts": sorted(resolved)}))
    print()

    # ── Stage 3: assemble ───────────────────────────────────────────────────
    print("── Stage 3: Assemble ──")
    insert_seq, features, consumed = assemble_insert(spec, resolved)
    insert_hash = _hashing.seq_sha256(insert_seq)
    print(f"  Insert assembled: {len(insert_seq)} bp")
    print(f"  seq_sha256: {insert_hash}")
    print(f"  Parts in order: {' → '.join(spec['architecture']['order'])}")
    res.construct_id = sid
    res.version = version
    res.insert_len = len(insert_seq)
    res.seq_sha256 = insert_hash
    res.features = list(features)
    res.consumed = dict(consumed)
    res.add(_result.StageResult("assemble", True,
                                data={"order": list(spec["architecture"]["order"])}))
    for feat in features:
        trim_info = ""
        if feat["trimmed_len"] != feat["original_len"]:
            trim_info = f" (trimmed {feat['original_len']}→{feat['trimmed_len']})"
        print(f"    {feat['start']:>5}..{feat['end']:<5} {feat['key']:<12} {feat['label']}{trim_info}")
    print()

    # ── Oracle check ────────────────────────────────────────────────────────
    if args.oracle:
        print("── Oracle validation ──")
        if insert_hash == args.oracle:
            print(f"  ✓ ORACLE MATCH: {insert_hash[:16]}…")
            res.add(_result.StageResult("oracle", True,
                                        data={"expected": args.oracle}))
        else:
            print(f"  ✗ ORACLE MISMATCH!")
            print(f"    Expected: {args.oracle[:32]}…")
            print(f"    Got:      {insert_hash[:32]}…")
            sys.exit(1)
        print()

    # ── Stage 4: validate ───────────────────────────────────────────────────
    print("── Stage 4: Validate ──")
    issues = validate_insert(insert_seq, features, spec, resolved)
    blocks = [i for i in issues if i.startswith("BLOCK")]
    warns = [i for i in issues if i.startswith("WARN")]
    infos = [i for i in issues if i.startswith("INFO")]
    for iss in issues:
        print(f"  {iss}")
    if blocks:
        _block("validate", f"BLOCK Stage-4: {len(blocks)} blocking issue(s)")
    _vf = []
    for _iss in issues:
        _st = (_result.FLAG if _iss.startswith("WARN")
               else _result.NOTE if _iss.startswith("INFO")
               else _result.FAIL)
        _vf.append(_result.Finding("validate", _st, _iss))
    res.add(_result.StageResult("validate", True, _vf))
    if not issues:
        print("  PASS — all checks clean")
    else:
        print(f"  PASS — {len(warns)} warnings, {len(infos)} info")
    print()

    # ── Stage 4b: dry-lab auto-gate (off-target blastn + codon quality) ──────
    try:
        sys.path.insert(0, str(HERE))
        from katana_drylab import run_drylab_gate
        _db, _dw, _di = run_drylab_gate(insert_seq, features, spec, resolved, HERE)
        for _m in _di + _dw + _db:
            print(f"  {_m}")
        if _db:
            _block("drylab", f"BLOCK Stage-4b: {len(_db)} dry-lab blocking issue(s)")
        _df = []
        for _m in _db:
            _df.append(_result.Finding("drylab", _result.FAIL, _m))
        for _m in _dw:
            # "NOT enforced this run" is a gate that did not RUN, which is SKIP rather
            # than FLAG: the whole reason SKIP is a separate tier is that "we did not
            # check" must never read as "checked and fine".
            if "NOT enforced" in _m:
                _cat = "offtarget" if "OFF-TARGET" in _m else "cai"
                _df.append(_result.Finding(_cat, _result.SKIP, _m))
            else:
                _df.append(_result.Finding("drylab", _result.FLAG, _m))
        for _m in _di:
            _df.append(_result.Finding("drylab", _result.NOTE, _m))
        res.add(_result.StageResult("drylab", True, _df))
        print("  Stage-4b PASS" + (f" — {len(_dw)} warning(s) to review" if _dw else " — clean"))
        _skipped = [w for w in _dw if "OFF-TARGET SKIPPED" in w]
        _hits = [w for w in _dw if "off-target" in w and w not in _skipped]
        if _hits:
            print("           Warnings are normal here and do not mean you did anything")
            print("           wrong. A match only BLOCKs at >=100 bp AND >=95% identity,")
            print("           because a match that long and that exact is never chance.")
            print("           Everything shorter is surfaced so a human can glance at it.")
        if _skipped:
            print("           The off-target check did not run: the genome it needs for")
            print("           this construct is not here. The line above says which.")
            print("           To fetch it:  python3 get_genome.py")
    except SystemExit:
        raise
    except Exception as _e:
        print(f"  WARN Stage-4b: dry-lab gate unavailable ({_e!r}) — NOT enforced this run")
    print()

    if args.dry_run:
        print("── Dry run — no output files ──")
        return

    # ── Stage 5: seal (write output) ────────────────────────────────────────
    print("── Stage 5: Seal ──")
    outdir = args.outdir or (HERE / "outputs")
    outdir.mkdir(parents=True, exist_ok=True)

    date_tag = datetime.now().strftime("%Y-%m-%d")
    gb_name = f"{sid}_insert_v{version}_{date_tag}.gb"
    fasta_name = f"{sid}_insert_v{version}_TWIST.fasta"

    gb_path = outdir / gb_name
    fasta_path = outdir / fasta_name

    write_genbank(insert_seq, features, spec, insert_hash, gb_path)
    write_fasta(insert_seq, spec, insert_hash, fasta_path)
    print(f"  .gb:    {gb_path}")
    print(f"  .fasta: {fasta_path}")

    # Verify the written .gb reproduces the hash
    written_seq = extract_gb_sequence(gb_path.read_text(encoding="utf-8"))
    written_hash = _hashing.seq_sha256(written_seq)
    if written_hash != insert_hash:
        _block("seal", f"BLOCK Stage-5: written .gb hash {written_hash[:12]} ≠ assembled {insert_hash[:12]}")
    print(f"  .gb round-trip hash verified ✓")
    print(f"  SEALED: {insert_hash}")
    res.outputs["gb"] = str(gb_path)
    res.outputs["fasta"] = str(fasta_path)
    res.add(_result.StageResult("seal", True, data={"sha256": insert_hash}))

    # ── SBOL 3 export (optional, standards interchange) ─────────────────────
    sbol_target = args.sbol
    if sbol_target is None:
        try:
            import sbol3  # noqa: F401
            sbol_target = outdir / f"{sid}_insert_v{version}.ttl"
        except ImportError:
            print("  INFO: sbol3 not installed, so no .ttl written (pip install sbol3).")
    if sbol_target:
        try:
            sys.path.insert(0, str(HERE))
            from katana_sbol import export_sbol
            _ok, _msgs = export_sbol(spec, resolved, insert_seq, features,
                                     sbol_target, fmt=args.sbol_format)
            for _m in _msgs:
                print(f"  {_m}")
            if _ok:
                res.outputs["sbol"] = str(sbol_target)
            if not _ok:
                _block("seal", "BLOCK Stage-5: SBOL export requested but not produced (see above)")
        except SystemExit:
            raise
        except Exception as _e:
            _block("seal", f"BLOCK Stage-5: SBOL export failed ({_e!r})")

    # Gibson split if needed
    frag_cap = spec.get("constraints", {}).get("fragment_bp_max", 5000)

    # One row per orderable piece, for the vendor order table written below.
    order_records = [{"name": f"{sid}_insert_v{version}", "role": "insert",
                      "length_bp": len(insert_seq), "sequence": insert_seq.upper(),
                      "seq_sha256": insert_hash,
                      "note": "complete insert" if len(insert_seq) <= frag_cap
                              else "complete insert (ordered as the fragments below)"}]

    if len(insert_seq) > frag_cap:
        print(f"\n── Gibson fragment split (insert {len(insert_seq)} > {frag_cap} cap) ──")
        frags = gibson_split(insert_seq, features, spec, args.gibson_overlap)
        for fname, fseq, fstart, fend in frags:
            fpath = outdir / f"{fname}_TWIST.fasta"
            header = f">{fname} {len(fseq)}bp pos {fstart}-{fend} overlap={args.gibson_overlap}"
            wrapped = "\n".join(fseq[i:i+80] for i in range(0, len(fseq), 80))
            fpath.write_text(f"{header}\n{wrapped}\n", encoding="utf-8", newline="\n")
            print(f"  {fname}: {len(fseq)} bp → {fpath}")

            order_records.append({
                "name": fname, "role": "fragment", "length_bp": len(fseq),
                "sequence": fseq.upper(), "seq_sha256": _hashing.seq_sha256(fseq),
                "note": f"pos {fstart}-{fend}, {args.gibson_overlap} bp overlap"})

    # ── Vendor order table (CSV) ─────────────────────────────────
    # Same sealed bases, a fourth shape. Vendors differ: some take FASTA, some want a
    # spreadsheet upload. Emitting all of them means nobody retypes a sequence into a web
    # form, which is precisely where a sequence and its label come apart.
    try:
        sys.path.insert(0, str(HERE))
        from katana_order_table import write_order_csv
        csv_path = outdir / f"{sid}_insert_v{version}_ORDER.csv"
        for _m in write_order_csv(order_records, spec, csv_path):
            print(f"  {_m}")
        print(f"  .csv:   {csv_path}  ({len(order_records)} row(s))")
        res.outputs["csv"] = str(csv_path)
    except Exception as _e:
        _block("seal", f"BLOCK Stage-5: order table not written ({_e!r})")

    print()

    # ── Stage 6: diff ───────────────────────────────────────────────────────
    if args.prior:
        print("── Stage 6: Diff vs prior ──")
        deltas = diff_vs_prior(insert_seq, args.prior)
        for d in deltas:
            print(f"  {d}")
        print()

    # ── Summary ─────────────────────────────────────────────────────────────
    print("═══ BUILD COMPLETE ═══")
    print(f"  Construct: {sid} v{version}")
    print(f"  Insert:    {len(insert_seq)} bp")
    print(f"  Hash:      {insert_hash}")
    print(f"  Verdict:   SEALED")
    print(f"  Output:    {gb_path}")


def build(spec_path, library=None, **opts):
    """Run the pipeline and RETURN what happened. Never exits, never prints.

    opts: oracle, expect_root, prior, outdir, dry_run, gibson_overlap, sbol,
    sbol_format, and `capture` (default True) to suppress the text.

    This is what a GUI worker thread, a web page and `--json` all call. The CLI calls
    the same pipeline through main(); there is no second implementation.
    """
    global _REFUSE
    import argparse as _ap
    import io as _io

    res = _result.BuildResult()
    res.dry_run = bool(opts.get("dry_run"))
    res.library = str(library or LIB)

    args = _ap.Namespace(
        spec=Path(spec_path), library=library,
        oracle=opts.get("oracle"), expect_root=opts.get("expect_root"),
        prior=(Path(opts["prior"]) if opts.get("prior") else None),
        outdir=(Path(opts["outdir"]) if opts.get("outdir") else None),
        sbol=(Path(opts["sbol"]) if opts.get("sbol") else None),
        dry_run=bool(opts.get("dry_run")),
        gibson_overlap=opts.get("gibson_overlap", 30),
        sbol_format=opts.get("sbol_format", "turtle"),
        json=False)

    buf = _io.StringIO()
    old_stdout, old_refuse = sys.stdout, _REFUSE
    if opts.get("capture", True):
        sys.stdout = buf
    _REFUSE = True
    try:
        _run_pipeline(args, res)
    except _Refused as refusal:
        res.add(_result.StageResult(
            refusal.stage, False,
            [_result.Finding("block", _result.FAIL,
                             refusal.message.splitlines()[0],
                             detail="\n".join(refusal.message.splitlines()[1:]))]))
    except SystemExit as exc:
        # A path that still exits -- the spec-not-found check and the YAML reader run
        # before any stage exists. Record it rather than letting it escape a GUI thread.
        res.add(_result.StageResult(
            "spec", False,
            [_result.Finding("block", _result.FAIL,
                             str(exc).splitlines()[0] if str(exc) else "the engine stopped",
                             detail="\n".join(str(exc).splitlines()[1:]))]))
    finally:
        sys.stdout, _REFUSE = old_stdout, old_refuse
    res.log = buf.getvalue()
    return res


def main(argv=None):
    args = _parse_args(argv)
    res = _result.BuildResult()
    res.dry_run = bool(args.dry_run)
    if getattr(args, "json", False):
        import io as _io
        buf, old = _io.StringIO(), sys.stdout
        sys.stdout = buf
        global _REFUSE
        _REFUSE = True
        try:
            _run_pipeline(args, res)
        except _Refused as refusal:
            res.add(_result.StageResult(
                refusal.stage, False,
                [_result.Finding("block", _result.FAIL,
                                 refusal.message.splitlines()[0],
                                 detail="\n".join(refusal.message.splitlines()[1:]))]))
        except SystemExit as exc:
            res.add(_result.StageResult(
                "spec", False,
                [_result.Finding("block", _result.FAIL,
                                 str(exc).splitlines()[0] if str(exc) else "stopped")]))
        finally:
            sys.stdout, _REFUSE = old, False
        res.log = buf.getvalue()
        json.dump(res.to_dict(), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return res.exit_code
    _run_pipeline(args, res)
    return res.exit_code


if __name__ == "__main__":
    main()
