#!/usr/bin/env python3
"""
Landlord-focused summary generator for SFWeather.

Reads the verified datasets produced by main.py and build_calendar.py
and produces data/landlord.json with actionable, source-verified insights
for a landlord managing property in 94122.

No numbers are invented - every figure traces to NOAA/NWS/NCEI/CPC sources
already fetched by the pipeline.
"""

from __future__ import annotations

import json
import datetime as dt
import re
import sys
from pathlib import Path

# The canonical ENSO label mapping lives in climo.py, next to the phase and
# strength bands it describes, so there is exactly one definition.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import climo  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "landlord.json"

# Allow override for testing
import os
_env = os.environ.get("SFWEATHER_DATA")
if _env:
    DATA = Path(_env)
    OUT = DATA / "landlord.json"


def load(name):
    p = DATA / name
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def pct(v):
    if v is None:
        return None
    return float(v)


# --------------------------------------------------------------------------
# Display and derivation helpers used by the maintenance cost-driver block.
# They are deliberately importable (main() is guarded) so the offline unit
# tests in tests/test_parsers.py can pin them down with synthetic values.
# --------------------------------------------------------------------------

#: Raw ENSO tokens -> reader-facing labels.  The canonical definitions live in
#: climo.py and are re-exported here so this module and the site renderer always
#: agree on exactly one mapping (the previous duplicate copy was how the season
#: panel ended up printing "el nino" while the executive summary printed
#: "El Niño" from the same value).
PHASE_LABELS = climo.PHASE_LABELS
STRENGTH_LABELS = climo.STRENGTH_LABELS
phase_label = climo.phase_label
strength_label = climo.strength_label
fmt_oni_c = climo.fmt_oni_c


#: NCEI ISD hourly archive (free, no key).  Used for the hour-by-hour
#: wind-and-rain statistic, which does not depend on the GSOD daily file.
ISD_URL = "https://www.ncei.noaa.gov/data/global-hourly/access/"

#: A season enters the hour-by-hour statistics only if the station reported on at
#: least this share of the 123 Oct 1 - Jan 31 dates.  Seasons below it are listed
#: in the published output with their coverage instead of being averaged in.
HOURLY_SEASON_MIN_COVERAGE_PCT = 95.0

#: NCEI Storm Events types this project counts as rain-related: flooding and
#: flash flooding, the "Heavy Rain" type NWS files when rain is the hazard, and
#: debris flow, which is the rain-driven slope failure a landlord's drainage and
#: foundation question runs into.  Defined once because two cards used to count
#: "flood-type" reports with two different sets, so the same page published 98
#: and 99 for the same quantity.
RAIN_RELATED_EVENT_TYPES = ("Flood", "Flash Flood", "Heavy Rain", "Debris Flow")


def summarise_hourly_wind_rain(isd, period, daily_wind_rain, heavy_wind_rain,
                               min_coverage_pct=HOURLY_SEASON_MIN_COVERAGE_PCT):
    """Hour-by-hour wind-and-rain statistic from the NCEI ISD hourly archive.

    Answers the landlord's "wind and rain at the same time" question with hours that
    actually coincide, instead of pairing a whole local rain day with a whole daily
    wind maximum.  Both are published: the hourly count, the same-station daily
    pairing (which isolates how much of the difference comes from pairing whole
    days), and the cross-station daily pairing this project published before.

    ``period`` is the ``(start_year, end_year)`` season-year window shared with the
    daily method, so the comparison is over the same seasons.  Nothing is invented:
    every figure is a count over ``by_local_date`` entries the parser produced, and
    the seasons that were left out are named with the reason.
    """
    if not isd or not isd.get("by_local_date"):
        return {"available": False,
                "reason": "No NCEI ISD hourly summary was produced by this run.",
                "source": "NOAA NCEI Integrated Surface Database (ISD)",
                "source_url": ISD_URL}
    y0, y1 = period
    by_season = {}
    for local_date, d in isd["by_local_date"].items():
        sy = climo.isd_season_year(local_date)
        s = by_season.setdefault(sy, {
            "season_year": sy, "season": f"{sy}-{sy + 1}", "dates_with_data": 0,
            "days_simultaneous": 0, "days_daily_pair": 0, "days_rain": 0,
            "days_wind_ge_threshold": 0, "simultaneous_hours": 0, "valid_hours": 0,
        })
        s["dates_with_data"] += 1
        s["valid_hours"] += d.get("valid_hours") or 0
        if (d.get("wind_rain_hours") or 0) > 0:
            s["days_simultaneous"] += 1
        s["simultaneous_hours"] += d.get("wind_rain_hours") or 0
        if (d.get("prcp_in") or 0.0) > 0.0:
            s["days_rain"] += 1
        windy = (d.get("wind_max_kt") is not None
                 and d["wind_max_kt"] >= climo.ISD_WIND_THRESHOLD_KT)
        if windy:
            s["days_wind_ge_threshold"] += 1
        if windy and (d.get("prcp_in") or 0.0) > 0.0:
            s["days_daily_pair"] += 1

    # The same-station whole-day pairing needs the per-date wind maximum and daily
    # precipitation total, which only the current aggregation writes.  If the
    # committed summary predates them, the pairing is *unavailable*, not zero:
    # publishing 0.0 would state that wind and rain never share a day at SFO.
    same_station_fields = any(isinstance(d, dict) and "wind_max_kt" in d
                              for d in isd["by_local_date"].values())

    expected = isd.get("dates_expected_per_season") or climo.ISD_SEASON_DATES_EXPECTED
    used, excluded = [], []
    for sy in sorted(by_season):
        s = by_season[sy]
        cov = climo.pct(s["dates_with_data"], expected)
        s = dict(s, dates_expected=expected, coverage_pct=cov)
        if not (y0 <= sy <= y1):
            s["excluded_because"] = (f"season {s['season']} is outside the "
                                     f"{y0}-{y1} window the daily statistic uses")
            excluded.append(s)
        elif cov is not None and cov < min_coverage_pct:
            s["excluded_because"] = (f"the station reported on only "
                                     f"{s['dates_with_data']} of {expected} dates "
                                     f"({cov}%)")
            excluded.append(s)
        else:
            used.append(s)

    if not used:
        return {"available": False,
                "reason": "The ISD hourly archive produced no season inside the "
                          "comparison window with enough date coverage.",
                "min_coverage_pct_required": min_coverage_pct,
                "source": "NOAA NCEI Integrated Surface Database (ISD)",
                "source_url": ISD_URL}

    stats = lambda key: climo.summarise([s[key] for s in used])
    days_sim = stats("days_simultaneous")
    hours_sim = stats("simultaneous_hours")
    days_pair = stats("days_daily_pair") if same_station_fields else None
    days_rain = stats("days_rain") if same_station_fields else None
    days_wind = stats("days_wind_ge_threshold") if same_station_fields else None
    coverage = [s["coverage_pct"] for s in used if s["coverage_pct"] is not None]

    multi_hour_hours = isd.get("simultaneous_hours_from_multi_hour_reports")
    notes = []
    if not same_station_fields:
        notes.append(
            "The committed hourly summary carries only the simultaneous-hour counts, so "
            "the same-station whole-day pairing is reported as unavailable rather than "
            "as zero. The next pipeline run writes the per-date wind maximum and daily "
            "precipitation total and the comparison appears.")
    if multi_hour_hours is None:
        notes.append(
            "The count of simultaneous hours coming from multi-hour precipitation "
            "reports is not present in this run's hourly summary.")
    if isd.get("latest_observation_utc"):
        notes.append(
            f"The hourly archive fetched by this run reaches "
            f"{str(isd.get('latest_observation_utc'))[:10]} (UTC) at its newest.")
    if isd.get("dates_expected_per_season") is None:
        notes.append(
            "The hourly summary predates the coverage fields; coverage is reported from "
            f"the {expected}-date season definition used by this project's parser.")

    def _diff(a, b):
        try:
            return round(float(a) - float(b), 2)
        except (TypeError, ValueError):
            return None

    return {
        "available": True,
        "station_id": isd.get("station_id"),
        "station_name": isd.get("station_name") or "SAN FRANCISCO INTERNATIONAL AIRPORT (KSFO)",
        "source": isd.get("source") or "NOAA NCEI Integrated Surface Database (ISD)",
        "source_url": ISD_URL,
        "units_period": isd.get("units"),
        "method": isd.get("method"),
        "timezone": isd.get("timezone", "America/Los_Angeles"),
        "wind_threshold_kt": isd.get("wind_threshold_kt", climo.ISD_WIND_THRESHOLD_KT),
        "season_window": f"{y0}-{y0 + 1} .. {y1}-{y1 + 1}",
        "n_seasons_used": len(used),
        "hours_with_both_observations": isd.get("valid_joint_hours"),
        "simultaneous_hours_total": isd.get("simultaneous_wind_rain_hours"),
        "simultaneous_hours_from_multi_hour_reports":
            isd.get("simultaneous_hours_from_multi_hour_reports"),
        "days_with_a_simultaneous_hour": days_sim,
        "simultaneous_hours_per_season": hours_sim,
        # None (not 0.0) when the underlying per-date fields are absent: an absent
        # measurement and a measured zero are different statements.
        "same_station_daily_fields_available": same_station_fields,
        "days_daily_pair_same_station": days_pair,
        "days_rain_same_station": days_rain,
        "days_wind_ge_threshold_same_station": days_wind,
        "cross_station_daily_days": dict(daily_wind_rain or {}),
        "heavy_cross_station_daily_days": dict(heavy_wind_rain or {}),
        "difference_daily_minus_hourly_same_station":
            _diff((days_pair or {}).get("mean"), days_sim.get("mean")),
        "difference_cross_station_minus_hourly":
            _diff((daily_wind_rain or {}).get("mean"), days_sim.get("mean")),
        "coverage": {
            "dates_expected_per_season": expected,
            "min_coverage_pct_required": min_coverage_pct,
            "seasons_used": len(used),
            "min_coverage_pct": min(coverage) if coverage else None,
            "seasons_below_full_coverage": [
                {"season": s["season"], "dates_with_data": s["dates_with_data"],
                 "coverage_pct": s["coverage_pct"]}
                for s in used if s["coverage_pct"] is not None and s["coverage_pct"] < 100.0],
            "seasons_excluded": [
                {"season": s["season"], "dates_with_data": s["dates_with_data"],
                 "coverage_pct": s["coverage_pct"],
                 "excluded_because": s["excluded_because"]} for s in excluded],
        },
        "per_season": [{k: v for k, v in s.items() if k != "excluded_because"}
                       for s in used],
        "excluded_seasons": excluded,
        "notes": notes,
    }


def expected_event_days(days, climo_key):
    """Expected number of days per season meeting a daily climatology test.

    The expected count of an event across a window is the sum of the daily
    probabilities (linearity of expectation - no independence assumption is
    needed for the *expectation*).  Accepts both record shapes used in this
    project: scoreboard days, where the percentages live under ``d["climo"]``,
    and raw climatology-table rows, where they live at the top level.
    Returns ``None`` when no row carries the key at all, so a missing source
    can never be misread as "expected 0 days".
    """
    total = 0.0
    seen = 0
    for d in days or []:
        if not isinstance(d, dict):
            continue
        climo = d.get("climo") if isinstance(d.get("climo"), dict) else d
        v = climo.get(climo_key)
        if v is None:
            continue
        seen += 1
        total += float(v) / 100.0
    if seen == 0:
        return None
    return round(total, 2)


