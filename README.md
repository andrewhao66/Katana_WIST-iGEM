# A parts library you can check, and the rule that keeps it honest

**Team WIST · iGEM 2026 · Acoustic Probiotics**

Five things went wrong for us before we built this. All five are the same failure wearing different
clothes: **a sequence and its label drifted apart, and nothing said so.**

| | What happened | Caught by |
|---|---|---|
| 1 | A part labelled `B0032` in two constructs carried the **`B0034`** sequence — three times the translation rate we had designed for | A second verification pass, days before signing a synthesis order |
| 2 | An ORF-finder with a minimum-length cutoff silently dropped a **72-amino-acid GvpA** from a 16.5 kb operon. The construct was already marked *sealed* | Diffing against the **annotated** reference — not against the raw file the extraction came from |
| 3 | A 0-based Python slice was written down as a 1-based coordinate. **Off by one**, and it had already reached an outbound vendor document | Someone re-measuring the span by hand and getting a different number |
| 4 | **Three copies** of one construct existed. Two were stale. One of the stale ones had the *exact same filename* as the sealed one; another was missing GvpA entirely | Asking "where are the current constructs?" and counting the answers |
| 5 | A part file named `…__47c4687cca62.gb` contained a sequence that hashes to `3c840d2b…`. Same length, different bases | The verifier in this bundle — on the day we proposed publishing the library |

None of these are exotic. They are the normal condition of a Registry part, a lab's shared drive, and
increasingly of anything an AI assistant hands you.

Failure 2 is worth a second look, because the first attempt to catch it *passed*. The build script
verified the extracted operon against the file the operon had been extracted from. It was checking
its own homework, and a self-consistent wrong answer is indistinguishable from a right one. The check
only worked when it was pointed at an independent, annotated source.

This is what we did about it.

---

## Run it

Download, unzip, and from a terminal in that folder:

```
./katana
```

It asks what you want to do. **Nothing needs installing beyond Python 3.9 or newer** — no
`pip`, no NCBI BLAST+, no genome download.

If you already know what you want:

```
./katana check someones-plasmid.gb      is this sequence what its labels say?
./katana build my-design.spec.yaml      Design Spec → order-ready sequence
./katana verify                         check the library, then try to break the checker
./katana gui                            the same things, with buttons
./katana web                            the sequence check, in a browser
```

On Windows it is `katana.bat` instead of `./katana`.

### Or use it in a browser, with nothing installed at all

```
./katana web
```

That starts a local server and opens a page you can drop a file onto. The audit runs
**inside the browser** — Katana's own modules, unmodified, through Pyodide — so the
sequence never leaves your machine. Useful on a school computer where you cannot install
anything, and on a Chromebook.

It needs the local server rather than just opening the file, because a browser refuses to
let a `file://` page fetch its own files. One command avoids that.

The same page can be published as a static site with `./katana deploy`; it stages by
default and only publishes with `--push`.

### On a Mac, run it from Terminal — do not double-click

macOS refuses to open a downloaded script that is not code-signed, and this one is not. Every
browser marks a downloaded file as quarantined, and Gatekeeper then blocks it; the
"Right-click → Open" trick that used to get past that was removed in macOS 15.

That block applies to **double-clicking only**. A script a shell runs is unaffected, because
what the system actually launches is the signed `/bin/bash`. So open Terminal, type `bash `
(with the trailing space), drag the file onto the window, and press Return.

Nothing is wrong when you see that dialog, and nothing you did caused it. It is also why every
command in this README is written to be run in a terminal rather than clicked.

### Start with `./katana verify`

It checks every part in this library against its manifest, then **deliberately corrupts a
scratch copy eight ways to prove the checker would have caught it.**

The second half is the point. Anyone can print "verified".

---

## Reproduce the results

**Build a construct.** A Design Spec plus the sealed library produce an annotated GenBank file, an
order-ready FASTA, an order table and a sequence hash:

