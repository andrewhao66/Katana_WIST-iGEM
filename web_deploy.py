#!/usr/bin/env python3
"""web_deploy.py — assemble the static site and, on request, publish it.

`katana deploy` lands here.

The published site is not just `ui/web/`. Pyodide fetches the engine modules and the
reference set over HTTP, so the deployable artifact is a staging directory holding the
page plus `core/`, the audit half of `kagami/`, the reference set and the bundled genome.
This script assembles exactly the file list `web_serve.SERVE` names, so the published
site and the local server can never be serving different things -- which is the whole
point: a published page that is a hand-assembled variant of the engine is the same defect
as a construct assembled by hand.

By default it only STAGES, and prints what it would publish. Publishing is an outward
action that needs saying out loud, so it takes --push and a remote.

The iGEM GitLab project is never pushed to by this script. The only sanctioned outward
destination is the separate GitHub repository the team chose for the web test.
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

DEFAULT_REMOTE = "https://github.com/andrewhao66/iGEM-katana-webtest.git"

# Never, whatever is asked. The iGEM GitLab project holds the team's real work, and a
# generated site force-pushed over its main branch is not something anybody recovers from
# a command line. web_deploy's docstring used to promise this; a docstring is not a
# control, and --remote was unrestricted.
FORBIDDEN_HOSTS = ("gitlab.igem.org",)

# Written into a staging directory so a later deploy knows the directory is ITS OWN
# output and may replace it. Without this, stage() ran shutil.rmtree() on whatever --out
# named: a directory holding one unrelated file came back holding eighteen staged ones,
# and the unrelated file was gone. `katana deploy --out .` deleted the repository and
# then failed because its own sources had gone with it.
MARKER = ".katana-staging"


class UnsafeTarget(Exception):
    """This directory is not ours to delete, so deploy will not delete it."""


def _host(url):
    """The host part of a git remote, for https:// and git@host:path alike."""
    u = str(url).strip()
    if "://" in u:
        u = u.split("://", 1)[1]
    if "@" in u.split("/", 1)[0]:
        u = u.split("@", 1)[1]
    return u.split("/", 1)[0].split(":", 1)[0].lower()


def remote_allowed(url, allow_other=False):
    """May deploy push to `url`? Returns (allowed, reason).

    Publishing is outward-facing and irreversible-ish: publish() force-pushes, because a
    generated artifact's history is the bundle's history. Force-pushing somewhere
    unintended is a different matter, so the destination is checked rather than trusted.
    """
    host = _host(url)
    for bad in FORBIDDEN_HOSTS:
        if host == bad or host.endswith("." + bad):
            return False, ("REFUSED: %s is on %s. Katana's web deploy force-pushes a "
                           "generated site, and the iGEM GitLab project holds the team's "
                           "real work -- replacing its branch is not recoverable from "
                           "here. Publish to the separate web repository instead:\n"
                           "       %s" % (url, bad, DEFAULT_REMOTE))
    if url.rstrip("/") == DEFAULT_REMOTE.rstrip("/"):
        return True, "the sanctioned web repository"
    if allow_other:
        return True, "allowed explicitly with --allow-remote"
    return False, ("REFUSED: %s is not the repository this deploy is set up for.\n"
                   "       The default is  %s\n"
                   "       If you really mean this one, say so: add --allow-remote.\n"
                   "       It force-pushes, so it will replace whatever is on that "
                   "branch." % (url, DEFAULT_REMOTE))


