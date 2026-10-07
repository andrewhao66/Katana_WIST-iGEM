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
