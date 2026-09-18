#!/usr/bin/env python3
"""Falsification harness for the guards added in this session.

Project rule: *a guard that cannot be made to fail is a bug in the guard.*
Each case below builds a mutated copy of the committed ``data/`` (and, where the
check reads documentation, a mutated copy of the repository), runs
``pipeline/verify_claims.py`` against it with ``SFWEATHER_DATA``, and asserts the
expected verdict for the named check.

Run:  python3 tests/falsify_guards.py
Exit: 0 if every case behaved as expected.
"""
from __future__ import annotations

import copy
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
DATA = REPO / "data"

GEO_URL = ("https://geocoding.geo.census.gov/geocoder/geographies/coordinates"
           "?x=-122.483894&y=37.760459&benchmark=Public_AR_Current"
           "&vintage=Current_Current&format=json")

VALID_GEO = {
    "county_subdivision": "Sunset CCD",
    "county_subdivision_geoid": "0607593267",
    "county": "San Francisco County",
    "county_geoid": "06075",
    "place": "San Francisco city",
    "place_geoid": "0667000",
    "census_tract": "Census Tract 326.01",
    "census_tract_geoid": "06075032601",
    "census_block_geoid": "060750326013006",
    "congressional_district": "Congressional District 11",
    "urban_area": "San Francisco--Oakland, CA Urban Area",
    "geography_types_returned": ["Counties", "County Subdivisions"],
    "source": "U.S. Census Bureau geocoder (reverse lookup of the published ZCTA centroid)",
    "url": GEO_URL,
    "sha256": "0" * 64,
    "naming_note": "fixture",
}


def load(name):
    return json.loads((DATA / name).read_text())


def dump(path, obj):
    path.write_text(json.dumps(obj, indent=2, default=str))


def run_ledger(datadir, repo_root=None):
    """Run the ledger against *datadir*; return (exit_code, {check_id: status})."""
    script = (repo_root or REPO) / "pipeline" / "verify_claims.py"
    env = dict(os.environ, SFWEATHER_DATA=str(datadir),
               PYTHONPATH=str((repo_root or REPO) / "pipeline"))
    proc = subprocess.run([sys.executable, str(script)], env=env,
                          capture_output=True, text=True, cwd=str(repo_root or REPO))
    statuses = {}
    vj = datadir / "verify.json"
    if vj.exists():
        for c in json.loads(vj.read_text()).get("checks", []):
            statuses[c["id"]] = c["status"]
    return proc.returncode, statuses, proc.stdout + proc.stderr


CASES = []


def case(name, expect_status, check_id):
    def deco(fn):
        CASES.append((name, expect_status, check_id, fn))
        return fn
    return deco


def with_geo(mutate=None, provenance=True, irregularity=False):
    """Build a fixture where the Census geography block is present (then mutated)."""
    def build(tmp):
        for f in DATA.glob("*.json"):
            shutil.copy2(f, tmp / f.name)
        run = load("run.json")
        geo = copy.deepcopy(VALID_GEO)
        if mutate:
            mutate(geo)
        run["target"]["centroid"]["census_geographies"] = geo
        dump(tmp / "run.json", run)
        cal = load("calendar.json")
        cal["target"] = run["target"]
        dump(tmp / "calendar.json", cal)
        # The committed provenance.json now contains the real geocoder entry, so
        # "no recorded fetch" has to mean *stripped*, not merely *not added* --
        # otherwise the case silently stops testing the guard.
        prov = load("provenance.json")
        before = len(prov.get("entries") or [])
        prov["entries"] = [e for e in (prov.get("entries") or [])
                           if "geocoding.geo.census.gov" not in str(e.get("url") or "")]
        if not provenance and len(prov["entries"]) == before:
            raise AssertionError("fixture expected a real geocoder entry to strip")
        if provenance:
            prov["entries"].append({
                "url": GEO_URL, "http_status": 200, "ok": True, "bytes": 4242,
                "sha256": "0" * 64, "content_type": "application/json",
                "retrieved_utc": "2026-09-18T17:42:11Z", "elapsed_s": 0.2,
                "note": "fixture: Census geocoder reverse lookup"})
        dump(tmp / "provenance.json", prov)
        if irregularity:
            q = load("quality_report.json")
            q["irregularities"].append(
                {"severity": "warning", "area": "geography",
                 "message": "fixture irregularity", "evidence": {}})
            dump(tmp / "quality_report.json", q)
        return tmp
    return build


@case("census geography present, traced, GEOIDs nest", "pass", "census-geographies-traceable")
def _c(tmp):
    return with_geo()(tmp)


@case("census GEOID nesting broken (wrong county prefix)", "fail", "census-geographies-traceable")
def _c2(tmp):
    def mutate(geo):
        geo["census_block_geoid"] = "999990326013006"
    return with_geo(mutate)(tmp)


@case("census geography with no recorded fetch", "fail", "census-geographies-traceable")
def _c3(tmp):
    return with_geo(provenance=False)(tmp)


