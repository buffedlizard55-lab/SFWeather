#!/usr/bin/env python3
"""Graceful-degradation harness for the rendered page.

The brief says to flag irregularities rather than hide them.  For the two blocks
added in session 7 that means something concrete: when the Census lookup did not
run, or when the forecast discussion was not fetched, the page must *say so* —
not name a district it has no evidence for, not render an empty card that looks
populated, and not leak a machine token into a table cell.

Each case mutates ``data/calendar.json`` / ``data/run.json`` the way a partial or
failed upstream fetch would, renders the page with ``tests/smoke.js`` (which now
fails on ``undefined``/``NaN``/a bare ``null`` cell in *any* section, and on a
missing expected section), and asserts the page still renders cleanly.

Run:  python3 tests/degrade_smoke.py     (needs node_modules installed)
Exit: 0 if every degraded state renders honestly.
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


def case(name, expect_fail=False):
    def deco(fn):
        CASES.append((name, expect_fail, fn))
        return fn
    return deco


def regress(repo, old, new, path="assets/js/app.js"):
    """Break the renderer the way a future refactor might, so the harness can
    prove it notices.  A degradation check that only ever runs against a correct
    renderer cannot fail, and a check that cannot fail is decoration."""
    p = repo / path
    src = p.read_text()
    if old not in src:
        raise AssertionError("renderer regression target not found: " + old[:70])
    p.write_text(src.replace(old, new, 1))
    return repo


def copy_repo(tmp):
    repo = tmp / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO / "index.html", repo / "index.html")
    for item in ("assets", "data", "tests"):
        shutil.copytree(REPO / item, repo / item, ignore=shutil.ignore_patterns("__pycache__"))
    return repo


def patch(repo, name, fn):
    p = repo / "data" / name
    obj = json.loads(p.read_text())
    fn(obj)
    p.write_text(json.dumps(obj))


@case("AFD discussion not fetched at all (no afd_language block)")
def _c1(repo):
    patch(repo, "calendar.json", lambda c: c.pop("afd_language", None))
    return repo


@case("AFD fetched but empty: scan reports itself as not scanned")
def _c2(repo):
    def fn(c):
        c["afd_language"] = {
            "scanned": False, "reason": "no AFD text was fetched this run",
            "sections_scanned": [], "sections_excluded_this_run": [],
            "categories": [], "any_language_found": False, "sentences_scanned": 0,
            "furniture_sentences_dropped": 0, "preamble_excluded": True,
            "scope_caveat": "x" * 40, "usage_note": "y" * 40, "verbatim_rule": "z" * 40,
            "none_found_statement": None, "sources": [],
        }
    patch(repo, "calendar.json", fn)
    return repo


@case("AFD scan found nothing: every category empty")
def _c3(repo):
    def fn(c):
        for cat in c["afd_language"]["categories"]:
            cat["sentences"] = []
            cat["sentence_count"] = 0
        c["afd_language"]["any_language_found"] = False
        c["afd_language"]["none_found_statement"] = (
            "No atmospheric-river, prolonged-rain or heavy-rain language appears in "
            "this discussion. That is a statement about this discussion only, and is "
            "not evidence that the season will be dry.")
    patch(repo, "calendar.json", fn)
    return repo


@case("Census lookup did not run (no census_geographies)")
def _c4(repo):
    def fn(c):
        (c.get("target", {}).get("centroid", {}) or {}).pop("census_geographies", None)
    patch(repo, "calendar.json", fn)
    patch(repo, "run.json", fn)
    return repo


@case("Census returned nothing usable (all names null)")
def _c5(repo):
    def fn(c):
        g = (c.get("target", {}).get("centroid", {}) or {}).get("census_geographies")
        if g is None:
            return
        for k in list(g):
            if k not in ("url", "sha256", "source", "naming_note",
                         "geography_types_returned"):
                g[k] = None
    patch(repo, "calendar.json", fn)
    patch(repo, "run.json", fn)
    return repo


@case("Census returned only a county (partial geography)")
def _c6(repo):
    def fn(c):
        g = (c.get("target", {}).get("centroid", {}) or {}).get("census_geographies")
        if g is None:
            return
        g["county_subdivision"] = None
        g["county_subdivision_geoid"] = None
        g["census_tract"] = None
        g["census_tract_geoid"] = None
        g["census_block_geoid"] = None
        g["place"] = None
        g["geography_types_returned"] = ["Counties", "States"]
    patch(repo, "calendar.json", fn)
    patch(repo, "run.json", fn)
    return repo


# An empty `current_forecast.days` is deliberately NOT a case here: that is a
# dataset-completeness failure, which tests/smoke.js and the claim ledger are
# supposed to reject outright.  This harness covers *partial content inside a
# block that is present*, i.e. the states an upstream fetch can legitimately
# produce.  Keeping the boundary explicit stops the two harnesses from
# disagreeing about who owns which failure.


@case("a scoreboard day publishes nulls for every headline value")
def _c8(repo):
    def fn(c):
        d = c["days"][40]
        for k in ("high_f", "low_f", "humidity_pct", "rain_chance_pct",
                  "rain_amount_in", "wind_max_mph", "gust_max_mph"):
            d[k] = None
    patch(repo, "calendar.json", fn)
    return repo


# --- the same states with the renderer broken, to prove the checks can fail ---

@case("renderer swallows the absent-AFD message", expect_fail=True)
def _r1(repo):
    patch(repo, "calendar.json", lambda c: c.pop("afd_language", None))
    return regress(repo, """  if (!a) {
    box.append(el('p', { class: 'empty', text:
      'The Area Forecast Discussion scan is not present in this dataset.' }));
    return;
  }""", "  if (!a) { return; }")


@case("renderer prints 'not scanned' but drops the recorded reason", expect_fail=True)
def _r2(repo):
    def fn(c):
        c["afd_language"] = {"scanned": False, "reason": "no AFD text was fetched this run",
                             "categories": [], "sections_scanned": [], "sentences_scanned": 0}
    patch(repo, "calendar.json", fn)
    return regress(repo,
                   "'Not scanned this run: ' + (a.reason || 'no reason recorded') + '.'",
                   "'Not scanned this run.'")


@case("renderer swallows the missing-Census-geography message", expect_fail=True)
def _r3(repo):
    def fn(c):
        (c.get("target", {}).get("centroid", {}) or {}).pop("census_geographies", None)
    patch(repo, "calendar.json", fn)
    patch(repo, "run.json", fn)
    return regress(repo, "not retrieved this run", "retrieved")


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
    for name, expect_fail, build in CASES:
        with tempfile.TemporaryDirectory() as td:
            repo = build(copy_repo(pathlib.Path(td)))
            code, out = run_smoke(repo)
            failed = code != 0
            ok = failed == expect_fail
            verdict = "caught the regression" if expect_fail else "renders honestly"
            print(f"  [{'ok ' if ok else 'BAD'}] {verdict} :: {name}")
            if not ok:
                bad.append((name, out[-700:]))
    print()
    if bad:
        for name, out in bad:
            print(f"--- {name}\n{out}\n")
        return 1
    print(f"all {len(CASES)} degraded states render honestly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
