#!/usr/bin/env python3
"""Fail-closed Parts Library audit (Gaps 4b + 5, and read-side of 2).
Checks every LOCK row: file present, file_sha256, seq_sha256, filename sha12, row manifest.
Then: no orphan part files without a row; recompute LOCK.root and match LOCK.root + last log line.
Exit code 0 only if EVERYTHING passes. Any problem -> non-zero (BLOCK)."""
import os, sys
import katana_lock as K

def main(lock_path):
    d = os.path.dirname(os.path.abspath(lock_path))
    header, rows = K.read_lock(lock_path)
    problems=[]
    if "row_sha256" not in header:
        problems.append("LOCK has no row_sha256 column — run migrate_add_manifest.py first")
        print("BLOCK:\n - "+problems[0]); return 2
    seen=set()
    for r in rows:
        rid=f"{r['id']} v{r['version']}"
        p=os.path.join(d, r["outfile"])
        if not os.path.exists(p):
            problems.append(f"{rid}: file MISSING ({r['outfile']})"); continue
        seen.add(os.path.normpath(p))
        if K.file_hash(p)!=r["file_sha256"]:
            problems.append(f"{rid}: file_sha256 MISMATCH (bytes changed)")
        try:
            if K.seq_hash(p)!=r["seq_sha256"]:
                problems.append(f"{rid}: seq_sha256 MISMATCH (sequence changed)")
        except Exception as e:
            problems.append(f"{rid}: seq parse error: {e}")
        if K.filename_sha12(r["outfile"])!=r["seq_sha256"][:12]:
            problems.append(f"{rid}: filename sha12 != seq_sha256")
        recomputed = K.row_sha256(r)
        if recomputed!=r.get("row_sha256"):
            problems.append(f"{rid}: row_sha256 MISMATCH (a trust field — source/version/class/outfile — was edited)")
    # orphan scan: any part file with no row = trust-by-dropping-a-file (Gap 5)
    exts=(".gb",".gbk",".faa",".fa",".fasta")
    pending=0
    for root,dirs,files in os.walk(d):
        # prune staging/working dirs (names starting with "_", e.g. _incoming): raw pre-seal fetches
        # legitimately have no LOCK row, so they are NOT orphans.
        pruned=[x for x in dirs if x.startswith("_")]
        dirs[:]=[x for x in dirs if not x.startswith("_")]
        for pd in pruned:
            for _r,_ds,_fs in os.walk(os.path.join(root,pd)):
                pending+=sum(1 for f in _fs if f.lower().endswith(exts))
        for fn in files:
            if fn.lower().endswith(exts):
                fp=os.path.normpath(os.path.join(root,fn))
                if fp not in seen:
                    problems.append(f"ORPHAN part file with no LOCK row: {os.path.relpath(fp,d)}")
    # root check
    root=K.lock_root(rows)
    rp=os.path.join(d,"LOCK.root")
    if not os.path.exists(rp):
        problems.append("LOCK.root missing")
    else:
        stored=open(rp).read().strip()
        if stored!=root: problems.append(f"LOCK.root MISMATCH (rows added/removed/edited): file={stored[:12]} recomputed={root[:12]}")
        lp=os.path.join(d,"LOCK.root.log")
        if os.path.exists(lp):
            last=[l for l in open(lp).read().splitlines() if l.strip()][-1].split("\t")
            if len(last)<2 or last[1]!=root:
                problems.append("current LOCK.root is not the last entry in LOCK.root.log")
    if problems:
        print(f"BLOCK — {len(problems)} problem(s):")
        for p in problems: print("  -",p)
        return 1
    print(f"SEALED — {len(rows)} parts verified (file+seq+filename+manifest), root {root[:16]}..., no orphans." + (f" [{pending} file(s) in _incoming pending intake — OK]" if pending else ""))
    return 0

if __name__=="__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv)>1 else "LOCK.tsv"))
