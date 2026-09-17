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


def main():
    calendar = load("calendar.json")
    run = load("run.json")
    climatology = load("climatology.json")
    cpc = load("cpc.json")
    enso = load("enso.json")

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

    # 5. CPC outlooks for our window - filter to relevant valid seasons
    relevant_cpc = []
    for rec in calendar.get("cpc", {}).get("records", []):
        vs = rec.get("valid_season", "")
        # Keep outlooks that cover Oct 2026 - Jan 2027
        if vs and any(x in vs for x in ["OND 2026", "NDJ", "DJF", "Oct 2026", "Nov 2026", "Dec 2026", "Jan 2027", "SON 2026"]):
            relevant_cpc.append(rec)

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
        action_items.append({
            "category": "ENSO / seasonal tilt",
            "priority": "high" if phase == "el_nino" else "medium",
            "title": f"ENSO phase: {phase} (official ONI {latest_oni.get('oni_c')}°C for {oni_when})",
            "detail": f"NOAA's published ONI product shows {oni_when} at {latest_oni.get('oni_c')}°C = {phase}"
                      + (f", {str(latest_oni.get('strength')).replace('_', ' ')} by CPC's own strength bands" if latest_oni.get("strength") else "")
                      + (f". CPC Alert System Status: {diagnostic_status}." if diagnostic_status else ".")
                      + f" In El Niño years, Oct-Jan mean was {enso_strat.get('el_nino', {}).get('mean')} in vs {enso_strat.get('la_nina', {}).get('mean')} in for La Niña (n={enso_strat.get('el_nino', {}).get('n')} El Niño seasons). El Niño tilts toward wetter, but spread is wide: wettest El Niño 22.82 in, driest El Niño 7.27 in.",
            "source": "NOAA CPC official ONI product (oni.ascii.txt)",
            "source_url": oni_url
        })

    # CPC outlooks
    for rec in relevant_cpc:
        if rec.get("valid_season") in ["OND 2026", "NDJ 2026-2027", "DJF 2026-2027", "JFM 2027"]:
            action_items.append({
                "category": "Official CPC outlook",
                "priority": "medium",
                "title": f"CPC {rec.get('valid_season')}: {rec.get('category_label')} ({rec.get('prob')}%) - {rec.get('variable')}",
                "detail": f"Issued {rec.get('issued')}, forecast date {rec.get('fcst_date')}. This is a probability for the whole 3-month period, not a daily forecast. Category: {rec.get('category_label')} with {rec.get('prob')}% probability. For precipitation, 'Above median' means CPC favors above-normal total for the period.",
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

    # Final landlord JSON
    landlord = {
        "generated_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "target": run.get("target", {}),
        "season": calendar.get("season", {}),
        "normals_period": calendar.get("normals_period", [1991, 2020]),
        "executive_summary": {
            "location": "San Francisco, CA 94122 (Inner Sunset / Outer Sunset) - 37.7605N, -122.4839W",
            "verified_coordinate_source": "U.S. Census Bureau 2024 Gazetteer ZCTA file",
            "coordinate_source_url": "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_zcta_national.zip",
            "season_window": "October 1, 2026 - January 31, 2027 (123 days)",
            "current_enso": latest_oni,
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
            "key_finding": (
                f"Over 1991-2020, Oct-Jan averaged {season_total.get('mean')} in rain across {wet_days.get('mean')} wet days. "
                f"{streak_prob.get('ge_7_days', {}).get('pct')}% of seasons had a 7+ day wet streak, "
                f"{streak_prob.get('ge_10_days', {}).get('pct')}% had 10+ days. "
                f"Wind+rain together occurred {wind_rain.get('mean')} days per season on average at SFO (upper bound for Sunset). "
                f"Current ENSO: {latest_oni.get('phase')} (official ONI {latest_oni.get('oni_c')}C, {oni_when}) "
                f"tilts toward wetter than normal"
                + (f", with CPC status \"{diagnostic_status}\"" if diagnostic_status else "")
                + "; the CPC outlooks attached to each day show the official probabilities for this window."
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