@case("census geography naming nothing", "fail", "census-geographies-traceable")
def _c4(tmp):
    def mutate(geo):
        for k in ("county_subdivision", "county", "census_tract"):
            geo[k] = None
    return with_geo(mutate)(tmp)


@case("census geography absent but flagged as an irregularity", "pass", "census-geographies-traceable")
def _c5(tmp):
    for f in DATA.glob("*.json"):
        shutil.copy2(f, tmp / f.name)
    # Strip the geography that the refreshed dataset really carries, so this case
    # exercises the honest-degradation branch rather than passing via the
    # evidence branch by accident.
    run = load("run.json")
    had = (run.get("target", {}).get("centroid", {}) or {}).pop("census_geographies", None)
    if had is None:
        raise AssertionError("fixture expected the dataset to carry census_geographies")
    dump(tmp / "run.json", run)
    cal = load("calendar.json")
    cal["target"] = run["target"]
    dump(tmp / "calendar.json", cal)
    q = load("quality_report.json")
    q["irregularities"].append({"severity": "warning", "area": "geography",
                                "message": "fixture: lookup failed", "evidence": {}})
    dump(tmp / "quality_report.json", q)
    return tmp


@case("a quoted AFD sentence edited (no longer verbatim)", "fail", "afd-language-verbatim")
def _a(tmp):
    for f in DATA.glob("*.json"):
        shutil.copy2(f, tmp / f.name)
    cal = load("calendar.json")
    for cat in cal["afd_language"]["categories"]:
        if cat["sentences"]:
            cat["sentences"][0]["sentence"] = "INVENTED SENTENCE THAT NWS NEVER WROTE."
            break
    dump(tmp / "calendar.json", cal)
    return tmp


@case("AFD sentence count smaller than the published list", "fail", "afd-language-verbatim")
def _a2(tmp):
    for f in DATA.glob("*.json"):
        shutil.copy2(f, tmp / f.name)
    cal = load("calendar.json")
    for cat in cal["afd_language"]["categories"]:
        if cat["sentences"]:
            cat["sentence_count"] = 0
            break
    dump(tmp / "calendar.json", cal)
    return tmp


@case("AFD block deleted entirely", "fail", "afd-language-verbatim")
def _a3(tmp):
    for f in DATA.glob("*.json"):
        shutil.copy2(f, tmp / f.name)
    cal = load("calendar.json")
    del cal["afd_language"]
    dump(tmp / "calendar.json", cal)
    return tmp


@case("AFD scan claims to have run with no fetched text", "fail", "afd-language-verbatim")
def _a4(tmp):
    for f in DATA.glob("*.json"):
        shutil.copy2(f, tmp / f.name)
    nws = load("nws.json")
    nws["products"]["AFD"]["text"] = ""
    dump(tmp / "nws.json", nws)
    return tmp


@case("a date attached to an AFD quotation", "fail", "afd-language-quotations-only")
def _q(tmp):
    for f in DATA.glob("*.json"):
        shutil.copy2(f, tmp / f.name)
    cal = load("calendar.json")
    for cat in cal["afd_language"]["categories"]:
        if cat["sentences"]:
            cat["sentences"][0]["date"] = "2026-12-25"
            break
    dump(tmp / "calendar.json", cal)
    return tmp


@case("an invented rainfall amount attached to an AFD quotation", "fail", "afd-language-quotations-only")
def _q2(tmp):
    for f in DATA.glob("*.json"):
        shutil.copy2(f, tmp / f.name)
    cal = load("calendar.json")
    for cat in cal["afd_language"]["categories"]:
        if cat["sentences"]:
            cat["sentences"][0]["amount_in"] = 2.5
            break
    dump(tmp / "calendar.json", cal)
    return tmp


@case("a scoreboard day publishes a value with no basis", "fail", "day-field-basis-complete")
def _b(tmp):
    for f in DATA.glob("*.json"):
        shutil.copy2(f, tmp / f.name)
    cal = load("calendar.json")
    cal["days"][5]["temp_basis"] = None
    dump(tmp / "calendar.json", cal)
    return tmp


@case("a current-forecast day publishes humidity with no basis", "fail", "day-field-basis-complete")
def _b2(tmp):
    for f in DATA.glob("*.json"):
        shutil.copy2(f, tmp / f.name)
    cal = load("calendar.json")
    cal["current_forecast"]["days"][0]["humidity_basis"] = ""
    dump(tmp / "calendar.json", cal)
    return tmp


def _provenance_case(mutate_prov, mutate_quality=None):
    """Build a fixture with a controlled provenance manifest / quality report.

    run.json's counts are recomputed from the mutated manifest so the fixture
    does not trip the unrelated provenance-record-count check and obscure the
    verdict this case is actually about.
    """
    def build(tmp):
        for f in DATA.glob("*.json"):
            shutil.copy2(f, tmp / f.name)
        prov = load("provenance.json")
        mutate_prov(prov)
        dump(tmp / "provenance.json", prov)
        entries = prov.get("entries") or []
        failed = sum(1 for e in entries
                     if e.get("ok") is False or (e.get("http_status") or 200) != 200)
        run = load("run.json")
        run.setdefault("counts", {})
        run["counts"]["manifest_entries"] = len(entries)
        run["counts"]["successful_fetches"] = len(entries) - failed
        run["counts"]["failed_fetches"] = failed
        dump(tmp / "run.json", run)
        if mutate_quality:
            q = load("quality_report.json")
            mutate_quality(q)
            dump(tmp / "quality_report.json", q)
        return tmp
    return build


