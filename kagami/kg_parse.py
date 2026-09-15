"""
kg_parse.py — minimal, dependency-free FASTA / GenBank reader for Kagami.

Returns a Record: sequence (str, upper A/C/G/T/N), topology, and a list of
declared Features (the construct's *claims* about itself — label + role + span).
Kagami treats these claims as assertions to be checked, never as ground truth.
"""
import os
import re

_COMP = str.maketrans("ACGTNacgtn", "TGCANtgcan")


def revcomp(s: str) -> str:
    return s.translate(_COMP)[::-1]


class Feature:
    __slots__ = ("start", "end", "strand", "kind", "label")

    def __init__(self, start, end, strand, kind, label):
        self.start = start      # 1-based inclusive
        self.end = end          # 1-based inclusive
        self.strand = strand    # +1 / -1
        self.kind = kind        # feature key, e.g. CDS, promoter, RBS, terminator
        self.label = label      # human label / gene / product / note

    def span(self):
        return (self.start, self.end)


class Record:
    def __init__(self, name, seq, topology, features):
        self.name = name
        self.seq = seq
        self.topology = topology            # "circular" | "linear"
        self.features = features            # list[Feature]

    def sub(self, start, end):
        """1-based inclusive slice."""
        return self.seq[start - 1:end]


def _clean(seq: str) -> str:
    return "".join(c for c in seq.upper() if c.isalpha())


# feature keys we map onto Kagami roles for downstream audit
_ROLE_KEYS = {
    "promoter": "promoter",
    "rbs": "rbs",
    "ribosome_binding_site": "rbs",
    "cds": "cds",
    "gene": "cds",
    "terminator": "terminator",
    "misc_feature": "misc",
    "protein_bind": "misc",
}

_LABEL_QUALS = ("label", "gene", "product", "standard_name", "note")



# ── loose input: csv / tsv / xlsx / txt / pasted ────────────────────────────

_DNA_OK = set("ACGTUNRYKMSWBDHV")


def _dna_fraction(tok):
    if not tok:
        return 0.0
    up = tok.upper()
    return sum(1 for c in up if c in _DNA_OK) / len(up)


def _dna_tokens(cells, min_len=8, min_frac=0.9):
    """Cells that are plausibly DNA, in document order.

    min_frac is deliberately below 1.0: exports carry stray spaces, line breaks and the odd digit
    from a position ruler. It is high enough that prose, part names and dates do not qualify.
    """
    out = []
    for c in cells:
        tok = "".join(ch for ch in str(c) if not ch.isspace() and not ch.isdigit())
        if len(tok) >= min_len and _dna_fraction(tok) >= min_frac:
            out.append("".join(ch for ch in tok.upper() if ch.isalpha()))
    return out


