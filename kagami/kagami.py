#!/usr/bin/env python3
"""
Kagami — the reverse-Katana sequence auditor.

Katana builds a construct forward from intent. Kagami runs it backward: take any
sequence, identify the parts inside it against PUBLIC references, and return a
pass / flag / fail verdict per block — with the reason and the fix for each finding.

Kagami's edge is the AUDIT (QC verdict + reasons + fixes), not the annotation —
identifying parts is already solved by pLannotate / SnapGene. It uses only public
references and public checking machinery, so it ships under the WIST iGEM team,
decoupled from any private research track.

Kagami REPORTS; it does not SEAL. Only forward Katana seals, hashes, and rebuilds
(see kg_bridge for how the loop closes without breaking circular-provenance).

Usage:
  python kagami.py audit INPUT.gb [options]
    --vendor {Twist,GenScript,IDT}   apply that vendor's per-fragment size cap
    --host GENOME.fna                run the >40 bp host off-target scan
    --html OUT.html                  write the visual report
    --json OUT.json                  write machine-readable findings
    --emit-spec OUT.spec.yaml        write a draft Katana Spec (rebuild bridge)
    --emit-intake OUT.intake.txt     write per-part library intake requests

Exit codes:  0 PASS (incl. PASS — N notes)   5 REVIEW (flags, no fail)   1 FAIL   2 ERROR
"""
import argparse
import html
import json
import os
import re
import sys
import tempfile

import kg_parse
import kg_refs
import kg_identify
import kg_audit
import kg_bridge

VENDOR_CAP = {"Twist": 5000, "IDT": 3000, "GenScript": 10000}


def _load_host(path):
    if not path:
        return None
    seq = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith(">"):
                continue
            seq.append("".join(c for c in line if c.isalpha()))
    return "".join(seq).upper()


def run(args):
    if not os.path.exists(args.input):
        print(f"ERROR: input not found: {args.input}", file=sys.stderr)
        return 2
    if getattr(args, "library", None):
        # Load before identification, since the reference set is what identify() blasts against.
        added, replaced, problems = kg_refs.add_library(args.library)
        print(f"library  : {added} part(s) loaded from {args.library}"
              + (f", {replaced} shipped reference(s) superseded" if replaced else ""))
        for p in problems:
            print(f"  REFUSED  {p}")
        if not added:
            print("  (nothing loaded - auditing against the shipped reference set only)")

    record = kg_parse.parse(args.input)
    _joined = getattr(record, "assembled_from", None)
    if _joined:
        print(f"input    : {len(_joined)} DNA fragment(s) found and joined IN FILE ORDER "
              f"({', '.join(str(n) + ' bp' for n in _joined)} = {sum(_joined)} bp total)")
        print("           If that is not the order they belong in, the audit below is of a "
              "construct you did not build.")

    ident_status = {}
    with tempfile.TemporaryDirectory() as wd:
        blocks = kg_identify.identify(record, wd, status=ident_status,
                                      deep=getattr(args, "deep", False))
    if ident_status.get("deep_failed"):
        # Only --deep can be unavailable now. The default identifier always runs, so there is
        # no longer a line here saying a mislabel could not be caught.
        print("deep     : %s" % ident_status["deep_failed"])

    cap = VENDOR_CAP.get(args.vendor) if args.vendor else None
    host_seq = _load_host(args.host) if args.host else None
    host_reca = {"pos": True, "neg": False}.get(getattr(args, "host_reca", None))
    assembly = getattr(args, "assembly", None)
    if getattr(args, "registry", False):
        print("registry : checking claimed BBa_* labels against the iGEM Registry ...")
        _reg = registry_findings(record, blocks)
        if not _reg:
            print("  (no block claims a Registry part name — nothing to check)")
    else:
        _reg = []

    findings = kg_audit.audit(record, blocks, vendor=args.vendor,
                              fragment_bp_max=cap, host_seq=host_seq,
                              host_reca=host_reca, assembly=assembly,
                              identify_status=ident_status)
    findings = _reg + findings
    v = kg_audit.verdict(findings)

    print_text(record, blocks, findings, v)

    if args.json:
        write_json(args.json, record, blocks, findings, v)
        print(f"\n[json]   {args.json}")
    if args.html:
        write_html(args.html, record, blocks, findings, v)
        print(f"[html]   {args.html}")
    if args.emit_spec:
        with open(args.emit_spec, "w", encoding="utf-8") as f:
            f.write(kg_bridge.draft_spec(record, blocks, findings, vendor=args.vendor or "Twist"))
        print(f"[spec]   {args.emit_spec}   (draft Katana Spec — rebuild bridge)")
    if args.emit_intake:
        reqs = kg_bridge.intake_requests(blocks)
        with open(args.emit_intake, "w", encoding="utf-8") as f:
            f.write("# Kagami intake requests → hand to katana-parts-library.\n")
            f.write("# Each part is fetched FRESH from its primary source, then verified,\n")
            f.write("# sealed and hashed by the library — NEVER sealed from this construct\n")
            f.write("# (circular-provenance-seal-rule). Kagami does not hash/seal parts itself.\n\n")
            for r in reqs:
                f.write(f"[{r['cls']}] {r['id']}\n")
                f.write(f"    primary source : {r['primary_source']}\n")
                f.write(f"    action         : {r['action']}\n")
                if r.get("note"):
                    f.write(f"    note           : {r['note']}\n")
                f.write("\n")
        print(f"[intake] {args.emit_intake}   (→ katana-parts-library)")

    return {"PASS": 0, "REVIEW": 5, "FAIL": 1}[kg_audit.verdict_kind(findings)]


