#!/usr/bin/env python3
"""
test_determinism.py — the engine's central claim, as an executable test.

The claim: **the same Design Spec plus the same sealed Parts Library always produce a
byte-identical construct.** If that is true, a construct is a *regenerable artifact*
rather than a file you have to trust, and a build can be audited by anyone who has the
Spec and the library.

This suite proves it five ways:

  1. ORACLE      Each Spec rebuilds to the exact sha256 recorded below. Those hashes are
                 not invented for the test — they are the sealed hashes of constructs this
                 team actually ordered from a synthesis vendor. `pAP-Logic` in particular
                 is the DNA that was synthesised. If the engine ever stops reproducing
                 these, it is no longer the engine that built our constructs.
  2. REPEATABLE  Building the same Spec twice in one session yields the same hash.
  3. PIN         A wrong --expect-root is REFUSED. Integrity checks that only pass are
                 worthless; this asserts the engine actually fails closed.
  4. TAMPER      A single flipped base in the manifest breaks the library root, and the
                 engine refuses to build against it.
  5. SBOL        The SBOL 3 export is valid UTF-8, reloads, revalidates, and the construct
                 hash recomputes from the SBOL file to the same seal. Publishing to a
                 standard must not cost you the ability to verify what you published.

Run:  python3 test_determinism.py            (uses the sibling parts-library)
      python3 test_determinism.py -v         (show each build)

Exit 0 = all passed. Non-zero = a failure, printed.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE / "katana_build.py"

# The engine prints box-drawing and status glyphs. On a default Windows console
# (cp1252) both writing them here and DECODING them from a subprocess raise
# UnicodeError. Force UTF-8 on both sides rather than depending on the locale.
for _stream in (sys.stdout, sys.stderr):
    try:
        if (_stream.encoding or "").lower().replace("-", "") != "utf8":
            _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def find_lock_root() -> "str | None":
    """Read the LOCK root of whichever Parts Library the engine will resolve.

    Deliberately NOT a hardcoded constant, and that is a correctness point rather
    than a convenience. This suite runs in at least two places: this published
    bundle, whose library is a curated SUBSET, and the maintainers' working tree,
    whose library is larger. Those two have different roots *by construction* -- the
    root is a hash over all manifest rows -- so pinning one of them here would make
    the suite fail for everyone who is not us.

    That is precisely the "works on my machine" failure the engine's own
    --expect-root flag exists to prevent, and it would be embarrassing to ship it
    inside the test that demonstrates the flag. (It was in fact written that way
    first, pinned to the private library's root, and caught by running the suite
    against a realistic bundle before release.)

    The CONSTRUCT hashes in ORACLES below are the real invariant. They are identical
    under both libraries, because the part *sequences* are identical; only the set of
    rows in the manifest differs.
    """
    for base in (HERE, *HERE.parents):
        candidate = base / "parts-library" / "ref_parts" / "LOCK.root"
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8").strip()
    return None


EXPECT_ROOT = find_lock_root()

# Sealed hashes of real, ordered constructs. Do not edit to make a test pass:
# a mismatch here means the engine changed, and that is exactly what this catches.
ORACLES = {
    "pAP-Logic":       "1d99b7be2c513b198b8236a271f58beee5ddcce5551ccc1a73fa25ac4bcd5b7a",
    "pAP-Output":      "e7d438289afe9869aeb7a9d03982c0c3067b4483ab900c33167bf1e28a507fab",
    "pAP-Report-dual": "eed71d277eeb8e49358739bf2e93a232cd42a691bfd09307bbf7c8b03026b42b",
    "pSense-Lac-dual": "9bc4a9168192fd6a6d2259e0ff30c475f6973d189e0a1ede60d45f759b7f89e3",
    "pSense-Lac-lacZ": "b7a30a45dd6c79f0027319ef02fe2effd77cc8c16395e34ed74ea5dd20e5048b",
    "pSense-Lac":      "a6adcf29f29844b15b9214337a2b91a52c8a60fdb1eda9f0e97ac3ade2060bdf",
    "pSense-Nit-dual": "f93cd75170773560aaf441a5e6ec19ab2beb7d82e009ad05d40bc673a9e0bb80",
    "pSense-Nit":      "796e94a0ea2452edd2ce59ca30b8f28fea232b37ab2a036714239069fd1196f5",
}

HASH_RE = re.compile(r"seq_sha256:\s*([0-9a-f]{64})")


def find_specs_dir(override: Path | None = None) -> Path:
    """Locate the Design Specs.

    In the published bundle `specs/` sits beside the engine. In this team's working
    tree it lives under `katana/specs/`. Check both, so the same test runs in both
    layouts without editing.
    """
    if override:
        if override.is_dir() and any(override.glob("*.spec.yaml")):
            return override
        sys.exit(f"BLOCK: --specs {override} has no *.spec.yaml files")
    for base in (HERE, *HERE.parents):
        for cand in (base / "specs", base / "katana" / "specs"):
            if cand.is_dir() and any(cand.glob("*.spec.yaml")):
                return cand
    sys.exit("BLOCK: cannot locate a specs/ directory containing *.spec.yaml "
             "(pass --specs PATH)")


def build(spec: Path, expect_root: str | None = EXPECT_ROOT,
          extra: list[str] | None = None,
          dry_run: bool = True) -> subprocess.CompletedProcess:
    # Most checks only need the computed hash, so they run --dry-run and write nothing.
    # The SBOL check needs real output files, so it opts out.
    cmd = [sys.executable, str(ENGINE), str(spec)]
    if dry_run:
        cmd.append("--dry-run")
    if expect_root:
        cmd += ["--expect-root", expect_root]
    cmd += extra or []
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def hash_of(proc: subprocess.CompletedProcess) -> str | None:
    m = HASH_RE.search(proc.stdout)
    return m.group(1) if m else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--specs", type=Path, default=None,
                    help="Directory of *.spec.yaml (default: auto-detect)")
    args = ap.parse_args()

    specs_dir = find_specs_dir(args.specs)
    print(f"Specs: {specs_dir}\n")
    failures: list[str] = []
    passed = 0

    # ── 1. ORACLE ───────────────────────────────────────────────────────────
    print("1. ORACLE — every Spec rebuilds to its sealed hash")
    for name, expected in sorted(ORACLES.items()):
        spec = specs_dir / f"{name}.spec.yaml"
        if not spec.exists():
            print(f"   SKIP {name} (spec not in this bundle)")
            continue
        got = hash_of(build(spec))
        if got == expected:
            passed += 1
            print(f"   PASS {name:<18} {expected[:16]}…")
        else:
            failures.append(f"ORACLE {name}: expected {expected[:16]}… got {str(got)[:16]}…")
            print(f"   FAIL {name:<18} expected {expected[:16]}… got {str(got)[:16]}…")

    # ── 2. REPEATABLE ───────────────────────────────────────────────────────
    print("\n2. REPEATABLE — same Spec twice, same hash")
    sample = next((specs_dir / f"{n}.spec.yaml" for n in ORACLES
                   if (specs_dir / f"{n}.spec.yaml").exists()), None)
    if sample:
        h1, h2 = hash_of(build(sample)), hash_of(build(sample))
        if h1 and h1 == h2:
            passed += 1
            print(f"   PASS {sample.stem:<18} {h1[:16]}… twice")
        else:
            failures.append(f"REPEATABLE: {h1} != {h2}")
            print(f"   FAIL {h1} != {h2}")

    # ── 3. PIN — a wrong pin must be REFUSED ────────────────────────────────
    print("\n3. PIN — a wrong --expect-root is refused")
    bad = "deadbeef" + "0" * 56
    proc = build(sample, expect_root=bad)
    if proc.returncode != 0 and "BLOCK" in (proc.stdout + proc.stderr):
        passed += 1
        print("   PASS wrong pin blocked the build")
    else:
        failures.append("PIN: a wrong --expect-root did NOT block the build")
        print(f"   FAIL wrong pin was accepted (rc={proc.returncode})")

    # ── 4. TAMPER — edit the manifest, the root must break ──────────────────
    print("\n4. TAMPER — one edited manifest row breaks the library root")
    lib = next((q / "parts-library" for q in (HERE, *HERE.parents)
                if (q / "parts-library" / "ref_parts" / "LOCK.tsv").exists()), None)
    if lib is None:
        print("   SKIP (no parts-library found)")
    else:
        with tempfile.TemporaryDirectory() as td:
            sandbox = Path(td) / "sandbox"
            sandbox.mkdir(parents=True)
            # Copy ONLY the parts library — never the enclosing tree. (An earlier
            # version copied lib.parent, which in a real project is the whole
            # repository: minutes of I/O and gigabytes of temp for a test that
            # needs one manifest.) ref_genomes is excluded: large, and unused here.
            shutil.copytree(lib, sandbox / "parts-library",
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "ref_genomes"))
            lock = sandbox / "parts-library" / "ref_parts" / "LOCK.tsv"
            if lock.exists():
                rows = lock.read_text(encoding="utf-8").splitlines()
                # Corrupt one row hash — the manifest is now internally inconsistent.
                for i, r in enumerate(rows[1:], start=1):
                    if "\t" in r:
                        cols = r.split("\t")
                        cols[-1] = ("0" * 64) if cols[-1] != "0" * 64 else "f" * 64
                        rows[i] = "\t".join(cols)
                        break
                lock.write_text("\n".join(rows) + "\n", encoding="utf-8")
                engine_copy = sandbox / "katana_build.py"
                shutil.copyfile(ENGINE, engine_copy)
                # Everything the engine needs to RUN, not just the engine. This list grew
                # when PyYAML was vendored: a sandbox missing _vendor/ made the engine exit
                # on "no YAML parser available" BEFORE it ever reached the LOCK.root check,
                # so this test reported "tampered manifest accepted" while the real cause was
                # an incomplete sandbox. A test that assembles a broken engine proves nothing
                # about the engine.
                for helper in ("katana_drylab.py", "blast_offtarget.py",
                               "katana_order_table.py", "katana_sbol.py", "vendor_path.py"):
                    if (HERE / helper).exists():
                        shutil.copyfile(HERE / helper, sandbox / helper)
                if (HERE / "_vendor").is_dir():
                    shutil.copytree(HERE / "_vendor", sandbox / "_vendor",
                                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                # Assert the sandbox can run at all before trusting what it says about
                # tampering. Without this the next assertion cannot tell "the engine refused
                # the tampered library" from "the engine could not start".
                sanity = subprocess.run(
                    [sys.executable, str(engine_copy), "--help"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace")
                if sanity.returncode != 0:
                    failures.append("TAMPER: the sandboxed engine could not start, so this "
                                    "check could not measure anything")
                    print("   FAIL sandboxed engine will not start — this check measured "
                          "nothing:\n     "
                          + (sanity.stdout + sanity.stderr).strip()[:300])
                else:
                    spec_copy = sandbox / "specs"
                    if not spec_copy.exists():
                        shutil.copytree(specs_dir, spec_copy)
                    target = spec_copy / sample.name
                    proc = subprocess.run(
                        [sys.executable, str(engine_copy), str(target), "--dry-run"],
                        capture_output=True, text=True,
                        encoding="utf-8", errors="replace")
                    out = proc.stdout + proc.stderr
                    if proc.returncode != 0 and "not self-consistent" in out:
                        passed += 1
                        print("   PASS tampered manifest refused (root no longer self-consistent)")
                    else:
                        failures.append("TAMPER: a corrupted LOCK row did NOT block the build")
                        print(f"   FAIL tampered manifest accepted (rc={proc.returncode})")

    # ── 5. SBOL — export must be valid, reloadable, and hash-faithful ───────
    print("\n5. SBOL — export is valid SBOL 3 and preserves hash verifiability")
    try:
        import sbol3  # noqa: F401
    except ImportError:
        print("   SKIP (sbol3 not installed — optional exporter)")
    else:
        import hashlib
        with tempfile.TemporaryDirectory() as td:
            ttl = Path(td) / "out.ttl"
            proc = build(sample, extra=["--outdir", td, "--sbol", str(ttl)],
                         dry_run=False)
            expected = hash_of(proc)
            if proc.returncode != 0 or not ttl.exists():
                failures.append("SBOL: export did not produce a file")
                print(f"   FAIL export failed (rc={proc.returncode})")
            else:
                raw = ttl.read_bytes()
                try:
                    # RDF/Turtle MUST be UTF-8. A locale-encoded file parses locally
                    # and fails everywhere else — assert bytes, not appearance.
                    raw.decode("utf-8")
                    doc = sbol3.Document()
                    doc.read(str(ttl))
                    errs = list(getattr(doc.validate(), "errors", []) or [])
                    seqs = [o for o in doc.objects if isinstance(o, sbol3.Sequence)]
                    # The construct sequence is the longest one in the document.
                    longest = max(seqs, key=lambda s: len(s.elements or ""))
                    got = hashlib.sha256((longest.elements or "").upper().encode()).hexdigest()
                    if errs:
                        failures.append(f"SBOL: {len(errs)} validation error(s) on reload")
                        print(f"   FAIL {len(errs)} validation error(s) on reload")
                    elif got != expected:
                        failures.append("SBOL: hash recomputed from SBOL != engine seal")
                        print(f"   FAIL hash from SBOL {got[:16]}… != seal {str(expected)[:16]}…")
                    else:
                        passed += 1
                        print(f"   PASS valid UTF-8, revalidates, hash recomputes to {got[:16]}…")
                except UnicodeDecodeError as e:
                    failures.append(f"SBOL: output is not valid UTF-8 ({e})")
                    print(f"   FAIL output is not valid UTF-8 ({e})")

    # ── verdict ─────────────────────────────────────────────────────────────
    print("\n" + "─" * 60)
    if failures:
        print(f"FAILED — {len(failures)} problem(s):")
        for f in failures:
            print(f"  {f}")
        return 1
    print(f"ALL PASSED — {passed} checks. The engine is deterministic and fails closed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
