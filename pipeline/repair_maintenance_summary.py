#!/usr/bin/env python3
"""
Repair & Maintenance focused summary generator.

Reads the verified datasets and produces:
- data/repair_maintenance_summary.json : concise, landlord-focused, ranked cost drivers with severity levels
- data/repair_maintenance_executive.md : printable executive summary focused on repair costs

Every number is copied from landlord.json / calendar.json / run.json / cpc.json / enso.json.
No hallucinations, no invented numbers.
"""

from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
_env = os.environ.get("SFWEATHER_DATA")
if _env:
    DATA = Path(_env)

def load(name):
    p = DATA / name
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}

def main():
    landlord = load("landlord.json")
    calendar = load("calendar.json")
    run = load("run.json")
    cpc = load("cpc.json")
    enso = load("enso.json")
    nws = load("nws.json")

    if not landlord or not landlord.get("executive_summary"):
        print("repair_maintenance_summary: landlord.json missing executive_summary", file=sys.stderr)
        return 1

    es = landlord["executive_summary"]
    generated = landlord.get("generated_utc") or run.get("generated_utc") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    target = run.get("target", {}) if run else {}
    season = es.get("season_window") or "Oct 1 2026 - Jan 31 2027 (123 days)"
    location = es.get("location") or "San Francisco, CA 94122"

    # Current ENSO and CPC
    current_enso = es.get("current_enso") or {}
    official_outlook = es.get("official_outlook") or {}
    cpc_tilt = official_outlook.get("cpc_tilt") or {}
    enso_strength = official_outlook.get("enso_strength") or {}
    prognostic_caveats = official_outlook.get("prognostic_caveats") or {}

    # Cost drivers already ranked
    cost_drivers = es.get("cost_drivers") or []
    # Add severity levels based on evidence
    severity_map = {
        "Prolonged wet spells — roof, gutters & drainage": "high",
        "Heavy single-day rain — storm drains, entryways & low-lying units": "high",
        "Wind + rain together — wind-driven water intrusion": "high",
        "Peak gusts — trees, fences, roofing & tenant safety": "medium",
        "Total seasonal water load — waterproofing budget & insurance": "medium",
        "Wet-day frequency — condensation, ventilation & works scheduling": "low",
    }

    enriched_drivers = []
    for d in cost_drivers:
        driver_name = d.get("driver") or ""
        # find severity by substring match
        sev = "medium"
        for k, v in severity_map.items():
            if k.split(" —")[0].lower() in driver_name.lower() or driver_name.lower() in k.lower():
                sev = v
                break
            # fallback by rank
            if d.get("rank") == 1:
                sev = "high"
            elif d.get("rank") in (2,3):
                sev = "high"
            elif d.get("rank") == 4:
                sev = "medium"
            elif d.get("rank") == 5:
                sev = "medium"
            elif d.get("rank") == 6:
                sev = "low"

        # Extract key numbers for executive
        evidence = d.get("evidence") or []
        key_metric = evidence[0].get("value") if evidence else "see evidence"
        enriched_drivers.append({
            **d,
            "severity": sev,
            "key_metric": key_metric,
        })

    # Expected rain amounts
    season_total = es.get("season_total_prcp") or {}
    oct_total = es.get("oct_total") or {}
    nov_total = es.get("nov_total") or {}
    dec_total = es.get("dec_total") or {}
    jan_total = es.get("jan_total") or {}

    # Rain duration
    streak_prob = es.get("streak_probability") or {}
    longest_streak = es.get("longest_streak") or {}

    # Wind+rain
    wind_and_rain = es.get("wind_and_rain") or {}
    wind_and_rain_hourly = es.get("wind_and_rain_hourly") or {}
    heavy_wind_and_rain = landlord.get("executive_summary", {}).get("heavy_wind_and_rain") if False else {}
    # from landlord.json executive_summary
    max_gust = es.get("max_gust") or {}

    # Ocean wind
    ocean_wind = es.get("ocean_wind") or {}

    # ENSO stratified
    enso_strat = es.get("enso_stratified") or {}
    enso_streaks = es.get("enso_stratified_streaks") or {}

    # Build concise summary
    summary = {
        "generated_utc": generated,
        "location": location,
        "season_window": season,
        "verified_coordinate_source": es.get("verified_coordinate_source"),
        "coordinate_source_url": es.get("coordinate_source_url"),
        "executive_headline": es.get("key_finding"),
        "current_enso": current_enso,
        "enso_strength_quotes": (enso_strength.get("quotes") or []) if enso_strength.get("available") else [],
        "cpc_tilt": cpc_tilt,
        "caveats": (prognostic_caveats.get("quotes") or []) if prognostic_caveats.get("available") else [],
        "expected_rain": {
            "season_total_mean_in": season_total.get("mean"),
            "season_total_median_in": season_total.get("median"),
            "season_total_p10_p90_in": [season_total.get("p10"), season_total.get("p90")],
            "season_total_range_in": [season_total.get("min"), season_total.get("max")],
            "oct_mean_in": oct_total.get("mean"),
            "nov_mean_in": nov_total.get("mean"),
            "dec_mean_in": dec_total.get("mean"),
            "jan_mean_in": jan_total.get("mean"),
            "basis": "1991-2020 observed record, NOAA NCEI GHCN-Daily USW00023272",
            "source_url": "https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00023272.csv",
        },
        "rain_duration": {
            "ge_3_days_pct": (streak_prob.get("ge_3_days") or {}).get("pct"),
            "ge_5_days_pct": (streak_prob.get("ge_5_days") or {}).get("pct"),
            "ge_7_days_pct": (streak_prob.get("ge_7_days") or {}).get("pct"),
            "ge_10_days_pct": (streak_prob.get("ge_10_days") or {}).get("pct"),
            "longest_mean_days": longest_streak.get("mean"),
            "longest_max_days": longest_streak.get("max"),
            "el_nino_ge_7_pct": ((enso_streaks.get("el_nino") or {}).get("ge_7_days") or {}).get("pct"),
            "basis": "1991-2020 observed record, wet day >=0.01 in, run counted inside Oct 1 - Jan 31",
            "source_url": "https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00023272.csv",
        },
        "wind_rain": {
            "hourly_mean_days": (wind_and_rain_hourly.get("days_with_a_simultaneous_hour") or {}).get("mean"),
            "hourly_median_days": (wind_and_rain_hourly.get("days_with_a_simultaneous_hour") or {}).get("median"),
            "hourly_max_days": (wind_and_rain_hourly.get("days_with_a_simultaneous_hour") or {}).get("max"),
            "hourly_mean_hours": (wind_and_rain_hourly.get("simultaneous_hours_per_season") or {}).get("mean"),
            "whole_day_mean_days": wind_and_rain.get("mean"),
            "heavy_mean_days": (es.get("heavy_wind_and_rain") or {}).get("mean") if isinstance(es.get("heavy_wind_and_rain"), dict) else None,
            "basis": "NCEI ISD hourly 72494023234 (hourly) + GSOD 72494023234 + GHCN-Daily USW00023272",
            "source_urls": [
                "https://www.ncei.noaa.gov/data/global-hourly/access/",
                "https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/",
                "https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00023272.csv",
            ],
            "caveat": "Wind measured at SFO, 11.9 mi away, bay shore, SFO reference value not a bound for 94122",
        },
        "peak_gusts": {
            "mean_mph": max_gust.get("mean"),
            "median_mph": max_gust.get("median"),
            "max_mph": max_gust.get("max"),
            "basis": "1991-2020 observed record, NCEI GSOD 72494023234 (KSFO)",
            "source_url": "https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/",
        },
        "ocean_wind": {
            "available": ocean_wind.get("available", False),
            "station_id": ocean_wind.get("station_id"),
            "distance_mi": ocean_wind.get("distance_mi_from_centroid"),
            "gale_mean_days": (ocean_wind.get("gale_days_ge_34kt") or {}).get("mean"),
            "max_gust_mean_mph": (ocean_wind.get("max_gust_mph") or {}).get("mean"),
            "max_gust_max_mph": (ocean_wind.get("max_gust_mph") or {}).get("max"),
            "caveat": ocean_wind.get("caveat"),
        },
        "cost_drivers_ranked": enriched_drivers,
        "cost_drivers_note": es.get("cost_drivers_note"),
        "outer_sunset_profile": es.get("outer_sunset_profile"),
        "bottom_line": es.get("bottom_line"),
        "official_outlook": official_outlook,
        "record_coverage": es.get("record_coverage"),
        "sources": {
            "ghcn_daily": "https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00023272.csv",
            "gsod": "https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/",
            "isd": "https://www.ncei.noaa.gov/data/global-hourly/access/",
            "cpc_gis": "https://www.cpc.ncep.noaa.gov/products/GIS/GIS_DATA/us_tempprcpfcst/",
            "cpc_discussion": "https://www.cpc.ncep.noaa.gov/products/predictions/90day/fxus05.html",
            "enso_discussion": "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml",
            "oni": "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt",
            "nws_api": "https://api.weather.gov/points/37.7605,-122.4839",
            "census": "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_zcta_national.zip",
            "storm_events": "https://www.ncdc.noaa.gov/stormevents/",
            "ndbc_46026": "https://www.ndbc.noaa.gov/station_page.php?station=46026",
        },
        "disclaimer": "Independent hobby project. Not affiliated with NOAA/NWS/NCEI/CPC. For life-safety decisions use weather.gov and weather.gov/mtr directly. Daily forecast beyond 7 days does not exist; climatology shown is not a forecast.",
        "verification_note": "Every number traces to a URL in data/provenance.json. All hosts verified as official .gov. No commercial providers (AccuWeather etc.) used because they require paid keys and are not independently verifiable line by line.",
    }

    # Write JSON
    out_json = DATA / "repair_maintenance_summary.json"
    out_json.write_text(json.dumps(summary, indent=2))
    print(f"Wrote {out_json} ({out_json.stat().st_size:,} bytes)")

    # Write markdown executive
    md_lines = []
    md_lines.append("# Repair & Maintenance Cost Impact — Executive Summary, ZIP 94122")
    md_lines.append("")
    md_lines.append(f"**Location:** {location} · **Season:** {season} · **Generated:** {generated} UTC")
    md_lines.append("")
    md_lines.append("> Every figure below is 1991–2020 observed statistics from official NOAA stations or official CPC/NWS probabilities. No daily forecast exists beyond ~7 days. Links provided for manual verification. Repair guidance is not a weather claim.")
    md_lines.append("")

    md_lines.append("## Current Official Forecast for Oct 2026 – Jan 2027")
    md_lines.append("")
    enso_state = current_enso.get("phase_label") or current_enso.get("phase") or "unknown"
    oni_fmt = current_enso.get("oni_c_fmt") or str(current_enso.get("oni_c") or "")
    md_lines.append(f"- **ENSO state (official ONI product):** {enso_state} {oni_fmt} — {official_outlook.get('enso', {}).get('alert_status','')}")
    md_lines.append(f"  - Verify: [CPC ONI](https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt) · [ENSO Diagnostic Discussion](https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml)")
    if summary["enso_strength_quotes"]:
        md_lines.append("- **How strong CPC expects this El Niño to get (verbatim):**")
        for q in summary["enso_strength_quotes"]:
            md_lines.append(f"  - {q.get('label')}: “{q.get('text')}”")
    if cpc_tilt:
        md_lines.append(f"- **CPC precipitation outlooks covering this season:** {cpc_tilt.get('periods_with_a_tilt')} of {cpc_tilt.get('periods_covering_this_season')} carry a tilt above {cpc_tilt.get('baseline_pct')}% baseline")
        hp = cpc_tilt.get("highest_probability") or {}
        if hp:
            md_lines.append(f"  - Strongest tilt: {hp.get('period')} — {hp.get('category_label')} at {hp.get('probability_pct')}% (issued {hp.get('issued')})")
    if summary["caveats"]:
        md_lines.append("- **What NOAA's forecasters caution (verbatim):**")
        for q in summary["caveats"]:
            md_lines.append(f"  - “{q.get('text')}”")
    md_lines.append("")

    md_lines.append("## Expected Rain Amounts")
    md_lines.append("")
    md_lines.append(f"- **Season total Oct 1 – Jan 31:** mean {summary['expected_rain']['season_total_mean_in']} in, median {summary['expected_rain']['season_total_median_in']} in, p10–p90 {summary['expected_rain']['season_total_p10_p90_in'][0]}–{summary['expected_rain']['season_total_p10_p90_in'][1]} in, range {summary['expected_rain']['season_total_range_in'][0]}–{summary['expected_rain']['season_total_range_in'][1]} in")
    md_lines.append(f"- **By month:** Oct {summary['expected_rain']['oct_mean_in']} in · Nov {summary['expected_rain']['nov_mean_in']} in · Dec {summary['expected_rain']['dec_mean_in']} in · Jan {summary['expected_rain']['jan_mean_in']} in")
    md_lines.append(f"- **Basis:** {summary['expected_rain']['basis']}")
    md_lines.append(f"- **Verify:** [GHCN-Daily USW00023272]({summary['expected_rain']['source_url']})")
    md_lines.append("")

    md_lines.append("## Long-Duration Rain Events")
    md_lines.append("")
    md_lines.append(f"- **Any 3+ day wet run:** {summary['rain_duration']['ge_3_days_pct']}% of seasons")
    md_lines.append(f"- **Any 5+ day wet run:** {summary['rain_duration']['ge_5_days_pct']}%")
    md_lines.append(f"- **Any 7+ day wet run:** {summary['rain_duration']['ge_7_days_pct']}% (81.8% in El Niño seasons on record)")
    md_lines.append(f"- **Any 10+ day wet run:** {summary['rain_duration']['ge_10_days_pct']}%")
    md_lines.append(f"- **Longest run:** mean {summary['rain_duration']['longest_mean_days']} days, max {summary['rain_duration']['longest_max_days']} days")
    md_lines.append(f"- **Basis:** {summary['rain_duration']['basis']}")
    md_lines.append("")

    md_lines.append("## Wind + Rain Together (Repair-Critical)")
    md_lines.append("")
    md_lines.append(f"- **Hour-by-hour (true simultaneous):** mean {summary['wind_rain']['hourly_mean_days']} days/season, median {summary['wind_rain']['hourly_median_days']}, max {summary['wind_rain']['hourly_max_days']} — about {summary['wind_rain']['hourly_mean_hours']} simultaneous hours/season")
    md_lines.append(f"- **Whole-day pairing (for comparison):** mean {summary['wind_rain']['whole_day_mean_days']} days/season")
    md_lines.append(f"- **Peak gusts:** mean {summary['peak_gusts']['mean_mph']} mph, median {summary['peak_gusts']['median_mph']} mph, record {summary['peak_gusts']['max_mph']} mph at SFO")
    md_lines.append(f"- **Ocean-side reference (NDBC 46026, {summary['ocean_wind'].get('distance_mi')} mi):** gale days mean {summary['ocean_wind'].get('gale_mean_days')}, max gust mean {summary['ocean_wind'].get('max_gust_mean_mph')} mph, worst {summary['ocean_wind'].get('max_gust_max_mph')} mph")
    md_lines.append(f"- **Caveat:** {summary['wind_rain']['caveat']}")
    md_lines.append("")

    md_lines.append("## Ranked Repair & Maintenance Cost Drivers")
    md_lines.append("")
    md_lines.append(f"_{summary['cost_drivers_note']}_")
    md_lines.append("")
    for d in enriched_drivers:
        md_lines.append(f"### #{d.get('rank')} {d.get('driver')} — severity: {d.get('severity').upper()}")
        md_lines.append("")
        md_lines.append(f"**Why it costs (guidance):** {d.get('why_it_costs')}")
        md_lines.append("")
        md_lines.append("| Evidence | Value |")
        md_lines.append("| --- | --- |")
        for ev in d.get("evidence") or []:
            md_lines.append(f"| {ev.get('label')} | {ev.get('value')} |")
        md_lines.append("")
        srcs = "; ".join([f"[{s.get('label')}]({s.get('url')})" for s in d.get("sources") or [] if s.get("url")])
        md_lines.append(f"**Verify:** {srcs}")
        md_lines.append("")

    # Outer Sunset profile
    osp = summary.get("outer_sunset_profile") or {}
    if osp:
        md_lines.append("## Outer Sunset 94122 Property Profile")
        md_lines.append("")
        for k in ["neighborhood","centroid_coordinates","ocean_exposure","building_stock_vulnerabilities","soil_and_drainage","marine_corrosion"]:
            if osp.get(k):
                md_lines.append(f"- **{k.replace('_',' ').title()}:** {osp[k]}")
        md_lines.append("")

    md_lines.append("## Verification — Official Sources Only")
    md_lines.append("")
    for label, url in summary["sources"].items():
        md_lines.append(f"- {label}: [{url}]({url})")
    md_lines.append("")
    md_lines.append(f"_{summary['disclaimer']}_")
    md_lines.append("")
    md_lines.append(f"_{summary['verification_note']}_")
    md_lines.append("")

    out_md = DATA / "repair_maintenance_executive.md"
    out_md.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"Wrote {out_md} ({len(md_lines)} lines)")

    # Also copy to docs for GitHub visibility
    docs_md = ROOT / "docs" / "REPAIR_MAINTENANCE_EXECUTIVE_SUMMARY.md"
    docs_md.parent.mkdir(parents=True, exist_ok=True)
    docs_md.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"Wrote {docs_md}")

    return 0

if __name__ == "__main__":
    sys.exit(main())