# ---------------------------------------------------------------- text report
_MARK = {"PASS": "PASS", "FLAG": "FLAG", "FAIL": "FAIL", "NOTE": "note", "SKIP": "----"}
_ORDER = {"FAIL": 0, "FLAG": 1, "NOTE": 2, "SKIP": 3, "PASS": 4}


def _block_line(b):
    role = b.ident_role or b.claim_role or "-"
    if b.ident_id:
        ident = b.ident_id
    elif b.note:
        ident = b.note
    elif role in ("cds", "reporter", "gene"):
        ident = "CDS (no reference match)"
    else:
        ident = "unidentified"
    claim = f'  claim="{b.claim_label}"' if b.claim_label else ""
    conf = ""
    if b.pident is not None:
        conf = f"  [{b.pident}% id, {int((b.coverage or 0)*100)}% cov]"
    # Identical-sequence re-deposits are common - fifteen references carry the exact B0015
    # sequence. Naming one of them silently would claim more certainty than the evidence supports.
    alts = getattr(b, "alternatives", None) or []
    amb = ""
    if alts:
        shown = ", ".join(alts[:3]) + (" ..." if len(alts) > 3 else "")
        amb = f"  (= {len(alts)} other ref{'s' if len(alts) != 1 else ''}: {shown})"
    strand = "+" if b.strand == 1 else "-"
    return f"  {b.start:>6}-{b.end:<6} {strand}  {role:<11} {ident}{conf}{claim}{amb}"


def _ident_not_run(findings):
    """True when the identification step did not run. Read off the findings so every output
    format (text, JSON, HTML) agrees without threading another argument through each one."""
    return any(f.category == "identification" and f.status == "FLAG" for f in findings)