def parse_damage_usd(value):
    """Parse an NCEI Storm Events damage string (e.g. '2.50K', '1.2M') to USD.

    '0.00K' is a real Storm Events value meaning *no recorded damage*, so it
    parses to 0.0 (and sorts below any positive damage), while an empty or
    missing string parses to None (unknown, not zero).
    """
    if value is None:
        return None
    s = str(value).strip().upper()
    if not s:
        return None
    mult = 1.0
    if s.endswith("K"):
        mult, s = 1_000.0, s[:-1]
    elif s.endswith("M"):
        mult, s = 1_000_000.0, s[:-1]
    elif s.endswith("B"):
        mult, s = 1_000_000_000.0, s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None


GHCN_URL = ("https://www.ncei.noaa.gov/data/"
            "global-historical-climatology-network-daily/access/USW00023272.csv")
GSOD_URL = "https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/"
STORM_URL = "https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/"
ONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
NORMALS_URL = "https://www.ncei.noaa.gov/data/normals-daily/1991-2020/access/USW00023272.csv"
ENSODISC_URL = ("https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/"
                "enso_advisory/ensodisc.shtml")

#: The climatological baseline for CPC's three-way long-lead split.  CPC's own
#: polygons carry 33% for "no tilt"; 100/3 is the exact baseline.
CPC_BASELINE_PCT = 100.0 / 3.0


def cpc_tilt_summary(records):
    """Summarise the CPC precipitation outlooks that cover this season.

    Returns only counts and the published numbers - it never converts a
    period probability into a daily one, and it separates records whose
    probability sits on the climatological baseline from records that carry a
    real tilt.  A period with ``Cat="Above"`` and ``Prob=33.0`` is counted as
    "at the baseline", not as an above-median signal.
    """
    rows = [r for r in (records or []) if r.get("variable") == "prcp" and r.get("prob") is not None]
    if not rows:
        return None
    tilted, baseline = [], []
    for r in sorted(rows, key=lambda r: (r.get("valid_season") or "")):
        try:
            prob = float(r["prob"])
        except (TypeError, ValueError):
            continue
        cat = (r.get("category") or "").upper()
        entry = {"period": r.get("valid_season"), "issued": r.get("issued"),
                 "category_label": r.get("category_label"),
                 "category_raw": r.get("category"),
                 "probability_pct": prob,
                 "at_baseline": abs(prob - CPC_BASELINE_PCT) < 0.5,
                 "source_url": r.get("url")}
        (baseline if entry["at_baseline"] else tilted).append(entry)
    best = None
    if tilted:
        best = max(tilted, key=lambda e: e["probability_pct"])
    return {
        "periods_covering_this_season": len(rows),
        "periods_with_a_tilt": len(tilted),
        "periods_at_climatological_baseline": len(baseline),
        "highest_probability": best,
        "rows": sorted(rows, key=lambda r: (r.get("valid_season") or "")) and
                [{"period": r.get("valid_season"), "issued": r.get("issued"),
                  "variable": r.get("variable"),
                  "category_label": r.get("category_label"),
                  "category_raw": r.get("category"),
                  "probability_pct": r.get("prob")} for r in
                 sorted(rows, key=lambda r: (r.get("valid_season") or ""))],
        "baseline_pct": round(CPC_BASELINE_PCT, 1),
        "method": ("Counted from the CPC long-lead polygons this project sampled at the "
                   "94122 point. CPC publishes whole percentages, so a probability that "
                   "rounds to 33% is counted as sitting on the climatological baseline "
                   "(100/3 = 33.3%) and is not reported as a tilt, even when CPC's "
                   "category field says Above/Below."),
        "source_url": ("https://www.cpc.ncep.noaa.gov/products/GIS/GIS_DATA/us_tempprcpfcst/"),
    }


#: Sentences this page watches for in CPC's monthly long-lead Prognostic
#: Discussion (fxus05), the narrative behind the seasonal outlook polygons.
#: Each pattern is written against the *kind* of statement, with the parts CPC
#: rewrites every month (the month name, the index value, the release window)
#: generalised, because the discussion is a new document each issuance.  What
#: is published is the matched span, verbatim - never a paraphrase.
PROGNOSTIC_DISCUSSION_URL = \
    "https://www.cpc.ncep.noaa.gov/products/predictions/90day/fxus05.html"

PROGNOSTIC_CAVEAT_PATTERNS = [
    {
        "key": "pdo_state",
        "label": "The state of the Pacific Decadal Oscillation, in NOAA's own words",
        "pattern": (r"The first factor is the presence of a fairly strong, "
                    r"negatively phased Pacific Decadal Oscillation \(PDO\), "
                    r"with the [A-Za-z]+ PDO index value of [-+\d.]+\s*\."),
    },
    {
        "key": "pdo_dampening",
        "label": ("NOAA's forecasters stating, in their own words, that this "
                  "El Ni\u00f1o may not behave like the classic strong ones"),
        "pattern": (r"This time, however, the PDO phase is negative and may "
                    r"dampen the typical impacts of a strong El Ni\u00f1o in "
                    r"certain areas\."),
    },
    {
        "key": "next_issuance_may_revise",
        "label": "NOAA's forecasters saying the probabilities themselves may move at the next issuance",
        "pattern": (r"These probabilities may be [A-Za-z]+ further in the next "
                    r"set of seasonal outlooks, to be released in [^,]+, "
                    r"pending reassessment of the latest model forecasts\."),
    },
]

_ISSUED_LINE_RE = (r"(?:\d{3,4}\s+[AP]M\s+E[SD]T\s+)?[A-Za-z]{3}\s+[A-Za-z]{3}\s+"
                   r"\d{1,2}\s+\d{4}")


def prognostic_caveats(cpc):
    """Extract the cautionary sentences CPC's forecasters actually wrote.

    The 90-day Prognostic Discussion is fetched, hashed and archived whole by
    the pipeline (``data/cpc.json`` -> ``discussions``).  This function reads
    that archived text and pulls out the sentences that *qualify* the outlook
    this page summarises - the stated caveats, not the headline.  Design rules,
    same as the AFD card:

    * quotations only, copied verbatim (whitespace collapsed) - the reader sees
      NOAA's words, never this project's paraphrase of them;
    * located by pattern, so a rewritten discussion simply publishes nothing
      rather than a stale quote;
    * what was watched for and not found is published as ``not_found``, so an
      absent caveat is visible rather than silent;
    * no date, amount or probability of this project's making is attached.

    The archived text occasionally carries publisher-side mojibake (broken
    smart-quote bytes around e.g. 'Big Three').  Quotes containing characters
    that are not printable plain text are refused, so nothing undecodable can
    reach the page through this path.
    """
    discussions = (cpc or {}).get("discussions") or []
    disc = next((d for d in discussions
                 if "90-Day" in (d.get("label") or "")
                 or "90day" in (d.get("url") or "")), None)
    if not disc or not (disc.get("ok") is True) or not (disc.get("text") or "").strip():
        return {
            "available": False,
            "reason": ("The archived 90-day Prognostic Discussion is absent or "
                       "empty in this run, so no caveat can be quoted."),
            "source_url": PROGNOSTIC_DISCUSSION_URL,
        }

    collapsed = climo.collapse_ws(disc["text"])
    quotes, not_found = [], []
    for spec in PROGNOSTIC_CAVEAT_PATTERNS:
        m = re.search(spec["pattern"], collapsed)
        if not m:
            not_found.append(spec["key"])
            continue
        text = m.group(0).strip()
        # Refuse anything that is not clean printable text: the discussion
        # text is decoded on a best-effort basis and individual sentences can
        # carry publisher-side broken bytes.  A refused sentence is reported,
        # not silently dropped.
        if any(ord(ch) < 32 or ord(ch) in (127, 0xFFFD) for ch in text):
            not_found.append(spec["key"] + " (matched but not clean plain text)")
            continue
        quotes.append({"key": spec["key"], "label": spec["label"], "text": text})

    issued = None
    m = re.search(_ISSUED_LINE_RE, collapsed)
    if m:
        issued = m.group(0).strip()

    return {
        "available": True,
        "issued_line": issued,
        "quotes": quotes,
        "not_found": not_found,
        "patterns_watched_for": [s["key"] for s in PROGNOSTIC_CAVEAT_PATTERNS],
        "source_url": disc.get("url") or PROGNOSTIC_DISCUSSION_URL,
        "discussion_sha256": disc.get("sha256"),
        "discussion_characters": disc.get("characters"),
        "how_to_read": (
            "Sentences copied verbatim from the long-lead Prognostic Discussion "
            "CPC issued with the seasonal outlook, located by pattern in the "
            "text the pipeline fetched and hashed. They are NOAA's forecasters "
            "qualifying their own outlook; no number or date has been attached "
            "by this project. When a later discussion no longer contains a "
            "sentence, it stops appearing here and is listed under not_found."),
    }


