"""
build_refs.py — (re)generate Kagami's public reference set into refs/.

This is how the reference set expands the RIGHT way: it PROJECTS the verified,
sealed PUBLIC reference parts out of the Synbio parts-library into a self-contained
data file that ships with Kagami — plus a few hand-seeded canonical public parts
not yet in the library.

TRUST NOTHING ON READ (added 2026-09-14). For every library part it pulls, it
RECOMPUTES seq_sha256 = sha256(UPPER, letters-only) — the exact convention of
parts-library/_tools/katana_lock.py — and requires it to equal BOTH (a) the
part's seq_sha256 in LOCK.tsv and (b) the sha12 in the sealed filename. It also
recomputes LOCK.root (Merkle root over row hashes) and checks it against the last
attested root in LOCK.root.log. Any mismatch is fail-closed: the offending part is
NOT written and the build exits non-zero. A Kagami reference is therefore never a
sequence read on faith — it is one that reproduced its seal at build time.

It pulls public reference parts, plus the few `designed` parts listed in PUBLISHED_DESIGNED
that already ship in the published iGEM bundle. It never pulls a non-public part (IP boundary), and never
reads a sequence out of a construct (circular provenance). Only the allowlist below
— public, generically useful iGEM parts — is included.

Usage:
  python3 build_refs.py --library path/to/your/parts-library
  (defaults to a sibling ../../../../parts-library if run inside the project tree)
  --no-lock-root  : skip the LOCK.root integrity check (per-part hash gate still runs)

Exit codes: 0 = all pulled parts verified; 1 = ≥1 part failed its hash gate;
            2 = LOCK.root mismatch / LOCK unreadable (library integrity).
"""
import argparse
import glob
import hashlib
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kg_parse  # noqa: E402


# ---- hashing, byte-for-byte per parts-library/_tools/katana_lock.py ----
LOCK_FIELDS = ["id", "version", "seq_sha256", "file_sha256", "length",
               "source", "date", "class", "outfile"]


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def seq_sha256_of(seq):
    return _sha("".join(c for c in seq if c.isalpha()).upper().encode())


def _row_sha(row):
    return _sha("\n".join(f"{k}={row.get(k,'')}" for k in LOCK_FIELDS).encode())


def _lock_root(rows):
    return _sha("\n".join(_row_sha(r) for r in rows).encode())


def read_lock(path):
    with open(path, "r", encoding="utf-8") as f:
        lines = [ln.rstrip("\n") for ln in f if ln.strip() != ""]
    header = lines[0].split("\t")
    return [dict(zip(header, ln.split("\t"))) for ln in lines[1:]]


def last_attested_root(logpath):
    if not os.path.exists(logpath):
        return None
    last = None
    with open(logpath, "r", encoding="utf-8") as f:
        for ln in f:
            parts = ln.split("\t")
            if len(parts) >= 2 and len(parts[1]) == 64:
                last = parts[1]
    return last


def _filename_sha12(outfile):
    return os.path.basename(outfile).rsplit(".", 1)[0].split("__")[-1]


# Designed parts are team-authored, so they are NOT public by default. These specific ones are:
# each already ships in the published iGEM bundle's parts library, so seeding them here discloses
# nothing that is not already downloadable. Anything not on this list is refused below, which makes
# the IP boundary a check rather than a comment. Add an id here only after confirming it appears in
# the public export's LOCK.tsv, and say so in the note.
PUBLISHED_DESIGNED = {
    "RBS_sfGFP_med": "ships in the public bundle as designed/acoustic/"
                     "RBS_sfGFP_med__v1__4fb6162d1eb2.gb (one of 13 designed parts in the "
                     "30-part public export)",
}

