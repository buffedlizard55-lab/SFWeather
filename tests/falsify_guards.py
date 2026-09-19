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
    # The digest check reads data/alerts.xml (RSS/JSON item agreement), which is
    # not a *.json copy-loop file — stage the committed feed unless the case
    # deleted it on purpose.
    if not (datadir / "alerts.xml").exists() and (DATA / "alerts.xml").exists():
        shutil.copy2(DATA / "alerts.xml", datadir / "alerts.xml")
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


@case("hourly wind+rain mean does not match the per-season values", "fail",
      "wind-rain-hourly-arithmetic")
def _h1(tmp):
    for f in DATA.glob("*.json"):
        shutil.copy2(f, tmp / f.name)
    ll = load("landlord.json")
    hourly = ll["executive_summary"]["wind_and_rain_hourly"]
    published = hourly.get("days_with_a_simultaneous_hour") or {}
    if published.get("mean") is None:
        raise AssertionError("fixture expected a published hourly mean to corrupt")
    published["mean"] = round(float(published["mean"]) + 1.0, 2)
    dump(tmp / "landlord.json", ll)
    return tmp


@case("a season published as used is also listed as excluded", "fail",
      "wind-rain-hourly-arithmetic")
def _h2(tmp):
    for f in DATA.glob("*.json"):
        shutil.copy2(f, tmp / f.name)
    ll = load("landlord.json")
    hourly = ll["executive_summary"]["wind_and_rain_hourly"]
    if not hourly.get("per_season") or not hourly.get("excluded_seasons"):
        raise AssertionError("fixture expected both used and excluded seasons")
    hourly["excluded_seasons"][0]["season"] = hourly["per_season"][0]["season"]
    dump(tmp / "landlord.json", ll)
    return tmp


@case("a used season sits below the published coverage floor", "fail",
      "wind-rain-hourly-arithmetic")
def _h3(tmp):
    for f in DATA.glob("*.json"):
        shutil.copy2(f, tmp / f.name)
    ll = load("landlord.json")
    hourly = ll["executive_summary"]["wind_and_rain_hourly"]
    if not hourly.get("per_season"):
        raise AssertionError("fixture expected published seasons")
    # 100% floor: any used season with thinner coverage must be caught.
    hourly["coverage"]["min_coverage_pct_required"] = 100.0
    dump(tmp / "landlord.json", ll)
    return tmp


@case("the hourly statistic loses its ISD source URL", "fail", "wind-rain-hourly-traceable")
def _h4(tmp):
    for f in DATA.glob("*.json"):
        shutil.copy2(f, tmp / f.name)
    ll = load("landlord.json")
    hourly = ll["executive_summary"]["wind_and_rain_hourly"]
    if not hourly.get("source_url"):
        raise AssertionError("fixture expected a source_url to strip")
    hourly["source_url"] = "https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/"
    dump(tmp / "landlord.json", ll)
    return tmp


@case("an archive last_date stops matching its published age", "fail", "record-coverage-published")
def _h5(tmp):
    for f in DATA.glob("*.json"):
        shutil.copy2(f, tmp / f.name)
    run = load("run.json")
    cov = run.get("record_coverage") or {}
    archives = cov.get("archives") or []
    if not archives:
        raise AssertionError("fixture expected a published record_coverage block")
    archives[0]["last_date"] = "1999-01-01"
    dump(tmp / "run.json", run)
    return tmp


@case("the record_coverage block disappears from the run", "warn", "record-coverage-published")
def _h6(tmp):
    for f in DATA.glob("*.json"):
        shutil.copy2(f, tmp / f.name)
    run = load("run.json")
    if "record_coverage" not in run:
        raise AssertionError("fixture expected a record_coverage block to remove")
    run.pop("record_coverage")
    dump(tmp / "run.json", run)
    return tmp


@case("a current daily archive is relabelled as a not-yet-published annual file",
      "fail", "expected-absences-justified")