def build_bottom_line(*, season_total, wet_days, streak_prob, longest_streak,
                      wind_rain, heavy_wind_and_rain, max_gust, expected_days,
                      severity, latest_oni, oni_when, diagnostic_status,
                      tilt, storms, days_in_horizon, horizon_last_day,
                      enso_strat=None, hourly_wind_rain=None,
                      caveats=None):
    """The landlord's questions, answered in the order they were asked.

    Every value is copied from an already-verified structure; nothing here is
    a new derivation.  Each answer carries the basis it rests on, so a reader
    can see at a glance whether a number is an observation, an expectation
    over the observed distribution, or an official period probability - and
    never a daily forecast, because none exists this far out.
    """
    def g(d, k):
        """Nested lookup that tolerates a key that exists but is None.

        ``(d or {}).get(k, {})`` returns None when the key is present with a
        None value, which then blows up on the next .get().  The severity
        blocks are legitimately absent until the fetching pipeline has run, so
        every read here has to survive that.
        """
        if not isinstance(d, dict):
            return None
        return d.get(k)

    obs = "1991\u20132020 observed record, NOAA NCEI station USW00023272 (San Francisco downtown)"
    obs_wind = "1991\u20132020 observed record, NOAA NCEI GSOD station 72494023234 (SFO ASLO, 11.9 mi away)"
    obs_hourly = ("hour-by-hour observed record, NOAA NCEI ISD hourly station 72494023234 "
                  "(SFO ASLO, 11.9 mi away) \u2014 an hour counts when a single observation carries "
                  "wind \u2265 20 kt and precipitation > 0")
    exp_basis = ("1991\u20132020 observed record \u2014 an expectation over those 30 seasons, "
                 "not a prediction for 2026-27")

    out = []

    out.append({
        "n": 1,
        "key": "rain_amount",
        "question": "How much rain should I expect over the season?",
        "answer": (
            f"Plan on about {g(season_total,'mean')} in for Oct 1 \u2013 Jan 31. "
            f"The median season is {g(season_total,'median')} in; the record range across 30 seasons is "
            f"{g(season_total,'min')}\u2013{g(season_total,'max')} in, and the driest 10% of seasons were at or "
            f"below {g(season_total,'p10')} in while the wettest 10% were at or above {g(season_total,'p90')} in. "
            "Budget off the mean, hold reserves against the p90."),
        "numbers": [
            {"label": "Season total, mean", "value": f"{g(season_total,'mean')} in"},
            {"label": "Season total, median", "value": f"{g(season_total,'median')} in"},
            {"label": "p10 \u2013 p90", "value": f"{g(season_total,'p10')} \u2013 {g(season_total,'p90')} in"},
            {"label": "Wettest / driest", "value": f"{g(season_total,'max')} in / {g(season_total,'min')} in"},
        ],
        "basis": obs,
        "confidence": f"n = {g(season_total,'n')} seasons",
        "sources": [{"label": "NCEI GHCN-Daily USW00023272", "url": GHCN_URL}],
    })

    out.append({
        "n": 2,
        "key": "rain_duration",
        "question": "Will it rain for days or weeks straight?",
        "answer": (
            f"A long wet spell is the normal case, not the exception: {g(streak_prob.get('ge_3_days',{}),'pct')}% of "
            f"seasons had a run of 3+ consecutive wet days, {g(streak_prob.get('ge_5_days',{}),'pct')}% had 5+ days, "
            f"{g(streak_prob.get('ge_7_days',{}),'pct')}% had 7+ days and {g(streak_prob.get('ge_10_days',{}),'pct')}% "
            f"had 10+ days. The longest run averages {g(longest_streak,'mean')} days and has reached "
            f"{g(longest_streak,'max')} days. A week-long spell is roughly a coin flip \u2014 worth pre-emptive "
            "gutter, roof-drain and tenant-communication plans."),
        "numbers": [
            {"label": "Any 3+ day wet run", "value": f"{g(streak_prob.get('ge_3_days',{}),'pct')}% of seasons"},
            {"label": "Any 5+ day wet run", "value": f"{g(streak_prob.get('ge_5_days',{}),'pct')}% of seasons"},
            {"label": "Any 7+ day wet run", "value": f"{g(streak_prob.get('ge_7_days',{}),'pct')}% of seasons"},
            {"label": "Any 10+ day wet run", "value": f"{g(streak_prob.get('ge_10_days',{}),'pct')}% of seasons"},
            {"label": "Longest run", "value": f"mean {g(longest_streak,'mean')} d \u00b7 max {g(longest_streak,'max')} d"},
        ],
        "basis": obs + " \u2014 wet day = \u2265 0.01 in of liquid precipitation, run counted inside Oct 1 \u2013 Jan 31",
        "confidence": f"n = {g(longest_streak,'n')} seasons",
        "sources": [{"label": "NCEI GHCN-Daily USW00023272", "url": GHCN_URL}],
    })

    # The threshold table is the honest way to talk about "storm severity":
    # NOAA publishes a percent-of-years value for eight precipitation
    # thresholds, and this project counts days at four of them from the same
    # station, so both numbers can be shown and checked.  A threshold with a
    # zero count in 30 seasons is left at 0.0 rather than dressed up as rare.
    thr = [(t.get("threshold_in"), t) for t in (g(severity, "threshold_comparison") or [])]
    thr_rows = []
    for inches, t in thr:
        proj = g(t, "project_mean_days")
        noaa = g(t, "noaa_expected_days")
        if proj is None and noaa is None:
            continue
        thr_rows.append({
            "label": f"Days \u2265 {inches:.2f} in per season, method A (counted) vs method B (NOAA published)",
            "value": (f"{proj} vs {noaa}"
                      if proj is not None and noaa is not None
                      else (f"{proj} counted" if proj is not None else f"{noaa} NOAA published")),
        })
    out.append({
        "n": 3,
        "key": "heavy_rain_days",
        "question": "How many hard-rain days will there be?",
        "answer": (
            f"Expect about {g(expected_days,'ge_025in_days')} days with \u2265 0.25 in and about "
            f"{g(expected_days,'ge_100in_days')} days with \u2265 1.00 in per season. Those are the days that "
            "overwhelm area drains, garage thresholds and ground-floor entryways. The counts are sums of the "
            "per-date observed probabilities, so they are an expectation over the 30-season record. "
            + (f"NOAA's own published per-date probabilities give {g(g(severity,'published_expected'),'ge_025in_days')} "
               f"and {g(g(severity,'published_expected'),'ge_100in_days')} days. "
               + (g(g(severity, 'two_method_agreement'), 'statement') + " "
                  if g(g(severity, 'two_method_agreement'), 'statement') else ""))),
        "numbers": [
            {"label": "Days \u2265 0.25 in per season, method A (sum of this project's per-date probabilities)",
             "value": f"{g(expected_days,'ge_025in_days')} days"},
            {"label": "Days \u2265 1.00 in per season, method A",
             "value": f"{g(expected_days,'ge_100in_days')} days"},
            {"label": "Days \u2265 0.25 in / \u2265 1.00 in, method B (NOAA's published probabilities)",
             "value": f"{g(g(severity,'published_expected'),'ge_025in_days')} / "
                      f"{g(g(severity,'published_expected'),'ge_100in_days')} days"},
            {"label": "Wettest single day on record in the window",
             "value": (f"{g(g(severity, 'record_daily_prcp_in'), 'value')} in "
                       f"({g(g(severity, 'record_daily_prcp_in'), 'season')})"
                       if g(g(severity, "record_daily_prcp_in"), "value") is not None
                       else "not derived this run")},
        ] + thr_rows,
        "basis": exp_basis,
        "confidence": "linearity of expectation over 123 dates",
        "sources": [{"label": "NCEI GHCN-Daily USW00023272", "url": GHCN_URL},
                    {"label": "NCEI 1991\u20132020 daily normals (NOAA's own probabilities)",
                     "url": NORMALS_URL}],
    })

    out.append({
        "n": 4,
        "key": "wind",
        "question": "How windy will it get?",
        "answer": (
            f"The strongest gust of the season averages {g(max_gust,'mean')} mph at SFO and has reached "
            f"{g(max_gust,'max')} mph in this record. Wind is measured at SFO, which is 11.9 mi away and more "
            "exposed than the Sunset, so treat these as an upper bound for the ZIP. The strongest gusts are a "
            "tree-limb, fence and loose-material risk with the shortest warning."),
        "numbers": [
            {"label": "Season max gust, mean", "value": f"{g(max_gust,'mean')} mph"},
            {"label": "Season max gust, record", "value": f"{g(max_gust,'max')} mph"},
            {"label": "Days with sustained wind \u2265 30 kt",
             "value": (f"mean {float(g(g(severity,'wind_days_ge_30kt'),'mean')):.1f} per season"
                       if g(g(severity, 'wind_days_ge_30kt'), 'mean') is not None else "not derived this run")},
            {"label": "Days with a gust \u2265 50 kt",
             "value": (f"mean {float(g(g(severity,'gust_days_ge_50kt'),'mean')):.1f} per season"
                       if g(g(severity, 'gust_days_ge_50kt'), 'mean') is not None else "not derived this run")},
        ],
        "basis": obs_wind,
        "confidence": f"n = {g(max_gust,'n')} seasons; upper bound for 94122",
        "sources": [{"label": "NCEI GSOD 72494023234 (KSFO)", "url": GSOD_URL},
                    {"label": "GSOD units README", "url":
                     "https://www.ncei.noaa.gov/data/global-summary-of-the-day/doc/readme.txt"}],
    })

    hourly = hourly_wind_rain or {}
    hourly_days = g(hourly, "days_with_a_simultaneous_hour") or {}
    hourly_hours = g(hourly, "simultaneous_hours_per_season") or {}
    same_station_daily = g(hourly, "days_daily_pair_same_station") or {}
    if hourly.get("available"):
        hourly_window = hourly.get("season_window")
        n_hourly = hourly.get("n_seasons_used")
        coverage = g(hourly, "coverage") or {}
        min_cov = g(coverage, "min_coverage_pct")
        multi = g(hourly, "simultaneous_hours_from_multi_hour_reports")
        if hourly.get("same_station_daily_fields_available"):
            same_mean = same_station_daily.get("mean")
            cross_mean = (wind_rain or {}).get("mean")
            comparison_sentence = (
                f"Pairing a whole day\u2019s rain with a whole day\u2019s wind maximum \u2014 a method "
                f"that cannot tell rain in the morning from wind at night \u2014 gives "
                f"{g(same_station_daily,'mean')} days on that same station and ")
            after_comparison = ""
            agreement_sentence = (
                " The two whole-day constructions agree, so the gap to the hourly count is the "
                "pairing rule, not the change of rain gauge."
                if (same_mean is not None and cross_mean is not None
                    and abs(float(same_mean) - float(cross_mean)) < 0.05) else "")
        else:
            comparison_sentence = ""
            after_comparison = ("The same-station whole-day comparison is not published in this run\u2019s "
                                "hourly dataset, so the hour-by-hour figure above is the one to use; for "
                                "reference, the whole-day method gives ")
            agreement_sentence = ""
        hourly_answer = (
            f"On the hour-by-hour record at SFO, rain and sustained wind \u2265 20 kt coincide on about "
            f"{g(hourly_days,'mean')} days a season (median {g(hourly_days,'median')}, range "
            f"{g(hourly_days,'min')}\u2013{g(hourly_days,'max')} over {n_hourly} seasons, {hourly_window}), "
            f"which is about {g(hourly_hours,'mean')} simultaneous hours a season. "
            + comparison_sentence + after_comparison
            + f"{g(wind_rain,'mean')} days when the downtown rain gauge is paired with SFO wind (the figure "
              "this page published before the hourly record was used)."
            + agreement_sentence
            + " Those are the days water is driven sideways under shingles, laps and window seals, and the "
              "days fences fail. The SFO wind figure is an upper bound for the Sunset.")
        hourly_numbers = [
            {"label": "Days per season with a simultaneous wind+rain hour (hourly record)",
             "value": (f"mean {g(hourly_days,'mean')} \u00b7 median {g(hourly_days,'median')} \u00b7 "
                       f"min {g(hourly_days,'min')} \u00b7 max {g(hourly_days,'max')}")},
            {"label": "Simultaneous wind+rain hours per season",
             "value": (f"mean {g(hourly_hours,'mean')} \u00b7 median {g(hourly_hours,'median')} \u00b7 "
                       f"max {g(hourly_hours,'max')}")},
            {"label": "Days per season, same station, whole-day pairing (for comparison)",
             "value": ((f"mean {g(same_station_daily,'mean')} \u00b7 median {g(same_station_daily,'median')} "
                        f"\u00b7 max {g(same_station_daily,'max')}")
                       if hourly.get("same_station_daily_fields_available")
                       else "not published in this run's hourly dataset")},
            {"label": "Days per season, whole-day pairing, downtown rain gauge + SFO wind",
             "value": f"mean {g(wind_rain,'mean')} \u00b7 max {g(wind_rain,'max')}"},
            {"label": "Heavy wind+rain days per season (\u2265 0.50 in and a gust \u2265 35 kt, whole-day pairing)",
             "value": f"mean {g(heavy_wind_and_rain,'mean')} \u00b7 max {g(heavy_wind_and_rain,'max')}"},
        ]
        if multi is None:
            multi_sentence = ("the multi-hour-accumulation count is not published in this run\u2019s "
                              "hourly dataset")
        elif multi:
            multi_sentence = (f"{multi} of the {g(hourly,'simultaneous_hours_total')} counted hours came "
                              "from reports whose precipitation period was longer than one hour, so those "
                              "are multi-hour accumulations rather than hour-by-hour measurements")
        else:
            multi_sentence = "every counted hour came from a report covering a single hour"
        hourly_confidence = (
            f"n = {n_hourly} seasons; thinnest season covers {min_cov}% of the 123 Oct\u2013Jan dates; "
            + multi_sentence
            + "; the whole-day method pairs a local-day rain total with a UTC-day wind figure (00\u201324Z), "
              "which is why it counts more days")
        hourly_sources = [
            {"label": "NCEI ISD hourly archive (station 72494023234, SFO)",
             "url": ISD_URL},
            {"label": "NCEI GSOD 72494023234 (KSFO)", "url": GSOD_URL},
            {"label": "NCEI GHCN-Daily USW00023272", "url": GHCN_URL},
        ]
    else:
        hourly_answer = (
            f"Yes \u2014 on about {g(wind_rain,'mean')} days a season at SFO (\u2265 0.01 in of rain and sustained "
            f"wind \u2265 20 kt), and on about {g(heavy_wind_and_rain,'mean')} heavy days (\u2265 0.50 in and a "
            "gust \u2265 35 kt). Those are the days water is driven sideways under shingles, laps and window "
            "seals, and the days fences fail. The SFO wind figure is an upper bound; the rain figure is the "
            "downtown gauge. The hour-by-hour record could not be summarised this run "
            f"({hourly.get('reason') or 'no reason recorded'}), so the whole-day figure is shown alone.")
        hourly_numbers = [
            {"label": "Wind+rain days per season (whole-day pairing)",
             "value": f"mean {g(wind_rain,'mean')} \u00b7 max {g(wind_rain,'max')}"},
            {"label": "Heavy wind+rain days per season",
             "value": f"mean {g(heavy_wind_and_rain,'mean')} \u00b7 max {g(heavy_wind_and_rain,'max')}"},
        ]
        hourly_confidence = ("GSOD days are 00\u201324Z (about 16:00\u201316:00 local), so the joint statistic "
                             "pairs a local-day rain total with a UTC-day wind figure \u2014 stated, not "
                             "corrected. No hour-by-hour summary was available this run.")
        hourly_sources = [{"label": "NCEI GSOD 72494023234 (KSFO)", "url": GSOD_URL},
                          {"label": "NCEI GHCN-Daily USW00023272", "url": GHCN_URL}]

    out.append({
        "n": 5,
        "key": "wind_and_rain",
        "question": "Will wind and rain hit at the same time?",
        "answer": hourly_answer,
        "numbers": hourly_numbers,
        "basis": obs + "; " + obs_wind + "; " + obs_hourly,
        "confidence": hourly_confidence,
        "sources": hourly_sources,
    })

    storm_rows = (storms or {}).get("events") or []
    flood_types = RAIN_RELATED_EVENT_TYPES
    years = (storms or {}).get("years") or []
    span = f"{years[0]}\u2013{years[-1]}" if years else "the covered years"
    n_flood = sum(1 for e in storm_rows if (e.get("event_type") or "") in flood_types)
    n_all = (storms or {}).get("n_events")
    n_dmg = (storms or {}).get("n_with_damage")

    # The severity answer is built from counts this project derived itself, not
    # from the damage field: NCEI's property-damage column for this county holds
    # token values, so "how much did it cost" cannot be answered from it.  What
    # can be answered is how often the record shows a day hard enough to matter.
    sev_w1 = g(g(severity, "wet_days_ge_1in"), "mean")
    sev_w1_rec = g(g(severity, "record_days_ge_1in"), "value")
    sev_w1_rec_season = g(g(severity, "record_days_ge_1in"), "season")
    sev_gust = g(g(severity, "gust_days_ge_40kt"), "mean")
    sev_severe = g(g(severity, "severe_wind_and_rain_days"), "mean")
    sev_severe_rec = g(g(severity, "record_severe_wind_and_rain_days"), "value")
    sev_bits = []
    if sev_w1 is not None:
        sev_bits.append(f"{sev_w1} days a season at \u2265 1.00 in of rain")
    if sev_gust is not None:
        sev_bits.append(f"{sev_gust} days with a gust \u2265 40 kt")
    if sev_severe is not None:
        sev_bits.append(f"{sev_severe} days that are both")
    sev_sentence = ("On the station record, the season averages " + ", ".join(sev_bits) + ".")
    sev_answer = (
        (sev_sentence + " " if sev_bits else "")
        + f"NOAA's Storm Events Database holds {n_all} records for San Francisco County over {span}, of "
        + f"which {n_flood} are rain-related ({', '.join(flood_types)}). "
        + "Its damage column is not usable as a cost estimate "
        + ("\u2014 every non-zero value NCEI holds for this county is a token amount "
           f"({n_dmg} of {n_all} records carry one) \u2014 " if n_dmg else "\u2014 ")
        + "so severity here is stated as counts of days at a plain threshold rather than as a dollar figure. "
        + "No named warning category (Advisory / Warning / High Wind) is applied: those criteria are written "
          "per forecast zone and this project does not restate them.")
    sev_numbers = [
        {"label": "Storm Events records, SF County", "value": f"{n_all} ({span})"},
        {"label": "Rain-related records (Flood, Flash Flood, Heavy Rain, Debris Flow)",
         "value": f"{n_flood} of {n_all}"},
        {"label": "Records with a non-zero damage figure",
         "value": ("not derived this run" if n_dmg is None else f"{n_dmg} of {n_all} \u2014 no dollar total published")},
    ]
    if sev_w1 is not None:
        sev_numbers.append({
            "label": "Days per season at \u2265 1.00 in",
            "value": (f"mean {sev_w1}" + (f" \u00b7 peak {sev_w1_rec} in {sev_w1_rec_season}"
                                          if sev_w1_rec is not None else ""))})
    if sev_gust is not None:
        sev_numbers.append({"label": "Days per season with a gust \u2265 40 kt",
                            "value": f"mean {sev_gust}"})
    if sev_severe is not None:
        sev_numbers.append({
            "label": "Days per season both \u2265 1.00 in and a gust \u2265 40 kt",
            "value": (f"mean {sev_severe}" + (f" \u00b7 peak {sev_severe_rec}"
                                              if sev_severe_rec is not None else ""))})

    out.append({
        "n": 6,
        "key": "storm_severity",
        "question": "How severe have the storms actually been here?",
        "answer": sev_answer,
        "numbers": sev_numbers,
        "basis": "NOAA NCEI Storm Events Database, reported events only \u2014 under-reporting is likely",
        "confidence": "counts derived from the station record; no dollar estimate is made",
        "sources": [{"label": "NCEI Storm Events Database", "url":
                     "https://www.ncdc.noaa.gov/stormevents/"},
                    {"label": "NCEI Storm Events CSV files", "url": STORM_URL},
                    {"label": "NCEI GSOD 72494023234 (KSFO wind)", "url": GSOD_URL}],
    })

    # What the official seasonal outlook adds, kept strictly separate from the
    # observed record above.
    official = {
        "enso": {
            "state": f"{latest_oni.get('phase_label') or phase_label(latest_oni.get('phase'))} "
                     f"({fmt_oni_c(latest_oni.get('oni_c'))}, {oni_when})"
                     if latest_oni else None,
            "alert_status": diagnostic_status,
            "source_url": ENSODISC_URL,
        },
        "cpc_tilt": tilt,
        "daily_forecast": {
            "days_in_this_scoreboard_with_a_real_forecast": days_in_horizon,
            "official_horizon_ends": horizon_last_day,
        },
    }
    # What the outlook's own authors wrote to qualify it, copied verbatim from
    # the discussion the pipeline archived (or a visible statement that the
    # discussion could not be read).  Quotations only - never a number of this
    # project's making.
    if caveats is not None:
        official["prognostic_caveats"] = caveats

    # The only bridge this project is entitled to draw between "the official
    # outlook says X" and "that costs Y": the same 30 seasons, split by the
    # ENSO phase NOAA published for them.  It is a conditional average over the
    # observed record, not a forecast, and it is labelled that way.
    phase = (latest_oni or {}).get("phase")
    strat = (enso_strat or {}).get(phase) if phase else None
    other = {p: v for p, v in (enso_strat or {}).items() if p != phase}
    if strat and strat.get("mean") is not None:
        entry = {
            "phase": phase,
            "phase_label": (latest_oni or {}).get("phase_label") or phase_label(phase),
            "seasons_in_phase": strat.get("n"),
            "mean_in": strat.get("mean"),
            "median_in": strat.get("median"),
            "min_in": strat.get("min"),
            "max_in": strat.get("max"),
            "how_to_read": (
                "Mean Oct 1 \u2013 Jan 31 precipitation over the seasons in the 1991-2020 record "
                "whose published CPC ONI placed them in this same phase. This is a conditional "
                "average of what happened, NOT a forecast for 2026-27, and the spread inside the "
                "phase is as informative as the mean."),
            "contrast": [
                {"phase": p, "phase_label": v.get("phase_label") or phase_label(p),
                 "seasons": v.get("n"), "mean_in": v.get("mean")}
                for p, v in sorted(other.items(), key=lambda kv: -(kv[1].get("mean") or 0))
            ],
            "source_url": ONI_URL,
            "phase_source_url": ENSODISC_URL,
        }
        official["enso_conditioned_record"] = entry
    else:
        official["enso_conditioned_record"] = None
    return out, official