```
./katana build specs/pSense-Nit.spec.yaml
```

Add `--sbol out.ttl` for SBOL 3, `--dry-run` to check without writing, `--json` to get the whole
result as data instead of text, and `--expect-root <sha256>` to bind the build to one exact
library state.

**Reproduce the main results.** This is the claim worth checking, so check it:

```
python3 test_determinism.py
```

It rebuilds every Spec in `specs/` and asserts each one reproduces a **recorded hash of a construct
we actually ordered from a synthesis vendor** — then confirms a repeat build matches, a wrong
`--expect-root` is refused, an edited manifest row is refused, and the SBOL export reloads and
still hashes to the same seal. Expect `ALL PASSED` in under a minute.

If those hashes stop reproducing, this is no longer the engine that built our DNA, and the suite
says so rather than letting it pass quietly.

**The optional extras.** Two checks need a package that is not bundled: the codon-quality gate
needs `python-codon-tables`, and SBOL export needs `sbol3`. Without them the engine still builds
and still audits — it tells you, loudly, which checks it therefore did not run, because a silent
skip would be worse than no check at all. If you want them:

```
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-optional.txt
```

That was once the *first* step rather than an optional one, and it is worth saying why it moved.
The old instructions opened with `pip install -r requirements.txt`, which pulled fifteen packages
including an OWL reasoner, and then asked for a 400 MB BLAST+ download and a `PATH` edit. Every
member of this team who tried to follow it failed. The YAML parser is now vendored in
`_vendor/yaml/` and part identification is pure Python, so there is nothing left to install.

---

## Turning on the off-target check

A build prints this until you give it a genome:

```
WARN  Stage-4b: OFF-TARGET SKIPPED - no genome for host 'E_coli_MG1655'. NOT enforced this run.
```

That check compares your construct against the whole genome of the organism you are putting it
into, looking for long high-identity stretches no intended part explains - a misassembly, the wrong
part, or a recoded gene drifting back toward the natural one. It needs a genome, and none ships
here. Genomes are large (*E. coli* ~4.6 MB, yeast ~12 MB) and, more to the point, there is no
correct set to bundle: whichever handful we picked would be the wrong one for the team working in
*Vibrio*, or cyanobacteria, or something we never thought of. So fetch the one you actually use:

```
./katana genome
```

A menu of 23 organisms with download sizes; type one letter. The list follows the **iGEM White
List** - the Risk Group 1 bacteria, the two permitted fungi, disarmed *Agrobacterium*, and all
seven named bacteriophages. Check the White List yourself before relying on it: it changes, and a
genome being downloadable here says nothing about what your division or institution permits.

The check itself is pure Python and needs nothing installed. It is a seed-and-extend scan,
good enough to catch a long high-identity host match that no intended part explains — which is
the misassembly signal it is there for — and not a substitute for a real alignment tool in a
publication. If you happen to have NCBI BLAST+ on your `PATH`, `kagami.py audit --deep` will
also use it for gapped, distant-homology search; nothing requires it.

Not on the list, or want to scan against a plasmid rather than a chromosome? Any NCBI accession
works. Replace all three capitalised words - pasted unchanged it refuses rather than downloading
something you did not choose:

```
./katana genome --accession YOUR_ACCESSION --name a_name --key YourHost
```

`YOUR_ACCESSION` is the identifier on the NCBI record (pUC19 is `M77789.2`), `a_name` is the
filename you want, and `YourHost` **must equal the `host` field in your Design Spec** - that is how
the check finds it. Genomes are fingerprinted and their accession and date recorded, exactly like a
part, so you can still prove a year from now which sequence a check ran against.

## Using it for your own project

**Your library is yours.** You never add parts to the one in this repository; it stays sealed so it
can go on being the reference you verified.

**1. Make your own library.**

```
./katana init my-project
```

An empty manifest with a correct starting fingerprint, a folder for your host genome, and a
commented Spec template.