def _h7(tmp):
    for f in DATA.glob("*.json"):
        shutil.copy2(f, tmp / f.name)
    prov = load("provenance.json")
    run = load("run.json")
    ghcn = next((e for e in prov["entries"]
                 if "global-historical-climatology-network-daily" in str(e.get("url"))), None)
    if ghcn is None:
        raise AssertionError("fixture expected a GHCN-Daily fetch to relabel")
    if not ghcn.get("ok"):
        raise AssertionError("fixture expected the GHCN-Daily fetch to have succeeded")
    # Simulate the regression: the daily archive stops answering, and the run
    # quietly writes it off as an annual file that is not published yet.
    ghcn["ok"] = False
    ghcn["http_status"] = 404
    ghcn["expected_absent"] = "annual-file-not-yet-published"
    counts = run["counts"]
    counts["successful_fetches"] -= 1
    counts["expected_absences"] = counts.get("expected_absences", 0) + 1
    dump(tmp / "provenance.json", prov)
    dump(tmp / "run.json", run)
    return tmp


@case("an expected absence invents its own reason", "fail", "expected-absences-justified")
def _h8(tmp):
    for f in DATA.glob("*.json"):
        shutil.copy2(f, tmp / f.name)
    prov = load("provenance.json")
    run = load("run.json")
    entry = next((e for e in prov["entries"]
                  if "/access/2026/" in str(e.get("url")) and not e.get("ok")), None)
    if entry is None:
        entry = next((e for e in prov["entries"] if not e.get("ok")), None)
    if entry is None:
        raise AssertionError("fixture expected at least one failed fetch to relabel")
    entry["expected_absent"] = "the-provider-is-slow-today"
    counts = run["counts"]
    counts["failed_fetches"] = max(0, counts["failed_fetches"] - 1)
    counts["expected_absences"] = counts.get("expected_absences", 0) + 1
    dump(tmp / "provenance.json", prov)
    dump(tmp / "run.json", run)
    return tmp


_LIVE_SAMPLING = ("lib_shape.point_in_polygon at the 94122 centroid "
                  "(same code path as live CPC outlooks)")
_ARCHIVE_URL = ("https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst/"
                "seasprcp_199508.zip")


def _prov_with_archive(tmp, *urls):
    prov = load("provenance.json")
    for u in urls:
        prov["entries"].append({"url": u, "http_status": 200, "ok": True,
                                "bytes": 12345, "sha256": "1" * 64,
                                "retrieved_utc": "2026-09-18T20:00:00Z",
                                "note": "fixture: archived CPC issuance"})
    dump(tmp / "provenance.json", prov)


@case("a fabricated back-test with one scored row passes", "pass",
      "cpc-backtest-sampling-method")
def _bt_pass(tmp):
    for f in DATA.glob("*.json"):
        shutil.copy2(f, tmp / f.name)
    dump(tmp / "cpc_backtest.json", {
        "status": "scored",
        "rows": [
            {"category": "EC", "observed_tercile": "Near-normal", "hit": None,
             "sampling": _LIVE_SAMPLING, "url": _ARCHIVE_URL,
             "polygon_index": 3},
            {"category": "Above", "observed_tercile": "Above", "hit": True,
             "sampling": _LIVE_SAMPLING, "url": _ARCHIVE_URL,
             "polygon_index": 3},
        ],
        "summary": {"hit_rate_pct": 100.0, "n_rows_scored": 1},
    })
    _prov_with_archive(tmp, _ARCHIVE_URL)
    return tmp


@case("an EC outlook counted as a hit fails the back-test guard", "fail",
      "cpc-backtest-sampling-method")
def _bt_ec(tmp):
    for f in DATA.glob("*.json"):
        shutil.copy2(f, tmp / f.name)
    dump(tmp / "cpc_backtest.json", {
        "status": "scored",
        "rows": [{"category": "EC", "observed_tercile": "Near-normal",
                  "hit": True, "sampling": _LIVE_SAMPLING,
                  "url": _ARCHIVE_URL, "polygon_index": 3}],
        "summary": {"hit_rate_pct": 100.0, "n_rows_scored": 1},
    })
    _prov_with_archive(tmp, _ARCHIVE_URL)
    return tmp


