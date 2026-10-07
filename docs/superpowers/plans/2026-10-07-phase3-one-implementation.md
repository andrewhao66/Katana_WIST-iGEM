# Phase 3: One Implementation, Three Renderers — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `build()` return a structured `BuildResult`, stop the GUI greping the engine's prose, and give the whole project one front door with an interactive menu, so that nobody has to choose between thirteen entry points or memorise fifty-five flags.

**Architecture:** `core/result.py` defines the result objects. `katana_build.build()` becomes a function returning one, with the CLI as a renderer over it rather than the only way to run it. `--json` serialises the same object. The GUI calls the function; `kg_verdict.classify()` — which greps stdout for `BLOCK`, `SEALED` and `NOT enforced` — becomes a fallback for the subprocess path and is no longer how the window learns what happened. A new `katana` entry point dispatches subcommands and, with no arguments, asks one question at a time.

**Tech Stack:** Python 3.9+, standard library plus the vendored YAML parser. `core/result.py` must stay Pyodide-clean like the rest of `core/`.

**Spec:** `docs/superpowers/specs/2026-10-07-katana-unification-design.md` — migration steps 4, 5 and 6 (§6, §7.1, §7.2).

## Global Constraints

- Python 3.9+. No `match`, no runtime `X | Y` unions, no `dataclasses` features newer than 3.9.
- `core/` stays stdlib-only and imports none of its consumers. `tests/test_one_core.py` enforces this.
- Verdict tokens `PASS` `FLAG` `FAIL` `REVIEW` `NOTE` `SKIP` `BLOCK` `SEALED` are API. A renderer may add words around them; it may not rename them.
- The engine's **stdout format stays backward-compatible**: `test_determinism.py` greps `seq_sha256:\s*([0-9a-f]{64})`, `kg_rebuild` greps `.gb:` / `.fasta:` / `.csv:` / `Output:`, and `kg_verdict.classify` greps `BLOCK` / `SEALED:` / `NOT enforced`. Those consumers migrate to `BuildResult` in this phase, but the printed lines remain so that an external script, or a user reading a log, is not broken.
- All 7 ORACLE construct hashes must reproduce at every step.
- Baseline to hold green, with nothing installed and `blastn` hidden: `tests/test_core_lock.py` 27/0, `tests/test_engine_gates.py` 10/0, `tests/test_one_core.py` 6/0, `verify.py` 8/8, `test_determinism.py` ALL PASSED 10, `kagami/tests.py` 91/0, `kagami/test_identify.py` 58/0.
- Every task ends in a local commit on branch `unify`. **Nothing is pushed to `origin` (GitLab).**

## Review Focus

Five conditions a reasonable person will meet that no existing test exercises.

1. **`./katana` with no arguments on a machine with no TTY** — a double-click, a CI step, or a pipe. `input()` raises `EOFError`, and the menu must print how to use the subcommands instead of a traceback. → Task 5.
2. **The menu offered a choice the machine cannot do** — "Open the window" where tkinter is absent, which is common on a minimal Linux. It must say so and stay in the menu rather than crashing. → Task 5.
3. **A `--json` consumer meeting a BLOCKed build** — the JSON must still be valid and say which stage refused and why, because a wrapper that gets a traceback on stderr and no JSON cannot report anything. → Task 2.
4. **The GUI's Build tab on a Spec that BLOCKs** — the verdict must read FAIL and name the blocking stage, which is what the greped `BLOCK` line used to supply. → Task 4.
5. **A Spec whose `architecture.order` names a part absent from `parts:`** — `assemble_insert` exits with a message; through `build()` that must become a `BuildResult` with a FAIL, not a `SystemExit` escaping into a GUI worker thread. → Task 2.

## File Structure

| File | Responsibility |
|---|---|
| `core/result.py` | **Create.** `Finding`, `StageResult`, `BuildResult`: the structured outcome of a build, with `verdict`, `to_dict()` and the stage records. |
| `tests/test_build_result.py` | **Create.** The RED tests for Tasks 1–3. |
| `katana_build.py` | **Modify.** `build(spec_path, library, opts) -> BuildResult`; `main()` renders it; `--json` serialises it. |
| `kagami/kg_verdict.py` | **Modify.** `from_result(BuildResult)` alongside the existing `classify(rc, out, dry)`, which stays for the subprocess path. |
| `kagami/kg_katana_tabs.py` | **Modify.** The Build tab reads a `BuildResult`. |
| `katana` / `katana.bat` | **Create.** The single entry point. |
| `ui_menu.py` | **Create.** The interactive menu: one question at a time, with defaults. |
| `tests/test_entry.py` | **Create.** The RED tests for Tasks 5–6. |

---

## Task 1: `core/result.py`

**Files:**
- Create: `core/result.py`
- Create: `tests/test_build_result.py`

**Interfaces:**
- Produces:
  - `core.result.Finding(category, status, summary, loc="", detail="", fix="")` with `.to_dict()`
  - `core.result.StageResult(name, ok, findings=None, data=None)` with `.to_dict()`
  - `core.result.BuildResult()` with `.stage(name) -> StageResult|None`, `.add(StageResult)`,
    `.verdict -> "PASS"|"REVIEW"|"FAIL"`, `.exit_code -> int`, `.to_dict()`,
    and the attributes `construct_id`, `version`, `insert_len`, `seq_sha256`, `outputs` (dict), `features` (list), `consumed` (dict).
  - `core.result.PASS`, `FLAG`, `FAIL`, `NOTE`, `SKIP` — the same five tokens `kg_audit` uses, so one vocabulary spans both directions.

- [ ] **Step 1: Write the failing test**

Create `tests/test_build_result.py`:

```python
"""Tests for core.result. Run: python3 tests/test_build_result.py"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from core import result as R

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  [" + detail + "]") if detail else ""))


print("core.result")

# The five tokens are the SAME vocabulary the reverse auditor already uses, so one
# verdict language spans both directions rather than two that must be kept in step.
check("the five status tokens exist and are the audit's own",
      (R.PASS, R.FLAG, R.FAIL, R.NOTE, R.SKIP) ==
      ("PASS", "FLAG", "FAIL", "NOTE", "SKIP"))

# ---- verdict roll-up: any FAIL beats any FLAG beats notes ----
_r = R.BuildResult()
check("an empty result is PASS", _r.verdict == "PASS", _r.verdict)
check("and exits 0", _r.exit_code == 0, str(_r.exit_code))

_r.add(R.StageResult("validate", True, [R.Finding("gc", R.PASS, "GC 51.2%")]))
check("a PASS finding keeps the verdict PASS", _r.verdict == "PASS", _r.verdict)

_r.add(R.StageResult("drylab", True, [R.Finding("offtarget", R.NOTE, "a note")]))
check("a NOTE does not hold back PASS", _r.verdict == "PASS", _r.verdict)
check("but it is counted", _r.count(R.NOTE) == 1, str(_r.count(R.NOTE)))

_r.add(R.StageResult("drylab", True, [R.Finding("cai", R.SKIP, "not run")]))
check("a SKIP does not hold back PASS either", _r.verdict == "PASS", _r.verdict)

_r.add(R.StageResult("validate", True, [R.Finding("hp", R.FLAG, "homopolymer 11")]))
check("a FLAG makes the verdict REVIEW", _r.verdict == "REVIEW", _r.verdict)
check("and REVIEW exits 5", _r.exit_code == 5, str(_r.exit_code))

_r.add(R.StageResult("source", False, [R.Finding("pin", R.FAIL, "pin mismatch")]))
check("a FAIL makes the verdict FAIL", _r.verdict == "FAIL", _r.verdict)
check("and FAIL exits 1", _r.exit_code == 1, str(_r.exit_code))

# ---- a stage that did not run is not a stage that passed ----
_r2 = R.BuildResult()
_r2.add(R.StageResult("drylab", True,
                      [R.Finding("offtarget", R.SKIP, "no genome for this host")]))
check("a skipped gate is recorded as not-run, not as passed",
      _r2.stage("drylab").findings[0].status == R.SKIP)
check("and the result can say which gates did not run",
      _r2.not_run() == ["offtarget"], str(_r2.not_run()))

# ---- serialisation: a wrapper must be able to read everything ----
_r3 = R.BuildResult()
_r3.construct_id = "pSense-Nit"
_r3.version = 2
_r3.insert_len = 1013
_r3.seq_sha256 = "796e94a0" + "0" * 56
_r3.outputs = {"gb": "/tmp/x.gb", "fasta": "/tmp/x.fasta"}
_r3.add(R.StageResult("seal", True))
_d = _r3.to_dict()
check("to_dict is JSON-serialisable", json.dumps(_d)[:1] == "{")
for _k in ("construct_id", "version", "insert_len", "seq_sha256", "verdict",
           "exit_code", "stages", "outputs", "findings"):
    check("to_dict carries %s" % _k, _k in _d, ", ".join(sorted(_d)))
check("the verdict in the dict matches the property",
      _d["verdict"] == _r3.verdict)
check("stages are named in the order they ran",
      [s["name"] for s in _d["stages"]] == ["seal"], str(_d["stages"]))

# Review Focus 3: a BLOCKed build must still serialise, and say which stage refused.
_r4 = R.BuildResult()
_r4.add(R.StageResult("source", False,
                      [R.Finding("pin", R.FAIL, "part 'sfGFP': pin does not match")]))
_d4 = _r4.to_dict()
check("a blocked build still serialises", json.dumps(_d4)[:1] == "{")
check("and names the stage that refused", _r4.blocked_stage() == "source",
      str(_r4.blocked_stage()))
check("and the reason is in the findings",
      "pin does not match" in json.dumps(_d4))

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd /Users/andrewhao/Desktop/katana && python3 tests/test_build_result.py
```

Expected: `ModuleNotFoundError: No module named 'core.result'`.

- [ ] **Step 3: Create `core/result.py`**

```python
"""core.result — the structured outcome of a build.

Why this exists. The GUI used to run the engine as a subprocess and grep its English
prose: kg_verdict.classify looked for "BLOCK", "SEALED:" and "NOT enforced",
kg_rebuild looked for ".gb:" and ".csv:", and test_determinism looked for
"seq_sha256:" and "not self-consistent". The engine's human-readable output was
therefore a machine interface, and rewording any message broke the window SILENTLY --
classify failing to find "SEALED:" fell through to "exited cleanly but printed no SEALED
line" and reported REVIEW, presenting a successful build as a problem.

kg_katana_tabs chose the subprocess for a good reason, stated in its own docstring: one
implementation of every gate, so the window cannot disagree with the command line.
Returning a structured object achieves that goal more strongly -- one literal code path
whose result is data rather than prose -- and it is what the browser front end needs,
since there is no stdout to grep in Pyodide.

The five status tokens are the ones kg_audit already uses, so the forward engine and the
reverse auditor speak one verdict language instead of two that must be kept in step.

Standard library only. Loaded by Pyodide in the browser front end.
"""

PASS = "PASS"
FLAG = "FLAG"
FAIL = "FAIL"
NOTE = "NOTE"
SKIP = "SKIP"

# Severity order for the roll-up. FAIL beats FLAG; NOTE and SKIP never hold back a PASS.
# SKIP exists because "we did not check" must never read as "checked and fine" -- the
# rule the whole project turns on.
_HOLDS_BACK = (FAIL, FLAG)


class Finding(object):
    """One thing the build observed, with why it matters and what to do."""

    __slots__ = ("category", "status", "summary", "loc", "detail", "fix")

    def __init__(self, category, status, summary, loc="", detail="", fix=""):
        self.category = category
        self.status = status
        self.summary = summary
        self.loc = loc
        self.detail = detail
        self.fix = fix

    def to_dict(self):
        return {"category": self.category, "status": self.status,
                "summary": self.summary, "loc": self.loc,
                "detail": self.detail, "fix": self.fix}

    def __repr__(self):
        return "<Finding %s %s: %s>" % (self.status, self.category, self.summary)


class StageResult(object):
    """What one pipeline stage did. `ok=False` means it refused to continue."""

    __slots__ = ("name", "ok", "findings", "data")

    def __init__(self, name, ok, findings=None, data=None):
        self.name = name
        self.ok = bool(ok)
        self.findings = list(findings or [])
        self.data = dict(data or {})

    def to_dict(self):
        return {"name": self.name, "ok": self.ok, "data": self.data,
                "findings": [f.to_dict() for f in self.findings]}


class BuildResult(object):
    """Everything a build produced: stages, findings, the seal, and the files.

    A renderer turns this into text, widgets, HTML or JSON. It is the only thing a
    caller needs, and nothing downstream has to parse a sentence.
    """

    def __init__(self):
        self.construct_id = ""
        self.version = None
        self.insert_len = 0
        self.seq_sha256 = ""
        self.library = ""
        self.library_root = ""
        self.pinned = False
        self.dry_run = False
        self.outputs = {}
        self.features = []
        self.consumed = {}
        self.stages = []

    # ---- building it up -------------------------------------------------------
    def add(self, stage):
        """Record a stage. Stages accumulate in the order they ran."""
        self.stages.append(stage)
        return stage

    def stage(self, name):
        """The LAST stage recorded under `name`, or None.

        Last rather than first: a stage can report more than once -- validate and the
        dry-lab gate both do -- and a caller asking for it wants the latest word.
        """
        for s in reversed(self.stages):
            if s.name == name:
                return s
        return None

    # ---- reading it off ------------------------------------------------------
    @property
    def findings(self):
        out = []
        for s in self.stages:
            out.extend(s.findings)
        return out

    def count(self, status):
        return sum(1 for f in self.findings if f.status == status)

    @property
    def verdict(self):
        """PASS / REVIEW / FAIL, by the same rules the reverse auditor uses."""
        for f in self.findings:
            if f.status == FAIL:
                return FAIL
        if any(s.ok is False for s in self.stages):
            return FAIL
        for f in self.findings:
            if f.status == FLAG:
                return "REVIEW"
        return PASS

    @property
    def exit_code(self):
        """0 PASS, 5 REVIEW, 1 FAIL -- the codes the reverse auditor already returns."""
        return {PASS: 0, "REVIEW": 5, FAIL: 1}[self.verdict]

    def blocked_stage(self):
        """The name of the stage that refused, or None."""
        for s in self.stages:
            if s.ok is False:
                return s.name
        for s in self.stages:
            for f in s.findings:
                if f.status == FAIL:
                    return s.name
        return None

    def not_run(self):
        """The categories of check that did not run.

        A caller can say so out loud, which is the whole reason SKIP is a separate tier:
        a gate that vanished silently is worse than no gate.
        """
        return [f.category for f in self.findings if f.status == SKIP]

    def to_dict(self):
        return {
            "construct_id": self.construct_id,
            "version": self.version,
            "insert_len": self.insert_len,
            "seq_sha256": self.seq_sha256,
            "library": self.library,
            "library_root": self.library_root,
            "pinned": self.pinned,
            "dry_run": self.dry_run,
            "verdict": self.verdict,
            "exit_code": self.exit_code,
            "blocked_stage": self.blocked_stage(),
            "not_run": self.not_run(),
            "outputs": dict(self.outputs),
            "features": list(self.features),
            "consumed": dict(self.consumed),
            "stages": [s.to_dict() for s in self.stages],
            "findings": [f.to_dict() for f in self.findings],
        }
```