def print_text(record, blocks, findings, v):
    print("=" * 72)
    print(f"KAGAMI · sequence audit   ·   {record.name}   ·   {len(record.seq)} bp   "
          f"· {record.topology}")
    print("=" * 72)
    if _ident_not_run(findings):
        # "identified against the public seed set" is the same false reassurance as the PASS was,
        # only smaller: nothing was compared against the seed set on this run.
        print(f"\nDECOMPOSITION — {len(blocks)} block(s) from the file's OWN ANNOTATION only "
              f"(not identified — BLAST+ unavailable):")
    else:
        print(f"\nDECOMPOSITION — {len(blocks)} block(s) identified against the public seed set:")
    for b in blocks:
        print(_block_line(b))

    print("\nAUDIT:")
    for f in sorted(findings, key=lambda x: _ORDER.get(x.status, 9)):
        loc = f" @ {f.loc}" if f.loc else ""
        print(f"  [{_MARK.get(f.status, f.status)}] {f.category:<16} {f.summary}{loc}")
        if f.detail:
            print(f"         · {f.detail}")
        if f.fix and f.status not in ("PASS", "SKIP"):
            print(f"         → fix: {f.fix}")

    kind = kg_audit.verdict_kind(findings)
    nfail = kg_audit.count(findings, "FAIL")
    nflag = kg_audit.count(findings, "FLAG")
    nnote = kg_audit.count(findings, "NOTE")
    print("\n" + "-" * 72)
    print(f"VERDICT: {v}   ({nfail} fail, {nflag} to resolve, {nnote} note)")
    if kind == "REVIEW":
        print("  Nothing failed outright, but there are items to resolve before ordering/building.")
    elif kind == "FAIL":
        print("  A hard error is present — fix before this construct is used.")
    elif nnote:
        print("  Clean to order. The notes are context to be aware of, not problems.")
    else:
        print("  All checks passed on the audited dimensions.")
    print("  Kagami reports; it does not SEAL. To rebuild clean, use --emit-spec")
    print("  and hand it to forward Katana (katana-spec → parts-library → assemble).")
    print("-" * 72)


# ---------------------------------------------------------------- json
def write_json(path, record, blocks, findings, v):
    obj = dict(
        name=record.name, length=len(record.seq), topology=record.topology,
        verdict=v,
        # Explicit, because a pipeline consuming this JSON cannot otherwise tell an empty
        # `identity` field meaning "no reference matched" from one meaning "never asked".
        identification_ran=not _ident_not_run(findings),
        blocks=[dict(start=b.start, end=b.end, strand=b.strand,
                     claim=b.claim_label, identity=b.ident_id, name=b.ident_name,
                     role=b.ident_role or b.claim_role, variant=b.ident_variant,
                     registry=b.ident_registry, pident=b.pident, coverage=b.coverage,
                     provenance=b.provenance, note=b.note) for b in blocks],
        findings=[dict(category=f.category, status=f.status, summary=f.summary,
                       loc=f.loc, detail=f.detail, fix=f.fix) for f in findings],
    )
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2)


# ---------------------------------------------------------------- html
_ROLE_COLOR = {"promoter": "var(--accent)", "rbs": "var(--warn)",
               "cds": "var(--accent-ink)", "reporter": "var(--accent-ink)",
               "terminator": "var(--muted)"}
_STAT = {"PASS": ("p", "✓"), "FLAG": ("w", "!"), "FAIL": ("f", "✕"),
         "NOTE": ("n", "○"), "SKIP": ("s", "–")}


