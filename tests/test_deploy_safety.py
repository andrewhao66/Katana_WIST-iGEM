"""test_deploy_safety.py — deploy must not delete your work or push to the wrong place.

Run: python3 tests/test_deploy_safety.py

Two defects found by an independent Codex review, reproduced before being accepted.

1. `stage()` ran `shutil.rmtree(target)` on whatever `--out` named. Measured: a directory
   holding one unrelated file came back holding eighteen staged ones, and the unrelated
   file was gone. `katana deploy --out .` deletes the repository and then fails because
   its own sources are gone with it. No --push is needed, and nothing asks first.

2. `--remote` was unrestricted, and publish() force-pushes. So
   `katana deploy --push --remote <any writable repository>` could replace that
   repository's main branch with the generated site -- including the iGEM GitLab project
   that web_deploy's own docstring says is never pushed to. A docstring is not a control.

Both are the same mistake in different clothes: a destructive default with no gate on it.
The staging directory is the one thing deploy is allowed to destroy, and the sanctioned
remote is the one place it is allowed to publish.
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import web_deploy

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  [" + str(detail)[:300] + "]") if detail else ""))


def staged(target):
    """Run stage(), returning the refusal message or None on success."""
    try:
        web_deploy.stage(target)
        return None
    except SystemExit as exc:
        return str(exc)
    except web_deploy.UnsafeTarget as exc:
        return str(exc)


print("deploy safety")

D = tempfile.mkdtemp(prefix="deploysafe_")

# ---- staging must not destroy a directory holding someone else's files ----
victim = os.path.join(D, "victim")
os.makedirs(os.path.join(victim, "important"))
keep = os.path.join(victim, "important", "notes.txt")
with open(keep, "w", encoding="utf-8") as f:
    f.write("a week of someone's work\n")

msg = staged(victim)
check("staging REFUSES a directory that holds files it did not write", msg is not None,
      "it staged into it")
check("and the file is still there", os.path.isfile(keep), "it was deleted")
if msg:
    check("and the refusal names the directory", victim in msg or "not empty" in msg.lower()
          or "would delete" in msg.lower(), msg[:200])
    check("and says what to do instead",
          any(w in msg.lower() for w in ("--out", "empty", "remove")), msg[:200])

# The repository itself is the case that actually bites: `--out .`
msg = staged(ROOT)
check("staging REFUSES the repository root", msg is not None, "it staged into the repo")
check("and katana_build.py is still there",
      os.path.isfile(os.path.join(ROOT, "katana_build.py")))
check("and ui/web/index.js is still there",
      os.path.isfile(os.path.join(ROOT, "ui", "web", "index.js")))

# Home, and the places a mistyped path lands.
for danger in (os.path.expanduser("~"), "/", os.path.dirname(ROOT)):
    msg = staged(danger)
    check("staging refuses %s" % danger, msg is not None, "it would have staged there")

# ---- but an empty or fresh directory is fine, and so is re-staging ----
fresh = os.path.join(D, "fresh")
msg = staged(fresh)
check("staging a path that does not exist yet works", msg is None, msg)
check("and it produced the page", os.path.isfile(os.path.join(fresh, "index.html")))

msg = staged(fresh)
check("staging over its OWN previous output works, so deploy is repeatable", msg is None,
      msg)
check("and the page is still there", os.path.isfile(os.path.join(fresh, "index.html")))

empty = os.path.join(D, "empty")
os.makedirs(empty)
check("staging into an existing EMPTY directory works", staged(empty) is None)

# A directory with our own marker plus a stray file is still ours to replace -- that is
# the normal case of editing the page and re-deploying.
with open(os.path.join(fresh, "stray.txt"), "w", encoding="utf-8") as f:
    f.write("left over from a previous build\n")
check("staging over our own output that has gained a stray file still works",
      staged(fresh) is None)

# ---- publishing must not reach the iGEM GitLab, whatever is asked ----
check("the default remote is the sanctioned GitHub repository",
      "github.com/andrewhao66/iGEM-katana-webtest" in web_deploy.DEFAULT_REMOTE,
      web_deploy.DEFAULT_REMOTE)

GITLAB = ["https://gitlab.igem.org/2026/software/wist/katana.git",
          "git@gitlab.igem.org:2026/software/wist/katana.git",
          "https://GITLAB.IGEM.ORG/2026/software/wist/katana.git",
          "https://user:token@gitlab.igem.org/2026/software/wist/katana.git"]
for url in GITLAB:
    allowed, why = web_deploy.remote_allowed(url)
    check("publishing to %s is refused" % url[:52], not allowed, why)
    check("  and the refusal says why", why and "igem" in why.lower(), why)

# Any other remote is refused too, unless it is said out loud -- a generated artifact
# force-pushed over somebody's branch is not recoverable from the command line.
allowed, why = web_deploy.remote_allowed("https://github.com/someone/else.git")
check("an unrecognised remote is refused by default", not allowed, why)
check("and the refusal says how to override it deliberately",
      why and "--allow-remote" in why, why)

allowed, why = web_deploy.remote_allowed("https://github.com/someone/else.git",
                                         allow_other=True)
check("--allow-remote permits a different repository", allowed, why)

allowed, why = web_deploy.remote_allowed(GITLAB[0], allow_other=True)
check("but --allow-remote does NOT permit the iGEM GitLab", not allowed, why)

allowed, why = web_deploy.remote_allowed(web_deploy.DEFAULT_REMOTE)
check("and the sanctioned remote needs no override", allowed, why)

# ---- the command line must not publish by accident ----
p = subprocess.run([sys.executable, "web_deploy.py", "--out",
                    os.path.join(D, "cli")],
                   cwd=ROOT, capture_output=True, text=True, timeout=300)
check("`deploy` with no --push stages and publishes nothing", p.returncode == 0,
      (p.stdout + p.stderr)[-200:])
check("and says so", "Nothing was published" in p.stdout, p.stdout[-200:])

p = subprocess.run([sys.executable, "web_deploy.py", "--out", os.path.join(D, "cli2"),
                    "--push", "--remote", GITLAB[0]],
                   cwd=ROOT, capture_output=True, text=True, timeout=300)
check("`deploy --push --remote <the iGEM GitLab>` refuses", p.returncode != 0,
      "exit %d" % p.returncode)
check("and does so before running git at all",
      "igem" in (p.stdout + p.stderr).lower()
      and "fatal" not in (p.stdout + p.stderr).lower(),
      (p.stdout + p.stderr)[-200:])

# ---- and deploy's own bookkeeping must not reach the published site ----
mk = os.path.join(D, "marker")
web_deploy.stage(mk)
check("the staging marker is written, so a re-deploy is allowed",
      os.path.isfile(os.path.join(mk, web_deploy.MARKER)))
check("but it is git-ignored, so `git add -A` cannot publish it",
      web_deploy.MARKER in open(os.path.join(mk, ".gitignore"),
                                encoding="utf-8").read())
_listed, _ = web_deploy.stage(os.path.join(D, "marker2"))
check("and it is not counted among the site's files",
      not any(web_deploy.MARKER in str(n) for n, _s in _listed),
      str([n for n, _s in _listed])[:150])

shutil.rmtree(D, ignore_errors=True)

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
