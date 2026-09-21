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
import re
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
# Bug 72, render side: _c2 and _c3 looped for the first non-empty category and
# mutated nothing on a dry discussion, so _c3 "failed" without testing the
# guard and _c2 passed vacuously.  seed_afd_sentence() publishes one verbatim
# sentence from the fetched discussion archived in the same fixture first, so
# both cases exercise the renderer against the shape a stormy night produces.
def _first_prose_sentence(afd_text):
    collapsed = re.sub(r"\s+", " ", afd_text or "").strip()
    for frag in re.split(r"(?<=[.!?])\s+", collapsed):
        s = frag.strip()
        if len(s) < 60:
            continue
        if s.startswith("Issued at"):
            continue
        if "..." in s or "&&" in s or "FXUS" in s or "AFDMTR" in s:
            continue
        if not re.match(r"[A-Z]", s):
            continue
        if s.count(".") > 3:
            continue
        return s
    raise AssertionError("fixture AFD text carries no seedable prose sentence")


def seed_afd_sentence(repo):
    cal_p = repo / "data" / "calendar.json"
    cal = json.loads(cal_p.read_text())
    cats = cal["afd_language"]["categories"]
    if any(c.get("sentences") for c in cats):
        return
    nws = json.loads((repo / "data" / "nws.json").read_text())
    seed = _first_prose_sentence(
        ((nws.get("products") or {}).get("AFD") or {}).get("text") or "")
    section = (cal["afd_language"].get("sections_scanned") or ["LONG TERM"])[0]
    cats[0]["sentences"] = [{
        "section": section, "sentence": seed, "matched_patterns": []}]
    cats[0]["sentence_count"] = 1
    cal["afd_language"]["any_language_found"] = True
    cal_p.write_text(json.dumps(cal))


@case("a quoted AFD sentence edited in the data (ledger's job, not the renderer's)",
      expect_fail=False)
def _c2(repo):
    seed_afd_sentence(repo)
    def fn(cal):
        for cat in cal["afd_language"]["categories"]:
            if cat["sentences"]:
                cat["sentences"][0]["sentence"] = "SENTENCE THE PAGE WAS NOT GIVEN."
                break
    patch_calendar(repo, fn)
    return repo


@case("an AFD quotation given a date")
def _c3(repo):
    seed_afd_sentence(repo)
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
    # itself - which is exactly how a real regression would happen.  The anchor
    # must be the *calendar* renderer's own line: the repair hero clears a grid
    # with the same statement, and patching the first match made this case a
    # silent no-op (it passed on main while claiming to guard the grid).
    patch_text(repo, "assets/js/app.js",
               """  function drawMonth() {
    const grid = $('#calendar-grid');
    grid.innerHTML = '';""",
               """  function drawMonth() {
    const grid = $('#calendar-grid');
    grid.innerHTML = 'NMME guidance below';""")
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


# ==========================================================================
# Cases for render guard 30: the prognostic-discussion caveat card.
# ==========================================================================

@case("a CPC caveat sentence in the dataset but not rendered",
      expect_msg="is in the dataset but not rendered")
def _cav1(repo):
    # The renderer must publish every caveat the dataset carries.  Making the
    # renderer drop one (slicing the list it maps over) while the dataset
    # still lists it is the render defect guard 30 exists to catch.  Editing
    # the dataset's sentence instead is NOT a render defect - the card must
    # faithfully render whatever the dataset publishes, and non-verbatim text
    # is the ledger's job (see falsify_guards.py, case "a prognostic caveat
    # quote edited (no longer verbatim)").
    patch_text(repo, "assets/js/app.js",
               "const quotes = (cav.quotes || []).map(q => [",
               "const quotes = (cav.quotes || []).slice(0, 2).map(q => [")
    return repo


@case("the caveats card rendered without the no-number-attached marker",
      expect_msg="no number or date attached")