def _refuse_unsafe(target):
    """Raise unless `target` is ours to create or replace.

    Deploy is allowed to destroy exactly one thing: a staging directory it made. Anything
    else -- the repository, a home directory, a folder with somebody's week in it -- is
    refused with its own name in the message.
    """
    t = os.path.abspath(target)
    if not os.path.exists(t):
        return                                  # nothing to destroy

    if not os.path.isdir(t):
        raise UnsafeTarget("REFUSED: %s is a file, not a directory." % t)

    # Named places that are never a staging directory, however empty they look.
    never = {os.path.abspath(os.sep), os.path.abspath(os.path.expanduser("~")),
             os.path.abspath(HERE), os.path.abspath(os.path.dirname(HERE)),
             os.path.abspath(os.getcwd())}
    if t in never:
        raise UnsafeTarget(
            "REFUSED: %s is not a staging directory -- it is the repository, your home "
            "directory, or the directory you are standing in.\n"
            "       Deploy writes a throwaway copy of the site. Give it a path of its "
            "own:\n"
            "       ./katana deploy --out _site" % t)

    # A directory that holds the engine is the repository under another name.
    if os.path.isfile(os.path.join(t, "katana_build.py")):
        raise UnsafeTarget(
            "REFUSED: %s holds Katana's own files, so deploying into it would delete the "
            "engine.\n       Give it a path of its own:  ./katana deploy --out _site" % t)

    entries = [e for e in os.listdir(t) if e not in (".DS_Store",)]
    if not entries:
        return                                  # empty: ours to fill
    if os.path.isfile(os.path.join(t, MARKER)):
        return                                  # our own previous output: ours to replace

    raise UnsafeTarget(
        "REFUSED: %s is not empty and was not written by deploy, so it will not be "
        "deleted.\n"
        "       It holds %d item(s), starting with: %s\n"
        "       Either empty it yourself, or give deploy a path of its own:\n"
        "       ./katana deploy --out _site"
        % (t, len(entries), ", ".join(sorted(entries)[:4])))

# Where each served file lands in the published site. The page is served from the root,
# so index.html and index.js move up out of ui/web/; everything else keeps its path,
# because that is what the page's own fetches expect.
def published_path(rel):
    if rel == "ui/web/index.html":
        return "index.html"
    if rel == "ui/web/index.js":
        return "index.js"
    return rel


NOJEKYLL = (
    "# GitHub Pages runs Jekyll by default, which SKIPS files and directories whose\n"
    "# names begin with an underscore. Nothing here starts with one today, but the\n"
    "# engine vendors _vendor/ and a future page file could, and a silently missing\n"
    "# module would read as a broken page rather than a missing file. Disable it.\n"
)

README = """# katana-kagami — check a sequence, in your browser

This is the published build of katana-kagami, the browser front end to Katana's sequence
auditor. Open the page and drop a
GenBank, FASTA or spreadsheet file on it.

**Nothing is uploaded.** The page runs Katana's own audit modules through Pyodide —
CPython compiled to WebAssembly — so the sequence you check never leaves your machine.

It is not a reimplementation. The `.py` files here are the same ones the command-line
tool runs; two implementations of one check drift apart, and that drift is the failure
the project exists to prevent.

## What it does and does not do

It identifies the parts in a sequence against {nrefs} public references and reports what
it finds: a label that disagrees with its bases, a truncated part, a broken reading
frame, restriction sites that matter for your assembly method, GC and homopolymer
outliers, direct repeats, host homology, and size against a vendor cap.

It does **not** seal parts or build constructs. Those need a parts library that lives in
git, with a history you can audit — so they belong to the command-line tool.

## Source

Generated by `web_deploy.py` from the Katana bundle. Do not edit these files here: edit
them in the bundle and re-run the deploy, or the published page becomes a hand-assembled
variant of the engine, which is exactly what this project refuses to allow for DNA.
"""


