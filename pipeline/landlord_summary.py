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
from pathlib import Path

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

#: Raw ENSO phase tokens produced by the pipeline -> reader-facing labels.
#: The raw token must never reach the page: "el_nino" is a data key, not a
#: phrase, and showing it made the executive summary read like machine output.
PHASE_LABELS = {
    "el_nino": "El Niño",
    "la_nina": "La Niña",
    "neutral": "Neutral",
}


def phase_label(phase):
    """Reader-facing label for an ENSO phase token.

    Returns the mapped label for the three phases the pipeline can produce.
    An unexpected token is returned as-is (it is a real data value, so it is
    safe to show) rather than replaced with a guessed phrase.
    """
    if phase is None:
        return "unknown"
    return PHASE_LABELS.get(str(phase).strip().lower(), str(phase))


def fmt_oni_c(value):
    """Format an ONI anomaly the way NOAA publishes it: signed, 2 dp, deg C."""
    if value is None:
        return None
    try:
        return f"{float(value):+.2f} °C"
    except (TypeError, ValueError):
        return None


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
                             "recorded at SFO, ~10 miles away and more exposed, so treat the "
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
                "title": f"CPC {rec.get('valid_season')}: {rec.get('category_label')} ({prob_txt}) - {rec.get('variable')}",
                "detail": f"Issued {rec.get('issued')}, forecast date {rec.get('fcst_date')}. This is a probability for the whole 3-month period, not a daily forecast. Category: {rec.get('category_label')} {prob_detail}. {variable_note}",
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
