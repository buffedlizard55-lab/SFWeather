#!/usr/bin/env python3
"""Offline self-test for the repair & maintenance executive-summary tier.

The tier's risks are specific, and each one is asserted here against synthetic
datasets shaped like the real ones (no network, temporary directories only):

* a **number typed into the generator** rather than read from a dataset - asserted
  by extracting every numeric token from the generated page and requiring it to
  exist in the JSON the page was generated from;
* a **stale artifact looking fresh** - asserted by building from datasets written
  by two different runs and requiring ``currency.is_current`` to be false while
  the published stamp stays the landlord.json stamp;
* a **quote paraphrased or reconstructed** - asserted by rewriting NOAA's sentence
  in the synthetic fetched text and requiring the entry to move to
  ``next_issuances_not_found`` instead of being repaired;
* a **null published as a figure** - asserted by disabling the ocean-buoy tier and
  requiring an explicit sentence, with no ``None`` anywhere in the page;
* an **undocumented severity** - asserted against the published rank rule.

Writes only into temporary directories; touches no network.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import repair_maintenance_summary as rt  # noqa: E402

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok, detail: str = "") -> None:
    CHECKS.append((name, bool(ok), str(detail)))


# NOAA's real sentences, copied from the fetched CPC pages this project reads.
ENSO_SENTENCE = ("The next ENSO Diagnostics Discussion is scheduled for "
                 "8 October 2026.")
NEXT_SET_SENTENCE = ("These probabilities may be increased further in the next "
                     "set of seasonal outlooks, to be released in mid-late "
                     "October, pending reassessment of the latest model "
                     "forecasts.")
SUPERSEDE_SENTENCE = ("This set of outlooks will be superseded by the issuance "
                      "of the new set next month on Oct 15 2026")

def _wrapped(sentence, width=72):
    """Wrap a sentence the way CPC's HTML-to-text conversion does.

    The real archived pages break sentences across lines at arbitrary points
    ("...in the next set \n of seasonal outlooks..."), which is why the tier must
    search whitespace-collapsed text.  The fixtures wrap too, so that path is
    exercised rather than assumed.
    """
    words, lines, cur = sentence.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return "\n".join(lines)


ENSO_PAGE_TEXT = (
    "EL NIÑO/SOUTHERN OSCILLATION (ENSO) DIAGNOSTIC DISCUSSION issued by "
    "CLIMATE PREDICTION CENTER/NCEP/NWS " + _wrapped(ENSO_SENTENCE, 40) +
    " To receive an e-mail notification when the monthly ENSO Diagnostic "
    "Discussions are released, please send an e-mail message to: "
    "ncep.list.enso-update@noaa.gov")
CPC_PAGE_TEXT = (
    "Prognostic Discussion for Monthly and Seasonal Outlooks.\n"
    "The first factor is the presence of a fairly strong, negatively phased "
    "Pacific Decadal Oscillation (PDO). " + _wrapped(NEXT_SET_SENTENCE) + "\n"
    + _wrapped(SUPERSEDE_SENTENCE) + "\n1991-2020 base period means were "
    "implemented effective with the May 20, 2021 forecast release.")


def _driver(rank, name, why="A reason that is published as guidance.",
            sources=None, evidence=None):
    return {
        "rank": rank,
        "driver": name,
        "why_it_costs": why,
        "evidence": evidence if evidence is not None else
        [{"label": f"Metric {rank}", "value": f"{rank}.5 units"}],
        "sources": sources if sources is not None else
        [{"label": "NCEI GHCN-Daily", "url": rt.SOURCES["ghcn_daily"][1]}],
    }


def _near_term_window(rain):
    """A hand-computable three-day NWS window shaped like the verified one.

    *rain* is the per-day rain amount list; every other field is fixed so the
    expected counts below can be checked by hand:
      rain >= 0.1  -> days 2 and 3 (0.15, 0.30);  gust >= 30 -> days 2 and 3
      (32.0, 30.0);  window rain total 0.47 in;  56 grid hours.
    """
    def day(date, weekday, hours, high, pop, r, gust):
        return {
            "date": date, "weekday": weekday, "hours_covered": hours,
            "high_f": high, "low_f": 58, "humidity_pct": 90.0,
            "rain_chance_pct": pop, "rain_amount_in": r, "wind_max_mph": 12.0,
            "gust_max_mph": gust,
            "temp_basis": "synthetic temp basis",
            "humidity_basis": "synthetic humidity basis",
            "rain_chance_basis": "synthetic pop basis",
            "rain_amount_basis": "synthetic rain basis",
            "wind_basis": "synthetic wind basis",
            "gust_basis": "synthetic gust basis",
        }
    return {
        "first_day": "2026-09-21", "last_day": "2026-09-23",
        "horizon_days": 3, "inside_season_window": False,
        "forecast_updated": "2026-09-21T20:26:08+00:00",
        "days": [
            day("2026-09-21", "Monday", 8, 61, 2, rain[0], 16.1),
            day("2026-09-22", "Tuesday", 24, 63, 30, rain[1], 32.0),
            day("2026-09-23", "Wednesday", 24, 70, 20, rain[2], 30.0),
        ],
        "sources": [{"label": "NWS hourly gridded forecast (api.weather.gov)",
                     "url": rt.SOURCES["nws_api"][1]}],
    }


def synthetic_datasets(stamp="2026-09-21T14:20:21Z", calendar_stamp=None,
                       ocean_available=True, rewrite_enso_sentence=False,
                       driver_list=None, near_term="absent"):
    """Build datasets shaped like the committed ones, with hand-checkable values."""
    calendar_stamp = calendar_stamp or stamp
    enso_text = ENSO_PAGE_TEXT
    if rewrite_enso_sentence:
        # CPC rewrites the sentence so that the pattern this project watches no
        # longer matches.  The date is real, the wording is not: the tier must
        # drop the entry rather than publish a sentence NOAA no longer wrote.
        # The replacement is made against the wrapped block the fixture actually
        # contains - a no-op replace() here would make this case a silent pass.
        block = _wrapped(ENSO_SENTENCE, 40)
        assert block in enso_text, "fixture must contain the wrapped sentence"
        enso_text = enso_text.replace(
            block, "CPC will publish its next ENSO assessment on 5 November 2026.")
    drivers = driver_list if driver_list is not None else [
        _driver(1, "Prolonged wet spells \u2014 roof, gutters & drainage"),
        _driver(2, "Heavy single-day rain \u2014 storm drains, entryways"),
        _driver(3, "Wind + rain together \u2014 wind-driven water intrusion"),
        _driver(4, "Peak gusts \u2014 trees, fences, roofing & tenant safety"),
        _driver(5, "Total seasonal water load \u2014 waterproofing budget"),
        _driver(6, "Wet-day frequency \u2014 condensation, ventilation"),
    ]
    landlord = {
        "generated_utc": stamp,
        "executive_summary": {
            "location": "San Francisco, CA 94122 (test fixture)",
            "season_window": "October 1, 2026 - January 31, 2027 (123 days)",
            "key_finding": "A hand-written test fixture headline.",
            "verified_coordinate_source": "U.S. Census Bureau Gazetteer file",
            "coordinate_source_url": rt.SOURCES["census"][1],
            "current_enso": {"label": "JJA 2026", "phase": "el_nino",
                             "phase_label": "El Niño", "oni_c": 1.8,
                             "oni_c_fmt": "+1.80 °C", "strength": "strong",
                             "strength_label": "strong"},
            "official_outlook": {
                "enso": {"state": "El Niño (+1.80 °C, JJA 2026)",
                         "alert_status": "El Niño Advisory",
                         "source_url": rt.SOURCES["enso_discussion"][1]},
                "cpc_tilt": {
                    "periods_covering_this_season": 6, "periods_with_a_tilt": 2,
                    "periods_at_climatological_baseline": 4, "baseline_pct": 33.3,
                    "highest_probability": {"period": "JFM 2027", "issued": "2026-09-17",
                                            "category_label": "Above median",
                                            "probability_pct": 50.0,
                                            "source_url": "https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst/seasprcp_202609.zip"},
                    "rows": [], "method": "sampled at the 94122 point",
                    "source_url": rt.SOURCES["cpc_gis"][1]},
                "daily_forecast": {"days_in_this_scoreboard_with_a_real_forecast": 0,
                                   "official_horizon_ends": "2026-09-27"},
                "enso_strength": {"available": True, "not_found": [],
                                  "quotes": [{"key": "k", "label": "CPC on strength",
                                              "text": "A verbatim sentence about strength.",
                                              "source_url": rt.SOURCES["enso_discussion"][1]}]},
                "prognostic_caveats": {"available": True, "not_found": ["a_rewritten_key"],
                                       "how_to_read": "Verbatim sentences.",
                                       "quotes": [{"key": "pdo_state", "label": "PDO",
                                                   "text": "A verbatim caveat sentence.",
                                                   "source_url": rt.SOURCES["cpc_discussion"][1]}]},
                "enso_conditioned_record": {
                    "phase": "el_nino", "phase_label": "El Niño",
                    "seasons_in_phase": 11, "mean_in": 14.23, "median_in": 13.56,
                    "min_in": 7.27, "max_in": 22.82,
                    "contrast": [], "how_to_read": "A conditional average, not a forecast.",
                    "source_url": rt.SOURCES["oni"][1]},
            },
            "streak_probability": {"ge_3_days": {"seasons": 29, "pct": 96.7},
                                   "ge_5_days": {"seasons": 24, "pct": 80.0},
                                   "ge_7_days": {"seasons": 16, "pct": 53.3},
                                   "ge_10_days": {"seasons": 7, "pct": 23.3}},
            "longest_streak": {"n": 30, "mean": 7.3, "median": 7.0, "max": 17.0},
            "enso_stratified_streaks": {"el_nino": {
                "n": 11, "phase_label": "El Niño",
                "longest_streak_days": {"mean": 9.1, "max": 17.0},
                "ge_7_days": {"seasons": 9, "pct": 81.8},
                "ge_10_days": {"seasons": 4, "pct": 36.4}}},
            "wind_and_rain_hourly": {
                "available": True, "station_id": "72494023234",
                "station_name": "SAN FRANCISCO INTERNATIONAL AIRPORT (KSFO)",
                "wind_threshold_kt": 20,
                "simultaneous_hours_from_multi_hour_reports": 11.0,
                "days_with_a_simultaneous_hour": {"n": 30, "mean": 7.9, "median": 7.0, "max": 16.0},
                "simultaneous_hours_per_season": {"mean": 29.5, "median": 27.0, "max": 66.0},
            },
            "wind_and_rain": {"n": 30, "mean": 11.1, "median": 10.0, "max": 24.0},
            "heavy_wind_and_rain": {"n": 30, "mean": 2.2, "median": 2.0, "max": 8.0},
            "max_gust": {"n": 30, "mean": 53.8, "median": 54.1, "min": 41.3, "max": 70.0},
            "season_total_prcp": {"n": 30, "mean": 12.79, "median": 13.26, "min": 1.71,
                                  "max": 22.82, "p10": 6.38, "p90": 18.59},
            "oct_total": {"mean": 0.94}, "nov_total": {"mean": 2.6},
            "dec_total": {"mean": 4.78}, "jan_total": {"mean": 4.47},
            "ocean_wind": ({
                "available": True, "station_id": "46026", "station_name": "SF - 18 NM West",
                "distance_mi_from_centroid": 19.4, "seasons_with_data": 28,
                "seasons_total": 30, "thin_seasons": [],
                "gale_days_ge_34kt": {"mean": 7.37, "max": 15.0},
                "max_gust_mph": {"mean": 50.86, "max": 62.0},
                "caveat": "NOT A LAND STATION and NOT A MEASUREMENT INSIDE ZIP 94122.",
                "is_a_bound_for_94122": False,
                "source_urls": [rt.SOURCES["ndbc_46026"][1]]}
                if ocean_available else
                {"available": False, "caveat": None, "source_urls": []}),
            "cost_drivers": drivers,
            "cost_drivers_note": "Ranked for the landlord question behind this site.",
            "outer_sunset_profile": {"neighborhood": "Outer Sunset / Sunset District",
                                     "centroid_coordinates": "37.7605N, -122.4839W"},
            "bottom_line": [],
            "record_coverage": {"as_of": "2026-09-21",
                                "archives": [{"label": "GHCN-Daily USW00023272",
                                              "last_date": "2026-09-18", "age_days": 3,
                                              "url": rt.SOURCES["ghcn_daily"][1]}]},
        },
    }
    calendar = {
        "generated_utc": calendar_stamp,
        "definitions": {
            "wet_day": "calendar day with >= 0.01 in of liquid precipitation",
            "wet_streak": "consecutive wet days within Oct 1 - Jan 31",
            "wind_and_rain_day": "SFO ASOS daily max sustained wind >= 20 kt AND precip >= 0.01 in",
            "heavy_wind_and_rain_day": "SFO ASOS max gust >= 35 kt AND precip >= 0.50 in"},
        "days": [{"date": "2026-10-01", "tier": "climatology", "high_f": 70.3,
                  "low_f": 56.1, "humidity_pct": 68.7, "wind_max_mph": 20.6,
                  "gust_max_mph": 26.6, "rain_chance_pct": 10.0,
                  "rain_amount_in": 0.005},
                 {"date": "2026-10-02", "tier": "climatology", "high_f": 70.4,
                  "low_f": 56.0, "humidity_pct": 68.9, "wind_max_mph": 20.4,
                  "gust_max_mph": 26.2, "rain_chance_pct": 11.0,
                  "rain_amount_in": 0.01}],
    }
    if near_term == "days":
        calendar["current_forecast"] = _near_term_window([0.02, 0.15, 0.30])
    elif near_term == "dry":
        calendar["current_forecast"] = _near_term_window([0.0, 0.0, 0.0])
    elif near_term == "empty":
        calendar["current_forecast"] = {
            "first_day": "2026-09-21", "last_day": None, "horizon_days": 0,
            "inside_season_window": False,
            "forecast_updated": "2026-09-21T20:26:08+00:00", "days": [],
            "sources": [{"label": "NWS hourly gridded forecast (api.weather.gov)",
                         "url": rt.SOURCES["nws_api"][1]}],
        }
    # "absent" (the default) leaves the key out entirely, the way a run whose
    # NWS fetch failed would.
    run = {"generated_utc": stamp,
           "target": {"zip": "94122", "label": "San Francisco, CA 94122",
                      "centroid": {"lat": 37.760459, "lon": -122.483894,
                                   "url": rt.SOURCES["census"][1]}}}
    cpc = {"generated_utc": stamp,
           "discussions": [{"label": "90-Day (3-month) Outlook Discussion",
                            "url": rt.SOURCES["cpc_discussion"][1],
                            "sha256": "c" * 64, "text": CPC_PAGE_TEXT,
                            "retrieved_utc": "2026-09-21T14:16:51Z"}]}
    enso = {"generated_utc": stamp,
            "sources": [{"label": "ENSO Diagnostic Discussion",
                         "url": rt.SOURCES["enso_discussion"][1],
                         "sha256": "e" * 64, "text": enso_text,
                         "retrieved_utc": "2026-09-21T14:16:56Z"}]}
    nws = {"generated_utc": stamp,
           "gridpoint_raw": {"generated_at": "2026-09-21T14:05:00Z"}}
    return {"landlord.json": landlord, "calendar.json": calendar, "run.json": run,
            "cpc.json": cpc, "enso.json": enso, "nws.json": nws}


def _summary(**kw):
    return rt.build_summary(synthetic_datasets(**kw))


# --------------------------------------------------------------------------- #

def run() -> int:
    # 1. Severity is a pure function of rank, and the rule is published.
    try:
        got = [rt.severity_for_rank(r) for r in range(1, 7)]
        check("severity follows the published rank rule",
              got == ["high", "high", "high", "medium", "medium", "low"], got)
    except rt.RepairTierError as exc:
        check("severity follows the published rank rule", False, str(exc))
    try:
        rt.severity_for_rank("first")
        check("a non-integer rank is refused", False, "no error raised")
    except rt.RepairTierError:
        check("a non-integer rank is refused", True)

    s = _summary()
    ranks = [d["rank"] for d in s["cost_drivers_ranked"]]
    sevs = [d["severity"] for d in s["cost_drivers_ranked"]]
    check("every driver carries a severity from its rank",
          ranks == [1, 2, 3, 4, 5, 6] and sevs == ["high", "high", "high", "medium", "medium", "low"],
          f"{ranks} {sevs}")
    check("the severity rule is published with every driver",
          all(d.get("severity_rule") == rt.SEVERITY_RULE for d in s["cost_drivers_ranked"]))

    # 2. The stamp rule: never the wall clock, always the landlord dataset, and
    #    a disagreement between datasets is published rather than hidden.
    check("generated_utc is the landlord.json stamp",
          s["generated_utc"] == "2026-09-21T14:20:21Z", s["generated_utc"])
    check("a single-stamp build is marked current", s["currency"]["is_current"] is True,
          json.dumps(s["currency"]))
    check("inputs that carry no build stamp are listed, not assumed to agree",
          s["currency"]["sources_without_a_build_stamp"] == [],
          json.dumps(s["currency"]["sources_without_a_build_stamp"]))
    stale = _summary(calendar_stamp="2026-09-20T00:00:00Z")
    check("datasets from two different runs are not marked current",
          stale["currency"]["is_current"] is False
          and stale["currency"]["sources_disagreeing"] == ["calendar.json"],
          json.dumps(stale["currency"]))
    check("a stale build keeps the dataset's own stamp, never a wall-clock one",
          stale["generated_utc"] == "2026-09-21T14:20:21Z"
          and stale["currency"]["oldest_source_utc"] == "2026-09-20T00:00:00Z",
          f"{stale['generated_utc']} / {stale['currency']}")

    # The fetch containers carry no build stamp: they must be reported, with the
    # newest content fetched into them, instead of being silently folded in.
    unstamped = synthetic_datasets()
    unstamped["cpc.json"].pop("generated_utc")
    s2 = rt.build_summary(unstamped)
    check("a fetch container with no build stamp is listed with its content time",
          s2["currency"]["sources_without_a_build_stamp"] == ["cpc.json"]
          and s2["sources_read"]["cpc.json"]["content_as_of_utc"] == "2026-09-21T14:16:51Z"
          and s2["currency"]["is_current"] is True
          and "carry no build stamp" in s2["currency"]["note"],
          json.dumps(s2["currency"]))
    future = synthetic_datasets()
    future["cpc.json"]["discussions"][0]["retrieved_utc"] = "2026-09-22T09:00:00Z"
    s3 = rt.build_summary(future)
    check("content fetched after the artifact stamp marks the summary not current",
          s3["currency"]["is_current"] is False
          and s3["currency"]["content_newer_than_the_artifact"] == ["cpc.json"],
          json.dumps(s3["currency"]))

    # 3. Contract failures stop the run instead of publishing a hole.
    bad_ranks = [_driver(1, "a"), _driver(1, "b")]
    try:
        rt.build_summary(synthetic_datasets(driver_list=bad_ranks))
        check("duplicate ranks stop the build", False, "no error raised")
    except rt.RepairTierError:
        check("duplicate ranks stop the build", True)
    try:
        rt.build_summary(synthetic_datasets(driver_list=[_driver(1, "a", why="")]))
        check("a driver with no guidance sentence stops the build", False, "no error raised")
    except rt.RepairTierError:
        check("a driver with no guidance sentence stops the build", True)
    try:
        rt.build_summary(synthetic_datasets(driver_list=[_driver(1, "a", sources=[])]))
        check("a driver with no source URL stops the build", False, "no error raised")
    except rt.RepairTierError:
        check("a driver with no source URL stops the build", True)

    # 4. Absent data is published as absent - no null dressed up as a figure.
    no_buoy = _summary(ocean_available=False)
    md = rt.render_markdown(no_buoy)
    check("an unpublished ocean-wind tier is labelled, not left blank",
          no_buoy["ocean_wind"]["available"] is False
          and no_buoy["ocean_wind"]["status"] == "not published in this snapshot"
          and "not published in this snapshot" in md,
          no_buoy["ocean_wind"].get("unavailable_note"))
    check("no null reaches the printable page as a figure",
          "None" not in md and "null" not in md,
          "; ".join(l for l in md.splitlines() if "None" in l or "null" in l)[:200])

    # 5. The watch list quotes NOAA verbatim; a rewritten sentence is dropped.
    texts = [i["text"] for i in s["next_issuances"]]
    keys = {i["key"] for i in s["next_issuances"]}
    check("all three scheduled/next-issuance sentences are located",
          keys == {"next_enso_discussion", "next_long_lead_may_rise",
                   "next_long_lead_issuance"}, sorted(keys))
    check("the ENSO sentence is carried verbatim",
          ENSO_SENTENCE in texts, texts[:1])
    check("the 'may be increased further' sentence is carried verbatim",
          NEXT_SET_SENTENCE in texts)
    check("the named issuance date is captured, not invented",
          next(i["value"] for i in s["next_issuances"]
               if i["key"] == "next_enso_discussion") == "8 October 2026",
          [i.get("value") for i in s["next_issuances"]])
    from climo import collapse_ws as _collapse  # same rule the ledger uses
    check("every extracted sentence is a verbatim substring of its fetched page",
          all(i["text"] in _collapse(CPC_PAGE_TEXT if "fxus05" in (i["source_url"] or "")
                                     else ENSO_PAGE_TEXT)
              for i in s["next_issuances"]))
    check("a sentence broken across lines in the fetched page is still found "
          "(and published collapsed)",
          "\n" in ENSO_PAGE_TEXT and "\n" not in next(
              i["text"] for i in s["next_issuances"] if i["key"] == "next_enso_discussion"))
    check("the extraction records the file it read, with its hash",
          all(i.get("source_sha256") and i.get("source_url") for i in s["next_issuances"]))
    rewritten = _summary(rewrite_enso_sentence=True)
    check("a rewritten sentence moves to not-found instead of being repaired",
          "next_enso_discussion" in rewritten["next_issuances_not_found"]
          and all(i["key"] != "next_enso_discussion" for i in rewritten["next_issuances"]),
          json.dumps(rewritten["next_issuances_not_found"]))
    check("caveat sentences that vanished are listed as not found, not rewritten",
          s["caveats_not_found"] == ["a_rewritten_key"], s.get("caveats_not_found"))

    # 6. Numbers are copied, never retyped: every value on the printable page must
    #    be a value published in the JSON it was generated from.  The page must be
    #    the *complete* one here (the absence case above renders a page with no
    #    ocean block, which would silently skip that block's figures).
    md_full = rt.render_markdown(s)
    json_text = json.dumps(s, ensure_ascii=False, default=str)
    # The lookbehind keeps a year range ("1991-2020") reading as two values and a
    # real negative reading with its sign.
    number = r"(?<![\d.])-?\d+(?:\.\d+)?"
    json_values = {float(t) for t in re.findall(number, json_text)}
    # A thousands separator is stripped only between digits, so a coordinate
    # written "37.7605,-122.4839" keeps its sign.
    md_plain = re.sub(r"(?<=\d),(?=\d{3}\b)", "", md_full)
    # URLs are checked separately below; their digit runs are coordinates or
    # product ids, not figures (kept in step with the claim ledger's rule).
    md_plain = re.sub(r"https?://\S+", "", md_plain)
    md_values = {float(t) for t in re.findall(number, md_plain)}
    tokens = sorted(md_values)
    orphan = [t for t in sorted(md_values) if t not in json_values]
    check("every number on the printable page exists in the JSON it came from",
          not orphan, f"orphan values: {orphan[:8]} of {len(tokens)}")
    md_urls = sorted(set(re.findall(r"https?://[^\s)\]\"]+", md_full)))
    check("every URL on the printable page exists in the JSON it came from",
          not [u for u in md_urls if u not in json_text],
          [u for u in md_urls if u not in json_text][:4])
    check("the headline rain figures are the source values, unchanged",
          s["expected_rain"]["season_total_mean_in"] == 12.79
          and s["expected_rain"]["season_total_p90_in"] == 18.59
          and s["rain_duration"]["phase_conditioned"]["ge_7_days_pct"] == 81.8,
          json.dumps(s["expected_rain"]))

    # 7. Determinism: two builds of the same data are byte-identical.
    check("the build is deterministic",
          json.dumps(_summary(), sort_keys=True) == json.dumps(_summary(), sort_keys=True))
    check("the printable page is deterministic",
          rt.render_markdown(_summary()) == rt.render_markdown(_summary()))

    # 8. main() writes all three artifacts, and writes nothing when the dataset
    #    it summarises is absent.
    with tempfile.TemporaryDirectory() as td:
        data_dir = Path(td) / "data"
        docs_dir = Path(td) / "docs"
        data_dir.mkdir()
        for name, payload in synthetic_datasets().items():
            (data_dir / name).write_text(json.dumps(payload), encoding="utf-8")
        rc = rt.main(["--datadir", str(data_dir), "--docsdir", str(docs_dir)])
        wrote = [(data_dir / "repair_maintenance_summary.json").exists(),
                 (data_dir / "repair_maintenance_executive.md").exists(),
                 (docs_dir / "REPAIR_MAINTENANCE_EXECUTIVE_SUMMARY.md").exists()]
        check("main() writes the JSON, the printable page and the docs copy",
              rc == 0 and all(wrote), f"rc={rc} wrote={wrote}")
        check("the docs copy is byte-identical to the data copy",
              (data_dir / "repair_maintenance_executive.md").read_text(encoding="utf-8")
              == (docs_dir / "REPAIR_MAINTENANCE_EXECUTIVE_SUMMARY.md").read_text(encoding="utf-8"))
        first = (data_dir / "repair_maintenance_summary.json").read_bytes()
        rt.main(["--datadir", str(data_dir), "--docsdir", str(docs_dir)])
        check("re-running main() over the same data changes nothing",
              (data_dir / "repair_maintenance_summary.json").read_bytes() == first)

    with tempfile.TemporaryDirectory() as td:
        data_dir = Path(td) / "data"
        data_dir.mkdir()
        (data_dir / "landlord.json").write_text(json.dumps({"generated_utc": "x"}),
                                                encoding="utf-8")
        rc = rt.main(["--datadir", str(data_dir), "--docsdir", str(Path(td) / "docs")])
        check("an absent executive_summary block writes nothing and exits non-zero",
              rc == 1 and not (data_dir / "repair_maintenance_summary.json").exists(), rc)

    # 9. The published source ledger is official-only, and the coordinate URL is
    #    the one the run actually recorded.
    hosts = {u.split("/", 3)[2] for u in s["sources"].values()}
    check("every source host in the ledger is an official government host",
          all(h.endswith(".gov") or h.endswith(".noaa.gov") for h in hosts), sorted(hosts))
    check("the census URL published is the file the run fetched, not a guess",
          s["sources"]["census"].startswith("https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"),
          s["sources"]["census"])
    check("every source URL in the ledger appears in the JSON's own detail block",
          all(s["sources_detail"][k]["url"] == v for k, v in s["sources"].items()))

    # 10. The scoreboard block answers the seven requested day fields honestly.
    sb = s["scoreboard"]
    check("the scoreboard publishes how many days carry all seven requested fields",
          sb["days_total"] == 2 and sb["days_with_all_seven_fields"] == 2
          and sb["days_with_a_real_official_forecast_now"] == 0, json.dumps(sb))
    check("the scoreboard keeps the no-invented-forecast rule in its own words",
          "No daily forecast is invented" in (sb.get("note") or ""))


    # 11. Two values the tier derives instead of typing them: the distance to the
    #     SFO station (read out of the dataset's own sentence) and the gale
    #     threshold (read out of the dataset's own key name).
    with_distance = synthetic_datasets()
    with_distance["landlord.json"]["caveats"] = [
        "Wind data come from the SFO ASOS (KSFO), 11.9 miles south-east of 94122 "
        "(great-circle distance from the ZIP centroid to the station)."]
    s4 = rt.build_summary(with_distance)
    check("the station distance is parsed from the dataset's own sentence",
          s4["peak_gusts"]["distance_mi"] == 11.9
          and "11.9 miles" in (s4["peak_gusts"]["distance_sentence"] or ""),
          json.dumps(s4["peak_gusts"].get("distance_sentence")))
    check("a dataset that never states the distance yields no distance",
          s["peak_gusts"]["distance_mi"] is None
          and "No dataset read by this tier states" in s["peak_gusts"]["distance_note"],
          s["peak_gusts"].get("distance_note"))
    # The distance sentence must survive being the first sentence in its string,
    # prefer a candidate that does not leak an internal field path, and refuse a
    # dataset that states two different distances.
    first_sentence = synthetic_datasets()
    first_sentence["landlord.json"]["action_items"] = [
        {"detail": "Wind is recorded at SFO, 11.9 miles away from 94122."}]
    s5 = rt.build_summary(first_sentence)
    check("a distance sentence that starts its string keeps its first character",
          s5["peak_gusts"]["distance_sentence"].startswith("Wind is recorded at SFO"),
          s5["peak_gusts"]["distance_sentence"])
    both = synthetic_datasets()
    both["landlord.json"]["caveats"] = [
        "Wind is recorded at SFO, 11.9 miles away, see climatology.meta.station_distance_mi."]
    both["landlord.json"]["action_items"] = [
        {"detail": "Wind at SFO ASOS (11.9 mi away; an SFO reference value, not a bound for 94122)."}]
    s6 = rt.build_summary(both)
    check("a distance sentence leaking an internal field path is not preferred",
          "climatology.meta" not in (s6["peak_gusts"]["distance_sentence"] or "")
          and "not a bound for 94122" in (s6["peak_gusts"]["distance_sentence"] or ""),
          s6["peak_gusts"]["distance_sentence"])
    clash = synthetic_datasets()
    clash["landlord.json"]["caveats"] = [
        "Wind is recorded at SFO, 11.9 miles away from 94122.",
        "The station sits 12.4 miles from 94122."]
    try:
        rt.build_summary(clash)
        check("two different distances in the data stop the build", False, "no error raised")
    except rt.RepairTierError as exc:
        check("two different distances in the data stop the build", "more than one" in str(exc), str(exc))

    check("the gale threshold is read from the dataset's counter key",
          s["ocean_wind"]["gale_threshold_kt"] == 34
          and s["ocean_wind"]["gale_counter_key"] == "gale_days_ge_34kt",
          json.dumps({k: s["ocean_wind"][k] for k in ("gale_threshold_kt", "gale_counter_key")}))
    check("the tier publishes the dataset's own definitions rather than its own prose",
          s["definitions"].get("wet_day") == "calendar day with >= 0.01 in of liquid precipitation"
          and s["wind_rain"]["heavy_definition"] == "SFO ASOS max gust >= 35 kt AND precip >= 0.50 in",
          json.dumps(s.get("definitions")))
    line = md_full.splitlines()
    check("the printable page opens with the location, season and stamp",
          line[0].startswith("# Repair & Maintenance Cost Impact")
          and "94122" in line[2] and "2026-09-21" in line[2], line[2][:160])

    # 12. The near-term block: the only official day-by-day forecast.  It must
    #     copy the verified NWS window verbatim (values AND basis strings),
    #     derive its counts under the published rule, and publish an absent
    #     window as absent with a sentence - never as a blank card.
    nt = s["near_term_forecast"]  # the default fixture carries no NWS window
    check("with no NWS product the near-term block is published as absent",
          nt["available"] is False
          and nt["status"] == "not published in this snapshot"
          and "not available" in (nt["unavailable_note"] or "")
          and nt["days"] == [] and nt["counts"] is None
          and nt["summary_sentence"] is None,
          json.dumps(nt)[:200])
    md_absent = rt.render_markdown(s)
    check("with no NWS product the printable page says the block is unpublished",
          "Not published in this snapshot" in md_absent
          and "no near-term day-by-day forecast" in md_absent,
          [l for l in md_absent.splitlines() if "near-term" in l][:2])
    check("with no NWS product the season context is still stated",
          "0 of the 2 season days" in (nt["season_sentence"] or ""),
          nt["season_sentence"][:160])

    snt = rt.build_summary(synthetic_datasets(near_term="days"))
    nt2 = snt["near_term_forecast"]
    cf = synthetic_datasets(near_term="days")["calendar.json"]["current_forecast"]
    check("the near-term block copies the verified window day for day, basis strings included",
          [d["date"] for d in nt2["days"]] == [d["date"] for d in cf["days"]]
          and all(nt2["days"][i][k] == cf["days"][i][k] for i in range(3)
                  for k in ("high_f", "gust_max_mph", "rain_amount_in",
                            "gust_basis", "temp_basis", "hours_covered")),
          json.dumps(nt2["days"][1])[:200])
    c2 = nt2["counts"]
    check("the near-term window counts match the hand-computed rule",
          c2["days_total"] == 3 and c2["hours_covered_total"] == 56
          and c2["window_rain_total_in"] == 0.47
          and c2["days_with_rain"] == 2
          and c2["days_with_strong_wind"] == 2
          and c2["days_with_rain_and_strong_wind"] == 2
          and c2["wettest_day"] == {"date": "2026-09-23", "rain_amount_in": 0.30}
          and c2["peak_gust"] == {"date": "2026-09-22", "gust_max_mph": 32.0},
          json.dumps(c2))
    check("the near-term rule is published with its plain thresholds",
          c2["rain_flag_in"] == 0.1 and c2["gust_flag_mph"] == 30
          and ">= 0.1 in" in nt2["rules_text"]
          and ">= 30 mph" in nt2["rules_text"]
          and "not an NWS product" in nt2["rules_text"],
          nt2["rules_text"][:160])
    check("the near-term window geometry is copied from the verified dataset",
          nt2["first_day"] == cf["first_day"] and nt2["last_day"] == cf["last_day"]
          and nt2["horizon_days"] == 3
          and nt2["forecast_updated"] == cf["forecast_updated"]
          and nt2["source_url"] == cf["sources"][0]["url"]
          and nt2["sources"] == cf["sources"],
          json.dumps({k: nt2[k] for k in ("first_day", "source_url")}))
    want_sentence = rt.compose_near_term_sentence(cf, c2)
    check("the near-term summary sentence recomposes from the verified window",
          nt2["summary_sentence"] == want_sentence
          and "2 of 3 days carry rain >= 0.1 in" in want_sentence
          and "wettest day 2026-09-23 at 0.3 in" in want_sentence
          and "peak 32.0 mph on 2026-09-22" in want_sentence,
          want_sentence[:200])
    md_nt = rt.render_markdown(snt)
    check("the printable page carries the near-term table, sentence and rule",
          all(d["date"] in md_nt for d in cf["days"])
          and want_sentence in md_nt
          and nt2["rules_text"] in md_nt
          and "(partial)" in md_nt,
          f"{md_nt.count('2026-09-2')} window dates on the page")
    tie_days = [
        {"date": "2026-10-01", "hours_covered": 24, "rain_amount_in": 0.2,
         "gust_max_mph": 31.0},
        {"date": "2026-10-02", "hours_covered": 24, "rain_amount_in": 0.2,
         "gust_max_mph": 31.0},
    ]
    ctie = rt.near_term_counts(tie_days)
    check("a tie reports the earlier day, so the rule is deterministic",
          ctie["wettest_day"] == {"date": "2026-10-01", "rain_amount_in": 0.2}
          and ctie["peak_gust"] == {"date": "2026-10-01", "gust_max_mph": 31.0},
          json.dumps(ctie))
    sntd = rt.build_summary(synthetic_datasets(near_term="dry"))
    cnd = sntd["near_term_forecast"]["counts"]
    snd = sntd["near_term_forecast"]["summary_sentence"]
    check("a dry window says no rain days, no wettest day, plainly",
          cnd["days_with_rain"] == 0 and cnd["wettest_day"] is None
          and cnd["window_rain_total_in"] == 0.0
          and "No day in this window carries rain >= 0.1 in" in snd
          and "No day has rain and strong wind on the same day." in snd,
          snd[:200])
    nte = rt.build_summary(synthetic_datasets(near_term="empty"))
    check("a window with no daily periods is published as absent, not blank",
          nte["near_term_forecast"]["available"] is False
          and "returned no daily periods" in nte["near_term_forecast"]["unavailable_note"],
          json.dumps(nte["near_term_forecast"])[:200])

    # ---- report
    failed = [c for c in CHECKS if not c[1]]
    for name, ok, detail in CHECKS:
        if not ok:
            print(f"  FAIL {name}")
            if detail:
                print(f"       {detail}")
    print(f"repair tier self-test: {len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