def stage(target):
    """Copy the deployable file set into `target`. Returns (files, bytes)."""
    sys.path.insert(0, HERE)
    import web_serve

    missing = web_serve.missing_files()
    if missing:
        raise SystemExit("BLOCK: these files are missing, so the site would be "
                         "incomplete:\n  " + "\n  ".join(missing))

    _refuse_unsafe(target)
    if os.path.isdir(target):
        shutil.rmtree(target)
    os.makedirs(target)
    with open(os.path.join(target, MARKER), "w", encoding="utf-8") as f:
        f.write("Written by web_deploy.py. Its presence is what allows a later deploy to\n"
                "replace this directory; without it, deploy refuses rather than deleting\n"
                "a directory it cannot prove is its own.\n")
    # The marker is deploy's own bookkeeping and has no business on the published site,
    # where `git add -A` would otherwise carry it.
    with open(os.path.join(target, ".gitignore"), "w", encoding="utf-8") as f:
        f.write("# web_deploy's own bookkeeping, not part of the site.\n%s\n" % MARKER)

    total = 0
    files = []
    for rel in web_serve.SERVE:
        dest = os.path.join(target, published_path(rel))
        os.makedirs(os.path.dirname(dest) or target, exist_ok=True)
        shutil.copyfile(os.path.join(HERE, rel), dest)
        size = os.path.getsize(dest)
        total += size
        files.append((published_path(rel), size))

    with open(os.path.join(target, ".nojekyll"), "w", encoding="utf-8") as f:
        f.write(NOJEKYLL)

    nrefs = "?"
    try:
        with open(os.path.join(target, "kagami", "refs", "reference_parts.fasta"),
                  encoding="utf-8") as f:
            nrefs = "{:,}".format(sum(1 for ln in f if ln.startswith(">")))
    except Exception:
        pass
    with open(os.path.join(target, "README.md"), "w", encoding="utf-8") as f:
        f.write(README.format(nrefs=nrefs))

    return files, total


def publish(target, remote, branch="main", allow_other=False):
    """Commit the staged site and push it. Outward-facing; only called with --push.

    The destination is checked HERE as well as in main(), because this is the function
    that force-pushes and a caller that reaches it directly must not get a free pass.
    """
    allowed, why = remote_allowed(remote, allow_other=allow_other)
    if not allowed:
        raise SystemExit(why)

    def git(*args):
        p = subprocess.run(["git"] + list(args), cwd=target,
                           capture_output=True, text=True)
        if p.returncode != 0:
            raise SystemExit("BLOCK: git %s failed:\n%s"
                             % (" ".join(args), (p.stdout + p.stderr).strip()))
        return p.stdout

    git("init", "-q", "-b", branch)
    git("add", "-A")
    git("-c", "user.name=katana-deploy",
        "-c", "user.email=katana-deploy@localhost",
        "commit", "-q", "-m",
        "Publish katana-kagami\n\n"
        "Generated by web_deploy.py from the Katana bundle. The .py files here are the\n"
        "engine's own modules, not a reimplementation.")
    git("remote", "add", "origin", remote)
    # Force, because this is a generated artifact: its history is the bundle's history,
    # and a published site that has diverged from the bundle is the defect, not a
    # change worth preserving.
    git("push", "--force", "origin", branch)
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    target = os.path.join(HERE, "_site")
    remote = DEFAULT_REMOTE
    do_push = False
    allow_other = False
    for i, tok in enumerate(argv):
        if tok == "--out" and i + 1 < len(argv):
            target = os.path.abspath(argv[i + 1])
        elif tok == "--remote" and i + 1 < len(argv):
            remote = argv[i + 1]
        elif tok == "--push":
            do_push = True
        elif tok == "--allow-remote":
            allow_other = True

    # Check the destination BEFORE staging. Staging copies 26 MB and deletes a directory;
    # doing that work and then refusing to publish wastes it and, worse, leaves somebody
    # believing the refusal came after something was sent.
    if do_push:
        allowed, why = remote_allowed(remote, allow_other=allow_other)
        if not allowed:
            print(why)
            return 2

    try:
        files, total = stage(target)
    except UnsafeTarget as exc:
        print(str(exc))
        return 2
    print("Staged the site in %s" % target)
    print()
    for rel, size in files:
        print("  %-44s %8.1f KB" % (rel, size / 1024.0))
    print("  %-44s %8.1f KB" % ("(total)", total / 1024.0))
    print()
    print("First load is about %.1f MB uncompressed; a web server gzips the sequence"
          % (total / 1e6))
    print("data to roughly a quarter of that, and the browser caches it.")
    print()
    if not do_push:
        print("Nothing was published. To publish this to")
        print("    %s" % remote)
        print("run the same command with --push.")
        print()
        print("To see it locally first, with no publishing at all:  ./katana web")
        return 0

    print("Publishing to %s ..." % remote)
    rc = publish(target, remote, allow_other=allow_other)
    if rc == 0:
        print("Pushed. GitHub Pages serves it once the repository's Pages setting")
        print("points at the branch -- Settings -> Pages -> Deploy from a branch.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