- [ ] **Step 4: Run the test**

```bash
cd /Users/andrewhao/Desktop/katana && python3 tests/test_build_result.py
```

Expected: `0 failed`.

- [ ] **Step 5: `core/` must still be Pyodide-clean and acyclic**

```bash
cd /Users/andrewhao/Desktop/katana && python3 tests/test_one_core.py
```

Expected: `6 passed, 0 failed`.

- [ ] **Step 6: Commit**

```bash
git add core/result.py tests/test_build_result.py
git commit -m "feat: core.result -- the structured outcome of a build

The GUI ran the engine as a subprocess and greped its English prose: kg_verdict looked
for BLOCK, SEALED: and NOT enforced, kg_rebuild for .gb: and .csv:, test_determinism for
seq_sha256: and not self-consistent. The engine's human-readable output was therefore a
machine interface, and rewording any message broke the window SILENTLY -- classify
failing to find SEALED: fell through to 'exited cleanly but printed no SEALED line' and
reported REVIEW, presenting a successful build as a problem.

kg_katana_tabs chose the subprocess for a good reason, stated in its own docstring: one
implementation of every gate, so the window cannot disagree with the command line. A
structured return achieves that more strongly -- one literal code path whose result is
data -- and it is what the browser front end needs, because Pyodide has no stdout to
grep.

The five status tokens are kg_audit's own, so the forward engine and the reverse auditor
speak one verdict language rather than two kept in step by hand. SKIP stays a separate
tier because 'we did not check' must never read as 'checked and fine'."
```

---

## Task 2: `build()` returns a `BuildResult`

**Files:**
- Modify: `katana_build.py`
- Modify: `tests/test_build_result.py`

**Interfaces:**
- Produces: `katana_build.build(spec_path, library=None, **opts) -> BuildResult`.
  `opts` accepts `oracle`, `expect_root`, `prior`, `outdir`, `dry_run`, `gibson_overlap`,
  `sbol`, `sbol_format`. It **returns** rather than calling `sys.exit`, so a GUI worker
  thread or a web page gets a result instead of a `SystemExit`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_build_result.py`, before the final `print`:

```python
# ---- build() returns a result instead of exiting ----
sys.path.insert(0, ROOT)
import katana_build

_spec = os.path.join(ROOT, "specs", "pSense-Nit.spec.yaml")
_res = katana_build.build(_spec, dry_run=True)
check("build() returns a BuildResult", isinstance(_res, R.BuildResult),
      type(_res).__name__)
check("it carries the construct id", _res.construct_id == "pSense-Nit",
      _res.construct_id)
check("it carries the sealed hash",
      _res.seq_sha256 ==
      "796e94a0ea2452edd2ce59ca30b8f28fea232b37ab2a036714239069fd1196f5",
      _res.seq_sha256)
check("it carries the insert length", _res.insert_len == 1013, str(_res.insert_len))
check("it records every stage it ran",
      [s.name for s in _res.stages][:4] == ["library", "source", "assemble", "validate"],
      str([s.name for s in _res.stages]))
check("a clean dry run does not read FAIL", _res.verdict != "FAIL", _res.verdict)
check("the off-target gate with no genome is recorded as not-run",
      "offtarget" in _res.not_run(), str(_res.not_run()))

# Review Focus 5: a Spec whose architecture.order names a part absent from parts: must
# come back as a FAIL in the result, NOT as a SystemExit escaping into a worker thread.
import shutil
import tempfile

_d = tempfile.mkdtemp(prefix="br_")
_bad = os.path.join(_d, "bad.spec.yaml")
_src = open(_spec, encoding="utf-8").read()
open(_bad, "w", encoding="utf-8").write(
    _src.replace("order:          [PyeaR, RBS_sfGFP_med, sfGFP, B0015]",
                 "order:          [PyeaR, RBS_sfGFP_med, sfGFP, B0015, NoSuchPart]"))
try:
    _r5 = katana_build.build(_bad, dry_run=True)
    _raised = None
except SystemExit as exc:
    _r5, _raised = None, "SystemExit(%s)" % exc
except Exception as exc:
    _r5, _raised = None, "%s: %s" % (type(exc).__name__, exc)
check("an order naming an unknown part returns a result, not an exception",
      _r5 is not None, _raised or "")
check("and that result reads FAIL", _r5 is not None and _r5.verdict == "FAIL",
      _r5.verdict if _r5 else "")
check("and names the stage that refused",
      _r5 is not None and _r5.blocked_stage() == "assemble",
      str(_r5.blocked_stage()) if _r5 else "")
check("and the reason mentions the part",
      _r5 is not None and "NoSuchPart" in json.dumps(_r5.to_dict()))
shutil.rmtree(_d, ignore_errors=True)
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd /Users/andrewhao/Desktop/katana && python3 tests/test_build_result.py 2>&1 | tail -6
```

Expected: `AttributeError: module 'katana_build' has no attribute 'build'`.

- [ ] **Step 3: Restructure `katana_build.py` around `build()`**

The stage functions already exist and already compute everything needed. The change is
that each returns or records into a `BuildResult` instead of printing and exiting, and
`main()` becomes a renderer.

Introduce a module-level helper so the stage functions can report a refusal without
exiting:

```python
class _Refused(Exception):
    """A stage refused to continue. Carries the stage name and the findings.

    Raised internally and caught by build(), which turns it into a BuildResult. The
    stage functions used to call sys.exit, which is correct for a CLI and wrong for
    everything else: a GUI worker thread got SystemExit, and a web page got nothing at
    all. The CLI renderer re-prints exactly the same text, so a user reading a terminal
    sees no change.
    """

    def __init__(self, stage, findings):
        Exception.__init__(self, stage)
        self.stage = stage
        self.findings = findings


def _refuse(stage, message, category="block", fix=""):
    raise _Refused(stage, [_result.Finding(category, _result.FAIL, message, fix=fix)])