# id -> (role, variant, display name).  Public reference parts, plus PUBLISHED_DESIGNED ids.
ALLOWLIST = {
    "J23114": ("promoter", "constitutive-weak", "Anderson promoter (weak ~0.10)"),
    "J23116": ("promoter", "constitutive-weak", "Anderson promoter (weak ~0.16)"),
    "J23117": ("promoter", "constitutive-weak", "Anderson promoter (weak ~0.06)"),
    "PyeaR": ("promoter", None, "PyeaR nitrate/nitrite-responsive promoter"),
    "P_hrpL": ("promoter", None, "pHrpL sigma54 AND-gate output promoter (BBa_K4907019)"),
    "ALPaGA": ("promoter", None, "ALPaGA LldR lactate-responsive promoter (Addgene #175272)"),
    "B0032": ("rbs", "weak", "RBS (weak, BBa_B0032)"),
    # Team-designed, already public. Without it this RBS lands in an unidentified block and the
    # RBS-to-ATG spacing check cannot run on it - which is exactly what happened to the first
    # student construct Kagami was ever given.
    "RBS_sfGFP_med": ("rbs", "medium", "sfGFP RBS (OSTIR-tuned, medium; WIST iGEM)"),
    "B0015": ("terminator", "double", "Double terminator (BBa_B0015)"),
    "ECK120033736": ("terminator", None, "natural E. coli terminator (Chen 2013)"),
    "L3S2P55": ("terminator", None, "synthetic Voigt terminator (Chen 2013)"),
    "L3S2P11": ("terminator", None, "synthetic Voigt terminator (Chen 2013)"),
    "L3S2P24": ("terminator", None, "synthetic Voigt terminator (Chen 2013)"),
    "L3S3P11": ("terminator", None, "synthetic Voigt terminator (Chen 2013)"),
    "L3S3P31": ("terminator", None, "synthetic Voigt terminator (Chen 2013)"),
    "sfGFP": ("reporter", None, "superfolder GFP CDS (BBa_I746916)"),
    "amilCP": ("reporter", None, "amilCP blue chromoprotein CDS (BBa_K592009)"),
    "lacZ": ("reporter", None, "beta-galactosidase lacZ (E. coli MG1655)"),
    "KanR": ("cds", None, "kanamycin resistance (aph/nptII)"),
    "cat": ("cds", None, "chloramphenicol resistance (Tn9 cat / CmR)"),
    "p15A": ("origin", None, "p15A replication origin (pACYC184)"),
    "pSC101_ori": ("origin", None, "pSC101 low-copy replicon"),
}

# public canonical parts not (yet) in the library — hand-seeded, to be verified.
HAND_SEED = [
    dict(id="B0034", registry="BBa_B0034", role="rbs", variant="strong",
         name="RBS (strong, BBa_B0034)", seq="AAAGAGGAGAAA",
         provenance="seed — verify vs iGEM Registry BBa_B0034"),
    dict(id="J23100", registry="BBa_J23100", role="promoter", variant="constitutive-strong",
         name="Anderson promoter (strong ~1.0)",
         seq="TTGACGGCTAGCTCAGTCCTAGGTACAGTGCTAGC",
         provenance="seed — verify vs iGEM Registry BBa_J23100"),
    dict(id="J23106", registry="BBa_J23106", role="promoter", variant="constitutive-medium",
         name="Anderson promoter (medium ~0.47)",
         seq="TTTACGGCTAGCTCAGTCCTAGGTATAGTGCTAGC",
         provenance="seed — verify vs iGEM Registry BBa_J23106"),
    dict(id="J23119", registry="BBa_J23119", role="promoter", variant="constitutive-strong",
         name="Anderson promoter (consensus)",
         seq="TTGACAGCTAGCTCAGTCCTAGGTATAATGCTAGC",
         provenance="seed — verify vs iGEM Registry BBa_J23119"),
]



# ── the standard catalogue (--registry-bulk) ────────────────────────────────
# A PROPOSAL, not a claim that each exists. Every name is looked up; misses are reported and
# skipped. Chosen as what a team actually reaches for: the Anderson promoter ladder, the B003x RBS
# ladder, the usual terminators, the common reporters, and the classic inducible/repressor pairs.
STANDARD_PARTS = (
    # Anderson constitutive promoter ladder - the single most-reused family in iGEM
    [f"BBa_J231{n:02d}" for n in range(0, 20)]
    # B00xx: the classic RBS ladder and the classic terminators live in one dense block
    + [f"BBa_B00{n:02d}" for n in range(10, 16)]        # terminators B0010-B0015
    + [f"BBa_B00{n:02d}" for n in range(29, 36)]        # RBS ladder B0029-B0035
    + [f"BBa_B10{n:02d}" for n in range(1, 13)]         # B1001-B1012 terminators
    # E00xx / E1010: the standard fluorescent reporters
    + [f"BBa_E00{n:02d}" for n in range(20, 43)]
    + ["BBa_E1010"]
    # I746xxx: the superfolder GFP family
    + [f"BBa_I746{n:03d}" for n in range(909, 917)]
    # K592xxx: the chromoprotein set (amilCP and relatives) - visible without a fluorimeter,
    # which is why school teams reach for them
    + [f"BBa_K592{n:03d}" for n in range(0, 31)]
    # C00xx repressors/activators and R00xx inducible promoters, as matched pairs
    + ["BBa_C0012", "BBa_C0040", "BBa_C0051", "BBa_C0060", "BBa_C0061", "BBa_C0062",
       "BBa_C0079", "BBa_C0080"]
    + ["BBa_R0010", "BBa_R0011", "BBa_R0040", "BBa_R0051", "BBa_R0062", "BBa_R0063",
       "BBa_R0080", "BBa_R0082"]
    # M00xx degradation tags - a common cause of "my protein disappeared"
    + [f"BBa_M00{n:02d}" for n in range(50, 54)]
    # the RFP test device every team transforms first
    + ["BBa_J04450"]
)