def _cav2(repo):
    patch_text(repo, "assets/js/app.js",
               "document.createTextNode('Verbatim quotations, located by pattern in the "
               "fetched text \\u2014 no number or date attached by this project \\u00b7 '),",
               "document.createTextNode('From the discussion \\u00b7 '),")
    return repo


@case("the caveats card rendered without its source link",
      expect_msg="does not link the prognostic discussion")
def _cav3(repo):
    patch_text(repo, "assets/js/app.js",
               "link(cav.source_url, 'Read CPC\\u2019s prognostic discussion')",
               "document.createTextNode('CPC prognostic discussion')")
    return repo


@case("an unavailable caveats card that renders without its stated reason",
      expect_msg="does not state its reason")
def _cav4(repo):
    # Make the dataset honestly unavailable (reason stated), then break the
    # renderer's disclosure of that reason - the reader would see a card that
    # explains nothing about why no caveat is quoted.
    def fn(ll):
        cav = ll["executive_summary"]["official_outlook"]["prognostic_caveats"]
        cav.clear()
        cav.update({
            "available": False,
            "reason": "The archived 90-day Prognostic Discussion is absent or "
                      "empty in this run, so no caveat can be quoted.",
            "source_url": "https://www.cpc.ncep.noaa.gov/products/predictions/90day/fxus05.html",
            "quotes": [],
        })
    patch_json(repo, "data/landlord.json", fn)
    patch_text(repo, "assets/js/app.js",
               "el('div', { class: 'off-sub', text: cav.reason || 'The archived discussion could not be read this run.' }),",
               "el('div', { class: 'off-sub', text: '' }),")
    return repo


# ==========================================================================
# Cases for render guard 31: the ENSO strength outlook card.
# ==========================================================================

@case("an ENSO strength sentence in the dataset but not rendered",
      expect_msg="strength quote")
def _str1(repo):
    # Mirror of _cav1 for the strength card, with one improvement: it asserts
    # the fixture carries at least two quotes before slicing one away, so a
    # rewritten discussion cannot turn this case into a silent no-op pass.
    ll = json.loads((repo / "data" / "landlord.json").read_text())
    n_quotes = len(((((ll.get("executive_summary") or {}).get("official_outlook")
                       or {}).get("enso_strength")) or {}).get("quotes") or [])
    assert n_quotes >= 2, "fixture expected at least two strength quotes to drop one of"
    patch_text(repo, "assets/js/app.js",
               "const squotes = (estr.quotes || []).map(q => [",
               "const squotes = (estr.quotes || []).slice(0, 1).map(q => [")
    return repo


@case("the strength card rendered without its no-added-number marker",
      expect_msg="no number or date of its own")
def _str2(repo):
    patch_text(repo, "assets/js/app.js",
               "document.createTextNode('Quoted verbatim from CPC\\u2019s discussion "
               "\\u2014 no number or date of its own added by this project \\u00b7 '),",
               "document.createTextNode('From the discussion \\u00b7 '),")
    return repo


@case("the strength card rendered without its source link",
      expect_msg="does not link the ENSO Diagnostic Discussion")
def _str3(repo):
    patch_text(repo, "assets/js/app.js",
               "link(estr.source_url, 'Read CPC\\u2019s ENSO Diagnostic Discussion')",
               "document.createTextNode('CPC ENSO Diagnostic Discussion')")
    return repo


@case("an unavailable strength card that renders without its stated reason",
      expect_msg="does not state its reason")
def _str4(repo):
    # Make the dataset honestly unavailable (reason stated), then break the
    # renderer's disclosure of that reason.
    def fn(ll):
        estr = ll["executive_summary"]["official_outlook"]["enso_strength"]
        estr.clear()
        estr.update({
            "available": False,
            "reason": "The archived ENSO Diagnostic Discussion is absent or "
                    "empty in this run, so no strength outlook can be quoted.",
            "source_url": "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml",
            "quotes": [],
        })
    patch_json(repo, "data/landlord.json", fn)
    patch_text(repo, "assets/js/app.js",
               "el('div', { class: 'off-sub', text: estr.reason || 'The archived ENSO discussion could not be read this run.' }),",
               "el('div', { class: 'off-sub', text: '' }),")
    return repo