@case("a back-test row scored off the live sampling path fails", "fail",
      "cpc-backtest-sampling-method")
def _bt_path(tmp):
    for f in DATA.glob("*.json"):
        shutil.copy2(f, tmp / f.name)
    dump(tmp / "cpc_backtest.json", {
        "status": "scored",
        "rows": [{"category": "Above", "observed_tercile": "Above",
                  "hit": True, "sampling": "eyeballed off the GIF",
                  "url": _ARCHIVE_URL, "polygon_index": 3}],
        "summary": {"hit_rate_pct": 100.0, "n_rows_scored": 1},
    })
    _prov_with_archive(tmp, _ARCHIVE_URL)
    return tmp


@case("a back-test row with no recorded fetch fails", "fail",
      "cpc-backtest-sampling-method")
def _bt_prov(tmp):
    for f in DATA.glob("*.json"):
        shutil.copy2(f, tmp / f.name)
    dump(tmp / "cpc_backtest.json", {
        "status": "scored",
        "rows": [{"category": "Above", "observed_tercile": "Above",
                  "hit": True, "sampling": _LIVE_SAMPLING,
                  "url": _ARCHIVE_URL, "polygon_index": 3}],
        "summary": {"hit_rate_pct": 100.0, "n_rows_scored": 1},
    })
    # No provenance entry added: the fetch is untraceable by construction.
    return tmp


@case("a scoreboard day stripped of deep links fails", "fail",
      "deep-links-traceable")
def _dl(tmp):
    for f in DATA.glob("*.json"):
        shutil.copy2(f, tmp / f.name)
    cal = load("calendar.json")
    if not cal["days"][0].get("deep_links"):
        raise AssertionError("fixture expected the dataset to carry deep_links")
    cal["days"][0]["deep_links"] = {}
    dump(tmp / "calendar.json", cal)
    return tmp


@case("a duplicated AFD issuance fails the history guard", "fail",
      "afd-history-consistent")
def _ah(tmp):
    for f in DATA.glob("*.json"):
        shutil.copy2(f, tmp / f.name)
    hist = load("afd_history.json")
    if not hist:
        raise AssertionError("fixture expected a non-empty afd_history.json")
    hist.append(copy.deepcopy(hist[0]))
    dump(tmp / "afd_history.json", hist)
    return tmp


@case("a digest built at the wrong threshold fails", "fail",
      "digest-rss-traceable")
def _dg(tmp):
    for f in DATA.glob("*.json"):
        shutil.copy2(f, tmp / f.name)
    dg = load("digest.json")
    dg["pop_threshold_pct"] = 40
    dump(tmp / "digest.json", dg)
    return tmp


@case("a model-guidance key on a scoreboard day fails", "fail",
      "model-guidance-separated")
def _mg(tmp):
    for f in DATA.glob("*.json"):
        shutil.copy2(f, tmp / f.name)
    cal = load("calendar.json")
    cal["days"][0]["model_cfs_rain_in"] = 1.23
    dump(tmp / "calendar.json", cal)
    return tmp


@case("a successor probe with an invented verdict fails", "fail",
      "successor-probe-present")
def _sp(tmp):
    for f in DATA.glob("*.json"):
        shutil.copy2(f, tmp / f.name)
    dump(tmp / "isd_history.json", {
        "url": "https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv",
        "verdict": "the-intern-deleted-it",
    })
    _prov_with_archive(
        tmp, "https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv")
    return tmp


@case("a digest whose RSS feed is malformed fails", "fail",
      "digest-rss-traceable")
def _dg_rss(tmp):
    for f in DATA.glob("*.json"):
        shutil.copy2(f, tmp / f.name)
    (tmp / "alerts.xml").write_text("<rss><channel><item>unclosed")
    return tmp



MG_INDEX = "https://www.cpc.ncep.noaa.gov/products/NMME/probindex.shtml"
MG_DESCR = "https://www.cpc.ncep.noaa.gov/products/NMME/NMME_PROB_descr.html"
MG_IMAGE = ("https://www.cpc.ncep.noaa.gov/products/NMME/prob/images/"
            "prob_ensemble_prate_us_season1.png")