def write_html(path, record, blocks, findings, v):
    seqlen = len(record.seq)
    segs = []
    for b in blocks:
        w = max(2.0, 100.0 * b.length / seqlen)
        role = b.ident_role or b.claim_role or "misc"
        color = _ROLE_COLOR.get(role, "var(--muted)")
        # verdict dot for this block
        dot = "pass"
        for f in findings:
            if f.loc == f"{b.start}-{b.end}":
                if f.status == "FAIL":
                    dot = "fail"; break
                if f.status == "FLAG":
                    dot = "warn"
                elif f.status == "NOTE" and dot == "pass":
                    dot = "note"
        lbl = html.escape(b.ident_id or (b.claim_label or "?"))
        segs.append(
            f'<div class="seg" style="flex-grow:{w};border-left:4px solid {color}">'
            f'<span class="vdot {dot}"></span><span class="role">{lbl}</span></div>')

    rows = []
    for f in sorted(findings, key=lambda x: _ORDER.get(x.status, 9)):
        cls, gly = _STAT.get(f.status, ("n", "○"))
        loc = f'<span class="loc">{html.escape(f.loc)}</span>' if f.loc else '<span class="loc">—</span>'
        note = f'<span class="note">{html.escape(f.detail)}</span>' if f.detail else ""
        fix = f'<span class="fix">→ {html.escape(f.fix)}</span>' if (f.fix and f.status not in ("PASS", "SKIP")) else ""
        rows.append(
            f'<div class="rrow"><span class="st {cls}">{gly}</span>'
            f'<span class="what"><b>{html.escape(f.summary)}</b>{note}{fix}</span>{loc}</div>')

    kind = kg_audit.verdict_kind(findings)
    vclass = {"PASS": "ok", "REVIEW": "cond", "FAIL": "bad"}[kind]
    nfail = kg_audit.count(findings, "FAIL")
    nnote = kg_audit.count(findings, "NOTE")
    # The verdict line (v) already carries its own count ("PASS — 1 note", "REVIEW — 1 to resolve"),
    # so the pill is that line plus only the SECONDARY count, never a repeat of the primary one.
    if kind == "FAIL":
        pill = f"{v} · {nfail} error" + ("s" if nfail != 1 else "")
    elif kind == "REVIEW" and nnote:
        pill = f"{v} · {nnote} note" + ("s" if nnote != 1 else "")
    else:
        pill = v

    _nr = _ident_not_run(findings)
    doc = _HTML.replace("{{NAME}}", html.escape(record.name)) \
              .replace("{{LEN}}", f"{seqlen:,}") \
              .replace("{{TOPO}}", record.topology) \
              .replace("{{NBLOCK}}", str(len(blocks))) \
              .replace("{{BLOCKWORD}}", "blocks from the file's own annotation — NOT identified"
                       if _nr else "blocks identified") \
              .replace("{{RULERWORD}}", "identification DID NOT RUN (BLAST+ unavailable)"
                       if _nr else "identified vs public reference seed set") \
              .replace("{{VCLASS}}", vclass) \
              .replace("{{PILL}}", html.escape(pill)) \
              .replace("{{STRIP}}", "\n".join(segs)) \
              .replace("{{ROWS}}", "\n".join(rows))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc)


