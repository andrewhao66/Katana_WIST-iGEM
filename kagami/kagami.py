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

Exit codes:  0 PASS   5 CONDITIONAL (flags, no fail)   1 FAIL   2 ERROR
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

    with tempfile.TemporaryDirectory() as wd:
        blocks = kg_identify.identify(record, wd)

    cap = VENDOR_CAP.get(args.vendor) if args.vendor else None
    host_seq = _load_host(args.host) if args.host else None
    if getattr(args, "registry", False):
        print("registry : checking claimed BBa_* labels against the iGEM Registry ...")
        _reg = registry_findings(record, blocks)
        if not _reg:
            print("  (no block claims a Registry part name — nothing to check)")
    else:
        _reg = []

    findings = kg_audit.audit(record, blocks, vendor=args.vendor,
                              fragment_bp_max=cap, host_seq=host_seq)
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

    return {"PASS": 0, "CONDITIONAL": 5, "FAIL": 1}[v]


# ---------------------------------------------------------------- text report
_MARK = {"PASS": "PASS", "FLAG": "FLAG", "FAIL": "FAIL"}


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


def print_text(record, blocks, findings, v):
    print("=" * 72)
    print(f"KAGAMI · sequence audit   ·   {record.name}   ·   {len(record.seq)} bp   "
          f"· {record.topology}")
    print("=" * 72)
    print(f"\nDECOMPOSITION — {len(blocks)} block(s) identified against the public seed set:")
    for b in blocks:
        print(_block_line(b))

    order = {"FAIL": 0, "FLAG": 1, "PASS": 2}
    print("\nAUDIT:")
    for f in sorted(findings, key=lambda x: order[x.status]):
        loc = f" @ {f.loc}" if f.loc else ""
        print(f"  [{_MARK[f.status]}] {f.category:<16} {f.summary}{loc}")
        if f.detail:
            print(f"         · {f.detail}")
        if f.fix and f.status != "PASS":
            print(f"         → fix: {f.fix}")

    nfail = sum(1 for f in findings if f.status == "FAIL")
    nflag = sum(1 for f in findings if f.status == "FLAG")
    print("\n" + "-" * 72)
    print(f"VERDICT: {v}   ({nfail} fail, {nflag} flag)")
    if v == "CONDITIONAL":
        print("  Not clean, not broken — review the flags before ordering/building.")
    elif v == "FAIL":
        print("  A hard error is present — fix before this construct is used.")
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
_STAT = {"PASS": ("p", "✓"), "FLAG": ("w", "!"), "FAIL": ("f", "✕")}


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
        lbl = html.escape(b.ident_id or (b.claim_label or "?"))
        segs.append(
            f'<div class="seg" style="flex-grow:{w};border-left:4px solid {color}">'
            f'<span class="vdot {dot}"></span><span class="role">{lbl}</span></div>')

    order = {"FAIL": 0, "FLAG": 1, "PASS": 2}
    rows = []
    for f in sorted(findings, key=lambda x: order[x.status]):
        cls, gly = _STAT[f.status]
        loc = f'<span class="loc">{html.escape(f.loc)}</span>' if f.loc else '<span class="loc">—</span>'
        note = f'<span class="note">{html.escape(f.detail)}</span>' if f.detail else ""
        fix = f'<span class="fix">→ {html.escape(f.fix)}</span>' if (f.fix and f.status != "PASS") else ""
        rows.append(
            f'<div class="rrow"><span class="st {cls}">{gly}</span>'
            f'<span class="what"><b>{html.escape(f.summary)}</b>{note}{fix}</span>{loc}</div>')

    vclass = {"PASS": "ok", "CONDITIONAL": "cond", "FAIL": "bad"}[v]
    nfail = sum(1 for f in findings if f.status == "FAIL")
    nflag = sum(1 for f in findings if f.status == "FLAG")

    doc = _HTML.replace("{{NAME}}", html.escape(record.name)) \
              .replace("{{LEN}}", f"{seqlen:,}") \
              .replace("{{TOPO}}", record.topology) \
              .replace("{{NBLOCK}}", str(len(blocks))) \
              .replace("{{VERDICT}}", v) \
              .replace("{{VCLASS}}", vclass) \
              .replace("{{VSUM}}", f"{nflag} flag, {nfail} fail") \
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
.vdot.pass{background:var(--pass)}.vdot.warn{background:var(--warn)}.vdot.fail{background:var(--fail)}
.ruler{display:flex;justify-content:space-between;font-family:"IBM Plex Mono",monospace;font-size:10.5px;color:var(--faint)}
.vpill{font-family:"IBM Plex Mono",monospace;font-size:12px;font-weight:600;padding:5px 12px;border-radius:999px}
.vpill.ok{background:var(--pass-soft);color:var(--pass)}.vpill.cond{background:var(--warn-soft);color:var(--warn)}.vpill.bad{background:var(--fail-soft);color:var(--fail)}
.top{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
.rrow{display:grid;grid-template-columns:20px 1fr auto;gap:12px;align-items:baseline;padding:12px 0;border-top:1px solid var(--border);font-size:14px}
.rrow .st{font-family:"IBM Plex Mono",monospace;font-weight:700;text-align:center}
.rrow .st.p{color:var(--pass)}.rrow .st.w{color:var(--warn)}.rrow .st.f{color:var(--fail)}
.what .note{display:block;color:var(--muted);font-size:12.5px;margin-top:2px}
.what .fix{display:block;color:var(--accent-ink);font-size:12.5px;margin-top:2px}
.loc{font-family:"IBM Plex Mono",monospace;font-size:12px;color:var(--faint);white-space:nowrap}
h2{font-family:"Archivo",sans-serif;font-size:15px;margin:0 0 6px}
footer{margin-top:28px;font-family:"IBM Plex Mono",monospace;font-size:11.5px;color:var(--faint)}
</style></head><body><div class="wrap">
<div class="eyebrow">◤ Kagami · reverse-Katana audit</div>
<h1>{{NAME}}</h1>
<div class="sub">{{LEN}} bp · {{TOPO}} · {{NBLOCK}} blocks identified</div>
<div class="card"><div class="top" style="margin-bottom:12px"><h2>Decomposition</h2>
<span class="vpill {{VCLASS}}">{{VERDICT}} · {{VSUM}}</span></div>
<div class="strip">{{STRIP}}</div>
<div class="ruler"><span>0 bp</span><span>identified vs public reference seed set</span><span>{{LEN}} bp</span></div>
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
    a.add_argument("--registry", action="store_true",
                   help="check labels that name an iGEM Registry part (BBa_*) against the Registry "
                        "itself. Needs the network. It verifies CLAIMS; it cannot identify an "
                        "unknown sequence, because the Registry API is addressed by name.")
    a.add_argument("--library", metavar="PATH",
                   help="a Katana parts library (the folder holding LOCK.tsv) to audit against, "
                        "in ADDITION to the shipped reference set. Every part is hash-checked "
                        "against LOCK before it is used; mismatches are refused, not loaded.")
    a.add_argument("--html")
    a.add_argument("--json")
    a.add_argument("--emit-spec", dest="emit_spec")
    a.add_argument("--emit-intake", dest="emit_intake")
    args = ap.parse_args()
    if args.cmd != "audit":
        ap.print_help()
        return 2
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
