#!/usr/bin/env python3
"""host-genome off-target / recombination-homology scan.
Real NCBI blastn if installed (makeblastdb+blastn); else fast built-in seed
index: two linear passes (genome fwd + revcomp) of forward-query k-mers,
diagonal-grouped ungapped HSPs with % identity. Detects high-identity
(recombination-relevant, >~75%) homology; distant homologs (<~70%) need BLAST+
(auto-used if present). On-environment; no sequence leaves the machine.
Usage: blast_offtarget.py <query.fna> <genome.fna> [min_id=80] [min_len=40] [k=13]"""
import sys, shutil, subprocess, tempfile, os
from collections import defaultdict
def rc(s): return s.translate(str.maketrans("ACGTN","TGCAN"))[::-1]
def read_fasta(p):
    n=None;s=[]
    for l in open(p):
        if l.startswith(">"): n=l[1:].strip(); continue
        s.append("".join(c for c in l.strip().upper() if c in "ACGTN"))
    return n,"".join(s)
def real_blast(qp,gp,min_id,min_len):
    tmp=tempfile.mkdtemp(); db=os.path.join(tmp,"db")
    subprocess.run(["makeblastdb","-in",gp,"-dbtype","nucl","-out",db],check=True,capture_output=True)
    out=subprocess.run(["blastn","-query",qp,"-db",db,"-outfmt","6 sstart send length pident",
        "-perc_identity",str(min_id)],check=True,capture_output=True,text=True).stdout
    return [(int(f[2]),float(f[3]),int(f[0]),int(f[1]),"+") for f in
            (ln.split("\t") for ln in out.splitlines()) if int(f[2])>=min_len]
def fallback(query,genome,min_id,min_len,k):
    qidx=defaultdict(list)
    for qp in range(len(query)-k+1): qidx[query[qp:qp+k]].append(qp)
    n=len(genome); hsps=[]
    for st,G in (('+',genome),('-',rc(genome))):
        diags=defaultdict(list)
        get=qidx.get
        for i in range(len(G)-k+1):
            hl=get(G[i:i+k])
            if hl:
                for qp in hl: diags[i-qp].append((i,qp))
        for d,lst in diags.items():
            lst.sort(key=lambda x:x[1]); qs=lst[0][1]; qe=lst[-1][1]+k
            gs=lst[0][0]; ge=lst[-1][0]+k
            qseg=query[qs:qe]; gseg=G[gs:ge]
            if len(qseg)!=len(gseg) or len(qseg)<min_len: continue
            m=sum(1 for a,b in zip(qseg,gseg) if a==b); idp=100*m/len(qseg)
            if idp>=min_id:
                gc=(gs+1,ge) if st=='+' else (n-gs,n-ge+1)
                hsps.append((len(qseg),round(idp,1),gc[0],gc[1],st))
    hsps.sort(reverse=True); return hsps
if __name__=="__main__":
    qp,gp=sys.argv[1],sys.argv[2]
    min_id=float(sys.argv[3]) if len(sys.argv)>3 else 80.0
    min_len=int(sys.argv[4]) if len(sys.argv)>4 else 40
    k=int(sys.argv[5]) if len(sys.argv)>5 else 13
    qn,q=read_fasta(qp); gn,g=read_fasta(gp)
    eng="blastn(real)" if shutil.which("blastn") else f"seed-extend(fallback,k={k})"
    print(f"# q={qn[:40]} ({len(q)}bp) genome={gn[:30]} ({len(g)}bp) engine={eng} min_id={min_id}% min_len={min_len}")
    rows=real_blast(qp,gp,min_id,min_len) if shutil.which("blastn") else fallback(q,g,min_id,min_len,k)
    if not rows: print("NO host homology >= thresholds."); sys.exit(0)
    print(f"{'len':>6}{'%id':>7}{'g_start':>10}{'g_end':>10}  str")
    for r in rows[:25]: print(f"{r[0]:>6}{r[1]:>7}{r[2]:>10}{r[3]:>10}  {r[4]}")