_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kagami audit — {{NAME}}</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;700;800&family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
:root{--bg:#eef1f4;--surface:#fff;--surface-2:#f7f9fb;--ink:#161b24;--muted:#586470;--faint:#8892a0;--border:#dce1e8;--accent:#0e6e78;--accent-ink:#0a545c;--warn:#a9761a;--pass:#2c7d5a;--fail:#c23945;--warn-soft:#f3e7cf;--pass-soft:#dbeee5;--fail-soft:#f4dcde}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0e131a;--surface:#161d27;--surface-2:#1a2330;--ink:#e9edf2;--muted:#9aa5b2;--faint:#6a7583;--border:#26313f;--accent:#40b7c2;--accent-ink:#7fd3da;--warn:#d7a44e;--pass:#54c48d;--fail:#e56d76;--warn-soft:#3a2e15;--pass-soft:#12352a;--fail-soft:#3c1e22}}
*{box-sizing:border-box}body{background:var(--bg);color:var(--ink);font-family:"IBM Plex Sans",system-ui,sans-serif;margin:0;line-height:1.5}
.wrap{max-width:860px;margin:0 auto;padding:32px 22px 64px}
h1{font-family:"Archivo",sans-serif;font-size:26px;font-weight:800;letter-spacing:-.01em;margin:0}
.sub{font-family:"IBM Plex Mono",monospace;color:var(--muted);font-size:13px;margin-top:6px}
.eyebrow{font-family:"IBM Plex Mono",monospace;font-size:12px;letter-spacing:.13em;text-transform:uppercase;color:var(--accent-ink);margin-bottom:8px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:20px;margin-top:22px}
.strip{display:flex;gap:3px;height:52px;margin:4px 0}
.seg{position:relative;border-radius:6px;display:flex;align-items:center;overflow:hidden;min-width:0;background:var(--surface-2);border:1px solid var(--border)}
.seg .role{font-family:"IBM Plex Mono",monospace;font-size:11px;padding:0 6px 0 9px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-weight:500}
.vdot{position:absolute;top:6px;right:6px;width:9px;height:9px;border-radius:50%}
.vdot.pass{background:var(--pass)}.vdot.warn{background:var(--warn)}.vdot.fail{background:var(--fail)}.vdot.note{background:var(--faint)}
.ruler{display:flex;justify-content:space-between;font-family:"IBM Plex Mono",monospace;font-size:10.5px;color:var(--faint)}
.vpill{font-family:"IBM Plex Mono",monospace;font-size:12px;font-weight:600;padding:5px 12px;border-radius:999px}
.vpill.ok{background:var(--pass-soft);color:var(--pass)}.vpill.cond{background:var(--warn-soft);color:var(--warn)}.vpill.bad{background:var(--fail-soft);color:var(--fail)}
.top{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
.rrow{display:grid;grid-template-columns:20px 1fr auto;gap:12px;align-items:baseline;padding:12px 0;border-top:1px solid var(--border);font-size:14px}
.rrow .st{font-family:"IBM Plex Mono",monospace;font-weight:700;text-align:center}
.rrow .st.p{color:var(--pass)}.rrow .st.w{color:var(--warn)}.rrow .st.f{color:var(--fail)}.rrow .st.n{color:var(--muted)}.rrow .st.s{color:var(--faint)}
.what .note{display:block;color:var(--muted);font-size:12.5px;margin-top:2px}
.what .fix{display:block;color:var(--accent-ink);font-size:12.5px;margin-top:2px}
.loc{font-family:"IBM Plex Mono",monospace;font-size:12px;color:var(--faint);white-space:nowrap}
h2{font-family:"Archivo",sans-serif;font-size:15px;margin:0 0 6px}
footer{margin-top:28px;font-family:"IBM Plex Mono",monospace;font-size:11.5px;color:var(--faint)}
</style></head><body><div class="wrap">
<div class="eyebrow">◤ Kagami · reverse-Katana audit</div>
<h1>{{NAME}}</h1>
<div class="sub">{{LEN}} bp · {{TOPO}} · {{NBLOCK}} {{BLOCKWORD}}</div>
<div class="card"><div class="top" style="margin-bottom:12px"><h2>Decomposition</h2>
<span class="vpill {{VCLASS}}">{{PILL}}</span></div>
<div class="strip">{{STRIP}}</div>
<div class="ruler"><span>0 bp</span><span>{{RULERWORD}}</span><span>{{LEN}} bp</span></div>
</div>
<div class="card"><h2 style="margin-bottom:6px">Audit</h2>{{ROWS}}</div>
<footer>Kagami reports; it does not seal. Rebuild clean via forward Katana (katana-spec → parts-library → assemble). Public parts only · WIST iGEM.</footer>
</div></body></html>"""



_REGISTRY_NAME = re.compile(r"^BBa[_\-][A-Za-z0-9]+$")


def registry_findings(record, blocks):
    """Check every block whose CLAIMED label is a Registry part name against the Registry.

    Returns a list of Finding. Identification is not attempted: the API is name-addressed, so a
    block with no claimed name has nothing to look up and is left alone.
    """
    import kg_registry
    from kg_audit import Finding, PASS, FLAG

    out, seen = [], {}
    for b in blocks:
        label = (b.claim_label or "").strip()
        if not label or not _REGISTRY_NAME.match(label):
            continue
        name = label.replace("-", "_")
        if name not in seen:
            try:
                seen[name] = kg_registry.fetch(name)
            except kg_registry.RegistryUnavailable as exc:
                out.append(Finding(
                    "registry", FLAG, f"Could not reach the iGEM Registry to check {label}",
                    loc=f"{b.start}-{b.end}", detail=str(exc),
                    fix="Re-run with a network connection, or drop --registry to audit offline."))
                return out                     # one unreachable means the rest would be too
        part = seen[name]
        loc = f"{b.start}-{b.end}"
        if part is None:
            out.append(Finding(
                "registry", FLAG, f"The Registry has no part called {label}",
                loc=loc, detail="The label names a part the Registry does not hold.",
                fix="Check the part number, or record where this sequence really came from."))
            continue

        here = kg_refs.normalise(record.sub(b.start, b.end))
        there = kg_refs.normalise(part["seq"])
        if b.strand == -1:
            here = kg_parse.revcomp(here)
        uuid8 = part["uuid"][:8]
        if here == there:
            out.append(Finding(
                "registry", PASS,
                f"{label} confirmed against the Registry ({len(there)} bp, uuid {uuid8})",
                loc=loc))
        elif here and here in there:
            out.append(Finding(
                "registry", FLAG,
                f"{label} is TRUNCATED: {len(here)} bp of the Registry's {len(there)} bp",
                loc=loc,
                detail="The bases present are a proper subsequence of the part named.",
                fix="Use the full part, or relabel this as the fragment it actually is."))
        elif there and there in here:
            out.append(Finding(
                "registry", FLAG,
                f"{label} is EXTENDED: {len(here)} bp contains the Registry's {len(there)} bp",
                loc=loc,
                detail="Extra bases sit inside this block beyond the part named.",
                fix="Check the boundaries; a scar or neighbouring part may be included."))
        else:
            out.append(Finding(
                "registry", FLAG,
                f"{label} does NOT match the Registry sequence "
                f"({len(here)} bp here vs {len(there)} bp, uuid {uuid8})",
                loc=loc,
                detail="The label names a real Registry part and this is not that sequence.",
                fix="Identify what this really is before building with it."))
    return out

def run_rebuild(args):
    """Audit the input, then drive the forward engine to seal the parts and rebuild a clean,
    order-ready construct. The seal always comes from each part's primary source, never the audited
    bytes; unresolved or non-Registry parts stop the rebuild with instructions."""
    import kg_rebuild
    if not os.path.exists(args.input):
        print(f"ERROR: input not found: {args.input}", file=sys.stderr)
        return 2
    here = os.path.dirname(os.path.abspath(__file__))
    engine = getattr(args, "engine", None) or kg_rebuild.find_engine(here)
    if not engine:
        print("ERROR: rebuild needs the forward Katana engine (katana_init.py, add_part.py,\n"
              "       katana_build.py) alongside Kagami. They ship together in the katana bundle —\n"
              "       run this from the unzipped bundle, or pass --engine <dir>.", file=sys.stderr)
        return 2

    record = kg_parse.parse(args.input)
    if getattr(args, "library", None):
        added, replaced, problems = kg_refs.add_library(args.library)
        print(f"library  : {added} of your part(s) loaded for identification"
              + (f", {replaced} shipped reference(s) superseded" if replaced else ""))
        for p in problems:
            print(f"  REFUSED  {p}")
    _rb_status = {}
    with tempfile.TemporaryDirectory() as wd:
        blocks = kg_identify.identify(record, wd, status=_rb_status)
    if _rb_status.get("deep_failed"):
        print("deep     : %s" % _rb_status["deep_failed"])

    lib = args.library or os.path.join(
        os.path.dirname(os.path.abspath(args.input)),
        os.path.splitext(os.path.basename(args.input))[0] + "_katana", "parts-library")
    print(f"\nRebuilding {record.name}: {len(blocks)} block(s) identified.\n")
    res = kg_rebuild.rebuild(record, blocks, library=lib, engine=engine,
                             vendor=args.vendor or "Twist", outdir=args.outdir,
                             progress=lambda m: print("  " + m))
    print()
    st = res["status"]
    if st == "rebuilt":
        print("REBUILT — clean, sealed, order-ready.")
        if res.get("gb"):
            print(f"  construct: {res['gb']}")
        for o in res["outputs"]:
            if o != res.get("gb"):
                print(f"  output:    {o}")
        print(f"  spec:      {res['spec']}")
        print("\n  Every base traces to a part sealed from its own primary source, not from the")
        print("  sequence you audited. Run katana-diff to see what moved.")
        return 0
    if st == "blocked-unresolved":
        print("STOPPED — these parts have no independent primary source, so they cannot be sealed:")
        for b in res["blockers"]:
            print(f"  [{b['id']}] {b['reason']}")
        ok = [p for p in res.get("parts", []) if p.get("how") == "fetch"]
        if ok:
            print("\n  Parts that WOULD auto-seal from the Registry once the above are resolved:")
            for p in ok:
                print(f"    {p['id']} ({p['registry']})")
        return 5
    if st == "seal-failed":
        print("STOPPED — a part could not be sealed from its primary source:")
        print(res["detail"])
        return 1
    if st == "build-failed":
        print("STOPPED — the parts sealed, but the rebuild did not validate. Katana said:")
        print(res["detail"])
        print(f"\n  The recovered Spec is at: {res['spec']}  (fix and re-run katana_build).")
        return 1
    return 1


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="kagami", description="Reverse-Katana sequence auditor.")
    sub = ap.add_subparsers(dest="cmd")
    a = sub.add_parser("audit", help="audit a sequence")
    a.add_argument("input")
    a.add_argument("--vendor", choices=sorted(VENDOR_CAP))
    a.add_argument("--host")
    a.add_argument("--host-reca", dest="host_reca", choices=["pos", "neg"],
                   help="recA status of the host given by --host: pos (recA+, the default "
                        "assumption if omitted) or neg (recA-, a cloning strain). A >40 bp host "
                        "match is an actionable finding only in a recA+ background; in a recA- "
                        "strain it drops to a note.")
    a.add_argument("--assembly", choices=["BsaI", "BsmBI", "SapI", "BioBrick"],
                   help="the assembly method context. A Type IIS or BioBrick-forbidden site is only "
                        "an actionable finding when the chosen method's enzyme would cut it; "
                        "otherwise it is reported as a note. Omit for plain synthesis.")
    a.add_argument("--registry", action="store_true",
                   help="check labels that name an iGEM Registry part (BBa_*) against the Registry "
                        "itself. Needs the network. It verifies CLAIMS; it cannot identify an "
                        "unknown sequence, because the Registry API is addressed by name.")
    a.add_argument("--deep", action="store_true",
                   help="also run NCBI BLAST+ (if installed) for gapped, distant-homology "
                        "search. The built-in identifier runs either way; this only adds "
                        "sensitivity for homologs below about 90%% identity.")
    a.add_argument("--library", metavar="PATH",
                   help="a Katana parts library (the folder holding LOCK.tsv) to audit against, "
                        "in ADDITION to the shipped reference set. Every part is hash-checked "
                        "against LOCK before it is used; mismatches are refused, not loaded.")
    a.add_argument("--html")
    a.add_argument("--json")
    a.add_argument("--emit-spec", dest="emit_spec")
    a.add_argument("--emit-intake", dest="emit_intake")

    rb = sub.add_parser("rebuild",
                        help="audit, then seal the parts from their primary source and rebuild a "
                             "clean, order-ready construct via forward Katana (one command).")
    rb.add_argument("input")
    rb.add_argument("--library", metavar="PATH",
                    help="your Katana parts library: designed parts you already sealed are reused, "
                         "and freshly-fetched Registry parts are added here. Omitted: a fresh "
                         "library is created beside the input.")
    rb.add_argument("--vendor", choices=sorted(VENDOR_CAP), default="Twist")
    rb.add_argument("--outdir", help="where to write the recovered Spec and build outputs "
                                     "(default: beside the library).")
    rb.add_argument("--engine", help="directory holding the Katana engine tools "
                                     "(default: found next to Kagami in the bundle).")

    args = ap.parse_args()
    if args.cmd == "audit":
        return run(args)
    if args.cmd == "rebuild":
        return run_rebuild(args)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
