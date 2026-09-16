"""
kg_rebuild.py — the one-command bridge from a Kagami audit to a clean, sealed Katana rebuild.

Kagami finds and explains; it never seals (sealing a part from the construct you are auditing is
the circular-provenance trap Katana forbids). This module orchestrates the FORWARD engine to do the
sealing and the rebuild, by driving the engine's own CLI tools as separate processes — it imports
nothing from the engine, so Kagami stays decoupled and the seal still comes from each part's
independent primary source, never from the audited bytes.

The chain, all real engine steps:
  1. katana_init.py     — create the target parts library (once).
  2. add_part.py        — for each identified block, fetch it FRESH from its primary source
                          (the iGEM Registry), verify, seal, hash, LOCK. Never from the construct.
  3. (read LOCK.tsv)    — pull each freshly-sealed part's pin + seal fields.
  4. katana_build.py    — assemble a clean, deterministic .gb from the sealed parts, validate,
                          seal, and emit the order-ready outputs (.gb, .fasta, SBOL, ORDER.csv).

What it will NOT do: invent a source for a block Kagami could not identify, or auto-source a
designed / non-Registry part that is not already in your library. Those STOP the rebuild with a
specific instruction per part, because a part with no independent primary source cannot be sealed —
the same law the whole system rests on.
"""
import os
import subprocess
import sys

ENGINE_TOOLS = ("katana_init.py", "add_part.py", "katana_build.py")


def find_engine(kagami_dir):
    """Locate the forward Katana engine (its CLI tools) relative to Kagami.

    In the published bundle the engine sits at the bundle root, one level above kagami/. Return that
    directory if all three tools are present, else None (Kagami on its own cannot rebuild)."""
    for d in (os.path.dirname(kagami_dir), kagami_dir):
        if all(os.path.isfile(os.path.join(d, t)) for t in ENGINE_TOOLS):
            return d
    return None


def plan(blocks, have=()):
    """Decide, in construct order, what each block needs. Returns (parts, blockers).

    parts    — ordered [{id, role, registry, how}] where how is 'fetch' (seal fresh from the
               Registry) or 'reuse' (already sealed in the target library).
    blockers — [{id, reason}] parts with no independent source (designed/library-only or
               unresolved). Any blocker stops the rebuild until a human names the source.
    """
    have = set(have)
    parts, blockers = [], []
    for b in blocks:
        role = b.ident_role or b.claim_role or "misc_feature"
        if b.ident_id and b.ident_id in have:
            parts.append({"id": b.ident_id, "role": role, "registry": None, "how": "reuse"})
        elif b.ident_id and b.ident_registry and str(b.ident_registry).upper().startswith("BBA_"):
            parts.append({"id": b.ident_id, "role": role,
                          "registry": b.ident_registry, "how": "fetch"})
        elif b.ident_id:
            blockers.append({
                "id": b.ident_id,
                "reason": f"{b.ident_id} was identified but has no iGEM Registry source to fetch "
                          f"(it looks designed, or came from a private library not given here). "
                          f"Add it yourself: add_part.py --from <your-library> --id {b.ident_id}, "
                          f"or --file <seq>; or pass --library <your-library> so Kagami can reuse it."})
        else:
            blockers.append({
                "id": f"UNRESOLVED_{b.start}_{b.end}",
                "reason": f"the {role} at {b.start}-{b.end} ({b.length} bp) matched no reference, so "
                          f"it has no primary source to seal from. Identify where it came from, then "
                          f"add_part.py --accession / --file before rebuilding."})
    return parts, blockers


def _run(cmd, cwd=None):
    # Decode as UTF-8 with replacement, never the Windows locale (cp1252): the engine tools print
    # ✓ / → / … and their output would otherwise crash the subprocess reader on a non-cp1252 byte.
    p = subprocess.run([sys.executable] + cmd, cwd=cwd, capture_output=True,
                       encoding="utf-8", errors="replace")
    return p.returncode == 0, (p.stdout or "") + (p.stderr or "")


def _lock_path(library):
    """Locate ref_parts/LOCK.tsv. `--library` may point at the parts-library dir itself or at the
    project root that holds it (katana_init makes <root>/parts-library/ref_parts), so check both."""
    for cand in (os.path.join(library, "ref_parts", "LOCK.tsv"),
                 os.path.join(library, "parts-library", "ref_parts", "LOCK.tsv")):
        if os.path.isfile(cand):
            return cand
    return None


def _lock_rows(library):
    """Read the library's LOCK.tsv → {id: {version, seq_sha256, length, outfile}}."""
    lock = _lock_path(library)
    rows = {}
    if not lock:
        return rows
    with open(lock, "r", encoding="utf-8") as f:
        header = f.readline().rstrip("\n").split("\t")
        idx = {h: i for i, h in enumerate(header)}
        for line in f:
            if not line.strip():
                continue
            c = line.rstrip("\n").split("\t")

            def g(k):
                return c[idx[k]] if k in idx and idx[k] < len(c) else ""
            rows[g("id")] = {"version": g("version"), "seq_sha256": g("seq_sha256"),
                             "length": g("length"), "outfile": g("outfile")}
    return rows


