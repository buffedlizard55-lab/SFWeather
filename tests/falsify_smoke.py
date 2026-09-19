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



@case("the hourly wind+rain mean is dropped from the landlord data",
      expect_msg="hourly block reports available with no days mean")
def _c8(repo):
    def fn(ll):
        blk = ll["executive_summary"]["wind_and_rain_hourly"]
        blk["days_with_a_simultaneous_hour"].pop("mean", None)
    patch_json(repo, "data/landlord.json", fn)
    return repo


@case("the multi-hour precipitation disclosure is removed")
def _c9(repo):
    def fn(ll):
        for row in ll["executive_summary"]["bottom_line"]:
            if row.get("key") == "wind_and_rain":
                row["confidence"] = row["confidence"].replace(
                    "longer than one hour", "LONGER THAN ONE HOUR")
    patch_json(repo, "data/landlord.json", fn)
    return repo


@case("the stale-archive flag names only the first stale archive")
def _c10(repo):
    p = repo / "assets" / "js" / "app.js"
    s = p.read_text()
    old = "`Flagged: ${stale.map(labelFor).join('; ')} `"
    assert old in s, "fixture cannot mutate the stale-archive line it expects"
    s = s.replace(old, "`Flagged: ${stale.slice(0, 1).map(labelFor).join('; ')} `", 1)
    p.write_text(s)
    return repo


@case("the status line stops disclosing expected absences")
def _c11(repo):
    # First give the fixture the shape the next pipeline run will produce: four
    # fetches that are supposed to be absent.  Then remove the disclosure.
    def fn(prov):
        n = 0
        for e in prov["entries"]:
            if not e.get("ok"):
                e["expected_absent"] = True
                n += 1
        assert n, "fixture expected at least one failed fetch to reclassify"
    patch_json(repo, "data/provenance.json", fn)
    p = repo / "assets" / "js" / "app.js"
    src = p.read_text()
    old = "    + (absent ? ` \u00b7 ${absent} absent by design (not-yet-published annual file or station without an observations endpoint)` : '')"
    assert old in src, "fixture cannot mutate the expected-absence clause it expects"
    p.write_text(src.replace(old, "", 1))
    return repo


@case("the status line counts an expected absence as a failure")
def _c12(repo):
    def fn(prov):
        n = 0
        for e in prov["entries"]:
            if not e.get("ok"):
                e["expected_absent"] = True
                n += 1
        assert n, "fixture expected at least one failed fetch to reclassify"
    patch_json(repo, "data/provenance.json", fn)
    p = repo / "assets" / "js" / "app.js"
    src = p.read_text()
    old = "e.ok === false && !e.expected_absent).length;"
    assert old in src, "fixture cannot mutate the failure count it expects"
    p.write_text(src.replace(old, "e.ok === false).length;", 1))
    return repo


def patch_json(repo, rel, fn):
    p = repo / rel
    data = json.loads(p.read_text())
    fn(data)
    p.write_text(json.dumps(data))


# ==========================================================================
# Cases for the render guards added with the model-guidance tier, the official
# product feed, the archive-status card and the per-day deep links.
# ==========================================================================

MG_INDEX = "https://www.cpc.ncep.noaa.gov/products/NMME/probindex.shtml"
MG_DESCR = "https://www.cpc.ncep.noaa.gov/products/NMME/NMME_PROB_descr.html"
DESCR_TEXT = ("NMME ensemble contains 79 members, all weighted equally. A/B/N "
              "[Above/Below/Neutral] are terciles.")
DESCR_SENTENCES = ["NMME ensemble contains 79 members, all weighted equally.",
                   "A/B/N [Above/Below/Neutral] are terciles."]


def patch_text(repo, relpath, old, new, required=True):
    p = repo / relpath
    text = p.read_text()
    if old not in text:
        if required:
            raise AssertionError(f"fixture expected to find in {relpath}: {old[:60]!r}")
        return repo
    p.write_text(text.replace(old, new, 1))
    return repo


def write_data(repo, name, obj):
    (repo / "data" / name).write_text(json.dumps(obj, indent=2))
    return repo


