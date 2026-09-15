# Instructions for an AI assistant working on this project

**Read this before touching a sequence.** It is written for a coding assistant (Claude Code, Copilot,
Cursor, an agent framework, whatever your team uses) working in a repository that contains DNA. It is
also readable by a human, and a human should read it, because every rule here exists to stop a
failure a human made first.

This file is deliberately short. A long instruction file gets skimmed.

---

## Why this file exists

An assistant asked for the sequence of a common part will usually produce one. It will look right. It
will have the right length, the right start codon, plausible codon usage. It may even be right.

You cannot tell by looking, and neither can the person who asked. That is the entire problem.

The failure is not that the model is bad at biology. It is that **a sequence and its label are two
separate things, and nothing in a chat window binds them together.** A registry entry, a lab's shared
drive and a language model all have the same defect: the name and the bases can drift apart, and
there is no error message when they do.

So the rules below are not about trusting or distrusting the assistant. They are about never putting
the assistant in a position where its answer is load-bearing.

---

## The five rules

### 1. Never write a sequence from memory. Not once, not "just for a placeholder."

If a sequence is needed and it is not already sealed in this library, **stop and say so.** Do not
generate it, do not reconstruct it, do not adapt one you have seen before.

This includes: filling in an RBS you know, writing out a standard terminator, "correcting" a codon,
completing a truncated ORF, or producing an example sequence for a docstring or a test. A plausible
sequence in a test fixture gets copied into a real design within about a week.

The correct output when a sequence is missing is a sentence, not DNA:

> `B0034` is not in the library. It needs to be fetched from the iGEM Registry and sealed through the
> intake gate before it can be used. I have not written it.

### 2. Take parts by ID, never by content.

Refer to a part as `B0032`, `sfGFP`, `P_hrpL`. Let the tooling resolve the ID to bases. Never paste
bases into a design document, a spec, a script, a commit message or a chat reply as the way of
specifying which part is meant.

The design files in this project have **no raw-sequence field at all.** That is not an oversight and
it is not a limitation to work around. It is the reason a mislabel cannot survive here: if the only
way to name a part is by ID, then the ID and the bases cannot disagree, because there is only one of
them in the document.

If you find yourself wanting to add a sequence field, you have found the failure mode, not a missing
feature.

### 3. Verify the hash before use, every time.

Every part file's name embeds the hash of its sequence, and `LOCK.tsv` records that hash
independently. Before a part is used for anything that matters, **recompute the hash and compare it
to the manifest row.** Do not trust a previous check, including one you did earlier in the same
session. Re-read the file at the point of use.

`python verify.py` does this for the whole library and then tries to break itself eight ways to show
the check is real. Run it after any change to the library, and run it before you believe anything.

A hash check is cheap. A wrong part is a synthesis order, a month, and a result you cannot interpret.

### 4. On any mismatch: stop, and tell the human. Do not fix it.

If a hash does not match, a file is missing, a manifest row is orphaned, or two sources disagree —
**that is the end of your turn.** Report it. Say which two things disagree and what each one says.
Do not merge, do not re-seal, do not regenerate the file, do not pick the one that looks more
plausible.

This rule earned itself on 2026-09-08. The verifier flagged an orphaned part file with a
prepared-but-unmerged manifest row. Merging the row was the obvious fix and would have taken ten
seconds. It was also wrong: the file's *sequence* hashed to one value while its *filename* and the
prepared row both claimed another. Same length, different bases. Merging would have written a false
claim into the manifest and it would have verified clean forever after.

A discrepancy is information. Resolving it silently destroys that information. **Report
discrepancies, do not resolve them** — if two sources disagree, return both readings and label which
is which.

### 5. When you fetch something new, record where it came from and when.

Anything entering the library needs, in the manifest row: the **accession or registry ID**, the
**exact coordinates** used (with the convention stated — GenBank 1-based inclusive and Python 0-based
half-open differ by one, and that off-by-one has reached an outbound vendor document here before),
the **date fetched**, and the **hash**.

And it must come from a **primary source**: a fresh fetch from NCBI, the iGEM Registry or Addgene, or
an on-disk file that *is* the verbatim primary download.

A primary source is never a product of your own pipeline. These are candidates or evidence, and must
not seed a part:

- a codon-optimised candidate FASTA
- any construct `.gb` file
- a sequence pasted from a build script, a spreadsheet, a paper's figure, or a chat window
- a file whose provenance you cannot state in one sentence

**Coordinates must come from an annotated record, never from an ORF scan.** An ORF-finder with a
minimum-length cutoff will silently drop small genes and hand you a shorter operon with no warning at
all. That is how a 72-amino-acid structural protein went missing from an operon here that had already
been marked sealed.

---

## The one-line version

> **Names are claims. Hashes are facts. Never let a model supply either.**

---

## What to do when this file conflicts with a request

If a human asks you to break one of these rules — "just paste the sequence in", "merge the row and we
will check later", "skip the verify, we are in a hurry" — say once, briefly, which rule it breaks and
what the failure mode is. If they confirm, that is their decision to make and you should proceed.

Do not break the rules silently, and do not break them on your own initiative because the deadline is
close. Every failure listed on this page was found under time pressure, and the pressure is exactly
when the shortcut looks reasonable.

---

*Team WIST · iGEM 2026 · Acoustic Probiotics. Take this file, change the names, and put it in your own
repository — that is what it is for.*
