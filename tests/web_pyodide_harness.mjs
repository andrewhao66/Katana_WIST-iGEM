/* web_pyodide_harness.mjs — load Katana into a real Pyodide and run a real audit.
 *
 * This is the check that was missing. tests/test_web.py runs the page's Python block on
 * CPython, which proves the call signatures but not that the modules work compiled to
 * WebAssembly: a module-level `import subprocess`, a C extension, a filesystem
 * assumption or a memory limit would all pass there and fail in a browser.
 *
 * So this loads the same MODULES list index.js loads, into the same Pyodide version the
 * page pins, writes them into the same /katana/ layout, and runs the audit block
 * extracted from index.js verbatim. What it does not cover is pixels; the rendering
 * functions are tested separately in tests/web_render_harness.js.
 *
 * Driven by tests/test_web_pyodide.py, which skips loudly when pyodide is not installed.
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.dirname(HERE);

const results = [];
function assert(name, cond, detail) {
  results.push({ name, ok: !!cond, detail: String(detail == null ? "" : detail) });
}

function finish() {
  process.stdout.write(JSON.stringify(results));
}

// ESM resolution does not honour NODE_PATH, so an explicitly supplied path is tried
// first. This keeps a node_modules tree out of the repository while letting CI point at
// one it installed.
let loadPyodide;
const tried = [];
for (const spec of [process.env.KATANA_PYODIDE, "pyodide"].filter(Boolean)) {
  try {
    ({ loadPyodide } = await import(spec));
    break;
  } catch (err) { tried.push(spec + ": " + String(err.message).split("\n")[0]); }
}
if (!loadPyodide) {
  process.stdout.write(JSON.stringify({ unavailable: tried.join(" | ") }));
  process.exit(0);
}

// The page's own lists, read from the page, so this cannot drift from what ships.
const js = fs.readFileSync(path.join(ROOT, "ui", "web", "index.js"), "utf8");
const MODULES = [...js.matchAll(/"((?:core|kagami)\/[\w./]+\.py)"/g)].map((m) => m[1]);
const code = js.match(/json = await pyodide\.runPythonAsync\(`\n([\s\S]*?)`\);/)[1];

assert("index.js names its modules (" + MODULES.length + ")", MODULES.length >= 10,
       MODULES.length);

const py = await loadPyodide();
assert("Pyodide loads", !!py);

py.FS.mkdirTree("/katana/core");
py.FS.mkdirTree("/katana/kagami/refs");
for (const m of MODULES) {
  py.FS.writeFile("/katana/" + m, fs.readFileSync(path.join(ROOT, m)));
}
for (const d of ["kagami/refs/reference_parts.tsv",
                 "kagami/refs/reference_parts.fasta"]) {
  py.FS.writeFile("/katana/" + d, fs.readFileSync(path.join(ROOT, d)));
}

// Every module must IMPORT under WebAssembly. This is the assertion that would have
// caught kg_identify's module-level `import subprocess` in a browser rather than in a
// mock.
let importErr = null;
try {
  await py.runPythonAsync(`
import sys
sys.path.insert(0, "/katana")
sys.path.insert(0, "/katana/kagami")
import kg_parse, kg_refs, kg_seedmatch, kg_identify, kg_audit, kg_bridge
from core import hashing, lock, parts, result
`);
} catch (err) { importErr = String(err.message).split("\n").slice(-3).join(" "); }
assert("every module the page loads imports under WebAssembly", importErr === null,
       importErr);

const nrefs = await py.runPythonAsync("len(kg_refs.REFERENCE_PARTS)");
assert("the reference set loads in the browser (" + nrefs + " parts)", nrefs > 10000,
       nrefs);

// ---- a real audit, of the real demo, through the page's own code ----
py.FS.mkdirTree("/input");
py.FS.writeFile("/input/demo.gb",
  fs.readFileSync(path.join(ROOT, "kagami", "examples", "demo.gb")));
for (const [k, v] of [["_in_path", "/input/demo.gb"], ["_host_file", ""],
                      ["_host_reca", null], ["_assembly", null],
                      ["_vendor", "Twist"], ["_cap", 5000]]) {
  py.globals.set(k, v);
}

let report = null, auditErr = null;
try { report = JSON.parse(await py.runPythonAsync(code)); }
catch (err) { auditErr = String(err.message).split("\n").slice(-3).join(" "); }
assert("the page's audit block runs under WebAssembly", auditErr === null, auditErr);

if (report) {
  assert("it reports the demo at 843 bp", report.length === 843, report.length);
  assert("identification RAN with no blastn, in a browser",
         report.identification_ran === true, report.identification_ran);
  // Not a block COUNT. It was 4, and became 6 when the gap threshold was lowered from
  // 30 bases to 6 -- the two new rows are the 7 bp and 6 bp leftovers the decomposition
  // used to drop in silence. Counting rows pinned the incomplete behaviour; the real
  // guarantee is that the decomposition accounts for every base of the sequence.
  const covered = report.blocks.reduce((n, b) => n + (b.end - b.start + 1), 0);
  assert("its decomposition accounts for every base of the demo ("
         + covered + " of " + report.length + ")",
         covered === report.length, covered + " of " + report.length);
  assert("and the blocks tile without overlapping",
         report.blocks.slice(1).every((b, i) => b.start === report.blocks[i].end + 1),
         report.blocks.map((b) => b.start + "-" + b.end).join(", "));
  assert("and it finds the construct's real parts, not just gap rows",
         report.blocks.filter((b) => b.identity).length >= 3,
         report.blocks.map((b) => b.identity || "-").join(", "));
  assert("it catches the planted mislabel",
         report.findings.some((f) => f.category === "identity-mislabel"),
         report.findings.map((f) => f.category).join(","));
  assert("and the kind is REVIEW, which is what the pill reads",
         report.kind === "REVIEW", report.kind);
}

// ---- the host off-target path, which the page can now point at any genome ----
// The page shipped one genome and had no way to reach another, so this path only ever
// ran against MG1655 and the browser could not answer the off-target question about any
// other chassis. Exercised here with a stand-in chromosome built from the demo's own
// bases, so the expected match length is known exactly and no sequence is written by
// hand.
await py.runPythonAsync(`
import os
import kg_parse
_piece = kg_parse.parse("/input/demo.gb").seq[100:400]
os.makedirs("/genome", exist_ok=True)
with open("/genome/my_chassis.fna", "w") as _f:
    _f.write(">chr a 300-base slice of the demo, standing in for a chromosome\\n")
    for _i in range(0, len(_piece), 60):
        _f.write(_piece[_i:_i + 60] + "\\n")
`);

function hostFinding(rep) {
  return (rep && rep.findings || []).find((f) => f.category === "host-homology");
}

for (const [reca, want, label] of [[null, "FLAG", "a recA+ host (the default for a file)"],
                                   [false, "NOTE", "a recA- cloning strain"]]) {
  py.globals.set("_in_path", "/input/demo.gb");
  py.globals.set("_host_file", "/genome/my_chassis.fna");
  py.globals.set("_host_reca", reca);
  let rep = null, err = null;
  try { rep = JSON.parse(await py.runPythonAsync(code)); }
  catch (e) { err = String(e.message).split("\n").slice(-3).join(" "); }
  assert("a genome from the computer is read and scanned in the browser, " + label,
         err === null, err);
  const h = hostFinding(rep);
  assert("  the host check RAN rather than skipping", h && h.status !== "SKIP",
         h && h.status);
  assert("  and reports the real length (300 bp), not a ceiling",
         h && h.summary.includes("300"), h && h.summary);
  assert("  and its severity is " + want, h && h.status === want, h && h.status);
}

// A genome the reader cannot parse must say it was the GENOME. Two files reach an audit
// and the error only names one of them.
py.globals.set("_in_path", "/input/demo.gb");
py.FS.writeFile("/genome/not_a_genome.fna", Buffer.from("89504e470d0a1a0a", "hex"));
py.globals.set("_host_file", "/genome/not_a_genome.fna");
py.globals.set("_host_reca", null);
let genomeErr = null;
try { await py.runPythonAsync(code); }
catch (e) { genomeErr = String(e.message); }
assert("an unreadable genome is refused, not silently skipped", genomeErr !== null,
       "it returned a report");
assert("and the message says the GENOME was the problem, not the sequence",
       genomeErr !== null && /host genome/i.test(genomeErr)
       && /was not the problem/i.test(genomeErr),
       genomeErr && genomeErr.split("\n").slice(-3).join(" "));

// ---- and a file that is not a sequence is refused in the browser too ----
py.globals.set("_host_file", "");
py.globals.set("_host_reca", null);
py.FS.writeFile("/input/photo.png", Buffer.from("89504e470d0a1a0a", "hex"));
py.globals.set("_in_path", "/input/photo.png");
let refusal = null;
try { await py.runPythonAsync(code); }
catch (err) {
  const m = String(err.message).match(/NotASequenceFile:\s*([\s\S]*?)(?:\n\n|$)/);
  refusal = m ? m[1].trim() : "(raised, but not NotASequenceFile)";
}
assert("a PNG is refused in the browser, not audited as 0 bp", refusal !== null,
       "it was audited");
assert("and the refusal names the file type, so the page can show it",
       refusal && refusal.includes("PNG"), refusal);

finish();