# The archive-status and per-day deep-link falsification cases that used to live
# here were retired with the modules they covered: main resolved the GSOD/ISD
# stop as an NCEI retirement with its own successor probes, and publishes
# per-field deep links guarded by tests/smoke.js guard 26 and the ledger's
# deep-links-traceable check.  Re-adding cases for code that no longer exists
# would only produce false confidence.



def run_smoke(repo):
    proc = subprocess.run(["node", "tests/smoke.js", str(repo)],
                          capture_output=True, text=True, cwd=str(REPO),
                          env={"PATH": "/usr/bin:/bin:/usr/local/bin", "NODE_PATH": NODE_PATH})
    return proc.returncode, proc.stdout + proc.stderr


# ==========================================================================
# Cases for render guard 32: the phase-conditioned wet-spell column.
# ==========================================================================

@case("the ENSO table rendered without the phase-conditioned spell column",
      expect_msg="lost the phase-conditioned 7+ day wet-spell column")
def _st1(repo):
    patch_text(repo, "assets/js/app.js",
               "{ label: '7+ day wet spell', num: true }, { label: 'Longest run, mean', num: true },",
               "")
    return repo


@case("the phase-conditioned column rendered without its sample size",
      expect_msg="does not print its sample size")
def _st2(repo):
    patch_text(repo, "assets/js/app.js",
               "`${n(st.ge_7_days.pct, 1)}% (${st.ge_7_days.seasons} of ${st.n})`",
               "`${n(st.ge_7_days.pct, 1)}%`")
    return repo


# --------------------------------------------------------------------------
# Guard 33: the phase-conditioned severity table and the wind-station wording.
# --------------------------------------------------------------------------

@case("the severity table in the dataset but not rendered",
      expect_msg="did not render it")
def _sv1(repo):
    patch_text(repo, "assets/js/app.js",
               "if (cs && Array.isArray(cs.rows) && cs.rows.length) {",
               "if (false) {")
    return repo


@case("a severity row rendered with a different value than the dataset",
      expect_msg="not rendered as published")
def _sv2(repo):
    patch_text(repo, "assets/js/app.js",
               "`${fmtOrDash(r.phase_mean)} \\u00b7 ${fmtOrDash(r.phase_median)} \\u00b7 ${fmtOrDash(r.phase_max)}`",
               "`${fmtOrDash(Number(r.phase_mean) + 1)} \\u00b7 ${fmtOrDash(r.phase_median)} \\u00b7 ${fmtOrDash(r.phase_max)}`")
    return repo


@case("the severity cell rendered without the phase n beside the all-season n",
      expect_msg="does not print the phase n")
def _sv3(repo):
    patch_text(repo, "assets/js/app.js",
               "`(${cs.seasons_in_phase} of the ${cs.seasons_total}), beside all seasons`",
               "`, beside all seasons`")
    return repo


@case("the severity cell rendered without the not-a-forecast wording",
      expect_msg="small-sample")
def _sv4(repo):
    patch_text(repo, "assets/js/app.js",
               "el('div', { class: 'off-sub', text: cs.how_to_read || '' }),",
               "el('div', { class: 'off-sub', text: '' }),")
    return repo


@case("a severity row dropped from the render",
      expect_msg="row(s) for")
def _sv5(repo):
    patch_text(repo, "assets/js/app.js",
               "cs.rows.map(r => [\n          r.label,",
               "cs.rows.slice(1).map(r => [\n          r.label,")
    return repo


@case("the ENSO season card rendered without the severity columns",
      expect_msg="lost the severity column")
def _sv6(repo):
    patch_text(repo, "assets/js/app.js",
               "{ label: 'Days \\u2265 1.00 in, mean', num: true }, ",
               "")
    return repo