@case("a failed fetch that is explained in the quality report", "pass",
      "failed-fetches-explained")
def _f1(tmp):
    def prov(p):
        p["entries"] = [e for e in p["entries"] if e.get("ok") is not False]
        p["entries"].append({"url": "https://api.weather.gov/stations/ZZZ9/observations/latest",
                             "http_status": 404, "ok": False, "bytes": 0, "sha256": None,
                             "note": "Latest official observation from station ZZZ9",
                             "retrieved_utc": "2026-09-18T18:00:00Z"})
    def qual(q):
        q["irregularities"].append({
            "severity": "warning", "area": "fetch",
            "message": "A source fetch did not return HTTP 200 (404): Latest official "
                       "observation from station ZZZ9. Nothing was inferred in its place.",
            "evidence": {"url": "https://api.weather.gov/stations/ZZZ9/observations/latest",
                         "http_status": 404}})
    return _provenance_case(prov, qual)(tmp)


@case("a failed fetch left unexplained in the quality report", "warn",
      "failed-fetches-explained")
def _f2(tmp):
    def prov(p):
        p["entries"] = [e for e in p["entries"] if e.get("ok") is not False]
        p["entries"].append({"url": "https://api.weather.gov/stations/ZZZ9/observations/latest",
                             "http_status": 404, "ok": False, "bytes": 0, "sha256": None,
                             "note": "Latest official observation from station ZZZ9",
                             "retrieved_utc": "2026-09-18T18:00:00Z"})
    return _provenance_case(prov)(tmp)


@case("no fetch failed at all", "pass", "failed-fetches-explained")
def _f3(tmp):
    def prov(p):
        p["entries"] = [e for e in p["entries"] if e.get("ok") is not False]
        for e in p["entries"]:
            e["http_status"] = 200
    return _provenance_case(prov)(tmp)


def _repo_copy_with(mutate_readme=None, mutate_data=None):
    """Copy the repository so documentation checks can be falsified too."""
    def build(tmp):
        repo = tmp / "repo"
        for item in ("pipeline", "docs", "README.md"):
            src = REPO / item
            if src.is_dir():
                shutil.copytree(src, repo / item)
            else:
                (repo / item).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, repo / item)
        (repo / "data").mkdir(parents=True, exist_ok=True)
        for f in DATA.glob("*.json"):
            shutil.copy2(f, repo / "data" / f.name)
        if mutate_readme:
            mutate_readme(repo / "README.md")
        if mutate_data:
            mutate_data(repo / "data")
        return repo
    return build


@case("README quotes a figure the dataset does not publish", "warn", "readme-figures-traceable")
def _d(tmp):
    def mutate(path):
        s = path.read_text()
        path.write_text(s.replace("mean **12.79 in**", "mean **99.99 in**", 1))
    return _repo_copy_with(mutate_readme=mutate)(tmp)


@case("README quotes a horizon date this run never published", "warn", "docs-current-dates-traceable")
def _d2(tmp):
    def mutate(path):
        s = path.read_text()
        path.write_text(s + "\n\nThe NWS horizon currently ends 2026-09-29.\n")
    return _repo_copy_with(mutate_readme=mutate)(tmp)


@case("README quotes a horizon date inside a code span (a fixture literal, not a claim)",
      "pass", "docs-current-dates-traceable")
def _d3(tmp):
    # The falsification harnesses have to name dates no run publishes; writing
    # that down must not read as documentation drift.  Prose dates still warn
    # (case _d2) - the difference is the code span, not the date.
    def mutate(path):
        s = path.read_text()
        path.write_text(s + "\n\nThe harness uses `2026-09-29` as its stale-horizon fixture.\n")
    return _repo_copy_with(mutate_readme=mutate)(tmp)


def main():
    failures = []
    for name, expect, check_id, build in CASES:
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            target = build(tmp)
            datadir = target / "data" if (target / "data").exists() else target
            repo_root = target if (target / "pipeline").exists() else None
            _code, statuses, output = run_ledger(datadir, repo_root)
            got = statuses.get(check_id, "absent")
            ok = got == expect
            print(f"  [{'ok ' if ok else 'BAD'}] expected {expect:5s} got {got:5s} :: {name}")
            if not ok:
                failures.append((name, expect, got, output[-600:]))
    print()
    if failures:
        print(f"{len(failures)} falsification case(s) did not behave as expected:")
        for name, expect, got, out in failures:
            print(f"\n--- {name}: expected {expect}, got {got}\n{out}")
        return 1
    print(f"all {len(CASES)} falsification cases behaved as expected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