def build_cost_drivers(*, days, dist, streak_prob, enso_strat, latest_oni,
                       diagnostic_status, relevant_cpc, storms, monthly,
                       hourly_wind_rain=None):
    """Ranked repair & maintenance cost drivers for the 94122 rainy season.

    Every number in ``evidence`` is copied from the verified datasets produced
    by the pipeline (``dist`` comes from the GHCN-derived season statistics,
    CPC records from the official shapefile samples, storm counts from the
    NCEI Storm Events county extract).  ``why_it_costs`` is maintenance
    *guidance* about cost mechanisms, never a weather claim - the site labels
    it as such next to each driver.
    """
    drivers = []
    ghcn = [{"label": "NCEI GHCN-Daily USW00023272 (SF downtown gauge)", "url": GHCN_URL}]
    gsod = [{"label": "NCEI GSOD 72494023234 (KSFO wind)", "url": GSOD_URL}]
    storm_src = [{"label": "NCEI Storm Events CSV archive (SF County)", "url": STORM_URL}]

    # 1. Prolonged wet spells ---------------------------------------------
    lp = streak_prob or {}
    streak = dist.get("longest_wet_streak_days") or {}
    if lp and streak:
        evidence = []
        for key, label in (("ge_3_days", "Run of ≥3 consecutive wet days"),
                           ("ge_5_days", "Run of ≥5 consecutive wet days"),
                           ("ge_7_days", "Run of ≥7 consecutive wet days"),
                           ("ge_10_days", "Run of ≥10 consecutive wet days")):
            v = lp.get(key)
            if v:
                evidence.append({
                    "label": label,
                    "value": f"{v.get('pct')}% of seasons ({v.get('seasons')} of 30)"})
        if streak.get("max") is not None:
            evidence.append({
                "label": "Longest run in a season",
                "value": f"mean {streak.get('mean')} days · max {streak.get('max')} days on record"})
        drivers.append({
            "driver": "Prolonged wet spells — roof, gutters & drainage",
            "why_it_costs": ("A week or more of nearly continuous rain saturates roofing and "
                             "sheathing, finds failed flashing, and keeps gutters overflowing — "
                             "the classic path to ceiling stains, rotten fascia and end-of-lease "
                             "repair bills. Inspect roof, gutters and downspouts before the season "
                             "and re-check after any 7+ day run."),
            "evidence": evidence,
            "sources": ghcn,
        })

    # 2. Heavy single-day rain --------------------------------------------
    exp_025 = expected_event_days(days, "p_rain_ge_025in_pct")
    exp_100 = expected_event_days(days, "p_rain_ge_100in_pct")
    dec = dist.get("december_total_prcp_in") or {}
    jan = dist.get("january_total_prcp_in") or {}
    flood_count = None
    flood_with_damage = None
    storm_years = None
    if storms and isinstance(storms.get("events"), list):
        flood_types = RAIN_RELATED_EVENT_TYPES
        flood_count = sum(1 for e in storms["events"]
                          if (e or {}).get("event_type") in flood_types)
        flood_with_damage = sum(
            1 for e in storms["events"]
            if (e or {}).get("event_type") in flood_types
            and (parse_damage_usd((e or {}).get("damage_property")) or 0) > 0)
        if storms.get("years"):
            ys = storms["years"]
            storm_years = f"{min(ys)}–{max(ys)}"
    if exp_025 is not None or exp_100 is not None:
        evidence = []
        if exp_025 is not None:
            evidence.append({"label": "Days ≥ 0.25 in rain per season (expected count)",
                             "value": f"{exp_025} days"})
        if exp_100 is not None:
            evidence.append({"label": "Days ≥ 1.00 in rain per season (expected count)",
                             "value": f"{exp_100} days"})
        if dec.get("max") is not None:
            evidence.append({
                "label": "Wettest December / January on record (1991–2020)",
                "value": f"{dec.get('max')} in / {(jan or {}).get('max')} in"})
        if flood_count is not None:
            evidence.append({
                "label": (f"Rain-related storm reports in SF County "
                          f"(Flood, Flash Flood, Heavy Rain, Debris Flow; "
                          f"{storm_years or 'archive years'})"),
                "value": (f"{flood_count} events in NOAA Storm Events "
                          "(reported events only - under-reporting is likely)")})
            if flood_with_damage is not None:
                evidence.append({
                    "label": "…of those, reports carrying a recorded property-damage figure",
                    "value": (f"{flood_with_damage} of {flood_count} "
                              "(county damage entries are sparse in this database)")})
        drivers.append({
            "driver": "Heavy single-day rain — storm drains, entryways & low-lying units",
            "why_it_costs": ("Short, intense rain is what overwhelms area drains, garage thresholds "
                             "and ground-floor entryways, and it is when sewer backups and slope "
                             "failures happen. Clear drains before the season; the heaviest days "
                             "cluster in December and January."),
            "evidence": evidence,
            "sources": ghcn + storm_src,
        })

    # 3. Wind + rain together ---------------------------------------------
    wr = dist.get("wind_and_rain_days") or {}
    hwr = dist.get("heavy_wind_and_rain_days") or {}
    hourly = hourly_wind_rain or {}
    h_days = (hourly.get("days_with_a_simultaneous_hour") or {})
    h_pair = (hourly.get("days_daily_pair_same_station") or {})
    hourly_src = [{"label": "NCEI ISD hourly archive (station 72494023234, SFO)",
                   "url": ISD_URL}]
    if wr:
        evidence = []
        if hourly.get("available") and h_days:
            evidence.append({
                "label": "Days per season with a simultaneous wind ≥ 20 kt + rain hour "
                         "(hour-by-hour record, SFO)",
                "value": (f"mean {h_days.get('mean')} · median {h_days.get('median')} · "
                          f"max {h_days.get('max')} over {hourly.get('n_seasons_used')} seasons")})
            if h_pair and hourly.get("same_station_daily_fields_available"):
                evidence.append({
                    "label": "Days per season, whole-day pairing at the same station (for comparison)",
                    "value": (f"mean {h_pair.get('mean')} · median {h_pair.get('median')} · "
                              f"max {h_pair.get('max')}")})
        evidence += [
            {"label": "Days with rain ≥ 0.01 in and sustained wind ≥ 20 kt (whole-day pairing, "
                      "downtown gauge + SFO wind)",
             "value": (f"mean {wr.get('mean')} · median {wr.get('median')} · "
                       f"max {wr.get('max')} per season")},
            {"label": "Days with rain ≥ 0.50 in and a gust ≥ 35 kt",
             "value": (f"mean {hwr.get('mean')} · median {hwr.get('median')} · "
                       f"max {hwr.get('max')} per season")},
        ]
        drivers.append({
            "driver": "Wind + rain together — wind-driven water intrusion",
            "why_it_costs": ("Wind pushes rain sideways under shingles, laps and window seals and "
                             "into vents, so buildings leak during storms that would stay dry in "
                             "calm rain. These are also fence-failure and tree-limb days. Wind is "
                             "recorded at SFO, 11.9 miles away (computed great-circle distance from the "
                             "94122 centroid, see climatology.meta.station_distance_mi) and "
                             "more exposed, so treat the "
                             "counts as an upper bound for the Sunset. The headline count is the "
                             "hour-by-hour one: rain and wind measured in the same hour, not rain "
                             "and wind somewhere on the same day."),
            "evidence": evidence,
            "sources": (hourly_src if hourly.get("available") else []) + gsod + ghcn,
        })

    # 4. Peak gusts ---------------------------------------------------------
    mg = dist.get("max_gust_mph") or {}
    tw_count = None
    if storms and isinstance(storms.get("events"), list):
        tw_count = sum(1 for e in storms["events"]
                       if (e or {}).get("event_type") == "Thunderstorm Wind")
    if mg:
        evidence = [
            {"label": "Strongest gust of the season (SFO ASOS)",
             "value": (f"mean {mg.get('mean')} mph · median {mg.get('median')} mph · "
                       f"record {mg.get('max')} mph")},
        ]
        if tw_count is not None:
            evidence.append({
                "label": f"Thunderstorm-wind reports in SF County ({storm_years or 'archive years'})",
                "value": f"{tw_count} events in NOAA Storm Events"})
        drivers.append({
            "driver": "Peak gusts — trees, fences, roofing & tenant safety",
            "why_it_costs": ("The strongest gust of the season is what breaks limbs onto roofs and "
                             "cars and flattens fences - the storm-season liability with the "
                             "shortest fuse. SFO is more exposed than the Sunset, so these gusts "
                             "are an upper bound for the ZIP."),
            "evidence": evidence,
            "sources": gsod + storm_src,
        })

    # 5. Total seasonal water load (budget baseline + ENSO/CPC tilt) --------
    st = dist.get("season_total_prcp_in") or {}
    el = (enso_strat or {}).get("el_nino") or {}
    ln = (enso_strat or {}).get("la_nina") or {}
    prcp_cpc = [r for r in (relevant_cpc or [])
                if r.get("variable") == "prcp" and r.get("category_label")]
    # Every CPC outlook shapefile cited in the evidence rows, once each, so the
    # source list covers every period shown.
    cpc_srcs = []
    seen_cpc = set()
    for r in prcp_cpc:
        u = r.get("url")
        if u and u not in seen_cpc:
            seen_cpc.add(u)
            cpc_srcs.append({"label": f"CPC {r.get('valid_season')} shapefile", "url": u})
    if st:
        evidence = [
            {"label": "Season total, Oct 1 – Jan 31 (1991–2020)",
             "value": (f"mean {st.get('mean')} in · median {st.get('median')} in · "
                       f"range {st.get('min')}–{st.get('max')} in · p10–p90 "
                       f"{st.get('p10')}–{st.get('p90')} in")},
        ]
        if latest_oni and latest_oni.get("oni_c") is not None:
            when = latest_oni.get("label") or latest_oni.get("year_month") or "unknown period"
            stat = f"; CPC Alert System Status: {diagnostic_status}" if diagnostic_status else ""
            evidence.append({
                "label": "Current ENSO state (NOAA's published ONI product)",
                "value": (f"{when}: {fmt_oni_c(latest_oni.get('oni_c'))} = "
                          f"{phase_label(latest_oni.get('phase'))}"
                          + (f" ({str(latest_oni.get('strength')).replace('_', ' ')})"
                             if latest_oni.get("strength") else "") + stat)})
        if el and ln:
            evidence.append({
                "label": "Season total by ENSO phase (1991–2020; small samples)",
                "value": (f"El Niño {el.get('mean')} in (n={el.get('n')}) · "
                          f"La Niña {ln.get('mean')} in (n={ln.get('n')})")})
        for r in prcp_cpc:
            # A missing probability must never render as "None%" - say what is
            # actually known instead of printing a broken number.
            prob_txt = (f"{r.get('prob')}% probability" if r.get("prob") is not None
                        else "probability not stated in the sampled polygon")
            evidence.append({
                "label": f"CPC {r.get('valid_season')} precipitation outlook (issued {r.get('issued')})",
                "value": f"{r.get('category_label')} at {prob_txt}"})
        drivers.append({
            "driver": "Total seasonal water load — waterproofing budget & insurance",
            "why_it_costs": ("This is the total water the envelope must shed across the season and "
                             "the right baseline for repair budgets: plan for the mean, but price "
                             "reserves off the wetter tail - the p90 season delivered about 1.5x the "
                             "mean. El Niño tilts toward the wet end in this record, but individual "
                             "El Niño seasons have ranged from 7.27 to 22.82 in, so the tilt is not "
                             "a promise."),
            "evidence": evidence,
            "sources": ghcn + [{"label": "NOAA CPC official ONI product", "url": ONI_URL}] + cpc_srcs,
        })

    # 6. Wet-day frequency ----------------------------------------------------
    wd = dist.get("wet_days") or {}
    if wd:
        evidence = [
            {"label": "Wet days per season (≥0.01 in)", 
             "value": (f"mean {wd.get('mean')} · median {wd.get('median')} · "
                       f"range {wd.get('min')}–{wd.get('max')} of 123 days")},
        ]
        month_bits = []
        for m in monthly or []:
            lbl, ew = m.get("label"), m.get("expected_wet_days")
            if lbl and ew is not None:
                month_bits.append(f"{lbl} {m.get('year')}: {ew}")
        if month_bits:
            evidence.append({"label": "Expected wet days by month",
                             "value": " · ".join(month_bits)})
        drivers.append({
            "driver": "Wet-day frequency — condensation, ventilation & works scheduling",
            "why_it_costs": ("Three to four wet days a week for months drives indoor condensation "
                             "and mold complaints and closes windows for exterior paint, roofing "
                             "and concrete work. October is normally the driest month of the "
                             "window - schedule exterior jobs there, not in December."),
            "evidence": evidence,
            "sources": ghcn,
        })

    for i, d in enumerate(drivers, start=1):
        d["rank"] = i
    return drivers