def registry_bulk(existing_ids):
    """Fetch STANDARD_PARTS from the Registry. Returns (rows, misses, unreachable).

    `existing_ids` are already-seeded ids (library-derived, LOCK-verified). A Registry copy of one
    of those is skipped: hash-verified provenance outranks a network fetch.
    """
    import datetime
    import kg_registry

    rows, misses = [], []
    today = datetime.date.today().isoformat()
    print(f"fetching {len(STANDARD_PARTS)} standard parts from the iGEM Registry ...")
    for name in STANDARD_PARTS:
        pid = name[4:] if name.startswith("BBa_") else name
        if pid in existing_ids:
            continue                      # the sealed library's copy wins
        time.sleep(0.4)          # pace the run; two calls per part adds up fast
        time.sleep(0.4)          # pace the run; two calls per part adds up fast
        try:
            p = kg_registry.fetch(name)
        except kg_registry.RegistryUnavailable as exc:
            print(f"  Registry unreachable: {exc}")
            return rows, misses, True
        if not p:
            misses.append(name)
            continue
        seq = p["seq"]
        prov = (f"iGEM Registry {p['name']} uuid={p['uuid']} "
                f"seq_sha256={seq_sha256_of(seq)[:12]} fetched={today}"
                + (f" | {p['so']} {p['so_label']}" if p["so"] else ""))
        rows.append((pid, p["name"], p["role"] or "", "", p["title"][:70] or p["name"], prov, seq))
        existing_ids.add(pid)
    return rows, misses, False

def _registry_hint(source):
    i = source.find("BBa_")
    if i >= 0:
        j = i
        while j < len(source) and (source[j].isalnum() or source[j] == "_"):
            j += 1
        return source[i:j]
    return ""




# Composite DEVICES, by the Registry's own term. A Generator is promoter + RBS + CDS + terminator in
# one entry; a Translational Unit is RBS + CDS. They are excluded from the reference set because a
# reference that is several parts outranks the individual parts on match length and collapses the
# decomposition - measured on 2026-09-15, see the commit message.
COMPOSITE_TERMS = ("IGEM:0000007", "IGEM:0000009", "IGEM:0000021")


def _is_composite(provenance):
    return any(term in provenance for term in COMPOSITE_TERMS)