**2. Find the part you want.** You rarely have an accession in your head. You have a decision - "I
need the lactate-responsive repressor from *E. coli*" - and turning that into coordinates is dull,
mechanical work where mistakes are easy and invisible:

```
./katana find lldR
```

It checks your own library first and stops if the part is already there. Otherwise it searches NCBI
and prints each candidate with organism, coordinates, strand and length, followed by the exact
`add_part.py` command. When several strains match a common gene name it says so and explains why
that matters - a part from the wrong strain survives all the way to a synthesis order. When only
one matched, it does not warn you about ambiguity that did not happen.

`--seal` prints the block to paste into a Spec for a part you already hold. `--search-anyway`
searches NCBI even when you have the part, which is how you find out the public record changed
since you sealed your copy. `./katana find --have` lists the thirty parts already here.

**3. Put it in your library.** A part enters one way: from its primary source, checked, written
once, fingerprinted, recorded with where it came from.

Already sealed here (`B0015`, `B0032`, `J23116`, `sfGFP`, `P_hrpL`, `p15A`, `cat`, `KanR` and
more)? Copy it rather than fetching a second, slightly different version:

```
./katana add --library my-project/parts-library --from parts-library/ref_parts --id B0015
```

The copy re-reads and re-hashes the file rather than trusting the row it came from, and refuses if
the source library disagrees with itself.

From NCBI:

```
./katana add --library my-project/parts-library --id lacZ --accession NC_000913.3 --range 363231..366305 --strand -
```

Designed yourself, or saved from a Registry page - point it at a local file:

```
./katana add --library my-project/parts-library --id my_rbs --file my_rbs.fasta --class designed
```

From the iGEM Registry, which needs no account:

```
./katana add --library my-project/parts-library --registry BBa_B0015
```

That records the part's **uuid** alongside its sequence - an identity check independent of the
fingerprint, saying the Registry means *that record*, not merely something with the same bases -
and the Sequence Ontology term, so `BBa_B0015` arrives noted as `SO:0000141 Terminator`.

Each command prints the exact `seal:` block to paste into your Spec, so you never copy a
fingerprint by hand. Add `--expect-length` when you know how long the part should be and want a
wrong accession refused rather than sealed.

---

## The rule worth stealing

**A part enters the library only from its primary source.**

You can adopt this today, with none of this software, using a text file and some discipline. It is
the part that actually prevented our failures; everything else here is just enforcement.

A primary source is a fresh fetch from NCBI, the iGEM Registry or Addgene, or an on-disk file that
*is* the verbatim primary download. **A primary source is never a product of your own pipeline.**
These are candidates or evidence, and must not seed a part:

- a codon-optimised candidate FASTA
- any construct `.gb` file
- a sequence pasted from a build script, a spreadsheet, a paper's figure, or a chat window
- a file whose provenance you cannot state in one sentence

### The checklist, runnable by hand

For each part, before it is allowed to exist in your project:

1. **Fetch it from the primary source.** Write down the accession or Registry ID.
2. **Write down the coordinates you used, and which convention.** GenBank is 1-based inclusive;
   Python slicing is 0-based half-open. They differ by one. That off-by-one is failure 3 above, and
   it travelled as far as a vendor's inbox.
3. **Take boundaries from an annotated record, never from an ORF scan.** A length cutoff drops small
   genes with no warning. That is failure 2.
4. **Hash the sequence and put the hash in the filename.** Then a renamed file is caught by
   inspection, and a re-fetched-but-not-re-sealed file is caught by recomputation. That is failure 5.
5. **Record the date.** Sources change under you.
6. **Never edit a sealed part in place.** Add a new version with a new hash and keep the old row.
7. **Refer to the part only by ID from then on.** If a design document has no field where a raw
   sequence can be written, a mislabel is structurally impossible rather than merely unlikely. That
   is failure 1, and it is the single highest-value change on this list.

That is the whole method. Seven lines and a hashing tool you already have.

---

## What is in here

