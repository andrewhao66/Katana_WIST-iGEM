"""kg_verdict.py - how a Katana engine run is worded. No GUI, no I/O, standard library only.

Lives in its own module because TWO front ends need the identical wording: the Tk window
(kg_katana_tabs.py) and the browser page (web/kg_web.py, which cannot import tkinter). One copy means
the two cannot drift, and a "gate did not run" can never be called a PASS in one place and not the
other.
"""


def classify(rc, out, dry):
    """Turn an engine run into (kind, headline, detail). Pure, so it can be tested without a window.

    kind is PASS / REVIEW / FAIL. A run that exited 0 but says a gate was not enforced is REVIEW:
    claiming PASS there would be exactly the silent thinner report the Audit tab refuses to give.
    """
    lines = [ln.rstrip() for ln in out.splitlines() if ln.strip()]
    if rc != 0:
        block = [ln.strip() for ln in lines if ln.strip().startswith("BLOCK")]
        detail = block[-1] if block else (lines[-1].strip() if lines else "The engine stopped.")
        return "FAIL", "BLOCKED", detail
    unenforced = [ln.strip() for ln in lines if "NOT enforced" in ln]
    sealed = [ln.strip() for ln in lines if ln.strip().startswith("SEALED:")]
    if dry:
        if unenforced:
            return "REVIEW", "CHECKED - a gate did not run", unenforced[0]
        return "PASS", "CHECKED", "Stages 1-4b passed. Dry run: nothing was written."
    if not sealed:
        return "REVIEW", "FINISHED - no seal line", "The engine exited cleanly but printed no SEALED line."
    if unenforced:
        return "REVIEW", "SEALED - a gate did not run", unenforced[0]
    return "PASS", "SEALED", sealed[0].replace("SEALED:", "seq_sha256").strip()