def mg_fixture(mutate=None):
    mg = {
        "generated_utc": "2026-09-18T21:00:00Z",
        "tier": "model-guidance",
        "not_an_official_forecast": True,
        "merged_into_scoreboard": False,
        "warning": ("MODEL GUIDANCE - NOT AN OFFICIAL FORECAST. Raw multi-model ensemble "
                    "products. Nothing here is merged into the day-by-day scoreboard."),
        "isolation_rule": "enforced by the model-guidance-isolation ledger check",
        "coverage_verbatim": "October 2026 - April 2027",
        "pages": {
            "prob_index": {"key": "prob_index", "label": "NMME probability forecasts",
                           "url": MG_INDEX, "ok": True, "http_status": 200, "bytes": 9000,
                           "sha256": "1" * 64, "retrieved_utc": "2026-09-18T21:00:00Z",
                           "plain_text": "For: October 2026 - April 2027",
                           "why": "states the period the maps cover",
                           "warning": "Model guidance, not an official forecast."},
            "description": {"key": "description", "label": "Description", "url": MG_DESCR,
                            "ok": True, "http_status": 200, "bytes": 8000, "sha256": "2" * 64,
                            "retrieved_utc": "2026-09-18T21:00:01Z",
                            "plain_text": DESCR_TEXT,
                            "verbatim_sentences": list(DESCR_SENTENCES),
                            "why": "defines the contours",
                            "warning": "Model guidance, not an official forecast."},
        },
        "images": [{"variable": "precipitation rate", "variable_key": "prate",
                    "season_index": 1, "url": MG_INDEX, "ok": True, "http_status": 200,
                    "bytes": 4321, "sha256": "3" * 64,
                    "local_path": "assets/model_guidance/nmme_prate_us_season1.png",
                    "season_mapping_note": "the month range is printed inside the image",
                    "warning": "Model guidance, not an official forecast."}],
        "probes": [],
        "counts": {"pages_requested": 2, "pages_retrieved": 2, "images_archived": 1,
                   "verbatim_sentences": 2, "probes_ok": 0},
        "what_this_tier_does_not_do": ["It does not convert an ensemble into a probability "
                                       "for one ZIP code."],
        "irregularities": [],
    }
    if mutate:
        mutate(mg)
    return mg


@case("model guidance published: warning first, quotes verbatim, images labelled",
      expect_fail=False)
def _mg_ok(repo):
    write_data(repo, "model_guidance.json", mg_fixture())
    return repo


@case("a model-guidance image rendered without its own warning",
      expect_msg="no warning of its own")
def _mg_no_item_warning(repo):
    def mutate(mg):
        mg["images"][0]["warning"] = ""
    write_data(repo, "model_guidance.json", mg_fixture(mutate))
    return repo


@case("NOAA's coverage string dropped from the model-guidance card",
      expect_msg="coverage string is not rendered verbatim")
def _mg_no_coverage(repo):
    patch_text(repo, "assets/js/app.js",
               "if (mg.coverage_verbatim) {", "if (false && mg.coverage_verbatim) {")
    write_data(repo, "model_guidance.json", mg_fixture())
    return repo


@case("an NMME definition sentence paraphrased by the renderer",
      expect_msg="not rendered verbatim")
def _mg_paraphrase(repo):
    patch_text(repo, "assets/js/app.js",
               "el('span', { class: 'verbatim', text: '\\u201c' + t + '\\u201d' })]))",
               "el('span', { class: 'verbatim', text: t.replace(/79/, 'eighty') })]))")
    write_data(repo, "model_guidance.json", mg_fixture())
    return repo


@case("the model-guidance tier mentioned inside the scoreboard grid",
      expect_msg="scoreboard grid mentions the model-guidance tier")
def _mg_leak(repo):
    # The renderer clears the grid, so the leak has to come from the renderer
    # itself - which is exactly how a real regression would happen.
    patch_text(repo, "assets/js/app.js",
               "    grid.innerHTML = '';",
               "    grid.innerHTML = 'NMME guidance below';")
    write_data(repo, "model_guidance.json", mg_fixture())
    return repo


@case("the model-guidance host element removed from the page",
      expect_msg="section rendered empty: #model-guidance-body")
def _mg_missing_host(repo):
    patch_text(repo, "index.html", '<div id="model-guidance-body"></div>', "")
    return repo


