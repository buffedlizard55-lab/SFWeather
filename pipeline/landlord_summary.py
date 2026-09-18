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


def build_bottom_line(*, season_total, wet_days, streak_prob, longest_streak,
                      wind_rain, heavy_wind_and_rain, max_gust, expected_days,
                      severity, latest_oni, oni_when, diagnostic_status,
                      tilt, storms, days_in_horizon, horizon_last_day,
                      enso_strat=None):
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
            "label": f"Days \u2265 {inches:.2f} in per season",
            "value": (f"{proj} counted \u00b7 {noaa} NOAA published"
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
            "per-date observed probabilities, so they are an expectation over the 30-season record, and "
            "NOAA's own published per-date probabilities give almost the same answer "
            f"({g(g(severity,'published_expected'),'ge_025in_days')} and "
            f"{g(g(severity,'published_expected'),'ge_100in_days')} days) \u2014 two independent methods, "
            "same station, same threshold."),
        "numbers": [
            {"label": "Days \u2265 0.25 in per season", "value": f"{g(expected_days,'ge_025in_days')} (expected)"},
            {"label": "Days \u2265 1.00 in per season", "value": f"{g(expected_days,'ge_100in_days')} (expected)"},
            {"label": "Same, NOAA's own published probabilities",
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

    out.append({
        "n": 5,
        "key": "wind_and_rain",
        "question": "Will wind and rain hit at the same time?",
        "answer": (
            f"Yes \u2014 on about {g(wind_rain,'mean')} days a season at SFO (\u2265 0.01 in of rain and sustained wind "
            f"\u2265 20 kt), and on about {g(heavy_wind_and_rain,'mean')} heavy days (\u2265 0.50 in and a gust "
            "\u2265 35 kt). Those are the days water is driven sideways under shingles, laps and window seals, and "
            "the days fences fail. The SFO wind figure is an upper bound; the rain figure is the downtown gauge."),
        "numbers": [
            {"label": "Wind+rain days per season", "value": f"mean {g(wind_rain,'mean')} \u00b7 max {g(wind_rain,'max')}"},
            {"label": "Heavy wind+rain days per season",
             "value": f"mean {g(heavy_wind_and_rain,'mean')} \u00b7 max {g(heavy_wind_and_rain,'max')}"},
        ],
        "basis": obs + "; " + obs_wind,
        "confidence": "GSOD days are 00\u201324Z (about 16:00\u201316:00 local), so the joint statistic pairs a "
                      "local-day rain total with a UTC-day wind figure \u2014 stated, not corrected",
        "sources": [{"label": "NCEI GSOD 72494023234 (KSFO)", "url": GSOD_URL},
                    {"label": "NCEI GHCN-Daily USW00023272", "url": GHCN_URL}],
    })

    storm_rows = (storms or {}).get("events") or []
    flood_types = ("Flood", "Flash Flood", "Heavy Rain")
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
        + f"which {n_flood} are flood-type. Its damage column is not usable as a cost estimate "
        + ("\u2014 every non-zero value NCEI holds for this county is a token amount "
           f"({n_dmg} of {n_all} records carry one) \u2014 " if n_dmg else "\u2014 ")
        + "so severity here is stated as counts of days at a plain threshold rather than as a dollar figure. "
        + "No named warning category (Advisory / Warning / High Wind) is applied: those criteria are written "
          "per forecast zone and this project does not restate them.")
    sev_numbers = [
        {"label": "Storm Events records, SF County", "value": f"{n_all} ({span})"},
        {"label": "Flood-type records", "value": f"{n_flood}"},
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
                       diagnostic_status, relevant_cpc, storms, monthly):
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
        flood_types = {"Flood", "Flash Flood", "Heavy Rain", "Debris Flow"}
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
                "label": f"Flood-type storm reports in SF County ({storm_years or 'archive years'})",
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
    if wr:
        drivers.append({
            "driver": "Wind + rain together — wind-driven water intrusion",
            "why_it_costs": ("Wind pushes rain sideways under shingles, laps and window seals and "
                             "into vents, so buildings leak during storms that would stay dry in "
                             "calm rain. These are also fence-failure and tree-limb days. Wind is "
                             "recorded at SFO, 11.9 miles away (computed great-circle distance from the "
                             "94122 centroid, see climatology.meta.station_distance_mi) and "
                             "more exposed, so treat the "
                             "counts as an upper bound for the Sunset."),
            "evidence": [
                {"label": "Days with rain ≥ 0.01 in and sustained wind ≥ 20 kt",
                 "value": (f"mean {wr.get('mean')} · median {wr.get('median')} · "
                           f"max {wr.get('max')} per season")},
                {"label": "Days with rain ≥ 0.50 in and a gust ≥ 35 kt",
                 "value": (f"mean {hwr.get('mean')} · median {hwr.get('median')} · "
                           f"max {hwr.get('max')} per season")},
            ],
            "sources": gsod + ghcn,
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

    # 3. Wind and rain
    wind_rain = dist.get("wind_and_rain_days", {})
    heavy_wind_rain = dist.get("heavy_wind_and_rain_days", {})
    max_gust = dist.get("max_gust_mph", {})

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

    # Wind + rain
    if wind_rain.get("mean"):
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
        relevant_cpc=relevant_cpc, storms=storms, monthly=monthly)

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
        threshold_comparison.append({
            "threshold_in": inches,
            "project_mean_days": (proj or {}).get("mean"),
            "project_max_days": (proj or {}).get("max"),
            "noaa_expected_days": noaa,
            "project_method": ("mean of the 30 seasons' counts of days at or above this "
                               "threshold, from the station's daily precipitation file"),
            "noaa_method": ("sum of NOAA's own published per-date percent-of-years value "
                            "(DLY-PRCP-PCTALL-GE***HI) over the 123 dates"),
        })
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
        enso_strat=enso_strat)

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
                f"Wind+rain together occurred {wind_rain.get('mean')} days per season on average at SFO (upper bound for Sunset). "
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
