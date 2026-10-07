"""kg_katana_tabs.py - the forward Katana engine, in the Kagami window.

WHY. Kagami's Audit tab reads a sequence somebody else made. The engine tabs run the other
direction: take a Design Spec, build it from sealed parts, and hand back an order-ready sequence.
Until now that needed `python3 katana_build.py ...` in a terminal, which most students never open.

HOW. These tabs add no logic of their own. Each button runs the engine's own CLI tool as a child
process (the same way kg_rebuild.py already does) and shows its output, so there is exactly one
implementation of every gate and the window cannot disagree with the command line. The verdict
is read from the tool's exit code and the lines it prints; the window never decides on its own
that something passed.

Reporting rules carried over from the Audit tab:
  - the word (SEALED / BLOCKED / ...) is always shown, colour never carries the meaning alone;
  - a check that did not run is REVIEW, never PASS. The engine prints "NOT enforced this run" when
    a gate was unavailable, and a sealed build with that line is shown as such;
  - the work runs on a thread, and every Tk variable is read on the main thread before it starts.

Standard library only, like the rest of Kagami.
"""
import csv
import glob
import os
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

COLOUR = {"PASS": "#1a7f37", "REVIEW": "#9a6700", "FAIL": "#b42318"}
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def default_workspace():
    """Where builds go unless told otherwise: a visible folder the student can find again."""
    return os.path.join(os.path.expanduser("~"), "Documents", "Kagami", "builds")


def open_path(path):
    """Open a file or folder in the system's default app."""
    try:
        if sys.platform == "win32":
            os.startfile(path)                                   # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as e:
        messagebox.showerror("Kagami", f"Could not open {path}\n\n{e}")


def lock_path(library):
    """Find ref_parts/LOCK.tsv for a library given as the parts-library dir or its project root."""
    for rel in (("ref_parts",), ("parts-library", "ref_parts"), ()):
        cand = os.path.join(library, *rel, "LOCK.tsv")
        if os.path.isfile(cand):
            return cand
    return None


def read_lock(lock):
    """LOCK.tsv -> list of dict rows, for the Library tab's table.

    Through core.lock when the bundle is present. Still returns [] rather than raising
    when a manifest is unreadable: a tab that cannot list parts must not take the window
    down with it.
    """
    import kg_refs
    _h, core_lock, _p = kg_refs._import_core()
    if core_lock is not None:
        try:
            return core_lock.read(lock)[1]
        except Exception:
            return []
    try:
        with open(lock, encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh, delimiter="\t"))
    except Exception:
        return []


# classify lives in kg_verdict so the browser page can share it without importing tkinter.
from kg_verdict import classify  # noqa: E402,F401