def _carry_forward_registry_rows(refdir, rows):
    """Preserve previously fetched Registry parts this run did not produce.

    Fetching costs minutes and a share of a public service's rate limit; keeping costs nothing. A
    run that fetched nothing must therefore not be allowed to erase a run that fetched plenty.

    Only "iGEM Registry" rows are carried. Library rows are re-derived from LOCK every run, so
    resurrecting one from a stale file could reinstate a part that has since been removed.
    """
    tsv = os.path.join(refdir, "reference_parts.tsv")
    fasta = os.path.join(refdir, "reference_parts.fasta")
    if not (os.path.exists(tsv) and os.path.exists(fasta)):
        return rows, 0

    seqs, cur = {}, None
    with open(fasta, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith(">"):
                cur = line[1:].strip()
                seqs[cur] = []
            elif cur:
                seqs[cur].append(line.strip())
    seqs = {k: "".join(v) for k, v in seqs.items()}

    have = {r[0] for r in rows}
    carried = 0
    with open(tsv, "r", encoding="utf-8") as f:
        header = f.readline().rstrip("\n").split("\t")
        ix = {h: i for i, h in enumerate(header)}
        for line in f:
            if not line.strip():
                continue
            c = line.rstrip("\n").split("\t")

            def g(k):
                return c[ix[k]] if k in ix and ix[k] < len(c) else ""
            pid, prov = g("id"), g("provenance")
            if pid in have or not prov.startswith("iGEM Registry") or pid not in seqs:
                continue
            rows.append((pid, g("registry"), g("role"), g("variant"), g("name"), prov, seqs[pid]))
            carried += 1
    return rows, carried

def main():
    ap = argparse.ArgumentParser()
    default_lib = os.path.normpath(os.path.join(HERE, "..", "..", "..", "..", "parts-library"))
    ap.add_argument("--library", default=default_lib, help="path to Synbio/parts-library")
    ap.add_argument("--registry-bulk", action="store_true", dest="registry_bulk",
                    help="also fetch the STANDARD_PARTS catalogue from the iGEM Registry and add "
                         "any not already supplied by the sealed library. Needs the network; the "
                         "result is baked into the shipped reference file so audits stay offline.")
    ap.add_argument("--no-lock-root", action="store_true",
                    help="skip the LOCK.root integrity check (per-part hash gate still runs)")
    a = ap.parse_args()

    refdir = os.path.join(HERE, "refs")
    os.makedirs(refdir, exist_ok=True)
    rp = os.path.join(a.library, "ref_parts")
    lockpath = os.path.join(rp, "LOCK.tsv")

    # --- LOCK load + root integrity (trust nothing on read) ---
    lock_rows, lock_by_outfile = [], {}
    if os.path.exists(lockpath):
        try:
            lock_rows = read_lock(lockpath)
        except Exception as e:
            print(f"ERROR: cannot read LOCK.tsv: {e}", file=sys.stderr)
            return 2
        # Key on the BARE FILENAME. LOCK records a designed part's outfile with its
        # subdirectory (designed/<track>/x.gb) while the loop below looks up a basename, so
        # keying on the raw field made every designed part look absent from LOCK and the
        # fail-closed gate refused it. Both spellings are kept so either lookup resolves.
        lock_by_outfile = {}
        for r in lock_rows:
            of = r.get("outfile") or ""
            lock_by_outfile[of] = r
            lock_by_outfile[os.path.basename(of)] = r
        if not a.no_lock_root:
            recomputed = _lock_root(lock_rows)
            attested = last_attested_root(os.path.join(rp, "LOCK.root.log"))
            if attested and recomputed != attested:
                print(f"BLOCK: LOCK.root mismatch — recomputed {recomputed[:12]} != "
                      f"attested {attested[:12]} ({len(lock_rows)} rows). Library integrity "
                      f"drift; refusing to build the reference set.", file=sys.stderr)
                return 2
            print(f"LOCK.root OK: {recomputed[:12]} over {len(lock_rows)} rows"
                  + ("" if attested else " (no LOCK.root.log to compare — per-part gate only)"))
    else:
        print(f"WARNING: no LOCK.tsv at {lockpath} — writing hand-seeded parts only.",
              file=sys.stderr)

    rows = []      # (id, registry, role, variant, name, provenance, seq)
    blocked, missing = [], []

    for pid, (role, variant, name) in ALLOWLIST.items():
        # Search the whole library, not just its top level. Designed parts live in
        # designed/<track>/, so a top-level-only glob reported every one of them as "missing" and
        # skipped it in silence - the ALLOWLIST could not have contained a designed part at all.
        hits = sorted(set(glob.glob(os.path.join(rp, f"{pid}__v*.gb"))
                          + glob.glob(os.path.join(rp, "**", f"{pid}__v*.gb"), recursive=True)))
        if not hits:
            missing.append(pid)
            continue
        chosen = hits[-1]
        rec = kg_parse.parse(chosen)
        seq = rec.seq
        if not seq:
            blocked.append((pid, "empty sequence"))
            continue

        # --- the gate: recompute seq_sha256 and match LOCK + filename ---
        recomputed = seq_sha256_of(seq)
        fn12 = _filename_sha12(chosen)
        lockrow = lock_by_outfile.get(os.path.basename(chosen))
        if lock_rows and lockrow is None:
            blocked.append((pid, f"{os.path.basename(chosen)} not in LOCK"))
            continue
        if recomputed[:12] != fn12:
            blocked.append((pid, f"seq_sha256 {recomputed[:12]} != filename {fn12}"))
            continue
        if lockrow is not None and recomputed != lockrow.get("seq_sha256"):
            blocked.append((pid, f"seq_sha256 {recomputed[:12]} != LOCK "
                                 f"{str(lockrow.get('seq_sha256'))[:12]}"))
            continue

        # The IP boundary, enforced rather than described: a designed part is seeded only if it is
        # recorded in PUBLISHED_DESIGNED as already shipping publicly.
        klass = (lockrow or {}).get("class", "")
        if klass == "designed" and pid not in PUBLISHED_DESIGNED:
            blocked.append((pid, "class=designed and not in PUBLISHED_DESIGNED (IP boundary)"))
            continue

        src = lockrow.get("source", "") if lockrow else ""
        registry = _registry_hint(src)
        prov = f"parts-library {os.path.basename(chosen)} [seq_sha256 verified vs LOCK]"
        if src:
            prov += f" | {src[:80]}"
        rows.append((pid, registry, role, variant or "", name, prov, seq))

    incomplete = False
    seeded_ids = {r[0] for r in rows}

    if getattr(a, "registry_bulk", False):
        bulk, bulk_misses, unreachable = registry_bulk(seeded_ids)
        rows.extend(bulk)
        print(f"Registry: {len(bulk)} part(s) added"
              + (f", {len(bulk_misses)} not found" if bulk_misses else ""))
        if bulk_misses:
            print(f"  not in the Registry (skipped): {', '.join(bulk_misses)}")
        if unreachable:
            # Exit non-zero. A silently incomplete reference set is the failure mode that matters:
            # it degrades identification everywhere, quietly, and nothing downstream would notice.
            print("  WARNING: the Registry became unreachable partway; the set is INCOMPLETE.",
                  file=sys.stderr)
            incomplete = True


    if blocked:
        print("\nBLOCKED parts (hash gate failed — NOT written):", file=sys.stderr)
        for pid, why in blocked:
            print(f"  ✗ {pid}: {why}", file=sys.stderr)

    if missing:
        print(f"\nnot found in library (skipped): {', '.join(missing)}")

    # Keep what earlier runs paid for. Without this a throttled run silently replaces a good
    # reference set with a smaller one - which is exactly what happened on 2026-09-15.
    rows, carried = _carry_forward_registry_rows(refdir, rows)
    if carried:
        print(f"carried forward: {carried} Registry part(s) fetched by an earlier run")

    # Drop composite devices. Filtered here, at the single write choke point, so it catches
    # carried-forward rows as well - a fetch-time filter would leave the ones already on disk in
    # place forever.
    before = len(rows)
    dropped = [r[0] for r in rows if _is_composite(r[5])]
    rows = [r for r in rows if not _is_composite(r[5])]
    if dropped:
        print(f"composites excluded: {before - len(rows)} device(s) that would swallow their own "
              f"parts ({', '.join(sorted(dropped)[:6])}"
              + (" ..." if len(dropped) > 6 else "") + ")")

    # Hand-seeded parts are the WEAKEST tier: typed in, never confirmed against a primary source.
    # They are added LAST, after carry-forward, so a uuid-sourced Registry row always wins. Running
    # them earlier let a hand-typed B0034 outrank the fetched one - the placeholder beating the
    # real thing, which is the opposite of the intent.
    have = {r[0] for r in rows}
    for h in HAND_SEED:
        if h["id"] in have:
            continue
        rows.append((h["id"], h["registry"], h["role"], h["variant"] or "",
                     h["name"], h["provenance"], h["seq"]))

    rows.sort(key=lambda r: (r[2], r[0]))
    with open(os.path.join(refdir, "reference_parts.tsv"), "w", encoding="utf-8") as f:
        f.write("id\tregistry\trole\tvariant\tname\tprovenance\n")
        for pid, registry, role, variant, name, prov, seq in rows:
            f.write(f"{pid}\t{registry}\t{role}\t{variant}\t{name}\t{prov}\n")
    with open(os.path.join(refdir, "reference_parts.fasta"), "w", encoding="utf-8") as f:
        for pid, registry, role, variant, name, prov, seq in rows:
            f.write(f">{pid}\n{seq}\n")

    # Three provenance tiers, counted separately because they are not equally trustworthy.
    from_lib = sum(1 for r in rows if r[5].startswith("parts-library"))
    from_reg = sum(1 for r in rows if r[5].startswith("iGEM Registry"))
    hand = len(rows) - from_lib - from_reg
    print(f"\nwrote {len(rows)} parts to {refdir}/  "
          f"({from_lib} library-verified, {from_reg} Registry-fetched, {hand} hand-seeded)")
    if incomplete:
        print("", file=sys.stderr)
        print("the reference set is INCOMPLETE - re-run to finish it", file=sys.stderr)
    roles = {}
    for r in rows:
        roles[r[2]] = roles.get(r[2], 0) + 1
    print("  by role: " + ", ".join(f"{k}={v}" for k, v in sorted(roles.items())))

    # An INCOMPLETE reference set is a failure, not a warning: it silently degrades identification
    # everywhere and nothing downstream would notice. This line was missing when the comment above
    # already claimed it, so the run printed INCOMPLETE and exited 0.
    return 1 if (blocked or incomplete) else 0


if __name__ == "__main__":
    sys.exit(main())