def _spec_text(record, parts, rows, vendor):
    """Emit a BUILD-READY Katana Spec (with the seal blocks katana_build needs), not the draft."""
    L = ["id:            " + record.name + "-rebuilt",
         "version:       1",
         "track:         acoustic",
         'purpose:       "rebuilt from a Kagami audit; parts freshly sealed from primary source"',
         "host:          E_coli_MG1655",
         "assembly:      { method: null }",
         "vendor:        " + vendor,
         "constraints:",
         "  fragment_bp_max: 5000",
         "  forbid_sites:    [EcoRI, XbaI, SpeI, PstI, BsaI, BsmBI, SapI]",
         "  host_context:    E_coli_MG1655",
         "  output_gate:     acoustic-only",
         "",
         "parts:"]
    order = []
    for p in parts:
        r = rows.get(p["id"])
        if not r:
            continue
        sha12 = r["seq_sha256"][:12]
        L += [f"  - id: {p['id']}",
              f"    role: {p['role']}",
              "    class: reference",
              f'    pin:    "{p["id"]}@v{r["version"]}@{sha12}"',
              f'    seal:   {{ status: SEALED, lib: "{r["outfile"]}", seq_sha256_12: {sha12}, '
              f'length: {r["length"]} }}']
        order.append(p["id"])
    L += ["",
          "architecture:",
          f"  order:    [{', '.join(order)}]",
          "  topology: linear-insert"]
    return "\n".join(L) + "\n"


def rebuild(record, blocks, library, engine, vendor="Twist", outdir=None, progress=None):
    """Run the full seal -> build chain. `progress(msg)` receives step lines. Returns a dict with
    `status` one of:
      'blocked-unresolved' — some parts have no primary source (blockers listed); nothing sealed.
      'seal-failed'        — an add_part step failed (detail included).
      'build-failed'       — parts sealed, but katana_build blocked (its output included).
      'rebuilt'            — success; outputs[] lists the produced files, gb is the construct .gb.
    """
    def say(m):
        if progress:
            progress(m)

    library = os.path.abspath(library)
    have = set(_lock_rows(library))
    parts, blockers = plan(blocks, have)
    if blockers:
        return {"status": "blocked-unresolved", "blockers": blockers, "parts": parts}
    if not parts:
        return {"status": "blocked-unresolved",
                "blockers": [{"id": "-", "reason": "no identifiable parts to rebuild from."}],
                "parts": []}

    # 1. init the library if it is not there yet. katana_init takes the PROJECT ROOT and creates
    #    <root>/parts-library/ref_parts inside it, so when --library points at a parts-library dir
    #    the root is its parent.
    if _lock_path(library) is None:
        root = os.path.dirname(library) if os.path.basename(library) == "parts-library" else library
        say(f"Creating a parts library under {root} ...")
        ok, out = _run([os.path.join(engine, "katana_init.py"), root], cwd=engine)
        if not ok or _lock_path(library) is None:
            return {"status": "seal-failed", "detail": "katana_init failed:\n" + out}

    # 2. seal each fetch part FRESH from the Registry (reuse ones are already sealed)
    for p in parts:
        if p["how"] == "reuse" or p["id"] in _lock_rows(library):
            say(f"{p['id']} is already in the library — reusing the sealed copy.")
            continue
        say(f"Sealing {p['id']} from the iGEM Registry ({p['registry']}) ...")
        ok, out = _run([os.path.join(engine, "add_part.py"), "--library", library,
                        "--registry", p["registry"], "--id", p["id"]], cwd=engine)
        if not ok or p["id"] not in _lock_rows(library):
            return {"status": "seal-failed",
                    "detail": f"could not seal {p['id']} ({p['registry']}):\n" + out}

    # 3. generate the build-ready spec from LOCK
    rows = _lock_rows(library)
    outdir = os.path.abspath(outdir or os.path.join(os.path.dirname(library), "rebuild_outputs"))
    os.makedirs(outdir, exist_ok=True)
    spec_path = os.path.join(outdir, record.name + "-rebuilt.spec.yaml")
    with open(spec_path, "w", encoding="utf-8") as f:
        f.write(_spec_text(record, parts, rows, vendor))
    say(f"Wrote the recovered Spec: {spec_path}")

    # 4. assemble + validate + seal + emit outputs (run in outdir so outputs/ lands there)
    say("Rebuilding with Katana (assemble, validate, seal, order outputs) ...")
    ok, out = _run([os.path.join(engine, "katana_build.py"), spec_path, "--library", library],
                   cwd=outdir)
    if not ok:
        return {"status": "build-failed", "detail": out, "spec": spec_path}

    produced = []
    for line in out.splitlines():
        t = line.strip()
        for tag in (".gb:", ".fasta:", ".csv:", "Output:"):
            if t.startswith(tag):
                produced.append(t[len(tag):].strip())
    gb = next((p for p in produced if p.lower().endswith(".gb")), None)
    return {"status": "rebuilt", "spec": spec_path, "outputs": sorted(set(produced)),
            "gb": gb, "log": out}
