/* web_render_harness.js — run ui/web/index.js's render() against crafted reports.
 *
 * The rendering path decides what colour a verdict is and what glyph a finding gets.
 * Those are the two places where "we did not check" could come out looking like
 * "checked and fine", so they are worth testing against the real code rather than by
 * reading it. This stubs just enough DOM for index.js to load, then calls render().
 *
 * Driven by tests/test_web_render.py, which prints the results and sets the exit code.
 */
const fs = require("fs");
const path = require("path");

function makeEl() {
  return { textContent: "", innerHTML: "", className: "", style: {},
           classList: { add() {}, remove() {}, contains: () => false },
           addEventListener() {}, click() {}, value: "", files: null };
}

const els = {};
global.document = {
  getElementById: (id) => (els[id] = els[id] || makeEl()),
};
global.loadPyodide = undefined;    // boot() fails and is caught; render() is unaffected
global.fetch = () => Promise.reject(new Error("no network in the harness"));

const src = fs.readFileSync(
  path.join(__dirname, "..", "ui", "web", "index.js"), "utf8");
// index.js is a plain script. Evaluate it, then reach the functions it defined.
const fn = new Function("return (function(){" + src +
  "\nreturn { render: render, esc: esc, STAT: STAT, ORDER: ORDER };})()");
const mod = fn();

const results = [];
function assert(name, cond, detail) {
  results.push({ name, ok: !!cond, detail: String(detail == null ? "" : detail) });
}

function report(over) {
  return Object.assign({
    name: "t", length: 100, topology: "linear", joined: [],
    verdict: "PASS", kind: "PASS", identification_ran: true,
    blocks: [{ start: 1, end: 10, strand: 1, claim: "c", identity: "i", role: "r",
               pident: 100, coverage: 1, note: null, alternatives: [] }],
    findings: [],
  }, over);
}

// ---- the pill's colour must come from the engine's kind, not from the headline ----
// verdict_kind() is documented as "the canonical verdict token for logic, colour and
// exit codes". The headline is a human sentence and will be reworded.
mod.render(report({ kind: "FAIL", verdict: "Do not order this — 2 blocking problems" }));
assert("a FAIL kind renders as fail even when the headline does not start with FAIL",
       els.pill.className.includes("bad"), els.pill.className);

mod.render(report({ kind: "REVIEW", verdict: "2 things to resolve before ordering" }));
assert("a REVIEW kind renders as review even when the headline is reworded",
       els.pill.className.includes("cond"), els.pill.className);

mod.render(report({ kind: "PASS", verdict: "PASS — 3 notes" }));
assert("a PASS kind renders as pass", els.pill.className.includes("ok"),
       els.pill.className);

// An unknown kind must NOT come out green. A new tier added to the engine reaching an
// old page is exactly the case where an optimistic default is dangerous.
mod.render(report({ kind: "SOMETHING_NEW", verdict: "Something new happened" }));
assert("an unknown kind does not render as pass",
       !els.pill.className.includes("ok"), els.pill.className);

// ---- SKIP must never look like a tick ----
mod.render(report({ findings: [
  { category: "c", status: "SKIP", summary: "not checked", loc: null,
    detail: "no host given", fix: null }] }));
assert("a SKIP finding does not render the PASS tick",
       !els.findings.innerHTML.includes("✓"), els.findings.innerHTML.slice(0, 120));
assert("and it renders the skip glyph", els.findings.innerHTML.includes("–"),
       els.findings.innerHTML.slice(0, 120));

// An unrecognised status must not render as a tick either.
mod.render(report({ findings: [
  { category: "c", status: "WHAT", summary: "s", loc: null, detail: null, fix: null }] }));
assert("an unrecognised status does not render the PASS tick",
       !els.findings.innerHTML.includes("✓"), els.findings.innerHTML.slice(0, 120));

// ---- ordering: a FAIL must come before a PASS, and an unknown must not sort last ----
mod.render(report({ findings: [
  { category: "a", status: "PASS", summary: "ok-thing", loc: null, detail: null, fix: null },
  { category: "b", status: "FAIL", summary: "bad-thing", loc: null, detail: null, fix: null },
  { category: "c", status: "WHAT", summary: "odd-thing", loc: null, detail: null, fix: null }] }));
const html = els.findings.innerHTML;
assert("a FAIL is listed before a PASS",
       html.indexOf("bad-thing") < html.indexOf("ok-thing"),
       html.replace(/<[^>]+>/g, "|").slice(0, 160));
assert("an unrecognised status is not buried below the passes",
       html.indexOf("odd-thing") < html.indexOf("ok-thing"),
       html.replace(/<[^>]+>/g, "|").slice(0, 160));

// ---- escaping ----
mod.render(report({ blocks: [
  { start: 1, end: 2, strand: 1, claim: "<img src=x onerror=alert(1)>",
    identity: "<script>bad()</script>", role: "<b>r</b>",
    pident: 99, coverage: 1, note: null, alternatives: [] }] }));
assert("a block's claim is escaped", !els.blocks.innerHTML.includes("<img src=x"),
       els.blocks.innerHTML.slice(0, 140));
assert("a block's identity is escaped",
       !els.blocks.innerHTML.includes("<script>"), els.blocks.innerHTML.slice(0, 140));

mod.render(report({ findings: [
  { category: "c", status: "FLAG", summary: "<script>x()</script>",
    loc: "<b>1..2</b>", detail: "<img src=x onerror=1>", fix: "<i>f</i>" }] }));
assert("a finding's summary is escaped",
       !els.findings.innerHTML.includes("<script>"), els.findings.innerHTML.slice(0, 140));
assert("a finding's detail is escaped",
       !els.findings.innerHTML.includes("<img src=x"), els.findings.innerHTML.slice(0, 140));
assert("a finding's loc is escaped",
       !els.findings.innerHTML.includes("<b>1..2</b>"), els.findings.innerHTML.slice(0, 140));

process.stdout.write(JSON.stringify(results));