| Part | Class | Length | Source |
|---|---|---|---|
| `HrpR.Ec-opt` | designed | 945 | designed codon-opt; parent=NCBI protein YET37120; host=E_co... |
| `HrpS.Ec-opt` | designed | 909 | designed codon-opt; parent=NCBI protein YET37121; host=E_co... |
| `HrpS.Ec-opt` | designed | 909 | designed codon-opt v2; parent=NCBI protein YET37121; host=E... |
| `HrpS.Ec-opt` | designed | 909 | designed codon-opt v3; tool=optimize-codons(DNAChisel: Codo... |
| `RBS_hrpR` | designed | 36 | designed synthesised 5'UTR; tool=design-rbs; engine=OSTIR(R... |
| `RBS_hrpR` | designed | 36 | designed synthesised 5'UTR; tool=design-rbs; engine=OSTIR 1... |
| `RBS_hrpS` | designed | 37 | designed synthesised 5'UTR; tool=design-rbs; engine=OSTIR(R... |
| `RBS_hrpS` | designed | 39 | designed synthesised 5'UTR; tool=design-rbs; engine=OSTIR 1... |
| `RBS_lacZ_weak` | designed | 18 | designed RBS element; parent=B0032 (BBa_B0032 weak core) + ... |
| `RBS_lldR_strong` | designed | 38 | designed synthesised 5'UTR; tool=design-rbs; engine=OSTIR 1... |
| `RBS_lldR_strong` | designed | 39 | designed synthesised 5'UTR; tool=design-rbs; engine=OSTIR 1... |
| `RBS_lldR_strong` | designed | 39 | designed synthesised 5'UTR; tool=design-rbs; engine=OSTIR 1... |
| `RBS_sfGFP_med` | designed | 18 | designed RBS; tool=OSTIR-ladder(local); engine=OSTIR 1.1.3 ... |
| `ALPaGA` | reference | 352 | Addgene #175272 :844..1195(+) ALPaGA LldR/lactate-responsiv... |
| `AxeTxe` | reference | 840 | Addgene #192473 (verbatim primary deposit sequence-376957.g... |
| `B0015` | reference | 129 | iGEM Registry BBa_B0015 (double terminator B0010-B0012; uui... |
| `B0032` | reference | 13 | iGEM Registry BBa_B0032 (RBS.3 weak; uuid dd29b240-f03a-42c... |
| `bARGSer_operon` | reference | 16474 | Addgene #192473 (pBAD-bARGSer-AxeTxe; verbatim primary depo... |
| `cat` | reference | 660 | NCBI V00622:244..903 (Tn9 cat CDS) |
| `ECK120033736` | reference | 53 | terminator; canonical from Cello Eco1C1G1T1 UCF (CIDARLAB/C... |
| `J23116` | reference | 35 | iGEM Registry BBa_J23116 (constitutive promoter family, And... |
| `KanR` | reference | 795 | NCBI AY048743.1 (pKD4) 459..1253(+); aminoglycoside 3'-phos... |
| `L3S2P55` | reference | 57 | terminator; canonical from Cello Eco1C1G1T1 UCF (CIDARLAB/C... |
| `lacZ` | reference | 3075 | NCBI NC_000913.3:363231-366305(-) |
| `lldR` | reference | 777 | NCBI NC_000913.3:3779054..3779830(+) lldR (b3604, DNA-bindi... |
| `p15A` | reference | 913 | NCBI X06403:581..1493 (pACYC184 p15A rep_origin) |
| `P_hrpL` | reference | 208 | iGEM Registry BBa_K4907019 (pHrpL); sigma54 HrpR+HrpS-activ... |
| `pSC101_ori` | reference | 1701 | NCBI NC_002056.1 (E. coli plasmid pSC101, complete sequence... |
| `PyeaR` | reference | 162 | NCBI NC_000913.3:1879946-1880107(-) |
| `sfGFP` | reference | 720 | iGEM Registry BBa_I746916 (superfolder GFP CDS; Pedelacq 20... |

Every row in `parts-library/ref_parts/LOCK.tsv` carries the accession and coordinates it came from,
the date it was sealed, and three hashes: of the sequence, of the file, and of the manifest row
itself. `LOCK.root` is a hash over all the rows, so the manifest cannot be edited without saying so.

These are the 30 parts that the Design Specs in `specs/` actually resolve to, plus four
reference parts we chose to include for their own sake (the reporter operon, its stability cassette,
a marker and an origin). It is a subset of a larger working library, not a general collection, and we
are not claiming they are good parts — only that each one is demonstrably the sequence its accession
says it is.

The subset is derived, not hand-picked: it is computed from the part IDs the published Specs name,
so a part we do not publish a Spec for is not published either. That rule is what makes the omissions
boring instead of a judgement call, and it is worth copying if you ever export part of a library.

The seven files in `specs/` are our real Design Specs, the documents that describe each construct as
an **ordered list of part IDs plus intent** — host, backbone, assembly method, constraints. Read one
and notice what is missing: there is nowhere to put a sequence. They are included as worked examples
of the format, because the format is the idea.

And `katana_build.py` is the engine that turns one into a construct: it resolves each part id against
the library, **re-hashes every part as it reads it**, assembles in the Spec's order, validates
junctions and restriction sites, optionally runs a host off-target and codon-quality gate, then seals
the result and writes GenBank, FASTA and SBOL 3. Every stage is a hard stop rather than a warning.
`ARCHITECTURE.md` explains how it fits together and where to extend it.

The engine is the same one that produced the constructs this team ordered — not a cleaned-up
demonstration version. `test_determinism.py` is what proves that, by rebuilding them.

---

## An instruction file for your AI assistant

`AGENTS.md` (shipped also as `CLAUDE.md`, since assistants look for one name or the other) is a short
set of rules for a coding assistant working in a repository that contains DNA:

- never write a sequence from memory, not even as a placeholder or a test fixture
- take parts by ID, never by pasted content
- verify the hash at the point of use, not once per session
- on any mismatch, **stop and tell the human** — do not merge, do not re-seal, do not pick the more
  plausible one
- when fetching something new, record accession, coordinates, convention, date and hash

We wrote it because the assistants we use are good at producing a sequence that looks right, and
neither we nor they can tell by looking. Rule 4 is the one that earned itself: failure 5 above came
with a prepared manifest row sitting right next to it, and merging that row was a ten-second obvious
fix that would have written a false claim into the manifest permanently.

Copy the file, change the names, drop it in your repository.

---

## What this does not do

- **It does not design anything for you.** No sequence generation, no optimisation. It will not
  choose your parts, optimise your codons, or tell you whether your circuit is a good idea. Those
  are your decisions, and the Spec is where you record them. What it does is check that what you
  think you have is what you actually have.
- **It is not an assembly planner.** It builds the order the Spec states. The Gibson fragment split
  is a worked example with a single overlap parameter, not a strategy chooser. If you need a
  different assembly route, you decide it and encode it in the Spec.
- **It does not replace sequencing.** It verifies the design side, before any DNA exists. Circuit-seq
  and similar tools verify the physical DNA afterwards. They answer different questions and you want
  both.
- **The test suites test the software, not your biology.** `verify.py` corrupting a library eight
  ways proves tampering is caught; `test_determinism.py` proves builds are reproducible and fail
  closed. Neither tells you whether your construct will work at the bench.

---

## Licence

Code is **Apache License 2.0** (see `LICENSE`). Team-authored content — this README, `ARCHITECTURE.md`,
`AGENTS.md` — is **CC BY 4.0**. The sequences are third-party and carry their source's terms; each
accession is recorded in `LOCK.tsv`. See `LICENSE.md` for how the three fit together.

Built by Team WIST for iGEM 2026. If it saves you one mislabelled part, it has paid for itself.