@case("a severity cell rendered although the dataset has no rows",
      expect_msg="but a severity cell rendered")
def _sv7(repo):
    def fn(ll):
        off = (ll.get("executive_summary") or {}).get("official_outlook") or {}
        off["enso_conditioned_severity"] = None
    patch_json(repo, "data/landlord.json", fn)
    patch_text(repo, "assets/js/app.js",
               "if (cs && Array.isArray(cs.rows) && cs.rows.length) {",
               "if (true) { const cs = { rows: [{label: 'x'}], sources: [] };")
    return repo


@case("the page calling the SFO wind record an upper bound for the Sunset again",
      expect_msg="unsourced direction, bug 74")
def _sv8(repo):
    def fn(ll):
        es = ll.get("executive_summary") or {}
        for item in es.get("bottom_line") or []:
            if item.get("key") == "wind":
                item["answer"] = (item.get("answer") or "") + " Treat these as an upper bound for the Sunset."
    patch_json(repo, "data/landlord.json", fn)
    return repo


@case("the static wind paragraph calling SFO an upper bound for the neighbourhood again",
      expect_msg="unsourced direction, bug 74")
def _sv9(repo):
    patch_text(repo, "index.html",
               "not as a bound for the neighbourhood.",
               "read these as an upper bound for the neighbourhood.")
    return repo



def patch_ocean(repo, fn):
    """Mutate the ocean-wind payload the smoke guard renders.

    The guard reads data/ocean_wind.json when the nightly run has published one and
    the tier's render fixture otherwise, so a case writes the mutated payload to the
    *published* path: that is the file the guard will read whichever exists.  A case
    that mutated the fixture while a published file was present would change nothing
    and pass vacuously.
    """
    src = repo / "data" / "ocean_wind.json"
    if not src.exists():
        src = repo / "tests" / "fixtures" / "ocean_wind_render.json"
    obj = json.loads(src.read_text())
    fn(obj)
    (repo / "data" / "ocean_wind.json").write_text(json.dumps(obj))
    return repo

@case("the Outer Sunset profile card element removed from index.html",
      expect_msg="#landlord-sunset-card element missing from the page")
def _osp1(repo):
    patch_text(repo, "index.html", 'id="landlord-sunset-card"', 'id="landlord-sunset-card-renamed"')
    return repo


@case("the Outer Sunset profile Pacific row dropped",
      expect_msg="missing Pacific Ocean Exposure row")
def _osp2(repo):
    patch_text(repo, "assets/js/app.js",
               "el('tr', {}, [el('th', { text: 'Pacific Ocean Exposure' }), el('td', { text: osp.ocean_exposure })]),",
               "")
    return repo


@case("the ocean-side wind card element removed from index.html",
      expect_msg="ocean-side wind card is missing")
def _ow1(repo):
    patch_text(repo, "index.html", 'id="ocean-wind-body"', 'id="ocean-wind-body-renamed"')
    return repo


@case("the ocean-side wind renderer disabled (card renders nothing)",
      expect_msg="#ocean-wind-body rendered nothing at all")
def _ow2(repo):
    patch_text(repo, "assets/js/app.js",
               "function renderOceanWind(ow, cal) {",
               "function renderOceanWind(ow, cal) { return;")
    return repo


@case("the ocean-side wind caveat paraphrased instead of published verbatim",
      expect_msg="does not carry the dataset caveat phrase")
def _ow3(repo):
    return patch_ocean(repo, lambda ow: ow.update(
        {"caveat": "The buoy is the best available guide to wind in the Sunset."}))


@case("the ocean-side wind coverage line dropped from the payload",
      expect_msg="does not publish how many seasons carry data")
def _ow4(repo):
    return patch_ocean(repo, lambda ow: ow["summary"].pop("seasons_with_data", None))


@case("the ocean-side wind season table rendering only ten of its rows",
      expect_msg="the ocean-wind season table rendered")