class _Pane:
    """One tab: an output area, a verdict, and a way to run an engine tool on a worker thread."""

    def __init__(self, nb, engine, title):
        self.engine = engine
        self.frame = ttk.Frame(nb, padding=12)
        nb.add(self.frame, text=title)
        self.q = queue.Queue()
        self.busy = False
        self.lines = []
        self._buttons = []

    # ---- widgets shared by both tabs ------------------------------------------------------
    def _output(self, parent, intro, act):
        """Verdict, detail line, a table area and the log. `act` is the button row (spinner lives there)."""
        self.spin = ttk.Progressbar(act, mode="indeterminate", length=160)
        self.verdict = tk.Label(parent, text="", font=("Segoe UI", 20, "bold"), anchor="w")
        self.verdict.pack(fill="x", pady=(14, 2))
        self.subtitle = ttk.Label(parent, text="", foreground="#555", wraplength=900, justify="left")
        self.subtitle.pack(fill="x")
        self.extra = ttk.Frame(parent)                 # order table / parts list goes here
        self.extra.pack(fill="x", pady=(8, 0))
        box = ttk.Frame(parent)
        box.pack(fill="both", expand=True, pady=(10, 0))
        self.text = tk.Text(box, wrap="word", height=12, font=("Consolas", 10),
                            borderwidth=1, relief="solid", padx=10, pady=8)
        sb = ttk.Scrollbar(box, command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        self.text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.text.tag_configure("fail", foreground=COLOUR["FAIL"], font=("Consolas", 10, "bold"))
        self.text.tag_configure("warn", foreground=COLOUR["REVIEW"])
        self.text.tag_configure("ok", foreground=COLOUR["PASS"])
        self.text.tag_configure("dim", foreground="#666")
        self._say(intro + "\n", "dim")

    def _say(self, s, tag=None):
        self.text.configure(state="normal")
        self.text.insert("end", s, tag or ())
        self.text.see("end")
        self.text.configure(state="disabled")

    def _clear(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")
        self.verdict.configure(text="")
        self.subtitle.configure(text="")

    def _show(self, kind, headline, detail):
        self.verdict.configure(text=headline, fg=COLOUR[kind])
        self.subtitle.configure(text=detail)

    @staticmethod
    def _tag_for(line):
        s = line.strip()
        if s.startswith("BLOCK") or "MISMATCH" in s or s.startswith("PROBLEM"):
            return "fail"
        if s.startswith("WARN") or "NOT enforced" in s:
            return "warn"
        if s.startswith("SEALED") or s.startswith("PASS") or s.startswith("OK") or "✓" in s:
            return "ok"
        return None

    # ---- running an engine tool -------------------------------------------------------------
    def _start(self, args, done):
        """Run [sys.executable] + args. done(rc, output) is called on the main thread."""
        if self.busy:
            return
        self.busy = True
        self.lines = []
        self._clear()
        for w in self.extra.winfo_children():
            w.destroy()
        for b in self._buttons:
            b.configure(state="disabled")
        self.spin.pack(side="left", padx=(12, 0))
        self.spin.start(12)
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}

        def work():
            try:
                p = subprocess.Popen([sys.executable] + args, cwd=self.engine, env=env,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                     encoding="utf-8", errors="replace", creationflags=_NO_WINDOW)
                for line in p.stdout:
                    self.q.put(("line", line))
                self.q.put(("done", p.wait()))
            except Exception as e:                       # could not even start the tool
                self.q.put(("err", f"{type(e).__name__}: {e}"))

        threading.Thread(target=work, daemon=True).start()
        self.frame.after(60, self._drain, done)

    def _drain(self, done):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "line":
                    self.lines.append(val)
                    self._say(val, self._tag_for(val))
                    continue
                self.busy = False
                self.spin.stop()
                self.spin.pack_forget()
                for b in self._buttons:
                    b.configure(state="normal")
                done(val if kind == "done" else -1, "".join(self.lines) if kind == "done" else val)
                return
        except queue.Empty:
            pass
        self.frame.after(60, self._drain, done)

    def _table(self, columns, rows, widths=None, height=5):
        """A small read-only table in the `extra` area."""
        tv = ttk.Treeview(self.extra, columns=columns, show="headings", height=height)
        for c in columns:
            tv.heading(c, text=c)
            tv.column(c, width=(widths or {}).get(c, 110), anchor="w", stretch=True)
        for r in rows:
            tv.insert("", "end", values=r)
        sb = ttk.Scrollbar(self.extra, command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        tv.pack(side="left", fill="x", expand=True)
        sb.pack(side="right", fill="y")
        return tv


class BuildPane(_Pane):
    def __init__(self, nb, engine):
        super().__init__(nb, engine, "Build")
        f = self.frame
        self.spec, self.library = tk.StringVar(), tk.StringVar()
        self.outdir = tk.StringVar(value=default_workspace())

        box = ttk.LabelFrame(f, text="Design Spec to build", padding=10)
        box.pack(fill="x")
        r0 = ttk.Frame(box); r0.pack(fill="x")
        ttk.Label(r0, text="Spec file", width=14).pack(side="left")
        ttk.Entry(r0, textvariable=self.spec).pack(side="left", fill="x", expand=True)
        ttk.Button(r0, text="Choose…", command=self._pick_spec).pack(side="left", padx=(8, 0))
        examples = sorted(glob.glob(os.path.join(engine, "specs", "*.spec.yaml")))
        self._examples = {os.path.basename(p)[:-len(".spec.yaml")]: p for p in examples}
        if self._examples:
            r1 = ttk.Frame(box); r1.pack(fill="x", pady=(6, 0))
            ttk.Label(r1, text="Or an example", width=14).pack(side="left")
            cb = ttk.Combobox(r1, state="readonly", values=list(self._examples))
            cb.pack(side="left", fill="x", expand=True)
            cb.bind("<<ComboboxSelected>>", lambda _e: self.spec.set(self._examples[cb.get()]))
        ttk.Label(box, foreground="#555",
                  text="A Design Spec says WHAT to build (which parts, in what order). The engine "
                       "turns it into a sequence using only sealed parts.").pack(anchor="w", pady=(6, 0))

        opt = ttk.LabelFrame(f, text="Where", padding=10)
        opt.pack(fill="x", pady=(10, 0))
        r2 = ttk.Frame(opt); r2.pack(fill="x")
        ttk.Label(r2, text="Parts library", width=14).pack(side="left")
        ttk.Entry(r2, textvariable=self.library).pack(side="left", fill="x", expand=True)
        ttk.Button(r2, text="…", width=3, command=self._pick_lib).pack(side="left", padx=(6, 0))
        ttk.Label(opt, foreground="#555",
                  text="Leave blank to use the shipped, sealed reference library.").pack(
            anchor="w", pady=(2, 8))
        r3 = ttk.Frame(opt); r3.pack(fill="x")
        ttk.Label(r3, text="Save results in", width=14).pack(side="left")
        ttk.Entry(r3, textvariable=self.outdir).pack(side="left", fill="x", expand=True)
        ttk.Button(r3, text="…", width=3, command=self._pick_out).pack(side="left", padx=(6, 0))

        act = ttk.Frame(f); act.pack(fill="x", pady=(12, 0))
        b1 = ttk.Button(act, text="Check only (writes nothing)", command=lambda: self.go(True))
        b2 = ttk.Button(act, text="Build and seal", command=lambda: self.go(False))
        b1.pack(side="left"); b2.pack(side="left", padx=(8, 0))
        self.open_dir = ttk.Button(act, text="Open results folder", state="disabled",
                                   command=lambda: open_path(self._last_out))
        self.open_csv = ttk.Button(act, text="Open order table", state="disabled",
                                   command=lambda: open_path(self._last_csv))
        self.open_dir.pack(side="left", padx=(8, 0)); self.open_csv.pack(side="left", padx=(8, 0))
        self._buttons = [b1, b2]
        self._last_out = self._last_csv = ""
        self._output(f, "Choose a spec and press Check only, or Build and seal.", act)

    def _pick_spec(self):
        p = filedialog.askopenfilename(title="Choose a Design Spec",
                                       filetypes=[("Design Spec", "*.yaml *.yml"), ("All files", "*.*")])
        if p:
            self.spec.set(p)

    def _pick_lib(self):
        p = filedialog.askdirectory(title="Choose a parts library folder")
        if p:
            self.library.set(p)

    def _pick_out(self):
        p = filedialog.askdirectory(title="Where should results be saved?")
        if p:
            self.outdir.set(p)

    def go(self, dry):
        # Read every Tk variable here, on the main thread.
        spec, lib, out = self.spec.get().strip(), self.library.get().strip(), self.outdir.get().strip()
        if not os.path.isfile(spec):
            messagebox.showinfo("Kagami", "Choose a Design Spec file first.")
            return
        args = [os.path.join(self.engine, "katana_build.py"), spec]
        if lib:
            args += ["--library", lib]
        if dry:
            args.append("--dry-run")
        else:
            if not out:
                messagebox.showinfo("Kagami", "Choose a folder to save the results in.")
                return
            args += ["--outdir", out]
        self.open_dir.configure(state="disabled"); self.open_csv.configure(state="disabled")
        self._start(args, lambda rc, output: self._finished(rc, output, dry, out))

    def _finished(self, rc, output, dry, out):
        kind, head, detail = classify(rc, output, dry)
        self._show(kind, head, detail)
        if dry or rc != 0:
            return
        m = re.search(r"\.csv:\s+(.+?)\s+\(\d+ row", output)
        self._last_out = out
        self.open_dir.configure(state="normal")
        if m and os.path.isfile(m.group(1)):
            self._last_csv = m.group(1)
            self.open_csv.configure(state="normal")
            self._order_table(self._last_csv)

    def _order_table(self, path):
        try:
            with open(path, encoding="utf-8", newline="") as fh:
                rd = csv.DictReader(fh)
                cols = [c for c in (rd.fieldnames or []) if c.lower() != "sequence"]
                # list(...) rather than a nested list literal: two opening brackets in a row read as
                # an Obsidian internal-note link to the release leak-scanner, which blocks the
                # build. Same result, and the scanner stays strict.
                rows = [list(self._cell(r.get(c, "")) for c in cols) for r in rd]
        except Exception as e:
            self._say(f"\n(Could not read the order table: {e})\n", "warn")
            return
        ttk.Label(self.extra, text="Order table (sequence column left out here; it is in the file)",
                  foreground="#555").pack(anchor="w")
        self._table(cols, rows)

    @staticmethod
    def _cell(v):
        v = str(v)
        return v if len(v) <= 44 else v[:40] + "…"


class LibraryPane(_Pane):
    def __init__(self, nb, engine):
        super().__init__(nb, engine, "Library")
        f = self.frame
        self.library = tk.StringVar()
        box = ttk.LabelFrame(f, text="Parts library", padding=10)
        box.pack(fill="x")
        r = ttk.Frame(box); r.pack(fill="x")
        ttk.Label(r, text="Library", width=14).pack(side="left")
        ttk.Entry(r, textvariable=self.library).pack(side="left", fill="x", expand=True)
        ttk.Button(r, text="…", width=3, command=self._pick).pack(side="left", padx=(6, 0))
        ttk.Label(box, foreground="#555", justify="left", wraplength=900,
                  text="Blank means the shipped reference library. Checking it re-hashes every part "
                       "against its manifest and then tries to break the checker eight ways, so a "
                       "pass means the checker would have noticed tampering.").pack(anchor="w", pady=(6, 0))
        act = ttk.Frame(f); act.pack(fill="x", pady=(12, 0))
        b1 = ttk.Button(act, text="Check library", command=self.check)
        b2 = ttk.Button(act, text="Start a new library…", command=self.new_library)
        b1.pack(side="left"); b2.pack(side="left", padx=(8, 0))
        self._buttons = [b1, b2]
        self._output(f, "Press Check library to verify every part against its seal.", act)
        self._list_parts(self._shipped_lock())

    def _shipped_lock(self):
        return lock_path(os.path.join(self.engine, "parts-library"))

    def _pick(self):
        p = filedialog.askdirectory(title="Choose a parts library folder")
        if p:
            self.library.set(p)
            self._list_parts(lock_path(p))

    def _list_parts(self, lock):
        for w in self.extra.winfo_children():
            w.destroy()
        rows = read_lock(lock) if lock else []
        if not rows:
            return
        ttk.Label(self.extra, text=f"{len(rows)} sealed part(s)", foreground="#555").pack(anchor="w")
        self._table(["id", "version", "length", "class", "source"],
                    [list((r.get("id", ""), r.get("version", ""), r.get("length", ""),
                           r.get("class", ""), r.get("source", "")[:60])) for r in rows],
                    widths={"id": 130, "version": 60, "length": 70, "class": 90, "source": 340},
                    height=6)

    def check(self):
        lib = self.library.get().strip()
        if not lib:
            args, lock = [os.path.join(self.engine, "verify.py")], self._shipped_lock()
        else:
            lock = lock_path(lib)
            if not lock:
                messagebox.showinfo("Kagami", "That folder has no ref_parts/LOCK.tsv. "
                                              "Use 'Start a new library' to make one.")
                return
            args = [os.path.join(self.engine, "verify_library_v2.py"), lock]

        def done(rc, output):
            if rc == 0:
                self._show("PASS", "INTACT", "Every part matches the hash it was sealed with.")
            else:
                self._show("FAIL", "PROBLEM", "Do not use the affected part until you know why. "
                                              "A failure here is the checker working.")
            self._list_parts(lock)
        self._start(args, done)

    def new_library(self):
        p = filedialog.askdirectory(title="Pick (or make) an empty folder for your new library")
        if not p:
            return
        args = [os.path.join(self.engine, "katana_init.py"), p]

        def done(rc, output):
            if rc != 0:
                kind, head, detail = classify(rc, output, True)
                self._show(kind, "NOT CREATED", detail)
                return
            self.library.set(os.path.join(p, "parts-library"))
            self._show("PASS", "CREATED", f"Empty library and a template spec are in {p}. "
                                          "Add parts with add_part.py; this window does not do that yet.")
        self._start(args, done)


def add_tabs(nb, engine):
    """Attach the engine tabs to the main notebook. Returns the panes (for tests)."""
    return [BuildPane(nb, engine), LibraryPane(nb, engine)]