DESCR_TEXT = ("NMME ensemble contains 79 members, all weighted equally. A/B/N "
              "[Above/Below/Neutral] are terciles. The tercile limits were determined "
              "separately for each model using the NMME hindcasts (1982-2010).")
DESCR_SENTENCES = ["NMME ensemble contains 79 members, all weighted equally.",
                   "A/B/N [Above/Below/Neutral] are terciles."]

def copy_data(tmp):
    """Copy the committed dataset into a scratch dir the ledger can be run on."""
    for f in DATA.glob("*.json"):
        shutil.copy2(f, tmp / f.name)
    return tmp


def mg_fixture(mutate=None, manifest=True, extra_rows=None):
    def build(tmp):
        copy_data(tmp)
        mg = {
            "generated_utc": "2026-09-18T21:00:00Z",
            "tier": "model-guidance",
            "not_an_official_forecast": True,
            "merged_into_scoreboard": False,
            "warning": ("MODEL GUIDANCE - NOT AN OFFICIAL FORECAST. Raw multi-model "
                        "ensemble products. No value from this section is merged into "
                        "the day-by-day scoreboard."),
            "isolation_rule": "checked by model-guidance-isolation",
            "coverage_verbatim": "October 2026 - April 2027",
            "pages": {
                "prob_index": {"key": "prob_index", "url": MG_INDEX, "ok": True,
                               "http_status": 200,
                               "plain_text": f"NMME probability forecasts For: October 2026 - April 2027 index",
                               "warning": "Model guidance, not an official forecast."},
                "description": {"key": "description", "url": MG_DESCR, "ok": True,
                                "http_status": 200, "plain_text": DESCR_TEXT,
                                "verbatim_sentences": list(DESCR_SENTENCES),
                                "warning": "Model guidance, not an official forecast."},
            },
            "images": [{"variable": "precipitation rate", "variable_key": "prate",
                        "season_index": 1, "url": MG_IMAGE, "ok": True, "http_status": 200,
                        "bytes": 4321, "sha256": "1" * 64,
                        "warning": "Model guidance, not an official forecast."}],
            "probes": [{"key": "nomads_cfs_prod", "ok": False, "http_status": 404,
                        "error": "HTTP 404", "decoded": False,
                        "url": "https://nomads.ncep.noaa.gov/pub/data/nccf/com/cfs/prod/"}],
            "irregularities": [],
        }
        if mutate:
            mutate(mg)
        dump(tmp / "model_guidance.json", mg)
        if manifest:
            rows = [{"url": u, "http_status": 200, "ok": True, "bytes": 999,
                     "sha256": "2" * 64, "retrieved_utc": "2026-09-18T21:00:00Z",
                     "note": "fixture"} for u in (MG_INDEX, MG_DESCR, MG_IMAGE)]
            rows += list(extra_rows or [])
            dump(tmp / "model_guidance_provenance.json",
                 {"generated_utc": "2026-09-18T21:00:00Z", "area": "model_guidance",
                  "note": "fixture manifest", "entries": rows})
        return tmp
    return build


AFD_TEXT = ("Area Forecast Discussion\n.SHORT TERM...\nA weak front will bring periods of "
            "rain Thursday night into Friday, with gusty southwest winds and gusts to 40 mph.\n")

def feed_fixture(mutate=None):
    def build(tmp):
        copy_data(tmp)
        feed = load("feed.json")
        if mutate:
            mutate(feed)
        dump(tmp / "feed.json", feed)
        return tmp
    return build

# ---------------------------------------------------------------- CPC coverage
@case("CPC coverage as published: every day carries the records that cover it",
      "pass", "cpc-season-covers-complete")
def _cpc1(tmp):
    return copy_data(tmp)


@case("one CPC record dropped from one day (silent under-coverage)",
      "fail", "cpc-season-covers-complete")
