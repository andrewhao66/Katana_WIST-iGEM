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

    # The kind comes from the verdict the engine computed, and ONLY from it. This used to
    # decide for itself, by looking at not_run alone -- so a build with real FLAG findings
    # (off-target matches away from any expected locus) was shown as "CHECKED / Stages
    # 1-4b passed", while BuildResult.verdict said REVIEW. The same result read two ways,
    # in both directions depending on what the finding was.
    #
    # One decision now. not_run only words the reason, because "a gate did not run" and
    # "a gate ran and found something" need different sentences even though both are
    # REVIEW.
    def _why():
        if not_run:
            return "a gate did not run", "Not enforced this run: " + ", ".join(not_run)
        flags = [f.get("summary", "") for f in (d.get("findings") or [])
                 if f.get("status") == "FLAG"]
        n = len(flags)
        return ("%d to resolve" % n if n else "to resolve",
                flags[0] if n == 1 else
                "; ".join(flags[:2]) + (" (+%d more)" % (n - 2) if n > 2 else ""))

    # A FLOOR, not a second decision. The kind comes from `verdict` -- but this function
    # also accepts a plain dict, from an older --json file or another tool, and such a
    # dict can be self-contradictory: verdict PASS with a non-empty not_run. Trusting
    # `verdict` alone there would report a pass for a build where a gate did not run,
    # which is the failure this whole tier exists to prevent, re-entering through the one
    # door that takes input from outside. Two sources disagreeing get the more cautious
    # reading AND the reason, rather than the optimistic one in silence.
    if verdict == "PASS" and not_run:
        verdict = "REVIEW"

    if d.get("dry_run"):
        if verdict == "REVIEW":
            tag, detail = _why()
            return "REVIEW", "CHECKED - " + tag, detail
        return "PASS", "CHECKED", "Stages 1-4b passed. Dry run: nothing was written."

    if not d.get("seq_sha256"):
        return ("REVIEW", "FINISHED - no seal",
                "The engine exited cleanly but recorded no sealed hash.")

    if verdict == "REVIEW":
        tag, detail = _why()
        return ("REVIEW", "SEALED - " + tag,
                detail + " | seq_sha256 " + d["seq_sha256"])

    return "PASS", "SEALED", "seq_sha256 " + d["seq_sha256"]
