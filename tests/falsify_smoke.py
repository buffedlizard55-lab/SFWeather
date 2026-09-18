#!/usr/bin/env python3
"""Falsification harness for the render guards added to tests/smoke.js.

``tests/falsify_guards.py`` falsifies the claim ledger; this one falsifies the
jsdom render guards, because a render guard that cannot fail is just decoration.
Each case copies the repository into a temp tree, mutates ``data/calendar.json``
(or the page markup) the way a regression would, runs ``node tests/smoke.js``
against that copy, and asserts the smoke test *fails* with the expected message.

Run:  python3 tests/falsify_smoke.py     (needs node_modules installed)
Exit: 0 if every case behaved as expected.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
NODE_PATH = str(REPO / "node_modules")

CASES = []


def case(name, expect_fail=True, expect_msg=""):
    def deco(fn):
        CASES.append((name, expect_fail, expect_msg, fn))
        return fn
    return deco


def copy_repo(tmp):
    repo = tmp / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    for item in ("index.html", ".nojekyll"):
        if (REPO / item).exists():
            shutil.copy2(REPO / item, repo / item)
    for item in ("assets", "data", "pipeline", "tests", "docs"):
        shutil.copytree(REPO / item, repo / item, ignore=shutil.ignore_patterns("__pycache__"))
    return repo


def patch_calendar(repo, fn):
    p = repo / "data" / "calendar.json"
    cal = json.loads(p.read_text())
    fn(cal)
    p.write_text(json.dumps(cal))


@case("baseline: unmutated copy renders clean", expect_fail=False)
def _baseline(repo):
    return repo


@case("AFD block removed from the dataset")
def _c1(repo):
    patch_calendar(repo, lambda cal: cal.pop("afd_language", None))
    return repo


# Tampering with the *data* is not a render defect: the card must faithfully
# render whatever the dataset publishes, and it does.  Source fidelity is the
# claim ledger's job - see tests/falsify_guards.py, case "a quoted AFD sentence
# edited (no longer verbatim)", which fails exactly this mutation.  Kept here so
# the boundary between the two harnesses is written down rather than assumed.
@case("a quoted AFD sentence edited in the data (ledger's job, not the renderer's)",
      expect_fail=False)
def _c2(repo):
    def fn(cal):
        for cat in cal["afd_language"]["categories"]:
            if cat["sentences"]:
                cat["sentences"][0]["sentence"] = "SENTENCE THE PAGE WAS NOT GIVEN."
                break
    patch_calendar(repo, fn)
    return repo


@case("an AFD quotation given a date")
def _c3(repo):
    def fn(cal):
        for cat in cal["afd_language"]["categories"]:
            if cat["sentences"]:
                cat["sentences"][0]["date"] = "2026-12-25"
                break
    patch_calendar(repo, fn)
    return repo


@case("AFD scope statement stripped from the card markup")
def _c4(repo):
    p = repo / "assets" / "js" / "app.js"
    s = p.read_text()
    s = s.replace("scope_caveat", "scope_caveat_removed_")
    p.write_text(s)
    return repo


@case("the AFD card element removed from the page")
def _c5(repo):
    p = repo / "index.html"
    s = p.read_text()
    s = s.replace('id="afd-language"', 'id="afd-language-renamed"')
    p.write_text(s)
    return repo


@case("a day's temperature basis emptied", expect_msg="no basis")
def _c6(repo):
    def fn(cal):
        for d in cal["days"]:
            if d.get("temp_basis"):
                d["temp_basis"] = ""
                break
    patch_calendar(repo, fn)
    return repo


@case("a day's gust basis emptied", expect_msg="Max gust")
def _c7(repo):
    def fn(cal):
        for d in cal["days"]:
            if d.get("gust_basis"):
                d["gust_basis"] = ""
                break
    patch_calendar(repo, fn)
    return repo


def run_smoke(repo):
    proc = subprocess.run(["node", "tests/smoke.js", str(repo)],
                          capture_output=True, text=True, cwd=str(REPO),
                          env={"PATH": "/usr/bin:/bin:/usr/local/bin", "NODE_PATH": NODE_PATH})
    return proc.returncode, proc.stdout + proc.stderr


def main():
    if not pathlib.Path(NODE_PATH).exists():
        print("node_modules not installed - run: npm install")
        return 2
    bad = []
    for name, expect_fail, expect_msg, build in CASES:
        with tempfile.TemporaryDirectory() as td:
            repo = build(copy_repo(pathlib.Path(td)))
            code, out = run_smoke(repo)
            failed = code != 0
            ok = (failed == expect_fail) and (
                not expect_msg or expect_msg in out or not expect_fail)
            print(f"  [{'ok ' if ok else 'BAD'}] smoke {'failed' if failed else 'passed'} "
                  f"(expected {'fail' if expect_fail else 'pass'}) :: {name}")
            if not ok:
                bad.append((name, out[-500:]))
    print()
    if bad:
        for name, out in bad:
            print(f"--- {name}\n{out}\n")
        return 1
    print(f"all {len(CASES)} smoke falsification cases behaved as expected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