def _cpc2(tmp):
    copy_data(tmp)
    cal = load("calendar.json")
    victim = next(d for d in cal["days"] if d["date"] == "2026-12-15")
    if not victim.get("cpc"):
        raise AssertionError("fixture expected CPC records attached to 2026-12-15")
    victim["cpc"] = victim["cpc"][1:]
    dump(tmp / "calendar.json", cal)
    return tmp


@case("cross-year season parsed as one calendar year (the 2027-01 regression)",
      "fail", "cpc-season-covers-complete")
def _cpc3(tmp):
    copy_data(tmp)
    cal = load("calendar.json")
    n = 0
    for rec in cal["cpc"]["records"]:
        if rec.get("covers") and "2027-01" in rec["covers"]:
            rec["covers"] = [m for m in rec["covers"] if m != "2027-01"]
            n += 1
    if not n:
        raise AssertionError("fixture expected a record covering 2027-01")
    dump(tmp / "calendar.json", cal)
    return tmp


@case("a CPC record declares no coverage at all", "fail", "cpc-record-coverage-declared")
def _cpc4(tmp):
    copy_data(tmp)
    cal = load("calendar.json")
    rec = next(r for r in cal["cpc"]["records"] if r.get("covers"))
    rec["covers"] = []
    rec["start_date"] = rec["end_date"] = None
    dump(tmp / "calendar.json", cal)
    return tmp


@case("a CPC record attached to a day outside its coverage", "fail", "cpc-record-reach")
def _cpc5(tmp):
    copy_data(tmp)
    cal = load("calendar.json")
    rec = next(r for r in cal["cpc"]["records"] if r.get("covers"))
    rec = copy.deepcopy(rec)
    rec["covers"] = ["2026-09"]                      # entirely outside the season
    cal["cpc"]["records"].append(rec)
    day = next(d for d in cal["days"] if d["date"] == "2026-10-05")
    day.setdefault("cpc", []).append(copy.deepcopy(rec))
    dump(tmp / "calendar.json", cal)
    return tmp


# --------------------------------------------------------- auxiliary manifests
@case("an auxiliary manifest on a vetted host, with evidence", "pass",
      "auxiliary-manifests-vetted")
def _aux1(tmp):
    return mg_fixture()(tmp)


@case("an auxiliary manifest records a non-vetted host", "fail",
      "auxiliary-manifests-vetted")
def _aux2(tmp):
    return mg_fixture(extra_rows=[{
        "url": "https://accuweather.example/api/forecast.json", "http_status": 200,
        "ok": True, "bytes": 10, "sha256": "4" * 64,
        "retrieved_utc": "2026-09-18T21:00:00Z", "note": "fixture: commercial host"}])(tmp)


@case("an auxiliary manifest is anonymous (area does not match its filename)",
      "fail", "auxiliary-manifests-vetted")
def _aux3(tmp):
    copy_data(tmp)
    dump(tmp / "model_guidance_provenance.json", {
        "generated_utc": "2026-09-18T21:00:00Z", "area": "some_other_area",
        "note": "", "entries": []})
    return tmp


@case("a fetch double-recorded in the nightly and an auxiliary manifest",
      "fail", "auxiliary-manifests-separate")
def _aux4(tmp):
    copy_data(tmp)
    prov = load("provenance.json")
    row = next(e for e in prov["entries"] if e.get("ok"))
    dump(tmp / "model_guidance_provenance.json", {
        "generated_utc": "2026-09-18T21:00:00Z", "area": "model_guidance",
        "note": "fixture", "entries": [copy.deepcopy(row)]})
    return tmp


@case("run.json's manifest total inflated by an auxiliary manifest's rows",
      "fail", "auxiliary-manifests-separate")
def _aux5(tmp):
    copy_data(tmp)
    run = load("run.json")
    run["counts"]["manifest_entries"] += 7
    dump(tmp / "run.json", run)
    dump(tmp / "model_guidance_provenance.json", {
        "generated_utc": "2026-09-18T21:00:00Z", "area": "model_guidance", "note": "fixture",
        "entries": [{"url": MG_INDEX, "http_status": 200, "ok": True, "bytes": 999,
                     "sha256": "2" * 64, "retrieved_utc": "2026-09-18T21:00:00Z",
                     "note": "fixture"}] * 7})
    return tmp