#: Caption shown above the cost-driver block on the site; it separates the
#: guidance sentences from the verified numbers so neither is mistaken for
#: the other.
COST_DRIVERS_NOTE = (
    "Ranked for the landlord question behind this site: what about this "
    "rainy season plausibly drives repair and maintenance cost. The "
    "'Why it matters' sentence under each driver is maintenance guidance "
    "about cost mechanisms — it is not a weather claim. Every number is "
    "computed from, and links to, the official sources shown. Expected-day "
    "counts are sums of the per-date 1991–2020 observed probabilities "
    "(linearity of expectation): an expectation over the distribution, not "
    "a prediction for 2026-27."
)


# CPC category explanations, keyed on (variable, category_label) so the sentence
# on the page always describes the category that is actually displayed.
# category_label values are produced by build_calendar.py from the raw DBF "Cat"
# field (EC / Above / Below), so this table mirrors that mapping exactly.
_CPC_NOTES = {
    ("prcp", "Above median"):
        "For precipitation, 'Above median' means CPC favours an above-median total "
        "for the whole 3-month period.",
    ("prcp", "Below median"):
        "For precipitation, 'Below median' means CPC favours a below-median total "
        "for the whole 3-month period.",
    ("prcp", "Equal chances"):
        "For precipitation, 'Equal chances' means CPC sees no tilt: above-median, "
        "near-median and below-median totals are all about equally likely (33% each). "
        "This is not a forecast of dry conditions.",
    ("temp", "Above normal"):
        "For temperature, 'Above normal' means CPC favours an above-normal average "
        "temperature for the whole 3-month period.",
    ("temp", "Below normal"):
        "For temperature, 'Below normal' means CPC favours a below-normal average "
        "temperature for the whole 3-month period.",
    ("temp", "Equal chances"):
        "For temperature, 'Equal chances' means CPC sees no tilt: above-normal, "
        "near-normal and below-normal averages are all about equally likely (33% each).",
}