```

Then `build()`:

```python
def build(spec_path, library=None, **opts):
    """Run the pipeline and RETURN what happened. Never exits.

    opts: oracle, expect_root, prior, outdir, dry_run, gibson_overlap, sbol, sbol_format.

    This is the one implementation. ui/cli renders it as text, the GUI as widgets, the
    web front end as HTML, and --json serialises it. The engine's printed output remains
    byte-compatible for anything that still reads a log, but nothing downstream has to
    parse a sentence to know what happened.
    """
    res = _result.BuildResult()
    res.dry_run = bool(opts.get("dry_run"))
    spec_path = Path(spec_path)
    lib = _resolve_library(library) if library else LIB
    res.library = str(lib)

    try:
        if not spec_path.exists():
            _refuse("spec", "spec file not found: %s" % spec_path,
                    fix="Check the spelling and that you are in the right folder.")
        spec = load_yaml_simple(spec_path)
        res.construct_id = spec.get("id", "")
        res.version = spec.get("version", 1)

        _stage_library(res, lib, opts.get("expect_root"))
        resolved = _stage_source(res, spec, lib)
        insert_seq, features, consumed = _stage_assemble(res, spec, resolved)
        res.insert_len = len(insert_seq)
        res.seq_sha256 = _hashing.seq_sha256(insert_seq)
        res.features = features
        res.consumed = consumed
        _stage_oracle(res, opts.get("oracle"))
        _stage_validate(res, insert_seq, features, spec, resolved)
        _stage_drylab(res, insert_seq, features, spec, resolved)
        if not res.dry_run:
            _stage_seal(res, insert_seq, features, spec, lib, opts)
            _stage_diff(res, insert_seq, opts.get("prior"))
    except _Refused as refusal:
        res.add(_result.StageResult(refusal.stage, False, refusal.findings))

    return res