# ------------------------------------------------------------- model guidance
@case("model guidance flagged, quoted verbatim, every link fetched", "pass",
      "model-guidance-isolation")
def _mg1(tmp):
    return mg_fixture()(tmp)


@case("model guidance presented as merged into the scoreboard", "fail",
      "model-guidance-isolation")
def _mg2(tmp):
    def mutate(mg):
        mg["merged_into_scoreboard"] = True
        mg["warning"] = "Ensemble guidance for the season."
    return mg_fixture(mutate)(tmp)


@case("a model-guidance field leaked into the day-by-day calendar", "fail",
      "model-guidance-isolation")
def _mg3(tmp):
    def mutate(mg):
        pass
    def build(tmp):
        mg_fixture(mutate)(tmp)
        cal = load("calendar.json")
        cal["days"][0]["nmme_prate_probability_pct"] = 41.0
        dump(tmp / "calendar.json", cal)
        return tmp
    return build(tmp)


@case("an NMME definition sentence paraphrased instead of copied", "fail",
      "model-guidance-quotes-verbatim")
def _mg4(tmp):
    def mutate(mg):
        mg["pages"]["description"]["verbatim_sentences"] = [
            "The NMME ensemble has 79 members which are weighted equally."]
    return mg_fixture(mutate)(tmp)


@case("a guidance link published that was never fetched", "fail",
      "model-guidance-links-fetched")
def _mg5(tmp):
    def mutate(mg):
        mg["pages"]["skill"] = {"key": "skill", "ok": True, "http_status": 200,
                                "url": "https://www.cpc.ncep.noaa.gov/products/NMME/prob/rpss.probindex.html",
                                "warning": "Model guidance, not an official forecast."}
    return mg_fixture(mutate)(tmp)


@case("a guidance fetch that failed publishes no error", "fail",
      "model-guidance-links-fetched")
def _mg6(tmp):
    def mutate(mg):
        mg["probes"][0].pop("error")
    return mg_fixture(mutate)(tmp)


@case("an archived guidance image is not the image that was hashed", "fail",
      "model-guidance-links-fetched")
def _mg7(tmp):
    def mutate(mg):
        mg["images"][0]["local_path"] = "assets/model_guidance/does-not-exist.png"
    return mg_fixture(mutate)(tmp)

# ------------------------------------------------------------------ the feed
@case("the published feed: sorted, dated, traceable", "pass", "feed-traceable")
def _fd1(tmp):
    return copy_data(tmp)


@case("a feed that is not sorted newest first", "fail", "feed-traceable")
def _fd2(tmp):
    def mutate(f):
        f["entries"] = list(reversed(f["entries"]))
    return feed_fixture(mutate)(tmp)


@case("a feed whose published counts do not match its rows", "fail", "feed-traceable")
def _fd3(tmp):
    def mutate(f):
        f["counts"]["entries"] = (f["counts"]["entries"] or 0) + 5
    return feed_fixture(mutate)(tmp)


@case("a model-guidance feed entry marked official", "fail", "feed-traceable")
def _fd4(tmp):
    def mutate(f):
        f["entries"].append({
            "kind": "model-guidance", "title": "NMME run", "official": True,
            "timestamp_utc": "2026-09-18T21:00:00Z", "date_utc": "2026-09-18",
            "time_known": True, "detail": "fixture", "url": MG_INDEX,
            "source_file": "data/model_guidance.json", "provenance_verified": True})
        f["counts"]["entries"] = len(f["entries"])
        f["counts"]["official"] = f["counts"]["official"] + 1
        f["counts"]["kinds"]["model-guidance"] = 1
        f["entries"].sort(key=lambda e: e.get("timestamp_utc") or "", reverse=True)
    return feed_fixture(mutate)(tmp)


@case("a feed entry linking a non-vetted host", "fail", "feed-traceable")
def _fd5(tmp):
    def mutate(f):
        f["entries"][0]["url"] = "https://accuweather.example/san-francisco"
        f["counts"]["provenance_verified"] = max(0, f["counts"]["provenance_verified"] - 1)
    return feed_fixture(mutate)(tmp)