@case("the feed stops reporting its own entry count",
      expect_msg="does not report its own entry count")
def _feed_count(repo):
    patch_text(repo, "assets/js/app.js",
               "(c.entries || 0) + ' entries, ' +",
               "((c.entries || 0) + 1) + ' entries, ' +")
    return repo


@case("the feed rendered oldest first", expect_msg="not rendered newest first")
def _feed_order(repo):
    patch_text(repo, "assets/js/app.js",
               "const all = (feed.entries || []).concat(feed.undated_entries || []);",
               "const all = (feed.entries || []).slice().reverse()"
               ".concat(feed.undated_entries || []);")
    return repo


@case("the feed hides that a publisher gave a date with no time",
      expect_msg="no clock time was published")
def _feed_date_only(repo):
    patch_text(repo, "assets/js/app.js", "if (dateOnly || undated) {", "if (false) {")
    return repo


@case("a feed row rendered without its official/not-official pill",
      expect_msg="no official/not-official pill")
def _feed_pill(repo):
    patch_text(repo, "assets/js/app.js",
               "    officialPill(e.official !== false),",
               "    el('span', { text: '' }),")
    return repo


@case("the archive-status card drops the probe's verdict",
      expect_msg="verdict is not rendered")
def _probe_verdict(repo):
    run = json.loads((repo / "data" / "run.json").read_text())
    wind = next(a for a in run["record_coverage"]["archives"] if a["area"] == "wind")
    write_data(repo, "ncei_archive_probe.json", {
        "generated_utc": "2026-09-18T22:00:00Z",
        "station_id": "72494023234",
        "last_date_published_by_the_site": wind["last_date"],
        "verdict": {"classification": "archive-wide-lag", "statement": "fixture statement",
                    "gap_days": 3, "slack_days_allowed": 15},
        "recommended_actions": [{"action": "keep the stale-archive flag and re-probe nightly"}],
        "tests": [],
    })
    patch_text(repo, "assets/js/app.js",
               "el('h3', { text: 'Verdict: ' + (v.classification || 'not determined') }),",
               "el('h3', { text: 'Verdict: not determined' }),")
    return repo


@case("the archive-status card drops a recommended action",
      expect_msg="recommended action from the probe is not rendered")
def _probe_actions(repo):
    run = json.loads((repo / "data" / "run.json").read_text())
    wind = next(a for a in run["record_coverage"]["archives"] if a["area"] == "wind")
    write_data(repo, "ncei_archive_probe.json", {
        "generated_utc": "2026-09-18T22:00:00Z",
        "last_date_published_by_the_site": wind["last_date"],
        "verdict": {"classification": "archive-wide-lag", "statement": "fixture"},
        "recommended_actions": [{"action": "keep the stale-archive flag and re-probe nightly"}],
        "tests": [],
    })
    patch_text(repo, "assets/js/app.js", "if (actions.length) {", "if (false) {")
    return repo


@case("a station-day deep link pointing at another date",
      expect_msg="does not ask for")
def _dl_wrong_date(repo):
    def mutate(cal):
        day = next(d for d in cal["days"] if d["date"] == cal["days"][0]["date"])
        for dl in day["deep_links"]:
            dl["url"] = dl["url"].replace(day["date"], "2026-12-25")
    patch_calendar(repo, mutate)
    return repo


@case("a deep link leaving the official hosts", expect_msg="leaves the official hosts")
def _dl_bad_host(repo):
    def mutate(cal):
        cal["days"][0]["deep_links"][0]["url"] = "https://accuweather.example/day"
    patch_calendar(repo, mutate)
    return repo


@case("a day with no deep links at all", expect_msg="offers no deep link")
def _dl_missing(repo):
    patch_calendar(repo, lambda cal: cal["days"][0].__setitem__("deep_links", []))
    return repo


@case("deep links rendered without saying whether this run fetched them",
      expect_msg="does not say whether this run fetched it")
def _dl_no_pill(repo):
    patch_text(repo, "assets/js/app.js",
               "        el('span', { class: 'pill ' + (dl.fetched_by_this_run ? 'pill-ok' : ''),\n"
               "          text: dl.fetched_by_this_run ? 'fetched this run' : 'link only' }),",
               "        el('span', { class: 'pill' }),")
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