def _xlsx_cells(path):
    """Cell text from an .xlsx, in sheet order. stdlib only - an xlsx is a zip of XML."""
    import zipfile
    import xml.etree.ElementTree as ET

    NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall(f"{NS}si"):
                shared.append("".join(node.text or "" for node in si.iter(f"{NS}t")))
        sheets = sorted(n for n in z.namelist()
                        if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"))
        cells = []
        for name in sheets:
            root = ET.fromstring(z.read(name))
            for c in root.iter(f"{NS}c"):
                v = c.find(f"{NS}v")
                if c.get("t") == "s" and v is not None:
                    try:
                        cells.append(shared[int(v.text)])
                    except (ValueError, IndexError):
                        pass
                elif c.get("t") == "inlineStr":
                    cells.append("".join(n.text or "" for n in c.iter(f"{NS}t")))
                elif v is not None and v.text:
                    cells.append(v.text)
    return cells


def _parse_loose(path, text=None) -> Record:
    """Last resort: find the DNA in whatever this file is."""
    if str(path).lower().endswith((".xlsx", ".xlsm")):
        cells = _xlsx_cells(path)
    else:
        cells = re.split(r'[,;\t\r\n"]+', text or "")
    pieces = _dna_tokens(cells)
    if not pieces:
        # One last try: the whole file might be bare bases with no delimiters at all.
        whole = "".join(ch for ch in (text or "") if ch.isalpha())
        if len(whole) >= 8 and _dna_fraction(whole) >= 0.95:
            pieces = [whole.upper()]
    rec = Record(os.path.basename(str(path)).rsplit(".", 1)[0], _clean("".join(pieces)),
                 "linear", [])
    # Surfaced by the CLI. Joining in the wrong order yields a different construct that would still
    # audit cleanly, so the join must be visible, never assumed.
    rec.assembled_from = [len(p) for p in pieces] if len(pieces) > 1 else []
    return rec

def parse(path: str) -> Record:
    """FASTA, GenBank, or whatever the student actually saved.

    Dispatch is on CONTENT, not on the extension, because a file called .txt is as likely to hold
    GenBank as anything else - and a beginner's ".csv" is often a sequence pasted into one cell.
    """
    if str(path).lower().endswith((".xlsx", ".xlsm")):
        return _parse_loose(path)                      # binary; do not read it as text
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    stripped = text.lstrip()
    if stripped[:1] == ">":
        return _parse_fasta(path, text)
    if "LOCUS" in text[:2000] or "\nORIGIN" in text:
        return _parse_genbank(path, text)
    # Not a format with a spec. Go and find the DNA.
    return _parse_loose(path, text)


def _parse_fasta(path, text) -> Record:
    name = "sequence"
    chunks = []
    for line in text.splitlines():
        if line.startswith(">"):
            name = line[1:].strip().split()[0] if line[1:].strip() else name
        else:
            chunks.append(line)
    seq = _clean("".join(chunks))
    return Record(name, seq, "linear", [])


_LOC_RE = re.compile(r"(complement\()?\s*<?(\d+)\.\.>?(\d+)\)?")


def _parse_location(loc):
    """Return (start, end, strand) for simple/complement/join spans (1-based)."""
    strand = -1 if "complement" in loc else 1
    coords = re.findall(r"(\d+)\.\.(\d+)", loc)
    if not coords:
        one = re.findall(r"(\d+)", loc)
        if not one:
            return None
        p = int(one[0])
        return (p, p, strand)
    starts = [int(a) for a, _ in coords]
    ends = [int(b) for _, b in coords]
    return (min(starts), max(ends), strand)


def _parse_genbank(path, text) -> Record:
    lines = text.splitlines()

    # name + topology from LOCUS
    name, topology = "sequence", "linear"
    for ln in lines:
        if ln.startswith("LOCUS"):
            parts = ln.split()
            if len(parts) >= 2:
                name = parts[1]
            if "circular" in ln.lower():
                topology = "circular"
            break

    # sequence from ORIGIN..//
    seq_lines, in_origin = [], False
    for ln in lines:
        if ln.startswith("ORIGIN"):
            in_origin = True
            continue
        if in_origin:
            if ln.startswith("//"):
                break
            seq_lines.append(ln)
    seq = _clean("".join(seq_lines))

    # features
    features = []
    in_feat = False
    cur_kind = None
    cur_loc = ""
    cur_quals = {}

    def flush():
        if not cur_kind:
            return
        loc = _parse_location(cur_loc)
        if not loc:
            return
        role = _ROLE_KEYS.get(cur_kind.lower(), cur_kind.lower())
        label = ""
        for q in _LABEL_QUALS:
            if q in cur_quals and cur_quals[q]:
                label = cur_quals[q]
                break
        features.append(Feature(loc[0], loc[1], loc[2], role, label))

    for ln in lines:
        if ln.startswith("FEATURES"):
            in_feat = True
            continue
        if not in_feat:
            continue
        if ln.startswith("ORIGIN") or ln.startswith("//"):
            flush()
            break
        # feature key line: 5 spaces, key in cols ~6-20, then location
        if len(ln) > 5 and ln[5] != " " and not ln.lstrip().startswith("/"):
            flush()
            cur_kind = ln[5:21].strip()
            cur_loc = ln[21:].strip()
            cur_quals = {}
        elif ln.lstrip().startswith("/"):
            m = re.match(r'\s*/([^=]+)=?"?([^"]*)"?', ln)
            if m:
                cur_quals[m.group(1).strip().lower()] = m.group(2).strip()
        elif cur_kind and cur_loc and ln.strip() and not cur_quals:
            # location continuation (join spanning lines)
            cur_loc += ln.strip()

    return Record(name, seq, topology, features)