@case("a feed entry with no evidence behind it and no label saying so", "warn",
      "feed-provenance")
def _fd6(tmp):
    def mutate(f):
        row = next(e for e in f["entries"] if e.get("provenance_verified") is True)
        row["provenance_verified"] = False
        row.pop("provenance_note", None)
        f["counts"]["provenance_verified"] -= 1
        f["counts"]["provenance_unverified"] = f["counts"].get("provenance_unverified", 0) + 1
    return feed_fixture(mutate)(tmp)


# --------------------------------------------------------------------------
# Prognostic-discussion caveats (ledger check prognostic-caveats-verbatim).
# The block publishes CPC's own cautionary sentences verbatim; each mutation
# below is a way that block could lie.
# --------------------------------------------------------------------------

def _copy_all(tmp):
    for f in DATA.glob("*.json"):
        shutil.copy2(f, tmp / f.name)


def _patch_caveats(tmp, fn):
    ll = load("landlord.json")
    cav = ll["executive_summary"]["official_outlook"]["prognostic_caveats"]
    fn(cav)
    dump(tmp / "landlord.json", ll)


@case("a prognostic caveat quote edited (no longer verbatim)", "fail",
      "prognostic-caveats-verbatim")
def _pc1(tmp):
    _copy_all(tmp)
    def fn(cav):
        cav["quotes"][0]["text"] = "A PARAPHRASE THIS PROJECT WROTE ITSELF."
    _patch_caveats(tmp, fn)
    return tmp


@case("a prognostic caveat quote with a hand-added key outside the patterns", "fail",
      "prognostic-caveats-verbatim")
def _pc2(tmp):
    _copy_all(tmp)
    def fn(cav):
        cav["quotes"][0]["key"] = "hand_added_opinion"
    _patch_caveats(tmp, fn)
    return tmp


@case("the prognostic caveats block removed from the dataset", "fail",
      "prognostic-caveats-verbatim")
def _pc3(tmp):
    _copy_all(tmp)
    ll = load("landlord.json")
    ll["executive_summary"]["official_outlook"].pop("prognostic_caveats", None)
    dump(tmp / "landlord.json", ll)
    return tmp


@case("caveats claimed available but the archived discussion is gone", "fail",
      "prognostic-caveats-verbatim")
def _pc4(tmp):
    _copy_all(tmp)
    cpc = load("cpc.json")
    cpc["discussions"] = [d for d in cpc.get("discussions", [])
                          if "90-Day" not in (d.get("label") or "")]
    dump(tmp / "cpc.json", cpc)
    return tmp


@case("an honestly unavailable caveats block (reason stated, no quotes)", "pass",
      "prognostic-caveats-verbatim")
def _pc5(tmp):
    _copy_all(tmp)
    def fn(cav):
        cav.clear()
        cav.update({
            "available": False,
            "reason": "The archived 90-day Prognostic Discussion is absent or "
                      "empty in this run, so no caveat can be quoted.",
            "source_url": "https://www.cpc.ncep.noaa.gov/products/predictions/90day/fxus05.html",
            "quotes": [],
        })
    _patch_caveats(tmp, fn)
    return tmp


@case("a control-character (mojibake) sentence smuggled into the quotes", "fail",
      "prognostic-caveats-verbatim")
def _pc6(tmp):
    _copy_all(tmp)
    def fn(cav):
        # A sentence that is otherwise ordinary prose but carries the
        # publisher-side broken smart-quote bytes (\u0080\u009c) inside it.
        cav["quotes"][0]["text"] = "clean text \u0080\u009c with mojibake inside."
    _patch_caveats(tmp, fn)
    return tmp


@case("a Unicode replacement character smuggled into the quotes", "fail",
      "prognostic-caveats-verbatim")
def _pc7(tmp):
    _copy_all(tmp)
    def fn(cav):
        cav["quotes"][0]["text"] = "decoded with replacement \ufffd somewhere."
    _patch_caveats(tmp, fn)
    return tmp


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