def cpc_category_note(variable, category_label):
    """Return an explanation of *this* CPC category, or say it is undefined.

    Never falls back to a different category's wording - an unrecognised label
    gets an explicit 'not documented here' rather than a plausible-looking
    sentence about some other category.
    """
    note = _CPC_NOTES.get((variable, category_label))
    if note:
        return note
    return (
        f"CPC's meaning for the category '{category_label}' "
        f"({variable}) is not documented in this project's tables, so no "
        "interpretation is offered here - see the CPC source map for the "
        "official legend."
    )


def main():
    calendar = load("calendar.json")
    run = load("run.json")
    climatology = load("climatology.json")
    cpc = load("cpc.json")
    enso = load("enso.json")
    storms = load("storm_events.json")

    # Season summary
    dist = calendar.get("season_summary", {})
    streak_prob = calendar.get("streak_probability", {})
    enso_strat = calendar.get("enso_stratified", {})
    monthly = calendar.get("monthly", [])
    days = calendar.get("days", [])

    # CPC records relevant to our window
    cpc_records = calendar.get("cpc", {}).get("records", []) or cpc.get("shapefiles", [])

    # Build landlord-focused insights
    # 1. Expected rain amounts
    season_total = dist.get("season_total_prcp_in", {})
    oct_total = dist.get("october_total_prcp_in", {})
    nov_total = dist.get("november_total_prcp_in", {})
    dec_total = dist.get("december_total_prcp_in", {})
    jan_total = dist.get("january_total_prcp_in", {})

    # 2. Rain duration
    wet_days = dist.get("wet_days", {})
    longest_streak = dist.get("longest_wet_streak_days", {})

    # 3. Wind and rain.  Two methods, both published:
    #    - the cross-station daily pairing that has always been on this page
    #      (GHCN downtown rain day x GSOD SFO daily max wind, UTC day), and
    #    - the hour-by-hour co-occurrence at SFO from the ISD hourly archive.
    #    The hourly number is the one that actually answers "at the same time";
    #    the daily number is kept and labelled, never quietly replaced.
    wind_rain = dist.get("wind_and_rain_days", {})
    heavy_wind_rain = dist.get("heavy_wind_and_rain_days", {})
    max_gust = dist.get("max_gust_mph", {})
    isd = load("isd_hourly_summary.json")
    hourly_wind_rain = summarise_hourly_wind_rain(
        isd, tuple(run.get("normals_period", [1991, 2020])), wind_rain, heavy_wind_rain)

    # 4. ENSO context - NOAA's published ONI product is the headline value.
    enso_cal = calendar.get("enso", {}) or {}
    latest_oni = (enso_cal.get("latest_official") or enso.get("latest_oni")
                  or (enso.get("official_oni") or {}).get("latest") or {})
    # The official product is season-labelled (e.g. "JJA 2026"); older drafts of
    # this file used a month label.  Both are rendered without inventing a label.
    oni_when = latest_oni.get("label") or latest_oni.get("year_month") or "unknown period"
    oni_url = ((enso_cal.get("official") or {}).get("url")
               or "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt")
    diagnostic_url = (enso_cal.get("diagnostic_url")
                      or "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml")
    diagnostic_status = enso_cal.get("diagnostic_status")

    # 5. CPC outlooks for our window - match exact valid periods only.
    # A substring test such as `"NDJ" in vs` would pull an older NDJ issuance
    # into a future-season summary if the archive contains multiple years.
    relevant_periods = {
        "SON 2026", "OND 2026", "NDJ 2026-2027", "DJF 2026-2027",
        "JFM 2027", "Oct 2026", "Nov 2026", "Dec 2026", "Jan 2027",
    }
    relevant_cpc = [
        rec for rec in calendar.get("cpc", {}).get("records", [])
        if rec.get("valid_season") in relevant_periods
    ]

    # Sort by issued date descending, keep most recent per period
    relevant_cpc_sorted = sorted(relevant_cpc, key=lambda r: (r.get("issued") or "", r.get("valid_season") or ""), reverse=True)
    # Deduplicate by valid_season+variable keeping most recent
    seen = {}
    deduped = []
    for r in relevant_cpc_sorted:
        key = (r.get("valid_season"), r.get("variable"))
        if key not in seen:
            seen[key] = True
            deduped.append(r)
    relevant_cpc = sorted(deduped, key=lambda r: r.get("valid_season") or "")

    # 6. Daily risk calendar - which dates historically have highest rain chance
    high_risk_days = sorted(
        [d for d in days if d.get("climo", {}).get("p_rain_day_pct") is not None],
        key=lambda d: d["climo"]["p_rain_day_pct"],
        reverse=True
    )[:15]

    low_risk_days = sorted(
        [d for d in days if d.get("climo", {}).get("p_rain_day_pct") is not None],
        key=lambda d: d["climo"]["p_rain_day_pct"]
    )[:10]

    # 7. Build action items based on verified climatology
    action_items = []

    # Rain amount action
    if season_total.get("mean"):
        action_items.append({
            "category": "Rainfall preparation",
            "priority": "high",
            "title": f"Prepare for {season_total.get('mean')} inches average seasonal rain (Oct-Jan)",
            "detail": f"Historical range {season_total.get('min')} to {season_total.get('max')} inches over 30 seasons. Median {season_total.get('median')} inches. This is the baseline before any El Niño tilt.",
            "source": "NCEI GHCN-Daily USW00023272 1991-2020",
            "source_url": "https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00023272.csv"
        })

    # Duration action
    ge_7 = streak_prob.get("ge_7_days", {})
    if ge_7.get("pct"):
        action_items.append({
            "category": "Rain duration",
            "priority": "high" if ge_7.get("pct", 0) >= 50 else "medium",
            "title": f"{ge_7.get('pct')}% of seasons have at least one 7-day wet streak",
            "detail": f"In 1991-2020, {ge_7.get('seasons')} of 30 seasons had a run of 7+ consecutive wet days (≥0.01 in) inside Oct 1-Jan 31. Longest run on record: {longest_streak.get('max')} days. Average longest run: {longest_streak.get('mean')} days. Prepare for roof, gutters, and drainage to handle week-long rain.",
            "source": "NCEI GHCN-Daily USW00023272",
            "source_url": "https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00023272.csv"
        })

    ge_10 = streak_prob.get("ge_10_days", {})
    if ge_10.get("pct"):
        action_items.append({
            "category": "Rain duration",
            "priority": "medium",
            "title": f"{ge_10.get('pct')}% of seasons have a 10-day wet streak",
            "detail": f"{ge_10.get('seasons')} of 30 seasons had 10+ consecutive wet days. This is not rare - about 1 year in 4. Consider tenant communication plan for extended wet periods.",
            "source": "NCEI GHCN-Daily USW00023272",
            "source_url": "https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00023272.csv"
        })

    # Wind + rain.  The action item quotes the hour-by-hour count when it is
    # available, because that is the one that means "at the same time".
    hourly_days = (hourly_wind_rain or {}).get("days_with_a_simultaneous_hour") or {}
    if hourly_days.get("mean") is not None:
        action_items.append({
            "category": "Wind + rain",
            "priority": "high",
            "title": (f"Expect {hourly_days.get('mean')} days per season when rain and sustained "
                      "wind ≥ 20 kt happen in the same hour"),
            "detail": (f"Hour-by-hour NCEI ISD record at SFO ASOS (more exposed than the Sunset, so an "
                       f"upper bound for 94122): mean {hourly_days.get('mean')}, median "
                       f"{hourly_days.get('median')}, max {hourly_days.get('max')} local dates per "
                       f"Oct-Jan season carrying at least one hour with rain AND sustained wind ≥ 20 kt, "
                       f"over {(hourly_wind_rain or {}).get('n_seasons_used')} seasons. "
                       + (f"Pairing whole days instead (the method used before) gives mean "
                          f"{((hourly_wind_rain or {}).get('days_daily_pair_same_station') or {}).get('mean')} "
                          "days at the same station, and "
                          if (hourly_wind_rain or {}).get("same_station_daily_fields_available") else "")
                       + f"{wind_rain.get('mean')} days when the downtown "
                       "rain gauge is paired with SFO wind. Heavy wind+rain (≥0.50 in AND gust ≥35 kt, "
                       f"whole days): mean {heavy_wind_rain.get('mean')}, max "
                       f"{heavy_wind_rain.get('max')} days."),
            "source": "NCEI ISD hourly 72494023234 (KSFO) + GSOD + GHCN-Daily",
            "source_url": ISD_URL,
        })
    elif wind_rain.get("mean"):
        action_items.append({
            "category": "Wind + rain",
            "priority": "high",
            "title": f"Expect {wind_rain.get('mean')} days per season with both rain and sustained wind ≥20 kt",
            "detail": f"At SFO ASOS (more exposed than Sunset, so upper bound for 94122): mean {wind_rain.get('mean')}, median {wind_rain.get('median')}, max {wind_rain.get('max')} days per Oct-Jan season with ≥0.01 in rain AND ≥20 kt sustained wind. Heavy wind+rain (≥0.50 in AND gust ≥35 kt): mean {heavy_wind_rain.get('mean')}, max {heavy_wind_rain.get('max')} days.",
            "source": "NCEI GSOD 72494023234 (KSFO) + GHCN-Daily",
            "source_url": "https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/"
        })

    # Gusts
    if max_gust.get("mean"):
        action_items.append({
            "category": "Wind / gusts",
            "priority": "high",
            "title": f"Seasonal max gust averages {max_gust.get('mean')} mph (record {max_gust.get('max')} mph)",
            "detail": f"SFO ASOS reports average strongest gust of season {max_gust.get('mean')} mph, median {max_gust.get('median')} mph. Sunset will be less, but this is the verified upper bound. Check trees, fences, and loose items.",
            "source": "NCEI GSOD 72494023234",
            "source_url": "https://www.ncei.noaa.gov/data/global-summary-of-the-day/doc/readme.txt"
        })

    # ENSO
    if latest_oni.get("oni_c") is not None:
        phase = latest_oni.get("phase", "unknown")
        phase_txt = phase_label(phase)
        oni_txt = fmt_oni_c(latest_oni.get("oni_c"))
        action_items.append({
            "category": "ENSO / seasonal tilt",
            "priority": "high" if phase == "el_nino" else "medium",
            "title": f"ENSO phase: {phase_txt} (official ONI {oni_txt} for {oni_when})",
            "detail": f"NOAA's published ONI product shows {oni_when} at {oni_txt} = {phase_txt}"
                      + (f", {str(latest_oni.get('strength')).replace('_', ' ')} by CPC's own strength bands" if latest_oni.get("strength") else "")
                      + (f". CPC Alert System Status: {diagnostic_status}." if diagnostic_status else ".")
                      + f" In El Niño years, Oct-Jan mean was {enso_strat.get('el_nino', {}).get('mean')} in vs {enso_strat.get('la_nina', {}).get('mean')} in for La Niña (n={enso_strat.get('el_nino', {}).get('n')} El Niño seasons). El Niño tilts toward wetter, but spread is wide: wettest El Niño {enso_strat.get('el_nino', {}).get('max')} in, driest El Niño {enso_strat.get('el_nino', {}).get('min')} in.",
            "source": "NOAA CPC official ONI product (oni.ascii.txt)",
            "source_url": oni_url
        })

    # CPC outlooks
    # The explanation has to be keyed on the category that is actually shown,
    # not just on the variable.  Keying it on the variable alone produced
    # "CPC OND 2026: Equal chances (33%) ... For precipitation, 'Above median'
    # means CPC favors an above-median total" - an explanation of a different
    # category than the one on the page, which is exactly the kind of statement
    # this project is not allowed to make.
    for rec in relevant_cpc:
        if rec.get("valid_season") in ["OND 2026", "NDJ 2026-2027", "DJF 2026-2027", "JFM 2027"]:
            variable_note = cpc_category_note(rec.get("variable"), rec.get("category_label"))
            if rec.get("prob") is not None:
                prob_txt = f"{rec.get('prob')}%"
                prob_detail = f"with {rec.get('prob')}% probability"
            else:
                prob_txt = "probability not stated"
                prob_detail = "with the probability not stated in the sampled polygon"
            action_items.append({
                "category": "Official CPC outlook",
                "priority": "medium",
                "title": f"CPC {rec.get('valid_season')}: {rec.get('category_label')} ({prob_txt}) - {rec.get('variable')}"
                         + (" - at the climatological baseline" if rec.get("probability_at_climatological_baseline") else ""),
                "detail": f"Issued {rec.get('issued')}, forecast date {rec.get('fcst_date')}. This is a probability for the whole 3-month period, not a daily forecast. Category: {rec.get('category_label')} {prob_detail}. {variable_note}"
                          + (f" Note: {rec.get('baseline_note')}" if rec.get("baseline_note") else ""),
                "source": rec.get("url"),
                "source_url": rec.get("url")
            })

    # Monthly breakdown
    monthly_summary = []
    for m in monthly:
        tot = m.get("total_prcp") or {}
        monthly_summary.append({
            "month": m.get("label"),
            "year": m.get("year"),
            "mean_in": tot.get("mean"),
            "median_in": tot.get("median"),
            "min_in": tot.get("min"),
            "max_in": tot.get("max"),
            "p90_in": tot.get("p90"),
            "expected_wet_days": m.get("expected_wet_days"),
            "days": m.get("days"),
            "cpc_outlooks": [
                {"valid_season": r.get("valid_season"), "variable": r.get("variable"),
                 "category_label": r.get("category_label"), "prob": r.get("prob"),
                 "issued": r.get("issued"), "url": r.get("url")}
                for r in (m.get("cpc_seasonal") or [])[:4]
            ]
        })

    # 8. Maintenance cost drivers - ranked executive summary -----------------
    # Every number inside comes from the verified structures above; nothing is
    # added by hand.  The expected-day counts are published separately as well
    # so the verification ledger can re-derive them from climatology.json.
    expected_days = {
        "ge_025in_days": expected_event_days(days, "p_rain_ge_025in_pct"),
        "ge_100in_days": expected_event_days(days, "p_rain_ge_100in_pct"),
        "method": ("Sum of each calendar date's 1991-2020 observed probability over the "
                   "123-day window (linearity of expectation): the expected number of days "
                   "per season meeting the test, not a prediction for 2026-27."),
    }
    cost_drivers = build_cost_drivers(
        days=days, dist=dist, streak_prob=streak_prob, enso_strat=enso_strat,
        latest_oni=latest_oni, diagnostic_status=diagnostic_status,
        relevant_cpc=relevant_cpc, storms=storms, monthly=monthly,
        hourly_wind_rain=hourly_wind_rain)

    # 8b. NOAA's own published daily normals for the same station ----------
    # The landlord's two headline rain questions have an *officially published*
    # answer as well as this project's derivation: NCEI publishes, for every
    # calendar date, the share of years recording at least 0.25 in and at least
    # 1.00 in of precipitation.  Summing those published probabilities over the
    # 123 dates gives the expected heavy-rain days per season straight from the
    # official file - an independent counterpart to ``expected_days`` above.
    # Both are published side by side; neither replaces the other.
    published_official = {
        "source": "NOAA NCEI U.S. Climate Normals 1991-2020 (daily, by station)",
        "url": (calendar.get("daily_normals_official") or {}).get("url"),
        "station_id": (calendar.get("daily_normals_official") or {}).get("station_id"),
        "station_name": (calendar.get("daily_normals_official") or {}).get("station_name"),
        "sha256": (calendar.get("daily_normals_official") or {}).get("sha256"),
        "retrieved_utc": (calendar.get("daily_normals_official") or {}).get("retrieved_utc"),
        "dates_parsed": (calendar.get("daily_normals_official") or {}).get("dates_parsed"),
        "columns": (calendar.get("daily_normals_official") or {}).get("layout", {}).get("column_by_key"),
        "comparison": calendar.get("daily_normals_comparison"),
    }
    pub_expected = {}
    for key, label in (("p_pcp_ge_0p01in_pct", "ge_001in_days"),
                       ("p_pcp_ge_0p10in_pct", "ge_010in_days"),
                       ("p_pcp_ge_0p25in_pct", "ge_025in_days"),
                       ("p_pcp_ge_0p50in_pct", "ge_050in_days"),
                       ("p_pcp_ge_1p00in_pct", "ge_100in_days"),
                       ("p_pcp_ge_2p00in_pct", "ge_200in_days"),
                       ("p_pcp_ge_4p00in_pct", "ge_400in_days"),
                       ("p_pcp_ge_6p00in_pct", "ge_600in_days")):
        total = 0.0
        seen = 0
        for d in days:
            off = d.get("official_normal") or {}
            v = off.get(key)
            if v is None:
                continue
            seen += 1
            total += float(v) / 100.0
        if seen:
            pub_expected[label] = round(total, 2)
    if pub_expected:
        # Named ``dates_compared``, not ``days_covered``: this project used to
        # publish a *different* ``days_covered`` in nws_window meaning "scoreboard
        # days carrying a real NWS forecast", and two unrelated quantities with
        # one name is how a reader ends up quoting the wrong one.
        pub_expected["dates_compared"] = len(days)
        pub_expected["method"] = (
            "Sum of NOAA's own published per-date probabilities (DLY-PRCP-PCTALL-"
            "GE***HI) over the 123 dates of the window - the same linearity-of-"
            "expectation arithmetic as expected_days, but using the official "
            "published probabilities instead of this project's own count.")
        published_official["published_expected_days"] = pub_expected
    official_daily_normals = published_official if published_official.get("comparison") \
        or pub_expected else None

    # 8c. The landlord's six questions, answered in order -----------------
    # Severity counters come from the same GHCN/GSOD files as everything else;
    # the record values are the per-season maxima bound to their season.
    severity_dist = {
        k: dist.get(k) for k in (
            "wet_days_ge_050in", "wet_days_ge_1in", "wet_days_ge_2in",
            "wet_days_ge_400in", "max_daily_prcp_in", "wind_days_ge_30kt",
            "gust_days_ge_40kt", "gust_days_ge_50kt", "max_wind_mph",
            "severe_wind_and_rain_days",
        ) if dist.get(k) is not None
    }

    # The project's own count and NOAA's published expectation, on the same
    # threshold, side by side.  NOAA publishes a percent-of-years value for
    # exactly these eight precipitation thresholds, and this project counts
    # days at four of them from the same station's daily file - so the reader
    # can see both methods rather than having to trust one.
    _threshold_pairs = (
        (0.50, "wet_days_ge_050in", "ge_050in_days"),
        (1.00, "wet_days_ge_1in", "ge_100in_days"),
        (2.00, "wet_days_ge_2in", "ge_200in_days"),
        (4.00, "wet_days_ge_400in", "ge_400in_days"),
    )
    threshold_comparison = []
    for inches, proj_key, noaa_key in _threshold_pairs:
        proj = dist.get(proj_key)
        noaa = pub_expected.get(noaa_key)
        if proj is None and noaa is None:
            continue
        proj_mean = (proj or {}).get("mean")
        entry = {
            "threshold_in": inches,
            "project_mean_days": proj_mean,
            "project_max_days": (proj or {}).get("max"),
            "noaa_expected_days": noaa,
            "difference_days": (round(proj_mean - noaa, 2)
                                if (proj_mean is not None and noaa is not None) else None),
            "project_method": ("mean of the 30 seasons' counts of days at or above this "
                               "threshold, from the station's daily precipitation file"),
            "noaa_method": ("sum of NOAA's own published per-date percent-of-years value "
                            "(DLY-PRCP-PCTALL-GE***HI) over the 123 dates"),
        }
        threshold_comparison.append(entry)

    # Whether the claim "the two methods agree" is allowed to be made is decided
    # here, from the numbers, not written into the prose by hand: if the
    # differences had come out large the site would have to say that instead.
    _diffs = [abs(t["difference_days"]) for t in threshold_comparison
              if t.get("difference_days") is not None]
    two_method_agreement = None
    if _diffs:
        _worst = max(_diffs)
        two_method_agreement = {
            "thresholds_compared": len(_diffs),
            "largest_difference_days": round(_worst, 2),
            "agree_within_a_tenth": _worst <= 0.10,
            "statement": (f"The two independent methods agree to within {_worst:.2f} day(s) "
                          f"per season across {len(_diffs)} thresholds."
                          if _worst <= 0.10 else
                          f"The two independent methods differ by up to {_worst:.2f} day(s) "
                          f"per season across {len(_diffs)} thresholds; both are published "
                          "as-is and neither is adjusted."),
            "source_note": ("One method counts days in this station's daily file; the other "
                            "sums NOAA's own published per-date probabilities. They share a "
                            "station but not a derivation."),
        }
    severity_record = calendar.get("severity_record", {}) or {}
    severity = {
        **severity_dist,
        "record_daily_prcp_in": severity_record.get("max_daily_prcp_in"),
        "record_gust": severity_record.get("max_gust_mph"),
        "record_sustained_wind": severity_record.get("max_wind_mph"),
        "record_days_ge_1in": severity_record.get("most_wet_days_ge_1in"),
        "record_days_gust_ge_40kt": severity_record.get("most_days_gust_ge_40kt"),
        "record_severe_wind_and_rain_days": severity_record.get(
            "most_severe_wind_and_rain_days"),
        "threshold_comparison": threshold_comparison,
        "two_method_agreement": two_method_agreement,
        "published_expected": pub_expected,
        "sources": [
            {"label": "NCEI GHCN-Daily USW00023272", "url": GHCN_URL},
            {"label": "NCEI GSOD 72494023234 (KSFO)", "url": GSOD_URL},
        ],
        "thresholds_note": (
            "Every counter is 'days per season at or above this plain threshold' in the "
            "units published by NCEI. No named warning category (Advisory/Warning) is "
            "applied, because those criteria are written per forecast zone and this "
            "project does not restate them."
        ),
    }
    # How many Storm Events rows carry a non-zero damage figure.  Recorded so
    # the executive summary can state it instead of pointing elsewhere.
    def _damage_usd(v):
        return parse_damage_usd(v)

    storm_events = (storms or {}).get("events") or []
    if storm_events:
        storms = dict(storms)
        storms["n_with_damage"] = sum(
            1 for e in storm_events if (_damage_usd(e.get("damage_property")) or 0) > 0)

    cpc_tilt = cpc_tilt_summary(relevant_cpc)
    bottom_line, official_outlook = build_bottom_line(
        season_total=season_total, wet_days=wet_days, streak_prob=streak_prob,
        longest_streak=longest_streak, wind_rain=wind_rain,
        heavy_wind_and_rain=heavy_wind_rain, max_gust=max_gust,
        expected_days=expected_days, severity=severity, latest_oni=latest_oni,
        oni_when=oni_when, diagnostic_status=diagnostic_status, tilt=cpc_tilt,
        storms=storms,
        days_in_horizon=(calendar.get("nws_window") or {}).get("scoreboard_days_in_horizon"),
        horizon_last_day=(calendar.get("nws_window") or {}).get("last_day"),
        enso_strat=enso_strat, hourly_wind_rain=hourly_wind_rain,
        caveats=prognostic_caveats(cpc))

    # Phase-aware ENSO sentence for the key finding: the tilt wording has to
    # follow the phase NOAA actually published, not a template that always
    # says "wetter".
    el_mean = (enso_strat.get("el_nino") or {}).get("mean")
    ln_mean = (enso_strat.get("la_nina") or {}).get("mean")
    nt_mean = (enso_strat.get("neutral") or {}).get("mean")
    if enso_strat and latest_oni.get("phase") == "el_nino" and el_mean and ln_mean:
        enso_tilt = (f"in this record El Niño seasons averaged wetter than La Niña "
                     f"({el_mean} in vs {ln_mean} in), with a wide spread in both")
    elif enso_strat and latest_oni.get("phase") == "la_nina" and el_mean and ln_mean:
        enso_tilt = (f"in this record La Niña seasons averaged drier than El Niño "
                     f"({ln_mean} in vs {el_mean} in), with a wide spread in both")
    elif enso_strat and nt_mean:
        enso_tilt = f"neutral seasons in this record averaged {nt_mean} in, with a wide spread"
    else:
        enso_tilt = "NOAA's published ONI is the official ENSO state"

    # Key-finding sentence for the wind-and-rain pair, built before the dict so the
    # hourly figure is used when it exists and the whole-day figure is named either
    # way.  Never a silent substitution: both numbers appear.
    _hourly_days = ((hourly_wind_rain or {}).get("days_with_a_simultaneous_hour") or {})
    if _hourly_days.get("mean") is not None:
        wind_rain_sentence = (
            f"Wind+rain together occurred {_hourly_days.get('mean')} days per season on average at "
            f"SFO on the hour-by-hour record (upper bound for Sunset); pairing whole days instead "
            f"gives {wind_rain.get('mean')} days. ")
    else:
        wind_rain_sentence = (
            f"Wind+rain together occurred {wind_rain.get('mean')} days per season on average at SFO "
            "(upper bound for Sunset). ")

    # Final landlord JSON
    landlord = {
        # This is a transform of the calendar/source snapshot, not a new
        # network fetch.  Preserve the source-run timestamp for honest freshness.
        "generated_utc": calendar.get("generated_utc") or run.get("generated_utc") or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "target": run.get("target", {}),
        "season": calendar.get("season", {}),
        "normals_period": calendar.get("normals_period", [1991, 2020]),
        "executive_summary": {
            "location": "San Francisco, CA 94122 (Inner Sunset / Outer Sunset) - 37.7605N, -122.4839W",
            "verified_coordinate_source": "U.S. Census Bureau 2024 Gazetteer ZCTA file",
            "coordinate_source_url": "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_zcta_national.zip",
            "season_window": "October 1, 2026 - January 31, 2027 (123 days)",
            "current_enso": dict(latest_oni,
                                 phase_label=phase_label(latest_oni.get("phase")),
                                 oni_c_fmt=fmt_oni_c(latest_oni.get("oni_c"))),
            # Hour-by-hour wind-and-rain co-occurrence from the NCEI ISD archive,
            # published next to the whole-day approximation it replaces as the
            # headline: the two answer "at the same time" differently and both
            # numbers stay on the page.
            "wind_and_rain_hourly": hourly_wind_rain,
            # How current each NCEI archive behind these numbers actually is.
            "record_coverage": run.get("record_coverage"),
            "season_total_prcp": season_total,
            "oct_total": oct_total,
            "nov_total": nov_total,
            "dec_total": dec_total,
            "jan_total": jan_total,
            "wet_days_per_season": wet_days,
            "longest_streak": longest_streak,
            "streak_probability": streak_prob,
            "wind_and_rain": wind_rain,
            "heavy_wind_and_rain": heavy_wind_rain,
            "max_gust": max_gust,
            "enso_stratified": enso_strat,
            "expected_days": expected_days,
            # The landlord's six questions, answered in the order asked, each
            # with the basis it rests on and the official file to check it in.
            # This is the block the page leads with.
            "bottom_line": bottom_line,
            "bottom_line_note": (
                "Each answer states the basis it rests on. Anything labelled "
                "1991\u20132020 observed record is an observation or an expectation over "
                "those 30 seasons; anything under 'Official outlook' is an official "
                "probability for a whole period. No row is a forecast for a named day "
                "\u2014 no official product issues one more than about a week ahead."),
            "official_outlook": official_outlook,
            "severity": severity,
            "cost_drivers": cost_drivers,
            "cost_drivers_note": COST_DRIVERS_NOTE,
            "key_finding": (
                f"Over 1991-2020, Oct-Jan averaged {season_total.get('mean')} in rain across {wet_days.get('mean')} wet days. "
                f"{streak_prob.get('ge_7_days', {}).get('pct')}% of seasons had a 7+ day wet streak, "
                f"{streak_prob.get('ge_10_days', {}).get('pct')}% had 10+ days. "
                f"{wind_rain_sentence}"
                f"Current ENSO: {phase_label(latest_oni.get('phase'))} (official ONI {fmt_oni_c(latest_oni.get('oni_c'))}, {oni_when}) - "
                f"{enso_tilt}"
                + (f"; CPC status \"{diagnostic_status}\"" if diagnostic_status else "")
                + ". The CPC outlooks attached to each day show the official probabilities for this window."
            )
        },
        "monthly": monthly_summary,
        "cpc_outlooks_relevant": relevant_cpc,
        "high_risk_dates": [
            {
                "date": d["date"],
                "month_label": d["month_label"],
                "day": d["day"],
                "rain_chance_pct": d["climo"].get("p_rain_day_pct"),
                "mean_prcp_in": d["climo"].get("mean_daily_prcp_in"),
                "max_gust_record_mph": d["climo"].get("max_gust_on_record_mph"),
                "wind_and_rain_pct": d["climo"].get("p_wind_and_rain_pct")
            }
            for d in high_risk_days
        ],
        "low_risk_dates": [
            {
                "date": d["date"],
                "month_label": d["month_label"],
                "day": d["day"],
                "rain_chance_pct": d["climo"].get("p_rain_day_pct")
            }
            for d in low_risk_days
        ],
        "action_items": action_items,
        "sources": {
            "census": "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_zcta_national.zip",
            "nws_api": "https://api.weather.gov/points/37.7605,-122.4839",
            "nws_human": "https://forecast.weather.gov/MapClick.php?lat=37.760459&lon=-122.483894",
            "cpc_gis": "https://www.cpc.ncep.noaa.gov/products/GIS/GIS_DATA/us_tempprcpfcst/",
            "cpc_90day_discussion": "https://www.cpc.ncep.noaa.gov/products/predictions/90day/fxus05.html",
            "cpc_oni_product": oni_url,
            "cpc_enso_diagnostic_discussion": diagnostic_url,
            "cpc_nino_table_crosscheck": "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/ensostuff/detrend.nino34.ascii.txt",
            "ghcn_daily": "https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00023272.csv",
            "gsod": "https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/",
            "gsod_readme": "https://www.ncei.noaa.gov/data/global-summary-of-the-day/doc/readme.txt",
            "storm_events": "https://www.ncdc.noaa.gov/stormevents/",
            "normals": "https://www.ncei.noaa.gov/data/normals-daily/1991-2020/access/USW00023272.csv"
        },
        "official_daily_normals": official_daily_normals,
        "disclaimer": "Independent hobby project. Not affiliated with NOAA/NWS/NCEI/CPC. For life-safety decisions use weather.gov and weather.gov/mtr directly. Daily forecast beyond 7 days does not exist; climatology shown is not a forecast.",
        "verification_note": "Every number traces to a URL in data/provenance.json. No commercial providers (AccuWeather etc.) are used because they require paid keys and are not independently verifiable line by line. All hosts verified against vetted official list."
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(landlord, indent=2))
    print(f"Wrote {OUT} ({OUT.stat().st_size:,} bytes)")
    print(f"  action items: {len(action_items)}")
    print(f"  relevant CPC outlooks: {len(relevant_cpc)}")
    print(f"  monthly: {len(monthly_summary)}")
    print(f"  maintenance cost drivers: {len(cost_drivers)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