def _ow5(repo):
    # The defect is in the renderer, not the payload: a payload that lost seasons
    # is the claim ledger's business (ocean-wind-coverage), while a table that
    # silently drops the seasons with no data would read as a full record.
    patch_text(repo, "assets/js/app.js",
               "const seasons = (ow.seasons || []).slice().sort((a, b) => a.season.localeCompare(b.season));",
               "const seasons = (ow.seasons || []).slice().sort((a, b) => a.season.localeCompare(b.season)).slice(0, 10);")
    return repo


@case("the ocean-side wind card linking to a host that is not NDBC",
      expect_msg="links to a host that is not NDBC")
def _ow6(repo):
    return patch_ocean(repo, lambda ow: ow["station"].update(
        {"station_page_url": "https://example.com/46026"}))



@case("the ocean-side wind record missing and the card silent about it",
      expect_msg="does not say the record is unpublished")
def _ow7(repo):
    # Two edits, one defect: the payload says the record is not published *and* the
    # card stops saying so.  An empty card reads as calm water, which is the whole
    # reason the fallback sentence exists.
    patch_ocean(repo, lambda ow: ow.clear())
    patch_text(repo, "assets/js/app.js",
               "Not published in this snapshot: ", "Nothing to report. ")
    return repo




# ==========================================================================
# Cases for render guard 36: the repair & maintenance executive hero.
#
# The block is generated by pipeline/repair_maintenance_summary.py and rendered
# by renderRepairExecutive().  These cases are all *render* defects: a generator
# that publishes a bad figure is the claim ledger's business (see the
# repair-* checks in pipeline/verify_claims.py), while a renderer that hides,
# truncates or blanks a published figure is this guard's.
# ==========================================================================

def patch_repair(repo, fn):
    """Mutate the repair payload the smoke guard reads."""
    p = repo / "data" / "repair_maintenance_summary.json"
    obj = json.loads(p.read_text())
    fn(obj)
    p.write_text(json.dumps(obj))
    return repo


@case("the repair hero rendering only the first three ranked drivers",
      expect_msg="the repair driver list rendered")
def _rp1(repo):
    patch_repair(repo, lambda r: None)
    return patch_text(repo, "assets/js/app.js",
                      "driversHost.append(...drivers.map(d => {",
                      "driversHost.append(...drivers.slice(0, 3).map(d => {")


@case("the repair hero dropping the severity badge from its drivers",
      expect_msg="does not print the severity")
def _rp2(repo):
    return patch_text(repo, "assets/js/app.js",
                      "{ class: 'severity-badge ' + sev, text: sev.toUpperCase() }",
                      "{ class: 'severity-badge ' + sev, text: '' }")


@case("the repair summary missing and the section silent about it",
      expect_msg="does not say the summary is unpublished")
def _rp3(repo):
    # Two edits, one defect: the payload loses the block the renderer keys on,
    # and the renderer stops saying the summary is unpublished.  A blank hero is
    # read as "no risk", which is the defect the fallback sentence exists for.
    patch_repair(repo, lambda r: r.pop("expected_rain", None))
    return patch_text(repo, "assets/js/app.js",
                      "'The repair & maintenance executive summary is not published in '",
                      "'Nothing to report. '")


@case("a repair source link pointed at a host that is not official",
      expect_msg="host that is not an official source")
def _rp4(repo):
    patch_repair(repo, lambda r: r["sources_list"][0].update({"url": "https://example.com/enso"}))
    return repo


@case("the repair currency line removed from the page",
      expect_msg="repair executive section is missing")
def _rp6(repo):
    return patch_text(repo, "index.html",
                      '<p class="fine repair-currency" id="repair-currency"></p>', '')


@case("the repair watch list rendering one of its verbatim sentences",
      expect_msg="the repair watch list rendered")
def _rp5(repo):
    return patch_text(repo, "assets/js/app.js",
                      "(rep.next_issuances || []).forEach(item => {",
                      "(rep.next_issuances || []).slice(0, 1).forEach(item => {")


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