```

Each `_stage_*` helper is the body of the existing stage, with `sys.exit(msg)` replaced
by `_refuse(stage_name, msg)` and its observations appended as `Finding`s. Keep every
message string exactly as it is: they are good, they were written for a reader in
trouble, and changing them is not this task.

- [ ] **Step 4: Make `main()` a renderer over the result**

```python
def main():
    args = _parse_args()
    res = build(args.spec, library=args.library, oracle=args.oracle,
                expect_root=args.expect_root, prior=args.prior, outdir=args.outdir,
                dry_run=args.dry_run, gibson_overlap=args.gibson_overlap,
                sbol=args.sbol, sbol_format=args.sbol_format)
    if args.json:
        json.dump(res.to_dict(), sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        render_text(res)
    return res.exit_code
```

`render_text(res)` prints the same lines the engine has always printed, in the same
order, including `seq_sha256: <hash>`, the `BLOCK ...` line for a refusal, `SEALED: ...`,
and the `.gb:` / `.fasta:` / `.csv:` output lines — because `test_determinism`,
`kg_rebuild` and anyone reading a log still rely on them.

Add the flag:

```python
    parser.add_argument("--json", action="store_true",
                        help="emit the whole result as JSON instead of text. Everything "
                             "the text output says, in a form a wrapper can read without "
                             "parsing sentences.")
```

- [ ] **Step 5: Run the result tests**

```bash
cd /Users/andrewhao/Desktop/katana && python3 tests/test_build_result.py 2>&1 | tail -14
```

Expected: `0 failed`.

- [ ] **Step 6: The engine's printed output must be unchanged where it matters**

```bash
cd /Users/andrewhao/Desktop/katana
python3 test_determinism.py 2>&1 | grep -E '^   (PASS|FAIL|SKIP)|ALL|FAILED'
python3 tests/test_engine_gates.py 2>&1 | tail -1
python3 katana_build.py specs/pSense-Nit.spec.yaml --dry-run | grep -cE 'seq_sha256:|Stage-1/2 PASS|Stage-4b'
```

Expected: all 7 ORACLE hashes PASS, `ALL PASSED — 10 checks`, `10 passed, 0 failed`, and
a non-zero count — the lines other consumers grep are still there.

- [ ] **Step 7: Review Focus 3 — `--json` on a BLOCKed build**

```bash
cd /Users/andrewhao/Desktop/katana
python3 katana_build.py specs/pSense-Nit.spec.yaml --dry-run --json | python3 -c "
import json, sys
d = json.load(sys.stdin)
print('verdict      :', d['verdict'])
print('exit_code    :', d['exit_code'])
print('seq_sha256   :', d['seq_sha256'][:16])
print('not_run      :', d['not_run'])
print('stages       :', [s['name'] for s in d['stages']])
"
python3 katana_build.py /nonexistent.spec.yaml --json 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
print('blocked build still emits valid JSON; blocked_stage =', d['blocked_stage'])
print('and the reason is present:',
      any('not found' in f['summary'] for f in d['findings']))
"
```

Expected: the first prints the verdict, the hash and `['offtarget']`; the second prints a
`blocked_stage` of `spec` and `True`. A wrapper that gets a traceback and no JSON cannot
report anything, which is why this is a Review Focus item.

- [ ] **Step 8: Commit**

```bash
git add katana_build.py tests/test_build_result.py
git commit -m "feat!: build() returns a BuildResult; --json emits it

The pipeline is now a function that RETURNS what happened rather than printing it and
calling sys.exit. main() is a renderer over the result, and --json serialises the same
object.

sys.exit was correct for a CLI and wrong for everything else: a GUI worker thread got
SystemExit, and a web page got nothing at all. Stage refusals raise an internal _Refused
that build() turns into a BuildResult with the stage marked not-ok, so a caller always
gets a result. Every message string is unchanged -- they were written for a reader in
trouble and they are good.

The printed output stays byte-compatible where it matters: seq_sha256:, the BLOCK line,
SEALED:, and the .gb: / .fasta: / .csv: output lines, because test_determinism,
kg_rebuild and anyone reading a log still read them. Those consumers move to BuildResult
in the next tasks; the lines remain for external scripts.

A blocked build still emits valid JSON naming the stage that refused and why. A wrapper
that gets a traceback and no JSON cannot report anything.

All 7 ORACLE construct hashes reproduce."
```

---

## Task 3: `kg_verdict.from_result`

**Files:**
- Modify: `kagami/kg_verdict.py`
- Modify: `kagami/tests.py`

**Interfaces:**
- Produces: `kg_verdict.from_result(result_dict_or_obj) -> (kind, headline, detail)`,
  the same three-tuple shape `classify()` returns, so a caller swaps one for the other.

- [ ] **Step 1: Write the failing test**

Append to the `engine tabs: verdict wording` section of `kagami/tests.py`, inside the
`if _kt:` block:

```python
    # from_result reads the engine's structured result instead of greping its prose.
    # The same three-tuple, so the window's rendering is unchanged -- what changes is
    # that rewording a message can no longer silently turn a sealed build into REVIEW.
    import json as _json
    _ok = {"verdict": "PASS", "exit_code": 0, "blocked_stage": None, "not_run": [],
           "dry_run": False, "seq_sha256": "abc123def4567890" + "0" * 48,
           "findings": [], "stages": [{"name": "seal", "ok": True, "findings": [],
                                       "data": {}}]}
    check("a clean sealed result reads SEALED / PASS",
          _kt.from_result(_ok)[:2] == ("PASS", "SEALED"))

    _skipped = dict(_ok, verdict="PASS", not_run=["offtarget"],
                    findings=[{"category": "offtarget", "status": "SKIP",
                               "summary": "OFF-TARGET SKIPPED - no genome",
                               "loc": "", "detail": "", "fix": ""}])
    _k, _h, _d = _kt.from_result(_skipped)
    check("a seal with a gate that did not run is REVIEW, not PASS", _k == "REVIEW")
    check("...and the headline says so in words", "gate did not run" in _h)
    check("...and the detail names which gate", "offtarget" in _d)

    _dry = dict(_ok, dry_run=True, seq_sha256="")
    check("a clean dry run says nothing was written",
          "nothing was written" in _kt.from_result(_dry)[2])

    _blocked = {"verdict": "FAIL", "exit_code": 1, "blocked_stage": "source",
                "not_run": [], "dry_run": False, "seq_sha256": "",
                "findings": [{"category": "pin", "status": "FAIL",
                              "summary": "part 'sfGFP': pin does not match",
                              "loc": "", "detail": "", "fix": ""}],
                "stages": [{"name": "source", "ok": False, "findings": [], "data": {}}]}
    _k, _h, _d = _kt.from_result(_blocked)
    check("a refused build is BLOCKED", (_k, _h) == ("FAIL", "BLOCKED"))
    check("...and quotes the reason", "pin does not match" in _d)
    check("...and names the stage", "source" in _d)

    # The old prose-greping classify() stays, for the subprocess path and for anything
    # outside this repository that calls it. It must not have changed.
    check("classify() still works on raw output",
          _kt.classify(0, "  SEALED: abc\n", False)[:2] == ("PASS", "SEALED"))
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd /Users/andrewhao/Desktop/katana/kagami && python3 tests.py 2>&1 | grep -E 'from_result|AttributeError|passed,'
```

Expected: an `AttributeError` on `from_result`.

- [ ] **Step 3: Add `from_result` to `kagami/kg_verdict.py`**

```python
def from_result(result):
    """Turn a BuildResult (object or its to_dict) into (kind, headline, detail).

    The same three-tuple classify() returns, so a caller swaps one for the other and the
    window's rendering is unchanged. What changes is that rewording an engine message can
    no longer silently turn a sealed build into REVIEW: classify() greps prose, and this
    reads data.

    The rule classify() encodes is kept exactly: a run that finished but left a gate
    unenforced is REVIEW, never PASS. "We did not check" must not read as "checked and
    fine".
    """
    d = result if isinstance(result, dict) else result.to_dict()
    verdict = d.get("verdict", "FAIL")
    not_run = list(d.get("not_run") or [])

    if verdict == "FAIL":
        stage = d.get("blocked_stage") or "?"
        reason = ""
        for f in d.get("findings") or []:
            if f.get("status") == "FAIL":
                reason = f.get("summary", "")
                break
        detail = reason or "The engine stopped."
        if stage and stage not in detail:
            detail = "%s (stage: %s)" % (detail, stage)
        return "FAIL", "BLOCKED", detail

    if d.get("dry_run"):
        if not_run:
            return ("REVIEW", "CHECKED - a gate did not run",
                    "Not enforced this run: " + ", ".join(not_run))
        return "PASS", "CHECKED", "Stages 1-4b passed. Dry run: nothing was written."

    if not d.get("seq_sha256"):
        return ("REVIEW", "FINISHED - no seal",
                "The engine exited cleanly but recorded no sealed hash.")

    if not_run:
        return ("REVIEW", "SEALED - a gate did not run",
                "Not enforced this run: " + ", ".join(not_run))

    return "PASS", "SEALED", "seq_sha256 " + d["seq_sha256"]
```

- [ ] **Step 4: Run the suite**

```bash
cd /Users/andrewhao/Desktop/katana/kagami && python3 tests.py 2>&1 | grep -E '^  FAIL|passed,'
```

Expected: `0 failed`, with the count risen by the ten new assertions.

- [ ] **Step 5: Commit**

```bash
git add kagami/kg_verdict.py kagami/tests.py
git commit -m "feat: kg_verdict.from_result reads the engine's result, not its prose

The same three-tuple classify() returns, so the window's rendering is unchanged. What
changes is that rewording an engine message can no longer silently turn a sealed build
into REVIEW -- classify() greps for SEALED: and BLOCK, and this reads data.

The rule classify() encodes is preserved exactly: a run that finished but left a gate
unenforced is REVIEW, never PASS. classify() itself stays for the subprocess path and
for anything outside this repository, and a test asserts it still behaves."
```

---

## Task 4: the GUI's Build tab calls the function

**Files:**
- Modify: `kagami/kg_katana_tabs.py`

- [ ] **Step 1: Teach `BuildPane` to call `build()` when the engine is importable**

Replace `BuildPane.go` and `_finished` so that, when `core/` and `katana_build` can be
imported, the pane calls the function on its worker thread and renders the
`BuildResult`; otherwise it keeps the subprocess path unchanged.

```python
    def _engine_importable(self):
        """True when katana_build can be imported from the engine directory.

        The subprocess path is kept as the fallback rather than deleted: Kagami can be
        unzipped on its own beside an engine it cannot import, and a window that works
        is worth more than one code path.
        """
        import importlib.util
        if self.engine not in sys.path:
            sys.path.insert(0, self.engine)
        return importlib.util.find_spec("katana_build") is not None
```

and in `go()`, when importable, run on a thread:

```python
        def work():
            try:
                import katana_build
                res = katana_build.build(spec, library=(lib or None),
                                         outdir=(None if dry else out), dry_run=dry)
                self.q.put(("result", res))
            except Exception as exc:
                self.q.put(("err", "%s: %s" % (type(exc).__name__, exc)))
```

The drain loop gains a `result` case that calls `classify`'s replacement:

```python
                if kind == "result":
                    self.busy = False
                    self.spin.stop(); self.spin.pack_forget()
                    for b in self._buttons:
                        b.configure(state="normal")
                    res = val
                    for line in render_lines(res):
                        self._say(line + "\n", self._tag_for(line))
                    k, head, detail = from_result(res)
                    self._show(k, head, detail)
                    self._after_build(res, dry)
                    return
```

- [ ] **Step 2: Review Focus 4 — a BLOCKing Spec must read FAIL and name the stage**

Add to `kagami/tests.py`, in the engine-tabs section:

```python
    # Review Focus 4: the Build tab on a Spec that BLOCKs. The verdict must read FAIL
    # and name the blocking stage -- which is what the greped "BLOCK" line used to
    # supply, and what a reader needs in order to know where to look.
    _blk = {"verdict": "FAIL", "exit_code": 1, "blocked_stage": "assemble",
            "not_run": [], "dry_run": True, "seq_sha256": "",
            "findings": [{"category": "block", "status": "FAIL",
                          "summary": "'NoSuchPart' appears in architecture.order but "
                                     "is not in your Spec's parts list",
                          "loc": "", "detail": "", "fix": ""}],
            "stages": [{"name": "assemble", "ok": False, "findings": [], "data": {}}]}
    _k, _h, _d = _kt.from_result(_blk)
    check("a BLOCKing Spec reads FAIL in the window", _k == "FAIL")
    check("...and the detail names the stage that refused", "assemble" in _d)
    check("...and quotes what the engine said", "NoSuchPart" in _d)
```

- [ ] **Step 3: Run the suite and the GUI import**

```bash
cd /Users/andrewhao/Desktop/katana/kagami
python3 tests.py 2>&1 | grep -E '^  FAIL|passed,'
python3 -c "
import sys; sys.path.insert(0, '.')
import kg_katana_tabs
print('tabs import OK; from_result wired:', hasattr(kg_katana_tabs, 'from_result'))
"
```

Expected: `0 failed`, and `from_result wired: True`.

- [ ] **Step 4: Commit**

```bash
git add kagami/kg_katana_tabs.py kagami/tests.py
git commit -m "feat: the Build tab calls build() and renders its result

One literal code path for every gate, which is what the subprocess was chosen to
guarantee and now holds more strongly: the window reads a BuildResult rather than
greping the engine's prose for SEALED: and BLOCK. Rewording a message can no longer turn
a sealed build into REVIEW.

The subprocess path is kept as a fallback rather than deleted, because Kagami can be
unzipped beside an engine it cannot import, and a window that works is worth more than
one code path.

Verified: a Spec that BLOCKs reads FAIL in the window and the detail names both the
stage that refused and what the engine said."
```

---

## Task 5: one front door

**Files:**
- Create: `katana` (POSIX), `katana.bat` (Windows), `ui_menu.py`
- Create: `tests/test_entry.py`

**Interfaces:**
- Produces: `ui_menu.run(argv, stdin=None, stdout=None) -> int` — the dispatcher and the
  interactive menu, importable so it can be tested without a terminal.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_entry.py`:

```python
"""test_entry.py — the single entry point. Run: python3 tests/test_entry.py"""
import io
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import ui_menu

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  [" + detail[:200] + "]") if detail else ""))


def run(argv, stdin_text=""):
    out = io.StringIO()
    rc = ui_menu.run(argv, stdin=io.StringIO(stdin_text), stdout=out)
    return rc, out.getvalue()


print("entry point")

# ---- subcommands ----
_rc, _out = run(["--help"])
check("--help lists the subcommands", "check" in _out and "build" in _out, _out[:200])
check("and exits 0", _rc == 0, str(_rc))

_rc, _out = run(["verify"])
check("`verify` runs the library check", "SEALED" in _out or "parts verified" in _out,
      _out[-200:])
check("and exits 0 on a sealed library", _rc == 0, str(_rc))

_rc, _out = run(["build", os.path.join(ROOT, "specs", "pSense-Nit.spec.yaml"),
                 "--dry-run"])
check("`build` builds a Spec", "796e94a0ea2452ed" in _out, _out[-300:])

_rc, _out = run(["nonsense"])
check("an unknown subcommand is refused, not guessed", _rc != 0, str(_rc))
check("and the refusal lists what IS available", "check" in _out, _out[:200])

# ---- the menu ----
_rc, _out = run([], stdin_text="3\n")
check("no arguments opens the menu", "what do you want to do" in _out.lower(),
      _out[:200])
check("the menu numbers its choices", "1)" in _out and "5)" in _out, _out[:300])
check("choosing 3 runs the library check",
      "SEALED" in _out or "parts verified" in _out, _out[-200:])

_rc, _out = run([], stdin_text="\n")
check("an empty choice leaves without doing anything",
      "nothing" in _out.lower(), _out[-200:])
check("and exits 0, because leaving is not an error", _rc == 0, str(_rc))

_rc, _out = run([], stdin_text="9\n")
check("an out-of-range choice says so rather than crashing",
      "not one of" in _out.lower() or "choose" in _out.lower(), _out[-200:])

# Review Focus 1: no TTY. A double-click, a CI step or a pipe gives no input at all.
# input() raises EOFError, and the menu must print how to use the subcommands rather
# than a traceback.
class _NoInput(io.StringIO):
    def readline(self, *a):
        raise EOFError("no tty")


_out2 = io.StringIO()
try:
    _rc2 = ui_menu.run([], stdin=_NoInput(), stdout=_out2)
    _raised = None
except Exception as exc:
    _rc2, _raised = None, "%s: %s" % (type(exc).__name__, exc)
check("no TTY does not raise", _raised is None, _raised or "")
check("and it tells the reader how to run it non-interactively",
      "katana check" in _out2.getvalue() or "katana build" in _out2.getvalue(),
      _out2.getvalue()[-300:])

# Review Focus 2: the menu offers the window. Where tkinter is absent -- common on a
# minimal Linux -- it must say so and stay usable, not crash.
_rc, _out = run([], stdin_text="5\n")
check("choosing the window either opens it or explains why it cannot",
      _rc == 0 or "tkinter" in _out.lower() or "window" in _out.lower(),
      _out[-300:])

# ---- the launcher script itself ----
_launcher = os.path.join(ROOT, "katana")
check("the katana launcher exists", os.path.isfile(_launcher))
check("and is executable", os.access(_launcher, os.X_OK))
_p = subprocess.run(["bash", "-n", _launcher], capture_output=True, text=True)
check("and is valid shell", _p.returncode == 0, _p.stderr[:200])

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd /Users/andrewhao/Desktop/katana && python3 tests/test_entry.py 2>&1 | tail -4
```

Expected: `ModuleNotFoundError: No module named 'ui_menu'`.

- [ ] **Step 3: Create `ui_menu.py`**

```python
#!/usr/bin/env python3
"""ui_menu.py — the one front door.

Why this exists. There were thirteen Python entry points and four launchers, and the
root README mentioned neither the auditor nor the window. A reader was asked to choose
between them before knowing what any of them did, and the first command in the README
failed on macOS because it said `python` rather than `python3`. Not one member of this
team got through it.

So: one command. `katana` with a subcommand for people who know what they want, and with
no arguments a menu that asks one question at a time. The fifty-five flags across the
underlying tools all still work; nobody has to meet them.

`run()` takes stdin and stdout so the menu can be tested without a terminal, which is
also what makes the no-TTY case (a double-click, a pipe, a CI step) something the tests
can pin rather than something a user discovers.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

COMMANDS = [
    ("check", "Check a sequence", "someone sent me a file; is the label true?"),
    ("build", "Build a construct", "Design Spec -> order-ready sequence"),
    ("verify", "Check the parts library",
     "re-hash everything, then try to break the checker"),
    ("add", "Add a part to my library", "from NCBI, the iGEM Registry, or a file"),
    ("gui", "Open the window", "the same things, with buttons"),
]


def _print(out, text=""):
    out.write(text + "\n")


def _usage(out):
    _print(out, "Katana - build DNA constructs you can check, and check ones you did not.")
    _print(out)
    _print(out, "  katana                     ask me what I want to do")
    for name, title, hint in COMMANDS:
        _print(out, "  katana %-20s %s" % (name, hint))
    _print(out)
    _print(out, "Every underlying tool's own flags still work, e.g.")
    _print(out, "  katana build my.spec.yaml --dry-run --expect-root <sha256>")
    _print(out, "  katana check my.gb --host genome.fna --html report.html")
    _print(out)
    _print(out, "Nothing needs installing beyond Python 3.9 or newer.")


def _run_module(path, argv, stdout):
    """Run one of the tools in-process, so its output lands in `stdout`."""
    import runpy
    old_argv, old_stdout = sys.argv, sys.stdout
    sys.argv = [path] + list(argv)
    sys.stdout = stdout
    try:
        runpy.run_path(path, run_name="__main__")
        return 0
    except SystemExit as exc:
        return int(exc.code or 0)
    finally:
        sys.argv, sys.stdout = old_argv, old_stdout


def _dispatch(name, argv, stdout):
    if name == "check":
        return _run_module(os.path.join(HERE, "kagami", "kagami.py"),
                           ["audit"] + list(argv), stdout)
    if name == "build":
        return _run_module(os.path.join(HERE, "katana_build.py"), argv, stdout)
    if name == "verify":
        return _run_module(os.path.join(HERE, "verify.py"), argv, stdout)
    if name == "add":
        return _run_module(os.path.join(HERE, "add_part.py"), argv, stdout)
    if name == "gui":
        try:
            import tkinter  # noqa: F401
        except ImportError:
            _print(stdout, "This machine has no tkinter, so the window cannot open.")
            _print(stdout, "Everything it does is available from the command line:")
            _print(stdout, "  katana check YOURFILE.gb")
            _print(stdout, "  katana build YOURSPEC.spec.yaml")
            _print(stdout, "On Debian or Ubuntu: sudo apt install python3-tk")
            return 0
        return _run_module(os.path.join(HERE, "kagami", "kagami_gui.py"), argv, stdout)
    _print(stdout, "There is no `katana %s`. What there is:" % name)
    _print(stdout)
    _usage(stdout)
    return 2


def _menu(stdin, stdout):
    _print(stdout, "Katana - what do you want to do?")
    _print(stdout)
    for n, (_name, title, hint) in enumerate(COMMANDS, 1):
        _print(stdout, "  %d) %-26s %s" % (n, title, hint))
    _print(stdout)
    _print(stdout, "  (press Return to leave)")
    _print(stdout)
    stdout.write("Choose (1-%d): " % len(COMMANDS))
    try:
        raw = stdin.readline()
    except EOFError:
        raw = None
    if raw is None:
        # No terminal: a double-click, a pipe, or a CI step. Say how to run it without
        # one rather than dying on a traceback nobody can act on.
        _print(stdout)
        _print(stdout, "Nothing is reading the keyboard here, so the menu cannot ask.")
        _print(stdout, "Name what you want instead:")
        _print(stdout)
        _usage(stdout)
        return 0

    choice = raw.strip()
    if not choice:
        _print(stdout)
        _print(stdout, "Nothing selected, so nothing was done.")
        _print(stdout, "Run it again when you know which one you need.")
        return 0
    if not choice.isdigit() or not (1 <= int(choice) <= len(COMMANDS)):
        _print(stdout)
        _print(stdout, "'%s' is not one of the numbers above, so nothing was done."
               % choice)
        _print(stdout, "Run it again and type a single number from 1 to %d."
               % len(COMMANDS))
        return 1

    name = COMMANDS[int(choice) - 1][0]
    _print(stdout)
    return _ask_and_run(name, stdin, stdout)


def _ask_and_run(name, stdin, stdout):
    """Ask for what the chosen command needs, one question at a time."""
    if name in ("verify", "gui"):
        return _dispatch(name, [], stdout)

    prompts = {
        "check": ("Which file? (drag it onto this window, then press Return)", []),
        "build": ("Which Design Spec? (drag it on, then press Return)", ["--dry-run"]),
        "add": ("Which iGEM Registry part? e.g. BBa_B0015", []),
    }
    question, extra = prompts[name]
    stdout.write(question + "\n> ")
    try:
        answer = (stdin.readline() or "").strip().strip('"').strip("'")
    except EOFError:
        answer = ""
    if not answer:
        _print(stdout)
        _print(stdout, "Nothing given, so nothing was done.")
        return 0
    if name == "add":
        return _dispatch("add", ["--registry", answer], stdout)
    return _dispatch(name, [answer] + extra, stdout)


def run(argv=None, stdin=None, stdout=None):
    """Dispatch a subcommand, or ask. Returns an exit code; never raises for input."""
    argv = list(sys.argv[1:] if argv is None else argv)
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout

    if not argv:
        return _menu(stdin, stdout)
    if argv[0] in ("-h", "--help", "help"):
        _usage(stdout)
        return 0
    return _dispatch(argv[0], argv[1:], stdout)


if __name__ == "__main__":
    sys.exit(run())
```

- [ ] **Step 4: Create the launchers**

`katana`:

```bash
#!/bin/bash
# Katana - one command for everything.
#
#   ./katana                       ask me what I want to do
#   ./katana check my.gb           is this sequence what its labels say?
#   ./katana build my.spec.yaml    Design Spec -> order-ready sequence
#   ./katana verify                check the parts library
#
# Nothing needs installing beyond Python 3.9 or newer. No pip, no NCBI BLAST+.
#
# ON A MAC, RUN THIS FROM TERMINAL RATHER THAN DOUBLE-CLICKING IT. macOS refuses to open
# a downloaded script that is not code-signed, and this one is not; the "Right-click ->
# Open" trick that used to get past that was removed in macOS 15. The block applies to
# double-clicking only -- a script a shell runs is unaffected. So: open Terminal, type
# `bash ` (with the trailing space), drag this file onto the window, press Return.

cd "$(dirname "${0}")" || exit 1

if [ ! -f ui_menu.py ]; then
  echo
  echo "  Katana's own files are not in this folder, so it cannot run."
  echo "  Unzip the download first, then run this from the extracted folder."
  echo
  exit 2
fi

PY=""
for c in python3 python3.12 python3.11 python3.10 python3.9 python; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo
  echo "  Python 3 was not found on this computer."
  echo
  echo "  macOS: copy the line below into Terminal, press Return, click through the"
  echo "  installer it opens, then run this file again."
  echo
  echo "    curl -L -o ~/Downloads/python.pkg https://www.python.org/ftp/python/3.12.10/python-3.12.10-macos11.pkg && open ~/Downloads/python.pkg"
  echo
  echo "  Debian/Ubuntu:  sudo apt install python3 python3-tk"
  echo
  exit 2
fi

exec "$PY" ui_menu.py "$@"
```

`katana.bat`:

```bat
@echo off
REM Katana - one command for everything.
REM
REM   katana                       ask me what I want to do
REM   katana check my.gb           is this sequence what its labels say?
REM   katana build my.spec.yaml    Design Spec -> order-ready sequence
REM   katana verify                check the parts library
REM
REM Nothing needs installing beyond Python 3.9 or newer. No pip, no NCBI BLAST+.
setlocal
cd /d "%~dp0"

if not exist "ui_menu.py" (
  echo(
  echo   Katana's own files are not in this folder, so it cannot run.
  echo   You probably ran this from INSIDE the downloaded .zip. Right-click the .zip,
  echo   choose "Extract All...", then run this from the extracted folder.
  echo(
  pause
  exit /b 2
)

REM Windows ships a PLACEHOLDER python.exe that opens the Microsoft Store instead of
REM running anything. `py` is the real launcher when Python is properly installed.
where /q py.exe && (py ui_menu.py %* & goto :done)
where /q python.exe && (python ui_menu.py %* & goto :done)
echo(
echo   Python 3 was not found. Install it from https://www.python.org/downloads/
echo   and tick "Add python.exe to PATH" in the installer, then run this again.
echo(
pause
exit /b 2

:done
endlocal
```

```bash
chmod +x katana
```

- [ ] **Step 5: Run the entry tests**

```bash
cd /Users/andrewhao/Desktop/katana && python3 tests/test_entry.py
```

Expected: `0 failed`.

- [ ] **Step 6: Drive it the way a person would**

```bash
cd /Users/andrewhao/Desktop/katana
./katana --help
printf '3\n' | ./katana | tail -6
./katana check kagami/examples/demo.gb | grep -E 'VERDICT|identity-mislabel'
./katana build specs/pSense-Nit.spec.yaml --dry-run | grep seq_sha256
./katana nonsense; echo "unknown subcommand exit=$?"
```

Expected: the usage list; the menu running the library check; the demo's mislabel and
`REVIEW`; the sealed hash; and a non-zero exit for the unknown subcommand.

- [ ] **Step 7: Commit**

```bash
git add katana katana.bat ui_menu.py tests/test_entry.py
git commit -m "feat: one front door -- ./katana, with a menu when asked nothing

There were thirteen Python entry points and four launchers, and the root README
mentioned neither the auditor nor the window. A reader had to choose between them before
knowing what any of them did, and the README's first command failed on macOS because it
said python rather than python3. Not one member of this team got through it.

Now: `katana <subcommand>` for people who know what they want, and `katana` with no
arguments asks one question at a time. The fifty-five flags across the underlying tools
all still work and are passed straight through; nobody has to meet them.

run() takes stdin and stdout, so the menu is testable without a terminal -- which is
what lets the no-TTY case be pinned rather than discovered. A double-click, a pipe or a
CI step gets a usage list instead of an EOFError traceback, and choosing the window on a
machine without tkinter gets an explanation and the command-line equivalent rather than
a crash.

The macOS launcher says to run it from Terminal, not to double-click it, and says why."
```

---

## Task 6: the README leads with the front door

**Files:** `README.md`, `kagami/README.md`

- [ ] **Step 1: Replace the README's opening how-to-run with the one command**

Immediately after the failure table, before `## Try it first, read second`, the first
instruction a reader meets becomes:

```markdown
## Run it

Download, unzip, and from a terminal in that folder:

```
./katana
```

It asks what you want to do. Nothing needs installing beyond Python 3.9 or newer — no
`pip`, no NCBI BLAST+.

If you already know what you want:

```
./katana check someones-plasmid.gb      is this sequence what its labels say?
./katana build my-design.spec.yaml      Design Spec → order-ready sequence
./katana verify                         check the parts library, then try to break the checker
```

On Windows, `katana.bat` instead of `./katana`. **On a Mac, run it from Terminal rather
than double-clicking** — macOS refuses to open a downloaded script that is not
code-signed, and the block applies to double-clicking only. Open Terminal, type `bash `
(with the trailing space), drag the file onto the window, press Return.
```

- [ ] **Step 2: Fold the old `Try it first` and `Install` sections into it**

`## Try it first, read second` becomes a short paragraph under `## Run it` pointing at
`./katana verify` and explaining why the second half of that command matters. The
`**Install.**` paragraph is deleted — there is nothing to install, and the sentence that
said so belongs here now.

- [ ] **Step 3: Give Kagami's README the same front door**

Replace its `## Usage` opening with `./katana check INPUT.gb`, keeping the full flag
list below it for people who want it.

- [ ] **Step 4: Check the documented commands actually run**

```bash
cd /Users/andrewhao/Desktop/katana
python3 - <<'PY'
import re, subprocess, sys
doc = open("README.md", encoding="utf-8").read()
cmds = [c for c in re.findall(r'^\s*(\./katana[^\n#]*)$', doc, re.M)]
print("found %d ./katana commands in README" % len(cmds))
bad = []
for c in cmds:
    c = c.strip()
    if "my-design" in c or "someones-plasmid" in c:
        continue          # placeholders, by design
    p = subprocess.run(["bash", "-c", c + " >/dev/null 2>&1"], timeout=300)
    if p.returncode not in (0, 5):
        bad.append((c, p.returncode))
for c, rc in bad:
    print("  FAILS: %s -> %d" % (c, rc))
print("documented commands that run:", len(cmds) - len(bad), "/", len(cmds))
sys.exit(1 if bad else 0)
PY
```

Expected: every non-placeholder `./katana` command in the README exits 0 or 5. A README
whose first command fails is what produced the 0-of-N install result; asserting it is
cheap.

- [ ] **Step 5: Commit**

```bash
git add README.md kagami/README.md
git commit -m "docs: the README leads with ./katana

The front page asked a reader to choose between thirteen entry points, mentioned neither
the auditor nor the window, and opened with a pip install and a 400 MB BLAST+ download.
Its very first command failed on macOS, because it said python rather than python3. Every
member of this team who followed it failed.

It now opens with one command that asks what you want, says there is nothing to install,
and says to run it from Terminal on a Mac and why.

A test extracts every ./katana command from the README and runs it, because a README
whose first command fails is what produced the 0-of-N result."
```

---

## Task 7: Phase 3 verification

- [ ] **Step 1: Every suite, bare interpreter, blastn hidden**

```bash
cd /Users/andrewhao/Desktop/katana
SAFE=/usr/bin:/bin:/usr/sbin:/sbin
python3 -c "import yaml" 2>&1 | tail -1
for t in tests/test_core_lock.py tests/test_engine_gates.py tests/test_one_core.py \
         tests/test_build_result.py tests/test_entry.py; do
  printf "  %-32s " "$t"; python3 "$t" 2>&1 | tail -1
done
printf "  %-32s " verify.py;           python3 verify.py 2>&1 | grep -oE '[0-9]+/[0-9]+ checks passed'
printf "  %-32s " test_determinism.py; python3 test_determinism.py 2>&1 | tail -1
printf "  %-32s " kagami/tests.py;     (cd kagami && PATH="$SAFE" /usr/bin/python3 tests.py 2>&1 | tail -1)
printf "  %-32s " kagami/test_identify.py; (cd kagami && PATH="$SAFE" /usr/bin/python3 test_identify.py 2>&1 | tail -1)
```

- [ ] **Step 2: The library and the Specs are untouched**

```bash
cd /Users/andrewhao/Desktop/katana && git diff --stat main..HEAD -- parts-library/ specs/
```

Expected: no output.

- [ ] **Step 3: Add the two new suites to CI**

In `.gitlab-ci.yml`, add `tests/test_build_result.py` and `tests/test_entry.py` to both
the `verify` and the `no-deps` jobs, then validate that every script entry is a string:

```bash
cd /Users/andrewhao/Desktop/katana && python3 -c "
import sys; sys.path.append('_vendor'); import yaml
d = yaml.safe_load(open('.gitlab-ci.yml'))
bad = [(j,i) for j,c in d.items() if isinstance(c,dict) and 'script' in c
       for i in c['script'] if not isinstance(i,str)]
print('non-string script entries:', bad or 'none')
"
```

- [ ] **Step 4: Commit the phase marker**

```bash
git add .gitlab-ci.yml
git commit -m "chore: phase 3 complete -- one implementation, one front door

build() returns a BuildResult; main() renders it; --json serialises it. The GUI reads
that object instead of greping the engine's prose for SEALED: and BLOCK, so rewording a
message can no longer silently turn a sealed build into REVIEW. The printed lines stay
byte-compatible for anything that still reads a log.

./katana is the single entry point. With a subcommand it does the thing; with no
arguments it asks one question at a time. Thirteen entry points and fifty-five flags are
still there for anyone who wants them, and nobody has to meet them.

Verified with nothing installed and blastn hidden: all suites green, all 7 ORACLE
construct hashes reproduced, parts-library/ and specs/ byte-identical to main.

Next: phase 4 (spec step 7) -- the web front end, local first, then GitHub Pages at
andrewhao66/iGEM-katana-webtest."
```
